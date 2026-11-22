#!/usr/bin/env python3
"""
Lumero com janela: a mesma IA do lumero.py, numa interface de chat.

Uso:   lumero-gui            (ou: python3 lumero_gui.py)
       python3 lumero_gui.py --navegador   abre no navegador em vez da janela própria

Como funciona: um servidor só deste computador (127.0.0.1, porta aleatória, com uma
senha de sessão) serve a página do chat (lumero_gui.html). A janela é do pywebview
quando ele está instalado; se não estiver, abre o Edge/Chrome no modo aplicativo ou o
navegador padrão. Ferramentas, memória, segurança e configurações são as do lumero.py.
"""
import base64
import datetime
import http.server
import io
import json
import os
import queue
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser

PASTA_APP = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, PASTA_APP)
ARQ_PAGINA = os.path.join(PASTA_APP, "lumero_gui.html")
ANSI = re.compile(r"\033\[[0-9;?]*[A-Za-z]|\033\][^\007]*\007")


# ============================================================================
# Eventos para a página (Server-Sent Events)
# ============================================================================
OUVINTES = []
_TRAVA_OUVINTES = threading.Lock()
SILENCIAR = threading.Event()  # esconde a prévia que algumas ferramentas imprimem


def evento(tipo, **dados):
    mensagem = json.dumps({"tipo": tipo, **dados}, ensure_ascii=False)
    with _TRAVA_OUVINTES:
        for fila in OUVINTES:
            fila.put(mensagem)


class SaidaParaJanela(io.TextIOBase):
    """O que as ferramentas escreveriam no terminal vira linhas cinza na conversa."""

    def __init__(self, arquivo_log):
        super().__init__()
        self.buffer_linha = ""
        self.log = arquivo_log

    def write(self, texto):
        texto = ANSI.sub("", str(texto))
        if self.log:
            try:
                self.log.write(texto)
                self.log.flush()
            except (OSError, ValueError):
                pass
        self.buffer_linha += texto
        partes = re.split(r"[\r\n]", self.buffer_linha)
        self.buffer_linha = partes.pop()
        for linha in partes:
            linha = linha.strip().lstrip("⎿│").strip()
            if linha and not SILENCIAR.is_set():
                evento("log", texto=linha[:300])
        return len(texto)

    def flush(self):
        pass

    def isatty(self):
        return False

    @property
    def encoding(self):
        return "utf-8"


def _abrir_log():
    try:
        import lumero as _l  # só para descobrir a pasta de dados
        pasta = _l.PASTA_DADOS
    except Exception:
        pasta = PASTA_APP
    try:
        os.makedirs(pasta, exist_ok=True)
        return open(os.path.join(pasta, "gui.log"), "a", encoding="utf-8")
    except OSError:
        return None


# sem terminal (pythonw no Windows, app no Mac) o stdout nem existe: nada pode ir para lá
sys.stdout = sys.stderr = SaidaParaJanela(None)
import lumero as L  # noqa: E402  (depois de trocar o stdout)

_LOG = _abrir_log()
sys.stdout = sys.stderr = SaidaParaJanela(_LOG)


# ============================================================================
# Pedaços do lumero.py adaptados para a janela
# ============================================================================
class SpinnerJanela:
    """Substitui o "Pensando…" girando do terminal por uma linha de status na janela."""

    def __init__(self, texto=None, pensando=True):
        self.__dict__["_texto"] = texto or ("Pensando" if pensando else "Respondendo")
        self.__dict__["extra"] = ""
        self.__dict__["ativo"] = False

    def __setattr__(self, nome, valor):
        if nome == "texto":
            self.__dict__["_texto"] = valor
            if self.ativo:
                evento("status", texto=valor)
        else:
            self.__dict__[nome] = valor

    @property
    def texto(self):
        return self._texto

    def iniciar(self):
        self.ativo = True
        evento("status", texto=self._texto)
        return self

    def parar(self):
        if self.ativo:
            self.ativo = False
            evento("status", texto="")


def perguntar_na_janela(texto):
    """Os poucos lugares do lumero.py que perguntam algo no terminal viram um cartão."""
    pergunta = ANSI.sub("", str(texto)).strip()
    ok = pedir_confirmacao("Confirmação", pergunta, perigo=False)
    return "sim" if ok else ""


L.Spinner = SpinnerJanela
L.perguntar = perguntar_na_janela

PARAR = threading.Event()
ESTADO = {"ocupado": False, "resposta": None, "ultimo_sinal": 0.0, "teve_sinal": False,
          "ollama_erro": None, "token": secrets.token_urlsafe(24), "porta": 0}
CONFIRMACOES = {}  # id -> {"evento": Event, "resposta": bool}
PASTA_CONVERSAS_GUI = os.path.join(L.PASTA_DADOS, "conversas-gui")
PASTA_ANEXOS = os.path.join(L.PASTA_DADOS, "anexos")
ARQ_INSTANCIA = os.path.join(L.PASTA_DADOS, "gui.json")
MSG_FIM_RESUMO = "Entendido, continuo a partir do resumo."


def gravar_config(**valores):
    """Grava opções no config.json (o mesmo que o terminal usa)."""
    try:
        with open(L.ARQ_CONFIG, encoding="utf-8") as f:
            dados = json.load(f)
    except (OSError, ValueError):
        dados = {}
    dados.update(valores)
    os.makedirs(L.PASTA_DADOS, exist_ok=True)
    with open(L.ARQ_CONFIG, "w", encoding="utf-8") as f:
        json.dump(dados, f, indent=2, ensure_ascii=False)


def nome_amigavel(nome):
    return nome.replace("_", " ").capitalize()


def detalhe_da_chamada(args):
    if len(args) == 1:
        detalhe = str(next(iter(args.values())))
    else:
        detalhe = ", ".join(f"{k}: {v}" for k, v in args.items())
    detalhe = detalhe.replace("\n", " ⏎ ")
    return detalhe[:160] + ("…" if len(detalhe) > 160 else "")


