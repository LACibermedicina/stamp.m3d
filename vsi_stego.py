#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VSI STEGO — selo/marca d'água invisível em vídeo (esteganografia)
=================================================================
Dois métodos de injeção, com ENCODER e DECODER:

  lsb  Least Significant Bit nos pixels (BGR). Muito rápido e invisível, mas
       só sobrevive a codecs SEM PERDA (FFV1 / x264 lossless). Qualquer
       recompressão com perda (H.264/H.265 normal) destrói os bits.

  dct  Transformada Discreta de Cosseno 8x8 no canal de luminância (Y).
       Cada bit é codificado pelo SINAL da diferença entre dois coeficientes
       de média frequência (método Koch-Zhao). O padrão é espalhado por todos
       os blocos de todos os quadros (posições, pares e bits embaralhados pela
       chave secreta) e o decoder faz votação por maioria ponderada. Sobrevive
       a recompressão H.264/H.265 e a pequenas mudanças de brilho/contraste.

Payload:  b'VS' | tamanho(2 bytes) | texto UTF-8 | CRC32  -> bits.
Apenas quem tem a CHAVE sabe ONDE olhar; sem ela o decoder não acha o selo.
O método DCT usa um PRNG portátil e é compatível com o verificador do app web.

Requisitos:  pip install opencv-python numpy      +  ffmpeg no PATH
Áudio, FPS e resolução: o vídeo é processado quadro a quadro com OpenCV, enviado
por pipe ao ffmpeg e o áudio ORIGINAL é copiado (sem recodificar) para o arquivo
final. Rotação/metadados de exibição do contêiner não são tratados.

Uso rápido
----------
  python vsi_stego.py encode video_original.mp4 saida.mkv --text SELO_AUTENTICIDADE_2026_ID9982 --method lsb
  python vsi_stego.py decode saida.mkv --key SELO_AUTENTICIDADE_2026_ID9982 --method lsb
  python vsi_stego.py encode video_original.mp4 saida.mp4 --text SELO_AUTENTICIDADE_2026_ID9982 --method dct
  python vsi_stego.py verify saida.mp4 --text SELO_AUTENTICIDADE_2026_ID9982 --method dct
  python vsi_stego.py selftest          # demonstração completa com vídeo sintético

Codec de saída recomendado
--------------------------
  LSB  -> --codec ffv1          (contêiner .mkv, lossless real; ou .avi com HuffYUV)
          --codec x264-lossless (libx264rgb -crf 0, .mkv; menor, também sem perda)
          NÃO use yuv420p com perda: a conversão RGB->YUV420 já apaga o LSB.
  DCT  -> --codec x264 --crf 14..18 (.mp4, yuv420p, preset slow)  [padrão]
          --codec x265 --crf 16..20 (.mp4/.mkv)
          Quanto menor o CRF, maior a margem de segurança do selo.
          Aumente --strength (ex.: 24-32) se o vídeo será recomprimido com CRF > 28.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zlib

import cv2
import numpy as np

MAGIC = b"VS"
BLOCK = 8
# pares de coeficientes de média frequência (u,v) comparados entre si
PAIRS = [((2, 3), (3, 2)), ((1, 4), (4, 1)), ((3, 3), (2, 4)), ((2, 2), (1, 3))]

# ----------------------------------------------------------------------------
# Payload <-> bits
# ----------------------------------------------------------------------------

def build_bits(text: str) -> np.ndarray:
    data = text.encode("utf-8")
    if len(data) > 65535:
        raise ValueError("texto do selo muito longo")
    frame = MAGIC + len(data).to_bytes(2, "big") + data
    frame += zlib.crc32(frame).to_bytes(4, "big")
    return np.unpackbits(np.frombuffer(frame, dtype=np.uint8))


def parse_bits(bits: np.ndarray):
    """Retorna texto se MAGIC + CRC32 conferem; senão None."""
    raw = np.packbits(bits.astype(np.uint8)).tobytes()
    if raw[:2] != MAGIC:
        return None
    n = int.from_bytes(raw[2:4], "big")
    if 4 + n + 4 > len(raw):
        return None
    body, crc = raw[: 4 + n], raw[4 + n : 8 + n]
    if zlib.crc32(body).to_bytes(4, "big") != crc:
        return None
    try:
        return body[4:].decode("utf-8")
    except UnicodeDecodeError:
        return None


