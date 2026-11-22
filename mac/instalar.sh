#!/bin/bash
# =============================================================================
#  Instalador do Lumero para macOS (Apple Silicon e Intel)
#
#  Uso: abra o Terminal, entre na pasta do Lumero e rode:   bash mac/instalar.sh
#  Abre o instalador com janela. Para instalar pelo Terminal: bash mac/instalar.sh --terminal
#  Opções:  --sim   responde "sim" para tudo     --voz   também instala a voz
#           --nao-interativo --modelos "a b"   usado pelo instalador com janela
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

SIM=0; VOZ=""; CRIAR_APP=1; TERMINAL=0; NAO_INTERATIVO=0; MODELOS_ARG="-"
while [ $# -gt 0 ]; do
    case "$1" in
        --sim) SIM=1; TERMINAL=1 ;;
        --terminal) TERMINAL=1 ;;
        --nao-interativo) NAO_INTERATIVO=1; SIM=1; TERMINAL=1 ;;
        --modelos) MODELOS_ARG="$2"; shift ;;
        --sem-app) CRIAR_APP=0 ;;
        --voz) VOZ=1 ;;
        --sem-voz) VOZ=0 ;;
        *) echo "Opção desconhecida: $1"; exit 1 ;;
    esac
    shift
done
export NONINTERACTIVE=$NAO_INTERATIVO   # Homebrew sem perguntas (a senha vem pelo SUDO_ASKPASS)

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
if [ "$TERMINAL" = 0 ] && [ -f "$RAIZ/instalador/instalador.py" ] && /usr/bin/xcode-select -p >/dev/null 2>&1; then
    echo "Abrindo o instalador do Lumero..."
    exec /usr/bin/python3 "$RAIZ/instalador/instalador.py" $([ "$CRIAR_APP" = 0 ] && echo --sem-app)
fi
for arq in lumero.py lumero_gui.py lumero_gui.html assets/lumero.icns; do
    [ -f "$RAIZ/$arq" ] || { echo "Falta o arquivo $arq. Extraia o zip inteiro e rode de novo."; exit 1; }
done

# ----------------------------------------------------------------------------- 1
echo "##PASSO pacotes"
passo "1/6 Conferindo o Mac"
echo "    macOS $(sw_vers -productVersion) · $(uname -m)"
if [ "$(sw_vers -productVersion | cut -d. -f1)" -lt 14 ]; then
    echo "    O Ollama precisa do macOS 14 (Sonoma) ou mais novo. Atualize o macOS e rode de novo."
    exit 1
fi
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
    if [ "$NAO_INTERATIVO" = 1 ] || pergunta "    Instalar o Homebrew agora? Ele pede a sua senha do Mac. [S/n]" s; then
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
echo "##PASSO lumero"
passo "3/6 Lumero"
mkdir -p "$DADOS" "$BIN" "$HOME/Applications"
if [ -f "$DADOS/lumero.py" ]; then
    mkdir -p "$DADOS/backups"
    cp "$DADOS/lumero.py" "$DADOS/backups/lumero-antes-da-instalacao-$(date +%Y%m%d-%H%M%S).py"
fi
cp "$RAIZ/lumero.py" "$DADOS/lumero.py"
cp "$RAIZ/lumero_gui.py" "$RAIZ/lumero_gui.html" "$DADOS/"
cp "$RAIZ/mac/desinstalar.sh" "$DADOS/desinstalar.sh" && chmod +x "$DADOS/desinstalar.sh"
cp "$RAIZ/assets/lumero.svg" "$DADOS/lumero.svg" 2>/dev/null || true

echo "    Criando o ambiente Python do Lumero..."
rm -rf "$DADOS/venv"
"$PY_BASE" -m venv "$DADOS/venv"
PY="$DADOS/venv/bin/python"
"$PY" -m pip install --quiet --disable-pip-version-check prompt_toolkit psutil pillow pillow-heif pypdf \
    || aviso "não consegui instalar algumas bibliotecas (sem internet?)."
