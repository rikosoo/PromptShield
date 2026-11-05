#!/usr/bin/env bash
# Backup lógico do banco do PromptShield (formato custom do pg_dump) com soma SHA-256.
#   infra/backup.sh "postgresql://dono:senha@host:5432/promptshield" /caminho/backup.dump
# Use a URL do DONO do banco (não a do papel restrito: ele não enxerga todas as linhas por causa da RLS).
# ATENÇÃO: o backup NÃO inclui a chave mestra (ORIGINAL_TEXT_MASTER_KEY). Guarde-a em outro lugar, com outro controle de acesso:
# sem ela os textos originais cifrados e os segredos de canais do backup não podem ser lidos (isso é proposital).
set -euo pipefail
url="${1:?uso: backup.sh URL_DO_BANCO ARQUIVO_DE_SAIDA}"
out="${2:?uso: backup.sh URL_DO_BANCO ARQUIVO_DE_SAIDA}"
url="${url/postgresql+psycopg:/postgresql:}"
umask 077
pg_dump --format=custom --no-password "$url" --file "$out"
( cd "$(dirname "$out")" && sha256sum "$(basename "$out")" > "$(basename "$out").sha256" )
echo "backup gravado em $out ($(du -h "$out" | cut -f1)); soma em $out.sha256"
