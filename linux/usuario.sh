#!/usr/bin/env bash
# =============================================================================
#  Parte do instalador do Lumero que roda como o seu usuário (Linux), sem perguntas:
#  copia o Lumero, cria o ambiente Python, os atalhos, o ícone e o atalho de teclado.
#  Chamado pelo instalar.sh (terminal) e pelo instalador com janela.
#
#  Opções:  --modelo NOME     modelo padrão gravado no config.json
#           --voz 0|1         instala a voz (/falar e /ouvir)
#           --substituir 0|1  substitui uma geração mais nova já instalada (padrão: 0)
# =============================================================================
set -euo pipefail

RAIZ="$(cd "$(dirname "$(realpath "$0")")/.." && pwd)"
DADOS="${XDG_DATA_HOME:-$HOME/.local/share}/lumero"
ANTIGO="$HOME/.local/share/assistente-ia"        # nome antigo (antes de virar Lumero)
BIN="$HOME/.local/bin"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICONES="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor"

MODELO=""; VOZ=0; SUBSTITUIR=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --modelo) MODELO="$2"; shift 2 ;;
        --voz) VOZ="$2"; shift 2 ;;
        --substituir) SUBSTITUIR="$2"; shift 2 ;;
        *) echo "Opção desconhecida: $1"; exit 2 ;;
    esac
done
[[ $EUID -eq 0 ]] && { echo "##ERRO Esta parte roda como o seu usuário, sem sudo."; exit 1; }
aviso() { echo "    ⚠️  $*"; }
pergunta() { [[ $SUBSTITUIR == 1 ]]; }   # sem perguntas: só substitui se pediram

echo "##PASSO lumero"
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
    if (( G_NOVA < G_ATUAL )) && ! pergunta; then
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


# ----------------------------------------------------------------------------- config
if [[ -n "$MODELO" ]]; then
    python3 - "$DADOS/config.json" "$MODELO" <<'EOF'
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
    echo "Modelo do Lumero: $MODELO"
fi

# ----------------------------------------------------------------------------- atalho
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


# ----------------------------------------------------------------------------- voz
if [[ $VOZ == 1 ]]; then
    echo "##PASSO voz"
    bash "$RAIZ/comum/instalar-voz.sh" "$PY" "$DADOS"
fi
echo "##FIM"
