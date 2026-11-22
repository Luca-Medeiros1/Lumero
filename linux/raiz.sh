#!/usr/bin/env bash
# =============================================================================
#  Parte do instalador do Lumero que precisa de administrador (Linux).
#  Roda uma vez só, sem perguntas: o instalador com janela chama com o pkexec
#  (uma janela de senha) e o de terminal chama com o sudo.
#
#  Opções:
#    --usuario NOME     dono da instalação (obrigatório)
#    --pacotes 0|1      instala os programas do sistema (python, bubblewrap, ffmpeg...)
#    --voz 0|1          também os programas da voz (espeak-ng, portaudio)
#    --ollama 0|1       instala e configura o Ollama
#    --so-cpu 0|1       o Ollama não usa a placa de vídeo (nem CUDA nem Vulkan)
#    --eco 0|1          modo econômico: limita a CPU e desliga o turbo enquanto a IA roda
#    --bloquear 0|1     o Ollama fica sem acesso à internet (só fala com este computador)
#    --modelos "a b"    modelos para baixar
#
#  Linhas que começam com ## são para o instalador com janela (passo atual etc.).
# =============================================================================
set -uo pipefail

USUARIO=""; PACOTES_SIM=1; VOZ=0; OLLAMA_SIM=1; SO_CPU=0; ECO=0; BLOQUEAR=0; MODELOS=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --usuario) USUARIO="$2"; shift 2 ;;
        --pacotes) PACOTES_SIM="$2"; shift 2 ;;
        --voz) VOZ="$2"; shift 2 ;;
        --ollama) OLLAMA_SIM="$2"; shift 2 ;;
        --so-cpu) SO_CPU="$2"; shift 2 ;;
        --eco) ECO="$2"; shift 2 ;;
        --bloquear) BLOQUEAR="$2"; shift 2 ;;
        --modelos) MODELOS="$2"; shift 2 ;;
        *) echo "Opção desconhecida: $1"; exit 2 ;;
    esac
done
[[ $EUID -eq 0 ]] || { echo "##ERRO Esta parte precisa de administrador."; exit 1; }
id "$USUARIO" >/dev/null 2>&1 && [[ "$USUARIO" != root ]] || { echo "##ERRO Usuário inválido: $USUARIO"; exit 2; }
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH"

aviso() { echo "    ⚠️  $*"; }
CONF_DIR="/etc/systemd/system/ollama.service.d"
API="http://127.0.0.1:11434"

if   command -v dnf    >/dev/null; then GER=dnf
elif command -v apt-get >/dev/null; then GER=apt
elif command -v pacman >/dev/null; then GER=pacman
elif command -v zypper >/dev/null; then GER=zypper
else GER=""; fi

instalar_pacotes() {
    case "$GER" in
        dnf)    dnf install -y --skip-unavailable "$@" 2>/dev/null || dnf install -y "$@" ;;
        apt)    DEBIAN_FRONTEND=noninteractive apt-get install -y "$@" ;;
        pacman) pacman -S --needed --noconfirm "$@" ;;
        zypper) zypper --non-interactive install --no-recommends "$@" ;;
        *)      return 1 ;;
    esac
}

