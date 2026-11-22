# =============================================================================
#  Instalador do Lumero para Windows 10 e 11
#
#  Como usar: dê dois cliques em  windows\instalar.cmd
#  (ou no PowerShell:  powershell -ExecutionPolicy Bypass -File windows\instalar.ps1)
#
#  Opções:  -Sim         responde "sim" para tudo (escolhas padrão)
#           -Voz         também instala a voz (/falar e /ouvir)
#           -SemRegistro não cria a entrada em "Aplicativos instalados" (usado pelo Setup .exe)
# =============================================================================
param([switch]$Sim, [switch]$Voz, [switch]$SemVoz, [switch]$SemRegistro, [switch]$SemPausa)
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}

$Raiz = Split-Path -Parent $PSScriptRoot
$Dados = Join-Path $env:LOCALAPPDATA 'Lumero'
$Bin = Join-Path $Dados 'bin'
$Api = 'http://127.0.0.1:11434'

function Sair($codigo) {
    if (-not $SemPausa) { Write-Host ''; Read-Host 'Aperte Enter para fechar' | Out-Null }
    exit $codigo
}
function Passo($texto) { Write-Host ''; Write-Host "==> $texto" -ForegroundColor Yellow }
function Aviso($texto) { Write-Host "    ⚠️  $texto" -ForegroundColor Yellow }
function Pergunta($texto, $padrao) {
    if ($Sim) { return ($padrao -eq 's') }
    $r = Read-Host "    $texto"
    if (-not $r) { $r = $padrao }
    return ($r -match '^[sSyY]')
}
function Atualizar-Path {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')
}
function Winget-Instalar($id, $nome) {
    Write-Host "    Instalando $nome..."
    winget install -e --id $id --silent --accept-source-agreements --accept-package-agreements --disable-interactivity 2>&1 |
        Where-Object { $_ -match 'instalad|installed|Erro|Error|falh|fail' } | ForEach-Object { Write-Host "      $_" }
    Atualizar-Path
}
function Achar-Python {
    foreach ($tentativa in @(@('py', '-3'), @('python'))) {
        $cmd = Get-Command $tentativa[0] -ErrorAction SilentlyContinue
        # o "python" da pasta WindowsApps é só um atalho para a Microsoft Store
        if ($cmd -and $cmd.Source -notlike '*\WindowsApps\*') {
            $argumentos = @($tentativa | Select-Object -Skip 1) + @('-c', 'import sys; print(sys.executable) if sys.version_info >= (3, 9) else None')
            try {
                $exe = & $tentativa[0] @argumentos 2>$null
                if ($LASTEXITCODE -eq 0 -and $exe) { return ($exe | Select-Object -First 1).Trim() }
            } catch {}
        }
    }
    return $null
}
function Achar-Ollama {
    $cmd = Get-Command ollama -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($c in @((Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'),
                     (Join-Path $env:ProgramFiles 'Ollama\ollama.exe'))) {
        if (Test-Path -LiteralPath $c) { return $c }
    }
    return $null
}
function Ollama-Responde {
    try { Invoke-RestMethod -Uri "$Api/api/version" -TimeoutSec 3 | Out-Null; return $true } catch { return $false }
}
function Gravar-Config($chave, $valor) {
    $arquivo = Join-Path $Dados 'config.json'
    $dados = @{}
    if (Test-Path -LiteralPath $arquivo) {
        try {
            (Get-Content -LiteralPath $arquivo -Raw -Encoding UTF8 | ConvertFrom-Json).PSObject.Properties |
                ForEach-Object { $dados[$_.Name] = $_.Value }
        } catch {}
    }
    $dados[$chave] = $valor
    $json = $dados | ConvertTo-Json
    [IO.File]::WriteAllText($arquivo, $json, (New-Object Text.UTF8Encoding($false)))
}

foreach ($arq in @('lumero.py', 'lumero_gui.py', 'lumero_gui.html', 'assets\lumero.ico', 'windows\desinstalar.ps1')) {
    if (-not (Test-Path -LiteralPath (Join-Path $Raiz $arq))) {
        Write-Host "Falta o arquivo $arq. Extraia o zip inteiro e rode de novo." -ForegroundColor Red
        Sair 1
    }
}
New-Item -ItemType Directory -Force -Path $Dados, $Bin | Out-Null

# ----------------------------------------------------------------------------- 1
Passo '1/7 Conferindo o computador'
$so = Get-CimInstance Win32_OperatingSystem
Write-Host "    $($so.Caption) (build $($so.BuildNumber))"
$ram = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
Write-Host "    RAM: $ram GB · Processador: $env:NUMBER_OF_PROCESSORS núcleos"
$vram = 0
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    $linha = (nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits 2>$null | Select-Object -First 1)
    if ($linha) {
        Write-Host "    Placa de vídeo: $linha MB"
        $vram = [int](($linha -split ',')[-1].Trim())
    }
}
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Write-Host '    O winget (Instalador de Aplicativo) não está disponível.' -ForegroundColor Red
    Write-Host '    Instale o "Instalador de Aplicativo" pela Microsoft Store e rode de novo.'
    Sair 1
}