# ============================================================================
# Conversas (cada uma num arquivo em conversas-gui/)
# ============================================================================
class Conversa:
    def __init__(self, ident=None, titulo="Nova conversa", mensagens=None, criado=None):
        self.id = ident or datetime.datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        self.titulo = titulo
        self.criado = criado or time.time()
        self.mensagens = [{"role": "system", "content": L.prompt_sistema()}] + (mensagens or [])

    @property
    def arquivo(self):
        return os.path.join(PASTA_CONVERSAS_GUI, self.id + ".json")

    def salvar(self):
        if len(self.mensagens) <= 1:
            return
        os.makedirs(PASTA_CONVERSAS_GUI, exist_ok=True)
        temporario = self.arquivo + ".tmp"
        with open(temporario, "w", encoding="utf-8") as f:
            json.dump({"id": self.id, "titulo": self.titulo, "criado": self.criado,
                       "atualizado": time.time(), "modelo": L.MODELO,
                       "mensagens": self.mensagens[1:]}, f, ensure_ascii=False)
        os.replace(temporario, self.arquivo)

    @classmethod
    def abrir(cls, ident):
        if not re.fullmatch(r"[\w-]+", ident or ""):
            raise ValueError("conversa inválida")
        with open(os.path.join(PASTA_CONVERSAS_GUI, ident + ".json"), encoding="utf-8") as f:
            dados = json.load(f)
        return cls(dados["id"], dados.get("titulo") or "Conversa", dados.get("mensagens", []),
                   dados.get("criado"))

    def exibicao(self):
        """A conversa no formato que a página desenha."""
        blocos = []
        for m in self.mensagens[1:]:
            papel = m.get("role")
            if papel == "user":
                if m.get("content", "").startswith("[Resumo da conversa"):
                    blocos.append({"papel": "aviso", "texto": "A conversa anterior foi resumida "
                                   "para caber na memória do modelo."})
                    continue
                blocos.append({"papel": "usuario", "texto": m.get("_texto", m.get("content", "")),
                               "anexos": m.get("_anexos", [])})
            elif papel == "assistant":
                if m.get("content") == MSG_FIM_RESUMO and not m.get("tool_calls"):
                    continue
                if not blocos or blocos[-1]["papel"] != "lumero":
                    blocos.append({"papel": "lumero", "partes": []})
                partes = blocos[-1]["partes"]
                if m.get("thinking"):
                    partes.append({"tipo": "pensamento", "texto": m["thinking"]})
                for chamada in m.get("tool_calls") or []:
                    funcao = chamada.get("function", {})
                    args = funcao.get("arguments") or {}
                    if isinstance(args, str):
                        try:
                            args = json.loads(args or "{}")
                        except ValueError:
                            args = {}
                    partes.append({"tipo": "ferramenta", "nome": nome_amigavel(funcao.get("name", "?")),
                                   "detalhe": detalhe_da_chamada(args), "resultado": None})
                if m.get("content"):
                    partes.append({"tipo": "texto", "texto": m["content"]})
            elif papel == "tool" and blocos and blocos[-1]["papel"] == "lumero":
                for parte in blocos[-1]["partes"]:
                    if parte["tipo"] == "ferramenta" and parte["resultado"] is None:
                        parte["resultado"] = m.get("content", "")
                        break
        return blocos


def lista_conversas():
    itens = []
    for arq in os.listdir(PASTA_CONVERSAS_GUI) if os.path.isdir(PASTA_CONVERSAS_GUI) else []:
        if not arq.endswith(".json"):
            continue
        try:
            with open(os.path.join(PASTA_CONVERSAS_GUI, arq), encoding="utf-8") as f:
                dados = json.load(f)
            itens.append({"id": dados["id"], "titulo": dados.get("titulo") or "Conversa",
                          "atualizado": dados.get("atualizado", 0)})
        except (OSError, ValueError, KeyError):
            continue
    return sorted(itens, key=lambda i: i["atualizado"], reverse=True)


ATUAL = {"conversa": None}


def conversa_atual():
    if ATUAL["conversa"] is None:
        ATUAL["conversa"] = Conversa()
    return ATUAL["conversa"]


# ============================================================================
# Anexos
# ============================================================================
def _miniatura(dados, tamanho=320):
    try:
        from PIL import Image
        imagem = Image.open(io.BytesIO(dados))
        imagem.thumbnail((tamanho, tamanho))
        saida = io.BytesIO()
        imagem.convert("RGB").save(saida, "JPEG", quality=80)
        return "data:image/jpeg;base64," + base64.b64encode(saida.getvalue()).decode()
    except Exception:
        return None


def _imagem_para_ia(dados):
    """Reduz fotos grandes antes de mandar para o modelo (economiza memória e tempo)."""
    try:
        from PIL import Image
        imagem = Image.open(io.BytesIO(dados))
        imagem.thumbnail((1024, 1024))
        saida = io.BytesIO()
        imagem.convert("RGB").save(saida, "JPEG", quality=85)
        return base64.b64encode(saida.getvalue()).decode()
    except Exception:
        return base64.b64encode(dados).decode()


def preparar_anexos(anexos):
    """Salva os anexos na pasta do Lumero. Devolve (texto extra, imagens base64, exibição)."""
    extra, imagens, exibicao = [], [], []
    if not anexos:
        return "", imagens, exibicao
    os.makedirs(PASTA_ANEXOS, exist_ok=True)
    for anexo in anexos[:8]:
        nome = re.sub(r"[^\w.\- ]", "_", os.path.basename(str(anexo.get("nome") or "arquivo")))[:80]
        try:
            dados = base64.b64decode(anexo.get("dados") or "")
        except ValueError:
            continue
        if len(dados) > 30 * 1024 * 1024:
            extra.append(f"[O arquivo {nome} passou de 30 MB e não foi anexado]")
            continue
        caminho = os.path.join(PASTA_ANEXOS, f"{datetime.datetime.now():%Y%m%d-%H%M%S}-{nome}")
        with open(caminho, "wb") as f:
            f.write(dados)
        imagem = str(anexo.get("tipo", "")).startswith("image/")
        exibicao.append({"nome": nome, "imagem": imagem,
                         "miniatura": _miniatura(dados) if imagem else None})
        if imagem and L.MODELO_VISAO == L.MODELO:
            imagens.append(_imagem_para_ia(dados))
            extra.append(f"[Imagem anexada: {nome}. Ela já está nesta mensagem: responda "
                         "olhando para ela, sem usar descrever_imagem.]")
        elif imagem:
            extra.append(f"[Imagem anexada, salva em {caminho}: use descrever_imagem para ver]")
        else:
            extra.append(f"[Arquivo anexado, salvo em {caminho}: use ler_arquivo para ler]")
    return "\n".join(extra), imagens, exibicao


# ============================================================================
# Confirmações (cartão "Permitir / Negar" na conversa)
# ============================================================================
def pedir_confirmacao(titulo, detalhes, perigo=False, codigo="", aviso=""):
    ident = uuid.uuid4().hex
    pendente = {"evento": threading.Event(), "resposta": False}
    CONFIRMACOES[ident] = pendente
    evento("confirmar", id=ident, titulo=titulo, detalhes=detalhes, codigo=codigo,
           perigo=perigo, aviso=aviso)
    while not pendente["evento"].wait(0.3):
        if PARAR.is_set():
            break
    CONFIRMACOES.pop(ident, None)
    evento("confirmado", id=ident, permitido=pendente["resposta"])
    return pendente["resposta"]


