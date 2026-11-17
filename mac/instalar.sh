#!/bin/bash
# =============================================================================
#  Instalador do Lumero para macOS (Apple Silicon e Intel)
#
#  Uso: abra o Terminal, entre na pasta do Lumero e rode:   bash mac/instalar.sh
#  Opções:  --sim   responde "sim" para tudo     --voz   também instala a voz
#           --sem-app  não cria o Lumero.app (usado pelo próprio app baixado em .dmg)
#
#  Usa o Homebrew (instala se não tiver) para o Python, o Ollama e o ffmpeg.
#  (Escrito para o bash 3.2 que vem no macOS.)
# =============================================================================
set -euo pipefail

RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
DADOS="$HOME/Library/Application Support/Lumero"
BIN="$HOME/.local/bin"
APP="$HOME/Applications/Lumero.app"
API="http://127.0.0.1:11434"

SIM=0; VOZ=""; CRIAR_APP=1
for arg in "$@"; do
    case "$arg" in
        --sim) SIM=1 ;;
        --sem-app) CRIAR_APP=0 ;;
        --voz) VOZ=1 ;;
        --sem-voz) VOZ=0 ;;
        *) echo "Opção desconhecida: $arg"; exit 1 ;;
    esac
done

minusculo() { echo "$1" | tr '[:upper:]' '[:lower:]'; }
pergunta() {  # pergunta "texto" padrão(s/n) -> 0 = sim
    local resp padrao="$2"
    if [ "$SIM" = 1 ]; then [ "$padrao" = s ]; return; fi
    read -r -p "$1 " resp </dev/tty || resp=""
    resp="$(minusculo "${resp:-$padrao}")"
    case "$resp" in s*|y*) return 0 ;; *) return 1 ;; esac
}
passo() { printf '\n\033[1;33m==> %s\033[0m\n' "$*"; }
aviso() { printf '    \033[33m⚠️  %s\033[0m\n' "$*"; }
esperar_ollama() {
    local i
    for i in $(seq 1 60); do
        curl -fs "$API/api/version" >/dev/null 2>&1 && return 0
        sleep 0.5
    done
    return 1
}

[ "$(uname)" = Darwin ] || { echo "Este instalador é para o macOS. No Linux use: bash linux/instalar.sh"; exit 1; }
[ "$(id -u)" -eq 0 ] && { echo "Rode como o seu usuário normal (sem sudo)."; exit 1; }
for arq in lumero.py assets/lumero.icns; do
    [ -f "$RAIZ/$arq" ] || { echo "Falta o arquivo $arq. Extraia o zip inteiro e rode de novo."; exit 1; }
done

# ----------------------------------------------------------------------------- 1
passo "1/6 Conferindo o Mac"
echo "    macOS $(sw_vers -productVersion) · $(uname -m)"
ram=$(( $(sysctl -n hw.memsize) / 1024 / 1024 / 1024 ))
echo "    RAM: ${ram} GB"
if [ "$(uname -m)" = arm64 ]; then
    echo "    Apple Silicon: o Ollama usa a GPU integrada (bem mais rápido)."
fi

# ----------------------------------------------------------------------------- 2
passo "2/6 Homebrew, Python, Ollama e ferramentas"
if ! command -v brew >/dev/null; then
    for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
        [ -x "$b" ] && eval "$("$b" shellenv)" && break
    done
fi
if ! command -v brew >/dev/null; then
    echo "    O Homebrew (instalador de programas) não está instalado."
    if pergunta "    Instalar o Homebrew agora? Ele pede a sua senha do Mac. [S/n]" s; then
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
            [ -x "$b" ] && eval "$("$b" shellenv)" && break
        done
    fi
    command -v brew >/dev/null || { echo "Sem o Homebrew não dá para continuar."; exit 1; }
fi
for pacote in python ollama ffmpeg poppler git sevenzip; do
    if [ "$pacote" = ollama ] && { command -v ollama >/dev/null || [ -d /Applications/Ollama.app ]; }; then
        echo "    ollama: já instalado"
    elif brew list --formula "$pacote" >/dev/null 2>&1; then
        echo "    $pacote: já instalado"
    else
        echo "    Instalando $pacote (pode demorar alguns minutos)..."
        brew install --quiet "$pacote" >/dev/null 2>&1 || aviso "não consegui instalar $pacote"
    fi
