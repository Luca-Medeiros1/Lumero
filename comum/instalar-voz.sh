#!/usr/bin/env bash
# Instala a voz do Lumero (Linux e Mac). Depois de instalada, tudo roda offline:
#   - reconhecimento de fala (/falar): whisper.cpp (pywhispercpp) + microfone (sounddevice)
#   - leitura das respostas (/ouvir): Piper (voz neural); se falhar, usa a voz do sistema
# Uso: bash comum/instalar-voz.sh CAMINHO_DO_PYTHON_DO_LUMERO PASTA_DE_DADOS
set -uo pipefail
PY="${1:?informe o python do Lumero}"
DADOS="${2:?informe a pasta de dados}"
VOZ_DIR="$DADOS/voz"
VOZ="pt_BR-faber-medium"
mkdir -p "$VOZ_DIR/whisper"

echo "    Reconhecimento de fala e microfone..."
if "$PY" -m pip install --quiet --disable-pip-version-check pywhispercpp sounddevice numpy; then
    echo "    ✓ /falar instalado (o modelo de ~150 MB é baixado no primeiro uso)."
else
    echo "    ⚠️  Não consegui instalar o reconhecimento de fala."
fi

echo "    Voz neural (Piper)..."
VENV="$VOZ_DIR/piper-venv"
BASE_PY="$(command -v python3)"
rm -rf "$VENV"
if "$BASE_PY" -m venv "$VENV" >/dev/null 2>&1 \
   && "$VENV/bin/pip" install --quiet --disable-pip-version-check piper-tts \
   && (cd "$VOZ_DIR" && "$VENV/bin/python" -m piper.download_voices "$VOZ" --data-dir "$VOZ_DIR" >/dev/null 2>&1); then
    echo "    ✓ Voz $VOZ instalada."
else
    rm -rf "$VENV"
    if [[ "$(uname)" == Darwin ]]; then
        echo "    O Piper não instalou: o Lumero vai usar a voz Luciana do macOS."
    else
        echo "    O Piper não instalou: o Lumero vai usar a voz do espeak-ng."
    fi
fi
