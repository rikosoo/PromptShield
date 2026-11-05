#!/usr/bin/env bash
# Atualiza o PromptShield numa VM de TESTE: backup, código novo, build, subida e verificação.
# Diferente do atualizar-vm.sh: cada passo mostra o que está fazendo e tem TEMPO LIMITE, então nada fica parado em silêncio.
#
#   bash infra/atualizar.sh                    # atualiza a branch em que a VM já está
#   bash infra/atualizar.sh minha-branch       # atualiza outra branch
#   bash infra/atualizar.sh --sem-backup       # pula o backup do banco (só use com dados de teste que você aceita perder)
#
# Nunca apaga o banco (não usa "down -v"). Se um passo estourar o tempo, o script PARA e diz qual foi e o que olhar.
set -uo pipefail

BACKUP=1
BRANCH=""
while [ $# -gt 0 ]; do
  case "$1" in
    --sem-backup) BACKUP=0; shift;;
    -h|--help) sed -n '2,10p' "$0"; exit 0;;
    -*) echo "opção desconhecida: $1" >&2; exit 2;;
    *) BRANCH=$1; shift;;
  esac
done

cd "$(dirname "$0")/.." || exit 1
[ -n "$BRANCH" ] || BRANCH=$(git rev-parse --abbrev-ref HEAD)

say()  { printf '\n== %s ==\n' "$*"; }
fail() { printf '\nPAROU: %s\n' "$*" >&2; exit 1; }

# docker: com sudo se o usuário ainda não está no grupo docker
if timeout 20 docker info >/dev/null 2>&1; then D="docker"; else D="sudo docker"; echo "(usando sudo para o docker)"; fi
DC="$D compose"
API_PORT=$(grep -E '^API_PORT=' .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '\r"')
API_PORT=${API_PORT:-8000}
BK_T=${PS_BACKUP_TIMEOUT:-120}     # segundos; mude só para testar o script

say "0/6 Estado da máquina"
free -m 2>/dev/null | sed -n '1,2p'
df -h / 2>/dev/null | sed -n '1,2p'
timeout 30 $DC ps || echo "(aviso: 'docker compose ps' não respondeu em 30 s; o Docker pode estar sem memória)"

say "1/6 Backup (até $((BK_T / 60)) min)"
mkdir -p "$HOME/backups"
STAMP=$(date +%F-%H%M)
if [ -f .env ]; then cp .env "$HOME/backups/env-$STAMP" && chmod 600 "$HOME/backups/env-$STAMP"; echo "cópia do .env: $HOME/backups/env-$STAMP"; else echo "sem .env para copiar"; fi
if [ "$BACKUP" = 0 ]; then
  echo "backup do banco PULADO (--sem-backup)"
else
  OUT="$HOME/backups/db-$STAMP.dump"
  # </dev/null: o docker não fica esperando teclado; timeout: nunca fica parado para sempre
  if timeout "$BK_T" $DC exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' </dev/null >"$OUT" 2>"$OUT.err"; then
    if [ -s "$OUT" ]; then echo "backup do banco: $OUT ($(du -h "$OUT" | cut -f1))"; rm -f "$OUT.err"
    else rm -f "$OUT"; fail "o backup saiu vazio. Veja $OUT.err. Se o banco ainda não existe (primeira subida), use --sem-backup."; fi
  else
    code=$?
    [ "$code" = 124 ] && fail "o backup passou de $BK_T s (banco travado ou máquina sem memória). Veja: $DC ps ; free -m ; $DC logs --tail 30 db. Para seguir sem backup (dados de teste): bash infra/atualizar.sh --sem-backup"
    fail "o backup falhou (código $code). Veja $OUT.err. Para seguir sem backup (dados de teste): bash infra/atualizar.sh --sem-backup"
  fi
fi

say "2/6 Código (branch $BRANCH)"
timeout 120 git fetch origin "$BRANCH" || fail "não consegui baixar a branch (rede, ou o repositório é privado e pediu senha). Rode: git fetch origin $BRANCH"
git checkout "$BRANCH" || fail "não consegui trocar para a branch $BRANCH (há alterações locais? veja: git status)"
timeout 120 git pull --ff-only origin "$BRANCH" || fail "git pull não conseguiu avançar sem conflito. Veja: git status"
git log --oneline -1

say "3/6 Build (um serviço por vez, baixa prioridade; pode levar vários minutos)"
export COMPOSE_PARALLEL_LIMIT=1
for svc in api worker web; do
  echo "-- build $svc ($(date +%H:%M:%S))"
  timeout 1500 nice -n 10 $DC build "$svc" || fail "o build de '$svc' falhou ou passou de 25 minutos. Veja a mensagem acima; falta de memória aparece como 'Killed'."
  sync
done

say "4/6 Subindo"
timeout 300 $DC up -d || fail "docker compose up não terminou. Veja: $DC ps ; $DC logs --tail 50 api"

say "5/6 Aguardando a API (até 2 minutos)"
ok=0
for i in $(seq 1 40); do
  if curl -fsS "localhost:$API_PORT/health" >/dev/null 2>&1; then ok=1; echo "API respondeu."; break; fi
  sleep 3
done
[ "$ok" = 1 ] || fail "a API não respondeu. Veja: $DC logs --tail 50 api"

say "6/6 Verificação"
timeout 30 $DC ps
echo "-- sensor servido (versão e hash):"
curl -fsS "localhost:$API_PORT/sensor/manifest.json" || echo "(manifest indisponível)"
echo
echo "Pronto. Backup do banco: ${OUT:-nenhum}. Recarregue o console no navegador (Ctrl+F5)."
