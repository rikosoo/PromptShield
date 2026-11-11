#!/usr/bin/env bash
# Atualização ASSISTIDA do PromptShield (Linux e macOS). Nada é instalado sozinho: o administrador aprovou o download no console
# (Administração > Atualizações) e roda este script no servidor.
#   bash atualizar.sh
# O que ele faz, nesta ordem: confere o arquivo baixado (SHA-256) e o conteúdo (SHA256SUMS) -> faz backup -> guarda os arquivos atuais
# em anterior/<versão>/ -> troca os arquivos do pacote (o .env, os dados e a licença ficam) -> sobe a versão nova -> confere a versão que a API informa.
set -euo pipefail
# o script troca os próprios arquivos no meio do caminho: roda a partir de uma cópia temporária para o bash não ler um arquivo que mudou
if [ -z "${PS_ATUALIZANDO:-}" ]; then
  tmp=$(mktemp); cp "$0" "$tmp"
  PS_ATUALIZANDO=1 PS_DIR="$(cd "$(dirname "$0")" && pwd)" exec bash "$tmp" "$@"
fi
cd "$PS_DIR"

say() { printf '\n== %s ==\n' "$*"; }
die() { printf '\nERRO: %s\n' "$*" >&2; exit 1; }
field() { printf '%s' "$1" | grep -o "\"$2\": \"[^\"]*\"" | head -1 | cut -d'"' -f4 || true; }

say "1/6 Conferindo o servidor"
[ -f .env ] && [ -f .instalado ] && [ -f VERSION ] || die "esta pasta não é uma instalação em uso (faltam .env, .instalado ou VERSION). Rode a atualização na pasta onde o PromptShield foi instalado."
command -v docker >/dev/null 2>&1 || die "Docker não encontrado."
if docker info >/dev/null 2>&1; then D="docker"; elif sudo -n docker info >/dev/null 2>&1; then D="sudo docker"; else die "Sem permissão no Docker (use um usuário do grupo 'docker' ou sudo)."; fi
atual=$(tr -d '[:space:]' < VERSION)
info=$($D compose exec -T api python -m app.cli update-ready 2>/dev/null) || die "Não há atualização pronta. No console, em Administração > Atualizações, aprove o download e espere o status «Pronta para instalar»."
novo=$(field "$info" version); arq=$(field "$info" file); soma=$(field "$info" sha256); caminho=$(field "$info" path)
printf '%s' "$novo" | grep -Eq '^[0-9]+(\.[0-9]+)+([.-][A-Za-z][0-9A-Za-z]*)?$' || die "versão inválida informada pela API: $novo"
printf '%s' "$arq" | grep -Eq '^promptshield-onprem-[0-9A-Za-z.-]+\.zip$' || die "nome de arquivo inesperado: $arq"
printf '%s' "$soma" | grep -Eq '^[0-9a-f]{64}$' || die "SHA-256 inválido informado pela API."
case "$caminho" in /var/lib/promptshield/updates/"$arq") ;; *) die "caminho inesperado: $caminho";; esac
[ "$novo" != "$atual" ] || die "a versão $novo já está instalada."
# versões com sufixo (ex.: 0.4.0-rc1) têm ordem própria, que o servidor já conferiu; a checagem simples vale para as numéricas
if ! printf '%s%s' "$atual" "$novo" | grep -q '[A-Za-z]'; then
  [ "$(printf '%s\n%s\n' "$atual" "$novo" | sort -V | tail -1)" = "$novo" ] || die "a versão $novo não é maior que a instalada ($atual). Não se volta atrás."
fi
echo "Versão instalada: $atual. Versão a instalar: $novo."

say "2/6 Trazendo e conferindo o arquivo"
rm -rf atualizacao && mkdir -p atualizacao
$D compose cp "api:$caminho" "atualizacao/$arq" || die "Não consegui copiar o arquivo do servidor."
if command -v sha256sum >/dev/null 2>&1; then calc=$(sha256sum "atualizacao/$arq" | cut -d' ' -f1); else calc=$(shasum -a 256 "atualizacao/$arq" | cut -d' ' -f1); fi
[ "$calc" = "$soma" ] || die "O SHA-256 do arquivo ($calc) não confere com o que o servidor conferiu ($soma). Nada foi alterado."
if command -v unzip >/dev/null 2>&1; then unzip -q "atualizacao/$arq" -d atualizacao/novo
elif command -v python3 >/dev/null 2>&1; then python3 -m zipfile -e "atualizacao/$arq" atualizacao/novo
else die "Instale 'unzip' (ou python3) para abrir o pacote."; fi
novo_dir="atualizacao/novo/${arq%.zip}"
[ -d "$novo_dir" ] && [ "$(tr -d '[:space:]' < "$novo_dir/VERSION")" = "$novo" ] || die "O conteúdo do pacote não é a versão $novo."
( cd "$novo_dir" && if command -v sha256sum >/dev/null 2>&1; then sha256sum -c SHA256SUMS --quiet; else shasum -a 256 -c SHA256SUMS --quiet; fi ) || die "Algum arquivo do pacote não confere com o SHA256SUMS. Nada foi alterado."
echo "Arquivo e conteúdo conferidos."

say "3/6 Backup (banco, .env e licença)"
bash ./backup.sh || die "O backup falhou: nada foi alterado. Resolva e rode de novo."

say "4/6 Guardando os arquivos atuais e trocando pelos da versão $novo"
mkdir -p "anterior/$atual"
for f in docker-compose.yml instalar.sh instalar.ps1 backup.sh atualizar.sh LEIA-ME.md VERSION SHA256SUMS env.example; do [ -f "$f" ] && cp -p "$f" "anterior/$atual/"; done
rm -rf fontes imagens
cp -a "$novo_dir"/. .
rm -rf atualizacao
echo "Arquivos trocados. O .env, os dados e a licença não foram tocados."

say "5/6 Subindo a versão nova (o banco é atualizado sozinho na partida)"
bash ./instalar.sh || die "O instalador falhou. Veja as mensagens acima. Para voltar: veja a seção 8 do LEIA-ME (anterior/$atual/ e backups/)."

say "6/6 Conferindo a versão"
port=$(grep -E '^API_PORT=' .env | tail -1 | cut -d= -f2-); port=${port:-8000}
ver=$(curl -fsS "http://localhost:$port/version" 2>/dev/null || true)
printf '%s' "$ver" | grep -q "\"$novo\"" || die "A API não informa a versão $novo (respondeu: ${ver:-nada}). Para voltar: veja a seção 8 do LEIA-ME (anterior/$atual/ e backups/)."
echo "PromptShield atualizado: $atual -> $novo."
echo "Se algo parecer estranho, não apague nada e fale com o fornecedor: o backup feito agora está em backups/."
