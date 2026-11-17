#!/usr/bin/env bash
# =============================================================================
#  Instala e configura o Ollama para o Lumero (Linux).
#  Usado pelo instalar.sh e pelos pacotes .deb/.rpm (na primeira vez que o Lumero abre).
#
#  - instala o Ollama (script oficial de ollama.com) se ainda não estiver instalado
#  - o Ollama só escuta neste computador (127.0.0.1) e, se você quiser, fica sem internet
#  - não liga sozinho com o computador: o Lumero liga ao abrir e desliga ao sair
#  - modo econômico opcional (para notebooks): limita a CPU e desliga o turbo
#  - baixa os modelos que você escolher
# =============================================================================
set -euo pipefail

CONF_DIR="/etc/systemd/system/ollama.service.d"
API="http://127.0.0.1:11434"
DADOS="${XDG_DATA_HOME:-$HOME/.local/share}/lumero"
SIM="${LUMERO_SIM:-0}"

pergunta() {
    local resp padrao="$2"
    if [[ $SIM == 1 ]]; then [[ "$padrao" == s ]]; return; fi
    read -r -p "$1 " resp </dev/tty || resp=""
    resp="${resp:-$padrao}"
    [[ "${resp,,}" == s* || "${resp,,}" == y* ]]
}
aviso() { printf '    \033[33m⚠️  %s\033[0m\n' "$*"; }
esperar_ollama() {
    for _ in $(seq 1 60); do
        curl -fs "$API/api/version" >/dev/null 2>&1 && return 0
        sleep 0.5
    done
    return 1
}
gravar_config() {  # gravar_config CHAVE VALOR  (no config.json do usuário)
    mkdir -p "$DADOS"
    python3 - "$DADOS/config.json" "$1" "$2" <<'EOF'
import json, sys
arquivo, chave, valor = sys.argv[1:4]
try:
    with open(arquivo, encoding="utf-8") as f:
        dados = json.load(f)
except (OSError, ValueError):
    dados = {}
dados[chave] = valor
with open(arquivo, "w", encoding="utf-8") as f:
    json.dump(dados, f, indent=2, ensure_ascii=False)
EOF
}

[[ $EUID -eq 0 ]] && { echo "Rode como o seu usuário normal (sem sudo)."; exit 1; }
command -v systemctl >/dev/null || { echo "Este instalador precisa do systemd."; exit 1; }

# ------------------------------------------------------------------ instalar
if ! command -v ollama >/dev/null; then
    echo "    Baixando o Ollama do site oficial (ollama.com)..."
    curl -fsSL https://ollama.com/install.sh | sh
else
    echo "    Ollama já instalado: $(ollama --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)"
fi
if ! systemctl cat ollama.service >/dev/null 2>&1; then
    # instalado por outro caminho, sem serviço: cria um igual ao do script oficial
    OLLAMA_BIN="$(command -v ollama)"
    id ollama >/dev/null 2>&1 || sudo useradd -r -s /bin/false -U -m -d /usr/share/ollama ollama
    sudo tee /etc/systemd/system/ollama.service >/dev/null <<EOF
[Unit]
Description=Ollama Service
After=network-online.target

[Service]
ExecStart=$OLLAMA_BIN serve
User=ollama
Group=ollama
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
EOF
fi

# ------------------------------------------------------------------ modo econômico
ram=$(awk '/MemTotal/ {printf "%d", $2/1024/1024 + 0.5}' /proc/meminfo)
vram=0
if command -v nvidia-smi >/dev/null; then
    vram=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -dc 0-9)
    vram=${vram:-0}
fi
tem_bateria=0; ls /sys/class/power_supply/BAT* >/dev/null 2>&1 && tem_bateria=1
padrao_eco=n
[[ $tem_bateria == 1 || -f "$CONF_DIR/10-economico.conf" ]] && padrao_eco=s

echo
echo "    Modo econômico: limita o processador e desliga o turbo enquanto a IA roda."
echo "    Fica mais lento, mas esquenta menos e evita desligamentos em notebooks com bateria fraca."
eco=0
if pergunta "    Ligar o modo econômico? [$( [[ $padrao_eco == s ]] && echo S/n || echo s/N )]" $padrao_eco; then eco=1; fi

nucleos=$(nproc)
cota=$(( nucleos * 3 / 8 )); (( cota < 1 )) && cota=1
sudo mkdir -p "$CONF_DIR"
sudo rm -f "$CONF_DIR/10-economico.conf"     # versão antiga (assistente-ia)
{
    echo "# Criado pelo instalador do Lumero"
    echo "[Service]"
    echo "# só aceita conexões deste computador"
    echo 'Environment="OLLAMA_HOST=127.0.0.1:11434"'
    echo 'Environment="OLLAMA_KEEP_ALIVE=30m"'
    echo 'Environment="OLLAMA_MAX_LOADED_MODELS=1"'
    echo 'Environment="OLLAMA_NUM_PARALLEL=1"'
    echo 'Environment="OLLAMA_CONTEXT_LENGTH=8192"'
    echo "Nice=5"
    if (( vram > 0 && vram < 4000 )); then
        echo "# placa de vídeo com pouca memória ($vram MB): só atrapalha, usa só o processador"
        echo 'Environment="CUDA_VISIBLE_DEVICES=-1"'
    fi
    if [[ $eco == 1 ]]; then
        echo "# modo econômico: limita a CPU e desliga o turbo enquanto o Ollama estiver ligado"
        echo "CPUQuota=$(( cota * 100 ))%"
        echo "ExecStartPre=+/bin/sh -c 'echo 1 > /sys/devices/system/cpu/intel_pstate/no_turbo 2>/dev/null; echo 0 > /sys/devices/system/cpu/cpufreq/boost 2>/dev/null; true'"
        echo "ExecStopPost=+/bin/sh -c 'echo 0 > /sys/devices/system/cpu/intel_pstate/no_turbo 2>/dev/null; echo 1 > /sys/devices/system/cpu/cpufreq/boost 2>/dev/null; true'"
    fi
} | sudo tee "$CONF_DIR/10-lumero.conf" >/dev/null
(( vram > 0 && vram < 4000 )) && echo "    Placa de vídeo com ${vram} MB: o Ollama vai usar só o processador."