# ----------------------------------------------------------------------------- 2
Passo '2/7 Python e Ollama'
$Python = Achar-Python
if (-not $Python) {
    Winget-Instalar 'Python.Python.3.12' 'Python 3.12'
    $Python = Achar-Python
    if (-not $Python) {
        foreach ($c in Get-ChildItem (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python3*\python.exe') -ErrorAction SilentlyContinue) { $Python = $c.FullName }
    }
    if (-not $Python) { Write-Host '    Não consegui instalar o Python. Instale em python.org e rode de novo.' -ForegroundColor Red; Sair 1 }
}
Write-Host "    Python: $Python"

$Ollama = Achar-Ollama
if (-not $Ollama) {
    Winget-Instalar 'Ollama.Ollama' 'Ollama (a IA que roda no seu computador)'
    Start-Sleep -Seconds 3
    $Ollama = Achar-Ollama
    if (-not $Ollama) { Write-Host '    Não consegui instalar o Ollama. Baixe em ollama.com/download e rode de novo.' -ForegroundColor Red; Sair 1 }
} else {
    Write-Host "    Ollama: $Ollama"
}
$inicializar = Join-Path ([Environment]::GetFolderPath('Startup')) 'Ollama.lnk'
if (Test-Path -LiteralPath $inicializar) {
    Write-Host '    O Ollama está configurado para ligar sozinho com o Windows.'
    if (Pergunta 'Deixar o Ollama desligado até você abrir o Lumero? (economiza memória) [S/n]' 's') {
        Remove-Item -LiteralPath $inicializar -Force
        Write-Host '    Pronto: o Lumero liga o Ollama ao abrir e desliga ao sair.'
    }
}

# ----------------------------------------------------------------------------- 3
Passo '3/7 Ferramentas extras (vídeo, áudio, compactar, git)'
if (Pergunta 'Instalar ffmpeg, 7-Zip e Git? (recomendado) [S/n]' 's') {
    if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) { Winget-Instalar 'Gyan.FFmpeg' 'ffmpeg' }
    if (-not (Test-Path "$env:ProgramFiles\7-Zip\7z.exe")) { Winget-Instalar '7zip.7zip' '7-Zip' }
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Winget-Instalar 'Git.Git' 'Git' }
}

# ----------------------------------------------------------------------------- 4
Passo '4/7 Lumero'
$Destino = Join-Path $Dados 'lumero.py'
if (Test-Path -LiteralPath $Destino) {
    New-Item -ItemType Directory -Force -Path (Join-Path $Dados 'backups') | Out-Null
    Copy-Item -LiteralPath $Destino -Destination (Join-Path $Dados ('backups\lumero-antes-da-instalacao-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.py'))
}
Copy-Item -LiteralPath (Join-Path $Raiz 'lumero.py') -Destination $Destino -Force
Copy-Item -LiteralPath (Join-Path $Raiz 'assets\lumero.ico') -Destination (Join-Path $Dados 'lumero.ico') -Force
foreach ($arq in @('lumero_gui.py', 'lumero_gui.html')) {
    Copy-Item -LiteralPath (Join-Path $Raiz $arq) -Destination (Join-Path $Dados $arq) -Force
}
Copy-Item -LiteralPath (Join-Path $Raiz 'windows\desinstalar.ps1') -Destination (Join-Path $Dados 'desinstalar.ps1') -Force

