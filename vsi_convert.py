#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VSI CONVERT — conversão segura de .webm para .mp4 com preservação de proveniência
================================================================================
Estratégia
  1) REMUX (troca de container, sem reencodificar):  -c copy -map ... -map_metadata 0
     Os pacotes de vídeo/áudio são idênticos aos do WebM; o script PROVA isso comparando o
     SHA-256 dos fluxos elementares (origem x destino). Selos invisíveis (DCT/LSB/marca
     d'água) vivem nos pixels e, portanto, permanecem intactos.
  2) TRANSCODIFICAÇÃO DE SEGURANÇA, só quando o remux não é possível:
       - codec não aceito no MP4 (VP8, Vorbis...)          -> H.264 CRF 12 (quase sem perda) + AAC 320k
       - canal ALPHA (transparência)                       -> Apple ProRes 4444 (yuva444p10le) em
         .mov/QuickTime (H.264 simples preencheria o fundo de preto). Alternativa: HEVC com alpha
         (hevc_videotoolbox, só macOS) com --alpha-codec hevc.
       - legendas WebVTT                                   -> mov_text
  3) PROVENIÊNCIA
       - SHA-256 do .webm ANTES do processo;
       - sidecar  <saida>.provenance.json  com tags/metadados, chave QR do selo (VSI_QR), pacote XMP,
         detecção de C2PA/JUMBF e (opcional) manifesto C2PA/VSI importado (--manifest);
       - os metadados são reinjetados no MP4 (-movflags +use_metadata_tags): vsi_source_sha256,
         vsi_qr, vsi_provenance_sha256 e as tags originais;
       - manifesto ASSINADO <saida>.derivation.json atestando "este MP4 é derivado direto do WebM
         de SHA-256 X" (HMAC-SHA256 com --sign-key ou Ed25519 com --ed25519-key, se 'cryptography').

Requisitos: Python 3.8+ e ffmpeg/ffprobe no PATH. Opcional: cryptography (Ed25519), vsi_stego.py
na mesma pasta (verifica o selo invisível antes e depois).

Comandos FFmpeg equivalentes (o script monta exatamente estes):
  # remux
  ffmpeg -i in.webm -map 0:v -map 0:a? -map 0:s? -map_metadata 0 -map_chapters 0 \\
         -c copy -c:s mov_text -movflags +faststart+use_metadata_tags out.mp4
  # transcodificação de segurança (sem alpha)
  ffmpeg -i in.webm -map 0:v -map 0:a? -map_metadata 0 -c:v libx264 -crf 12 -preset slow \\
         -pix_fmt yuv420p -c:a aac -b:a 320k -movflags +faststart+use_metadata_tags out.mp4
  # com alpha (QuickTime/ProRes 4444)
  ffmpeg -c:v libvpx-vp9 -i in.webm -map 0:v -map 0:a? -map_metadata 0 -c:v prores_ks \\
         -profile:v 4444 -pix_fmt yuva444p10le -vendor apl0 -c:a pcm_s24le out.mov

Uso:
  python vsi_convert.py convert video.webm video.mp4 --sign-key "segredo" [--manifest video_c2pa.json]
  python vsi_convert.py verify  video.mp4 --source video.webm --sign-key "segredo"
  python vsi_convert.py selftest
