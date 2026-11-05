#!/usr/bin/env bash
# Restaura um backup em um banco VAZIO já criado (ele nunca sobrescreve o banco em uso).
#   createdb promptshield_restaurado
#   infra/restore.sh /caminho/backup.dump "postgresql://dono:senha@host:5432/promptshield_restaurado"
# Confere a soma SHA-256 antes. O papel `promptshield_app` precisa existir no servidor (as migrações o criam).
set -euo pipefail
dump="${1:?uso: restore.sh ARQUIVO_DE_BACKUP URL_DO_BANCO_VAZIO}"
url="${2:?uso: restore.sh ARQUIVO_DE_BACKUP URL_DO_BANCO_VAZIO}"
url="${url/postgresql+psycopg:/postgresql:}"
if [ -f "$dump.sha256" ]; then ( cd "$(dirname "$dump")" && sha256sum --check "$(basename "$dump").sha256" ); else echo "AVISO: sem arquivo .sha256; integridade não conferida" >&2; fi
tables="$(psql "$url" -Atc "select count(*) from information_schema.tables where table_schema = 'public'")"
if [ "$tables" != "0" ]; then echo "recusado: o banco de destino não está vazio ($tables tabelas)" >&2; exit 2; fi
# Passa por SQL em vez de `pg_restore --dbname`: um pg_restore mais novo que o servidor (cliente 17+ contra servidor 16) escreve
# `SET transaction_timeout`, que o servidor mais antigo recusa e derruba a restauração. Tira só essa linha; qualquer outro erro para (ON_ERROR_STOP).
pg_restore --no-password -f - "$dump" | sed '/^SET transaction_timeout = /d' | psql "$url" --no-password -q -v ON_ERROR_STOP=1 -o /dev/null -f -
echo "restaurado em $url"