def rng_from_key(key: str, salt: str = "") -> np.random.Generator:
    seed = int.from_bytes(hashlib.sha256((salt + key).encode()).digest()[:8], "big")
    return np.random.default_rng(seed)


DEFAULT_STRENGTH = {"std": 24.0, "resize": 40.0, "crop": 28.0}
MAX_TEXT_BYTES = 255                      # limite do texto do selo
MAX_BITS = (8 + MAX_TEXT_BYTES) * 8       # cabeçalho(4) + texto + CRC(4)


# ----------------------------------------------------------------------------
# Método LSB (sem perda)
# ----------------------------------------------------------------------------

class LSB:
    REPS = 15  # cada bit é gravado em 15 posições embaralhadas (votação por maioria)

    def __init__(self, key, shape):
        size = shape[0] * shape[1] * shape[2]
        self.pos = rng_from_key(key, "lsb").permutation(size)[: self.REPS * MAX_BITS]  # posições secretas

    def embed(self, frame, bits):
        n = len(bits) * self.REPS
        if n > len(self.pos):
            raise ValueError("vídeo pequeno demais para este payload")
        flat = frame.reshape(-1)  # view do frame contíguo (modifica no lugar)
        p = self.pos[:n]
        flat[p] = (flat[p] & 0xFE) | np.tile(bits, self.REPS)
        return frame

    def raw(self, frame):
        return (frame.reshape(-1)[self.pos] & 1).astype(np.float32)

    def candidates(self, raw):
        """Gera (nbits, soft[-1..1]) para cada tamanho de texto possível."""
        for nbytes in range(1, MAX_TEXT_BYTES + 1):
            nb = (8 + nbytes) * 8
            if nb * self.REPS > len(raw):
                return
            yield nb, raw[: nb * self.REPS].reshape(self.REPS, nb).mean(axis=0) * 2 - 1


# ----------------------------------------------------------------------------
# Método DCT (resiste a recompressão)
# ----------------------------------------------------------------------------

class Mulberry32:
    """PRNG de 32 bits idêntico ao usado no JavaScript do app web."""
    M = 0xFFFFFFFF

    def __init__(self, seed):
        self.a = seed & self.M

    def next(self):
        M = self.M
        self.a = (self.a + 0x6D2B79F5) & M
        a = self.a
        t = ((a ^ (a >> 15)) * (a | 1)) & M
        t = ((t + (((t ^ (t >> 7)) * (t | 61)) & M)) & M) ^ t
        return ((t ^ (t >> 14)) & M) / 4294967296.0


def _dct_matrix(n=BLOCK):
    m = np.zeros((n, n), np.float32)
    for u in range(n):
        a = np.sqrt(1.0 / n) if u == 0 else np.sqrt(2.0 / n)
        for x in range(n):
            m[u, x] = a * np.cos((2 * x + 1) * u * np.pi / (2 * n))
    return m


D = _dct_matrix()


