#!/usr/bin/env bash
# Sobe o PromptShield em UMA máquina Linux (Debian/Ubuntu) para TESTE, sem depender de provedor de nuvem.
#   ./infra/vm-setup.sh --admin-email voce@exemplo.com [--name "Teste"] [--slug teste]
# O que faz: instala Docker (se faltar), cria .env com segredos aleatórios (OIDC mock, SÓ para teste),
# sobe tudo com as portas em 127.0.0.1 e cria um tenant. A chave ps_... aparece UMA vez.
# Acesse por túnel SSH (docs/teste-vm.md). NÃO use em máquina com portas abertas à internet.
# Status: NÃO EXECUTADO em máquina real (ver docs/roteiro-testes-reais.md, passo 0).
set -euo pipefail
EMAIL=""; NAME="Teste"; SLUG="teste"
while [ $# -gt 0 ]; do
  case "$1" in
    --admin-email) EMAIL=$2; shift 2;;
    --name) NAME=$2; shift 2;;
    --slug) SLUG=$2; shift 2;;
    -h|--help) sed -n '2,8p' "$0"; exit 0;;
    *) echo "opção desconhecida: $1" >&2; exit 2;;
  esac
done
[ -n "$EMAIL" ] || { echo "informe --admin-email" >&2; exit 2; }
cd "$(dirname "$0")/.."

if ! command -v docker >/dev/null 2>&1; then
  echo "Instalando Docker (apt)..."
  sudo apt-get update -y && sudo apt-get install -y docker.io docker-compose-v2 openssl
  sudo systemctl enable --now docker
fi
DOCKER="docker"; docker info >/dev/null 2>&1 || DOCKER="sudo docker"   # sem grupo docker ainda: usa sudo

if [ ! -f .env ]; then
  # .env novo + volume do banco antigo = senha do banco não confere (o Postgres só lê a senha na primeira criação do volume)
  if $DOCKER volume ls -q 2>/dev/null | grep -q 'pgdata$'; then
    echo "RECUSADO: já existe um volume de banco de uma instalação anterior, e este .env teria senhas novas." >&2
    echo "Se os dados são de teste e podem ser apagados: $DOCKER compose down -v  e rode este script de novo." >&2
    exit 1
  fi
  cp .env.example .env
  rnd() { openssl rand -hex 24; }
  sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$(rnd)/; s/^APP_DB_PASSWORD=.*/APP_DB_PASSWORD=$(rnd)/; \
          s/^OIDC_MODE=.*/OIDC_MODE=mock/; s/^OIDC_MOCK_SECRET=.*/OIDC_MOCK_SECRET=$(openssl rand -hex 32)/; s/^AUTH_MODE=.*/AUTH_MODE=mock/" .env
  chmod 600 .env
  echo ".env criado com segredos aleatórios (modo de login MOCK: só para teste)."
fi
if grep -Eq '^(WEB_BIND|API_BIND)=' .env 2>/dev/null && ! grep -q '^EXPOSE_CONFIRMED=1' .env; then
  echo "RECUSADO: WEB_BIND/API_BIND no .env expõem as portas sem a confirmação de infra/expose.sh. Com OIDC mock isso deixa qualquer um entrar." >&2; exit 1
fi

$DOCKER compose up --build -d
echo "Aguardando a API ficar saudável..."
for _ in $(seq 1 60); do
  if $DOCKER compose exec -T api python -c "import urllib.request as u; u.urlopen('http://localhost:8000/health')" >/dev/null 2>&1; then ok=1; break; fi
  sleep 3
done
[ "${ok:-0}" = 1 ] || { echo "A API não ficou saudável. Veja: $DOCKER compose logs api" >&2; exit 1; }
$DOCKER compose exec -T api python -m app.cli create-tenant --name "$NAME" --slug "$SLUG" --admin-email "$EMAIL"
echo
echo "Pronto. COPIE a chave ps_... acima: ela não aparece de novo."
echo "No seu computador: ssh -N -L 8000:localhost:8000 -L 3000:localhost:3000 usuario@IP_DA_VM"