"""
import argparse
import base64
import hashlib
import hmac
import json
import mmap
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

MP4_VIDEO_OK = {"h264", "hevc", "av1", "vp9", "mpeg4", "mpeg2video"}
MP4_AUDIO_OK = {"aac", "mp3", "opus", "flac", "ac3", "eac3", "alac"}


# ----------------------------------------------------------------------------
# utilidades
# ----------------------------------------------------------------------------

def need_tools():
    for t in ("ffmpeg", "ffprobe"):
        if not shutil.which(t):
            sys.exit(f"{t} não encontrado no PATH (https://ffmpeg.org).")


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def run(cmd, check=True):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[-1200:] or "ffmpeg falhou")
    return r


def probe(path):
    r = run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-show_chapters", "-of", "json", path])
    return json.loads(r.stdout)


def has_alpha(stream):
    pf = stream.get("pix_fmt", "")
    tags = {k.lower(): str(v) for k, v in (stream.get("tags") or {}).items()}
    # VP8/VP9 com alpha no WebM: pix_fmt yuv420p + tag alpha_mode=1 (alpha em BlockAdditional)
    return pf.startswith(("yuva", "rgba", "bgra", "argb", "abgr", "gbrap", "ya")) or tags.get("alpha_mode") == "1"


def encoder_exists(name):
    return name in run(["ffmpeg", "-hide_banner", "-encoders"], check=False).stdout


def stream_hash(path, spec):
    """SHA-256 do fluxo elementar (pacotes copiados), p.ex. spec='v:0' ou 'a:0'."""
    r = run(["ffmpeg", "-v", "error", "-i", path, "-map", f"0:{spec}", "-c", "copy",
             "-f", "hash", "-hash", "sha256", "-"], check=False)
    m = re.search(r"SHA256=([0-9a-f]{64})", r.stdout)
    return m.group(1) if m else None


# ----------------------------------------------------------------------------
# extração de proveniência (tags, VSI_QR, XMP, C2PA)
# ----------------------------------------------------------------------------

def extract_provenance(path, info):
    tags = dict(info.get("format", {}).get("tags") or {})
    streams_tags = [{"index": s["index"], "codec_type": s.get("codec_type"), "tags": s.get("tags") or {}}
                    for s in info.get("streams", [])]
    flat = {k.upper(): v for k, v in tags.items()}
    qr = flat.get("VSI_QR")
    xmp, c2pa = None, False
    size = os.path.getsize(path)
    with open(path, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        if not qr:                               # QR gravado pelo app como etiqueta Matroska no fim do arquivo
            i = mm.rfind(b"VSI1:")
            if i >= 0:
                m = re.match(rb"VSI1:[A-Za-z0-9+/=]+", mm[i:i + 4096])
                qr = m.group(0).decode() if m else None
        a = mm.find(b"<?xpacket begin")
        if a >= 0:
            b = mm.find(b"<?xpacket end", a)
            if b >= 0:
                xmp = mm[a:min(b + 40, a + 1_000_000)].decode("utf-8", "replace")
        c2pa = mm.find(b"c2pa") >= 0 and (mm.find(b"jumb") >= 0)
    return {"format_tags": tags, "stream_tags": streams_tags, "vsi_qr": qr, "xmp_packet": xmp,
            "c2pa_jumbf_detected": bool(c2pa), "chapters": info.get("chapters", []), "source_size": size}


# ----------------------------------------------------------------------------
# assinatura do manifesto de derivação
# ----------------------------------------------------------------------------

def canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sign_manifest(body, sign_key=None, ed25519_key=None):
    if ed25519_key:
        try:
            from cryptography.hazmat.primitives import serialization
            priv = serialization.load_pem_private_key(open(ed25519_key, "rb").read(), None)
            pub = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
            return {"alg": "Ed25519", "public_key": base64.b64encode(pub).decode(),
                    "value": base64.b64encode(priv.sign(canon(body))).decode()}
        except Exception as e:                    # noqa: BLE001
            sys.exit(f"falha ao assinar com Ed25519: {e}")
    key = sign_key or os.environ.get("VSI_SIGN_KEY")
    if not key:
        return {"alg": "none", "value": None, "note": "sem chave: manifesto NÃO assinado"}
    return {"alg": "HMAC-SHA256", "key_id": hashlib.sha256(key.encode()).hexdigest()[:12],
            "value": hmac.new(key.encode(), canon(body), hashlib.sha256).hexdigest()}


def check_signature(manifest, sign_key=None):
    sig, body = manifest.get("signature") or {}, {k: v for k, v in manifest.items() if k != "signature"}
    if sig.get("alg") == "HMAC-SHA256":
        key = sign_key or os.environ.get("VSI_SIGN_KEY")
        if not key:
            return None, "informe --sign-key para validar a assinatura HMAC"
        ok = hmac.compare_digest(sig["value"], hmac.new(key.encode(), canon(body), hashlib.sha256).hexdigest())
        return ok, "HMAC-SHA256"
    if sig.get("alg") == "Ed25519":
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
            Ed25519PublicKey.from_public_bytes(base64.b64decode(sig["public_key"])).verify(
                base64.b64decode(sig["value"]), canon(body))
            return True, "Ed25519"
        except Exception:                          # noqa: BLE001
            return False, "Ed25519"
    return None, "manifesto sem assinatura"


# ----------------------------------------------------------------------------
# conversão
# ----------------------------------------------------------------------------

def plan(info, force_transcode=False, alpha_codec="prores"):
    vs = [s for s in info["streams"] if s["codec_type"] == "video" and s.get("disposition", {}).get("attached_pic", 0) == 0]
    au = [s for s in info["streams"] if s["codec_type"] == "audio"]
    su = [s for s in info["streams"] if s["codec_type"] == "subtitle"]
    if not vs:
        sys.exit("o arquivo não tem fluxo de vídeo")
    alpha = any(has_alpha(v) for v in vs)
    reasons = []
    if alpha:
        reasons.append("canal alpha (transparência)")
    for v in vs:
        if v["codec_name"] not in MP4_VIDEO_OK:
            reasons.append(f"vídeo {v['codec_name']} não é aceito no MP4")
    for a in au:
        if a["codec_name"] not in MP4_AUDIO_OK:
            reasons.append(f"áudio {a['codec_name']} não é aceito no MP4")
    if force_transcode:
        reasons.append("--force-transcode")
    mode = "transcode" if reasons else "remux"
    if alpha:
        container = ".mov"
    else:
        container = ".mp4"
    return {"mode": mode, "reasons": reasons, "alpha": alpha, "container": container,
            "video": vs, "audio": au, "subs": su, "alpha_codec": alpha_codec}


def build_cmd(src, dst, pl, meta_args, vp9_alpha_decoder=False):
    cmd = ["ffmpeg", "-y", "-v", "error"]
    if pl["alpha"] and any(v["codec_name"] == "vp9" for v in pl["video"]):
        cmd += ["-c:v", "libvpx-vp9"]              # decodificador que lê o alpha do WebM
    elif pl["alpha"] and any(v["codec_name"] == "vp8" for v in pl["video"]):
        cmd += ["-c:v", "libvpx"]
    cmd += ["-i", src, "-map", "0:v", "-map", "0:a?", "-map", "0:s?", "-map_metadata", "0", "-map_chapters", "0"]
    if pl["mode"] == "remux":
        cmd += ["-c", "copy"]
    else:
        if pl["alpha"]:
            if pl["alpha_codec"] == "hevc" and encoder_exists("hevc_videotoolbox"):
                cmd += ["-c:v", "hevc_videotoolbox", "-alpha_quality", "1", "-q:v", "90", "-pix_fmt", "bgra", "-tag:v", "hvc1"]
            else:
                cmd += ["-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", "-vendor", "apl0",
                        "-qscale:v", "4", "-alpha_bits", "16"]
            cmd += ["-c:a", "pcm_s24le"]            # áudio sem perda no QuickTime
        else:
            cmd += ["-c:v", "libx264", "-crf", "12", "-preset", "slow", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "320k"]
            if any(a["codec_name"] in MP4_AUDIO_OK for a in pl["audio"]) and all(a["codec_name"] in MP4_AUDIO_OK for a in pl["audio"]):
                cmd[cmd.index("-c:a") + 1] = "copy"
                del cmd[cmd.index("-b:a"):cmd.index("-b:a") + 2]
    if pl["subs"]:
        cmd += ["-c:s", "mov_text"]
    cmd += ["-movflags", "+faststart+use_metadata_tags", *meta_args, dst]
    return cmd


def convert(src, dst=None, sign_key=None, ed25519_key=None, force_transcode=False, alpha_codec="prores",
            manifest_path=None, seal=None, quality_report=False, verbose=True):
    """Converte WebM -> MP4 (ou MOV com alpha), gera sidecar e manifesto assinado."""
    need_tools()
    t0 = time.time()
    info = probe(src)
    pl = plan(info, force_transcode, alpha_codec)
    dst = dst or os.path.splitext(src)[0] + pl["container"]
    if pl["alpha"] and not dst.lower().endswith(".mov"):
        dst = os.path.splitext(dst)[0] + ".mov"
        if verbose:
            print(f"  aviso: transparência exige QuickTime/ProRes; saída renomeada para {dst}")

    # 1) hash do original ANTES de qualquer processo
    src_sha = sha256_file(src)
    # 2) proveniência -> sidecar
    prov = extract_provenance(src, info)
    if manifest_path and os.path.exists(manifest_path):
        prov["imported_manifest"] = json.load(open(manifest_path, encoding="utf-8"))
    prov["source"] = {"file": os.path.basename(src), "sha256": src_sha, "container": info["format"].get("format_name"),
                      "streams": [{k: s.get(k) for k in ("index", "codec_type", "codec_name", "width", "height", "pix_fmt", "sample_rate", "channels")} for s in info["streams"]]}
    side = dst + ".provenance.json"
    json.dump(prov, open(side, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    side_sha = sha256_file(side)

    # 3) metadados a reinjetar no MP4
    meta = ["-metadata", f"vsi_source_sha256={src_sha}", "-metadata", f"vsi_provenance_sha256={side_sha}",
            "-metadata", "vsi_derivation=derived-from-webm"]
    if prov["vsi_qr"]:
        meta += ["-metadata", f"vsi_qr={prov['vsi_qr']}"]
    if prov["xmp_packet"] and len(prov["xmp_packet"]) < 30000:
        meta += ["-metadata", "vsi_xmp_b64=" + base64.b64encode(prov["xmp_packet"].encode()).decode()]
    if prov.get("imported_manifest"):
        meta += ["-metadata", "vsi_c2pa_sig=" + str(prov["imported_manifest"].get("signature", ""))[:120]]

    # 4) conversão (remux; se falhar, transcodificação de segurança)
    cmd = build_cmd(src, dst, pl, meta)
    if verbose:
        print(f"  modo: {pl['mode'].upper()}" + (f"  motivo: {'; '.join(pl['reasons'])}" if pl["reasons"] else ""))
    r = run(cmd, check=False)
    if r.returncode != 0 and pl["mode"] == "remux":
        pl.update(mode="transcode", reasons=["remux recusado pelo MP4: " + r.stderr.strip().splitlines()[-1][:160]])
        cmd = build_cmd(src, dst, pl, meta)
        if verbose:
            print("  remux falhou -> transcodificação de segurança")
        r = run(cmd, check=False)
    if r.returncode != 0:
        sys.exit("conversão falhou:\n" + r.stderr[-1500:])

    # 5) provas de derivação
    out_info = probe(dst)
    proof = {"mode": pl["mode"], "reasons": pl["reasons"], "ffmpeg_command": cmd}
    if pl["mode"] == "remux":
        eq = []
        for kind, n in (("v", len([s for s in info["streams"] if s["codec_type"] == "video"])),
                        ("a", len([s for s in info["streams"] if s["codec_type"] == "audio"]))):
            for i in range(n):
                a, b = stream_hash(src, f"{kind}:{i}"), stream_hash(dst, f"{kind}:{i}")
                eq.append({"stream": f"{kind}:{i}", "source_sha256": a, "derived_sha256": b, "identical": bool(a and a == b)})
        proof["elementary_streams"] = eq
        proof["lossless_remux"] = all(e["identical"] for e in eq)
    elif quality_report:
        num, den = (pl["video"][0].get("r_frame_rate") or "25/1").split("/")
        fps = int(num) / max(int(den), 1)   # alinha os quadros por índice (evita medir quadros trocados)
        q = run(["ffmpeg", "-i", dst, "-i", src, "-lavfi",
                 f"[0:v]setpts=N/({fps}*TB)[a];[1:v]setpts=N/({fps}*TB)[b];[a][b]psnr", "-f", "null", "-"], check=False)
        m = re.search(r"average:([\d.inf]+)", q.stderr)
        proof["psnr_db"] = m.group(1) if m else None
    seal_res = None
    if seal:
        try:
            import vsi_stego as vs
            seal_res = {}
            for label, p in (("source", src), ("derived", dst)):
                r_ = vs.verify(p, seal["text"], seal["key"], "dct", robust=seal.get("robust", "auto"))
                seal_res[label] = {"present": r_["present"], "match": r_["match"], "mode": r_.get("mode")}
        except Exception as e:                    # noqa: BLE001
            seal_res = {"error": str(e)}
    body = {
        "format": "VSI-Derivation/1",
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "statement": "O arquivo derivado é uma conversão direta e autêntica do arquivo de origem abaixo.",
        "source": {"name": os.path.basename(src), "size": os.path.getsize(src), "sha256": src_sha},
        "derived": {"name": os.path.basename(dst), "size": os.path.getsize(dst), "sha256": sha256_file(dst),
                    "container": out_info["format"].get("format_name"),
                    "streams": [{k: s.get(k) for k in ("codec_type", "codec_name", "width", "height", "pix_fmt")} for s in out_info["streams"]]},
        "provenance_sidecar": {"name": os.path.basename(side), "sha256": side_sha},
        "proof": proof,
        "seal_check": seal_res,
        "tool": "vsi_convert.py",
    }
    body["signature"] = sign_manifest(body, sign_key, ed25519_key)
    man = dst + ".derivation.json"
    json.dump(body, open(man, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    if verbose:
        print(f"  saída: {dst}\n  sidecar: {side}\n  manifesto: {man}   ({time.time()-t0:.1f}s)")
    return {"output": dst, "sidecar": side, "manifest": man, "mode": pl["mode"], "body": body}


def verify_derivation(derived, source=None, sign_key=None):
    """Valida o manifesto: hash do derivado, assinatura, (opcional) hash da origem e fluxos idênticos."""
    man = json.load(open(derived + ".derivation.json", encoding="utf-8"))
    ok_sig, alg = check_signature(man, sign_key)
    res = {"signature": {"valid": ok_sig, "alg": alg},
           "derived_hash_matches": sha256_file(derived) == man["derived"]["sha256"]}
    if source:
        res["source_hash_matches"] = sha256_file(source) == man["source"]["sha256"]
        if man["proof"]["mode"] == "remux":
            res["streams_identical"] = all(stream_hash(source, e["stream"]) == stream_hash(derived, e["stream"])
                                           for e in man["proof"]["elementary_streams"])
    res["authentic_derivative"] = bool(res["derived_hash_matches"] and ok_sig is not False and res.get("source_hash_matches", True)
                                       and res.get("streams_identical", True))
    return res


# ----------------------------------------------------------------------------
# autoteste
# ----------------------------------------------------------------------------

def selftest():
    need_tools()
    d = tempfile.mkdtemp(prefix="vsi_conv_")
    key, SELO = "chave-demo", "SELO_AUTENTICIDADE_2026_ID9982"
    try:
        import vsi_stego as vs
    except ImportError:
        vs = None
    print("== 1) WebM VP9+Opus (selo DCT, QR nos metadados) -> MP4 por REMUX ==")
    base = os.path.join(d, "base.mp4")
    if vs:
        vs.make_demo_video(base, seconds=3, size=(640, 360))
        sel = os.path.join(d, "selado.mp4")
        vs.encode(base, sel, SELO, SELO, "dct", "x264", 16, None, False, "std")
    else:
        sel = base
    webm = os.path.join(d, "video.webm")
    run(["ffmpeg", "-y", "-v", "error", "-i", sel, "-c:v", "libvpx-vp9", "-crf", "20", "-b:v", "0", "-c:a", "libopus",
         "-metadata", "title=Entrevista", "-metadata", "author=Marina Costa", "-metadata", "VSI_QR=VSI1:eyJ2IjoiYWJjIn0=", webm])
    r = convert(webm, os.path.join(d, "video.mp4"), sign_key=key, seal={"text": SELO, "key": SELO, "robust": "std"} if vs else None)
    print("  remux idêntico:", r["body"]["proof"].get("lossless_remux"), "| selo origem/derivado:", r["body"]["seal_check"])
    print("  verificação:", verify_derivation(r["output"], webm, key))
    print("  tags no MP4:", {k: v for k, v in probe(r["output"])["format"].get("tags", {}).items() if k.startswith(("vsi_", "title", "author"))})
    print("== 2) Adulteração do MP4 derivado deve ser detectada ==")
    with open(r["output"], "ab") as f:
        f.write(b"\0")
    print("  verificação:", verify_derivation(r["output"], webm, key)["authentic_derivative"])
    print("== 3) VP8 + Vorbis (não cabem no MP4) -> TRANSCODIFICAÇÃO H.264 CRF 12 ==")
    vp8 = os.path.join(d, "vp8.webm")
    run(["ffmpeg", "-y", "-v", "error", "-i", base, "-c:v", "libvpx", "-b:v", "2M", "-c:a", "libvorbis", vp8])
    r = convert(vp8, os.path.join(d, "vp8.mp4"), sign_key=key, quality_report=True)
    print("  modo:", r["mode"], "| PSNR:", r["body"]["proof"].get("psnr_db"), "| verificação:", verify_derivation(r["output"], vp8, key)["authentic_derivative"])
    print("== 4) WebM VP9 com ALPHA -> ProRes 4444 em .mov ==")
    al = os.path.join(d, "alpha.webm")
    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=red@0.0:s=320x180:d=2,format=yuva420p,drawbox=x=40:y=40:w=120:h=80:color=blue@0.8:t=fill",
         "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-auto-alt-ref", "0", al])
    r = convert(al, os.path.join(d, "alpha.mp4"), sign_key=key)
    out = probe(r["output"])
    vs_ = [s for s in out["streams"] if s["codec_type"] == "video"][0]
    print("  saída:", os.path.basename(r["output"]), "| codec:", vs_["codec_name"], "| pix_fmt:", vs_["pix_fmt"], "| verificação:", verify_derivation(r["output"], al, key)["authentic_derivative"])
    print(f"\nArquivos em: {d}")


def main():
    ap = argparse.ArgumentParser(description="Conversão segura WebM -> MP4 com proveniência")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("convert")
    c.add_argument("input"); c.add_argument("output", nargs="?")
    c.add_argument("--sign-key"); c.add_argument("--ed25519-key", help="chave privada PEM Ed25519")
    c.add_argument("--force-transcode", action="store_true")
    c.add_argument("--alpha-codec", choices=["prores", "hevc"], default="prores")
    c.add_argument("--manifest", help="manifesto C2PA/VSI (.json) a anexar ao sidecar")
    c.add_argument("--seal-text"); c.add_argument("--seal-key")
    c.add_argument("--seal-robust", choices=["auto", "std", "resize", "crop"], default="auto")
    c.add_argument("--quality-report", action="store_true")
    v = sub.add_parser("verify")
    v.add_argument("derived"); v.add_argument("--source"); v.add_argument("--sign-key")
    sub.add_parser("selftest")
    a = ap.parse_args()
    if a.cmd == "convert":
        seal = {"text": a.seal_text, "key": a.seal_key or a.seal_text, "robust": a.seal_robust} if a.seal_text else None
        convert(a.input, a.output, a.sign_key, a.ed25519_key, a.force_transcode, a.alpha_codec, a.manifest, seal, a.quality_report)
    elif a.cmd == "verify":
        r = verify_derivation(a.derived, a.source, a.sign_key)
        print(json.dumps(r, indent=2, ensure_ascii=False))
        sys.exit(0 if r["authentic_derivative"] else 1)
    else:
        selftest()


if __name__ == "__main__":
    main()
