#!/usr/bin/env bash
# Instalador do PromptShield (Linux e macOS). Seguro para rodar de novo: não apaga dados e mantém o .env existente.
#   bash instalar.sh
# Sem terminal interativo, informe PS_EMPRESA e PS_ADMIN_EMAIL no ambiente.
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\n== %s ==\n' "$*"; }
die() { printf '\nERRO: %s\n' "$*" >&2; exit 1; }
rnd() { head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n'; }
key32() { head -c 32 /dev/urandom | base64 | tr '+/' '-_' | tr -d '\n'; }

say "1/7 Conferindo os requisitos"
command -v docker >/dev/null 2>&1 || die "Docker não encontrado. Instale o Docker Engine (https://docs.docker.com/engine/install/) e rode de novo."
if docker info >/dev/null 2>&1; then D="docker"; elif sudo -n docker info >/dev/null 2>&1; then D="sudo docker"; else
  die "Sem permissão no Docker. Rode com um usuário do grupo 'docker' (sudo usermod -aG docker \$USER e entre de novo) ou com sudo."
fi
$D compose version >/dev/null 2>&1 || die "Docker Compose v2 não encontrado (o comando 'docker compose version' precisa funcionar)."
if [ -r /proc/meminfo ]; then
  mem_mb=$(awk '/MemTotal/ {printf "%d", $2/1024}' /proc/meminfo)
  [ "$mem_mb" -ge 3500 ] || printf 'AVISO: este servidor tem %s MB de memória; o recomendado é 4 GB ou mais.\n' "$mem_mb"
fi
echo "Docker e Compose encontrados."

say "2/7 Conferindo a integridade dos arquivos do pacote"
if command -v sha256sum >/dev/null 2>&1; then sha256sum -c SHA256SUMS --quiet || die "Algum arquivo do pacote não confere com o SHA256SUMS. Baixe o pacote de novo e compare o SHA-256 com o informado pelo fornecedor."
elif command -v shasum >/dev/null 2>&1; then shasum -a 256 -c SHA256SUMS --quiet || die "Algum arquivo do pacote não confere com o SHA256SUMS."
else echo "AVISO: sem sha256sum/shasum; a conferência dos arquivos foi pulada."; fi
echo "Arquivos conferidos."

say "3/7 Configuração (.env)"
if [ -f .env ]; then
  echo ".env já existe: mantido (as senhas e chaves não mudam)."
  grep -q '^PS_VERSION=' .env && sed -e "s|^PS_VERSION=.*|PS_VERSION=$(cat VERSION)|" .env > .env.novo && mv .env.novo .env
else
  umask 077
  sed -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(rnd)|" -e "s|^APP_DB_PASSWORD=.*|APP_DB_PASSWORD=$(rnd)|" \
      -e "s|^LOCAL_AUTH_SECRET=.*|LOCAL_AUTH_SECRET=$(rnd)$(rnd)|" -e "s|^ORIGINAL_TEXT_MASTER_KEY=.*|ORIGINAL_TEXT_MASTER_KEY=$(key32)|" env.example > .env
  chmod 600 .env
  echo ".env criado com senhas e chaves aleatórias. GUARDE uma cópia dele em lugar seguro."
fi

say "4/7 Imagens"
shopt -s nullglob
imgs=(imagens/*.tar imagens/*.tar.gz)
if [ "${#imgs[@]}" -gt 0 ]; then for f in "${imgs[@]}"; do echo "Carregando $f (pode levar alguns minutos)..."; $D load -i "$f" >/dev/null; done
else echo "Este pacote não traz imagens: elas serão construídas a partir das fontes (precisa de internet, leva vários minutos)."; fi

say "5/7 Subindo o PromptShield"
$D compose up -d

say "6/7 Aguardando a API"
port=$(grep -E '^API_PORT=' .env | tail -1 | cut -d= -f2-); port=${port:-8000}
ok=0
for _ in $(seq 1 100); do
  if curl -fsS "http://localhost:$port/health" >/dev/null 2>&1; then ok=1; break; fi
  sleep 3
done
[ "$ok" = 1 ] || die "A API não respondeu em 5 minutos. Veja: $D compose logs --tail 50 api"
echo "API no ar."

say "7/7 Primeiro acesso"
web_port=$(grep -E '^WEB_PORT=' .env | tail -1 | cut -d= -f2-); web_port=${web_port:-3000}
base=$(grep -E '^PUBLIC_BASE_URL=' .env | tail -1 | cut -d= -f2-); base=${base:-http://localhost:$web_port}
if [ -f .instalado ]; then
  echo "O primeiro acesso já foi configurado antes. Console: $base"
  exit 0
fi
empresa="${PS_EMPRESA:-}"; email="${PS_ADMIN_EMAIL:-}"
if [ -z "$empresa" ] || [ -z "$email" ]; then
  [ -t 0 ] || die "Sem terminal interativo: informe PS_EMPRESA e PS_ADMIN_EMAIL no ambiente."
  [ -n "$empresa" ] || read -r -p "Nome da sua empresa: " empresa
  [ -n "$email" ] || read -r -p "E-mail do administrador (é o seu login): " email
fi
[ -n "$empresa" ] || die "Informe o nome da empresa."
printf '%s' "$email" | grep -Eq '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$' || die "E-mail inválido: $email"
slug=$(printf '%s' "$empresa" | tr '[:upper:]' '[:lower:]' | sed -e 's/[^a-z0-9]\{1,\}/-/g' -e 's/^-//' -e 's/-$//' | cut -c1-60); slug=${slug:-empresa}
$D compose exec -T api python -m app.cli create-tenant --name "$empresa" --slug "$slug" --admin-email "$email" >/dev/null \
  || die "Não consegui criar a empresa (ela já existe?). Para definir a senha do administrador: $D compose exec api python -m app.cli set-password --email $email"
saida=$($D compose exec -T api python -m app.cli set-password --email "$email" --generate)
senha=${saida##*: }
date +%F > .instalado

cat <<FIM

============================================================
PromptShield instalado.

  Console:  $base
  Login:    $email
  Senha temporária (aparece SÓ agora; você troca ao entrar):
            $senha

Próximos passos:
  1. Abra o console, entre e defina a sua senha.
  2. Em "Licença", informe o CÓDIGO DE ATIVAÇÃO que o fornecedor enviou (por outro canal).
  3. Em "Dispositivos", conecte as máquinas dos funcionários.
Leia o LEIA-ME.md para HTTPS, backup e a validação com o fornecedor.
============================================================
FIM