def precisa_confirmar(nome, args, info):
    """Mesma regra do terminal. Devolve None (não pergunta) ou os dados do cartão."""
    if nome == "rodar_comando_admin":
        comando = re.sub(r"(?i)^\s*sudo\s+", "", str(args.get("comando", "")).strip())
        return {"titulo": "Rodar como administrador?", "detalhes": str(args.get("motivo") or ""),
                "codigo": comando, "perigo": True,
                "aviso": "Como administrador, este comando pode alterar todo o sistema. "
                         "Depois vai aparecer a janela de senha do sistema."}
    if nome == "rodar_comando":
        comando = str(args.get("comando", ""))
        pasta = L.caminho_seguro(args.get("pasta") or L.pasta_padrao())  # recusa pastas fora
        if L.COMANDOS_LEITURA_LIVRES and L.somente_leitura(comando):
            return None
        if (L.USAR_LIXEIRA and L.APAGAR_DIRETO.search(comando)) or L.PEDE_ADMIN.search(comando):
            return None  # o rodar_comando recusa sozinho, sem executar nada
        perigoso = any(p in comando.lower() for p in L.PADROES_PERIGOSOS)
        return {"titulo": "Rodar este comando?", "detalhes": "pasta: " + pasta.replace(L.HOME, "~", 1),
                "codigo": comando, "perigo": perigoso,
                "aviso": "Pode apagar ou sobrescrever arquivos!" if perigoso else ""}
    regra = info["confirmar"]
    if nome == "criar_arquivo" and regra(args):
        destino = L.caminho_seguro(args.get("caminho", ""))
        conteudo = str(args.get("conteudo", ""))
        return {"titulo": "Salvar este arquivo?", "codigo": conteudo[:3000] + ("\n…" if len(conteudo) > 3000 else ""),
                "detalhes": destino.replace(L.HOME, "~", 1) + (
                    "\nO arquivo que já existe vai para a lixeira." if os.path.exists(destino) else ""),
                "perigo": False, "aviso": ""}
    if callable(regra) and regra(args) or regra is True:
        return {"titulo": f"Permitir: {nome_amigavel(nome)}?",
                "detalhes": "\n".join(f"{k}: {v}" for k, v in args.items()), "codigo": "",
                "perigo": nome in ("energia", "processos"), "aviso": ""}
    return None


def executar_ferramenta(chamada, ident):
    nome = chamada["function"]["name"]
    args = chamada["function"].get("arguments") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args or "{}")
        except ValueError:
            args = {}
    evento("ferramenta", id=ident, nome=nome_amigavel(nome), detalhe=detalhe_da_chamada(args))
    info = L.FERRAMENTAS.get(nome)
    try:
        if not info:
            resultado = f"Erro: ferramenta desconhecida: {nome}"
        else:
            cartao = precisa_confirmar(nome, args, info)
            if cartao and not pedir_confirmacao(**cartao):
                resultado = "O usuário não permitiu essa ação."
            else:
                if nome == "criar_arquivo":  # o conteúdo já apareceu (ou nem precisa aparecer)
                    SILENCIAR.set()
                try:
                    resultado = str(info["func"](**args))
                finally:
                    SILENCIAR.clear()
    except TypeError as erro:
        resultado = f"Erro: parâmetros errados para {nome}: {erro}"
    except Exception as erro:
        resultado = f"Erro ao executar {nome}: {erro}"
    evento("resultado", id=ident, texto=resultado[:4000],
           erro=bool(re.match(r"^(Erro|Alteração NÃO|O usuário não|Comando NÃO)", resultado)))
    return resultado


# ============================================================================
# Conversa com o Ollama (igual ao terminal, mas mandando os pedaços para a janela)
# ============================================================================
def _para_ollama(mensagens):
    return [{k: v for k, v in m.items() if not k.startswith("_")} for m in mensagens]


def conversar(mensagens, pensar):
    dados = json.dumps({"model": L.MODELO, "messages": _para_ollama(mensagens), "stream": True,
                        "think": pensar, "tools": L.ferramentas_ativas(),
                        "options": {"num_ctx": L.CONTEXTO}}).encode()
    req = urllib.request.Request(L.OLLAMA, data=dados, headers={"Content-Type": "application/json"})
    abridor = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    L.esperar_esfriar()
    conteudo, pensamento, chamadas = "", "", []
    evento("status", texto="Pensando" if pensar else "Respondendo")
    ultima_medida = time.time()
    try:
        with abridor.open(req, timeout=600) as resposta:
            ESTADO["resposta"] = resposta
            for linha in resposta:
                if PARAR.is_set():
                    break
                if not linha.strip():
                    continue
                parte = json.loads(linha)
                if parte.get("error"):
                    raise RuntimeError(parte["error"])
                msg = parte.get("message") or {}
                if time.time() - ultima_medida > 3:
                    ultima_medida = time.time()
                    temp = L.temperatura_cpu()
                    if temp and temp >= L.TEMPERATURA_CRITICA:
                        raise RuntimeError(f"o processador chegou a {temp:.0f}°C, parei a "
                                           "resposta para proteger o computador")
                if msg.get("thinking"):
                    pensamento += msg["thinking"]
                    evento("pensamento", texto=msg["thinking"])
                if msg.get("content"):
                    if not conteudo:
                        evento("status", texto="")
                    conteudo += msg["content"]
                    evento("texto", texto=msg["content"])
                if msg.get("tool_calls"):
                    chamadas.extend(msg["tool_calls"])
                if parte.get("done"):
                    L.USO_CONTEXTO["tokens"] = (parte.get("prompt_eval_count") or 0) + \
                        (parte.get("eval_count") or 0)
                    break
    except (OSError, ValueError, AttributeError) as erro:
        if not PARAR.is_set():
            raise urllib.error.URLError(erro) if not isinstance(erro, urllib.error.URLError) else erro
    finally:
        ESTADO["resposta"] = None
        evento("status", texto="")
    mensagem = {"role": "assistant", "content": conteudo}
    if pensamento:
        mensagem["thinking"] = pensamento
    if chamadas and not PARAR.is_set():
        mensagem["tool_calls"] = chamadas
    return mensagem