class DCT:
    """Esteganografia DCT com três modos de robustez (escolhidos NA HORA de selar):

      std     recompressão e troca de formato (H.264/H.265/VP9/MP4/MKV/WebM), mesma resolução.
      resize  + redimensionamento: o selo vive numa grade normalizada de 384x216
              (qualquer escala/proporção do quadro é reamostrada para ela antes de ler).
      crop    + corte: o padrão é repetido em ladrilhos de 24x24 blocos com chips de
              sincronismo; o decoder acha a fase do ladrilho. Corte com deslocamento
              múltiplo de 8 px e escala 1:1. (Corte + redimensionamento juntos: não suportado.)
    """
    CW, CH, TILE, SYNC = 384, 216, 24, 128

    def __init__(self, key, shape, strength, mode="std"):
        self.mode, self.delta = mode, float(strength)
        H, W = shape[0], shape[1]
        fh, fw = (self.CH, self.CW) if mode == "resize" else (H, W)
        self.h, self.w = fh // BLOCK * BLOCK, fw // BLOCK * BLOCK
        self.nbx, self.nby = self.w // BLOCK, self.h // BLOCK
        self.nb = self.nbx * self.nby
        # PRNG portátil (Mulberry32 + Fisher-Yates): o app web usa o MESMO algoritmo.
        rng = Mulberry32(int(hashlib.sha256(("dct" + key).encode()).hexdigest()[:8], 16))
        n = self.TILE ** 2 if mode == "crop" else self.nb
        perm = list(range(n))
        for i in range(n - 1, 0, -1):
            j = int(rng.next() * (i + 1))
            perm[i], perm[j] = perm[j], perm[i]
        pair = np.array([int(rng.next() * len(PAIRS)) for _ in range(n)])
        self.ar = np.arange(self.nb)
        if mode == "crop":
            self.rank = np.empty(n, np.int64)
            self.rank[np.array(perm)] = np.arange(n)
            self.tsign = np.array([1.0 if rng.next() < 0.5 else -1.0 for _ in range(n)], np.float32)
            self.tpair = pair
            self.by, self.bx = np.divmod(self.ar, self.nbx)
            self.set_phase(0, 0)
        else:
            self.perm, self.pair_of_block = np.array(perm, np.int64), pair
            self.masks = [self.pair_of_block == p for p in range(len(PAIRS))]

    def set_phase(self, px, py):
        T = self.TILE
        self.pos = (self.bx + px) % T + ((self.by + py) % T) * T
        self.pair_of_block = self.tpair[self.pos]
        self.rk = self.rank[self.pos]
        self.masks = [self.pair_of_block == p for p in range(len(PAIRS))]

    def _blocks(self, y):
        b = y[: self.h, : self.w].reshape(self.nby, BLOCK, self.nbx, BLOCK).transpose(0, 2, 1, 3)
        return b.reshape(-1, BLOCK, BLOCK)

    def _unblocks(self, b, y_full):
        out = b.reshape(self.nby, self.nbx, BLOCK, BLOCK).transpose(0, 2, 1, 3)
        y_full[: self.h, : self.w] = out.reshape(self.h, self.w)
        return y_full

    def _embed_plane(self, y, bits):
        nbits = len(bits)
        if self.mode == "crop":
            if nbits > self.TILE ** 2 - self.SYNC:
                raise ValueError("texto grande demais para o modo crop (máx. ~55 bytes)")
            data = self.rk >= self.SYNC
            sign = np.where(data, np.where(bits[(self.rk - self.SYNC) % nbits] == 1, 1.0, -1.0), self.tsign[self.pos])
        else:
            if self.nb < nbits * 2:
                raise ValueError("resolução pequena demais para este payload")
            sign = np.where(bits[self.perm % nbits] == 1, 1.0, -1.0)
        sign = sign.astype(np.float32)
        C = D @ self._blocks(y) @ D.T  # DCT 2D de todos os blocos de uma vez
        for p, ((u1, v1), (u2, v2)) in enumerate(PAIRS):
            m = self.masks[p]
            c1, c2, s = C[m, u1, v1], C[m, u2, v2], sign[m]
            bad = s * (c1 - c2) < self.delta   # só altera onde a margem é insuficiente
            mid = (c1 + c2) / 2
            C[m, u1, v1] = np.where(bad, mid + s * self.delta / 2, c1)
            C[m, u2, v2] = np.where(bad, mid - s * self.delta / 2, c2)
        return self._unblocks(D.T @ C @ D, y.copy())

    def embed(self, frame, bits):
        ycc = cv2.cvtColor(frame, cv2.COLOR_BGR2YCrCb)
        y = ycc[:, :, 0].astype(np.float32)
        if self.mode == "resize":
            yc = cv2.resize(y, (self.CW, self.CH), interpolation=cv2.INTER_AREA)
            d = self._embed_plane(yc, bits) - yc
            y = y + cv2.resize(d, (y.shape[1], y.shape[0]), interpolation=cv2.INTER_LINEAR)
        else:
            y = self._embed_plane(y, bits)
        ycc[:, :, 0] = np.clip(y, 0, 255).round().astype(np.uint8)
        return cv2.cvtColor(ycc, cv2.COLOR_YCrCb2BGR)

    def soft4(self, frame):
        """Evidência (-1..+1) de cada bloco para cada um dos 4 pares: (nb, 4)."""
        y = cv2.cvtColor(frame, cv2.COLOR_BGR2YCrCb)[:, :, 0].astype(np.float32)
        if self.mode == "resize":
            y = cv2.resize(y, (self.CW, self.CH), interpolation=cv2.INTER_AREA)
        C = D @ self._blocks(y) @ D.T
        diff = np.stack([C[:, u1, v1] - C[:, u2, v2] for (u1, v1), (u2, v2) in PAIRS], axis=1)
        return np.clip(diff / self.delta, -1, 1)

    def candidates(self, S):
        """S: evidência por bloco (já escolhido o par de cada bloco)."""
        for nbytes in range(1, MAX_TEXT_BYTES + 1):
            nbt = (8 + nbytes) * 8
            if self.mode == "crop":
                data = self.rk >= self.SYNC
                if nbt > self.TILE ** 2 - self.SYNC or data.sum() < nbt * 2:
                    return
                idx, w = (self.rk[data] - self.SYNC) % nbt, S[data]
            else:
                if self.nb < nbt * 2:
                    return
                idx, w = self.perm % nbt, S
            yield nbt, np.bincount(idx, weights=w, minlength=nbt) / np.maximum(np.bincount(idx, minlength=nbt), 1)

    def read(self, frames):
        """Lê o payload a partir de vários quadros. Retorna (texto|None, confiança)."""
        S4 = np.mean([self.soft4(f) for f in frames], axis=0)
        if self.mode == "crop":                      # acha a fase do ladrilho pelo sincronismo
            best = (-1.0, 0, 0)
            for px in range(self.TILE):
                for py in range(self.TILE):
                    self.set_phase(px, py)
                    sync = self.rk < self.SYNC
                    sc = float((S4[self.ar, self.pair_of_block][sync] * self.tsign[self.pos[sync]]).mean())
                    if sc > best[0]:
                        best = (sc, px, py)
            if best[0] < 0.2:
                return None, 0.0
            self.set_phase(best[1], best[2])
        S = S4[self.ar, self.pair_of_block]
        for nbt, soft in self.candidates(S):
            txt = parse_bits((soft > 0).astype(np.uint8))
            if txt is not None and len(txt.encode("utf-8")) + 8 == nbt // 8:
                return txt, float(np.abs(soft).mean())
        return None, 0.0


