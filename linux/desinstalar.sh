#!/usr/bin/env bash
# Remove o Lumero do Linux. Pergunta antes de apagar o Ollama, os modelos e os seus dados.
# Uso: bash linux/desinstalar.sh
#      bash desinstalar.sh --sim --ollama 0|1 --dados 0|1   (sem perguntas; o Lumero usa isto)
#      --pacote   também remove o pacote .deb/.rpm/Arch do Lumero
# A senha é pedida uma vez: no terminal pelo sudo, fora dele pela janela do sistema (pkexec).
set -uo pipefail
DADOS="${XDG_DATA_HOME:-$HOME/.local/share}/lumero"
BIN="$HOME/.local/bin"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICONES="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor"

SIM=0; OLLAMA_RESP=""; DADOS_RESP=""; PACOTE=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --sim) SIM=1 ;;
        --ollama) OLLAMA_RESP="$2"; shift ;;
        --dados) DADOS_RESP="$2"; shift ;;
        --pacote) PACOTE=1 ;;
        *) echo "Opção desconhecida: $1"; exit 1 ;;
    esac
    shift
done
[[ -f /usr/share/lumero/lumero.py && "$(dirname "$(realpath "$0")")" == /usr/share/lumero ]] && PACOTE=1

pergunta() {  # pergunta "texto" resposta_pronta -> 0 = sim
    if [[ -n "$2" ]]; then [[ "$2" == 1 ]]; return; fi
    if [[ $SIM == 1 ]]; then return 1; fi
    local r; read -r -p "$1 " r; [[ "${r,,}" == s* ]]
}
avisar() {  # notificação no fim (quem chamou pela janela não vê o terminal)
    command -v notify-send >/dev/null && notify-send -i dialog-information "Lumero" "$1" 2>/dev/null
    echo "$1"
}

if [[ $SIM != 1 ]]; then
    read -r -p "Remover o Lumero? [s/N] " r
    [[ "${r,,}" == s* ]] || { echo "Nada foi removido."; exit 0; }
fi
REMOVER_OLLAMA=0; APAGAR_DADOS=0
command -v ollama >/dev/null && pergunta "Remover também o Ollama e TODOS os modelos baixados? [s/N]" "$OLLAMA_RESP" && REMOVER_OLLAMA=1
[[ -d "$DADOS" ]] && pergunta "Apagar também a memória, as conversas salvas e as configurações do Lumero? [s/N]" "$DADOS_RESP" && APAGAR_DADOS=1

echo "==> Lumero, atalhos e lembretes"
systemctl --user disable --now 'lembrete-*.timer' 2>/dev/null
rm -f "$HOME"/.config/systemd/user/lembrete-*
systemctl --user daemon-reload 2>/dev/null
pkill -f "lumero_gui.py" 2>/dev/null
pkill -f "instalador/instalador.py" 2>/dev/null
rm -f "$BIN/lumero" "$BIN/lumero-janela" "$BIN/lumero-gui" "$APPS/lumero.desktop" "$APPS/lumero-instalador.desktop" \
      "$ICONES/scalable/apps/lumero.svg" "$ICONES/256x256/apps/lumero.png"
rm -rf "$DADOS/venv" "$DADOS/voz/piper-venv"
rm -f "$DADOS/lumero.py" "$DADOS/lumero.svg" "$DADOS/lumero_gui.py" "$DADOS/lumero_gui.html" "$DADOS/gui.json" \
      "$DADOS/desinstalar.sh"
ESQ="org.gnome.settings-daemon.plugins.media-keys"
CAM="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/lumero/"
if command -v gsettings >/dev/null && gsettings list-keys "$ESQ" >/dev/null 2>&1; then
    gsettings reset-recursively "$ESQ.custom-keybinding:$CAM" 2>/dev/null
    atuais="$(gsettings get $ESQ custom-keybindings)"
    novos="$(echo "$atuais" | sed "s|, '$CAM'||; s|'$CAM', ||; s|'$CAM'||")"
    [[ "$novos" == "[]" ]] && novos="@as []"
    gsettings set $ESQ custom-keybindings "$novos"
fi
update-desktop-database "$APPS" 2>/dev/null
[[ $REMOVER_OLLAMA == 1 ]] && rm -rf "$HOME/.ollama"
if [[ $APAGAR_DADOS == 1 ]]; then
    rm -rf "$DADOS"
elif [[ -d "$DADOS" ]]; then
    echo "    Memória, conversas e configurações mantidas em $DADOS"
fi

# ---------------------------------------------------------------- parte de administrador (uma senha só)
RAIZ_SCRIPT="$(mktemp)"
{
    echo 'set -u'
    if [[ $REMOVER_OLLAMA == 1 ]]; then
        echo 'echo "==> Ollama e modelos"'
        echo 'systemctl disable --now ollama 2>/dev/null'
        echo 'rm -f /etc/systemd/system/ollama.service'
        echo 'rm -rf /etc/systemd/system/ollama.service.d'
        echo 'systemctl daemon-reload'
        echo 'rm -f /usr/local/bin/ollama /usr/bin/ollama'
        echo 'rm -rf /usr/local/lib/ollama /usr/lib/ollama /usr/share/ollama'
        echo 'userdel ollama 2>/dev/null; groupdel ollama 2>/dev/null'
        echo 'echo 0 > /sys/devices/system/cpu/intel_pstate/no_turbo 2>/dev/null'
    else
        echo '# o Ollama fica, mas sem as regras do Lumero'
        echo 'rm -f /etc/systemd/system/ollama.service.d/10-lumero.conf /etc/systemd/system/ollama.service.d/20-sem-internet.conf'
        echo 'systemctl daemon-reload 2>/dev/null'
    fi
    echo 'rm -f /etc/polkit-1/rules.d/49-lumero-ollama.rules /usr/local/bin/lumero-baixar-modelo'
    echo 'if [ -f /etc/apparmor.d/lumero-bwrap ]; then apparmor_parser -R /etc/apparmor.d/lumero-bwrap 2>/dev/null; rm -f /etc/apparmor.d/lumero-bwrap; fi'
    if [[ $PACOTE == 1 ]]; then
        echo 'echo "==> Pacote do Lumero"'
        echo 'if command -v dnf >/dev/null; then dnf remove -y lumero'
        echo 'elif command -v zypper >/dev/null; then zypper --non-interactive remove lumero'
        echo 'elif command -v pacman >/dev/null; then pacman -R --noconfirm lumero'
        echo 'elif command -v apt-get >/dev/null; then DEBIAN_FRONTEND=noninteractive apt-get remove -y lumero; fi'
    fi
} > "$RAIZ_SCRIPT"
if [[ -t 0 ]] && command -v sudo >/dev/null; then
    sudo bash "$RAIZ_SCRIPT"; codigo=$?
elif command -v pkexec >/dev/null; then
    pkexec /bin/bash "$RAIZ_SCRIPT"; codigo=$?
else
    codigo=1
fi
rm -f "$RAIZ_SCRIPT"

echo
if [[ $codigo == 0 ]]; then
    avisar "✓ Lumero removido. (As notas em Documentos/Notas IA foram mantidas.)"
else
    avisar "Lumero removido da sua pasta, mas a parte de administrador não rodou (senha cancelada?). Rode de novo: bash linux/desinstalar.sh"
fi
