#!/usr/bin/env bash
# Abre o console (e, se pedir, a API) da VM de TESTE para fora, SEM túnel. O banco nunca é exposto.
#   ./infra/expose.sh --public-ip 3.134.84.250 --web          # só o console (porta WEB_PORT do .env, padrão 3000)
#   ./infra/expose.sh --public-ip 3.134.84.250 --web --api    # também a API (porta API_PORT do .env, padrão 8000; veja o aviso)
#   ./infra/expose.sh --close                                 # volta para 127.0.0.1 (só túnel)
# Para usar portas altas, defina WEB_PORT e API_PORT no .env ANTES (ex.: 13000 e 18000; evite 32768-60999, que o Linux usa para conexões de saída).
# Pré-requisito que NÃO é deste script: no firewall da nuvem, libere a porta do console (e da API) SÓ para o seu IP.
# Riscos (leia): o login do console está em modo MOCK (qualquer pessoa que alcançar a porta entra com um e-mail cadastrado) e o tráfego
# é HTTP sem cifra. O console só mostra texto mascarado, mas o HOOK envia o texto ORIGINAL dos prompts para a API: se você expuser
# a API em HTTP, esse texto cruza a internet sem cifra. Por isso a API não é aberta a menos que você peça (--api).
# Status: NÃO EXECUTADO em máquina real.
set -euo pipefail
IP=""; WEB=0; API=0; CLOSE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --public-ip) IP=$2; shift 2;;
    --web) WEB=1; shift;;
    --api) API=1; shift;;
    --close) CLOSE=1; shift;;
    -h|--help) sed -n '2,12p' "$0"; exit 0;;
    *) echo "opção desconhecida: $1" >&2; exit 2;;
  esac
done
cd "$(dirname "$0")/.."
[ -f .env ] || { echo "sem .env: rode ./infra/vm-setup.sh primeiro" >&2; exit 1; }
DOCKER="docker"; docker info >/dev/null 2>&1 || DOCKER="sudo docker"
setenv() { if grep -q "^$1=" .env; then sed -i "s#^$1=.*#$1=$2#" .env; else echo "$1=$2" >> .env; fi; }
unsetenv() { sed -i "/^$1=/d" .env; }
getenv() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- | tr -d '\r"' || true; }
WEB_PORT="$(getenv WEB_PORT)"; WEB_PORT="${WEB_PORT:-3000}"
API_PORT="$(getenv API_PORT)"; API_PORT="${API_PORT:-8000}"
for pv in "$WEB_PORT" "$API_PORT"; do
  case "$pv" in ''|*[!0-9]*) echo "porta inválida no .env: '$pv' (use só números, de 1024 a 65535)" >&2; exit 2;; esac
  [ "$pv" -ge 1024 ] && [ "$pv" -le 65535 ] || { echo "porta fora de 1024-65535: $pv" >&2; exit 2; }
done
[ "$WEB_PORT" != "$API_PORT" ] || { echo "WEB_PORT e API_PORT não podem ser iguais ($WEB_PORT)" >&2; exit 2; }

if [ "$CLOSE" = 1 ]; then
  for k in WEB_BIND API_BIND EXPOSE_CONFIRMED; do unsetenv "$k"; done
  setenv PUBLIC_BASE_URL "http://localhost:$WEB_PORT"
  $DOCKER compose up -d
  echo "Fechado: portas só em 127.0.0.1. Use o túnel SSH."
  exit 0
fi
[ -n "$IP" ] && [ "$WEB$API" != "00" ] || { echo "informe --public-ip IP e --web e/ou --api" >&2; exit 2; }
ABRIR=""; PORTAS=""
if [ "$WEB" = 1 ]; then ABRIR="o console ($WEB_PORT)"; PORTAS="$WEB_PORT"; fi
if [ "$API" = 1 ]; then ABRIR="${ABRIR:+$ABRIR e }a API ($API_PORT)"; PORTAS="${PORTAS:+$PORTAS e }$API_PORT"; fi
echo "ATENÇÃO: você vai abrir $ABRIR em http://$IP"
echo "  1. O firewall da nuvem DEVE limitar essas portas ao SEU IP."
echo "  2. Login MOCK: quem alcançar a porta entra como qualquer e-mail cadastrado."
if [ "$API" = 1 ]; then
  echo "  3. HTTP sem cifra. A API recebe o texto ORIGINAL dos prompts: ele cruzaria a internet sem cifra."
else
  echo "  3. HTTP sem cifra."
fi
read -r -p "Digite 'entendi' para continuar: " ok
[ "$ok" = "entendi" ] || { echo "cancelado"; exit 1; }
setenv EXPOSE_CONFIRMED 1
[ "$WEB" = 1 ] && setenv WEB_BIND 0.0.0.0 && setenv PUBLIC_BASE_URL "http://$IP:$WEB_PORT"
[ "$API" = 1 ] && setenv API_BIND 0.0.0.0
$DOCKER compose up -d
echo "Pronto."
[ "$WEB" = 1 ] && echo "Console: http://$IP:$WEB_PORT"
[ "$API" = 1 ] && echo "API: http://$IP:$API_PORT (use este endereço como api_url do hook)"
echo "Firewall da nuvem: libere TCP $PORTAS só para o seu IP."
echo "Para voltar ao modo seguro: ./infra/expose.sh --close"