# ----------------------------------------------------------------------------
# ffmpeg: escrita por pipe + áudio original
# ----------------------------------------------------------------------------

CODECS = {  # nome: (argumentos ffmpeg, extensão sugerida)
    "ffv1": (["-c:v", "ffv1", "-level", "3", "-coder", "1", "-context", "1", "-g", "1", "-slicecrc", "1"], ".mkv"),
    "x264-lossless": (["-c:v", "libx264rgb", "-crf", "0", "-preset", "veryfast"], ".mkv"),
    "x264": (["-c:v", "libx264", "-preset", "slow", "-pix_fmt", "yuv420p"], ".mp4"),
    "x265": (["-c:v", "libx265", "-preset", "slow", "-pix_fmt", "yuv420p", "-tag:v", "hvc1"], ".mp4"),
}


def need_ffmpeg():
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        sys.exit("ffmpeg/ffprobe não encontrados no PATH (https://ffmpeg.org).")


def has_audio(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
                        "stream=codec_name", "-of", "csv=p=0", path], capture_output=True, text=True)
    return bool(r.stdout.strip())


def mux_audio(video_only, source, out):
    """Copia o áudio e metadados do original SEM recodificar (fallback: AAC)."""
    if not has_audio(source):
        shutil.move(video_only, out)
        return
    base = ["ffmpeg", "-y", "-loglevel", "error", "-i", video_only, "-i", source,
            "-map", "0:v:0", "-map", "1:a?", "-map_metadata", "1", "-c:v", "copy"]
    if subprocess.run(base + ["-c:a", "copy", out]).returncode != 0:
        subprocess.run(base + ["-c:a", "aac", "-b:a", "256k", out], check=True)
    os.remove(video_only)