def turno(texto, anexos):
    """Uma mensagem do usuário: responde, usa ferramentas e salva a conversa."""
    conversa = conversa_atual()
    mensagens = conversa.mensagens
    PARAR.clear()
    L.parar_fala()
    try:
        mensagens[0]["content"] = L.prompt_sistema()
        if L.USO_CONTEXTO["tokens"] > L.CONTEXTO * 0.7 or len(mensagens) > 60:
            try:
                if L.resumir_conversa(mensagens):
                    L.USO_CONTEXTO["tokens"] = 0
            except Exception:
                mensagens[:] = mensagens[:1] + mensagens[-30:]
                while len(mensagens) > 1 and mensagens[1]["role"] != "user":
                    mensagens.pop(1)
        pensar, texto_ia = L.decidir_pensar(texto)
        for grupo in L.ativar_grupos(texto_ia):
            evento("log", texto=f"ferramentas de {L.NOMES_GRUPOS.get(grupo, grupo)} ligadas")
        extra, imagens, exibicao = preparar_anexos(anexos)
        mensagem = {"role": "user", "content": (texto_ia + ("\n\n" + extra if extra else "")).strip(),
                    "_texto": texto, "_anexos": exibicao}
        if imagens:
            mensagem["images"] = imagens
        mensagens.append(mensagem)
        if conversa.titulo == "Nova conversa":
            conversa.titulo = (texto.strip().splitlines() or ["Conversa"])[0][:60] or "Conversa"
            evento("titulo", id=conversa.id, titulo=conversa.titulo)

        resposta = conversar(mensagens, pensar)
        mensagens.append(resposta)
        rodadas = 0
        while resposta.get("tool_calls") and rodadas < 8 and not PARAR.is_set():
            resultados = []
            for chamada in resposta["tool_calls"]:
                if PARAR.is_set():
                    resultado = "O usuário interrompeu antes desta ação."
                else:
                    resultado = executar_ferramenta(chamada, uuid.uuid4().hex)
                resultados.append(resultado)
                mensagens.append({"role": "tool", "content": resultado,
                                  "tool_name": chamada["function"]["name"]})
            if PARAR.is_set():
                break
            pensar = L.pensar_na_proxima_rodada(pensar, resposta["tool_calls"], resultados)
            resposta = conversar(mensagens, pensar)
            mensagens.append(resposta)
            rodadas += 1
        if PARAR.is_set():
            if not mensagens[-1].get("content"):
                mensagens.append({"role": "assistant", "content": "(resposta interrompida pelo usuário)"})
            evento("aviso", texto="Interrompido.")
        else:
            usadas = []
            for m in reversed(mensagens):
                if m.get("role") == "user":
                    break
                if m.get("role") == "tool" and m.get("tool_name"):
                    usadas.insert(0, m["tool_name"])
            L.preparar_sugestao(resposta.get("content") or "", usadas)
            if L.FALAR_RESPOSTAS["ligado"] and resposta.get("content"):
                L.falar(resposta["content"])
        if L.REINICIAR["pendente"]:
            evento("aviso", texto="O Lumero alterou o próprio código. Feche e abra de novo para aplicar.")
    except urllib.error.URLError:
        evento("erro", texto="Não consegui falar com o Ollama. Tentando ligar de novo…")
        if mensagens and mensagens[-1]["role"] == "user":
            mensagens.pop()
        ESTADO["ollama_erro"] = L.garantir_ollama()
        if not ESTADO["ollama_erro"]:
            evento("aviso", texto="Pronto, pode mandar a mensagem de novo.")
    except RuntimeError as erro:
        evento("erro", texto=f"Erro do Ollama: {erro}")
        if mensagens and mensagens[-1]["role"] == "user":
            mensagens.pop()
    except Exception as erro:  # nunca deixa a janela travada em "ocupado"
        evento("erro", texto=f"Erro inesperado: {erro}")
    finally:
        try:
            conversa.salvar()
        except OSError:
            pass
        ESTADO["ocupado"] = False
        uso = min(100, round(100 * L.USO_CONTEXTO["tokens"] / max(1, L.CONTEXTO)))
        evento("fim", id=conversa.id, titulo=conversa.titulo, contexto=uso,
               proxima=L.CONTEXTO_SUGESTAO["proxima"])



# ============================================================================
# Comandos com / e sugestões na caixa de texto
# ============================================================================
COMANDOS_JANELA = [
    ("/ajuda", "mostra os comandos e atalhos"),
    ("/nova", "começa uma conversa nova"),
    ("/ferramentas", "lista o que a IA consegue fazer"),
    ("/pensar", "raciocínio: auto, sempre ou nunca"),
    ("/pensamento", "mostra o raciocínio da última resposta"),
    ("/modelo", "mostra ou troca o modelo"),
    ("/nome", "mostra ou troca o nome pelo qual o Lumero te chama"),
    ("/estado", "temperatura, bateria, CPU/RAM e uso da IA"),
    ("/extras", "grupos de ferramentas extras"),
    ("/memoria", "o que a IA lembra sobre você"),
    ("/contexto", "mostra ou troca o tamanho da memória da conversa"),
    ("/compactar", "resume a conversa para liberar memória"),
    ("/conversas", "lista as conversas salvas"),
    ("/retomar", "abre uma conversa salva (sem nada: a última)"),
    ("/ouvir", "liga/desliga a leitura das respostas em voz alta"),
    ("/tema", "aparência: automático, claro ou escuro"),
]
APELIDOS = {"/limpar": "/nova", "/clear": "/nova", "/help": "/ajuda", "/memória": "/memoria"}
TEMAS = {"auto": "automático (igual ao sistema)", "claro": "claro", "escuro": "escuro"}
_HISTORICO = {"lista": None}


def ler_config():
    try:
        with open(L.ARQ_CONFIG, encoding="utf-8") as f:
            dados = json.load(f)
        return dados if isinstance(dados, dict) else {}
    except (OSError, ValueError):
        return {}


def tema_escolhido():
    tema = ler_config().get("TEMA", "auto")
    return tema if tema in TEMAS else "auto"


def tema_do_sistema():
    """'claro', 'escuro' ou None (a página usa o que o navegador disser)."""
    try:
        if L.EH_WINDOWS:
            import winreg
            chave = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                   r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            return "claro" if winreg.QueryValueEx(chave, "AppsUseLightTheme")[0] else "escuro"
        if L.EH_MAC:
            r = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"],
                               capture_output=True, text=True, timeout=2)
            return "escuro" if "dark" in r.stdout.lower() else "claro"
        mesa = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
        if shutil.which("gsettings") and any(m in mesa for m in ("gnome", "unity", "cinnamon", "budgie", "pantheon", "mate")):
            r = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                               capture_output=True, text=True, timeout=2)
            if "dark" in r.stdout:
                return "escuro"
            if "light" in r.stdout:
                return "claro"
            r = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"],
                               capture_output=True, text=True, timeout=2)
            if r.returncode == 0 and r.stdout.strip():
                return "escuro" if "dark" in r.stdout.lower() else "claro"
    except Exception:
        pass
    return None


