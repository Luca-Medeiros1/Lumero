#!/usr/bin/env bash
# =============================================================================
#  Instalador do Lumero para Linux
#  Fedora · Ubuntu/Debian/Mint/Pop!_OS · Arch/Manjaro/EndeavourOS · openSUSE
#
#  Uso (dentro da pasta do Lumero):   bash linux/instalar.sh
#  Opções:  --sim          responde "sim" para tudo (instala com as escolhas padrão)
#           --voz          também instala a voz (/falar e /ouvir)
#           --sem-ollama   não mexe no Ollama (use se ele já estiver configurado)
# =============================================================================
set -euo pipefail

RAIZ="$(cd "$(dirname "$(realpath "$0")")/.." && pwd)"
DADOS="${XDG_DATA_HOME:-$HOME/.local/share}/lumero"
ANTIGO="$HOME/.local/share/assistente-ia"        # nome antigo (antes de virar Lumero)
BIN="$HOME/.local/bin"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICONES="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor"

SIM=0; VOZ=""; OLLAMA_SIM=1
for arg in "$@"; do
    case "$arg" in
        --sim) SIM=1 ;;
        --voz) VOZ=1 ;;
        --sem-voz) VOZ=0 ;;
        --sem-ollama) OLLAMA_SIM=0 ;;
        *) echo "Opção desconhecida: $arg"; exit 1 ;;
    esac
done
export LUMERO_SIM=$SIM

pergunta() {  # pergunta "texto" padrão(s/n) -> 0 = sim
    local resp padrao="$2"
    if [[ $SIM == 1 ]]; then [[ "$padrao" == s ]]; return; fi
    read -r -p "$1 " resp </dev/tty || resp=""
    resp="${resp:-$padrao}"
    [[ "${resp,,}" == s* || "${resp,,}" == y* ]]
}
passo() { printf '\n\033[1;33m==> %s\033[0m\n' "$*"; }
aviso() { printf '    \033[33m⚠️  %s\033[0m\n' "$*"; }

[[ $EUID -eq 0 ]] && { echo "Rode como o seu usuário normal (sem sudo). O instalador pede a senha quando precisar."; exit 1; }
for arq in lumero.py lumero_gui.py lumero_gui.html assets/lumero.svg linux/configurar-ollama.sh; do
    [[ -f "$RAIZ/$arq" ]] || { echo "Falta o arquivo $arq. Extraia o zip inteiro e rode de novo."; exit 1; }
done

# ----------------------------------------------------------------------------- 1
passo "1/7 Conferindo o sistema"
. /etc/os-release 2>/dev/null || true
echo "    Sistema: ${PRETTY_NAME:-Linux}"
if   command -v dnf    >/dev/null; then GER=dnf
elif command -v apt-get >/dev/null; then GER=apt
elif command -v pacman >/dev/null; then GER=pacman
elif command -v zypper >/dev/null; then GER=zypper
else
    echo "    Não reconheci o gerenciador de pacotes (dnf, apt, pacman ou zypper)."
    echo "    Instale à mão: python3, bubblewrap, curl e polkit, e rode de novo."
    exit 1
fi
echo "    Gerenciador de pacotes: $GER"
ram=$(awk '/MemTotal/ {printf "%d", $2/1024/1024 + 0.5}' /proc/meminfo)
echo "    RAM: ${ram} GB · Processador: $(nproc) núcleos"
if command -v nvidia-smi >/dev/null; then
    echo "    Placa de vídeo: $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null | head -1)"
fi

# ----------------------------------------------------------------------------- 2
passo "2/7 Programas necessários (vai pedir sua senha)"
case "$GER" in
    dnf)    PACOTES=(python3 python3-pip bubblewrap polkit curl zstd wl-clipboard xclip poppler-utils
                     ffmpeg-free 7zip git python3-gobject libnotify webkit2gtk4.1) ;;
    apt)    PACOTES=(python3 python3-venv python3-pip bubblewrap pkexec curl zstd wl-clipboard xclip
                     poppler-utils ffmpeg 7zip git python3-gi libnotify-bin gir1.2-webkit2-4.1) ;;
    pacman) PACOTES=(python python-pip bubblewrap polkit curl zstd wl-clipboard xclip poppler
                     ffmpeg 7zip git python-gobject libnotify webkit2gtk-4.1) ;;
    zypper) PACOTES=(python3 python3-pip bubblewrap polkit curl zstd wl-clipboard xclip poppler-tools
                     ffmpeg 7zip git python3-gobject libnotify-tools typelib-1_0-WebKit2-4_1) ;;