def probe_fps(path, fallback):
    """FPS exato (fração, ex.: '24/1' ou '30000/1001') lido pelo ffprobe."""
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=r_frame_rate", "-of", "csv=p=0", path], capture_output=True, text=True)
    t = r.stdout.strip()
    return t if t and "/" in t and not t.startswith("0/") else repr(fallback)


def encode(src, dst, text, key=None, method="dct", codec=None, crf=16, strength=None, verbose=True, robust="std", overlay=None):
    """ENCODER: grava `text` de forma invisível em `src` e salva em `dst`."""
    need_ffmpeg()
    key = key or text
    codec = codec or ("ffv1" if method == "lsb" else "x264")
    if method == "lsb" and codec in ("x264", "x265"):
        print("AVISO: LSB não sobrevive a codec com perda; use ffv1 ou x264-lossless.", file=sys.stderr)
    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        sys.exit(f"não consegui abrir {src}")
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    bits = build_bits(text)
    strength = strength or DEFAULT_STRENGTH[robust]
    engine = LSB(key, (h, w, 3)) if method == "lsb" else DCT(key, (h, w, 3), strength, robust)

    vargs = list(CODECS[codec][0])
    if codec in ("x264", "x265"):
        vargs += ["-crf", str(crf)]
    tmp = tempfile.NamedTemporaryFile(suffix=os.path.splitext(dst)[1] or ".mkv", delete=False).name
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}",
           "-r", probe_fps(src, fps), "-i", "-", "-an", *vargs, tmp]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    n = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame = engine.embed(np.ascontiguousarray(frame), bits)
        if overlay is not None:                       # selo visível (badge) desenhado por cima
            frame = overlay(frame, n, fps)
        proc.stdin.write(np.ascontiguousarray(frame).tobytes())
        n += 1
        if verbose and n % 50 == 0:
            print(f"\r  quadros: {n}/{total}", end="", flush=True)
    cap.release()
    proc.stdin.close()
    if proc.wait() != 0:
        sys.exit("ffmpeg falhou ao gravar o vídeo")
    mux_audio(tmp, src, dst)
    if verbose:
        print(f"\r  quadros: {n}  fps={fps:.3f}  {w}x{h}  método={method}  codec={codec}  -> {dst}")
    return {"frames": n, "fps": fps, "size": (w, h), "method": method, "codec": codec}


def _sample_frames(path, k):
    """Lê até k quadros distribuídos ao longo do vídeo."""
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        sys.exit(f"não consegui abrir {path}")
    total = max(int(cap.get(cv2.CAP_PROP_FRAME_COUNT)), 1)
    want = set(np.linspace(0, total - 1, min(k, total)).astype(int).tolist())
    frames, i = [], 0
    while len(frames) < len(want):
        if not cap.grab():
            break
        if i in want:
            ok, fr = cap.retrieve()
            if ok:
                frames.append(fr)
        i += 1
    cap.release()
    return frames


def decode(path, key, method="dct", strength=None, max_frames=40, robust="auto"):
    """DECODER: extrai o selo. robust='auto' tenta std, resize e crop."""
    res = {"present": False, "payload": None, "confidence": 0.0, "frames_used": 0}
    if method == "lsb":
        frames = _sample_frames(path, 3)   # sem perda: qualquer quadro serve
        for fr in frames:
            eng = LSB(key, fr.shape)
            for nb, soft in eng.candidates(eng.raw(fr)):
                txt = parse_bits((soft > 0).astype(np.uint8))
                if txt is not None and len(txt.encode("utf-8")) + 8 == nb // 8:
                    return {"present": True, "payload": txt, "confidence": float(np.abs(soft).mean()), "frames_used": 1}
        return res
    frames = _sample_frames(path, max_frames)
    if not frames:
        return res
    for mode in (["std", "resize", "crop"] if robust == "auto" else [robust]):
        txt, conf = DCT(key, frames[0].shape, strength or DEFAULT_STRENGTH[mode], mode).read(frames)
        if txt is not None:
            return {"present": True, "payload": txt, "confidence": conf, "frames_used": len(frames), "mode": mode}
    return res