def historico():
    """Mensagens já enviadas, da mais recente para a mais antiga (para as sugestões)."""
    if _HISTORICO["lista"] is None:
        textos = []
        for item in reversed(lista_conversas()[:60]):
            try:
                with open(os.path.join(PASTA_CONVERSAS_GUI, item["id"] + ".json"), encoding="utf-8") as f:
                    for m in json.load(f).get("mensagens", []):
                        if m.get("role") == "user" and m.get("_texto"):
                            textos.append(m["_texto"])
            except (OSError, ValueError):
                continue
        try:  # o que foi digitado no terminal também vale
            with open(os.path.join(L.PASTA_DADOS, "historico-linha"), encoding="utf-8") as f:
                linhas = [ln[1:].rstrip("\n") for ln in f if ln.startswith("+")]
            textos = linhas[-300:] + textos
        except OSError:
            pass
        _HISTORICO["lista"] = []
        for t in reversed(textos):
            lembrar_mensagem(t, no_fim=True)
    return _HISTORICO["lista"]


def lembrar_mensagem(texto, no_fim=False):
    texto = (texto or "").strip()
    if not texto or "\n" in texto or texto.startswith("/") or len(texto) > 200:
        return
    lista = _HISTORICO["lista"] if _HISTORICO["lista"] is not None else historico()
    if texto in lista:
        if no_fim:
            return
        lista.remove(texto)
    if no_fim:
        lista.append(texto)
    else:
        lista.insert(0, texto)
    del lista[500:]


def opcoes_janela(comando):
    if comando == "/tema":
        return list(TEMAS.items())
    if comando == "/retomar":
        return [(c["id"], c["titulo"][:50]) for c in lista_conversas()[:15]]
    if comando == "/modelo":
        return [(m, "instalado") for m in modelos_instalados()]
    if comando in ("/pensar", "/extras", "/contexto"):
        return L.opcoes_do_comando(comando)
    return []


def completar_janela(texto):
    """Itens do menu: {texto, substituir, descricao}."""
    itens = []
    if texto.startswith("/"):
        if " " not in texto:
            itens = [(c, len(texto), d) for c, d in COMANDOS_JANELA if c.startswith(texto.lower())]
        else:
            comando, argumento = texto.split(" ", 1)
            comando = APELIDOS.get(comando.lower(), comando.lower())
            itens = [(o, len(argumento), d) for o, d in opcoes_janela(comando)
                     if L.sem_acento(o).startswith(L.sem_acento(argumento))]
    else:
        try:
            itens = L.completar(texto)
        except Exception:
            itens = []
    return [{"texto": t, "substituir": n, "descricao": d} for t, n, d in itens[:40]]


def sugerir_janela(texto):
    if texto.startswith("/"):
        if " " in texto:
            return ""
        opcoes = completar_janela(texto)
        return opcoes[0]["texto"][len(texto):] if len(opcoes) == 1 else ""
    try:
        return L.sugerir(texto, historico())
    except Exception:
        return ""


AJUDA_JANELA = """**Comandos** (digite `/` para ver o menu):

{comandos}

**Atalhos**

- **Tab** ou **→** aceita a sugestão em cinza; **↑ ↓** escolhem no menu
- **Shift+Enter** pula linha; **Esc** para a resposta
- **Ctrl+Shift+O** abre uma conversa nova
- comece com **!** para forçar a IA a pensar (ex.: `!qual o melhor jeito de...`)
- digite `~/` para completar caminhos de pastas"""


