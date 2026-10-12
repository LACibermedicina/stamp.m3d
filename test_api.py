#!/usr/bin/env python3
"""Teste de ponta a ponta da API (sobe um servidor temporário)."""
import http.client, json, os, shutil, subprocess, sys, tempfile, time, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("VSI_TEST_PORT", "18765"))


class Client:
    def __init__(self):
        self.cookie, self.csrf = None, None

    def call(self, method, path, body=None, ctype="application/json", headers=None, raw=False):
        c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=300)
        h = dict(headers or {})
        if self.cookie:
            h["Cookie"] = self.cookie
        if self.csrf and "X-CSRF-Token" not in h:
            h["X-CSRF-Token"] = self.csrf
        data = None
        if isinstance(body, (dict, list)):
            data, h["Content-Type"] = json.dumps(body).encode(), "application/json"
        elif body is not None:
            data, h["Content-Type"] = body, ctype
        if data is not None:
            h["Content-Length"] = str(len(data))
        c.request(method, path, data, h)
        r = c.getresponse()
        payload = r.read()
        sc = r.getheader("Set-Cookie")
        if sc:
            self.cookie = sc.split(";")[0] if "Max-Age=0" not in sc else None
        out = payload if raw else (json.loads(payload) if payload and r.getheader("Content-Type", "").startswith("application/json") else payload)
        return r.status, out


def ok(cond, label):
    print(("  OK   " if cond else "  FALHA ") + label)
    if not cond:
        global FAILS
        FAILS += 1


