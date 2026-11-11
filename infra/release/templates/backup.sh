#!/usr/bin/env bash
# Backup do PromptShield: banco, .env e a identidade da licença. Guarde a pasta backups/ FORA deste servidor.
set -euo pipefail
cd "$(dirname "$0")"
if docker info >/dev/null 2>&1; then D="docker"; else D="sudo docker"; fi
mkdir -p backups
umask 077
stamp="$(date +%F-%H%M)"
$D compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > "backups/banco-$stamp.dump"
[ -s "backups/banco-$stamp.dump" ] || { echo "ERRO: o backup do banco saiu vazio" >&2; rm -f "backups/banco-$stamp.dump"; exit 1; }
cp .env "backups/env-$stamp"
$D compose exec -T api tar czf - -C /var/lib/promptshield . > "backups/licenca-$stamp.tgz"       # identidade da licença: sem ela a instalação vira "não ativada"
( cd backups && sha256sum "banco-$stamp.dump" "licenca-$stamp.tgz" "env-$stamp" > "soma-$stamp.sha256" ) 2>/dev/null || true
echo "Backup gravado em backups/ ($stamp): banco, .env e identidade da licença."
echo "Guarde essa pasta fora deste servidor. A chave dos textos originais está no .env: guarde-a separada do banco."