def comando_janela(texto):
    """Roda um comando com /. Devolve o que a página deve mostrar ou fazer."""
    partes = texto.split(maxsplit=1)
    cmd = APELIDOS.get(partes[0].lower(), partes[0].lower())
    arg = partes[1].strip() if len(partes) > 1 else ""
    r = {"comando": True, "texto": ""}
    if cmd == "/ajuda":
        r["texto"] = AJUDA_JANELA.format(comandos="\n".join(f"- `{c}` {d}" for c, d in COMANDOS_JANELA))
    elif cmd == "/nova":
        if ESTADO["ocupado"]:
            raise ValueError("espere a resposta terminar")
        ATUAL["conversa"] = Conversa()
        L.USO_CONTEXTO["tokens"] = 0
        L.GRUPOS_EM_USO.clear()
        r["acao"] = "recarregar"
    elif cmd == "/ferramentas":
        linhas = []
        for nome, info in L.FERRAMENTAS.items():
            desc = info["schema"]["function"]["description"].split(". ")[0]
            grupo = info.get("grupo")
            ligado = not grupo or grupo in L.GRUPOS_EM_USO
            linhas.append(f"- {'●' if ligado else '○'} **{nome}**{f' [{grupo}]' if grupo else ''}: {desc}")
        r["texto"] = "**Ferramentas** (○ = grupo extra, liga sozinho pelo assunto)\n\n" + "\n".join(linhas)
    elif cmd == "/pensar":
        opcoes = {"auto": "auto", "automatico": "auto", "sim": True, "ligado": True, "sempre": True,
                  "nao": False, "desligado": False, "nunca": False}
        if arg:
            L.PENSAR = opcoes.get(L.sem_acento(arg.lower()), L.PENSAR)
        else:
            L.PENSAR = {"auto": True, True: False, False: "auto"}[L.PENSAR]
        gravar_config(PENSAR=L.PENSAR)
        r["texto"] = "Raciocínio: " + {True: "sempre pensa", False: "nunca pensa"}.get(L.PENSAR, "automático") + "."
    elif cmd == "/pensamento":
        p = L.ULTIMO_PENSAMENTO["texto"].strip()
        r["texto"] = ("**Raciocínio da última resposta**\n\n" + p) if p else "Não há raciocínio salvo."
    elif cmd == "/modelo":
        if arg:
            if arg not in modelos_instalados():
                raise ValueError(f"o modelo {arg} não está instalado")
            if L.MODELO_VISAO == L.MODELO:
                L.MODELO_VISAO = arg
            L.MODELO = arg
            gravar_config(MODELO=arg)
            r["texto"] = f"Modelo trocado para **{arg}**."
        else:
            r["texto"] = f"Modelo: **{L.MODELO}**\n\nInstalados: " + (", ".join(f"`{m}`" for m in modelos_instalados()) or "nenhum")
    elif cmd == "/nome":
        if arg:
            L.trocar_nome(arg)
            r["texto"] = f"Certo, vou te chamar de **{L.NOME_USUARIO}**." if L.NOME_USUARIO else "Nome apagado."
        else:
            r["texto"] = (f"Eu te chamo de **{L.NOME_USUARIO}**." if L.NOME_USUARIO else "Ainda não sei o seu nome.") + \
                " Para trocar: `/nome Seu Nome` (ou `/nome apagar`)."
    elif cmd == "/estado":
        r["texto"] = "```\n" + L.estado_do_pc() + "\n```"
    elif cmd == "/extras":
        if arg in ("todos", "tudo"):
            L.GRUPOS_EM_USO.update(L.GATILHOS_GRUPOS)
        elif arg in L.GATILHOS_GRUPOS:
            L.GRUPOS_EM_USO.add(arg)
        elif arg:
            raise ValueError(f"grupo desconhecido: {arg}")
        r["texto"] = "**Grupos extras**\n\n" + "\n".join(
            f"- {'● ligado' if g in L.GRUPOS_EM_USO else '○ desligado'} · **{g}**: {n}"
            for g, n in L.NOMES_GRUPOS.items()) + "\n\nEles ligam sozinhos quando o assunto aparece. Use `/extras nome` ou `/extras todos`."
    elif cmd == "/memoria":
        r["texto"] = L.ver_memoria()
    elif cmd == "/contexto":
        if arg:
            novo, aviso = L.trocar_contexto(arg)
            r["texto"] = f"Contexto: **{L.contexto_legivel(novo)}** ({novo} tokens)." + (f"\n\n⚠️ {aviso}" if aviso else "")
        else:
            uso = L.USO_CONTEXTO["tokens"]
            rec = f" O recomendado para este computador é **{L.contexto_legivel(L.CONTEXTO_RECOMENDADO)}**." if L.CONTEXTO_RECOMENDADO else ""
            r["texto"] = (f"Contexto: {uso} de {L.CONTEXTO} tokens usados ({100 * uso // max(1, L.CONTEXTO)}%). "
                          f"Limite: **{L.contexto_legivel(L.CONTEXTO)}**.{rec} A conversa é resumida sozinha ao passar de 70%.\n\n"
                          "Para mudar: `/contexto 16k`, `/contexto 32k` ou `/contexto recomendado` "
                          "(ou clique no contexto, embaixo da caixa de texto).")
    elif cmd == "/compactar":
        if ESTADO["ocupado"]:
            raise ValueError("espere a resposta terminar")
        conversa = conversa_atual()
        if not L.resumir_conversa(conversa.mensagens):
            r["texto"] = "A conversa ainda é curta, não precisa resumir."
        else:
            L.USO_CONTEXTO["tokens"] = 0
            conversa.salvar()
            r["texto"] = "Conversa resumida."
            r["acao"] = "recarregar"
    elif cmd == "/conversas":
        itens = lista_conversas()[:20]
        r["texto"] = ("**Conversas salvas** (abra com `/retomar` ou pela lista ao lado)\n\n" + "\n".join(
            f"- {c['titulo']}" for c in itens)) if itens else "Nenhuma conversa salva."
    elif cmd == "/retomar":
        if ESTADO["ocupado"]:
            raise ValueError("espere a resposta terminar")
        itens = lista_conversas()
        alvo = next((c for c in itens if c["id"] == arg), None) if arg else (itens[0] if itens else None)
        if not alvo and arg:
            alvo = next((c for c in itens if L.sem_acento(arg.lower()) in L.sem_acento(c["titulo"].lower())), None)
        if not alvo:
            raise ValueError("não achei essa conversa")
        ATUAL["conversa"] = Conversa.abrir(alvo["id"])
        L.USO_CONTEXTO["tokens"] = 0
        r["acao"] = "recarregar"
    elif cmd == "/ouvir":
        L.FALAR_RESPOSTAS["ligado"] = not L.FALAR_RESPOSTAS["ligado"]
        if not L.FALAR_RESPOSTAS["ligado"]:
            L.parar_fala()
        r["texto"] = "Respostas em voz alta: " + ("ligado." if L.FALAR_RESPOSTAS["ligado"] else "desligado.")
    elif cmd == "/tema":
        alvo = L.sem_acento(arg.lower())
        alvo = {"automatico": "auto", "sistema": "auto", "dark": "escuro", "light": "claro"}.get(alvo, alvo)
        if alvo not in TEMAS:
            alvo = {"auto": "claro", "claro": "escuro", "escuro": "auto"}[tema_escolhido()]
        gravar_config(TEMA=alvo)
        r["texto"] = f"Tema: {TEMAS[alvo]}."
    elif cmd in ("/falar", "/sair", "/salvar"):
        r["texto"] = {"/falar": "O microfone ainda não está na janela. Use o Lumero no terminal para falar.",
                      "/sair": "Para sair, é só fechar a janela.",
                      "/salvar": "As conversas da janela são salvas sozinhas."}[cmd]
    else:
        raise ValueError(f"comando desconhecido: {cmd}. Digite /ajuda")
    r["estado"] = estado()
    return r


# ============================================================================
# Servidor HTTP (só 127.0.0.1, com senha de sessão)
# ============================================================================
def modelos_instalados():
    try:
        return sorted(m["name"] for m in L.ollama_api("/api/tags", timeout=5).get("models", []))
    except Exception:
        return []


def estado():
    return {"versao": L.VERSAO, "geracao": L.GERACAO, "sistema": L.NOME_SISTEMA,
            "modelo": L.MODELO, "modelos": modelos_instalados(),
            "pensar": {True: "sempre", False: "nunca"}.get(L.PENSAR, "auto"),
            "falar": L.FALAR_RESPOSTAS["ligado"], "ocupado": ESTADO["ocupado"],
            "ollama_erro": ESTADO["ollama_erro"], "conversa": conversa_atual().id,
            "titulo": conversa_atual().titulo, "so": L.SO,
            "contexto": min(100, round(100 * L.USO_CONTEXTO["tokens"] / max(1, L.CONTEXTO))),
            "tema": tema_escolhido(), "nome": L.NOME_USUARIO,
            "contexto_limite": L.CONTEXTO, "contexto_recomendado": L.CONTEXTO_RECOMENDADO,
            "contexto_opcoes": L.CONTEXTO_OPCOES, "tema_sistema": tema_do_sistema(),
            "proxima": L.CONTEXTO_SUGESTAO["proxima"]}


