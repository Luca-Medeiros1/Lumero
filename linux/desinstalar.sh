#!/usr/bin/env bash
# Remove o Lumero do Linux. Pergunta antes de apagar o Ollama, os modelos e os seus dados.
# Uso: bash linux/desinstalar.sh
set -uo pipefail
DADOS="${XDG_DATA_HOME:-$HOME/.local/share}/lumero"
BIN="$HOME/.local/bin"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICONES="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor"

pergunta() { local r; read -r -p "$1 " r; [[ "${r,,}" == s* ]]; }

pergunta "Remover o Lumero? [s/N]" || { echo "Nada foi removido."; exit 0; }

echo "==> Lumero, atalhos e lembretes"
systemctl --user disable --now 'lembrete-*.timer' 2>/dev/null
rm -f "$HOME"/.config/systemd/user/lembrete-*
systemctl --user daemon-reload 2>/dev/null
rm -f "$BIN/lumero" "$BIN/lumero-janela" "$APPS/lumero.desktop" \
      "$ICONES/scalable/apps/lumero.svg" "$ICONES/256x256/apps/lumero.png"
rm -rf "$DADOS/venv" "$DADOS/voz/piper-venv"
rm -f "$DADOS/lumero.py" "$DADOS/lumero.svg"
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

if command -v ollama >/dev/null && pergunta "Remover também o Ollama e TODOS os modelos baixados? [s/N]"; then
    echo "==> Ollama e modelos"
    sudo systemctl disable --now ollama 2>/dev/null
    sudo rm -f /etc/systemd/system/ollama.service
    sudo rm -rf /etc/systemd/system/ollama.service.d
    sudo systemctl daemon-reload
    sudo rm -f "$(command -v ollama)" /usr/local/bin/ollama /usr/bin/ollama
    sudo rm -rf /usr/local/lib/ollama /usr/lib/ollama /usr/share/ollama
    sudo userdel ollama 2>/dev/null
    sudo groupdel ollama 2>/dev/null
    rm -rf "$HOME/.ollama"
    echo 0 | sudo tee /sys/devices/system/cpu/intel_pstate/no_turbo >/dev/null 2>&1
else
    # o Ollama fica, mas sem as regras do Lumero
    sudo rm -f /etc/systemd/system/ollama.service.d/10-lumero.conf
    sudo systemctl daemon-reload 2>/dev/null
fi
sudo rm -f /etc/polkit-1/rules.d/49-lumero-ollama.rules /usr/local/bin/lumero-baixar-modelo
if [[ -f /etc/apparmor.d/lumero-bwrap ]]; then
    sudo apparmor_parser -R /etc/apparmor.d/lumero-bwrap 2>/dev/null
    sudo rm -f /etc/apparmor.d/lumero-bwrap
fi

if [[ -d "$DADOS" ]]; then
    if pergunta "Apagar também a memória, as conversas salvas e as configurações do Lumero? [s/N]"; then
        rm -rf "$DADOS"
    else
        echo "    Mantidos em $DADOS"
    fi
fi
echo
echo "✓ Lumero removido. (As notas em Documentos/Notas IA foram mantidas.)"
