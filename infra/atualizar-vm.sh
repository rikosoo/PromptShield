#!/usr/bin/env bash
# Atualiza o PromptShield numa VM (teste): backup -> git pull -> rebuild -> verificacao.
# Uso:  bash infra/atualizar-vm.sh [branch]      (padrao: claude/wonderful-hamilton-9dsk59)
# Nunca apaga o banco (nao usa "down -v").
set -euo pipefail

BRANCH="${1:-claude/wonderful-hamilton-9dsk59}"
cd "$(dirname "$0")/.."

# Sem permissao no socket do Docker? Usa sudo (ou: sudo usermod -aG docker $USER e entre de novo no SSH).
if docker info >/dev/null 2>&1; then D="docker"; else D="sudo docker"; echo "(usando sudo para o docker)"; fi
DC="$D compose"

echo "== 1/5 Backup =="
mkdir -p "$HOME/backups"
STAMP=$(date +%F-%H%M)
cp .env "$HOME/backups/env-$STAMP" 2>/dev/null || echo "sem .env para copiar"
RUNNING=$($DC ps --status running 2>/dev/null || true)
if printf "%s" "$RUNNING" | grep -q db; then
  $DC exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > "$HOME/backups/db-$STAMP.dump" \
    && echo "backup do banco: $HOME/backups/db-$STAMP.dump ($(du -h "$HOME/backups/db-$STAMP.dump" | cut -f1))" \
    || { echo "ERRO no backup; parei antes de mudar qualquer coisa."; exit 1; }
else
  echo "banco nao esta rodando; sem backup (primeira subida?)."
fi

echo "== 2/5 Codigo =="
git fetch origin "$BRANCH"
git checkout "$BRANCH"
git pull origin "$BRANCH"
git log --oneline -1

echo "== 3/5 Build (um servico por vez, baixa prioridade: poupa a memoria de VMs pequenas) =="
export COMPOSE_PARALLEL_LIMIT=1
for svc in api worker web; do
  echo "-- build $svc"
  nice -n 10 $DC build "$svc"
  sync; sleep 2
done
echo "-- subindo"
$DC up -d

echo "== 4/5 Aguardando a API =="
for i in $(seq 1 40); do
  if curl -fsS localhost:"${API_PORT:-8000}"/health >/dev/null 2>&1; then echo "API respondeu."; break; fi
  sleep 3
  [ "$i" = 40 ] && { echo "API nao respondeu. Veja: $DC logs api | tail -50"; exit 1; }
done

echo "== 5/5 Verificacao =="
$DC ps
echo "-- migracoes aplicadas (esperado ate 0017):"
LOGS=$($DC logs api 2>/dev/null || true)
printf "%s\n" "$LOGS" | grep "Running upgrade" | tail -3 || true
echo "-- versao do sensor servida:"
curl -fsS localhost:"${API_PORT:-8000}"/sensor/manifest.json || true
echo
echo "Pronto. Abra o console e confira o menu: Sensores, Qualidade da deteccao, Licenca."