class Servidor(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False


class Pedido(http.server.BaseHTTPRequestHandler):
    server_version = "Lumero"
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    # ---------------------------------------------------------------- utilidades
    def _host_valido(self):
        porta = ESTADO["porta"]
        return self.headers.get("Host", "") in (f"127.0.0.1:{porta}", f"localhost:{porta}")

    def _token_valido(self):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        recebido = self.headers.get("X-Lumero-Token") or (query.get("t") or [""])[0]
        return secrets.compare_digest(recebido, ESTADO["token"])

    def _responder(self, codigo, corpo, tipo="application/json; charset=utf-8", extra=None):
        dados = corpo if isinstance(corpo, bytes) else json.dumps(corpo, ensure_ascii=False).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(dados)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for chave, valor in (extra or {}).items():
            self.send_header(chave, valor)
        self.end_headers()
        self.wfile.write(dados)

    def _corpo(self):
        tamanho = int(self.headers.get("Content-Length") or 0)
        if tamanho > 250 * 1024 * 1024:
            raise ValueError("pedido grande demais")
        return json.loads(self.rfile.read(tamanho) or b"{}") if tamanho else {}

    # ---------------------------------------------------------------- GET
    def do_GET(self):
        if not self._host_valido():
            return self._responder(403, {"erro": "host inválido"})
        caminho = urllib.parse.urlparse(self.path).path
        if caminho in ("/", "/index.html"):
            try:
                with open(ARQ_PAGINA, "rb") as f:
                    pagina = f.read()
            except OSError:
                return self._responder(500, b"Falta o arquivo lumero_gui.html", "text/plain")
            return self._responder(200, pagina, "text/html; charset=utf-8", {
                "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; "
                                           "style-src 'self' 'unsafe-inline'; "
                                           "script-src 'self' 'unsafe-inline'; "
                                           "connect-src 'self'; frame-ancestors 'none'"})
        if not caminho.startswith("/api/") or not self._token_valido():
            return self._responder(403, {"erro": "sem permissão"})
        ESTADO["ultimo_sinal"], ESTADO["teve_sinal"] = time.time(), True
        if caminho == "/api/eventos":
            return self._eventos()
        if caminho == "/api/estado":
            return self._responder(200, estado())
        if caminho == "/api/completar":
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query, keep_blank_values=True)
            texto = (query.get("texto") or [""])[0][:500]
            return self._responder(200, {"texto": texto, "itens": completar_janela(texto),
                                         "sugestao": sugerir_janela(texto)})
        if caminho == "/api/conversas":
            return self._responder(200, {"conversas": lista_conversas(),
                                         "atual": conversa_atual().id})
        if caminho == "/api/conversa":
            conversa = conversa_atual()
            return self._responder(200, {"id": conversa.id, "titulo": conversa.titulo,
                                         "blocos": conversa.exibicao(),
                                         "ocupado": ESTADO["ocupado"]})
        return self._responder(404, {"erro": "não encontrado"})

    def _eventos(self):
        fila = queue.Queue()
        with _TRAVA_OUVINTES:
            OUVINTES.append(fila)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.wfile.write(b": conectado\n\n")
            self.wfile.flush()
            while True:
                try:
                    mensagem = fila.get(timeout=15)
                    self.wfile.write(b"data: " + mensagem.encode() + b"\n\n")
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    ESTADO["ultimo_sinal"] = time.time()
                self.wfile.flush()
        except (OSError, ValueError):
            pass
        finally:
            with _TRAVA_OUVINTES:
                if fila in OUVINTES:
                    OUVINTES.remove(fila)
            self.close_connection = True

    # ---------------------------------------------------------------- POST
    def do_POST(self):
        if not self._host_valido() or not self._token_valido():
            return self._responder(403, {"erro": "sem permissão"})
        ESTADO["ultimo_sinal"], ESTADO["teve_sinal"] = time.time(), True
        caminho = urllib.parse.urlparse(self.path).path
        try:
            dados = self._corpo()
        except (ValueError, OSError) as erro:
            return self._responder(400, {"erro": str(erro)})
        acoes = {"/api/enviar": self._enviar, "/api/parar": self._parar,
                 "/api/confirmar": self._confirmar, "/api/nova": self._nova,
                 "/api/abrir": self._abrir, "/api/apagar": self._apagar,
                 "/api/renomear": self._renomear, "/api/config": self._config,
                 "/api/link": self._link, "/api/vivo": lambda d: {"ok": True},
                 "/api/fechei": self._fechei}
        acao = acoes.get(caminho)
        if not acao:
            return self._responder(404, {"erro": "não encontrado"})
        try:
            return self._responder(200, acao(dados))
        except (ValueError, KeyError, OSError) as erro:
            return self._responder(400, {"erro": str(erro)})

    def _enviar(self, dados):
        texto = str(dados.get("texto") or "").strip()
        anexos = dados.get("anexos") or []
        if not texto and not anexos:
            raise ValueError("mensagem vazia")
        if not anexos and re.match(r"^/[^\s/]+(\s|$)", texto):
            return comando_janela(texto)
        if ESTADO["ocupado"]:
            raise ValueError("o Lumero ainda está respondendo")
        lembrar_mensagem(texto)
        L.CONTEXTO_SUGESTAO["proxima"] = ""
        ESTADO["ocupado"] = True
        threading.Thread(target=turno, args=(texto or "O que você vê neste anexo?", anexos),
                         daemon=True).start()
        return {"ok": True}

    def _parar(self, dados):
        PARAR.set()
        for pendente in list(CONFIRMACOES.values()):
            pendente["evento"].set()
        resposta = ESTADO.get("resposta")
        if resposta is not None:
            try:
                resposta.close()
            except Exception:
                pass
        return {"ok": True}

    def _confirmar(self, dados):
        pendente = CONFIRMACOES.get(str(dados.get("id")))
        if pendente:
            pendente["resposta"] = bool(dados.get("permitir"))
            pendente["evento"].set()
        return {"ok": bool(pendente)}

    def _nova(self, dados):
        if ESTADO["ocupado"]:
            raise ValueError("espere a resposta terminar")
        ATUAL["conversa"] = Conversa()
        L.USO_CONTEXTO["tokens"] = 0
        return {"id": ATUAL["conversa"].id}

    def _abrir(self, dados):
        if ESTADO["ocupado"]:
            raise ValueError("espere a resposta terminar")
        ATUAL["conversa"] = Conversa.abrir(str(dados.get("id")))
        L.USO_CONTEXTO["tokens"] = 0
        return {"id": ATUAL["conversa"].id}

    def _apagar(self, dados):
        ident = str(dados.get("id"))
        if not re.fullmatch(r"[\w-]+", ident):
            raise ValueError("conversa inválida")
        if ESTADO["ocupado"] and ident == conversa_atual().id:
            raise ValueError("espere a resposta terminar")
        arquivo = os.path.join(PASTA_CONVERSAS_GUI, ident + ".json")
        if os.path.exists(arquivo):
            os.remove(arquivo)
        if ident == conversa_atual().id:
            ATUAL["conversa"] = Conversa()
        return {"ok": True, "atual": conversa_atual().id}

    def _renomear(self, dados):
        ident, titulo = str(dados.get("id")), str(dados.get("titulo") or "").strip()[:80]
        if not titulo:
            raise ValueError("título vazio")
        conversa = conversa_atual() if ident == conversa_atual().id else Conversa.abrir(ident)
        conversa.titulo = titulo
        conversa.salvar()
        return {"ok": True}

    def _config(self, dados):
        if "modelo" in dados:
            modelo = str(dados["modelo"])
            if modelo not in modelos_instalados():
                raise ValueError("modelo não instalado")
            if L.MODELO_VISAO == L.MODELO:
                L.MODELO_VISAO = modelo
            L.MODELO = modelo
            gravar_config(MODELO=modelo)
        if "pensar" in dados:
            L.PENSAR = {"sempre": True, "nunca": False}.get(dados["pensar"], "auto")
            gravar_config(PENSAR=L.PENSAR)
        if "contexto" in dados:
            novo, aviso = L.trocar_contexto(str(dados["contexto"]))
            resultado = estado()
            resultado["aviso"] = aviso
            return resultado
        if "tema" in dados:
            if dados["tema"] not in TEMAS:
                raise ValueError("tema inválido")
            gravar_config(TEMA=dados["tema"])
        if "falar" in dados:
            L.FALAR_RESPOSTAS["ligado"] = bool(dados["falar"])
            if not L.FALAR_RESPOSTAS["ligado"]:
                L.parar_fala()
        return estado()

    def _link(self, dados):
        url = str(dados.get("url") or "")
        if not re.match(r"^https?://", url):
            raise ValueError("só links http e https")
        L.abrir_externo(url)
        return {"ok": True}

    def _fechei(self, dados):
        ESTADO["fechou_em"] = time.time()
        return {"ok": True}