esac
instalar_pacotes() {
    case "$GER" in
        dnf)    sudo dnf install -y --skip-unavailable "$@" 2>/dev/null || sudo dnf install -y "$@" ;;
        apt)    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "$@" ;;
        pacman) sudo pacman -S --needed --noconfirm "$@" ;;
        zypper) sudo zypper --non-interactive install --no-recommends "$@" ;;
    esac
}
[[ $GER == apt ]] && sudo apt-get update -qq
if ! instalar_pacotes "${PACOTES[@]}" >/dev/null 2>&1; then
    # algum nome não existe nesta versão: instala um por um e segue com o que der
    for p in "${PACOTES[@]}"; do
        instalar_pacotes "$p" >/dev/null 2>&1 || { [[ $p == 7zip ]] && instalar_pacotes p7zip-full >/dev/null 2>&1; } \
            || aviso "não consegui instalar $p (o Lumero funciona sem ele, com menos recursos)"
    done
fi
command -v python3 >/dev/null || { echo "O Python 3 não instalou. Instale o python3 e rode de novo."; exit 1; }
echo "    Pronto."

# ----------------------------------------------------------------------------- 3
passo "3/7 Lumero"
mkdir -p "$DADOS" "$BIN" "$APPS" "$ICONES/scalable/apps" "$ICONES/256x256/apps"

