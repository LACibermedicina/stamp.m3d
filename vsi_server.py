#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VSI PLATFORM — servidor multiusuário (SQLite) com autoinstalador pelo navegador
==============================================================================
Somente biblioteca padrão do Python 3.8+ (o processamento de vídeo é opcional e usa
OpenCV/NumPy/ffmpeg via vsi_stego.py).

  python3 vsi_server.py --host 0.0.0.0 --port 8080

1º acesso: abra http://SERVIDOR:8080 -> o instalador pede o CÓDIGO DE INSTALAÇÃO que
aparece no terminal (e em data/INSTALL_CODE.txt), verifica o ambiente, cria o banco,
a chave secreta e a conta administradora. Depois disso o instalador é desativado.

Dados: data/vsi.db (SQLite, WAL), data/config.json, data/uploads/{orig,out}/.
Segurança: senhas com scrypt, sessões em cookie HttpOnly + CSRF, bloqueio por tentativas,
limite de taxa, CSP, verificação de Origin, caminhos de arquivo aleatórios.
"""
import argparse, base64, hashlib, hmac, json, mimetypes, os, queue, re, secrets, shutil, sqlite3
import sys, tempfile, threading, time, traceback
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

VERSION = "1.0.0"
APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP_DIR)
STATIC = os.path.join(APP_DIR, "static")
DATA = os.environ.get("VSI_DATA", os.path.join(APP_DIR, "data"))
DB_PATH = os.path.join(DATA, "vsi.db")
CFG_PATH = os.path.join(DATA, "config.json")
LOCK_PATH = os.path.join(DATA, "install.lock")
CODE_PATH = os.path.join(DATA, "INSTALL_CODE.txt")
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}

CFG = {}
INSTALL_CODE = None
ENGINE = {"ok": False, "why": "não verificado"}
JOBS = queue.Queue()
DECODE_SLOTS = threading.Semaphore(2)
RATE = defaultdict(deque)
LOCK = threading.Lock()


# ----------------------------------------------------------------------------
# utilidades
# ----------------------------------------------------------------------------
def utcnow():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def future(seconds):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + seconds))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def hmac_hex(key, msg):
    return hmac.new(bytes.fromhex(key) if re.fullmatch(r"[0-9a-f]{64}", key) else key.encode(), msg.encode(), hashlib.sha256).hexdigest()


def canon(o):
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class ApiError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code, self.msg = code, msg


def rate_ok(ip, key, limit, window):
    now = time.time()
    with LOCK:
        q = RATE[(ip, key)]
        while q and q[0] < now - window:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True


def db():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA busy_timeout=30000")
    return c


def rows(cur):
    return [dict(r) for r in cur.fetchall()]


def pw_hash(pw, salt=None):
    salt = salt or secrets.token_bytes(16)
    try:
        h = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
        return "scrypt$%s$%s" % (salt.hex(), h.hex())
    except (AttributeError, ValueError):
        h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 300000, 32)
        return "pbkdf2$%s$%s" % (salt.hex(), h.hex())


def pw_check(pw, stored):
    try:
        kind, salt, _ = stored.split("$")
        salt_b = bytes.fromhex(salt)
        if kind == "scrypt":
            h = hashlib.scrypt(pw.encode(), salt=salt_b, n=2 ** 14, r=8, p=1, dklen=32)
            return hmac.compare_digest("scrypt$%s$%s" % (salt, h.hex()), stored)
        h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt_b, 300000, 32)
        return hmac.compare_digest("pbkdf2$%s$%s" % (salt, h.hex()), stored)
    except Exception:
        return False


def tok_hash(t):
    return hashlib.sha256(re.sub(r"[^A-Z0-9]", "", t.upper()).encode()).hexdigest()


def new_invite_token():
    al = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    raw = "".join(secrets.choice(al) for _ in range(12))
    return "VSI-%s-%s-%s" % (raw[:4], raw[4:8], raw[8:])


def valid_email(e):
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", e or "")) and len(e) <= 160


def log_event(conn, user_id, typ, ref="", info=""):
    conn.execute("INSERT INTO events(ts,user_id,type,ref,info) VALUES(?,?,?,?,?)", (utcnow(), user_id, typ, ref, str(info)[:500]))


def save_cfg():
    tmp = CFG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(CFG, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CFG_PATH)
    try:
        os.chmod(CFG_PATH, 0o600)
    except OSError:
        pass


def installed():
    return os.path.exists(LOCK_PATH) and os.path.exists(DB_PATH)


# ----------------------------------------------------------------------------
# banco de dados
# ----------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
  role TEXT NOT NULL CHECK(role IN('adm','req')), pw TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
  failed INTEGER NOT NULL DEFAULT 0, lock_until REAL NOT NULL DEFAULT 0, created TEXT NOT NULL, last_login TEXT);
CREATE TABLE IF NOT EXISTS sessions(
  sid TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  csrf TEXT NOT NULL, created TEXT NOT NULL, expires TEXT NOT NULL, ip TEXT, ua TEXT);
CREATE TABLE IF NOT EXISTS invites(
  id INTEGER PRIMARY KEY AUTOINCREMENT, token_hash TEXT NOT NULL UNIQUE, role TEXT NOT NULL, email TEXT,
  expires TEXT NOT NULL, created TEXT NOT NULL, created_by INTEGER, used_by TEXT, used_at TEXT, revoked INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS access_requests(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT NOT NULL, role TEXT NOT NULL, reason TEXT,
  created TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', invite_id INTEGER, decided_by INTEGER, decided_at TEXT);
CREATE TABLE IF NOT EXISTS badges(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, text TEXT NOT NULL, emoji TEXT, color TEXT NOT NULL,
  shape TEXT NOT NULL, icon TEXT, methods TEXT NOT NULL DEFAULT '{}', created TEXT NOT NULL, created_by INTEGER, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS stamps(
  id INTEGER PRIMARY KEY AUTOINCREMENT, public_id TEXT NOT NULL UNIQUE, owner_id INTEGER NOT NULL REFERENCES users(id),
  owner_name TEXT NOT NULL, file_name TEXT NOT NULL, orig_path TEXT, orig_sha256 TEXT NOT NULL, out_path TEXT, out_sha256 TEXT,
  badge_id INTEGER, badge_json TEXT NOT NULL, purpose TEXT, robust TEXT NOT NULL DEFAULT 'std', embed_qr INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL, hc TEXT, auth_id INTEGER, created TEXT NOT NULL, approved_at TEXT, removed_at TEXT, restored_at TEXT,
  proc_ms INTEGER, duration_s REAL, size_mb REAL, verifs INTEGER NOT NULL DEFAULT 0, last_verif TEXT, manifest TEXT, error TEXT);
CREATE INDEX IF NOT EXISTS ix_stamps_owner ON stamps(owner_id);
CREATE INDEX IF NOT EXISTS ix_stamps_out ON stamps(out_sha256);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, user_id INTEGER, type TEXT NOT NULL, ref TEXT, info TEXT);
CREATE TABLE IF NOT EXISTS verifications(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, ip TEXT, method TEXT, stamp_id INTEGER, present INTEGER, integrity TEXT, status TEXT);
"""
PRESETS = [("M3D Original", "M3D Original", "M3D", "#7c6cf0", "pill"), ("Autêntico", "Autêntico", "🎬", "#ff7a9c", "pill"),
           ("Protegido", "Protegido", "🛡️", "#3bb4e5", "shield")]


