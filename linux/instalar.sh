#!/usr/bin/env bash
# =============================================================================
#  Instalador do Lumero para Linux
#  Fedora · Ubuntu/Debian/Mint/Pop!_OS · Arch/Manjaro/EndeavourOS · openSUSE
#
#  Uso (dentro da pasta do Lumero):   bash linux/instalar.sh
#  Abre o instalador com janela. Para instalar pelo terminal: bash linux/instalar.sh --terminal
#
#  Opções do modo terminal:
#     --sim          responde "sim" para tudo (instala com as escolhas recomendadas)
#     --voz          também instala a voz (/falar e /ouvir)
#     --sem-ollama   não mexe no Ollama (use se ele já estiver configurado)
# =============================================================================
set -euo pipefail

RAIZ="$(cd "$(dirname "$(realpath "$0")")/.." && pwd)"

TERMINAL=0; SIM=0; VOZ=""; OLLAMA_SIM=1
for arg in "$@"; do
    case "$arg" in
        --terminal) TERMINAL=1 ;;
        --sim) SIM=1; TERMINAL=1 ;;
        --voz) VOZ=1 ;;
        --sem-voz) VOZ=0 ;;
        --sem-ollama) OLLAMA_SIM=0 ;;
        *) echo "Opção desconhecida: $arg"; exit 1 ;;
    esac
done

[[ $EUID -eq 0 ]] && { echo "Rode como o seu usuário normal (sem sudo). O instalador pede a senha quando precisar."; exit 1; }
for arq in lumero.py lumero_gui.py lumero_gui.html assets/lumero.svg instalador/hardware.py \
           linux/raiz.sh linux/usuario.sh; do
    [[ -f "$RAIZ/$arq" ]] || { echo "Falta o arquivo $arq. Extraia o zip inteiro e rode de novo."; exit 1; }
done

# ----------------------------------------------------------------------------- com janela
if [[ $TERMINAL == 0 && ( -n "${DISPLAY:-}" || -n "${WAYLAND_DISPLAY:-}" ) ]] && command -v python3 >/dev/null; then
    echo "Abrindo o instalador do Lumero..."
    exec python3 "$RAIZ/instalador/instalador.py"
fi

# ----------------------------------------------------------------------------- no terminal
pergunta() {  # pergunta "texto" padrão(s/n) -> 0 = sim
    local resp padrao="$2"
    if [[ $SIM == 1 ]]; then [[ "$padrao" == s ]]; return; fi
    read -r -p "$1 " resp </dev/tty || resp=""
    resp="${resp:-$padrao}"
    [[ "${resp,,}" == s* || "${resp,,}" == y* ]]
}
passo() { printf '\n\033[1;33m==> %s\033[0m\n' "$*"; }
command -v python3 >/dev/null || { echo "Instale o python3 e rode de novo."; exit 1; }

NOME="$(python3 "$RAIZ/instalador/hardware.py" --nome 2>/dev/null)"
if [[ $SIM != 1 ]]; then
    echo
    read -r -p "Como você quer que o Lumero te chame? [${NOME:-sem nome}]: " resp </dev/tty || resp=""
    [[ -n "$resp" ]] && NOME="$resp"
fi

passo "1/4 Analisando o computador"
ANALISE="$(python3 "$RAIZ/instalador/hardware.py" --json)"
campo() { python3 -c "import json,sys; d=json.loads(sys.argv[1]); print($2)" "$ANALISE"; }
python3 "$RAIZ/instalador/hardware.py" | sed -n '1,/^$/p'
python3 - "$ANALISE" <<'EOF'
import json, sys
d = json.loads(sys.argv[1])
print("    " + d["aviso"])
EOF