def verify(path, text, key=None, method="dct", strength=None, robust="auto"):
    """Extrai e compara com o texto esperado."""
    r = decode(path, key or text, method, strength, robust=robust)
    r["match"] = bool(r["present"] and r["payload"] == text)
    return r


# ----------------------------------------------------------------------------
# Demonstração completa
# ----------------------------------------------------------------------------

def make_demo_video(path, seconds=3, fps=24, size=(640, 360)):
    """Gera um vídeo sintético (textura + movimento) com áudio senoidal."""
    need_ffmpeg()
    w, h = size
    rng = np.random.default_rng(7)
    noise = rng.integers(0, 40, (h, w, 3), dtype=np.uint8)
    tmp = path + ".v.mkv"
    p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}",
                          "-r", str(fps), "-i", "-", "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", tmp],
                         stdin=subprocess.PIPE)
    xs, ys = np.meshgrid(np.arange(w), np.arange(h))
    for i in range(seconds * fps):
        base = np.stack([(xs + i * 3) % 256, (ys * 2 + i) % 256, ((xs + ys) // 2 + i * 2) % 256], -1).astype(np.uint8)
        frame = cv2.add(base // 2 + 40, noise)
        cv2.circle(frame, (int(w / 2 + 150 * np.sin(i / 8)), h // 2), 40, (240, 240, 240), -1)
        p.stdin.write(frame.tobytes())
    p.stdin.close()
    p.wait()
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp, "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
                    "-c:v", "copy", "-c:a", "aac", "-shortest", path], check=True)
    os.remove(tmp)


def selftest():
    SELO = "SELO_AUTENTICIDADE_2026_ID9982"
    d = tempfile.mkdtemp(prefix="vsi_")
    src = os.path.join(d, "video_original.mp4")
    make_demo_video(src)
    print("== 1) LSB + FFV1 (sem perda) ==")
    out1 = os.path.join(d, "selado_lsb.mkv")
    encode(src, out1, SELO, method="lsb", codec="ffv1")
    print("  decode:", verify(out1, SELO, method="lsb"))
    print("  chave errada:", decode(out1, "OUTRA_CHAVE", method="lsb")["present"])
    print("  original sem selo:", decode(src, SELO, method="lsb")["present"])

    print("== 2) DCT + H.264 CRF 16 ==")
    out2 = os.path.join(d, "selado_dct.mp4")
    encode(src, out2, SELO, method="dct", codec="x264", crf=16)
    print("  decode:", verify(out2, SELO, method="dct"))
    print("== 3) DCT depois de RECOMPRESSÃO H.264 CRF 28 ==")
    out3 = os.path.join(d, "recomprimido.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", out2, "-c:v", "libx264", "-crf", "28", "-c:a", "copy", out3], check=True)
    print("  decode:", verify(out3, SELO, method="dct"))
    print("  chave errada:", decode(out3, "OUTRA_CHAVE", method="dct")["present"])
    print("  original sem selo:", decode(src, SELO, method="dct")["present"])
    print("== 5) Robustez escolhida NA HORA de selar (transformações aplicadas com ffmpeg) ==")
    big = os.path.join(d, "video_720p.mp4")
    make_demo_video(big, seconds=3, size=(1280, 720))
    def ff(src_, dst_, *args):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src_, *args, dst_], check=True)
    def chk(label, path, robust):
        r = verify(path, SELO, robust=robust)
        print(f"  {label:<52} -> {'selo RECONHECIDO' if r['match'] else 'selo perdido'}")
    for mode in ("std", "resize", "crop"):
        sel = os.path.join(d, f"sel_{mode}.mp4")
        encode(big, sel, SELO, method="dct", codec="x264", crf=16, robust=mode, verbose=False)
        print(f"-- selado com robust={mode}")
        chk("original selado (sem transformação)", sel, mode)
        for lab, args, ext in [("MP4 -> H.264 CRF 28", ["-c:v", "libx264", "-crf", "28", "-an"], ".mp4"),
                               ("-> H.265 CRF 28", ["-c:v", "libx265", "-crf", "28", "-x265-params", "log-level=error", "-an"], ".mp4"),
                               ("-> WebM VP9 CRF 36", ["-c:v", "libvpx-vp9", "-crf", "36", "-b:v", "0", "-an"], ".webm"),
                               ("redimensionar 960x540 + H.264 CRF 26", ["-vf", "scale=960:540", "-c:v", "libx264", "-crf", "26", "-an"], ".mp4"),
                               ("redimensionar 480x270 + H.264 CRF 26", ["-vf", "scale=480:270", "-c:v", "libx264", "-crf", "26", "-an"], ".mp4"),
                               ("redimensionar 320x180 + H.264 CRF 26", ["-vf", "scale=320:180", "-c:v", "libx264", "-crf", "26", "-an"], ".mp4"),
                               ("ampliar 1920x1080 + H.264 CRF 23", ["-vf", "scale=1920:1080", "-c:v", "libx264", "-crf", "23", "-an"], ".mp4"),
                               ("esticar 800x600 (muda proporção)", ["-vf", "scale=800:600", "-c:v", "libx264", "-crf", "26", "-an"], ".mp4"),
                               ("cortar 960x536 (offset 128,64 alinhado a 8 px)", ["-vf", "crop=960:536:128:64", "-c:v", "libx264", "-crf", "26", "-an"], ".mp4"),
                               ("cortar 960x540 (offset 101,37 NÃO alinhado)", ["-vf", "crop=960:540:101:37", "-c:v", "libx264", "-crf", "26", "-an"], ".mp4")]:
            out_ = os.path.join(d, f"t_{mode}_{abs(hash(lab))}{ext}")
            ff(sel, out_, *args)
            chk(lab, out_, mode)
    print("== 4) LSB depois de recompressão com perda (esperado: FALHAR) ==")
    out4 = os.path.join(d, "lsb_recomprimido.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", out1, "-c:v", "libx264", "-crf", "18", "-an", out4], check=True)
    print("  decode:", decode(out4, SELO, method="lsb")["present"])
    print(f"\nArquivos de teste em: {d}")