def init_db(conn):
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    if not conn.execute("SELECT 1 FROM badges LIMIT 1").fetchone():
        for n, t, e, c, s in PRESETS:
            conn.execute("INSERT INTO badges(name,text,emoji,color,shape,methods,created) VALUES(?,?,?,?,?,?,?)",
                         (n, t, e, c, s, '{"dct":true}', utcnow()))


# ----------------------------------------------------------------------------
# motor de selos (opcional)
# ----------------------------------------------------------------------------
def probe_engine():
    global ENGINE
    why = []
    for t in ("ffmpeg", "ffprobe"):
        if not shutil.which(t):
            why.append(t + " ausente")
    try:
        import cv2, numpy  # noqa: F401
    except Exception:
        why.append("opencv-python/numpy ausentes")
    if not why:
        try:
            import vsi_stego  # noqa: F401
        except Exception as e:  # noqa: BLE001
            why.append("vsi_stego: %s" % e)
    ENGINE = {"ok": not why, "why": "; ".join(why)}


def seal_key():
    return hmac_hex(CFG["secret"], "stego-key")


def seal_text(pid):
    return "%s.%s" % (pid, hmac_hex(CFG["secret"], "id:" + pid)[:6])


def parse_seal(text):
    m = re.fullmatch(r"([A-Z0-9]{10})\.([0-9a-f]{6})", text or "")
    if m and hmac.compare_digest(hmac_hex(CFG["secret"], "id:" + m.group(1))[:6], m.group(2)):
        return m.group(1)
    return None


