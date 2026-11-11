# Instalador do PromptShield para Windows (PowerShell com Docker Desktop). Seguro para rodar de novo: não apaga dados e mantém o .env existente.
#   Abra o PowerShell na pasta do pacote:   .\instalar.ps1
# Sem janela interativa, defina $env:PS_EMPRESA e $env:PS_ADMIN_EMAIL antes.
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Say($t) { Write-Host "`n== $t ==" }
function Die($t) { Write-Host "`nERRO: $t" -ForegroundColor Red; exit 1 }
function Rnd($bytes) { $b = New-Object byte[] $bytes; [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); ($b | ForEach-Object { $_.ToString("x2") }) -join "" }
function Key32 { $b = New-Object byte[] 32; [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); [Convert]::ToBase64String($b).Replace("+", "-").Replace("/", "_") }
function WriteUtf8NoBom($path, $text) { [System.IO.File]::WriteAllText((Join-Path $PSScriptRoot $path), $text, (New-Object System.Text.UTF8Encoding $false)) }

Say "1/7 Conferindo os requisitos"
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Die "Docker não encontrado. Instale o Docker Desktop (https://docs.docker.com/desktop/setup/install/windows-install/) e rode de novo." }
docker info *> $null
if ($LASTEXITCODE -ne 0) { Die "O Docker não está em execução. Abra o Docker Desktop, espere ele iniciar e rode de novo." }
docker compose version *> $null
if ($LASTEXITCODE -ne 0) { Die "Docker Compose v2 não encontrado (o comando 'docker compose version' precisa funcionar)." }
Write-Host "Docker e Compose encontrados."

Say "2/7 Conferindo a integridade dos arquivos do pacote"
foreach ($line in Get-Content SHA256SUMS) {
  if (-not $line.Trim()) { continue }
  $hash, $file = $line -split "  ", 2
  if ((Get-FileHash -Algorithm SHA256 -LiteralPath $file).Hash.ToLower() -ne $hash.ToLower()) { Die "O arquivo $file não confere com o SHA256SUMS. Baixe o pacote de novo e compare o SHA-256 com o informado pelo fornecedor." }
}
Write-Host "Arquivos conferidos."

Say "3/7 Configuração (.env)"
if (Test-Path .env) {
  Write-Host ".env já existe: mantido (as senhas e chaves não mudam)."
  $version = (Get-Content VERSION -Raw).Trim()
  $env_text = ((Get-Content .env) | ForEach-Object { if ($_ -match "^PS_VERSION=") { "PS_VERSION=$version" } else { $_ } }) -join "`n"
  WriteUtf8NoBom ".env" ($env_text + "`n")
} else {
  $lines = Get-Content env.example | ForEach-Object {
    if ($_ -match "^POSTGRES_PASSWORD=") { "POSTGRES_PASSWORD=$(Rnd 24)" }
    elseif ($_ -match "^APP_DB_PASSWORD=") { "APP_DB_PASSWORD=$(Rnd 24)" }
    elseif ($_ -match "^LOCAL_AUTH_SECRET=") { "LOCAL_AUTH_SECRET=$(Rnd 48)" }
    elseif ($_ -match "^ORIGINAL_TEXT_MASTER_KEY=") { "ORIGINAL_TEXT_MASTER_KEY=$(Key32)" }
    else { $_ }
  }
  WriteUtf8NoBom ".env" (($lines -join "`n") + "`n")
  Write-Host ".env criado com senhas e chaves aleatórias. GUARDE uma cópia dele em lugar seguro."
}

Say "4/7 Imagens"
$imgs = @(Get-ChildItem -Path imagens -Include *.tar, *.tar.gz -Recurse -ErrorAction SilentlyContinue)
if ($imgs.Count -gt 0) { foreach ($f in $imgs) { Write-Host "Carregando $($f.Name) (pode levar alguns minutos)..."; docker load -i $f.FullName | Out-Null; if ($LASTEXITCODE -ne 0) { Die "Falha ao carregar $($f.Name)." } } }
else { Write-Host "Este pacote não traz imagens: elas serão construídas a partir das fontes (precisa de internet, leva vários minutos)." }

Say "5/7 Subindo o PromptShield"
docker compose up -d
if ($LASTEXITCODE -ne 0) { Die "docker compose up falhou. Veja a mensagem acima." }

Say "6/7 Aguardando a API"
$port = ((Get-Content .env | Where-Object { $_ -match "^API_PORT=" } | Select-Object -Last 1) -replace "^API_PORT=", ""); if (-not $port) { $port = "8000" }
$ok = $false
for ($i = 0; $i -lt 100; $i++) {
  try { Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:$port/health" -TimeoutSec 3 | Out-Null; $ok = $true; break } catch { Start-Sleep -Seconds 3 }
}
if (-not $ok) { Die "A API não respondeu em 5 minutos. Veja: docker compose logs --tail 50 api" }
Write-Host "API no ar."

Say "7/7 Primeiro acesso"
$webPort = ((Get-Content .env | Where-Object { $_ -match "^WEB_PORT=" } | Select-Object -Last 1) -replace "^WEB_PORT=", ""); if (-not $webPort) { $webPort = "3000" }
$base = ((Get-Content .env | Where-Object { $_ -match "^PUBLIC_BASE_URL=" } | Select-Object -Last 1) -replace "^PUBLIC_BASE_URL=", ""); if (-not $base) { $base = "http://localhost:$webPort" }
if (Test-Path .instalado) { Write-Host "O primeiro acesso já foi configurado antes. Console: $base"; exit 0 }
$empresa = $env:PS_EMPRESA; $email = $env:PS_ADMIN_EMAIL
if (-not $empresa) { $empresa = Read-Host "Nome da sua empresa" }
if (-not $email) { $email = Read-Host "E-mail do administrador (é o seu login)" }
if (-not $empresa) { Die "Informe o nome da empresa." }
if ($email -notmatch "^[^@\s]+@[^@\s]+\.[^@\s]+$") { Die "E-mail inválido: $email" }
$slug = ($empresa.ToLower() -replace "[^a-z0-9]+", "-").Trim("-"); if (-not $slug) { $slug = "empresa" }; if ($slug.Length -gt 60) { $slug = $slug.Substring(0, 60) }
docker compose exec -T api python -m app.cli create-tenant --name $empresa --slug $slug --admin-email $email | Out-Null
if ($LASTEXITCODE -ne 0) { Die "Não consegui criar a empresa (ela já existe?). Para definir a senha do administrador: docker compose exec api python -m app.cli set-password --email $email" }
$saida = docker compose exec -T api python -m app.cli set-password --email $email --generate
$senha = ($saida | Select-Object -Last 1) -replace "^.*: ", ""
(Get-Date -Format "yyyy-MM-dd") | Out-File -Encoding ascii .instalado

Write-Host @"

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
"@
