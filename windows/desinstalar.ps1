# Remove o Lumero do Windows. Pergunta antes de apagar o Ollama, os modelos e os seus dados.
# Uso: Configurações → Aplicativos → Lumero → Desinstalar
#      (ou: powershell -ExecutionPolicy Bypass -File desinstalar.ps1)
param([switch]$SemPausa, [switch]$Confirmado)
$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
$Dados = Join-Path $env:LOCALAPPDATA 'Lumero'
$Bin = Join-Path $Dados 'bin'

function Pergunta($texto) { return ((Read-Host $texto) -match '^[sSyY]') }
function Sair { if (-not $SemPausa) { Read-Host 'Aperte Enter para fechar' | Out-Null }; exit 0 }

if (-not $Confirmado -and -not (Pergunta 'Remover o Lumero? [s/N]')) { Write-Host 'Nada foi removido.'; Sair }

Write-Host '==> Lumero, atalhos e lembretes'
Get-ScheduledTask -TaskName 'Lumero-Lembrete-*' -ErrorAction SilentlyContinue |
    Unregister-ScheduledTask -Confirm:$false -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*lumero_gui.py*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
foreach ($lnk in @((Join-Path ([Environment]::GetFolderPath('Programs')) 'Lumero.lnk'),
                   (Join-Path ([Environment]::GetFolderPath('Programs')) 'Lumero (terminal).lnk'),
                   (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Lumero.lnk'))) {
    Remove-Item -LiteralPath $lnk -Force -ErrorAction SilentlyContinue
}
$pathUsuario = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($pathUsuario) {
    $novo = ($pathUsuario -split ';' | Where-Object { $_ -and $_ -ne $Bin }) -join ';'
    [Environment]::SetEnvironmentVariable('Path', $novo, 'User')
}
Remove-Item -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Lumero' -Recurse -Force -ErrorAction SilentlyContinue
foreach ($item in @('venv', 'bin', 'voz\piper-venv', 'lumero.py', 'lumero_gui.py', 'lumero_gui.html', 'gui.json', 'lumero.ico', 'tmp')) {
    Remove-Item -LiteralPath (Join-Path $Dados $item) -Recurse -Force -ErrorAction SilentlyContinue
}
if (Get-NetFirewallRule -DisplayName 'Lumero - Ollama sem internet' -ErrorAction SilentlyContinue) {
    try {
        Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList "-NoProfile -Command Remove-NetFirewallRule -DisplayName 'Lumero - Ollama sem internet'"
    } catch { Write-Host '    (a regra do Firewall ficou; dá para apagar em "Firewall do Windows com Segurança Avançada")' }
}

if (Pergunta 'Remover também o Ollama e TODOS os modelos baixados? [s/N]') {
    Write-Host '==> Ollama e modelos'
    Get-Process -Name 'ollama', 'ollama app' -ErrorAction SilentlyContinue | Stop-Process -Force
    winget uninstall -e --id Ollama.Ollama --silent --disable-interactivity 2>&1 | Out-Null
    Remove-Item -LiteralPath (Join-Path $env:USERPROFILE '.ollama') -Recurse -Force -ErrorAction SilentlyContinue
}

if ((Test-Path -LiteralPath $Dados) -and (Pergunta 'Apagar também a memória, as conversas salvas e as configurações? [s/N]')) {
    Set-Location $env:USERPROFILE
    Remove-Item -LiteralPath $Dados -Recurse -Force -ErrorAction SilentlyContinue
}
Write-Host ''
Write-Host '✓ Lumero removido. (O Python e as notas em Documentos\Notas IA foram mantidos.)' -ForegroundColor Green
Sair
