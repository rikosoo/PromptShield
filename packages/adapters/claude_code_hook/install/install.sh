#!/bin/sh
# Instala o adaptador PromptShield para o Claude Code (Linux e macOS). Windows: NÃO implementado (ver README).
# Exige python3 (3.9 ou mais novo) na máquina e permissão de administrador para escrever em /etc ou /Library.
#
#   sudo ./install.sh --api-url https://api.exemplo.com.br --api-key ps_XXXX [--fail-mode open|closed]
#                     [--department Engenharia] [--install-dir DIR] [--root DIR] [--dry-run] [--managed-only-hooks]
#
# --root DIR      prefixo para teste: grava tudo sob DIR, sem tocar o sistema real
# --dry-run       só mostra o que faria
# --managed-only-hooks  liga allowManagedHooksOnly (bloqueia hooks de usuário, projeto e plugins: use com cuidado)
set -eu

API_URL=""; API_KEY=""; FAIL_MODE="open"; DEPT=""; ROOT=""; DRY=0; MANAGED_ONLY=0
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SRC="$HERE/../src/promptshield_claude_hook"
INSTALL_DIR="/usr/local/lib/promptshield"

while [ $# -gt 0 ]; do
  case "$1" in
    --api-url) API_URL=$2; shift 2;;
    --api-key) API_KEY=$2; shift 2;;
    --fail-mode) FAIL_MODE=$2; shift 2;;
    --department) DEPT=$2; shift 2;;
    --install-dir) INSTALL_DIR=$2; shift 2;;
    --root) ROOT=$2; shift 2;;
    --dry-run) DRY=1; shift;;
    --managed-only-hooks) MANAGED_ONLY=1; shift;;
    -h|--help) sed -n '2,12p' "$0"; exit 0;;
    *) echo "opção desconhecida: $1" >&2; exit 2;;
  esac
done

[ -n "$API_URL" ] && [ -n "$API_KEY" ] || { echo "informe --api-url e --api-key" >&2; exit 2; }
case "$FAIL_MODE" in open|closed) ;; *) echo "--fail-mode deve ser open ou closed" >&2; exit 2;; esac
command -v python3 >/dev/null 2>&1 || { echo "python3 não encontrado" >&2; exit 1; }
[ -d "$SRC" ] || { echo "código do adaptador não encontrado em $SRC" >&2; exit 1; }

case "$(uname -s)" in
  Darwin) SETTINGS_DIR="/Library/Application Support/ClaudeCode"; CONFIG_DIR="/Library/Application Support/PromptShield";;
  Linux)  SETTINGS_DIR="/etc/claude-code"; CONFIG_DIR="/etc/promptshield";;
  *) echo "sistema não suportado por este script: $(uname -s)" >&2; exit 1;;
esac
SETTINGS="$SETTINGS_DIR/managed-settings.json"
CONFIG="$CONFIG_DIR/claude-code-hook.json"
WRAPPER="$INSTALL_DIR/promptshield-claude-hook"

run() { if [ "$DRY" = 1 ]; then echo "[dry-run] $*"; else "$@"; fi; }
R() { printf '%s%s' "$ROOT" "$1"; }   # caminho real sob --root

echo "adaptador:   $INSTALL_DIR"
echo "configuração: $CONFIG   (modo de falha: $FAIL_MODE)"
echo "política gerenciada: $SETTINGS"

run mkdir -p "$(R "$INSTALL_DIR")/lib" "$(R "$CONFIG_DIR")" "$(R "$SETTINGS_DIR")"
run rm -rf "$(R "$INSTALL_DIR")/lib/promptshield_claude_hook"
run cp -R "$SRC" "$(R "$INSTALL_DIR")/lib/promptshield_claude_hook"

if [ "$DRY" = 0 ]; then
  cat > "$(R "$WRAPPER")" <<EOF
#!/bin/sh
PYTHONPATH="$INSTALL_DIR/lib\${PYTHONPATH:+:\$PYTHONPATH}" exec python3 -m promptshield_claude_hook "\$@"
EOF
  chmod 755 "$(R "$WRAPPER")"
  # a chave de ingestão precisa ser legível pelo usuário que roda o Claude Code (o hook roda como ele)
  PS_API_URL="$API_URL" PS_API_KEY="$API_KEY" PS_FAIL="$FAIL_MODE" PS_DEPT="$DEPT" python3 - "$(R "$CONFIG")" <<'PY'
import json, os, sys
cfg = {"api_url": os.environ["PS_API_URL"], "api_key": os.environ["PS_API_KEY"], "fail_mode": os.environ["PS_FAIL"],
       "timeout_seconds": 3, "integration_status": "partial"}
if os.environ.get("PS_DEPT"):
    cfg["department"] = os.environ["PS_DEPT"]
with open(sys.argv[1], "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)
    f.write("\n")
os.chmod(sys.argv[1], 0o644)
PY
else
  echo "[dry-run] gravaria $CONFIG e o wrapper $WRAPPER"
fi

# mescla os hooks na política gerenciada, preservando o que já existe; faz cópia de segurança
PS_WRAPPER="$WRAPPER" PS_FAIL="$FAIL_MODE" PS_DRY="$DRY" PS_MANAGED_ONLY="$MANAGED_ONLY" python3 - "$(R "$SETTINGS")" <<'PY'
import json, os, shutil, sys, time

path = sys.argv[1]
wrapper, fail, dry = os.environ["PS_WRAPPER"], os.environ["PS_FAIL"], os.environ["PS_DRY"] == "1"
data = {}
if os.path.exists(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not dry:
        shutil.copy2(path, f"{path}.bak-{time.strftime('%Y%m%d%H%M%S')}")

def entry(timeout):
    h = {"type": "command", "command": wrapper, "args": [], "timeout": timeout}
    if fail == "closed":
        h["onFailure"] = "block"   # exige Claude Code 2.1.295 ou mais novo
    return h

wanted = {"UserPromptSubmit": ({}, 10), "PreToolUse": ({"matcher": "*"}, 10), "PostToolUse": ({"matcher": "*"}, 10)}
hooks = data.setdefault("hooks", {})
for event, (extra, timeout) in wanted.items():
    groups = hooks.setdefault(event, [])
    # remove entradas antigas do PromptShield (reinstalação idempotente) e acrescenta a atual
    for g in groups:
        g["hooks"] = [h for h in g.get("hooks", []) if h.get("command") != wrapper]
    groups[:] = [g for g in groups if g.get("hooks")]
    groups.append({**extra, "hooks": [entry(timeout)]})
if os.environ["PS_MANAGED_ONLY"] == "1":
    data["allowManagedHooksOnly"] = True
out = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
if dry:
    print("[dry-run] managed-settings.json ficaria assim:\n" + out)
else:
    with open(path, "w", encoding="utf-8") as f:
        f.write(out)
PY

cat <<EOF

Pronto. Próximos passos:
  1. Teste a conexão:     PROMPTSHIELD_HOOK_CONFIG="$CONFIG" $WRAPPER check
  2. No Claude Code, rode /status e confirme "Enterprise managed settings (file)" em "Setting sources".
  3. Aviso à equipe: o hook envia prompts e ações dos agentes ao PromptShield. Comunique os colaboradores.
  4. Todas as políticas nascem em modo monitorar: nada é bloqueado até o administrador mudar para aplicar.
Atenção: a chave de API fica legível por todos os usuários da máquina (o hook roda como o usuário). Ela só envia eventos.
EOF