Write-Host '    Criando o ambiente Python do Lumero...'
$Venv = Join-Path $Dados 'venv'
if (-not (Test-Path (Join-Path $Venv 'Scripts\python.exe'))) { & $Python -m venv $Venv }
$Py = Join-Path $Venv 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Py)) { Aviso 'não consegui criar o ambiente Python; usando o Python do sistema.'; $Py = $Python }
& $Py -m pip install --quiet --disable-pip-version-check prompt_toolkit psutil pillow pillow-heif pypdf
if ($LASTEXITCODE -ne 0) { Aviso 'algumas bibliotecas não instalaram (sem internet?). O Lumero funciona com menos recursos.' }
# janela própria do chat (usa o WebView2, o motor do Edge que já vem no Windows)
& $Py -m pip install --quiet --disable-pip-version-check pywebview
if ($LASTEXITCODE -ne 0) { Aviso 'a janela própria não instalou: o chat vai abrir no Edge.' }
$PyJanela = Join-Path (Split-Path -Parent $Py) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $PyJanela)) { $PyJanela = $Py }
$Gui = Join-Path $Dados 'lumero_gui.py'

# comando "lumero" no terminal
$cmd = @"
@echo off
chcp 65001 >nul
title Lumero
"$Py" "$Destino" %*
"@
[IO.File]::WriteAllText((Join-Path $Bin 'lumero.cmd'), $cmd, (New-Object Text.UTF8Encoding($false)))
$pathUsuario = [Environment]::GetEnvironmentVariable('Path', 'User')
if (-not $pathUsuario) { $pathUsuario = '' }
if (($pathUsuario -split ';') -notcontains $Bin) {
    [Environment]::SetEnvironmentVariable('Path', ($pathUsuario.TrimEnd(';') + ';' + $Bin).TrimStart(';'), 'User')
}