SO_CPU=0; ECO=0; BLOQUEAR=1; MODELOS=""
if [[ $OLLAMA_SIM == 1 ]]; then
    if [[ "$(campo 'd["pode_forcar_cpu"]')" == True ]]; then
        if [[ "$(campo 'd["recomenda_so_cpu"]')" == True ]]; then
            pergunta "    Usar só o processador (recomendado para esta placa)? [S/n]" s && SO_CPU=1
        else
            pergunta "    Usar só o processador, sem a placa de vídeo? [s/N]" n && SO_CPU=1
        fi
    fi
    if [[ "$(campo 'd["bateria"]')" == True ]]; then
        echo
        echo "    Modo econômico: limita o processador e desliga o turbo enquanto a IA roda."
        echo "    Fica mais lento, mas esquenta menos e evita desligamentos com bateria fraca."
        pergunta "    Ligar o modo econômico? [S/n]" s && ECO=1
    fi

    passo "2/4 Modelos de IA"
    ANALISE="$(python3 "$RAIZ/instalador/hardware.py" --json $([[ $SO_CPU == 1 ]] && echo --so-cpu))"
    python3 "$RAIZ/instalador/hardware.py" $([[ $SO_CPU == 1 ]] && echo --so-cpu) | sed -n '/^    \[1\]/,$p'
    REC="$(campo '[i for i, m in enumerate(d["modelos"], 1) if m["recomendado"]][0]')"
    escolha="$REC"
    if [[ $SIM != 1 ]]; then
        read -r -p "    Quais baixar? (números separados por espaço, 0 = nenhum) [$REC]: " escolha </dev/tty || true
        escolha="${escolha:-$REC}"
    fi
    for n in $escolha; do
        [[ "$n" =~ ^[0-9]+$ ]] && (( n >= 1 )) || continue
        nome="$(campo "d['modelos'][$n - 1]['nome'] if $n <= len(d['modelos']) else ''")"
        [[ -n "$nome" ]] && MODELOS="$MODELOS $nome"
    done
    echo
    echo "    O Ollama não precisa de internet para conversar. A pesquisa do Lumero continua"
    echo "    funcionando com ele bloqueado (quem pesquisa é o Lumero)."
    pergunta "    Bloquear o acesso do Ollama à internet? [S/n]" s || BLOQUEAR=0
fi
if [[ -z "$VOZ" ]]; then
    pergunta "    Instalar a voz? (/falar com o microfone e /ouvir as respostas; ~300 MB) [s/N]" n && VOZ=1 || VOZ=0
fi

passo "3/4 Programas do sistema e Ollama (vai pedir sua senha)"
sudo bash "$RAIZ/linux/raiz.sh" --usuario "$USER" --pacotes 1 --voz "$VOZ" --ollama "$OLLAMA_SIM" \
    --so-cpu "$SO_CPU" --eco "$ECO" --bloquear "$BLOQUEAR" --modelos "${MODELOS# }" | grep -v '^##'

passo "4/4 Lumero"
PRIMEIRO="$(echo $MODELOS | awk '{print $1}')"
bash "$RAIZ/linux/usuario.sh" --modelo "$PRIMEIRO" --voz "$VOZ" | grep -v '^##'
[[ -n "$NOME" ]] && python3 "$RAIZ/instalador/hardware.py" --gravar-nome "$NOME" >/dev/null
if [[ -n "$PRIMEIRO" ]]; then
    CTX="$(python3 "$RAIZ/instalador/hardware.py" --gravar-contexto "$PRIMEIRO" $([[ $SO_CPU == 1 ]] && echo --so-cpu))"
    echo "    Contexto da conversa: $((CTX / 1024))K tokens (mude no Lumero com /contexto)"
fi

echo
printf '\033[1;32m✓ Lumero instalado%s!\033[0m\n' "${NOME:+, $NOME}"
echo "  • Procure \"Lumero\" no menu de aplicativos ou aperte Ctrl+Alt+A (GNOME): abre a janela de chat."
echo "  • Prefere o terminal? Digite  lumero  (num terminal novo) ou clique com o botão"
echo "    direito no ícone do Lumero → Abrir no terminal."
echo "  • O Ollama liga quando o Lumero abre e desliga quando você sai."
echo "  • Desinstalar: bash linux/desinstalar.sh"
