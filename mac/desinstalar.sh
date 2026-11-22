#!/bin/bash
# Remove o Lumero do macOS. Pergunta antes de apagar o Ollama, os modelos e os seus dados.
# Uso: bash mac/desinstalar.sh
set -u
DADOS="$HOME/Library/Application Support/Lumero"
pergunta() { local r; read -r -p "$1 " r; case "$(echo "$r" | tr '[:upper:]' '[:lower:]')" in s*|y*) return 0 ;; *) return 1 ;; esac; }

pergunta "Remover o Lumero? [s/N]" || { echo "Nada foi removido."; exit 0; }

echo "==> Lumero e lembretes"
for plist in "$HOME"/Library/LaunchAgents/com.lumero.lembrete-*.plist; do
    [ -f "$plist" ] || continue
    rotulo="$(basename "$plist" .plist)"
    launchctl bootout "gui/$(id -u)/$rotulo" 2>/dev/null || launchctl unload "$plist" 2>/dev/null
    rm -f "$plist"
done
pkill -f "$DADOS/lumero.py" 2>/dev/null
pkill -f "$DADOS/lumero_gui.py" 2>/dev/null
rm -rf "$HOME/Applications/Lumero.app" "$HOME/.local/bin/lumero" \
       "$DADOS/venv" "$DADOS/voz/piper-venv" "$DADOS/lumero.py" "$DADOS/Lumero.command" \
       "$HOME/.local/bin/lumero-gui" "$DADOS/lumero_gui.py" "$DADOS/lumero_gui.html" "$DADOS/gui.json"

if pergunta "Remover também o Ollama e TODOS os modelos baixados? [s/N]"; then
    echo "==> Ollama e modelos"
    pkill -x ollama 2>/dev/null
    command -v brew >/dev/null && brew uninstall --quiet ollama 2>/dev/null
    rm -rf "$HOME/.ollama"
    [ -d /Applications/Ollama.app ] && echo "    (O Ollama.app em Aplicativos foi mantido: arraste para o Lixo se quiser.)"
fi

if [ -d "$DADOS" ] && pergunta "Apagar também a memória, as conversas salvas e as configurações? [s/N]"; then
    rm -rf "$DADOS"
fi
echo
echo "✓ Lumero removido. (A linha do PATH em ~/.zprofile e as notas em Documentos/Notas IA foram mantidas.)"