def main():
    ap = argparse.ArgumentParser(description="Selo invisível em vídeo (LSB / DCT)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("encode", "decode", "verify"):
        s = sub.add_parser(name)
        if name == "encode":
            s.add_argument("input"); s.add_argument("output"); s.add_argument("--text", required=True)
            s.add_argument("--key", help="chave secreta (padrão: o próprio texto)")
            s.add_argument("--codec", choices=list(CODECS)); s.add_argument("--crf", type=int, default=16)
        elif name == "decode":
            s.add_argument("input"); s.add_argument("--key", required=True)
        else:
            s.add_argument("input"); s.add_argument("--text", required=True); s.add_argument("--key")
        s.add_argument("--method", choices=["lsb", "dct"], default="dct")
        s.add_argument("--strength", type=float, default=None, help="força do DCT (padrão por modo; maior = mais robusto, menos invisível)")
        s.add_argument("--robust", choices=["std", "resize", "crop"] if name == "encode" else ["auto", "std", "resize", "crop"], default="std" if name == "encode" else "auto", help="transformações toleradas: std=recompressão/formato; resize=+redimensionar; crop=+cortar (8 px alinhado)")
    sub.add_parser("selftest")
    a = ap.parse_args()
    if a.cmd == "encode":
        encode(a.input, a.output, a.text, a.key, a.method, a.codec, a.crf, a.strength, robust=a.robust)
    elif a.cmd == "decode":
        print(json.dumps(decode(a.input, a.key, a.method, a.strength, robust=a.robust), ensure_ascii=False, indent=2))
    elif a.cmd == "verify":
        r = verify(a.input, a.text, a.key, a.method, a.strength, robust=a.robust)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        sys.exit(0 if r["match"] else 1)
    else:
        selftest()


if __name__ == "__main__":
    main()