FAILS = 0
data = tempfile.mkdtemp(prefix="vsi_test_")
srv = subprocess.Popen([sys.executable, os.path.join(HERE, "vsi_server.py"), "--port", str(PORT), "--data", data], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
try:
    for _ in range(50):
        try:
            http.client.HTTPConnection("127.0.0.1", PORT, timeout=1).request("GET", "/api/install/status")
            break
        except OSError:
            time.sleep(0.2)
    A, R, P = Client(), Client(), Client()
    print("== Instalador")
    s, j = P.call("GET", "/api/install/status"); ok(s == 200 and j["installed"] is False, "status: não instalado")
    s, j = P.call("GET", "/"); ok(s == 200, "GET / serve o instalador")
    s, j = P.call("GET", "/api/me"); ok(s == 503, "API bloqueada antes da instalação")
    s, j = P.call("GET", "/api/install/check"); ok(s == 200 and any(c["name"].startswith("Python") for c in j["checks"]), "verificação de ambiente")
    body = {"code": "0000-0000", "site_name": "Teste", "admin_name": "Admin", "admin_email": "admin@x.com", "admin_password": "senha-forte-123", "max_upload_mb": 200}
    s, j = P.call("POST", "/api/install", body); ok(s == 403, "código errado rejeitado")
    code = open(os.path.join(data, "INSTALL_CODE.txt")).read().strip()
    body["code"] = code
    body["admin_password"] = "curta"
    s, j = P.call("POST", "/api/install", body); ok(s == 400, "senha curta rejeitada")
    body["admin_password"] = "senha-forte-123"
    s, j = P.call("POST", "/api/install", body); ok(s == 200, "instalação concluída")
    s, j = P.call("POST", "/api/install", body); ok(s == 403, "instalador desativado depois de instalar")
    ok(not os.path.exists(os.path.join(data, "INSTALL_CODE.txt")), "código de instalação removido")

    print("== Login e permissões")
    s, j = A.call("POST", "/api/auth/login", {"email": "admin@x.com", "password": "errada"}); ok(s == 401, "senha errada")
    s, j = A.call("POST", "/api/auth/login", {"email": "admin@x.com", "password": "senha-forte-123"}); ok(s == 200 and j["user"]["role"] == "adm", "login admin")
    A.csrf = j["csrf"]
    s, j = A.call("POST", "/api/admin/users", {"name": "X", "email": "x@y.com", "password": "12345678"}, headers={"X-CSRF-Token": "errado"}); ok(s == 403, "CSRF inválido bloqueado")
    s, j = A.call("GET", "/api/badges"); ok(s == 200 and len(j["badges"]) == 3, "3 modelos de selo padrão")
    badge_id = j["badges"][0]["id"]
    s, j = A.call("POST", "/api/admin/invites", {"role": "req", "email": "maria@x.com", "days": 7}); ok(s == 200 and j["token"].startswith("VSI-"), "convite gerado")
    tok = j["token"]
    s, j = P.call("POST", "/api/auth/token", {"token": "VSI-AAAA-BBBB-CCCC"}); ok(s == 400, "token inválido")
    s, j = P.call("POST", "/api/auth/token", {"token": tok.lower()}); ok(s == 200 and j["role"] == "req" and j["email"] == "maria@x.com", "token válido (minúsculo aceito)")
    s, j = R.call("POST", "/api/auth/register", {"token": tok, "name": "Maria", "email": "outro@x.com", "password": "senha-maria"}); ok(s == 400, "token vinculado a outro e-mail")
    s, j = R.call("POST", "/api/auth/register", {"token": tok, "name": "Maria", "email": "maria@x.com", "password": "senha-maria"}); ok(s == 200 and j["user"]["role"] == "req", "cadastro com token")
    R.csrf = j["csrf"]
    s, j = P.call("POST", "/api/auth/token", {"token": tok}); ok(s == 400, "token de uso único")
    s, j = R.call("GET", "/api/admin/users"); ok(s == 403, "solicitante não acessa admin")
    s, j = R.call("GET", "/api/admin/settings"); ok(s == 403, "solicitante não vê configurações")

    print("== Selo: upload, aprovação, processamento")
    sys.path.insert(0, HERE)
    import vsi_stego as vs
    vid = os.path.join(data, "demo.mp4")
    vs.make_demo_video(vid, seconds=2, size=(640, 360))
    meta = urllib.parse.quote(json.dumps({"fileName": "meu video.mp4", "badge_id": badge_id, "purpose": "Teste", "robust": "std", "declare": True}))
    s, j = R.call("POST", "/api/stamps/upload", open(vid, "rb").read(), "application/octet-stream", {"X-Meta": meta}); ok(s == 200 and j["status"] == "pending", "upload cria selo pendente")
    sid = j["id"]
    s, j = R.call("POST", "/api/stamps/%d/approve" % sid); ok(s == 403, "solicitante não aprova")
    s, j = R.call("GET", "/api/stamps"); ok(len(j["stamps"]) == 1 and "orig_sha256" not in j["stamps"][0], "solicitante vê só o seu selo, sem hashes")
    s, j = A.call("POST", "/api/stamps/%d/approve" % sid); ok(s == 200, "admin aprova")
    st = None
    for _ in range(120):
        s, j = A.call("GET", "/api/stamps")
        st = j["stamps"][0]["status"]
        if st in ("active", "failed"):
            break
        time.sleep(1)
    ok(st == "active", "processamento concluído (status=%s)" % st)
    if st == "failed":
        print("     erro:", j["stamps"][0]["error"])
    s, out = R.call("GET", "/api/stamps/%d/download" % sid, raw=True); ok(s == 200 and len(out) > 10000, "solicitante baixa o vídeo com selo (%d bytes)" % len(out))
    outf = os.path.join(data, "selado.mp4")
    open(outf, "wb").write(out)
    s, j = R.call("GET", "/api/stamps/%d/manifest" % sid); ok(s == 403, "solicitante não vê o manifesto")
    s, j = A.call("GET", "/api/stamps/%d/manifest" % sid, raw=True); ok(s == 200 and b"HMAC-SHA256" in j, "admin baixa o manifesto assinado")
    s, kj = A.call("GET", "/api/stamps/%d/key" % sid); ok(s == 200 and kj["key"].startswith("VSI1:"), "chave QR")

    print("== Verificação pública (sem login)")
    s, j = P.call("POST", "/api/public/verify", open(outf, "rb").read(), "application/octet-stream")
    ok(s == 200 and j["present"] and j["integrity"] == "intact" and j["status"] == "valid", "vídeo selado: presente/íntegro/válido")
    ok("owner" not in json.dumps(j) and "Maria" not in json.dumps(j), "dados do autor continuam trancados")
    rec = os.path.join(data, "recomp.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", outf, "-c:v", "libx264", "-crf", "28", "-an", rec], check=True)
    s, j = P.call("POST", "/api/public/verify", open(rec, "rb").read(), "application/octet-stream")
    ok(s == 200 and j["present"] and j["integrity"] == "altered", "recompressão H.264 CRF 28: selo reconhecido, arquivo alterado")
    s, j = P.call("POST", "/api/public/verify", open(vid, "rb").read(), "application/octet-stream"); ok(s == 200 and not j["present"], "vídeo original: sem selo")
    s, j = P.call("POST", "/api/public/verify", {"sha256": __import__("hashlib").sha256(open(outf, "rb").read()).hexdigest()}); ok(s == 200 and j["present"], "verificação por hash")
    pid = j["ref"]
    s, j = P.call("GET", "/api/public/stamp/" + pid); ok(s == 200 and j["status"] == "valid", "consulta pública por ID (QR)")
    s, j = A.call("POST", "/api/stamps/%d/revoke" % sid); ok(s == 200, "admin revoga")
    s, j = P.call("POST", "/api/public/verify", open(outf, "rb").read(), "application/octet-stream"); ok(j["status"] == "revoked", "verificação mostra REVOGADO")
    s, j = A.call("POST", "/api/stamps/%d/restore" % sid); ok(s == 200, "admin restaura")
    s, j = P.call("POST", "/api/public/verify", open(outf, "rb").read(), "application/octet-stream"); ok(j["status"] == "valid", "verificação volta a VÁLIDO")
    s, j = R.call("POST", "/api/admin/unlock", {"key": kj["key"]}); ok(s == 403, "solicitante não destranca")
    s, j = A.call("POST", "/api/admin/unlock", {"key": kj["key"]}); ok(s == 200 and j["author"]["name"] == "Maria" and j["authorizer"]["name"] == "Admin", "admin destranca a linhagem completa")

    print("== Pedido de acesso, estatísticas, backup")
    s, j = P.call("POST", "/api/auth/request", {"name": "João", "email": "joao@x.com", "reason": "preciso selar vídeos"}); ok(s == 200, "pedido de acesso")
    s, j = A.call("GET", "/api/admin/requests"); rid = j["requests"][0]["id"]
    s, j = A.call("POST", "/api/admin/requests/%d/approve" % rid, {}); ok(s == 200 and j["token"], "admin aprova e gera token")
    s, j2 = P.call("POST", "/api/auth/register", {"token": j["token"], "name": "João", "email": "joao@x.com", "password": "senha-joao1"}); ok(s == 200, "João se cadastra com o token")
    s, j = A.call("GET", "/api/stats"); ok(s == 200 and j["stamps"].get("active") == 1 and j["processing"]["videos"] == 1 and j["verifications"]["total"] >= 5, "estatísticas do admin")
    s, j = A.call("GET", "/api/admin/events"); ok(s == 200 and len(j["events"]) > 5, "auditoria")
    s, j = A.call("GET", "/api/admin/backup", raw=True); ok(s == 200 and j[:15] == b"SQLite format 3", "backup do banco SQLite")
    s, j = A.call("PUT", "/api/admin/users/1", {"active": False}); ok(s == 409, "não desativa o último administrador")
    s, j = A.call("POST", "/api/auth/logout"); ok(s == 200, "logout")
    s, j = A.call("GET", "/api/me"); ok(s == 401, "sessão encerrada")
finally:
    srv.terminate()
    try:
        srv.wait(10)
    except Exception:
        srv.kill()
    log = srv.stdout.read() if srv.stdout else ""
    if "Traceback" in log:
        print("---- log do servidor ----\n" + log[-3000:])
    shutil.rmtree(data, ignore_errors=True)
print("\n%s" % ("TODOS OS TESTES PASSARAM" if not FAILS else "%d FALHA(S)" % FAILS))
sys.exit(1 if FAILS else 0)