# você (e o Lumero) podem ligar e desligar o Ollama sem digitar senha
sudo rm -f /etc/polkit-1/rules.d/49-assistente-ollama.rules
sudo mkdir -p /etc/polkit-1/rules.d
sudo tee /etc/polkit-1/rules.d/49-lumero-ollama.rules >/dev/null <<EOF
// Criado pelo instalador do Lumero: o usuário $USER pode ligar/desligar o Ollama sem senha
polkit.addRule(function(action, subject) {
    if (action.id == "org.freedesktop.systemd1.manage-units" &&
        action.lookup("unit") == "ollama.service" &&
        subject.user == "$USER") {
        var verbo = action.lookup("verb");
        if (verbo == "start" || verbo == "stop" || verbo == "restart") {
            return polkit.Result.YES;
        }
    }
});
EOF

# ------------------------------------------------------------------ modelos
sudo rm -f "$CONF_DIR/20-sem-internet.conf"   # libera a internet só para baixar
sudo systemctl daemon-reload
sudo systemctl disable ollama >/dev/null 2>&1 || true   # não liga sozinho com o computador
sudo systemctl restart ollama
esperar_ollama || { echo "O Ollama não respondeu. Veja: systemctl status ollama"; exit 1; }

if (( vram >= 7000 && ram >= 16 )); then rec=3
elif (( ram >= 8 )); then rec=1
else rec=2; fi
echo
echo "    Modelos (todos conversam, usam ferramentas e enxergam imagens):"
echo "    [1] qwen3.5:4b  equilibrado: bom em quase tudo$( [[ $rec == 1 ]] && echo '  ← recomendado' )"
echo "    [2] qwen3.5:2b  mais rápido e leve, mas erra mais$( [[ $rec == 2 ]] && echo '  ← recomendado' )"
echo "    [3] qwen3.5:9b  mais esperto, mas pesado: placa de vídeo com 8 GB$( [[ $rec == 3 ]] && echo '  ← recomendado' )"
echo "    [0] nenhum agora"
escolha="$rec"
if [[ $SIM != 1 ]]; then
    read -r -p "    Quais baixar? (ex: 1 2) [$rec]: " escolha </dev/tty || true
    escolha="${escolha:-$rec}"
fi
padrao=""
for n in $escolha; do
    case "$n" in
        1) modelo="qwen3.5:4b" ;;
        2) modelo="qwen3.5:2b" ;;
        3) modelo="qwen3.5:9b" ;;
        0) continue ;;
        *) echo "    Opção $n ignorada"; continue ;;
    esac
    echo "    Baixando $modelo..."
    if ollama pull "$modelo"; then
        padrao="${padrao:-$modelo}"
    else
        aviso "não consegui baixar $modelo"
    fi
done
if [[ -n "$padrao" ]]; then
    gravar_config MODELO "$padrao"
    echo "    Modelo do Lumero: $padrao"
fi

# ------------------------------------------------------------------ sem internet
echo
echo "    O Ollama não precisa de internet para conversar. A pesquisa na internet do Lumero"
echo "    continua funcionando mesmo com o Ollama bloqueado (quem pesquisa é o Lumero)."
if pergunta "    Bloquear o acesso do Ollama à internet? [S/n]" s; then
    sudo tee "$CONF_DIR/20-sem-internet.conf" >/dev/null <<'EOF'
# Criado pelo instalador do Lumero: o Ollama só fala com este computador
[Service]
IPAddressDeny=any
IPAddressAllow=localhost
EOF
    echo "    Bloqueado. Para baixar outro modelo depois: lumero-baixar-modelo NOME"
fi

# comando para baixar modelos depois (libera a internet só durante o download)
sudo tee /usr/local/bin/lumero-baixar-modelo >/dev/null <<'EOF'
#!/usr/bin/env bash
# Baixa um modelo novo para o Lumero, liberando a internet do Ollama só durante o download.
[[ -z "${1:-}" ]] && { echo "Uso: lumero-baixar-modelo NOME   (ex: lumero-baixar-modelo qwen3.5:2b)"; exit 1; }
BLOQ=/etc/systemd/system/ollama.service.d/20-sem-internet.conf
tinha=0
if [[ -f "$BLOQ" ]]; then sudo mv "$BLOQ" "$BLOQ.pausado"; tinha=1; fi
sudo systemctl daemon-reload
systemctl restart ollama
for _ in $(seq 1 60); do curl -fs http://127.0.0.1:11434/api/version >/dev/null && break; sleep 0.5; done
ollama pull "$1"; rc=$?
if [[ $tinha == 1 ]]; then sudo mv "$BLOQ.pausado" "$BLOQ"; fi
sudo systemctl daemon-reload
systemctl stop ollama
exit $rc
EOF
sudo chmod 755 /usr/local/bin/lumero-baixar-modelo
rm -f "$HOME/.local/bin/ia-baixar-modelo"

sudo systemctl daemon-reload
sudo systemctl stop ollama   # o Lumero liga quando precisar
echo "    Ollama configurado."