def make_overlay(b):
    """Badge visível (canto inferior esquerdo): texto completo nos 3 primeiros segundos, depois só o ícone."""
    import unicodedata
    import cv2
    import numpy as np
    col = tuple(int(b["color"][i:i + 2], 16) for i in (5, 3, 1))
    text = unicodedata.normalize("NFKD", b.get("text") or "").encode("ascii", "ignore").decode()[:16]
    img = None
    if (b.get("icon") or "").startswith("data:image/"):
        try:
            img = cv2.imdecode(np.frombuffer(base64.b64decode(b["icon"].split(",", 1)[1]), np.uint8), cv2.IMREAD_UNCHANGED)
        except Exception:
            img = None
    shape = b.get("shape", "pill")

    def hook(frame, idx, fps):
        H = frame.shape[0]
        s = max(int(H * 0.075), 28)
        full = (idx / float(fps or 25)) < 3
        label = (text + "  VSI") if full and text else ""
        scale = s / 52.0
        (tw, _), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, scale, 2)
        w = int(s * 1.1 + (tw + s * 0.3 if label else 0))
        x, y = s // 2, H - int(s * 1.6)
        ov = frame.copy()
        if shape == "shield":
            pts = np.array([[x, y], [x + w, y], [x + w, y + int(s * .65)], [x + w // 2, y + s], [x, y + int(s * .65)]], np.int32)
            cv2.fillPoly(ov, [pts], col)
        else:
            r = s // 2 if shape == "pill" else s // 4
            cv2.rectangle(ov, (x + r, y), (x + w - r, y + s), col, -1)
            cv2.rectangle(ov, (x, y + r), (x + w, y + s - r), col, -1)
            for cx, cy in ((x + r, y + r), (x + w - r, y + r), (x + r, y + s - r), (x + w - r, y + s - r)):
                cv2.circle(ov, (cx, cy), r, col, -1)
        cx, cy = x + int(s * .55), y + int(s * .5)
        if img is not None:
            k = int(s * .7)
            ic = cv2.resize(img, (k, k))
            x0, y0 = cx - k // 2, cy - k // 2
            roi = ov[y0:y0 + k, x0:x0 + k]
            if ic.ndim == 3 and ic.shape[2] == 4:
                a = ic[:, :, 3:4] / 255.0
                roi[:] = (ic[:, :, :3] * a + roi * (1 - a)).astype(np.uint8)
            elif ic.ndim == 3:
                roi[:] = ic[:, :, :3]
        else:  # ícone padrão: marca de verificação
            cv2.polylines(ov, [np.array([[cx - s * .17, cy], [cx - s * .04, cy + s * .14], [cx + s * .2, cy - s * .14]], np.int32)],
                          False, (255, 255, 255), max(2, s // 12), cv2.LINE_AA)
        if label:
            cv2.putText(ov, label, (x + int(s * 1.05), y + int(s * .66)), cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), 2, cv2.LINE_AA)
        return cv2.addWeighted(ov, 0.94, frame, 0.06, 0)

    return hook


def ffprobe_tags(path):
    import subprocess
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format_tags", "-of", "json", path], capture_output=True, text=True, timeout=30)
        return {k.lower(): v for k, v in (json.loads(r.stdout).get("format", {}).get("tags") or {}).items()}
    except Exception:
        return {}


def process_stamp(sid):
    conn = db()
    try:
        s = conn.execute("SELECT * FROM stamps WHERE id=?", (sid,)).fetchone()
        if not s or s["status"] != "processing":
            return
        t0 = time.time()
        import subprocess
        import vsi_stego as vs
        dst = os.path.join(DATA, "uploads", "out", s["public_id"] + ".mp4")
        badge = json.loads(s["badge_json"])
        info = vs.encode(s["orig_path"], dst, seal_text(s["public_id"]), seal_key(), "dct", "x264", 16, None, False, s["robust"], overlay=make_overlay(badge))
        hc = hashlib.sha256((s["orig_sha256"] + str(s["owner_id"]) + str(s["owner_id"]) + str(s["auth_id"]) + str(s["badge_id"])).encode()).hexdigest()
        if s["embed_qr"]:
            key = "VSI1:" + base64.b64encode(json.dumps({"p": s["public_id"], "h": hc}).encode()).decode()
            tmp = dst + ".q.mp4"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", dst, "-c", "copy", "-movflags", "+faststart+use_metadata_tags", "-metadata", "vsi_qr=" + key, tmp], check=True)
            os.replace(tmp, dst)
        out_sha = sha256_file(dst)
        owner = conn.execute("SELECT name FROM users WHERE id=?", (s["owner_id"],)).fetchone()
        auth = conn.execute("SELECT name FROM users WHERE id=?", (s["auth_id"],)).fetchone()
        claim = {"title": s["file_name"], "public_id": s["public_id"], "hc": hc, "source_sha256": s["orig_sha256"], "derived_sha256": out_sha,
                 "author": owner["name"] if owner else "", "authorizer": auth["name"] if auth else "", "badge": badge.get("text"),
                 "purpose": s["purpose"], "issued_at": utcnow(),
                 "layers": ["sha256+timestamp", "dct-steganography/" + s["robust"], "visible-badge", "signed-manifest"] + (["qr-metadata"] if s["embed_qr"] else [])}
        manifest = {"format": "VSI-Manifest/1", "claim": claim, "signature": {"alg": "HMAC-SHA256", "value": hmac_hex(CFG["secret"], canon(claim))}}
        ms = int((time.time() - t0) * 1000)
        conn.execute("UPDATE stamps SET status='active',out_path=?,out_sha256=?,hc=?,manifest=?,proc_ms=?,duration_s=?,size_mb=?,error=NULL WHERE id=?",
                     (dst, out_sha, hc, json.dumps(manifest), ms, info["frames"] / float(info["fps"] or 25), os.path.getsize(dst) / 1048576.0, sid))
        log_event(conn, s["auth_id"], "processamento", s["public_id"], "%d ms" % ms)
        conn.commit()
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        conn.execute("UPDATE stamps SET status='failed',error=? WHERE id=?", (str(e)[:400], sid))
        conn.commit()
    finally:
        conn.close()


def worker():
    while True:
        sid = JOBS.get()
        try:
            process_stamp(sid)
        except Exception:  # noqa: BLE001
            traceback.print_exc()


# ----------------------------------------------------------------------------
# contexto da requisição
# ----------------------------------------------------------------------------
class Req:
    def __init__(self, h, method, parts, params):
        self.h, self.method, self.q = h, method, params
        self.path = parts
        self.user = None
        self.csrf = None
        self.ip = h.client_address[0]
        self._json = None
        self.conn = None

    def json(self):
        if self._json is None:
            n = int(self.h.headers.get("Content-Length") or 0)
            if n > 2_000_000:
                raise ApiError(413, "Corpo grande demais")
            raw = self.h.rfile.read(n) if n else b"{}"
            try:
                self._json = json.loads(raw.decode("utf-8") or "{}")
            except ValueError:
                raise ApiError(400, "JSON inválido")
        return self._json

    def save_body(self, dest, limit):
        n = int(self.h.headers.get("Content-Length") or 0)
        if n <= 0:
            raise ApiError(411, "Content-Length obrigatório")
        if n > limit:
            raise ApiError(413, "Arquivo maior que o limite de %d MB" % (limit // 1048576))
        h, left = hashlib.sha256(), n
        with open(dest, "wb") as f:
            while left > 0:
                b = self.h.rfile.read(min(1 << 20, left))
                if not b:
                    break
                f.write(b)
                h.update(b)
                left -= len(b)
        if left:
            os.remove(dest)
            raise ApiError(400, "Envio interrompido")
        return h.hexdigest()


def need(r, role=None):
    if not r.user:
        raise ApiError(401, "Entre na sua conta")
    if role == "adm" and r.user["role"] != "adm":
        raise ApiError(403, "Apenas Autorizador/Admin")


def public_user(u):
    return {"id": u["id"], "name": u["name"], "email": u["email"], "role": u["role"]}


# ----------------------------------------------------------------------------
# rotas: instalador
# ----------------------------------------------------------------------------
def checks():
    out = []
    v = sys.version_info
    out.append(("Python " + ".".join(map(str, v[:3])), v >= (3, 8), "requer 3.8 ou superior", True))
    out.append(("SQLite " + sqlite3.sqlite_version, True, "", True))
    try:
        os.makedirs(os.path.join(DATA, "uploads", "orig"), exist_ok=True)
        os.makedirs(os.path.join(DATA, "uploads", "out"), exist_ok=True)
        t = os.path.join(DATA, ".w")
        open(t, "w").close()
        os.remove(t)
        w = True
    except OSError:
        w = False
    out.append(("Pasta de dados gravável (%s)" % DATA, w, "ajuste as permissões da pasta", True))
    free = shutil.disk_usage(DATA if os.path.exists(DATA) else APP_DIR).free / 1073741824.0
    out.append(("Espaço livre %.1f GB" % free, free > 1, "pouco espaço para vídeos", False))
    for t in ("ffmpeg", "ffprobe"):
        out.append((t, bool(shutil.which(t)), "necessário para processar vídeos", False))
    for m in ("cv2", "numpy"):
        try:
            __import__(m)
            ok = True
        except Exception:
            ok = False
        out.append((m + (" (opencv-python-headless)" if m == "cv2" else ""), ok, "pip install opencv-python-headless numpy", False))
    return [{"name": n, "ok": o, "hint": h, "required": req} for n, o, h, req in out]


def r_install_status(r):
    return {"installed": installed(), "version": VERSION}


def r_install_check(r):
    if installed():
        raise ApiError(403, "Já instalado")
    return {"checks": checks()}


def r_install(r):
    if installed():
        raise ApiError(403, "Já instalado")
    if not rate_ok(r.ip, "install", 10, 600):
        raise ApiError(429, "Muitas tentativas")
    b = r.json()
    if not INSTALL_CODE or not hmac.compare_digest(str(b.get("code", "")).strip().upper(), INSTALL_CODE):
        raise ApiError(403, "Código de instalação incorreto (veja o terminal do servidor ou data/INSTALL_CODE.txt)")
    name, email, pw = str(b.get("admin_name", "")).strip(), str(b.get("admin_email", "")).strip().lower(), str(b.get("admin_password", ""))
    if not name or not valid_email(email):
        raise ApiError(400, "Informe nome e e-mail válidos do administrador")
    if len(pw) < 10:
        raise ApiError(400, "A senha do administrador precisa ter 10 ou mais caracteres")
    if any(not c["ok"] for c in checks() if c["required"]):
        raise ApiError(400, "O ambiente não atende aos requisitos obrigatórios")
    global CFG
    CFG = {"site_name": str(b.get("site_name") or "M3D Stamp")[:60], "base_url": str(b.get("base_url") or "").rstrip("/")[:200],
           "secret": secrets.token_hex(32), "public_verify": bool(b.get("public_verify", True)), "allow_requests": True,
           "max_upload_mb": max(1, min(int(b.get("max_upload_mb") or 500), 20000)), "session_hours": max(1, min(int(b.get("session_hours") or 8), 720)),
           "secure_cookies": bool(b.get("secure_cookies", False)), "embed_qr_default": False, "installed_at": utcnow(), "version": VERSION}
    conn = db()
    try:
        init_db(conn)
        conn.execute("INSERT INTO users(name,email,role,pw,created) VALUES(?,?,?,?,?)", (name, email, "adm", pw_hash(pw), utcnow()))
        log_event(conn, 1, "instalação", "", "sistema instalado")
        conn.commit()
    finally:
        conn.close()
    save_cfg()
    open(LOCK_PATH, "w").write(utcnow())
    try:
        os.remove(CODE_PATH)
    except OSError:
        pass
    probe_engine()
    return {"ok": True}


# ----------------------------------------------------------------------------
# rotas: autenticação
# ----------------------------------------------------------------------------
def start_session(r, conn, user):
    tok, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(16)
    conn.execute("INSERT INTO sessions(sid,user_id,csrf,created,expires,ip,ua) VALUES(?,?,?,?,?,?,?)",
                 (hashlib.sha256(tok.encode()).hexdigest(), user["id"], csrf, utcnow(), future(CFG["session_hours"] * 3600), r.ip, (r.h.headers.get("User-Agent") or "")[:200]))
    conn.execute("UPDATE users SET last_login=?,failed=0,lock_until=0 WHERE id=?", (utcnow(), user["id"]))
    r.h.set_cookie = "vsi_sid=%s; HttpOnly; Path=/; SameSite=Lax; Max-Age=%d%s" % (tok, CFG["session_hours"] * 3600, "; Secure" if CFG.get("secure_cookies") else "")
    return csrf


def r_login(r):
    if not rate_ok(r.ip, "login", 20, 300):
        raise ApiError(429, "Muitas tentativas. Aguarde alguns minutos.")
    b = r.json()
    email, pw = str(b.get("email", "")).strip().lower(), str(b.get("password", ""))
    u = r.conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    bad = ApiError(401, "E-mail ou senha incorretos")
    if not u:
        pw_hash(pw or "x")  # equaliza o tempo de resposta
        raise bad
    if u["lock_until"] > time.time():
        raise ApiError(423, "Conta bloqueada por tentativas excessivas. Tente em %d min." % (int(u["lock_until"] - time.time()) // 60 + 1))
    if not u["active"]:
        raise ApiError(403, "Conta desativada. Fale com um administrador.")
    if not pw_check(pw, u["pw"]):
        f = u["failed"] + 1
        r.conn.execute("UPDATE users SET failed=?,lock_until=? WHERE id=?", (0 if f >= 5 else f, time.time() + 300 if f >= 5 else 0, u["id"]))
        log_event(r.conn, u["id"], "login falhou", email)
        r.conn.commit()
        raise bad
    csrf = start_session(r, r.conn, u)
    log_event(r.conn, u["id"], "login", email)
    r.conn.commit()
    return {"user": public_user(u), "csrf": csrf}


def r_logout(r):
    if r.user:
        r.conn.execute("DELETE FROM sessions WHERE sid=?", (r.user["_sid"],))
        r.conn.commit()
    r.h.set_cookie = "vsi_sid=; HttpOnly; Path=/; SameSite=Lax; Max-Age=0"
    return {"ok": True}


def r_me(r):
    need(r)
    return {"user": public_user(r.user), "csrf": r.csrf}


def r_token_check(r):
    if not rate_ok(r.ip, "tok", 15, 300):
        raise ApiError(429, "Muitas tentativas. Aguarde alguns minutos.")
    t = r.conn.execute("SELECT * FROM invites WHERE token_hash=?", (tok_hash(str(r.json().get("token", ""))),)).fetchone()
    if not t:
        raise ApiError(400, "Token inválido")
    if t["revoked"]:
        raise ApiError(400, "Este token foi revogado")
    if t["used_at"]:
        raise ApiError(400, "Este token já foi usado")
    if t["expires"] < utcnow():
        raise ApiError(400, "Este token expirou")
    return {"valid": True, "role": t["role"], "email": t["email"] or ""}


def r_register(r):
    if not rate_ok(r.ip, "reg", 10, 600):
        raise ApiError(429, "Muitas tentativas")
    b = r.json()
    t = r.conn.execute("SELECT * FROM invites WHERE token_hash=?", (tok_hash(str(b.get("token", ""))),)).fetchone()
    if not t or t["revoked"] or t["used_at"] or t["expires"] < utcnow():
        raise ApiError(400, "Token indisponível")
    name, email, pw = str(b.get("name", "")).strip(), str(b.get("email", "")).strip().lower(), str(b.get("password", ""))
    if t["email"] and t["email"] != email:
        raise ApiError(400, "Este token foi emitido para outro e-mail")
    if not name or not valid_email(email):
        raise ApiError(400, "Informe nome e e-mail válidos")
    if len(pw) < 8:
        raise ApiError(400, "A senha precisa ter 8 ou mais caracteres")
    if r.conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
        raise ApiError(409, "Esse e-mail já está cadastrado")
    cur = r.conn.execute("INSERT INTO users(name,email,role,pw,created) VALUES(?,?,?,?,?)", (name[:80], email, t["role"], pw_hash(pw), utcnow()))
    r.conn.execute("UPDATE invites SET used_by=?,used_at=? WHERE id=?", (email, utcnow(), t["id"]))
    u = r.conn.execute("SELECT * FROM users WHERE id=?", (cur.lastrowid,)).fetchone()
    csrf = start_session(r, r.conn, u)
    log_event(r.conn, u["id"], "usuário", email, "conta criada com convite %d" % t["id"])
    r.conn.commit()
    return {"user": public_user(u), "csrf": csrf}


def r_request_access(r):
    if not CFG.get("allow_requests", True) or not rate_ok(r.ip, "req", 5, 3600):
        raise ApiError(429, "Pedidos indisponíveis ou limite atingido")
    b = r.json()
    name, email, why = str(b.get("name", "")).strip()[:80], str(b.get("email", "")).strip().lower(), str(b.get("reason", "")).strip()[:300]
    if not name or not valid_email(email) or len(why) < 5:
        raise ApiError(400, "Informe nome, e-mail válido e o motivo")
    if r.conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
        raise ApiError(409, "Esse e-mail já tem conta")
    if r.conn.execute("SELECT 1 FROM access_requests WHERE email=? AND status='pending'", (email,)).fetchone():
        raise ApiError(409, "Já existe um pedido pendente para esse e-mail")
    r.conn.execute("INSERT INTO access_requests(name,email,role,reason,created) VALUES(?,?,?,?,?)", (name, email, "adm" if b.get("role") == "adm" else "req", why, utcnow()))
    log_event(r.conn, None, "pedido", email, "pedido de acesso")
    r.conn.commit()
    return {"ok": True}


def r_password(r):
    need(r)
    b = r.json()
    if not pw_check(str(b.get("old", "")), r.user["pw"]):
        raise ApiError(400, "Senha atual incorreta")
    if len(str(b.get("new", ""))) < 8:
        raise ApiError(400, "A nova senha precisa ter 8 ou mais caracteres")
    r.conn.execute("UPDATE users SET pw=? WHERE id=?", (pw_hash(b["new"]), r.user["id"]))
    r.conn.execute("DELETE FROM sessions WHERE user_id=? AND sid<>?", (r.user["id"], r.user["_sid"]))
    log_event(r.conn, r.user["id"], "usuário", r.user["email"], "senha alterada")
    r.conn.commit()
    return {"ok": True}


# ----------------------------------------------------------------------------
# rotas: selos
# ----------------------------------------------------------------------------
PUB_FIELDS = "id,public_id,owner_id,owner_name,file_name,orig_sha256,out_sha256,badge_json,purpose,robust,embed_qr,status,created,approved_at,removed_at,restored_at,proc_ms,duration_s,size_mb,verifs,last_verif,error"


def stamp_view(s, adm):
    d = dict(s)
    d["badge"] = json.loads(d.pop("badge_json"))
    if not adm:
        d.pop("orig_sha256", None)
        d.pop("out_sha256", None)
    for k in ("orig_path", "out_path", "manifest"):
        d.pop(k, None)
    if not adm:
        d.pop("hc", None)
        d.pop("auth_id", None)
    d["downloadable"] = bool(s["status"] == "active")
    return d


def get_stamp(r, sid):
    s = r.conn.execute("SELECT * FROM stamps WHERE id=?", (sid,)).fetchone()
    if not s or (r.user["role"] != "adm" and s["owner_id"] != r.user["id"]):
        raise ApiError(404, "Selo não encontrado")
    return s


def r_stamps(r):
    need(r)
    adm = r.user["role"] == "adm"
    q, args = "SELECT %s FROM stamps" % PUB_FIELDS, []
    if not adm:
        q, args = q + " WHERE owner_id=?", [r.user["id"]]
    return {"stamps": [stamp_view(s, adm) for s in r.conn.execute(q + " ORDER BY id DESC LIMIT 500", args).fetchall()]}


def r_stamp_upload(r):
    need(r)
    if not ENGINE["ok"]:
        raise ApiError(503, "Processamento de vídeo indisponível neste servidor: " + ENGINE["why"])
    try:
        meta = json.loads(unquote(r.h.headers.get("X-Meta") or "{}"))
    except ValueError:
        raise ApiError(400, "Metadados inválidos")
    if not meta.get("declare"):
        raise ApiError(400, "É necessário declarar que você é o autor e responsável pelos dados")
    fname = re.sub(r"[^\w.\- ]", "_", os.path.basename(str(meta.get("fileName", "video.mp4"))))[:120]
    ext = os.path.splitext(fname)[1].lower()
    if ext not in VIDEO_EXT:
        raise ApiError(400, "Formato não aceito. Use: " + ", ".join(sorted(VIDEO_EXT)))
    badge = r.conn.execute("SELECT * FROM badges WHERE id=? AND active=1", (meta.get("badge_id"),)).fetchone()
    if not badge:
        raise ApiError(400, "Escolha um modelo de selo válido")
    robust = meta.get("robust") if meta.get("robust") in ("std", "resize", "crop") else "std"
    pid = "".join(secrets.choice("ABCDEFGHJKMNPQRSTUVWXYZ23456789") for _ in range(10))
    dest = os.path.join(DATA, "uploads", "orig", pid + ext)
    sha = r.save_body(dest, int(CFG["max_upload_mb"]) * 1048576)
    adm = r.user["role"] == "adm"
    bj = {"name": badge["name"], "text": badge["text"], "emoji": badge["emoji"], "color": badge["color"], "shape": badge["shape"], "icon": badge["icon"]}
    cur = r.conn.execute("INSERT INTO stamps(public_id,owner_id,owner_name,file_name,orig_path,orig_sha256,badge_id,badge_json,purpose,robust,embed_qr,status,auth_id,created,approved_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (pid, r.user["id"], r.user["name"], fname, dest, sha, badge["id"], json.dumps(bj), str(meta.get("purpose", ""))[:300], robust,
                          ((1 if meta.get("embed_qr") else 0) if adm else int(bool(CFG.get("embed_qr_default")))), "processing" if adm else "pending", r.user["id"] if adm else None, utcnow(), utcnow() if adm else None))
    log_event(r.conn, r.user["id"], "emissão" if adm else "solicitação", pid, fname)
    r.conn.commit()
    if adm:
        JOBS.put(cur.lastrowid)
    return {"id": cur.lastrowid, "public_id": pid, "status": "processing" if adm else "pending"}


def r_stamp_action(r, sid, action):
    need(r, "adm")
    s = r.conn.execute("SELECT * FROM stamps WHERE id=?", (sid,)).fetchone()
    if not s:
        raise ApiError(404, "Selo não encontrado")
    st, queue_it = s["status"], False
    if action == "approve" and st == "pending":
        r.conn.execute("UPDATE stamps SET status='processing',auth_id=?,approved_at=? WHERE id=?", (r.user["id"], utcnow(), sid))
        queue_it = True
    elif action == "reject" and st == "pending":
        r.conn.execute("UPDATE stamps SET status='rejected' WHERE id=?", (sid,))
    elif action == "revoke" and st == "active":
        r.conn.execute("UPDATE stamps SET status='revoked',removed_at=? WHERE id=?", (utcnow(), sid))
    elif action == "restore" and st == "revoked":
        r.conn.execute("UPDATE stamps SET status='active',restored_at=? WHERE id=?", (utcnow(), sid))
    elif action == "retry" and st == "failed":
        r.conn.execute("UPDATE stamps SET status='processing',error=NULL WHERE id=?", (sid,))
        queue_it = True
    else:
        raise ApiError(409, "Ação '%s' não permitida no estado '%s'" % (action, st))
    log_event(r.conn, r.user["id"], {"approve": "aprovação", "reject": "rejeição", "revoke": "remoção", "restore": "restauração", "retry": "reprocesso"}[action], s["public_id"], s["owner_name"])
    r.conn.commit()
    if queue_it:
        JOBS.put(sid)  # só depois do commit, senão o worker lê o estado antigo
    return {"ok": True}


def r_stamp_delete(r, sid):
    need(r)
    s = get_stamp(r, sid)
    if r.user["role"] != "adm" and s["status"] not in ("pending", "rejected", "failed"):
        raise ApiError(403, "Só um Autorizador/Admin remove selos já emitidos (use Revogar)")
    for p in (s["orig_path"], s["out_path"]):
        if p and os.path.exists(p):
            os.remove(p)
    r.conn.execute("DELETE FROM stamps WHERE id=?", (sid,))
    log_event(r.conn, r.user["id"], "exclusão", s["public_id"], s["file_name"])
    r.conn.commit()
    return {"ok": True}


def r_stamp_download(r, sid):
    need(r)
    s = get_stamp(r, sid)
    if s["status"] != "active" or not s["out_path"] or not os.path.exists(s["out_path"]):
        raise ApiError(409, "O vídeo com selo ainda não está disponível")
    return ("file", s["out_path"], os.path.splitext(s["file_name"])[0] + "_selo.mp4")


def r_stamp_manifest(r, sid):
    need(r, "adm")
    s = get_stamp(r, sid)
    if not s["manifest"]:
        raise ApiError(409, "Manifesto indisponível")
    return ("bytes", s["manifest"].encode(), os.path.splitext(s["file_name"])[0] + "_manifesto.json", "application/json")


def r_stamp_key(r, sid):
    need(r, "adm")
    s = get_stamp(r, sid)
    if not s["hc"]:
        raise ApiError(409, "Selo ainda não assinado")
    key = "VSI1:" + base64.b64encode(json.dumps({"p": s["public_id"], "h": s["hc"]}).encode()).decode()
    return {"key": key, "public_url": "%s/#/v/%s" % (CFG.get("base_url", ""), s["public_id"])}


def r_unlock(r):
    need(r, "adm")
    try:
        o = json.loads(base64.b64decode(str(r.json().get("key", "")).strip().replace("VSI1:", "")))
    except Exception:
        raise ApiError(400, "Chave inválida")
    s = r.conn.execute("SELECT * FROM stamps WHERE public_id=? AND hc=?", (o.get("p"), o.get("h"))).fetchone()
    if not s:
        raise ApiError(404, "A chave não corresponde a nenhum selo")
    auth = r.conn.execute("SELECT name,email FROM users WHERE id=?", (s["auth_id"],)).fetchone()
    owner = r.conn.execute("SELECT name,email FROM users WHERE id=?", (s["owner_id"],)).fetchone()
    return {"stamp": stamp_view(s, True), "author": dict(owner) if owner else None, "authorizer": dict(auth) if auth else None, "hc": s["hc"]}


# ----------------------------------------------------------------------------
# rotas: verificação pública
# ----------------------------------------------------------------------------
def verify_result(conn, ip, method, st, hash_hit, dct_hit, qr_meta, present_by):
    present = st is not None
    status = (("valid" if st["status"] == "active" else "revoked") if present and st["status"] in ("active", "revoked") else None)
    if present:
        conn.execute("UPDATE stamps SET verifs=verifs+1,last_verif=? WHERE id=?", (utcnow(), st["id"]))
    integrity = ("intact" if hash_hit else "altered") if present else None
    conn.execute("INSERT INTO verifications(ts,ip,method,stamp_id,present,integrity,status) VALUES(?,?,?,?,?,?,?)",
                 (utcnow(), ip, method, st["id"] if present else None, int(present), integrity, status))
    conn.commit()
    return {"present": present, "integrity": integrity, "status": status, "ref": st["public_id"] if present else None,
            "layers": {"sha256": bool(hash_hit), "dct": dct_hit, "qr_metadata": qr_meta}, "locked": True,
            "note": None if present else "Nenhum selo reconhecido neste arquivo."}


def r_public_verify(r):
    if not CFG.get("public_verify", True):
        raise ApiError(403, "A verificação pública está desativada")
    if not rate_ok(r.ip, "verify", 20, 60):
        raise ApiError(429, "Muitas verificações. Aguarde um minuto.")
    ct = (r.h.headers.get("Content-Type") or "").split(";")[0]
    if ct == "application/json":
        h = str(r.json().get("sha256", "")).strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", h):
            raise ApiError(400, "Hash inválido")
        st = r.conn.execute("SELECT * FROM stamps WHERE out_sha256=? AND hc IS NOT NULL", (h,)).fetchone()
        return verify_result(r.conn, r.ip, "hash", st, bool(st), None, False, "hash")
    tmp = tempfile.NamedTemporaryFile(delete=False, dir=os.path.join(DATA, "uploads"), suffix=".bin").name
    try:
        sha = r.save_body(tmp, int(CFG["max_upload_mb"]) * 1048576)
        st = r.conn.execute("SELECT * FROM stamps WHERE out_sha256=? AND hc IS NOT NULL", (sha,)).fetchone()
        qr_meta = bool(ENGINE["ok"] and "vsi_qr" in ffprobe_tags(tmp))
        dct = None
        if st is None and ENGINE["ok"]:
            if not DECODE_SLOTS.acquire(timeout=60):
                raise ApiError(503, "Servidor ocupado. Tente novamente.")
            try:
                import vsi_stego as vs
                res = vs.decode(tmp, seal_key(), "dct", None, 24, "auto")
            finally:
                DECODE_SLOTS.release()
            pid = parse_seal(res.get("payload")) if res.get("present") else None
            dct = bool(pid)
            if pid:
                st = r.conn.execute("SELECT * FROM stamps WHERE public_id=? AND hc IS NOT NULL", (pid,)).fetchone()
        elif ENGINE["ok"]:
            dct = True
        return verify_result(r.conn, r.ip, "file", st, bool(st and st["out_sha256"] == sha), dct, qr_meta, "file")
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def r_public_stamp(r, pid):
    st = r.conn.execute("SELECT status,created FROM stamps WHERE public_id=? AND hc IS NOT NULL", (str(pid).upper(),)).fetchone()
    if not st:
        return {"present": False}
    return {"present": True, "status": "valid" if st["status"] == "active" else "revoked", "issued_at": st["created"][:10]}


def r_public_info(r):
    return {"site_name": CFG.get("site_name"), "public_verify": CFG.get("public_verify", True), "engine": ENGINE["ok"],
            "allow_requests": CFG.get("allow_requests", True), "max_upload_mb": CFG.get("max_upload_mb"), "version": VERSION}


# ----------------------------------------------------------------------------
# rotas: modelos de selo
# ----------------------------------------------------------------------------
def badge_clean(b):
    t = str(b.get("text", "")).strip()[:16]
    if not t:
        raise ApiError(400, "Informe o texto do selo")
    col = str(b.get("color", "#7c6cf0"))
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", col):
        col = "#7c6cf0"
    ic = b.get("icon") if isinstance(b.get("icon"), str) and re.match(r"data:image/(png|jpeg|webp);base64,", b.get("icon", "")) and len(b["icon"]) < 400000 else None
    return (str(b.get("name") or t)[:40], t, str(b.get("emoji") or "")[:8], col, b.get("shape") if b.get("shape") in ("pill", "square", "shield") else "pill", ic)


def r_badges(r):
    need(r)
    return {"badges": [dict(b, methods=json.loads(b["methods"])) for b in rows(r.conn.execute("SELECT * FROM badges WHERE active=1 ORDER BY id"))]}


def r_badge_create(r):
    need(r, "adm")
    items = r.json()
    items = items if isinstance(items, list) else [items]
    n = 0
    for b in items[:50]:
        if isinstance(b, dict):
            r.conn.execute("INSERT INTO badges(name,text,emoji,color,shape,icon,methods,created,created_by) VALUES(?,?,?,?,?,?,?,?,?)", badge_clean(b) + ('{"dct":true}', utcnow(), r.user["id"]))
            n += 1
    log_event(r.conn, r.user["id"], "importação", "", "%d modelo(s) de selo" % n)
    r.conn.commit()
    return {"created": n}


def r_badge_delete(r, bid):
    need(r, "adm")
    if r.conn.execute("SELECT COUNT(*) FROM badges WHERE active=1").fetchone()[0] <= 1:
        raise ApiError(409, "Mantenha ao menos um modelo")
    r.conn.execute("UPDATE badges SET active=0 WHERE id=?", (bid,))
    r.conn.commit()
    return {"ok": True}


# ----------------------------------------------------------------------------
# rotas: administração
# ----------------------------------------------------------------------------
def r_stats(r):
    need(r)
    c, adm = r.conn, r.user["role"] == "adm"
    where, a = ("", []) if adm else (" WHERE owner_id=?", [r.user["id"]])
    cnt = {row[0]: row[1] for row in c.execute("SELECT status,COUNT(*) FROM stamps%s GROUP BY status" % where, a)}
    out = {"stamps": cnt, "total": sum(cnt.values())}
    if adm:
        out["requesters"] = rows(c.execute("SELECT owner_name AS name,COUNT(*) AS total,SUM(status='active') AS active,SUM(status IN('pending','processing')) AS waiting,SUM(status='revoked') AS removed,MAX(created) AS last FROM stamps GROUP BY owner_id ORDER BY total DESC LIMIT 50"))
        out["processing"] = dict(c.execute("SELECT COUNT(*) AS videos,COALESCE(SUM(proc_ms),0) AS ms,COALESCE(SUM(duration_s),0) AS seconds,COALESCE(SUM(size_mb),0) AS mb FROM stamps WHERE status IN('active','revoked')").fetchone())
        out["verifications"] = dict(c.execute("SELECT COUNT(*) AS total,SUM(present=0) AS no_seal,SUM(integrity='altered') AS altered FROM verifications").fetchone())
        out["never_verified"] = rows(c.execute("SELECT public_id,file_name,owner_name,created FROM stamps WHERE status='active' AND verifs=0 ORDER BY id DESC LIMIT 30"))
        out["users"] = c.execute("SELECT COUNT(*) FROM users WHERE active=1").fetchone()[0]
        out["pending_requests"] = c.execute("SELECT COUNT(*) FROM access_requests WHERE status='pending'").fetchone()[0]
    else:
        out["verifications"] = {"total": c.execute("SELECT COALESCE(SUM(verifs),0) FROM stamps WHERE owner_id=?", (r.user["id"],)).fetchone()[0]}
    return out


def r_events(r):
    need(r, "adm")
    lim = min(int(r.q.get("limit", ["100"])[0]), 500)
    return {"events": rows(r.conn.execute("SELECT e.ts,e.type,e.ref,e.info,u.name AS user FROM events e LEFT JOIN users u ON u.id=e.user_id ORDER BY e.id DESC LIMIT ?", (lim,)))}


def r_users(r):
    need(r, "adm")
    return {"users": rows(r.conn.execute("SELECT id,name,email,role,active,created,last_login,lock_until>? AS locked FROM users ORDER BY id", (time.time(),)))}


def r_user_create(r):
    need(r, "adm")
    b = r.json()
    name, email, pw = str(b.get("name", "")).strip()[:80], str(b.get("email", "")).strip().lower(), str(b.get("password", ""))
    if not name or not valid_email(email) or len(pw) < 8:
        raise ApiError(400, "Informe nome, e-mail válido e senha temporária de 8+ caracteres")
    if r.conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
        raise ApiError(409, "E-mail já cadastrado")
    r.conn.execute("INSERT INTO users(name,email,role,pw,created) VALUES(?,?,?,?,?)", (name, email, "adm" if b.get("role") == "adm" else "req", pw_hash(pw), utcnow()))
    log_event(r.conn, r.user["id"], "usuário", email, "criado")
    r.conn.commit()
    return {"ok": True}


def admins_left(c, uid):
    return c.execute("SELECT COUNT(*) FROM users WHERE role='adm' AND active=1 AND id<>?", (uid,)).fetchone()[0]


def r_user_update(r, uid):
    need(r, "adm")
    b, u = r.json(), r.conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not u:
        raise ApiError(404, "Usuário não encontrado")
    role = b.get("role", u["role"])
    active = int(bool(b.get("active", u["active"])))
    if u["role"] == "adm" and u["active"] and (role != "adm" or not active) and not admins_left(r.conn, uid):
        raise ApiError(409, "Mantenha ao menos um administrador ativo")
    if uid == r.user["id"] and not active:
        raise ApiError(409, "Você não pode desativar a própria conta")
    if b.get("password"):
        if len(str(b["password"])) < 8:
            raise ApiError(400, "Senha: mínimo de 8 caracteres")
        r.conn.execute("UPDATE users SET pw=?,failed=0,lock_until=0 WHERE id=?", (pw_hash(b["password"]), uid))
        r.conn.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
    r.conn.execute("UPDATE users SET role=?,active=?,name=? WHERE id=?", ("adm" if role == "adm" else "req", active, str(b.get("name", u["name"]))[:80], uid))
    if not active:
        r.conn.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
    log_event(r.conn, r.user["id"], "usuário", u["email"], "atualizado")
    r.conn.commit()
    return {"ok": True}


def r_user_delete(r, uid):
    need(r, "adm")
    u = r.conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not u:
        raise ApiError(404, "Usuário não encontrado")
    if uid == r.user["id"] or (u["role"] == "adm" and u["active"] and not admins_left(r.conn, uid)):
        raise ApiError(409, "Não é possível excluir a si mesmo nem o último administrador")
    if r.conn.execute("SELECT 1 FROM stamps WHERE owner_id=?", (uid,)).fetchone():
        raise ApiError(409, "Este usuário possui selos: desative a conta em vez de excluir")
    r.conn.execute("DELETE FROM users WHERE id=?", (uid,))
    log_event(r.conn, r.user["id"], "usuário", u["email"], "excluído")
    r.conn.commit()
    return {"ok": True}


def make_invite(c, by, role, email, days):
    tok = new_invite_token()
    cur = c.execute("INSERT INTO invites(token_hash,role,email,expires,created,created_by) VALUES(?,?,?,?,?,?)",
                    (tok_hash(tok), "adm" if role == "adm" else "req", (email or "").strip().lower() or None, future(max(1, min(int(days or 7), 90)) * 86400), utcnow(), by))
    return tok, cur.lastrowid


def r_invites(r):
    need(r, "adm")
    return {"invites": rows(r.conn.execute("SELECT id,role,email,expires,created,used_by,used_at,revoked FROM invites ORDER BY id DESC LIMIT 100"))}


def r_invite_create(r):
    need(r, "adm")
    b = r.json()
    tok, iid = make_invite(r.conn, r.user["id"], b.get("role"), b.get("email"), b.get("days"))
    log_event(r.conn, r.user["id"], "convite", str(iid), b.get("email") or "")
    r.conn.commit()
    return {"token": tok, "id": iid}


def r_invite_revoke(r, iid):
    need(r, "adm")
    r.conn.execute("UPDATE invites SET revoked=1 WHERE id=?", (iid,))
    r.conn.commit()
    return {"ok": True}


def r_requests(r):
    need(r, "adm")
    return {"requests": rows(r.conn.execute("SELECT * FROM access_requests ORDER BY id DESC LIMIT 100"))}


def r_request_decide(r, rid, action):
    need(r, "adm")
    q = r.conn.execute("SELECT * FROM access_requests WHERE id=? AND status='pending'", (rid,)).fetchone()
    if not q:
        raise ApiError(404, "Pedido não encontrado ou já decidido")
    tok = None
    if action == "approve":
        tok, iid = make_invite(r.conn, r.user["id"], r.json().get("role") or q["role"], q["email"], 7)
        r.conn.execute("UPDATE access_requests SET status='approved',invite_id=?,decided_by=?,decided_at=? WHERE id=?", (iid, r.user["id"], utcnow(), rid))
    else:
        r.conn.execute("UPDATE access_requests SET status='denied',decided_by=?,decided_at=? WHERE id=?", (r.user["id"], utcnow(), rid))
    log_event(r.conn, r.user["id"], "pedido", q["email"], "aprovado" if tok else "recusado")
    r.conn.commit()
    return {"token": tok}


def r_settings_get(r):
    need(r, "adm")
    d = {k: v for k, v in CFG.items() if k != "secret"}
    d["engine"] = ENGINE
    return d


def r_settings_put(r):
    need(r, "adm")
    b = r.json()
    for k, cast in (("site_name", lambda v: str(v)[:60]), ("base_url", lambda v: str(v).rstrip("/")[:200]), ("public_verify", bool), ("allow_requests", bool),
                    ("embed_qr_default", bool), ("secure_cookies", bool), ("max_upload_mb", lambda v: max(1, min(int(v), 20000))), ("session_hours", lambda v: max(1, min(int(v), 720)))):
        if k in b:
            CFG[k] = cast(b[k])
    save_cfg()
    log_event(r.conn, r.user["id"], "configuração", "", "atualizada")
    r.conn.commit()
    return {"ok": True}


def r_backup(r):
    need(r, "adm")
    tmp = os.path.join(DATA, "backup_%d.db" % int(time.time()))
    dst = sqlite3.connect(tmp)
    with dst:
        r.conn.backup(dst)
    dst.close()
    data = open(tmp, "rb").read()
    os.remove(tmp)
    return ("bytes", data, "vsi-backup-%s.db" % time.strftime("%Y%m%d-%H%M"), "application/octet-stream")


# ----------------------------------------------------------------------------
# roteador HTTP
# ----------------------------------------------------------------------------
def int_(x):
    return int(x)


ROUTES = [  # (método, regex, função, requer_instalado)
    ("GET", r"/api/install/status", r_install_status, False), ("GET", r"/api/install/check", r_install_check, False), ("POST", r"/api/install", r_install, False),
    ("GET", r"/api/public/info", r_public_info, True), ("POST", r"/api/public/verify", r_public_verify, True), ("GET", r"/api/public/stamp/([A-Za-z0-9]{10})", r_public_stamp, True),
    ("POST", r"/api/auth/login", r_login, True), ("POST", r"/api/auth/logout", r_logout, True), ("GET", r"/api/me", r_me, True),
    ("POST", r"/api/auth/token", r_token_check, True), ("POST", r"/api/auth/register", r_register, True), ("POST", r"/api/auth/request", r_request_access, True),
    ("POST", r"/api/auth/password", r_password, True),
    ("GET", r"/api/stamps", r_stamps, True), ("POST", r"/api/stamps/upload", r_stamp_upload, True),
    ("POST", r"/api/stamps/(\d+)/(approve|reject|revoke|restore|retry)", r_stamp_action, True), ("DELETE", r"/api/stamps/(\d+)", r_stamp_delete, True),
    ("GET", r"/api/stamps/(\d+)/download", r_stamp_download, True), ("GET", r"/api/stamps/(\d+)/manifest", r_stamp_manifest, True), ("GET", r"/api/stamps/(\d+)/key", r_stamp_key, True),
    ("POST", r"/api/admin/unlock", r_unlock, True),
    ("GET", r"/api/badges", r_badges, True), ("POST", r"/api/badges", r_badge_create, True), ("DELETE", r"/api/badges/(\d+)", r_badge_delete, True),
    ("GET", r"/api/stats", r_stats, True), ("GET", r"/api/admin/events", r_events, True),
    ("GET", r"/api/admin/users", r_users, True), ("POST", r"/api/admin/users", r_user_create, True), ("PUT", r"/api/admin/users/(\d+)", r_user_update, True), ("DELETE", r"/api/admin/users/(\d+)", r_user_delete, True),
    ("GET", r"/api/admin/invites", r_invites, True), ("POST", r"/api/admin/invites", r_invite_create, True), ("POST", r"/api/admin/invites/(\d+)/revoke", r_invite_revoke, True),
    ("GET", r"/api/admin/requests", r_requests, True), ("POST", r"/api/admin/requests/(\d+)/(approve|deny)", r_request_decide, True),
    ("GET", r"/api/admin/settings", r_settings_get, True), ("PUT", r"/api/admin/settings", r_settings_put, True), ("GET", r"/api/admin/backup", r_backup, True),
]
ROUTES = [(m, re.compile("^" + p + "$"), f, i) for m, p, f, i in ROUTES]
PUBLIC_POST = {"r_login", "r_public_verify", "r_token_check", "r_register", "r_request_access", "r_install"}
SEC_HEADERS = {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "same-origin",
               "Content-Security-Policy": "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; script-src 'self' https://cdnjs.cloudflare.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; connect-src 'self'; frame-ancestors 'none'"}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "VSI"
    set_cookie = None

    def log_message(self, fmt, *a):
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % a))

    def _send(self, code, body, ctype="application/json", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in dict(SEC_HEADERS, **(extra or {})).items():
            self.send_header(k, v)
        if self.set_cookie:
            self.send_header("Set-Cookie", self.set_cookie)
        if CFG.get("secure_cookies"):
            self.send_header("Strict-Transport-Security", "max-age=31536000")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(), extra={"Cache-Control": "no-store"})

    def _file(self, path, name, ctype=None):
        size = os.path.getsize(path)
        self.send_response(200)
        self.send_header("Content-Type", ctype or mimetypes.guess_type(path)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(size))
        self.send_header("Content-Disposition", 'attachment; filename="%s"' % re.sub(r'[^\w.\- ]', "_", name))
        for k, v in SEC_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()
        with open(path, "rb") as f:
            shutil.copyfileobj(f, self.wfile, 1 << 20)

    def _static(self, rel):
        rel = rel.lstrip("/")
        root = os.path.realpath(STATIC)
        path = os.path.realpath(os.path.join(STATIC, rel)) if rel else ""
        if not rel or rel in ("index.html", "install.html") or not path.startswith(root + os.sep) or not os.path.isfile(path):
            path = os.path.join(STATIC, "index.html" if installed() else "install.html")
        with open(path, "rb") as f:
            body = f.read()
        self._send(200, body, mimetypes.guess_type(path)[0] or "text/html", {"Cache-Control": "no-cache"})

    def handle_any(self):
        u = urlparse(self.path)
        path = u.path
        if not path.startswith("/api/"):
            return self._static(path[len("/static/"):] if path.startswith("/static/") else "")
        self.set_cookie = None
        try:
            for m, rx, fn, need_inst in ROUTES:
                mt = rx.match(path)
                if mt and m == self.command:
                    break
            else:
                raise ApiError(404, "Rota não encontrada")
            if need_inst and not installed():
                raise ApiError(503, "Sistema não instalado")
            origin = self.headers.get("Origin")
            if m != "GET" and origin and urlparse(origin).netloc != self.headers.get("Host"):
                raise ApiError(403, "Origem não permitida")
            r = Req(self, m, path, parse_qs(u.query))
            if installed():
                r.conn = db()
            try:
                if r.conn is not None:
                    self._auth(r)
                    if m != "GET" and r.user and fn.__name__ not in PUBLIC_POST and not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), r.csrf or ""):
                        raise ApiError(403, "Token CSRF inválido. Recarregue a página.")
                args = [int(g) if g.isdigit() else g for g in mt.groups()]
                res = fn(r, *args)
            finally:
                if r.conn is not None:
                    r.conn.close()
            if isinstance(res, tuple) and res[0] == "file":
                return self._file(res[1], res[2])
            if isinstance(res, tuple) and res[0] == "bytes":
                self.send_response(200)
                self.send_header("Content-Type", res[3])
                self.send_header("Content-Length", str(len(res[1])))
                self.send_header("Content-Disposition", 'attachment; filename="%s"' % res[2])
                for k, v in SEC_HEADERS.items():
                    self.send_header(k, v)
                self.end_headers()
                return self.wfile.write(res[1])
            self._json(200, res)
        except ApiError as e:
            self.close_connection = True  # corpo não lido: evita misturar requisições
            self._json(e.code, {"error": e.msg})
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self._json(500, {"error": "Erro interno do servidor"})

    def _auth(self, r):
        ck = self.headers.get("Cookie") or ""
        m = re.search(r"(?:^|;\s*)vsi_sid=([A-Za-z0-9_\-]+)", ck)
        if not m:
            return
        sid = hashlib.sha256(m.group(1).encode()).hexdigest()
        row = r.conn.execute("SELECT u.*,s.csrf AS _csrf,s.sid AS _sid FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.sid=? AND s.expires>? AND u.active=1", (sid, utcnow())).fetchone()
        if row:
            r.user, r.csrf = dict(row), row["_csrf"]

    do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = handle_any


def main():
    global DATA, DB_PATH, CFG_PATH, LOCK_PATH, CODE_PATH, CFG, INSTALL_CODE
    ap = argparse.ArgumentParser(description="VSI Platform")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--data", default=DATA)
    a = ap.parse_args()
    DATA = os.path.abspath(a.data)
    DB_PATH, CFG_PATH, LOCK_PATH, CODE_PATH = (os.path.join(DATA, n) for n in ("vsi.db", "config.json", "install.lock", "INSTALL_CODE.txt"))
    os.makedirs(os.path.join(DATA, "uploads", "orig"), exist_ok=True)
    os.makedirs(os.path.join(DATA, "uploads", "out"), exist_ok=True)
    if installed():
        CFG = json.load(open(CFG_PATH, encoding="utf-8"))
        conn = db()
        conn.executescript(SCHEMA)
        for (sid,) in conn.execute("SELECT id FROM stamps WHERE status='processing'").fetchall():
            JOBS.put(sid)  # retoma o que ficou pela metade
        conn.close()
        probe_engine()
        print("VSI Platform %s em http://%s:%d  (motor de selos: %s)" % (VERSION, a.host, a.port, "ativo" if ENGINE["ok"] else "INATIVO — " + ENGINE["why"]))
    else:
        INSTALL_CODE = "%s-%s" % (secrets.token_hex(2).upper(), secrets.token_hex(2).upper())
        with open(CODE_PATH, "w") as f:
            f.write(INSTALL_CODE + "\n")
        try:
            os.chmod(CODE_PATH, 0o600)
        except OSError:
            pass
        print("=" * 62 + "\n  MODO INSTALAÇÃO — abra http://%s:%d no navegador\n  CÓDIGO DE INSTALAÇÃO: %s\n" % (a.host, a.port, INSTALL_CODE) + "=" * 62)
    threading.Thread(target=worker, daemon=True).start()
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    srv.daemon_threads = True
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrando…")


if __name__ == "__main__":
    main()