# atalhos no menu Iniciar (com Ctrl+Alt+A) e, se quiser, na área de trabalho
function Criar-Atalho($caminho, $comTecla, $terminal) {
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut($caminho)
    if (-not $terminal) {   # janela de chat (pythonw: sem console preto atrás)
        $lnk.TargetPath = $PyJanela
        $lnk.Arguments = "`"$Gui`""
    } else {
        $wt = Get-Command wt.exe -ErrorAction SilentlyContinue
        if ($wt) {   # Windows Terminal: cores e símbolos melhores que o console antigo
            $lnk.TargetPath = $wt.Source
            $lnk.Arguments = "--title Lumero cmd /c `"$(Join-Path $Bin 'lumero.cmd')`""
        } else {
            $lnk.TargetPath = Join-Path $Bin 'lumero.cmd'
        }
    }
    $lnk.WorkingDirectory = $env:USERPROFILE
    $lnk.IconLocation = "$(Join-Path $Dados 'lumero.ico'),0"
    $lnk.Description = 'Lumero: IA local que pesquisa, acha arquivos e executa tarefas'
    if ($comTecla) { $lnk.Hotkey = 'CTRL+ALT+A' }
    $lnk.Save()
}
$menu = [Environment]::GetFolderPath('Programs')
Criar-Atalho (Join-Path $menu 'Lumero.lnk') $true $false
Criar-Atalho (Join-Path $menu 'Lumero (terminal).lnk') $false $true
Write-Host '    Atalhos no menu Iniciar: "Lumero" (janela de chat, Ctrl+Alt+A) e "Lumero (terminal)".'
if (Pergunta 'Criar também um atalho na área de trabalho? [s/N]' 'n') {
    Criar-Atalho (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Lumero.lnk') $false $false
}
$cmdGui = "@echo off`r`nstart `"`" `"$PyJanela`" `"$Gui`" %*`r`n"
[IO.File]::WriteAllText((Join-Path $Bin 'lumero-gui.cmd'), $cmdGui, (New-Object Text.UTF8Encoding($false)))

if (-not $SemRegistro) {   # aparece em Configurações → Aplicativos instalados
    $chave = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Lumero'
    New-Item -Path $chave -Force | Out-Null
    $versao = (Select-String -LiteralPath $Destino -Pattern '^VERSAO = "([^"]+)"' | Select-Object -First 1).Matches[0].Groups[1].Value
    Set-ItemProperty -Path $chave -Name DisplayName -Value 'Lumero'
    Set-ItemProperty -Path $chave -Name DisplayVersion -Value $versao
    Set-ItemProperty -Path $chave -Name Publisher -Value 'Lumero'
    Set-ItemProperty -Path $chave -Name DisplayIcon -Value (Join-Path $Dados 'lumero.ico')
    Set-ItemProperty -Path $chave -Name InstallLocation -Value $Dados
    Set-ItemProperty -Path $chave -Name UninstallString -Value ("powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"" + (Join-Path $Dados 'desinstalar.ps1') + "`"")
    Set-ItemProperty -Path $chave -Name NoModify -Value 1 -Type DWord
    Set-ItemProperty -Path $chave -Name NoRepair -Value 1 -Type DWord
}

# ----------------------------------------------------------------------------- 5
Passo '5/7 Modelos de IA'
$servidor = $null
if (-not (Ollama-Responde)) {
    $env:OLLAMA_HOST = '127.0.0.1:11434'
    $servidor = Start-Process -FilePath $Ollama -ArgumentList 'serve' -WindowStyle Hidden -PassThru
    for ($i = 0; $i -lt 60 -and -not (Ollama-Responde); $i++) { Start-Sleep -Milliseconds 500 }
}
if (-not (Ollama-Responde)) { Write-Host '    O Ollama não respondeu. Abra o Ollama pelo menu Iniciar e rode o instalador de novo.' -ForegroundColor Red; Sair 1 }

if ($vram -ge 7000 -and $ram -ge 16) { $rec = '3' } elseif ($ram -ge 8) { $rec = '1' } else { $rec = '2' }
function Marca($n) { if ($rec -eq $n) { '  ← recomendado' } else { '' } }
Write-Host '    Modelos (todos conversam, usam ferramentas e enxergam imagens):'
Write-Host "    [1] qwen3.5:4b  equilibrado: bom em quase tudo$(Marca '1')"
Write-Host "    [2] qwen3.5:2b  mais rápido e leve, mas erra mais$(Marca '2')"
Write-Host "    [3] qwen3.5:9b  mais esperto, mas pesado: placa de vídeo com 8 GB$(Marca '3')"
Write-Host '    [0] nenhum agora'
$escolha = $rec
if (-not $Sim) {
    $r = Read-Host "    Quais baixar? (ex: 1 2) [$rec]"
    if ($r) { $escolha = $r }
}
$padrao = $null
foreach ($n in ($escolha -split '[\s,]+')) {
    $modelo = @{ '1' = 'qwen3.5:4b'; '2' = 'qwen3.5:2b'; '3' = 'qwen3.5:9b' }[$n]
    if (-not $modelo) { continue }
    Write-Host "    Baixando $modelo..."
    & $Ollama pull $modelo
    if ($LASTEXITCODE -eq 0) { if (-not $padrao) { $padrao = $modelo } } else { Aviso "não consegui baixar $modelo" }
}
if ($padrao) { Gravar-Config 'MODELO' $padrao; Write-Host "    Modelo do Lumero: $padrao" }
if ($servidor) { Stop-Process -Id $servidor.Id -Force -ErrorAction SilentlyContinue }

# ----------------------------------------------------------------------------- 6
Passo '6/7 Internet do Ollama'
Write-Host '    O Ollama não precisa de internet para conversar. A pesquisa do Lumero continua'
Write-Host '    funcionando com ele bloqueado (quem pesquisa é o Lumero).'
$baixar = @"
# Baixa um modelo novo para o Lumero, liberando a internet do Ollama só durante o download.
param([Parameter(Mandatory=`$true)][string]`$Nome)
`$regra = 'Lumero - Ollama sem internet'
`$ollama = '$Ollama'
`$bloqueado = [bool](Get-NetFirewallRule -DisplayName `$regra -ErrorAction SilentlyContinue | Where-Object Enabled -eq 'True')
if (`$bloqueado) { Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList "-NoProfile -Command Disable-NetFirewallRule -DisplayName '`$regra'" }
`$liguei = `$null
try { Invoke-RestMethod http://127.0.0.1:11434/api/version -TimeoutSec 3 | Out-Null } catch {
    `$env:OLLAMA_HOST = '127.0.0.1:11434'
    `$liguei = Start-Process -FilePath `$ollama -ArgumentList 'serve' -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 4
}
& `$ollama pull `$Nome
if (`$liguei) { Stop-Process -Id `$liguei.Id -Force -ErrorAction SilentlyContinue }
if (`$bloqueado) { Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList "-NoProfile -Command Enable-NetFirewallRule -DisplayName '`$regra'" }
"@
[IO.File]::WriteAllText((Join-Path $Bin 'lumero-baixar-modelo.ps1'), $baixar, (New-Object Text.UTF8Encoding($true)))
[IO.File]::WriteAllText((Join-Path $Bin 'lumero-baixar-modelo.cmd'),
    "@echo off`r`npowershell -NoProfile -ExecutionPolicy Bypass -File `"%~dp0lumero-baixar-modelo.ps1`" %*`r`n",
    (New-Object Text.UTF8Encoding($false)))
if (Pergunta 'Bloquear a internet do Ollama no Firewall do Windows? (pede permissão de administrador) [S/n]' 's') {
    $pasta = Split-Path -Parent $Ollama
    $regras = @"
Remove-NetFirewallRule -DisplayName 'Lumero - Ollama sem internet' -ErrorAction SilentlyContinue
foreach (`$exe in @('$Ollama', '$(Join-Path $pasta 'ollama app.exe')')) {
    if (Test-Path -LiteralPath `$exe) {
        New-NetFirewallRule -DisplayName 'Lumero - Ollama sem internet' -Direction Outbound -Program `$exe -Action Block -Profile Any | Out-Null
    }
}
"@
    $arqRegras = Join-Path $env:TEMP 'lumero-firewall.ps1'
    [IO.File]::WriteAllText($arqRegras, $regras, (New-Object Text.UTF8Encoding($true)))
    try {
        Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$arqRegras`""
        Write-Host '    Bloqueado. Para baixar outro modelo depois: lumero-baixar-modelo NOME'
    } catch {
        Aviso 'a permissão de administrador foi negada; o Ollama continua com internet.'
    }
    Remove-Item -LiteralPath $arqRegras -ErrorAction SilentlyContinue
} else {
    Write-Host '    Para baixar outro modelo depois: lumero-baixar-modelo NOME'
}

# ----------------------------------------------------------------------------- 7
Passo '7/7 Voz (opcional)'
$querVoz = $Voz
if (-not $Voz -and -not $SemVoz) {
    $querVoz = Pergunta 'Instalar a voz? (/falar com o microfone; ~300 MB) [s/N]' 'n'
}
if ($querVoz) {
    & $Py -m pip install --quiet --disable-pip-version-check pywhispercpp sounddevice numpy
    if ($LASTEXITCODE -eq 0) { Write-Host '    ✓ /falar instalado (o modelo de ~150 MB é baixado no primeiro uso).' }
    else { Aviso 'não consegui instalar o reconhecimento de fala.' }
    $vozDir = Join-Path $Dados 'voz'
    $piper = Join-Path $vozDir 'piper-venv'
    New-Item -ItemType Directory -Force -Path $vozDir | Out-Null
    & $Python -m venv $piper
    $pyPiper = Join-Path $piper 'Scripts\python.exe'
    & $pyPiper -m pip install --quiet --disable-pip-version-check piper-tts
    if ($LASTEXITCODE -eq 0) {
        Push-Location $vozDir
        & $pyPiper -m piper.download_voices pt_BR-faber-medium --data-dir $vozDir 2>$null
        Pop-Location
    }
    if (Test-Path (Join-Path $vozDir 'pt_BR-faber-medium.onnx')) { Write-Host '    ✓ Voz neural instalada.' }
    else {
        Remove-Item -Recurse -Force $piper -ErrorAction SilentlyContinue
        Write-Host '    O /ouvir vai usar a voz do próprio Windows (Maria).'
    }
} else {
    Write-Host '    Pulado. Sem instalar nada, o /ouvir já usa a voz do próprio Windows.'
}

Write-Host ''
Write-Host '✓ Lumero instalado!' -ForegroundColor Green
Write-Host '  • Procure "Lumero" no menu Iniciar ou aperte Ctrl+Alt+A: abre a janela de chat.'
Write-Host '  • Prefere o terminal? Use o atalho "Lumero (terminal)".'
Write-Host '  • No terminal (abra um novo), digite: lumero'
Write-Host "  • Configurações: $Dados\config.json"
Write-Host '  • Desinstalar: Configurações → Aplicativos → Lumero'
Sair 0