done
PY_BASE="$(brew --prefix)/bin/python3"
[ -x "$PY_BASE" ] || PY_BASE="$(command -v python3)"

# ----------------------------------------------------------------------------- 3
passo "3/6 Lumero"
mkdir -p "$DADOS" "$BIN" "$HOME/Applications"
if [ -f "$DADOS/lumero.py" ]; then
    mkdir -p "$DADOS/backups"
    cp "$DADOS/lumero.py" "$DADOS/backups/lumero-antes-da-instalacao-$(date +%Y%m%d-%H%M%S).py"
fi
cp "$RAIZ/lumero.py" "$DADOS/lumero.py"

echo "    Criando o ambiente Python do Lumero..."
rm -rf "$DADOS/venv"
"$PY_BASE" -m venv "$DADOS/venv"
PY="$DADOS/venv/bin/python"
"$PY" -m pip install --quiet --disable-pip-version-check prompt_toolkit psutil pillow pillow-heif pypdf \
    || aviso "não consegui instalar algumas bibliotecas (sem internet?)."

cat > "$BIN/lumero" <<EOF
#!/bin/bash
# Abre o Lumero neste terminal
export PATH="$(brew --prefix)/bin:\$PATH"
exec "$PY" "$DADOS/lumero.py" "\$@"
EOF
chmod +x "$BIN/lumero"
# o .command abre no Terminal com dois cliques (é o que o Lumero.app usa)
cat > "$DADOS/Lumero.command" <<EOF
#!/bin/bash
printf '\033]0;Lumero\007'
"$BIN/lumero"
exit
EOF
chmod +x "$DADOS/Lumero.command"

if ! grep -q 'Lumero: ~/.local/bin' "$HOME/.zprofile" 2>/dev/null; then
    printf '\n# Lumero: ~/.local/bin no PATH\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$HOME/.zprofile"
fi

if [ "$CRIAR_APP" = 1 ]; then
# o aplicativo Lumero (Launchpad, Spotlight e Dock)
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$RAIZ/assets/lumero.icns" "$APP/Contents/Resources/lumero.icns"
VERSAO="$(sed -n 's/^VERSAO = "\(.*\)".*/\1/p' "$RAIZ/lumero.py" | head -1)"
cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>Lumero</string>
    <key>CFBundleDisplayName</key><string>Lumero</string>
    <key>CFBundleIdentifier</key><string>com.lumero.app</string>
    <key>CFBundleVersion</key><string>${VERSAO:-1.0.0}</string>
    <key>CFBundleShortVersionString</key><string>${VERSAO:-1.0.0}</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleExecutable</key><string>Lumero</string>
    <key>CFBundleIconFile</key><string>lumero</string>
    <key>LSMinimumSystemVersion</key><string>12.0</string>
</dict>
</plist>
EOF
cat > "$APP/Contents/MacOS/Lumero" <<EOF
#!/bin/bash
open "$DADOS/Lumero.command"
EOF
chmod +x "$APP/Contents/MacOS/Lumero"
touch "$APP"
LSREG=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister
[ -x "$LSREG" ] && "$LSREG" -f "$APP" >/dev/null 2>&1 || true
echo "    Lumero.app criado em ~/Aplicativos (procure \"Lumero\" no Spotlight: Cmd+Espaço)."
fi

# ----------------------------------------------------------------------------- 4
passo "4/6 Modelos de IA"
OLLAMA_BIN="$(command -v ollama || true)"
[ -z "$OLLAMA_BIN" ] && [ -x /Applications/Ollama.app/Contents/Resources/ollama ] && \
    OLLAMA_BIN=/Applications/Ollama.app/Contents/Resources/ollama
