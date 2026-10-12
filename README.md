# VSI Platform · M3D Stamp

Sistema multiusuário para emitir, gerenciar e verificar **selos de autenticidade em vídeo**.
Servidor em Python (somente biblioteca padrão) + banco **SQLite** + interface web.
O processamento de vídeo (esteganografia DCT + selo visível + manifesto assinado) usa OpenCV/NumPy/ffmpeg.

## Instalação rápida (copiar para o servidor e abrir no navegador)

```bash
# 1) copie a pasta para o servidor
scp -r vsi_platform usuario@servidor:/opt/

# 2) (opcional, para processar vídeos) dependências
sudo apt install -y python3 python3-venv ffmpeg
cd /opt/vsi_platform && python3 -m venv venv && ./venv/bin/pip install -r requirements.txt

# 3) inicie
./venv/bin/python vsi_server.py --host 0.0.0.0 --port 8080
```

O terminal mostra o **CÓDIGO DE INSTALAÇÃO** (também em `data/INSTALL_CODE.txt`).
Abra `http://SERVIDOR:8080` → o **autoinstalador**:
1. verifica o ambiente (Python, SQLite, permissões, espaço, ffmpeg/OpenCV/NumPy);
2. pede o código, o nome do sistema, a URL pública e cria a **conta administradora**;
3. cria o banco `data/vsi.db`, a chave secreta e desativa o instalador.

Sem `ffmpeg`/OpenCV/NumPy o sistema funciona (usuários, convites, registro, auditoria), mas **não** processa vídeos
nem lê selos em arquivos. Instale depois e reinicie.

## Produção (recomendado)

* Rode atrás de **HTTPS** (nginx: `nginx.conf.example`) e marque "cookies seguros" no instalador/Configurações.
* Serviço systemd: `vsi-platform.service` (ajuste caminhos/usuário). `--data /var/lib/vsi` guarda tudo fora do código.
* **Backup**: copie a pasta `data/` (ou use *Configurações → Baixar backup do banco*). Contém o banco, `config.json` (chave secreta) e os vídeos.
* Atualizar: substitua os arquivos do programa e reinicie; o banco e `data/` permanecem.

## Perfis

| Perfil | Pode |
|---|---|
| Visitante (sem login) | Verificar um vídeo: selo **presente/ausente**, **íntegro/alterado**, **válido/revogado**. Dados do autor ficam trancados. |
| Solicitante / Autor | Enviar vídeos, escolher o modelo e as transformações suportadas, acompanhar e **baixar o vídeo com selo**. Vê só os próprios selos. |
| Autorizador / Admin | Tudo acima + aprovar/rejeitar, **revogar/restaurar**, ver manifesto assinado, **destrancar a chave QR**, estatísticas, usuários, convites e pedidos de acesso, modelos de selo, auditoria, configurações e backup. |

Cadastro: só com **token de convite** (gerado por um administrador) ou após **pedido de acesso** aprovado.

## Como o selo funciona

* O original **nunca é alterado**: o selo vai numa cópia nova (`*_selo.mp4`) com o áudio original.
* Camadas: SHA-256 + data, **esteganografia DCT** invisível (chave secreta do servidor), selo visível no canto
  inferior esquerdo e **manifesto assinado** (HMAC-SHA256). Opcional: chave QR nos metadados do MP4 (só Admin).
* O solicitante escolhe **na hora de emitir** o que o selo deve suportar: *conversão/recompressão*, *+ redimensionamento*
  ou *+ corte* (deslocamento múltiplo de 8 px). Transformações não previstas **não mantêm** o selo invisível.
* A verificação pública reconhece o selo mesmo em cópia convertida/recompactada (marcando "ALTERADO"), sem expor dados.

## Segurança

Senhas com scrypt · sessão em cookie HttpOnly + token CSRF · bloqueio após 5 tentativas · limite de taxa
(login, token, verificação) · CSP e cabeçalhos de segurança · verificação de Origin · uploads com nome aleatório e limite
de tamanho · convites guardados só como hash · auditoria de eventos. O instalador exige o código do terminal e se desativa após o uso.

## API (resumo)

`GET /api/public/info` · `POST /api/public/verify` (corpo = vídeo, ou JSON `{"sha256":…}`) · `GET /api/public/stamp/<id>` ·
`POST /api/auth/login|logout|token|register|request|password` · `GET/POST /api/stamps…` · `/api/badges` · `/api/stats` ·
`/api/admin/{users,invites,requests,events,settings,backup,unlock}`.

## Testes

`python3 test_api.py` sobe um servidor temporário e roda ~55 verificações de ponta a ponta (instalação, permissões,
upload, processamento, verificação pública, revogação, backup).

## Arquivos

`vsi_server.py` servidor + instalador + API · `static/` interface · `vsi_stego.py` motor de selos · `vsi_convert.py` conversor WebM→MP4
com proveniência (uso em linha de comando) · `test_api.py` testes.