# instalação antiga com o nome "assistente-ia": leva memória, conversas e lembretes junto
if [[ -d "$ANTIGO" && ! -e "$DADOS/memoria.md" ]]; then
    echo "    Encontrei a instalação antiga (assistente-ia): trazendo memória, conversas e lembretes."
    cp -a "$ANTIGO/." "$DADOS/"
    rm -f "$DADOS/assistente.py"
    for u in "$HOME"/.config/systemd/user/lembrete-*.service; do
        [[ -f "$u" ]] && sed -i "s|$ANTIGO|$DADOS|g" "$u"
    done
    for s in "$DADOS"/lembretes/*.sh; do
        [[ -f "$s" ]] && sed -i "s|$ANTIGO|$DADOS|g; s|-i assistente-ia|-i lumero|g" "$s"
    done
    systemctl --user daemon-reload 2>/dev/null || true
    mv "$ANTIGO" "$ANTIGO.antigo-$(date +%Y%m%d)"
    rm -f "$BIN/assistente" "$BIN/assistente-janela" "$APPS/assistente-ia.desktop" \
          "$ICONES/scalable/apps/assistente-ia.svg"
    echo "    (a pasta antiga ficou em $ANTIGO.antigo-$(date +%Y%m%d); pode apagar depois)"
fi

geracao() { grep -m1 -oP '^GERACAO = \K[0-9]+' "$1" 2>/dev/null || echo 0; }
if [[ -f "$DADOS/lumero.py" ]]; then
    G_NOVA=$(geracao "$RAIZ/lumero.py"); G_ATUAL=$(geracao "$DADOS/lumero.py")
    mkdir -p "$DADOS/backups"
    cp "$DADOS/lumero.py" "$DADOS/backups/lumero-antes-da-instalacao-$(date +%Y%m%d-%H%M%S).py"
    if (( G_NOVA < G_ATUAL )) && ! pergunta "    O instalado é a geração $G_ATUAL e este é a $G_NOVA (mais antiga). Substituir? [s/N]" n; then
        echo "    Mantive a geração $G_ATUAL."
    else
        cp "$RAIZ/lumero.py" "$DADOS/lumero.py"
    fi
else
    cp "$RAIZ/lumero.py" "$DADOS/lumero.py"
fi
cp "$RAIZ/assets/lumero.svg" "$DADOS/lumero.svg"
cp "$RAIZ/lumero_gui.py" "$RAIZ/lumero_gui.html" "$DADOS/"

echo "    Criando o ambiente Python do Lumero..."
PY="python3"
if python3 -m venv --system-site-packages "$DADOS/venv" >/dev/null 2>&1; then
    PY="$DADOS/venv/bin/python"
    "$PY" -m pip install --quiet --disable-pip-version-check prompt_toolkit psutil pillow pypdf \
        || aviso "não consegui instalar algumas bibliotecas (sem internet?). O Lumero funciona com menos recursos."
    "$PY" -m pip install --quiet --disable-pip-version-check pillow-heif >/dev/null 2>&1 || true
    # janela própria do chat (usa o WebKitGTK do sistema); sem ela, abre no navegador
    "$PY" -m pip install --quiet --disable-pip-version-check pywebview >/dev/null 2>&1 \
        || aviso "a janela própria não instalou: o chat vai abrir no navegador."
else
    aviso "não consegui criar o ambiente Python (venv). Usando o Python do sistema."
fi

cat > "$BIN/lumero-gui" <<EOF
#!/usr/bin/env bash
# Abre o Lumero na janela de chat
exec "$PY" "$DADOS/lumero_gui.py" "\$@"
EOF
chmod +x "$BIN/lumero-gui"

cat > "$BIN/lumero" <<EOF
#!/usr/bin/env bash
# Abre o Lumero neste terminal
exec "$PY" "$DADOS/lumero.py" "\$@"
EOF
chmod +x "$BIN/lumero"

# abre o Lumero numa janela de terminal (o terminal que existir)
cat > "$BIN/lumero-janela" <<'EOF'
#!/usr/bin/env bash
CMD="$HOME/.local/bin/lumero"
if command -v ptyxis >/dev/null; then
    if ptyxis --help 2>&1 | grep -q -- "--standalone"; then exec ptyxis --standalone -- "$CMD"; fi
    exec ptyxis -- "$CMD"
fi
for t in gnome-terminal kgx konsole xfce4-terminal mate-terminal tilix alacritty kitty foot \
         wezterm x-terminal-emulator xterm; do
    command -v "$t" >/dev/null || continue
    case "$t" in
        gnome-terminal)  exec gnome-terminal --title="Lumero" -- "$CMD" ;;
        kgx|tilix)       exec "$t" -- "$CMD" ;;
        xfce4-terminal)  exec xfce4-terminal --title="Lumero" -x "$CMD" ;;
        mate-terminal)   exec mate-terminal --title="Lumero" -x "$CMD" ;;
        wezterm)         exec wezterm start -- "$CMD" ;;
        *)               exec "$t" -e "$CMD" ;;
    esac
done
notify-send "Lumero" "Não achei um programa de terminal. Abra um terminal e digite: lumero"
EOF
chmod +x "$BIN/lumero-janela"

cp "$RAIZ/assets/lumero.svg" "$ICONES/scalable/apps/lumero.svg"
[[ -f "$RAIZ/assets/lumero.png" ]] && cp "$RAIZ/assets/lumero.png" "$ICONES/256x256/apps/lumero.png"
cat > "$APPS/lumero.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Lumero
GenericName=Assistente de IA local
Comment=IA local que pesquisa, acha arquivos e executa tarefas no computador
Exec=$BIN/lumero-gui
Icon=lumero
Terminal=false
Categories=Utility;
Keywords=lumero;ia;ai;ollama;assistente;chat;
StartupNotify=true
StartupWMClass=lumero
Actions=terminal;

[Desktop Action terminal]
Name=Abrir no terminal
Exec=$BIN/lumero-janela
EOF
update-desktop-database "$APPS" 2>/dev/null || true
gtk-update-icon-cache -f -t "$ICONES" 2>/dev/null || true

if [[ ":$PATH:" != *":$BIN:"* ]]; then
    for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
        [[ -f "$rc" ]] && ! grep -q 'Lumero: ~/.local/bin' "$rc" && \
            printf '\n# Lumero: ~/.local/bin no PATH\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$rc"
    done
fi

# ----------------------------------------------------------------------------- 4
passo "4/7 Atalho de teclado"
ATALHO="${ATALHO:-<Control><Alt>a}"
ESQ="org.gnome.settings-daemon.plugins.media-keys"
CAM_ANTIGO="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/assistente-ia/"
CAM="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/lumero/"
if command -v gsettings >/dev/null && gsettings list-keys "$ESQ" >/dev/null 2>&1; then
    atuais="$(gsettings get "$ESQ" custom-keybindings)"
    if [[ "$atuais" == *"$CAM_ANTIGO"* ]]; then   # tira o atalho antigo
        gsettings reset-recursively "$ESQ.custom-keybinding:$CAM_ANTIGO" 2>/dev/null || true
        atuais="$(echo "$atuais" | sed "s|, '$CAM_ANTIGO'||; s|'$CAM_ANTIGO', ||; s|'$CAM_ANTIGO'||")"
    fi
    if [[ "$atuais" != *"$CAM"* ]]; then
        if [[ "$atuais" == "@as []" || "$atuais" == "[]" ]]; then atuais="['$CAM']"
        else atuais="${atuais%]}, '$CAM']"; fi
    fi
    gsettings set "$ESQ" custom-keybindings "$atuais"
    gsettings set "$ESQ.custom-keybinding:$CAM" name "Lumero"
    gsettings set "$ESQ.custom-keybinding:$CAM" command "$BIN/lumero-gui"
    gsettings set "$ESQ.custom-keybinding:$CAM" binding "$ATALHO"
    echo "    Ctrl+Alt+A abre o Lumero (muda em Configurações → Teclado → Atalhos)."
else
    echo "    Seu ambiente não é o GNOME: crie o atalho nas configurações de teclado"
    echo "    apontando para: $BIN/lumero-gui"
fi

# ----------------------------------------------------------------------------- 5
passo "5/7 Ollama (a IA que roda no seu computador)"
if [[ $OLLAMA_SIM == 1 ]]; then
    bash "$RAIZ/linux/configurar-ollama.sh"
else
    echo "    Pulado (--sem-ollama)."
fi

# ----------------------------------------------------------------------------- 6
passo "6/7 Conferindo a proteção dos comandos (sandbox)"
if command -v bwrap >/dev/null; then
    if bwrap --ro-bind / / --dev /dev --proc /proc --unshare-net true 2>/dev/null; then
        echo "    A sandbox funciona: os comandos da IA só alteram a sua pasta pessoal."
    elif [[ -d /etc/apparmor.d ]] && command -v apparmor_parser >/dev/null; then
        aviso "o AppArmor deste sistema bloqueia a sandbox (comum no Ubuntu 24.04 ou mais novo)."
        if pergunta "    Liberar o bubblewrap no AppArmor para o Lumero poder rodar comandos? [S/n]" s; then
            sudo tee /etc/apparmor.d/lumero-bwrap >/dev/null <<'EOF'
# Criado pelo instalador do Lumero: deixa o bubblewrap criar a sandbox dos comandos
abi <abi/4.0>,
include <tunables/global>

profile lumero-bwrap /usr/bin/bwrap flags=(unconfined) {
  userns,
  include if exists <local/lumero-bwrap>
}
EOF
            sudo apparmor_parser -r /etc/apparmor.d/lumero-bwrap \
                && bwrap --ro-bind / / --dev /dev --proc /proc --unshare-net true 2>/dev/null \
                && echo "    Pronto, a sandbox funciona." \
                || aviso "ainda não funcionou. A IA não vai conseguir rodar comandos de terminal."
        fi
    else
        aviso "a sandbox não funcionou. A IA não vai conseguir rodar comandos de terminal."
    fi
else
    aviso "o bubblewrap não instalou: a IA não vai conseguir rodar comandos de terminal."
fi

# ----------------------------------------------------------------------------- 7
passo "7/7 Voz (opcional)"
if [[ -z "$VOZ" ]]; then
    pergunta "    Instalar a voz? (/falar com o microfone e /ouvir as respostas; ~300 MB) [s/N]" n && VOZ=1 || VOZ=0
fi
if [[ $VOZ == 1 ]]; then
    case "$GER" in
        dnf)    instalar_pacotes espeak-ng portaudio >/dev/null 2>&1 || true ;;
        apt)    instalar_pacotes espeak-ng libportaudio2 >/dev/null 2>&1 || true ;;
        pacman) instalar_pacotes espeak-ng portaudio >/dev/null 2>&1 || true ;;
        zypper) instalar_pacotes espeak-ng portaudio >/dev/null 2>&1 || true ;;
    esac
    bash "$RAIZ/comum/instalar-voz.sh" "$PY" "$DADOS"
else
    echo "    Pulado. Para instalar depois: bash linux/instalar.sh --voz"
fi

echo
printf '\033[1;32m✓ Lumero instalado!\033[0m\n'
echo "  • Procure \"Lumero\" no menu de aplicativos ou aperte Ctrl+Alt+A (GNOME): abre a janela de chat."
echo "  • Prefere o terminal? Digite  lumero  (num terminal novo) ou clique com o botão"
echo "    direito no ícone do Lumero → Abrir no terminal."
echo "  • O Ollama liga quando o Lumero abre e desliga quando você sai."
echo "  • Configurações: $DADOS/config.json · Desinstalar: bash linux/desinstalar.sh"
