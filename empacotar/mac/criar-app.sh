#!/bin/bash
# Cria o Lumero.app e o .dmg para distribuir (roda no macOS; usado pelo GitHub Actions).
# O app baixado se instala sozinho na primeira vez que abre (roda o mac/instalar.sh no Terminal).
# Uso: bash empacotar/mac/criar-app.sh   ->  pacotes/Lumero-VERSAO-macOS.dmg
set -euo pipefail
RAIZ="$(cd "$(dirname "$0")/../.." && pwd)"
VERSAO="$(sed -n 's/^VERSAO = "\(.*\)".*/\1/p' "$RAIZ/lumero.py" | head -1)"
SAIDA="$RAIZ/pacotes"
TMP="$(mktemp -d)"
APP="$TMP/Lumero/Lumero.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/lumero" "$SAIDA"

cp "$RAIZ/assets/lumero.icns" "$APP/Contents/Resources/lumero.icns"
cp -R "$RAIZ/lumero.py" "$RAIZ/lumero_gui.py" "$RAIZ/lumero_gui.html" "$RAIZ/assets" "$RAIZ/mac" "$RAIZ/comum" "$RAIZ/instalador" "$APP/Contents/Resources/lumero/"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>Lumero</string>
    <key>CFBundleDisplayName</key><string>Lumero</string>
    <key>CFBundleIdentifier</key><string>com.lumero.app</string>
    <key>CFBundleVersion</key><string>$VERSAO</string>
    <key>CFBundleShortVersionString</key><string>$VERSAO</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleExecutable</key><string>Lumero</string>
    <key>CFBundleIconFile</key><string>lumero</string>
    <key>LSMinimumSystemVersion</key><string>14.0</string>
</dict>
</plist>
PLIST

cat > "$APP/Contents/MacOS/Lumero" <<'LANCADOR'
#!/bin/bash
# Abre a janela do Lumero. Na primeira vez, abre o instalador (janela ou Terminal).
RES="$(cd "$(dirname "$0")/../Resources/lumero" && pwd)"
DADOS="$HOME/Library/Application Support/Lumero"
geracao() { sed -n 's/^GERACAO = \([0-9]*\).*/\1/p' "$1" 2>/dev/null | head -1; }
if [ -x "$DADOS/venv/bin/python" ] && [ -f "$DADOS/Lumero.command" ]; then
    # app atualizado: copia o script novo (o anterior vai para os backups)
    NOVA="$(geracao "$RES/lumero.py")"; ATUAL="$(geracao "$DADOS/lumero.py")"
    if [ "${NOVA:-0}" -gt "${ATUAL:-0}" ]; then
        mkdir -p "$DADOS/backups"
        cp "$DADOS/lumero.py" "$DADOS/backups/lumero-antes-da-atualizacao-$(date +%Y%m%d-%H%M%S).py"
        cp "$RES/lumero.py" "$DADOS/lumero.py"
    fi
    cp "$RES/lumero_gui.py" "$RES/lumero_gui.html" "$DADOS/" 2>/dev/null
    export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
    exec "$DADOS/venv/bin/python" "$DADOS/lumero_gui.py"
elif xcode-select -p >/dev/null 2>&1 && [ -x /usr/bin/python3 ]; then
    # instalador com janela (abre no navegador)
    exec /usr/bin/python3 "$RES/instalador/instalador.py" --sem-app --app "$(cd "$(dirname "$0")/../.." && pwd)"
else
    INSTALAR="${TMPDIR:-/tmp}/lumero-instalar.command"
    {
        echo '#!/bin/bash'
        echo "printf '\\033]0;Instalando o Lumero\\007'"
        echo "if bash \"$RES/mac/instalar.sh\" --sem-app; then"
        echo '    echo; read -r -p "Aperte Enter para abrir o Lumero..." x'
        echo "    open -a \"$(cd "$(dirname "$0")/../.." && pwd)\""
        echo 'fi'
    } > "$INSTALAR"
    chmod +x "$INSTALAR"
    open "$INSTALAR"
fi
LANCADOR
chmod +x "$APP/Contents/MacOS/Lumero"

ln -s /Applications "$TMP/Lumero/Aplicativos"
DMG="$SAIDA/Lumero-$VERSAO-macOS.dmg"
rm -f "$DMG"
hdiutil create -volname "Lumero $VERSAO" -srcfolder "$TMP/Lumero" -ov -format UDZO "$DMG"
rm -rf "$TMP"
echo "Pronto: $DMG"
