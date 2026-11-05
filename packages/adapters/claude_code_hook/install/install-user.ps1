<#
Instala o adaptador PromptShield para o Claude Code NO SEU USUARIO do Windows (sem administrador, sem tocar na politica da maquina).
Status: NAO EXECUTADO em Windows real. E um modelo para o teste do roteiro (docs/teste-windows.md); anote o que falhar.

  .\install-user.ps1 -ApiUrl http://localhost:8000 [-ApiKey ps_...] [-Department Pessoal] [-FailMode open|closed] [-DryRun]
  .\install-user.ps1 -Uninstall

O que faz: instala o pacote com pip, grava %USERPROFILE%\.promptshield\hook.json (legivel so por voce), settings.json com os 3 hooks
e o atalho claude-ps.cmd, que roda `claude --settings ...` com a configuracao certa. Nao altera ~\.claude\settings.json.
O hook envia o que voce digita e as acoes do agente: use so com o seu consentimento e em um tenant de teste.
#>
param(
  [string]$ApiUrl = "http://localhost:8000",
  [string]$ApiKey = "",
  [string]$Department = "",
  [ValidateSet("open", "closed")][string]$FailMode = "open",
  [string]$Dir = (Join-Path $env:USERPROFILE ".promptshield"),
  [switch]$DryRun,
  [switch]$Uninstall
)
$ErrorActionPreference = "Stop"
$pkg = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if ($Uninstall) {
  if (Test-Path $Dir) { Remove-Item -Recurse -Force $Dir; Write-Host "Removido: $Dir" }
  python -m pip uninstall -y promptshield-claude-hook 2>$null | Out-Null
  Write-Host "Desinstalado. Revogue a chave no console do PromptShield."
  return
}

$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) { throw "python nao encontrado no PATH (precisa do Python 3.9 ou mais novo)." }
if ($ApiUrl -notmatch '^https?://') { throw "ApiUrl precisa comecar com http:// ou https://" }
if (-not $ApiKey) {
  $sec = Read-Host "Chave da API (ps_...)" -AsSecureString
  $ApiKey = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
}
if ($ApiKey -notmatch '^ps_') { throw "A chave deve comecar com ps_" }

$cfg = [ordered]@{ api_url = $ApiUrl.TrimEnd('/'); api_key = $ApiKey; fail_mode = $FailMode; timeout_seconds = 3; integration_status = "partial" }
if ($Department) { $cfg.department = $Department }
$pyJson = $py.Replace('\', '\\')
$hook = '{ "type": "command", "command": "' + $pyJson + '", "args": ["-m", "promptshield_claude_hook"], "timeout": 10 }'
$settings = @"
{
  "hooks": {
    "UserPromptSubmit": [ { "hooks": [ $hook ] } ],
    "PreToolUse":  [ { "matcher": "*", "hooks": [ $hook ] } ],
    "PostToolUse": [ { "matcher": "*", "hooks": [ $hook ] } ]
  }
}
"@
$launcher = "@echo off`r`nset PROMPTSHIELD_HOOK_CONFIG=$Dir\hook.json`r`nset PATH=%PATH%;%USERPROFILE%\.local\bin`r`nclaude --settings `"$Dir\settings.json`" %*`r`n"

if ($DryRun) {
  Write-Host "SIMULACAO. Faria:`n  pip install -e $pkg`n  gravar $Dir\hook.json (chave oculta), settings.json e claude-ps.cmd"
  Write-Host $settings
  return
}

function Write-NoBom($path, $text) { [IO.File]::WriteAllText($path, $text, (New-Object Text.UTF8Encoding($false))) }   # Windows PowerShell 5.1 grava BOM com -Encoding UTF8

python -m pip install -e $pkg
New-Item -ItemType Directory -Force $Dir | Out-Null
Write-NoBom (Join-Path $Dir "hook.json") ($cfg | ConvertTo-Json)
icacls (Join-Path $Dir "hook.json") /inheritance:r /grant:r "$($env:USERNAME):(R,W)" | Out-Null   # so voce le a chave
Write-NoBom (Join-Path $Dir "settings.json") $settings
Write-NoBom (Join-Path $Dir "claude-ps.cmd") $launcher

if (-not (Get-Command claude -ErrorAction SilentlyContinue)) { Write-Warning "O comando claude nao foi encontrado. Instale o Claude Code: irm https://claude.ai/install.ps1 | iex   (depois abra um novo PowerShell)" }
$env:PROMPTSHIELD_HOOK_CONFIG = Join-Path $Dir "hook.json"
python -m promptshield_claude_hook check
Write-Host "`nPronto. Abra o Claude Code com:  $Dir\claude-ps.cmd"
Write-Host "Importar historico (simulacao primeiro):  python -m promptshield_claude_hook import --preview 5"
