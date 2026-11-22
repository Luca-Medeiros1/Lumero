#!/usr/bin/env bash
# =============================================================================
#  Instala e configura o Ollama para o Lumero (Linux), no terminal.
#  Usado pelos pacotes .deb/.rpm/Arch na primeira vez que o Lumero abre sem janela.
#  (O instalador com janela faz o mesmo: python3 instalador/instalador.py)
# =============================================================================
set -euo pipefail
AQUI="$(cd "$(dirname "$(realpath "$0")")" && pwd)"
HW="$AQUI/../instalador/hardware.py"
[[ -f "$HW" ]] || HW="$AQUI/instalador/hardware.py"
DADOS="${XDG_DATA_HOME:-$HOME/.local/share}/lumero"

pergunta() {
    local resp padrao="$2"
    read -r -p "$1 " resp </dev/tty || resp=""
    resp="${resp:-$padrao}"
    [[ "${resp,,}" == s* || "${resp,,}" == y* ]]
}
[[ $EUID -eq 0 ]] && { echo "Rode como o seu usuário normal (sem sudo)."; exit 1; }

NOME="$(python3 "$HW" --nome 2>/dev/null)"
read -r -p "Como você quer que o Lumero te chame? [${NOME:-sem nome}]: " resp </dev/tty || resp=""
[[ -n "$resp" ]] && NOME="$resp"
[[ -n "$NOME" ]] && python3 "$HW" --gravar-nome "$NOME" >/dev/null

echo "==> Analisando o computador"
ANALISE="$(python3 "$HW" --json)"
campo() { python3 -c "import json,sys; d=json.loads(sys.argv[1]); print($2)" "$ANALISE"; }
python3 "$HW" | sed -n '1,/^$/p'
echo "    $(campo 'd["aviso"]')"

SO_CPU=0; ECO=0; BLOQUEAR=1; MODELOS=""
if [[ "$(campo 'd["pode_forcar_cpu"]')" == True ]]; then
    if [[ "$(campo 'd["recomenda_so_cpu"]')" == True ]]; then
        pergunta "    Usar só o processador (recomendado para esta placa)? [S/n]" s && SO_CPU=1
    else
        pergunta "    Usar só o processador, sem a placa de vídeo? [s/N]" n && SO_CPU=1
    fi
fi
if [[ "$(campo 'd["bateria"]')" == True ]]; then
    pergunta "    Ligar o modo econômico (esquenta menos, mais lento)? [S/n]" s && ECO=1
fi

echo
echo "==> Modelos de IA"
ANALISE="$(python3 "$HW" --json $([[ $SO_CPU == 1 ]] && echo --so-cpu))"
python3 "$HW" $([[ $SO_CPU == 1 ]] && echo --so-cpu) | sed -n '/^    \[1\]/,$p'
REC="$(campo '[i for i, m in enumerate(d["modelos"], 1) if m["recomendado"]][0]')"
read -r -p "    Quais baixar? (números separados por espaço, 0 = nenhum) [$REC]: " escolha </dev/tty || true
for n in ${escolha:-$REC}; do
    [[ "$n" =~ ^[0-9]+$ ]] && (( n >= 1 )) || continue
    nome="$(campo "d['modelos'][$n - 1]['nome'] if $n <= len(d['modelos']) else ''")"
    [[ -n "$nome" ]] && MODELOS="$MODELOS $nome"
done
pergunta "    Bloquear o acesso do Ollama à internet? (a pesquisa do Lumero continua funcionando) [S/n]" s || BLOQUEAR=0

echo
echo "==> Instalando (vai pedir sua senha)"
sudo bash "$AQUI/raiz.sh" --usuario "$USER" --pacotes 0 --ollama 1 --so-cpu "$SO_CPU" --eco "$ECO" \
    --bloquear "$BLOQUEAR" --modelos "${MODELOS# }" | grep -v '^##'

PRIMEIRO="$(echo $MODELOS | awk '{print $1}')"
if [[ -n "$PRIMEIRO" ]]; then
    mkdir -p "$DADOS"
    python3 - "$DADOS/config.json" "$PRIMEIRO" <<'EOF'
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
    echo "    Modelo do Lumero: $PRIMEIRO"
fi
echo "    Ollama configurado."