# ----------------------------------------------------------------------------- pacotes
if [[ $PACOTES_SIM == 1 ]]; then
    echo "##PASSO pacotes"
    echo "Instalando os programas do sistema ($GER)..."
    case "$GER" in
        dnf)    PACOTES=(python3 python3-pip bubblewrap polkit curl zstd wl-clipboard xclip poppler-utils
                         ffmpeg-free 7zip git python3-gobject libnotify webkit2gtk4.1) ;;
        apt)    PACOTES=(python3 python3-venv python3-pip bubblewrap pkexec curl zstd wl-clipboard xclip
                         poppler-utils ffmpeg 7zip git python3-gi libnotify-bin gir1.2-webkit2-4.1) ;;
        pacman) PACOTES=(python python-pip bubblewrap polkit curl zstd wl-clipboard xclip poppler
                         ffmpeg 7zip git python-gobject libnotify webkit2gtk-4.1) ;;
        zypper) PACOTES=(python3 python3-pip bubblewrap polkit curl zstd wl-clipboard xclip poppler-tools
                         ffmpeg 7zip git python3-gobject libnotify-tools typelib-1_0-WebKit2-4_1) ;;
        *)      PACOTES=() ; aviso "não reconheci o gerenciador de pacotes; pulei esta parte" ;;
    esac
    if [[ $VOZ == 1 ]]; then
        case "$GER" in
            apt) PACOTES+=(espeak-ng libportaudio2) ;;
            dnf|pacman|zypper) PACOTES+=(espeak-ng portaudio) ;;
        esac
    fi
    [[ $GER == apt ]] && apt-get update -qq
    if [[ ${#PACOTES[@]} -gt 0 ]] && ! instalar_pacotes "${PACOTES[@]}" >/dev/null 2>&1; then
        # algum nome não existe nesta versão: instala um por um e segue com o que der
        for p in "${PACOTES[@]}"; do
            echo "  $p"
            instalar_pacotes "$p" >/dev/null 2>&1 || { [[ $p == 7zip ]] && instalar_pacotes p7zip-full >/dev/null 2>&1; } \
                || aviso "não consegui instalar $p (o Lumero funciona sem ele, com menos recursos)"
        done
    fi
    echo "Programas do sistema prontos."
fi

# ----------------------------------------------------------------------------- Ollama
if [[ $OLLAMA_SIM == 1 ]]; then
    echo "##PASSO ollama"
    if ! command -v ollama >/dev/null; then
        echo "Baixando o Ollama do site oficial (ollama.com)..."
        curl -fsSL https://ollama.com/install.sh | sh || { echo "##ERRO Não consegui instalar o Ollama."; exit 3; }
    else
        echo "Ollama já instalado: $(ollama --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)"
    fi
    if ! systemctl cat ollama.service >/dev/null 2>&1; then
        OLLAMA_BIN="$(command -v ollama)"
        id ollama >/dev/null 2>&1 || useradd -r -s /bin/false -U -m -d /usr/share/ollama ollama
        cat > /etc/systemd/system/ollama.service <<EOF
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

    nucleos=$(nproc); cota=$(( nucleos * 3 / 8 )); (( cota < 1 )) && cota=1
    mkdir -p "$CONF_DIR"
    rm -f "$CONF_DIR/10-economico.conf"     # versão antiga (assistente-ia)
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
        if [[ $SO_CPU == 1 ]]; then
            echo "# só o processador: a placa de vídeo não é usada (nem pelo CUDA nem pelo Vulkan)"
            echo 'Environment="CUDA_VISIBLE_DEVICES=-1"'
            echo 'Environment="OLLAMA_VULKAN=0"'
            echo 'Environment="GGML_VK_VISIBLE_DEVICES=-1"'
        fi
        if [[ $ECO == 1 ]]; then
            echo "# modo econômico: limita a CPU e desliga o turbo enquanto o Ollama estiver ligado"
            echo "CPUQuota=$(( cota * 100 ))%"
            echo "ExecStartPre=+/bin/sh -c 'echo 1 > /sys/devices/system/cpu/intel_pstate/no_turbo 2>/dev/null; echo 0 > /sys/devices/system/cpu/cpufreq/boost 2>/dev/null; true'"
            echo "ExecStopPost=+/bin/sh -c 'echo 0 > /sys/devices/system/cpu/intel_pstate/no_turbo 2>/dev/null; echo 1 > /sys/devices/system/cpu/cpufreq/boost 2>/dev/null; true'"
        fi
    } > "$CONF_DIR/10-lumero.conf"
    echo "Configuração: $([[ $SO_CPU == 1 ]] && echo 'só o processador' || echo 'placa de vídeo quando der')$([[ $ECO == 1 ]] && echo ', modo econômico')."

    # o usuário (e o Lumero) ligam e desligam o Ollama sem digitar senha
    rm -f /etc/polkit-1/rules.d/49-assistente-ollama.rules
    mkdir -p /etc/polkit-1/rules.d
    cat > /etc/polkit-1/rules.d/49-lumero-ollama.rules <<EOF
// Criado pelo instalador do Lumero: o usuário $USUARIO pode ligar/desligar o Ollama sem senha
polkit.addRule(function(action, subject) {
    if (action.id == "org.freedesktop.systemd1.manage-units" &&
        action.lookup("unit") == "ollama.service" &&
        subject.user == "$USUARIO") {
        var verbo = action.lookup("verb");
        if (verbo == "start" || verbo == "stop" || verbo == "restart") {
            return polkit.Result.YES;
        }
    }
});
EOF

    # comando para baixar modelos depois (libera a internet só durante o download)
    cat > /usr/local/bin/lumero-baixar-modelo <<'EOF'
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
    chmod 755 /usr/local/bin/lumero-baixar-modelo
    rm -f "$(getent passwd "$USUARIO" | cut -d: -f6)/.local/bin/ia-baixar-modelo"

    # ------------------------------------------------------------------------- modelos
    echo "##PASSO modelos"
    rm -f "$CONF_DIR/20-sem-internet.conf"   # libera a internet só para baixar
    systemctl daemon-reload
    systemctl disable ollama >/dev/null 2>&1 || true   # não liga sozinho com o computador
    systemctl restart ollama
    for _ in $(seq 1 60); do curl -fs "$API/api/version" >/dev/null 2>&1 && break; sleep 0.5; done
    if ! curl -fs "$API/api/version" >/dev/null 2>&1; then
        echo "##ERRO O Ollama não respondeu. Veja: systemctl status ollama"
        exit 4
    fi
    falhas=0
    for modelo in $MODELOS; do
        echo "##MODELO $modelo"
        echo "Baixando $modelo..."
        if ! ollama pull "$modelo" 2>&1; then
            aviso "não consegui baixar $modelo"
            falhas=$((falhas + 1))
        fi
    done
    [[ -z "$MODELOS" ]] && echo "Nenhum modelo novo para baixar."

    # ------------------------------------------------------------------------- segurança
    echo "##PASSO seguranca"
    if [[ $BLOQUEAR == 1 ]]; then
        cat > "$CONF_DIR/20-sem-internet.conf" <<'EOF'
# Criado pelo instalador do Lumero: o Ollama só fala com este computador
[Service]
IPAddressDeny=any
IPAddressAllow=localhost
EOF
        echo "Internet do Ollama bloqueada (para baixar outro modelo: lumero-baixar-modelo NOME)."
    fi
    systemctl daemon-reload
    systemctl stop ollama   # o Lumero liga quando precisar
else
    echo "##PASSO seguranca"
fi

# ----------------------------------------------------------------------------- sandbox
# os comandos da IA rodam no bubblewrap; o AppArmor do Ubuntu 24.04+ bloqueia por padrão
if command -v bwrap >/dev/null; then
    testar() { runuser -u "$USUARIO" -- bwrap --ro-bind / / --dev /dev --proc /proc --unshare-net true 2>/dev/null; }
    if testar; then
        echo "A proteção dos comandos (sandbox) funciona."
    elif [[ -d /etc/apparmor.d ]] && command -v apparmor_parser >/dev/null; then
        echo "Liberando o bubblewrap no AppArmor para a sandbox funcionar..."
        cat > /etc/apparmor.d/lumero-bwrap <<'EOF'
# Criado pelo instalador do Lumero: deixa o bubblewrap criar a sandbox dos comandos
abi <abi/4.0>,
include <tunables/global>

profile lumero-bwrap /usr/bin/bwrap flags=(unconfined) {
  userns,
  include if exists <local/lumero-bwrap>
}
EOF
        apparmor_parser -r /etc/apparmor.d/lumero-bwrap && testar \
            && echo "Pronto, a sandbox funciona." \
            || aviso "a sandbox não funcionou: a IA não vai conseguir rodar comandos de terminal."
    else
        aviso "a sandbox não funcionou: a IA não vai conseguir rodar comandos de terminal."
    fi
else
    aviso "o bubblewrap não está instalado: a IA não vai conseguir rodar comandos de terminal."
fi
echo "##FIM"
exit 0
