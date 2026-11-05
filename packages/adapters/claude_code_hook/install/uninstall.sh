#!/bin/sh
# Remove o adaptador e as entradas do PromptShield da política gerenciada (as demais chaves ficam intactas).
set -eu
ROOT=""; INSTALL_DIR="/usr/local/lib/promptshield"
while [ $# -gt 0 ]; do
  case "$1" in
    --root) ROOT=$2; shift 2;;
    --install-dir) INSTALL_DIR=$2; shift 2;;
    *) echo "opção desconhecida: $1" >&2; exit 2;;
  esac
done
case "$(uname -s)" in
  Darwin) SETTINGS="/Library/Application Support/ClaudeCode/managed-settings.json"; CONFIG="/Library/Application Support/PromptShield/claude-code-hook.json";;
  Linux)  SETTINGS="/etc/claude-code/managed-settings.json"; CONFIG="/etc/promptshield/claude-code-hook.json";;
  *) echo "sistema não suportado: $(uname -s)" >&2; exit 1;;
esac
WRAPPER="$INSTALL_DIR/promptshield-claude-hook"
if [ -f "$ROOT$SETTINGS" ]; then
  PS_WRAPPER="$WRAPPER" python3 - "$ROOT$SETTINGS" <<'PY'
import json, os, sys
path, wrapper = sys.argv[1], os.environ["PS_WRAPPER"]
data = json.load(open(path, encoding="utf-8"))
hooks = data.get("hooks", {})
for event in list(hooks):
    for g in hooks[event]:
        g["hooks"] = [h for h in g.get("hooks", []) if h.get("command") != wrapper]
    hooks[event] = [g for g in hooks[event] if g.get("hooks")]
    if not hooks[event]:
        del hooks[event]
if not hooks:
    data.pop("hooks", None)
json.dump(data, open(path, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
PY
fi
rm -rf "$ROOT$INSTALL_DIR/lib/promptshield_claude_hook" "$ROOT$WRAPPER" "$ROOT$CONFIG"
echo "removido. (allowManagedHooksOnly, se foi ligado, não é desligado automaticamente.)"