# ============================================================================
# Janela
# ============================================================================
def _navegadores_app():
    """Navegadores que abrem uma página como aplicativo (sem abas nem barra de endereço)."""
    if L.EH_WINDOWS:
        bases = [os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", ""),
                 os.environ.get("LOCALAPPDATA", "")]
        nomes = [r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe",
                 r"BraveSoftware\Brave-Browser\Application\brave.exe"]
        return [os.path.join(b, n) for b in bases if b for n in nomes
                if os.path.exists(os.path.join(b, n))]
    if L.EH_MAC:
        apps = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
                "/Applications/Chromium.app/Contents/MacOS/Chromium"]
        return [a for a in apps if os.path.exists(a)]
    nomes = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
             "brave-browser", "microsoft-edge", "vivaldi"]
    achados = [shutil.which(n) for n in nomes if shutil.which(n)]
    if shutil.which("flatpak"):
        for app in ("com.google.Chrome", "org.chromium.Chromium", "com.brave.Browser"):
            if subprocess.run(["flatpak", "info", app], capture_output=True).returncode == 0:
                achados.append(f"flatpak run {app}")
    return achados


def _icone():
    for caminho in (os.path.join(PASTA_APP, "lumero.svg"), os.path.join(PASTA_APP, "assets", "lumero.png"),
                    os.path.join(L.PASTA_DADOS, "lumero.svg")):
        if os.path.exists(caminho):
            return caminho
    return None


def abrir_janela(url, forcar_navegador=False):
    """Abre a janela. Devolve True se ela "segura" o programa até ser fechada."""
    if not forcar_navegador:
        try:
            if L.EH_LINUX:  # o GNOME/KDE reconhece a janela como "Lumero" (ícone certo na barra)
                try:
                    import gi
                    from gi.repository import GLib
                    GLib.set_prgname("lumero")
                    GLib.set_application_name("Lumero")
                except Exception:
                    pass
            import webview
            escuro = "#1b1b1a"
            webview.create_window("Lumero", url, width=1180, height=820, min_size=(520, 560),
                                  background_color=escuro, text_select=True)
            opcoes = {}
            if L.EH_WINDOWS:
                opcoes["gui"] = "edgechromium"  # nunca o motor antigo do Internet Explorer
            elif _icone():
                opcoes["icon"] = _icone()
            try:
                webview.start(**opcoes)
            except TypeError:  # versões antigas do pywebview não têm icon=
                opcoes.pop("icon", None)
                webview.start(**opcoes)
            return True
        except Exception as erro:  # sem pywebview ou sem o motor de página: usa o navegador
            print(f"pywebview indisponível ({erro}); abrindo no navegador")
    for navegador in _navegadores_app():
        try:
            comando = navegador.split() if navegador.startswith("flatpak ") else [navegador]
            L.executar(comando + [f"--app={url}", "--new-window"])
            return False
        except OSError:
            continue
    webbrowser.open(url)
    return False


def instancia_existente():
    """Se o Lumero já está aberto, devolve a URL dele."""
    try:
        with open(ARQ_INSTANCIA, encoding="utf-8") as f:
            info = json.load(f)
        req = urllib.request.Request(f"http://127.0.0.1:{info['porta']}/api/estado",
                                     headers={"X-Lumero-Token": info["token"],
                                              "Host": f"127.0.0.1:{info['porta']}"})
        urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=2).read()
        return f"http://127.0.0.1:{info['porta']}/#t={info['token']}"
    except Exception:
        return None


def encerrar():
    try:
        os.remove(ARQ_INSTANCIA)
    except OSError:
        pass
    L.parar_fala()
    L.desligar_ollama()
    os._exit(0)


def vigiar_navegador():
    """Modo navegador: fecha o Lumero quando a página fica um bom tempo sem dar sinal."""
    while True:
        time.sleep(5)
        if not ESTADO["teve_sinal"] or ESTADO["ocupado"]:
            continue
        sem_sinal = time.time() - ESTADO["ultimo_sinal"]
        fechou = ESTADO.get("fechou_em", 0)
        with _TRAVA_OUVINTES:
            conectados = len(OUVINTES)
        if conectados == 0 and ((fechou and time.time() - fechou > 8 and fechou >= ESTADO["ultimo_sinal"] - 1)
                                or sem_sinal > 180):
            encerrar()


def main():
    forcar_navegador = "--navegador" in sys.argv
    existente = instancia_existente()
    if existente:  # já aberto: só abre outra janela para ele
        if not abrir_janela(existente, forcar_navegador):
            time.sleep(1)
        return

    os.makedirs(L.PASTA_DADOS, exist_ok=True)
    servidor = Servidor(("127.0.0.1", 0), Pedido)
    ESTADO["porta"] = servidor.server_address[1]
    with open(ARQ_INSTANCIA, "w", encoding="utf-8") as f:
        json.dump({"porta": ESTADO["porta"], "token": ESTADO["token"], "pid": os.getpid()}, f)
    try:
        os.chmod(ARQ_INSTANCIA, 0o600)
    except OSError:
        pass
    threading.Thread(target=servidor.serve_forever, daemon=True).start()

    def ligar_ollama():
        ESTADO["ollama_erro"] = L.garantir_ollama()
        evento("ollama", erro=ESTADO["ollama_erro"], modelos=modelos_instalados())
    threading.Thread(target=ligar_ollama, daemon=True).start()

    url = f"http://127.0.0.1:{ESTADO['porta']}/#t={ESTADO['token']}"
    if abrir_janela(url, forcar_navegador):
        encerrar()  # a janela foi fechada
    threading.Thread(target=vigiar_navegador, daemon=True).start()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        encerrar()


if __name__ == "__main__":
    if "--versao" in sys.argv or "--version" in sys.argv:
        print(f"Lumero {L.VERSAO} (geração {L.GERACAO}) · janela", file=sys.__stdout__)
        sys.exit(0)
    main()