# janela própria do chat (usa o WebKit do macOS); sem ela, abre no navegador
"$PY" -m pip install --quiet --disable-pip-version-check pywebview \
    || aviso "a janela própria não instalou: o chat vai abrir no navegador."

cat > "$BIN/lumero-gui" <<EOF
#!/bin/bash
# Abre o Lumero na janela de chat
export PATH="$(brew --prefix)/bin:/usr/local/bin:\$PATH"
exec "$PY" "$DADOS/lumero_gui.py" "\$@"
EOF
chmod +x "$BIN/lumero-gui"

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
    <key>LSMinimumSystemVersion</key><string>14.0</string>
</dict>
</plist>
EOF
cat > "$APP/Contents/MacOS/Lumero" <<EOF
#!/bin/bash
exec "$BIN/lumero-gui"
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
if [ "$NAO_INTERATIVO" != 1 ]; then
    NOME="$("$PY" "$RAIZ/instalador/hardware.py" --nome 2>/dev/null)"
    if [ "$SIM" != 1 ]; then
        read -r -p "    Como você quer que o Lumero te chame? [${NOME:-sem nome}]: " resp </dev/tty || resp=""
        [ -n "$resp" ] && NOME="$resp"
    fi
    [ -n "$NOME" ] && "$PY" "$RAIZ/instalador/hardware.py" --gravar-nome "$NOME" >/dev/null
fi
if [ "$MODELOS_ARG" = "-" ]; then   # Terminal: mostra a análise e pergunta
    ANALISE="$("$PY" "$RAIZ/instalador/hardware.py" --json)"
    "$PY" "$RAIZ/instalador/hardware.py"
    REC="$("$PY" -c 'import json,sys; d=json.loads(sys.argv[1]); print([i for i, m in enumerate(d["modelos"], 1) if m["recomendado"]][0])' "$ANALISE")"
    escolha="$REC"
    if [ "$SIM" != 1 ]; then
        read -r -p "    Quais baixar? (números separados por espaço, 0 = nenhum) [$REC]: " escolha </dev/tty || true
        escolha="${escolha:-$REC}"
    fi
    MODELOS_ARG="$("$PY" -c 'import json,sys
d = json.loads(sys.argv[1]); nomes = []
for n in sys.argv[2].split():
    if n.isdigit() and 1 <= int(n) <= len(d["modelos"]):
        nomes.append(d["modelos"][int(n) - 1]["nome"])
print(" ".join(nomes))' "$ANALISE" "$escolha")"
fi
echo "##PASSO modelos"
padrao=""
for modelo in $MODELOS_ARG; do
    echo "##MODELO $modelo"
    echo "    Baixando $modelo..."
    if "$OLLAMA_BIN" pull "$modelo" 2>&1; then
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
    CTX="$("$PY" "$RAIZ/instalador/hardware.py" --gravar-contexto "$padrao")"
    echo "    Contexto da conversa: $((CTX / 1024))K tokens (mude no Lumero com /contexto)"
fi
echo "    O Ollama só liga quando o Lumero abre (e só escuta este Mac: 127.0.0.1)."
echo "    Para baixar outro modelo depois: ollama serve & ollama pull NOME"

# ----------------------------------------------------------------------------- 5
passo "5/6 Voz (opcional)"
[ "$VOZ" = 1 ] && echo "##PASSO voz"
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
echo "##PASSO seguranca"
passo "6/6 Permissões do macOS (na primeira vez que usar)"
echo "    • Ler a tela (/tela): Ajustes do Sistema → Privacidade e Segurança → Gravação de Tela → Terminal"
echo "    • Microfone (/falar): o macOS pergunta na primeira gravação"
echo "    • Desligar/reiniciar: o macOS pergunta se o Terminal pode controlar os \"Eventos do Sistema\""

echo
printf '\033[1;32m✓ Lumero instalado!\033[0m\n'
echo "  • Abra pelo Spotlight (Cmd+Espaço, digite Lumero) ou pelo Launchpad: abre a janela de chat."
echo "  • Prefere o terminal? Digite  lumero  num Terminal novo."
echo "  • Configurações: $DADOS/config.json · Desinstalar: bash mac/desinstalar.sh"
echo "##FIM"