[ -z "$OLLAMA_BIN" ] && OLLAMA_BIN="$(brew --prefix)/bin/ollama"
SERVE_PID=""
if ! curl -fs "$API/api/version" >/dev/null 2>&1; then
    OLLAMA_HOST=127.0.0.1:11434 "$OLLAMA_BIN" serve >/dev/null 2>&1 &
    SERVE_PID=$!
fi
esperar_ollama || { echo "O Ollama não respondeu. Tente: ollama serve"; exit 1; }
if [ "$(uname -m)" = arm64 ] && [ "$ram" -ge 16 ]; then rec=3
elif [ "$ram" -ge 8 ]; then rec=1
else rec=2; fi
marca() { [ "$rec" = "$1" ] && echo "  ← recomendado" || true; }
echo "    Modelos (todos conversam, usam ferramentas e enxergam imagens):"
echo "    [1] qwen3.5:4b  equilibrado: bom em quase tudo$(marca 1)"
echo "    [2] qwen3.5:2b  mais rápido e leve, mas erra mais$(marca 2)"
echo "    [3] qwen3.5:9b  mais esperto: Mac M1/M2/M3/M4 com 16 GB ou mais$(marca 3)"
echo "    [0] nenhum agora"
escolha="$rec"
if [ "$SIM" != 1 ]; then
    read -r -p "    Quais baixar? (ex: 1 2) [$rec]: " escolha </dev/tty || true
    escolha="${escolha:-$rec}"
fi
padrao=""
for n in $escolha; do
    case "$n" in
        1) modelo="qwen3.5:4b" ;;
        2) modelo="qwen3.5:2b" ;;
        3) modelo="qwen3.5:9b" ;;
        *) continue ;;
    esac
    echo "    Baixando $modelo..."
    if "$OLLAMA_BIN" pull "$modelo"; then
        [ -z "$padrao" ] && padrao="$modelo"
    else
        aviso "não consegui baixar $modelo"
    fi
done
[ -n "$SERVE_PID" ] && kill "$SERVE_PID" 2>/dev/null || true
if [ -n "$padrao" ]; then
    "$PY" - "$DADOS/config.json" "$padrao" <<'EOF'
import json, sys
arquivo, modelo = sys.argv[1:3]
try:
    with open(arquivo, encoding="utf-8") as f:
        dados = json.load(f)
except (OSError, ValueError):
    dados = {}
dados["MODELO"] = modelo
with open(arquivo, "w", encoding="utf-8") as f:
    json.dump(dados, f, indent=2, ensure_ascii=False)
EOF
    echo "    Modelo do Lumero: $padrao"
fi
echo "    O Ollama só liga quando o Lumero abre (e só escuta este Mac: 127.0.0.1)."
echo "    Para baixar outro modelo depois: ollama serve & ollama pull NOME"

# ----------------------------------------------------------------------------- 5
passo "5/6 Voz (opcional)"
if [ -z "$VOZ" ]; then
    if pergunta "    Instalar a voz? (/falar com o microfone e /ouvir as respostas; ~300 MB) [s/N]" n; then VOZ=1; else VOZ=0; fi
fi
if [ "$VOZ" = 1 ]; then
    brew install --quiet portaudio >/dev/null 2>&1 || true
    bash "$RAIZ/comum/instalar-voz.sh" "$PY" "$DADOS"
else
    echo "    Pulado. Sem instalar nada, o /ouvir já usa a voz Luciana do macOS."
fi

# ----------------------------------------------------------------------------- 6
passo "6/6 Permissões do macOS (na primeira vez que usar)"
echo "    • Ler a tela (/tela): Ajustes do Sistema → Privacidade e Segurança → Gravação de Tela → Terminal"
echo "    • Microfone (/falar): o macOS pergunta na primeira gravação"
echo "    • Desligar/reiniciar: o macOS pergunta se o Terminal pode controlar os \"Eventos do Sistema\""

echo
printf '\033[1;32m✓ Lumero instalado!\033[0m\n'
echo "  • Abra pelo Spotlight (Cmd+Espaço, digite Lumero) ou pelo Launchpad,"
echo "    ou digite  lumero  num Terminal novo."
echo "  • Configurações: $DADOS/config.json · Desinstalar: bash mac/desinstalar.sh"
