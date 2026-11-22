#!/usr/bin/env python3
"""
Lumero: assistente de IA local com Ollama + ferramentas para o seu computador.
Funciona no Linux (Fedora, Ubuntu/Debian/Mint, Arch/Manjaro, openSUSE), no Windows 10/11
e no macOS. O modelo roda no próprio computador (Ollama em 127.0.0.1); só as
ferramentas de pesquisa acessam a internet, e você pode desligá-las em PESQUISA_INTERNET.

Uso:   lumero   (ou: python3 lumero.py)        janela de chat: lumero-gui (lumero_gui.py)
Sair:  digite "sair"

O que a IA consegue fazer:
  - pesquisar na internet e ler páginas para responder perguntas
  - abrir sites, qualquer programa instalado, pastas e arquivos
  - achar arquivos a partir de uma descrição (nome, tipo, data, tamanho, conteúdo)
  - ler arquivos de texto e PDF, salvar notas
  - rodar comandos de terminal com a sua permissão (só altera a pasta pessoal)
  - comandos de administrador pedindo a sua senha na janela do sistema
  - volume, brilho, lembretes, data/hora, bateria/RAM/disco e muito mais
"""
import ctypes
import datetime
import difflib
import glob
import html
import json
import os
import platform
import random
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
from html.parser import HTMLParser

# Pacotes .deb/.rpm trazem as bibliotecas Python numa pasta "vendor" ao lado do script
_VENDOR = os.path.join(os.path.dirname(os.path.realpath(__file__)), "vendor")
if os.path.isdir(_VENDOR):
    sys.path.insert(0, _VENDOR)

# ============================================================================
# Configurações
# ============================================================================
GERACAO = 24               # sobe 1 a cada alteração no script (automático na autoedição)
VERSAO = "1.2.2"          # versão dos instaladores (Linux, Windows e Mac)
MODELO = "qwen3.5:4b"      # leve, usa ferramentas, pensa e enxerga imagens
OLLAMA = "http://127.0.0.1:11434/api/chat"
CONTEXTO = 8192            # memória da conversa em tokens (maior = mais lento no processador)
NOME_USUARIO = ""          # como o Lumero chama você (o instalador pergunta; troque com /nome)
PENSAR = "auto"            # "auto" = decide sozinho; True = sempre pensa; False = nunca
                           # Dica: comece a mensagem com ! para forçar o modo pensar

PESQUISA_INTERNET = True   # False = a IA não acessa a internet de jeito nenhum
REDE_NOS_COMANDOS = False  # True = comandos no terminal podem acessar a internet
COMANDOS_LEITURA_LIVRES = True  # True = comandos só de leitura (ls, grep...) rodam sem perguntar
TEMPO_LIMITE = 120         # segundos máximos por comando

# Buscador usado em pesquisar_internet. Se o escolhido falhar, tenta os outros.
#   "searxng"    -> Google (e outros) através do SearXNG rodando no seu PC
#   "serper"     -> Google através da API paga serper.dev (precisa de chave)
#   "duckduckgo" -> DuckDuckGo direto, sem configurar nada
BUSCADOR = "duckduckgo"
SEARXNG_URL = "http://127.0.0.1:8888"
SEARXNG_MOTORES = "startpage"  # Startpage = resultados do Google; vazio = todos os ativos
SERPER_CHAVE = os.environ.get("SERPER_API_KEY", "")

# ----------------------------------------------------------------------------
# Sistema operacional (o resto do script se adapta sozinho)
# ----------------------------------------------------------------------------
SO = "windows" if os.name == "nt" else ("mac" if sys.platform == "darwin" else "linux")
EH_WINDOWS, EH_MAC, EH_LINUX = SO == "windows", SO == "mac", SO == "linux"
SEM_JANELA = 0x08000000 if EH_WINDOWS else 0   # Windows: não piscar janelas pretas

HOME = os.path.realpath(os.path.expanduser("~"))


def _pasta_dados():
    if EH_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or os.path.join(HOME, "AppData", "Local")
        return os.path.join(base, "Lumero")
    if EH_MAC:
        return os.path.join(HOME, "Library", "Application Support", "Lumero")
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(HOME, ".local", "share")
    return os.path.join(base, "lumero")


PASTA_DADOS = _pasta_dados()

USAR_LIXEIRA = True         # True = a IA não pode usar rm; apagar = mandar para a lixeira
MODELO_VISAO = MODELO      # o qwen3.5 também enxerga imagens; "" desliga a visão

# Cuidados com o computador
AUTOEDICAO = False          # True = a IA pode alterar o próprio script (o modelo 4b erra bastante nisso)
BUSCA_FOTOS = False         # True = procurar fotos pelo conteúdo (analisa foto por foto: pesado aqui)
GERENCIAR_OLLAMA = True     # liga o Ollama ao abrir o assistente e desliga ao sair
                            # (no Windows/Mac só desliga se foi o Lumero que ligou)
TEMPERATURA_PAUSA = 88      # °C: acima disso, espera o processador esfriar antes de continuar
TEMPERATURA_RETOMA = 75     # °C: volta a trabalhar quando cair até aqui
TEMPERATURA_CRITICA = 95    # °C: interrompe a resposta no meio para proteger o notebook
WHISPER_MODELO = "base"     # reconhecimento de voz: tiny, base ou small (maior = melhor e mais lento)
VOZ_PIPER = "pt_BR-faber-medium"  # voz usada para ler as respostas em voz alta
LIMITE_MEMORIA = 3000       # tamanho máximo (em letras) da memória permanente
VOZ_SISTEMA = ""             # voz do sistema para falar (vazio = escolhe uma em português)
USUARIO = (os.environ.get("USER") or os.environ.get("USERNAME")
           or os.path.basename(HOME))


def _outros_discos():
    """Windows: D:, E:, pendrives... (discos fixos e removíveis), menos o disco do Windows."""
    sistema = os.environ.get("SystemDrive", "C:").upper()
    discos = []
    try:
        mascara = ctypes.windll.kernel32.GetLogicalDrives()
        for i in range(26):
            letra = chr(65 + i)
            if mascara & (1 << i) and f"{letra}:" != sistema:
                raiz = f"{letra}:\\"
                if ctypes.windll.kernel32.GetDriveTypeW(raiz) in (2, 3):  # removível, fixo
                    discos.append(raiz)
    except (AttributeError, OSError):
        pass
    return discos


# Onde a IA pode procurar/abrir arquivos: pasta pessoal + pendrives/HDs externos
if EH_WINDOWS:
    PASTAS_PERMITIDAS = [HOME] + _outros_discos()
elif EH_MAC:
    PASTAS_PERMITIDAS = [HOME, "/Volumes"]
else:
    PASTAS_PERMITIDAS = [HOME, f"/run/media/{USUARIO}", f"/media/{USUARIO}"]

# ----------------------------------------------------------------------------
# config.json (na pasta de dados): o instalador grava aqui o modelo escolhido, e você
# pode mudar as opções abaixo sem mexer no script. As opções de segurança (lixeira,
# rede nos comandos, autoedição...) só mudam aqui no script, de propósito.
# ----------------------------------------------------------------------------
ARQ_CONFIG = os.path.join(PASTA_DADOS, "config.json")
OPCOES_CONFIG = {"MODELO", "MODELO_VISAO", "CONTEXTO", "PENSAR", "OLLAMA", "BUSCADOR",
                 "SEARXNG_URL", "SEARXNG_MOTORES", "PESQUISA_INTERNET", "GERENCIAR_OLLAMA",
                 "BUSCA_FOTOS", "TEMPERATURA_PAUSA", "TEMPERATURA_RETOMA",
                 "TEMPERATURA_CRITICA", "WHISPER_MODELO", "VOZ_PIPER", "VOZ_SISTEMA",
                 "LIMITE_MEMORIA", "NOME_USUARIO"}


def _carregar_config():
    try:
        with open(ARQ_CONFIG, encoding="utf-8") as f:
            dados = json.load(f)
    except (OSError, ValueError):
        return
    if not isinstance(dados, dict):
        return
    g = globals()
    modelo_antes = g["MODELO"]
    for chave, valor in dados.items():
        if chave in OPCOES_CONFIG and isinstance(valor, (str, int, float, bool)):
            g[chave] = valor
    if "MODELO" in dados and "MODELO_VISAO" not in dados and g["MODELO_VISAO"] == modelo_antes:
        g["MODELO_VISAO"] = g["MODELO"]  # o modelo escolhido também enxerga imagens


_carregar_config()
NOME_USUARIO = re.sub(r"\s+", " ", re.sub(r"[^\w\s'.-]", "", str(NOME_USUARIO))).strip()[:40]


def gravar_config(**valores):
    """Grava opções no config.json (o mesmo que a janela usa)."""
    try:
        with open(ARQ_CONFIG, encoding="utf-8") as f:
            dados = json.load(f)
        if not isinstance(dados, dict):
            dados = {}
    except (OSError, ValueError):
        dados = {}
    dados.update(valores)
    os.makedirs(PASTA_DADOS, exist_ok=True)
    with open(ARQ_CONFIG, "w", encoding="utf-8") as f:
        json.dump(dados, f, indent=2, ensure_ascii=False)


def trocar_nome(novo):
    """Troca o nome do usuário. Devolve o nome gravado ("" = apagado)."""
    global NOME_USUARIO
    if str(novo or "").strip().lower() in ("apagar", "nenhum", "-"):
        novo = ""
    NOME_USUARIO = re.sub(r"\s+", " ", re.sub(r"[^\w\s'.-]", "", str(novo or ""))).strip()[:40]
    gravar_config(NOME_USUARIO=NOME_USUARIO)
    return NOME_USUARIO

NAVEGADOR_UA = ("Mozilla/5.0 (X11; Linux x86_64; rv:140.0) "
                "Gecko/20100101 Firefox/140.0")

# ============================================================================
# Utilidades
# ============================================================================
def sem_acento(texto):
    texto = unicodedata.normalize("NFKD", str(texto))
    return "".join(c for c in texto if not unicodedata.combining(c)).lower()


PASTAS_CONHECIDAS_WIN = {"DOCUMENTS": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",
                         "PICTURES": "{33E28130-4E1E-4676-835A-98395C3BC3BB}",
                         "DOWNLOAD": "{374DE290-123F-4565-9164-39C4925E467B}",
                         "MUSIC": "{4BD8D571-6D19-48D3-BE97-422220080E43}",
                         "VIDEOS": "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}"}
PASTAS_INGLES = {"DOCUMENTS": "Documents", "PICTURES": "Pictures", "DOWNLOAD": "Downloads",
                 "MUSIC": "Music", "VIDEOS": "Videos"}


def pasta_usuario(tipo, padrao_linux):
    """Pasta Documentos/Imagens/Downloads de verdade em cada sistema."""
    if EH_WINDOWS and tipo in PASTAS_CONHECIDAS_WIN:   # inclusive se estiver no OneDrive
        try:
            guid = (ctypes.c_ubyte * 16).from_buffer_copy(
                uuid.UUID(PASTAS_CONHECIDAS_WIN[tipo]).bytes_le)
            caminho = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(
                    ctypes.byref(guid), 0, None, ctypes.byref(caminho)) == 0:
                valor = caminho.value
                ctypes.windll.ole32.CoTaskMemFree(caminho)
                if valor:
                    return valor
        except Exception:
            pass
        return os.path.join(HOME, PASTAS_INGLES.get(tipo, padrao_linux))
    if EH_MAC:
        nome = "Movies" if tipo == "VIDEOS" else PASTAS_INGLES.get(tipo, padrao_linux)
        return os.path.join(HOME, nome)
    try:
        caminho = subprocess.run(["xdg-user-dir", tipo], capture_output=True,
                                 text=True).stdout.strip()
        if caminho and caminho != HOME:
            return caminho
    except OSError:
        pass
    return os.path.join(HOME, padrao_linux)


PASTA_NOTAS = os.path.join(pasta_usuario("DOCUMENTS", "Documentos"), "Notas IA")


def dentro(real, base):
    """True se o caminho `real` é `base` ou fica dentro dela."""
    r = os.path.normcase(real)
    b = os.path.normcase(os.path.realpath(base)).rstrip("\\/")
    return r == b or r.startswith(b + os.sep)


def oculto(caminho):
    """Arquivos ocultos (.algo) ou do sistema no Windows (desktop.ini, NTUSER.DAT...)."""
    if os.path.basename(caminho).startswith("."):
        return True
    if not EH_WINDOWS:
        return False
    try:
        return bool(os.stat(caminho, follow_symlinks=False).st_file_attributes & 0x6)
    except (OSError, AttributeError):
        return True


# Ferramentas extras ficam em grupos que só entram na conversa quando o assunto
# aparece. Assim o modelo lê menos texto (mais rápido em computadores sem placa de vídeo).
GATILHOS_GRUPOS = {
    "midia": ["video", "audio", "mp3", "mp4", "mkv", "gif", "ffmpeg", "transcrev", "legenda",
              "musica", "cortar", "trecho", "gravacao", "podcast", "aula gravada"],
    "fotos": ["foto", "imagem", "imagens", "redimension", "comprim", "jpg", "jpeg", "png",
              "heic", "webp", "resolucao"],
    "arquivos": ["espaco", "disco", "duplicad", "maiores arquivos", "ocupando", "limpa",
                 "limpeza", "antigos", "organiz", "compact", "zip", "extrair", "extrai",
                 "descompact", "rar", "7z", ".tar"],
    "sistema": ["atualiza", "update", "processo", "pesado", "travando", "travou", "lento",
                "lentidao", "esquent", "rede", "wifi", "wi-fi", "internet", "conexao",
                "desligou", "reiniciou", "log", "por que o notebook", "por que o computador", "por que o pc", "consumindo"],
    "tela": ["tela", "print", "captura", "screenshot", "aparecendo", "na minha frente"],
    "tarefas": ["tarefa", "to-do", "todo", "afazer", "pendente", "pomodoro", "cronometr",
                "foco", "estudar"],
    "brasil": ["dolar", "euro", "cotacao", "moeda", "cambio", "cep", "endereco", "noticia",
               "manchete", "acontecendo"],
    "programacao": ["git", "commit", "repositorio", "branch", "diff", "servidor", "localhost",
                    "php", "projeto", "npm", "deploy", "codigo"],
}
NOMES_GRUPOS = {"midia": "vídeo e áudio", "fotos": "fotos em lote",
                "arquivos": "espaço, organizar e compactar", "sistema": "sistema e rede",
                "tela": "ler a tela", "tarefas": "tarefas e cronômetro",
                "brasil": "cotação, CEP e notícias", "programacao": "git e servidor"}
GRUPOS_EM_USO = set()


def ativar_grupos(texto):
    """Liga os grupos cujo assunto apareceu. Eles ficam ligados até /limpar."""
    t = " " + sem_acento(texto) + " "
    novos = {g for g, palavras in GATILHOS_GRUPOS.items()
             if g not in GRUPOS_EM_USO and any(p in t for p in palavras)}
    GRUPOS_EM_USO.update(novos)
    return novos


def ferramentas_ativas():
    return [f["schema"] for f in FERRAMENTAS.values()
            if not f.get("grupo") or f["grupo"] in GRUPOS_EM_USO]


# ---------------------------------------------------------------------------
# Pasta do projeto: se o assistente for aberto dentro de um projeto (por exemplo,
# no terminal do VS Code), essa pasta vira o padrão das ferramentas.
# ---------------------------------------------------------------------------
MARCADORES_PROJETO = [
    (".git", "git"), ("package.json", "JavaScript/Node"), ("composer.json", "PHP"),
    ("pubspec.yaml", "Flutter/Dart"), ("go.mod", "Go"), ("pyproject.toml", "Python"),
    ("requirements.txt", "Python"), ("Cargo.toml", "Rust"), ("pom.xml", "Java"),
    ("build.gradle", "Java/Android"), ("build.gradle.kts", "Kotlin/Android"),
    ("CMakeLists.txt", "C/C++"), ("Makefile", "Make"), ("index.php", "PHP"),
    ("index.html", "HTML"), (".vscode", "VS Code"),
]


def detectar_projeto(pasta):
    """Devolve (pasta, tipos) se a pasta (ou uma acima dela) parece um projeto."""
    pasta = os.path.realpath(pasta)
    if not any(dentro(pasta, b) and os.path.normcase(pasta) != os.path.normcase(b)
               for b in PASTAS_PERMITIDAS):
        return None, []  # a própria pasta pessoal (ou fora dela) não conta como projeto
    atual = pasta
    while dentro(atual, HOME) and os.path.normcase(atual) != os.path.normcase(HOME):
        tipos = []
        for marcador, tipo in MARCADORES_PROJETO:
            if os.path.exists(os.path.join(atual, marcador)) and tipo not in tipos:
                tipos.append(tipo)
        if not tipos:
            try:
                if any(n.endswith(".php") for n in os.listdir(atual)):
                    tipos.append("PHP")
            except OSError:
                pass
        if tipos:
            return atual, tipos
        if os.path.dirname(atual) == atual:
            break
        atual = os.path.dirname(atual)
    return None, []  # não parece um projeto: segue usando a pasta pessoal


PASTA_PROJETO, TIPOS_PROJETO = detectar_projeto(os.getcwd())


def pasta_padrao():
    """Onde as ferramentas trabalham quando o usuário não diz a pasta."""
    return PASTA_PROJETO or HOME


def caminho_seguro(caminho):
    """Caminho absoluto, garantindo que fica dentro das pastas permitidas."""
    caminho = os.path.expanduser((caminho or "~").strip().strip("'\""))
    if caminho.startswith("file://"):
        caminho = urllib.request.url2pathname(urllib.parse.urlparse(caminho).path)
    if not os.path.isabs(caminho):
        # caminhos relativos: primeiro no projeto (se houver), depois na pasta pessoal
        no_projeto = os.path.join(PASTA_PROJETO, caminho) if PASTA_PROJETO else None
        na_home = os.path.join(HOME, caminho)
        if no_projeto and (os.path.exists(no_projeto) or not os.path.exists(na_home)):
            caminho = no_projeto
        else:
            caminho = na_home
    real = os.path.realpath(caminho)
    for base in PASTAS_PERMITIDAS:
        if dentro(real, base):
            return real
    raise PermissionError("Só tenho acesso à pasta pessoal e a discos externos.")


def executar(comando, **extra):
    """Inicia um programa em segundo plano, sem prender o assistente."""
    if EH_WINDOWS:
        extra.setdefault("creationflags", SEM_JANELA)
    else:
        extra.setdefault("start_new_session", True)
    return subprocess.Popen(comando, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            stdin=subprocess.DEVNULL, **extra)


def abrir_externo(alvo):
    """Abre um site, arquivo ou pasta com o programa padrão do sistema."""
    if EH_WINDOWS:
        os.startfile(alvo)
    elif EH_MAC:
        executar(["open", alvo])
    else:
        executar(["xdg-open", alvo])


def rodar(comando, timeout=60, **extra):
    """subprocess.run com texto, sem janela no Windows e sem travar se o programa não existir."""
    if EH_WINDOWS:
        extra.setdefault("creationflags", SEM_JANELA)
    if "input" not in extra:
        extra.setdefault("stdin", subprocess.DEVNULL)
    # programas de console do Windows (netsh, powercfg, ping...) escrevem na página OEM
    extra.setdefault("encoding", "oem" if EH_WINDOWS else "utf-8")
    try:
        return subprocess.run(comando, capture_output=True, text=True, timeout=timeout,
                              errors="replace", **extra)
    except (OSError, subprocess.TimeoutExpired) as erro:
        return subprocess.CompletedProcess(comando, 127, "", str(erro))


def ps_str(texto):
    """Texto como literal do PowerShell entre aspas simples."""
    return "'" + str(texto).replace("'", "''") + "'"


def powershell(script, timeout=60):
    """Windows: roda um script no PowerShell e devolve (código, saída, erros)."""
    pasta = os.path.join(PASTA_DADOS, "tmp")
    os.makedirs(pasta, exist_ok=True)
    arquivo = os.path.join(pasta, f"ps-{os.getpid()}-{time.time_ns()}.ps1")
    with open(arquivo, "w", encoding="utf-8-sig") as f:  # o PowerShell 5 precisa do BOM
        f.write("$ProgressPreference = 'SilentlyContinue'\n"
                "[Console]::OutputEncoding = [Text.Encoding]::UTF8\n" + script)
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                            "Bypass", "-File", arquivo], capture_output=True, timeout=timeout,
                           stdin=subprocess.DEVNULL, creationflags=SEM_JANELA)
        return (r.returncode, r.stdout.decode("utf-8", "replace").strip(),
                r.stderr.decode("utf-8", "replace").strip())
    except (OSError, subprocess.TimeoutExpired) as erro:
        return 1, "", str(erro)
    finally:
        try:
            os.remove(arquivo)
        except OSError:
            pass


def ps_json(script, timeout=60):
    """Windows: roda um script que termina em ConvertTo-Json e devolve sempre uma lista."""
    _, saida, _ = powershell(script, timeout)
    try:
        dados = json.loads(saida) if saida else []
    except ValueError:
        return []
    return dados if isinstance(dados, list) else [dados]


def osascript(script, timeout=30, js=False):
    """Mac: roda AppleScript (ou JavaScript for Automation) e devolve (código, saída, erros)."""
    comando = ["osascript"] + (["-l", "JavaScript"] if js else []) + ["-e", script]
    r = rodar(comando, timeout=timeout)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def as_str(texto):
    """Texto como literal do AppleScript entre aspas."""
    return '"' + str(texto).replace("\\", "\\\\").replace('"', '\\"') + '"'


def nome_do_sistema():
    if EH_WINDOWS:
        versao = platform.version()
        build = int(versao.split(".")[-1]) if versao.split(".")[-1].isdigit() else 0
        return "Windows 11" if build >= 22000 else f"Windows {platform.release()}"
    if EH_MAC:
        return f"macOS {platform.mac_ver()[0]}"
    try:
        with open("/etc/os-release") as f:
            dados = dict(l.rstrip().split("=", 1) for l in f if "=" in l)
        return dados.get("PRETTY_NAME", "Linux").strip('"')
    except OSError:
        return "Linux"


def gerenciador_pacotes():
    """Linux: dnf, apt, pacman ou zypper. Mac: brew. Windows: winget."""
    if EH_WINDOWS:
        return "winget"
    if EH_MAC:
        return "brew"
    for g in ("dnf", "apt", "pacman", "zypper"):
        if shutil.which(g):
            return g
    return ""


GERENCIADOR = gerenciador_pacotes()
NOME_SISTEMA = nome_do_sistema()
# nome do pacote em cada gerenciador: {pacote: {gerenciador: nome}}
NOMES_PACOTES = {
    "ffmpeg": {"dnf": "ffmpeg-free", "apt": "ffmpeg", "pacman": "ffmpeg", "zypper": "ffmpeg",
               "brew": "ffmpeg", "winget": "Gyan.FFmpeg"},
    "7zip": {"dnf": "7zip", "apt": "7zip", "pacman": "7zip", "zypper": "7zip",
             "brew": "sevenzip", "winget": "7zip.7zip"},
    "git": {"dnf": "git", "apt": "git", "pacman": "git", "zypper": "git", "brew": "git",
            "winget": "Git.Git"},
    "poppler": {"dnf": "poppler-utils", "apt": "poppler-utils", "pacman": "poppler",
                "zypper": "poppler-tools", "brew": "poppler"},
    "bubblewrap": {"dnf": "bubblewrap", "apt": "bubblewrap", "pacman": "bubblewrap",
                   "zypper": "bubblewrap"},
    "wl-clipboard": {"dnf": "wl-clipboard", "apt": "wl-clipboard", "pacman": "wl-clipboard",
                     "zypper": "wl-clipboard"},
    "polkit": {"dnf": "polkit", "apt": "pkexec", "pacman": "polkit", "zypper": "polkit"},
    "espeak": {"dnf": "espeak-ng", "apt": "espeak-ng", "pacman": "espeak-ng",
               "zypper": "espeak-ng"},
}


def como_instalar(pacote):
    """Comando para o usuário instalar um programa que está faltando."""
    nome = NOMES_PACOTES.get(pacote, {}).get(GERENCIADOR, pacote)
    return {"dnf": f"sudo dnf install {nome}", "apt": f"sudo apt install {nome}",
            "pacman": f"sudo pacman -S {nome}", "zypper": f"sudo zypper install {nome}",
            "brew": f"brew install {nome}", "winget": f"winget install {nome}",
            }.get(GERENCIADOR, f"instale o pacote {nome}")


def como_instalar_python(pacote):
    """Bibliotecas de Python vão no ambiente do próprio Lumero."""
    return f'"{sys.executable}" -m pip install {pacote}'


def tamanho_legivel(n):
    for unidade in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unidade}"
        n /= 1024
    return f"{n:.1f} TB"


# ============================================================================
# Interface no terminal (estilo Claude Code)
# ============================================================================
def _ativar_cores():
    """Liga as cores (sequências ANSI) no console do Windows."""
    if not EH_WINDOWS:
        return True
    try:
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-11)
        modo = ctypes.c_uint32()
        if k.GetConsoleMode(h, ctypes.byref(modo)):
            return bool(k.SetConsoleMode(h, modo.value | 0x0004))  # VIRTUAL_TERMINAL
    except Exception:
        pass
    return False


if EH_WINDOWS:  # acentos e emojis certos no console do Windows
    for _fluxo in (sys.stdout, sys.stderr):
        try:
            _fluxo.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
CORES = sys.stdout.isatty() and "NO_COLOR" not in os.environ and _ativar_cores()
ANSI_RE = re.compile(r"\033\[[0-9;]*m")
ULTIMO_PENSAMENTO = {"texto": ""}


def _cor(codigo):
    if not CORES:
        return lambda t: str(t)
    return lambda t: f"\033[{codigo}m{t}\033[0m"


laranja, laranja_n = _cor("38;5;173"), _cor("1;38;5;173")
cinza, negrito, italico = _cor("2"), _cor("1"), _cor("3")
ciano, verde, vermelho, amarelo = _cor("36"), _cor("32"), _cor("31"), _cor("33")


def perguntar(texto):
    """input() com cores: o readline precisa das cores marcadas com \\001 e \\002."""
    if EH_WINDOWS:  # o Windows não usa readline
        return input(texto)
    return input(ANSI_RE.sub(lambda m: "\001" + m.group() + "\002", texto))


def largura():
    return max(40, min(shutil.get_terminal_size((100, 24)).columns, 120))


def visivel(texto):
    return len(ANSI_RE.sub("", texto))


def quebrar(texto, prefixo, prefixo_resto):
    """Quebra o texto na largura do terminal, mantendo o recuo."""
    limite = largura()
    linhas, atual, vazia = [], prefixo, True
    for palavra in texto.split(" "):
        if not vazia and visivel(atual) + 1 + visivel(palavra) > limite:
            linhas.append(atual)
            atual = prefixo_resto + palavra
        else:
            atual += ("" if vazia else " ") + palavra
        vazia = False
    linhas.append(atual)
    return "\n".join(linhas)


def md_inline(t):
    t = re.sub(r"`([^`]+)`", lambda m: ciano(m.group(1)), t)
    t = re.sub(r"\*\*(.+?)\*\*", lambda m: negrito(m.group(1)), t)
    t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", lambda m: italico(m.group(1)), t)
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
               lambda m: f"{m.group(1)} {cinza('(' + m.group(2) + ')')}", t)
    return t


class Renderizador:
    """Mostra a resposta da IA enquanto ela é gerada, formatando o markdown."""

    def __init__(self):
        self.buffer, self.em_codigo, self.primeira = "", False, True

    def alimentar(self, pedaco):
        self.buffer += pedaco
        while "\n" in self.buffer:
            linha, self.buffer = self.buffer.split("\n", 1)
            self.linha(linha)

    def fim(self):
        if self.buffer:
            self.linha(self.buffer)
            self.buffer = ""

    def linha(self, bruta):
        s = bruta.rstrip()
        if self.primeira and not s.strip():
            return
        p1 = "\n⏺ " if self.primeira else "  "
        self.primeira = False
        pr = "  "
        if s.strip().startswith("```"):
            self.em_codigo = not self.em_codigo
            print(p1 + cinza("─" * 3 + (" " + s.strip()[3:] if s.strip()[3:] else "")))
            return
        if self.em_codigo:
            print(p1 + ciano(s))
            return
        if not s.strip():
            print()
            return
        if re.match(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$", s):
            print(p1 + cinza("─" * min(40, largura() - 4)))
            return
        if s.lstrip().startswith("|"):
            print(p1 + md_inline(s))
            return
        m = re.match(r"^(#{1,6})\s+(.*)", s)
        if m:
            print(quebrar(laranja_n(ANSI_RE.sub("", md_inline(m.group(2)))), p1, pr))
            return
        m = re.match(r"^(\s*)[-*+]\s+(.*)", s)
        if m:
            recuo = " " * len(m.group(1))
            print(quebrar(md_inline(m.group(2)), p1 + recuo + "• ", pr + recuo + "  "))
            return
        m = re.match(r"^(\s*)(\d+[.)])\s+(.*)", s)
        if m:
            recuo = " " * len(m.group(1))
            marca = m.group(2) + " "
            print(quebrar(md_inline(m.group(3)), p1 + recuo + marca,
                          pr + recuo + " " * len(marca)))
            return
        if s.startswith(">"):
            print(quebrar(cinza(md_inline(s.lstrip("> "))), p1 + cinza("│ "), pr + cinza("│ ")))
            return
        print(quebrar(md_inline(s), p1, pr))


# ---------------------------------------------------------------------------
# Decide quando vale a pena pensar
# ---------------------------------------------------------------------------
PEDIDOS_COMPLEXOS = [
    "por que", "porque ", "pq ", "explique", "explica", "compare", "compara",
    "diferenca", "analise", "analisa", "resuma", "resume", "resumo", "planeje",
    "planeja", "plano", "escreva", "escreve", "redija", "crie um", "cria um",
    "crie uma", "cria uma", "codigo", "script", "programa que", "funcao",
    "vale a pena", "melhor ", "como funciona",
    "como faco", "como fazer", "passo a passo", "corrija", "corrige", "conserta",
    "erro", "problema", "nao funciona", "sugira", "sugere", "ideia", "estrategia",
    "seu codigo", "seu script", "se altere", "altere voce", "mude voce",
    "nova funcao", "nova ferramenta", "pesquise e", "pesquisa e", "e depois",
    "organize", "organiza", "traduza", "traduz", "revise", "revisa",
    "sudo", "root", "administrador", "instala", "instalar", "desinstala",
    "remove o programa", "atualiza o sistema", "atualizar o sistema",
]
PEDIDOS_SIMPLES = [
    "abre", "abrir", "abra", "fecha", "volume", "mudo", "silencia", "que horas",
    "que dia", "data de hoje", "hora", "bateria", "ram", "cpu", "gpu", "memoria",
    "processador", "placa de video", "uso", "usando", "disco", "espaco",
    "lista", "listar", "liste", "mostra", "mostre", "anota", "anote", "lembra",
    "lixeira", "apaga", "apague", "exclui", "exclua", "restaura", "memoria", "esquece",
    "temperatura", "brilho", "clima", "tempo em", "previsao", "quanto e", "quanto da",
    "copiei", "copia", "cola", "suspende", "desliga", "bloqueia", "modo de energia",
    "lembre", "lembrete", "pasta", "toca", "pesquisa no google",
]
FERRAMENTAS_SIMPLES = {
    "abrir", "lixeira", "memoria", "lembretes", "estado_do_pc", "modo_energia",
    "ajustar_brilho", "calcular", "previsao_tempo", "area_transferencia", "energia",
    "tarefas", "cronometro", "brasil", "processos", "compactar", "espaco_disco",
    "abrir_site", "abrir_programa", "abrir_arquivo", "abrir_pasta",
    "abrir_pesquisa_google", "data_hora", "info_sistema", "uso_recursos",
    "ajustar_volume", "criar_lembrete", "salvar_nota", "listar_programas",
    "listar_arquivos", "mover_para_lixeira", "listar_lixeira", "restaurar_da_lixeira",
    "lembrar_fato", "esquecer_fato", "ver_memoria", "criar_lembrete",
    "listar_lembretes", "cancelar_lembrete",
}


def decidir_pensar(texto):
    """Devolve (pensar, texto). Mensagens começando com ! sempre pensam."""
    if texto.startswith("!"):
        return True, texto[1:].strip()
    if PENSAR is True or PENSAR is False:
        return PENSAR, texto
    t = " " + sem_acento(texto) + " "
    palavras = len(texto.split())
    if any(p in t for p in PEDIDOS_COMPLEXOS):
        return True, texto
    if palavras > 25:
        return True, texto
    if any(re.search(r"\b" + re.escape(p) + r"\b", t) for p in PEDIDOS_SIMPLES) \
            and palavras <= 15:
        return False, texto
    return palavras > 12, texto


def pensar_na_proxima_rodada(pensando_antes, chamadas, resultados):
    """Depois de usar ferramentas: precisa pensar de novo?"""
    if PENSAR is True or PENSAR is False:
        return PENSAR
    if any(r.startswith(("Erro", "Nenhum", "Não ")) for r in resultados):
        return True  # algo deu errado: vale raciocinar para tentar de outro jeito
    nomes = {c["function"]["name"] for c in chamadas}
    if nomes <= FERRAMENTAS_SIMPLES:
        return False  # só ações simples: é só confirmar o que foi feito
    return pensando_antes


class Spinner:
    FRASES = ["Pensando", "Matutando", "Raciocinando", "Elaborando", "Processando",
              "Ruminando", "Cozinhando", "Tramando"]
    QUADROS = "·✢✳✶✻✽✻✶✳✢"

    def __init__(self, texto=None, pensando=True):
        self.texto = texto or (random.choice(self.FRASES) if pensando else "Respondendo")
        self.extra, self.ativo, self.inicio = "", False, time.time()

    def _girar(self):
        i = 0
        while self.ativo:
            seg = int(time.time() - self.inicio)
            linha = (f"{laranja(self.QUADROS[i % len(self.QUADROS)])} "
                     f"{laranja(self.texto + '…')} "
                     f"{cinza(f'({seg}s{self.extra} · Ctrl+C interrompe)')}")
            sys.stdout.write("\r\033[K" + linha)
            sys.stdout.flush()
            i += 1
            time.sleep(0.12)

    def iniciar(self):
        if CORES:
            self.ativo = True
            self.thread = threading.Thread(target=self._girar, daemon=True)
            self.thread.start()
        return self

    def parar(self):
        if self.ativo:
            self.ativo = False
            self.thread.join()
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()


ROTULOS = {"servidor_dev": "Servidor", "espaco_disco": "EspaçoEmDisco", "ler_tela": "LerTela",
           "rodar_comando": "PowerShell" if EH_WINDOWS else "Bash", "criar_arquivo": "CriarArquivo", "lixeira": "Lixeira", "estado_do_pc": "EstadoDoPC", "descrever_imagem": "Visão", "buscar_fotos_por_conteudo": "BuscarFotos", "lembrar_fato": "Memória", "rodar_comando_admin": "Sudo" if EH_LINUX else "Admin", "pesquisar_internet": "Pesquisa",
           "ler_pagina": "LerPágina", "ler_arquivo": "Ler",
           "buscar_arquivos": "BuscarArquivos", "editar_proprio_codigo": "EditarScript"}


def mostrar_chamada(nome, args):
    rotulo = ROTULOS.get(nome) or "".join(p.capitalize() for p in nome.split("_"))
    if len(args) == 1:
        detalhe = str(next(iter(args.values())))
    else:
        detalhe = ", ".join(f"{k}: {str(v)!r}" if isinstance(v, str) else f"{k}: {v}"
                            for k, v in args.items())
    detalhe = detalhe.replace("\n", " ⏎ ")
    limite = largura() - visivel(rotulo) - 6
    if len(detalhe) > limite:
        detalhe = detalhe[:limite - 1] + "…"
    print(f"\n{verde('⏺')} {negrito(rotulo)}{cinza('(')}{detalhe}{cinza(')')}")


def mostrar_resultado(texto, max_linhas=4):
    linhas = (texto or "").strip().splitlines() or ["(sem resultado)"]
    pintar = vermelho if re.match(r"^(Erro|Alteração NÃO|O usuário não)", linhas[0]) else cinza
    for i, linha in enumerate(linhas[:max_linhas]):
        prefixo = "  ⎿  " if i == 0 else "     "
        limite = largura() - 6
        if len(linha) > limite:
            linha = linha[:limite - 1] + "…"
        print(pintar(prefixo + linha))
    if len(linhas) > max_linhas:
        print(cinza(f"     … +{len(linhas) - max_linhas} linhas"))


def data_do_script():
    try:
        return datetime.datetime.fromtimestamp(
            os.path.getmtime(os.path.realpath(__file__))).strftime("%d/%m/%Y %H:%M")
    except OSError:
        return "?"


def cabecalho():
    larg = min(largura(), 72)
    internet = {"searxng": "Google via SearXNG", "serper": "Google via Serper",
                "duckduckgo": "DuckDuckGo"}.get(BUSCADOR, BUSCADOR)
    linhas = [
        f"{laranja('✻')} {negrito('Lumero')}" + (cinza(f" · olá, {NOME_USUARIO}!") if NOME_USUARIO else ""),
        "",
        cinza("  /ajuda para ver os comandos · Ctrl+C interrompe"),
        "",
        cinza(f"  modelo:   {MODELO}  (pensar: "
              + {True: "sempre", False: "nunca"}.get(PENSAR, "automático") + ")"),
        cinza(f"  script:   geração {GERACAO} · alterado em {data_do_script()}"),
        cinza(f"  projeto:  {PASTA_PROJETO.replace(HOME, '~', 1)}"
              + (f"  ({', '.join(TIPOS_PROJETO)})" if TIPOS_PROJETO else "")) if PASTA_PROJETO
        else cinza(f"  pasta:    {os.getcwd()}"),
        cinza(f"  sistema:  {NOME_SISTEMA}"),
        cinza("  energia:  " + {False: "turbo desligado (modo econômico)", True: "turbo ligado",
                                None: "turbo: não informado"}[turbo_ligado()]
              + (f" · processador a {temperatura_cpu():.0f}°C" if temperatura_cpu() else ""))
        if EH_LINUX else cinza(f"  energia:  {_modo_energia_atual() or 'não informado'}"),
        cinza(f"  pesquisa: {internet if PESQUISA_INTERNET else 'desligada (offline)'}"),
    ]
    print(laranja("╭" + "─" * (larg - 2) + "╮"))
    for linha in linhas:
        espaco = max(0, larg - 4 - visivel(linha))
        print(laranja("│") + " " + linha + " " * espaco + " " + laranja("│"))
    print(laranja("╰" + "─" * (larg - 2) + "╯"))


# ---------------------------------------------------------------------------
# Linha de digitação: menu de comandos com "/" e sugestões em cinza
# (usa o prompt_toolkit, instalado pelo instalador do Lumero)
# ---------------------------------------------------------------------------
try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.auto_suggest import AutoSuggest, Suggestion
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.formatted_text import ANSI
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.styles import Style
    TEM_PTK = True
except ImportError:
    TEM_PTK = False

COMANDOS_BARRA = [
    ("/ajuda", "mostra a ajuda"),
    ("/limpar", "começa uma conversa nova"),
    ("/ferramentas", "lista o que a IA consegue fazer"),
    ("/pensar", "modo pensar: auto, sempre ou nunca"),
    ("/pensamento", "mostra o raciocínio da última resposta"),
    ("/modelo", "mostra ou troca o modelo"),
    ("/nome", "mostra ou troca o nome pelo qual o Lumero te chama"),
    ("/estado", "temperatura, bateria, CPU/RAM e uso da IA"),
    ("/extras", "grupos de ferramentas extras (ligam sozinhos pelo assunto)"),
    ("/memoria", "o que a IA lembra sobre você"),
    ("/contexto", "quanto da memória da conversa já foi usado"),
    ("/compactar", "resume a conversa para liberar memória"),
    ("/salvar", "salva a conversa atual"),
    ("/conversas", "lista as conversas salvas"),
    ("/retomar", "retoma uma conversa (sem nada: a última)"),
    ("/falar", "grava sua voz e envia como mensagem"),
    ("/ouvir", "liga/desliga a leitura das respostas em voz alta"),
    ("/sair", "fecha o assistente"),
]

# Pedidos comuns: completam o que você começou a digitar (quando o histórico não ajuda)
FRASES_COMUNS = [
    "abre o navegador", "abre a pasta Downloads", "abre o arquivo ",
    "qual a temperatura do processador?", "quanto de bateria e RAM eu tenho?",
    "como está o tempo hoje em ", "vai chover amanhã em ", "pesquisa na internet sobre ",
    "cria um script que ", "acha os arquivos ", "acha as fotos ", "lê o arquivo ",
    "me lembra de ", "me lembra às ", "lembra que ", "esquece que ",
    "coloca o volume em ", "coloca no modo economia", "coloca o brilho em ",
    "resume o texto que eu copiei", "traduz o texto que eu copiei para o inglês",
    "quanto é ", "quais lembretes eu tenho?", "o que tem na lixeira?",
    "o que tem na minha pasta ", "descreve a imagem ", "suspende o notebook",
    "explica o que é ", "que horas são?",
]

# Depois de cada resposta, um próximo passo provável aparece na linha vazia
PROXIMOS_PASSOS = {
    "criar_arquivo": "testa o script",
    "pesquisar_internet": "lê o primeiro resultado e resume",
    "ler_pagina": "resume em 3 tópicos",
    "buscar_arquivos": "abre o primeiro arquivo",
    "buscar_por_conteudo": "abre o primeiro arquivo",
    "listar_arquivos": "quanto espaço essa pasta ocupa?",
    "estado_do_pc": "coloca no modo economia",
    "previsao_tempo": "e para o fim de semana?",
    "descrever_imagem": "tem algum texto na imagem? lê para mim",
    "rodar_comando": "explica o resultado",
    "midia": "abre o arquivo gerado",
    "fotos": "abre a pasta com as fotos",
    "espaco_disco": "mostra os arquivos duplicados",
    "organizar_pasta": "pode organizar",
    "compactar": "abre a pasta",
    "sistema": "o que você recomenda?",
    "processos": "encerra o que está pesando mais",
    "tarefas": "quais são minhas tarefas?",
    "git": "sugere uma mensagem de commit",
    "servidor_dev": "abre no navegador",
    "brasil": "e o euro?",
    "ler_arquivo": "resume em 3 tópicos",
    "area_transferencia": "resume em 3 tópicos",
    "lembretes": "quais lembretes eu tenho?",
}
CONTEXTO_SUGESTAO = {"proxima": ""}


def opcoes_do_comando(comando):
    """Opções que aparecem depois de um comando, ex: /pensar <auto|sempre|nunca>."""
    if comando == "/pensar":
        return [("auto", "decide sozinho"), ("sempre", "sempre pensa"), ("nunca", "nunca pensa")]
    if comando == "/extras":
        return [("todos", "liga todos os grupos")] + list(NOMES_GRUPOS.items())
    if comando == "/modelo":
        try:
            modelos = ollama_api("/api/tags", timeout=2).get("models", [])
            return [(m["name"], tamanho_legivel(m.get("size", 0))) for m in modelos]
        except Exception:
            return []
    if comando == "/retomar":
        return [(os.path.basename(arq)[:-5], f"{data} · {titulo[:40]}")
                for arq, data, titulo in conversas_salvas()[:15]]
    return []


def completar(texto):
    """Lista de (texto a inserir, quantos caracteres substituir, descrição)."""
    if texto.startswith("/"):
        if " " not in texto:
            return [(cmd, len(texto), desc) for cmd, desc in COMANDOS_BARRA
                    if cmd.startswith(texto.lower())]
        comando, argumento = texto.split(" ", 1)
        return [(opcao, len(argumento), desc) for opcao, desc in opcoes_do_comando(comando.lower())
                if sem_acento(opcao).startswith(sem_acento(argumento))]
    palavra = texto.split(" ")[-1]
    if palavra.startswith(("~/", "/")) and not texto.startswith("/"):
        pasta, inicio = os.path.split(os.path.expanduser(palavra))
        try:
            nomes = sorted(n for n in os.listdir(pasta or "/") if not n.startswith(".")
                           and n.lower().startswith(inicio.lower()))
        except OSError:
            return []
        base = palavra[:len(palavra) - len(inicio)]
        saida = []
        for nome in nomes[:40]:
            eh_pasta = os.path.isdir(os.path.join(pasta or "/", nome))
            saida.append((base + nome + ("/" if eh_pasta else ""), len(palavra),
                          "pasta" if eh_pasta else ""))
        return saida
    return []


def sugerir(texto, historico=()):
    """O resto da frase sugerido em cinza (ou "" se não houver sugestão)."""
    if not texto:
        return CONTEXTO_SUGESTAO["proxima"]
    if texto.startswith("/"):
        opcoes = completar(texto) if " " not in texto else []
        return opcoes[0][0][len(texto):] if len(opcoes) == 1 else ""
    if len(texto) < 2:
        return ""
    for anterior in historico:  # do mais recente para o mais antigo
        if anterior.startswith(texto) and len(anterior) > len(texto) and "\n" not in anterior:
            return anterior[len(texto):]
    for frase in FRASES_COMUNS:
        if frase.startswith(texto.lower()) and len(frase) > len(texto):
            return frase[len(texto):]
    return ""


def preparar_sugestao(resposta, ferramentas_usadas):
    """Escolhe o próximo passo provável depois de uma resposta."""
    proxima = ""
    for nome in reversed(ferramentas_usadas):
        if nome in PROXIMOS_PASSOS:
            proxima = PROXIMOS_PASSOS[nome]
            break
    texto = (resposta or "").strip()
    if not proxima and texto.endswith("?"):
        proxima = "sim"  # a IA fez uma pergunta: a resposta mais provável
    CONTEXTO_SUGESTAO["proxima"] = proxima


if TEM_PTK:
    class _Completador(Completer):
        def get_completions(self, documento, evento):
            for texto, substituir, desc in completar(documento.text_before_cursor):
                yield Completion(texto, start_position=-substituir, display_meta=desc)

    class _Sugestor(AutoSuggest):
        def get_suggestion(self, buffer, documento):
            historico = list(reversed(buffer.history.get_strings()))
            resto = sugerir(documento.text, historico)
            return Suggestion(resto) if resto else None

    _SESSAO = {"sessao": None}

    def _sessao():
        if _SESSAO["sessao"] is None:
            os.makedirs(PASTA_DADOS, exist_ok=True)
            teclas = KeyBindings()

            @teclas.add("tab")
            def _(evento):
                buffer = evento.current_buffer
                if not buffer.text and CONTEXTO_SUGESTAO["proxima"]:
                    buffer.insert_text(CONTEXTO_SUGESTAO["proxima"])  # aceita o próximo passo
                elif buffer.complete_state:
                    buffer.complete_next()
                elif buffer.suggestion and buffer.suggestion.text:
                    buffer.insert_text(buffer.suggestion.text)  # Tab aceita a sugestão
                else:
                    buffer.start_completion(select_first=False)

            estilo = Style.from_dict({
                "completion-menu.completion": "bg:#2a2a2e #d0d0d0",
                "completion-menu.completion.current": "bg:#d97757 #1a1a1a bold",
                "completion-menu.meta.completion": "bg:#2a2a2e #8a8a8a",
                "completion-menu.meta.completion.current": "bg:#d97757 #1a1a1a",
                "auto-suggestion": "#6c6c6c",
                "placeholder": "#5c5c5c italic",
            })
            _SESSAO["sessao"] = PromptSession(
                history=FileHistory(os.path.join(PASTA_DADOS, "historico-linha")),
                completer=_Completador(), complete_while_typing=True,
                auto_suggest=_Sugestor(), key_bindings=teclas, style=estilo,
                reserve_space_for_menu=6)
        return _SESSAO["sessao"]


def preparar_historico():
    if TEM_PTK:
        return  # o prompt_toolkit guarda o próprio histórico
    try:
        import readline
    except ImportError:
        return
    os.makedirs(PASTA_DADOS, exist_ok=True)
    arquivo = os.path.join(PASTA_DADOS, "historico")
    try:
        readline.read_history_file(arquivo)
    except OSError:
        pass
    readline.set_history_length(1000)
    readline.set_completer(lambda texto, i: (
        [texto[:len(texto) - n] + c for c, n, _ in completar(texto)] + [None])[i])
    readline.set_completer_delims("\n")
    readline.parse_and_bind("tab: complete")  # sem prompt_toolkit: Tab completa os comandos
    import atexit
    atexit.register(lambda: readline.write_history_file(arquivo))


def _ler_linha(primeira):
    if TEM_PTK and sys.stdin.isatty():
        proxima = CONTEXTO_SUGESTAO["proxima"]
        dica = (f"{proxima}   (Tab para usar)" if proxima else
                "digite / para ver os comandos · → ou Tab aceita a sugestão")
        return _sessao().prompt(ANSI(cinza("│") + (" > " if primeira else "   ")),
                                placeholder=ANSI(cinza(dica)) if primeira else None)
    prompt = (cinza("│") + (" > " if primeira else "   "))
    return perguntar(prompt) if CORES else input("> " if primeira else "  ")


def ler_entrada():
    borda = "─" * (largura() - 2)
    print("\n" + cinza("╭" + borda + "╮"))
    try:
        texto = _ler_linha(True)
        while texto.endswith("\\"):  # termine a linha com \ para continuar
            texto = texto[:-1] + "\n" + _ler_linha(False)
    finally:
        print(cinza("╰" + borda + "╯"))
    return texto


AJUDA = """Comandos:
  /ajuda          mostra esta ajuda
  /limpar         começa uma conversa nova
  /ferramentas    lista o que a IA consegue fazer
  /pensar [modo]  auto, sempre ou nunca (sem nada, alterna)
  /pensamento     mostra o raciocínio da última resposta
  /modelo [nome]  mostra ou troca o modelo (ex: /modelo qwen3:4b)
  /memoria        mostra o que a IA lembra sobre você
  /estado         temperatura, bateria, uso de CPU/RAM e da IA
  /extras [grupo] mostra ou liga os grupos de ferramentas extras
  /contexto       mostra quanto da memória da conversa já foi usado
  /compactar      resume a conversa agora para liberar memória
  /salvar [nome]  salva a conversa atual
  /conversas      lista as conversas salvas
  /retomar [n]    retoma uma conversa (sem número: a última)
  /falar          grava sua voz e envia como mensagem
  /ouvir          liga/desliga a leitura das respostas em voz alta
  /sair           fecha o assistente

Dicas:
  • comece com ! para forçar a IA a pensar (ex: !qual o melhor jeito de...)
  • termine a linha com \\ para escrever em várias linhas
  • digite / para ver o menu de comandos; ~/ completa caminhos de pastas
  • a sugestão em cinza é aceita com → ou Tab
  • use as setas ↑ ↓ para repetir mensagens anteriores
  • Ctrl+C interrompe a IA; duas vezes seguidas fecha o assistente"""


def tratar_comando(texto, mensagens):
    global PENSAR, MODELO
    partes = texto.split(maxsplit=1)
    cmd, arg = partes[0].lower(), (partes[1].strip() if len(partes) > 1 else "")
    if cmd in ("/sair", "/exit", "/bye"):
        return "sair"
    if cmd in ("/ajuda", "/help"):
        print("\n" + AJUDA)
    elif cmd in ("/limpar", "/clear"):
        mensagens[:] = [{"role": "system", "content": prompt_sistema()}]
        GRUPOS_EM_USO.clear()
        print(cinza("\n  ⎿  Conversa reiniciada."))
    elif cmd == "/ferramentas":
        print()
        for nome, info in FERRAMENTAS.items():
            desc = info["schema"]["function"]["description"].split(". ")[0]
            grupo = info.get("grupo")
            marca = verde("•") if not grupo or grupo in GRUPOS_EM_USO else cinza("○")
            extra = cinza(f" [{grupo}]") if grupo else ""
            print(quebrar(cinza(desc), f"  {marca} {negrito(nome)}{extra}: ", "      "))
    elif cmd == "/pensar":
        opcoes = {"auto": "auto", "automatico": "auto", "sim": True, "ligado": True,
                  "sempre": True, "nao": False, "desligado": False, "nunca": False}
        if arg:
            PENSAR = opcoes.get(sem_acento(arg), PENSAR)
        else:  # alterna: auto -> sempre -> nunca -> auto
            PENSAR = {"auto": True, True: False, False: "auto"}[PENSAR]
        nome = {True: "sempre pensa", False: "nunca pensa"}.get(PENSAR, "automático")
        print(cinza(f"\n  ⎿  Modo pensar: {nome}."))
    elif cmd == "/pensamento":
        texto = ULTIMO_PENSAMENTO["texto"].strip()
        print("\n" + (quebrar(cinza(texto.replace("\n", " ")), "  ", "  ") if texto
                      else cinza("  ⎿  Não há raciocínio salvo.")))
    elif cmd == "/modelo":
        if arg:
            MODELO = arg
        print(cinza(f"\n  ⎿  Modelo: {MODELO}"))
    elif cmd == "/nome":
        if arg:
            trocar_nome(arg)
            mensagens[0]["content"] = prompt_sistema()
            print(cinza(f"\n  ⎿  Certo, vou te chamar de {NOME_USUARIO}." if NOME_USUARIO
                        else "\n  ⎿  Nome apagado."))
        else:
            print(cinza(f"\n  ⎿  Seu nome: {NOME_USUARIO or '(nenhum)'}. Para trocar: /nome Seu Nome"))
    elif cmd == "/extras":
        if arg in ("todos", "tudo"):
            GRUPOS_EM_USO.update(GATILHOS_GRUPOS)
        elif arg in GATILHOS_GRUPOS:
            GRUPOS_EM_USO.add(arg)
        print()
        for grupo, nome in NOMES_GRUPOS.items():
            marca = verde("● ligado   ") if grupo in GRUPOS_EM_USO else cinza("○ desligado")
            print(f"  {marca}  {negrito(grupo)} {cinza('· ' + nome)}")
        print(cinza("\n  Os grupos ligam sozinhos quando o assunto aparece. "
                    "Use /extras NOME ou /extras todos para ligar à mão."))
    elif cmd == "/estado":
        print(cinza("\n  ⎿  " + estado_do_pc().replace("\n", "\n     ")))
    elif cmd == "/memoria":
        print(cinza("\n  ⎿  " + ver_memoria().replace("\n", "\n     ")))
    elif cmd == "/contexto":
        uso = USO_CONTEXTO["tokens"]
        barra = int(20 * min(1, uso / CONTEXTO))
        print(cinza(f"\n  ⎿  {'█' * barra}{'░' * (20 - barra)} {uso} de {CONTEXTO} tokens "
                    f"({100 * uso // CONTEXTO}%) · resume sozinho ao passar de 70%"))
    elif cmd == "/compactar":
        try:
            if not resumir_conversa(mensagens):
                print(cinza("\n  ⎿  A conversa ainda é curta, não precisa resumir."))
            USO_CONTEXTO["tokens"] = 0
        except Exception as erro:
            print(vermelho(f"\n  ⎿  Não consegui resumir: {erro}"))
    elif cmd == "/salvar":
        print(cinza(f"\n  ⎿  Conversa salva em {salvar_conversa(mensagens, arg)}"))
    elif cmd == "/conversas":
        itens = conversas_salvas()
        print()
        if not itens:
            print(cinza("  ⎿  Nenhuma conversa salva."))
        for i, (arq, data, titulo) in enumerate(itens[:20], 1):
            nome = os.path.basename(arq)[:-5]
            print(f"  {laranja(str(i) + '.')} {negrito(nome)} {cinza('· ' + data + ' · ' + titulo[:50])}")
    elif cmd == "/retomar":
        print(cinza("\n  ⎿  " + retomar_conversa(mensagens, arg)))
        GRUPOS_EM_USO.clear()
        for m in mensagens:
            if m.get("role") == "user":
                ativar_grupos(m.get("content") or "")
        ultima = next((m for m in reversed(mensagens) if m["role"] == "assistant"
                       and m.get("content")), None)
        if ultima:
            print(quebrar(cinza(ultima["content"][:300].replace("\n", " ")), "     ", "     "))
    elif cmd == "/falar":
        try:
            texto_falado, erro = gravar_e_transcrever()
        except KeyboardInterrupt:
            print(cinza("\n  ⎿  Gravação cancelada."))
            return None
        if erro:
            print(vermelho(f"\n  ⎿  {erro}"))
            return None
        print(f"\n  {laranja('🎙️')} {texto_falado}")
        return ("mensagem", texto_falado)
    elif cmd == "/ouvir":
        FALAR_RESPOSTAS["ligado"] = not FALAR_RESPOSTAS["ligado"]
        if not FALAR_RESPOSTAS["ligado"]:
            parar_fala()
        tem_voz = (not EH_LINUX or os.path.exists(os.path.join(PASTA_VOZ, "piper-venv"))
                   or shutil.which("espeak-ng"))
        print(cinza(f"\n  ⎿  Respostas em voz alta: {'ligado' if FALAR_RESPOSTAS['ligado'] else 'desligado'}"
                    + ("" if tem_voz else " (nenhuma voz instalada: rode o instalador da voz)")))
    else:
        print(cinza(f"\n  ⎿  Comando desconhecido: {cmd}. Digite /ajuda."))
    return None


# ============================================================================
# Registro de ferramentas
# ============================================================================
FERRAMENTAS = {}


def ferramenta(descricao, parametros=None, obrigatorios=None, confirmar=False,
               precisa_internet=False, ativa=True, grupo=None):
    """confirmar pode ser True/False ou uma função que recebe os argumentos e decide."""
    def registrar(func):
        if (precisa_internet and not PESQUISA_INTERNET) or not ativa:
            return func
        props = {nome: {"type": tipo, "description": desc}
                 for nome, (tipo, desc) in (parametros or {}).items()}
        FERRAMENTAS[func.__name__] = {
            "func": func,
            "confirmar": confirmar,
            "grupo": grupo,
            "schema": {"type": "function", "function": {
                "name": func.__name__, "description": descricao,
                "parameters": {"type": "object", "properties": props,
                               "required": obrigatorios or []}}},
        }
        return func
    return registrar


# ============================================================================
# Internet: pesquisa e leitura de páginas
# ============================================================================
def baixar(url, dados=None, limite=2_000_000):
    req = urllib.request.Request(url, data=dados, headers={
        "User-Agent": NAVEGADOR_UA, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=20) as r:
        bruto = r.read(limite)
        charset = r.headers.get_content_charset() or "utf-8"
        return bruto.decode(charset, errors="replace"), r.headers.get_content_type()


def limpar_html(trecho):
    return html.unescape(re.sub(r"<[^>]+>", "", trecho)).strip()


def link_real(href):
    """O DuckDuckGo embrulha os links; extrai o endereço verdadeiro."""
    href = html.unescape(href)
    if href.startswith("//"):
        href = "https:" + href
    partes = urllib.parse.urlparse(href)
    if "duckduckgo.com" in partes.netloc and partes.path.startswith("/l/"):
        alvo = urllib.parse.parse_qs(partes.query).get("uddg", [""])[0]
        return alvo or href
    return href


def pesquisar_ddg(termo):
    dados = urllib.parse.urlencode({"q": termo, "kl": "br-pt"}).encode()
    pagina, _ = baixar("https://html.duckduckgo.com/html/", dados)
    titulos = []
    for atributos, titulo in re.findall(r'<a([^>]*class="result__a"[^>]*)>(.*?)</a>',
                                        pagina, re.S):
        href = re.search(r'href="([^"]+)"', atributos)
        if href:
            titulos.append((href.group(1), titulo))
    resumos = re.findall(r'class="result__snippet"[^>]*>(.*?)</(?:a|div)>', pagina, re.S)
    resultados = []
    for i, (href, titulo) in enumerate(titulos):
        url = link_real(href)
        if "duckduckgo.com/y.js" in url:  # anúncios
            continue
        resultados.append({"titulo": limpar_html(titulo), "url": url,
                           "resumo": limpar_html(resumos[i]) if i < len(resumos) else ""})
    return resultados


def pesquisar_wikipedia(termo):
    url = ("https://pt.wikipedia.org/w/api.php?action=query&list=search&format=json"
           "&srlimit=5&srsearch=" + urllib.parse.quote(termo))
    dados = json.loads(baixar(url)[0])
    return [{"titulo": r["title"],
             "url": "https://pt.wikipedia.org/wiki/" + urllib.parse.quote(r["title"].replace(" ", "_")),
             "resumo": limpar_html(r.get("snippet", ""))}
            for r in dados.get("query", {}).get("search", [])]


def pesquisar_searxng(termo):
    def consultar(motores):
        params = {"q": termo, "format": "json", "language": "pt-BR"}
        if motores:
            params["engines"] = motores
        url = SEARXNG_URL.rstrip("/") + "/search?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": NAVEGADOR_UA})
        local = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with local.open(req, timeout=15) as r:
            return json.load(r).get("results", [])
    resultados = consultar(SEARXNG_MOTORES)
    if not resultados and SEARXNG_MOTORES:
        resultados = consultar("")  # o Google falhou: usa os outros motores
    return [{"titulo": r.get("title", ""), "url": r.get("url", ""),
             "resumo": r.get("content", "")} for r in resultados]


def pesquisar_serper(termo):
    if not SERPER_CHAVE:
        raise RuntimeError("sem chave (SERPER_API_KEY)")
    dados = json.dumps({"q": termo, "gl": "br", "hl": "pt-br"}).encode()
    req = urllib.request.Request("https://google.serper.dev/search", data=dados, headers={
        "X-API-KEY": SERPER_CHAVE, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        resposta = json.load(r)
    resultados = []
    caixa = resposta.get("answerBox") or {}
    if caixa.get("answer") or caixa.get("snippet"):
        resultados.append({"titulo": "Resposta do Google", "url": caixa.get("link", ""),
                           "resumo": caixa.get("answer") or caixa.get("snippet")})
    for r in resposta.get("organic", []):
        resultados.append({"titulo": r.get("title", ""), "url": r.get("link", ""),
                           "resumo": r.get("snippet", "")})
    return resultados


BUSCADORES = {"searxng": ("Google/SearXNG", pesquisar_searxng),
              "serper": ("Google/Serper", pesquisar_serper),
              "duckduckgo": ("DuckDuckGo", pesquisar_ddg),
              "wikipedia": ("Wikipédia", pesquisar_wikipedia)}


@ferramenta("Pesquisa na internet (Google) e devolve os principais resultados "
            "(título, link e resumo). Use para perguntas sobre fatos, notícias, "
            "preços, pessoas, lugares ou qualquer coisa atual. Depois use ler_pagina "
            "para ler o resultado mais promissor.",
            {"termo": ("string", "O que pesquisar, de forma curta e objetiva")},
            ["termo"], precisa_internet=True)
def pesquisar_internet(termo):
    ordem = [BUSCADOR] + [b for b in BUSCADORES if b != BUSCADOR]
    erros = []
    for chave in ordem:
        if chave not in BUSCADORES or (chave == "serper" and not SERPER_CHAVE):
            continue
        nome, funcao = BUSCADORES[chave]
        try:
            resultados = funcao(termo)
        except Exception as erro:
            erros.append(f"{nome}: {erro}")
            continue
        if resultados:
            linhas = [f"{i}. {r['titulo']}\n   {r['url']}\n   {r['resumo']}"
                      for i, r in enumerate(resultados[:6], 1)]
            return f"Resultados via {nome}:\n" + "\n".join(linhas)
    return "Nenhum resultado encontrado." + (f" Erros: {'; '.join(erros)}" if erros else "")


def abrir_pesquisa_google(termo):
    abrir_externo("https://www.google.com/search?q=" + urllib.parse.quote_plus(termo))
    return f"Pesquisa do Google por '{termo}' aberta no navegador."


class ExtratorTexto(HTMLParser):
    IGNORAR = {"script", "style", "noscript", "nav", "header", "footer", "aside",
               "form", "svg", "button", "iframe"}
    BLOCOS = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr", "section",
              "article", "table"}

    def __init__(self):
        super().__init__()
        self.partes, self.ignorando, self.titulo, self._no_titulo = [], 0, "", False

    def handle_starttag(self, tag, attrs):
        if tag in self.IGNORAR:
            self.ignorando += 1
        elif tag == "title":
            self._no_titulo = True
        elif tag in self.BLOCOS:
            self.partes.append("\n")

    def handle_endtag(self, tag):
        if tag in self.IGNORAR and self.ignorando:
            self.ignorando -= 1
        elif tag == "title":
            self._no_titulo = False

    def handle_data(self, data):
        if self._no_titulo:
            self.titulo += data
        elif not self.ignorando:
            self.partes.append(data)

    def texto(self):
        bruto = "".join(self.partes)
        linhas = [re.sub(r"\s+", " ", l).strip() for l in bruto.splitlines()]
        return "\n".join(l for l in linhas if len(l) > 1)


@ferramenta("Lê o texto de uma página da internet. Use depois de pesquisar_internet "
            "para obter a informação completa.",
            {"url": ("string", "Endereço completo da página")}, ["url"],
            precisa_internet=True)
def ler_pagina(url, limite=5000):
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    conteudo, tipo = baixar(url)
    if "html" not in tipo and "text" not in tipo:
        return f"A página não é texto (tipo: {tipo})."
    extrator = ExtratorTexto()
    extrator.feed(conteudo)
    texto = extrator.texto()
    if len(texto) > limite:
        texto = texto[:limite] + "\n[... página cortada ...]"
    return f"Título: {extrator.titulo.strip()}\nFonte: {url}\n\n{texto}"


@ferramenta("Abre um site no navegador do usuário para ele ver.",
            {"url": ("string", "Endereço do site, ex: https://www.youtube.com")}, ["url"])
def abrir_site(url):
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    abrir_externo(url)
    return f"Site {url} aberto no navegador."


# ============================================================================
# Programas instalados
#   Linux: atalhos .desktop   Mac: apps .app   Windows: menu Iniciar (Get-StartApps)
# ============================================================================
PASTAS_APPS = [
    "/usr/share/applications",
    "/usr/local/share/applications",
    "/var/lib/flatpak/exports/share/applications",
    "/var/lib/snapd/desktop/applications",
    os.path.join(HOME, ".local/share/applications"),
    os.path.join(HOME, ".local/share/flatpak/exports/share/applications"),
]
PASTAS_APPS_MAC = ["/Applications", "/Applications/Utilities", "/System/Applications",
                   "/System/Applications/Utilities", os.path.join(HOME, "Applications")]
# nomes em português -> nomes que os programas costumam ter
APELIDOS_PROGRAMAS = {
    "navegador": ["firefox", "google chrome", "chrome", "edge", "microsoft edge", "safari",
                  "brave", "chromium", "opera"],
    "arquivos": ["arquivos", "files", "nautilus", "dolphin", "explorador de arquivos",
                 "file explorer", "finder"],
    "explorador": ["explorador de arquivos", "file explorer"],
    "gerenciador de arquivos": ["arquivos", "files", "dolphin", "finder", "file explorer"],
    "configuracoes": ["configuracoes", "settings", "system settings", "system preferences",
                      "ajustes do sistema", "preferencias do sistema"],
    "calculadora": ["calculadora", "calculator"],
    "bloco de notas": ["bloco de notas", "notepad", "editor de texto", "textedit", "gedit"],
    "editor de texto": ["editor de texto", "text editor", "gedit", "kate", "textedit",
                        "notepad"],
    "terminal": ["terminal", "console", "konsole", "ptyxis", "windows terminal",
                 "windows powershell", "iterm"],
    "loja": ["software", "app store", "microsoft store", "discover", "central de programas"],
    "notas": ["notes", "notas"],
    "musica": ["music", "musica", "spotify", "rhythmbox"],
    "fotos": ["photos", "fotos", "imagens"],
    "calendario": ["calendar", "calendario", "agenda"],
    "mensagens": ["messages", "mensagens"],
    "email": ["mail", "thunderbird", "outlook", "evolution", "geary"],
}


def ler_desktop(caminho):
    info, na_secao = {}, False
    try:
        with open(caminho, encoding="utf-8", errors="replace") as f:
            for linha in f:
                linha = linha.strip()
                if linha.startswith("["):
                    if na_secao:
                        break
                    na_secao = linha == "[Desktop Entry]"
                    continue
                if na_secao and "=" in linha:
                    chave, valor = linha.split("=", 1)
                    info[chave.strip()] = valor.strip()
    except OSError:
        return None
    if info.get("Type") != "Application":
        return None
    if info.get("NoDisplay", "").lower() == "true" or info.get("Hidden", "").lower() == "true":
        return None
    nome = info.get("Name[pt_BR]") or info.get("Name[pt]") or info.get("Name")
    if not nome:
        return None
    if shutil.which("gio"):
        abrir = ["gio", "launch", caminho]
    elif shutil.which("gtk-launch"):
        abrir = ["gtk-launch", os.path.basename(caminho)]
    else:  # sem gio nem gtk-launch: roda a linha Exec= sem os códigos %U, %f...
        abrir = [p for p in shlex.split(info.get("Exec", "")) if not p.startswith("%")]
    return {"nome": nome, "nome_en": info.get("Name", nome),
            "descricao": info.get("Comment[pt_BR]") or info.get("Comment", ""),
            "palavras": info.get("Keywords[pt_BR]", "") + ";" + info.get("Keywords", ""),
            "abrir": abrir}


_APPS = {"lista": None, "quando": 0.0}


def programas_instalados():
    if _APPS["lista"] is not None and time.time() - _APPS["quando"] < 600:
        return _APPS["lista"]
    apps = {}
    if EH_WINDOWS:
        dados = ps_json("Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress")
        ignorar = re.compile(r"(?i)uninstall|desinstal|readme|leia-me|\bhelp\b|ajuda|documenta")
        for d in dados:
            if d.get("Name") and d.get("AppID") and not ignorar.search(d["Name"]):
                apps[d["AppID"]] = {"nome": d["Name"], "nome_en": d["Name"], "descricao": "",
                                    "palavras": "",
                                    "abrir": ["explorer.exe", "shell:AppsFolder\\" + d["AppID"]]}
    elif EH_MAC:
        for pasta in PASTAS_APPS_MAC:
            for caminho in glob.glob(os.path.join(pasta, "*.app")):
                nome = os.path.basename(caminho)[:-4]
                apps[nome] = {"nome": nome, "nome_en": nome, "descricao": "", "palavras": "",
                              "abrir": ["open", "-a", caminho]}
    else:
        for pasta in PASTAS_APPS:
            for caminho in glob.glob(os.path.join(pasta, "*.desktop")):
                app = ler_desktop(caminho)
                if app and app["abrir"]:
                    apps[os.path.basename(caminho)] = app  # o último (do usuário) vence
    _APPS.update(lista=list(apps.values()), quando=time.time())
    return _APPS["lista"]


@ferramenta("Lista os programas instalados no computador. Use um filtro para "
            "procurar, ex: 'vídeo', 'editor', 'navegador'.",
            {"filtro": ("string", "Palavra para filtrar (opcional)")})
def listar_programas(filtro=""):
    apps = programas_instalados()
    f = sem_acento(filtro)
    if f:
        alvos = [f] + APELIDOS_PROGRAMAS.get(f, [])
        apps = [a for a in apps if any(alvo in sem_acento(
            " ".join([a["nome"], a["nome_en"], a["descricao"], a["palavras"]]))
            for alvo in alvos)]
    apps.sort(key=lambda a: sem_acento(a["nome"]))
    if not apps:
        return "Nenhum programa encontrado com esse filtro."
    return "\n".join(f"- {a['nome']}" + (f": {a['descricao']}" if a["descricao"] else "")
                     for a in apps[:60])


@ferramenta("Abre qualquer programa instalado pelo nome (ex: Firefox, Chrome, "
            "Calculadora, Terminal, Arquivos, Configurações, Spotify).",
            {"nome": ("string", "Nome do programa")}, ["nome"])
def abrir_programa(nome):
    apps = programas_instalados()
    if not apps:
        return "Erro: não consegui listar os programas instalados."
    alvos = [sem_acento(nome)] + APELIDOS_PROGRAMAS.get(sem_acento(nome), [])

    def pontuar(app):
        nomes = [sem_acento(app["nome"]), sem_acento(app["nome_en"])]
        melhor = 0.0
        for i, alvo in enumerate(alvos):
            peso = 1.0 if i == 0 else 0.95  # o nome pedido vale mais que um apelido
            if alvo in nomes:
                pontos = 3
            elif any(n.startswith(alvo) for n in nomes):
                pontos = 2.5
            elif any(alvo in n for n in nomes):
                pontos = 2
            elif alvo in sem_acento(app["palavras"] + " " + app["descricao"]):
                pontos = 1
            else:
                pontos = max(difflib.SequenceMatcher(None, alvo, n).ratio() for n in nomes)
            melhor = max(melhor, pontos * peso)
        return melhor

    candidatos = sorted(apps, key=pontuar, reverse=True)
    if pontuar(candidatos[0]) < 0.6:
        return f"Não achei um programa chamado '{nome}'. Use listar_programas para ver os disponíveis."
    app = candidatos[0]
    executar(app["abrir"])
    return f"{app['nome']} aberto."


# ============================================================================
# Arquivos: abrir, procurar, ler, notas
# ============================================================================
TIPOS = {
    "foto": [".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".raf", ".raw",
             ".bmp", ".tif", ".tiff", ".svg"],
    "video": [".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".wmv", ".mts", ".3gp"],
    "audio": [".mp3", ".wav", ".flac", ".ogg", ".m4a", ".opus", ".aac"],
    "documento": [".pdf", ".doc", ".docx", ".odt", ".txt", ".md", ".rtf"],
    "pdf": [".pdf"],
    "planilha": [".xls", ".xlsx", ".ods", ".csv"],
    "apresentacao": [".ppt", ".pptx", ".odp"],
    "compactado": [".zip", ".rar", ".7z", ".tar", ".gz", ".xz", ".bz2"],
    "codigo": [".py", ".php", ".js", ".html", ".css", ".sh", ".c", ".cpp", ".java",
               ".json", ".sql", ".ts"],
    "projeto_video": [".kdenlive"],
    "instalador": [".rpm", ".deb", ".flatpak", ".flatpakref", ".appimage", ".iso", ".exe",
                   ".msi", ".dmg", ".pkg"],
}
SINONIMOS_TIPO = {"imagem": "foto", "fotos": "foto", "imagens": "foto", "videos": "video",
                  "musica": "audio", "musicas": "audio", "som": "audio",
                  "documentos": "documento", "texto": "documento",
                  "planilhas": "planilha", "slides": "apresentacao",
                  "zip": "compactado", "programacao": "codigo"}
EXTENSOES_TEXTO = set(TIPOS["codigo"]) | {".txt", ".md", ".csv", ".log", ".xml",
                                          ".yml", ".yaml", ".ini", ".conf"}


def abrir_arquivo(arquivo):
    caminho = caminho_seguro(arquivo)
    if not os.path.exists(caminho):
        return f"O arquivo {caminho} não existe."
    abrir_externo(caminho)
    return f"{caminho} aberto."


def abrir_pasta(pasta):
    caminho = caminho_seguro(pasta)
    if not os.path.isdir(caminho):
        return f"A pasta {caminho} não existe."
    abrir_externo(caminho)
    return f"Pasta {caminho} aberta."


@ferramenta("Lista os arquivos e subpastas de uma pasta.",
            {"pasta": ("string", "Caminho da pasta. Padrão: a pasta do projeto ou a pessoal.")})
def listar_arquivos(pasta=""):
    caminho = caminho_seguro(pasta or pasta_padrao())
    itens = sorted(i for i in os.listdir(caminho) if not oculto(os.path.join(caminho, i)))
    itens = [i + ("/" if os.path.isdir(os.path.join(caminho, i)) else "") for i in itens]
    extra = f"\n(... e mais {len(itens) - 100} itens)" if len(itens) > 100 else ""
    return f"Conteúdo de {caminho}:\n" + "\n".join(itens[:100]) + extra


PASTAS_IGNORADAS = {"node_modules", "__pycache__", ".git", "venv", ".venv", "site-packages",
                    "AppData", "$Recycle.Bin", "System Volume Information"}


def pasta_ignorada(atual, nome):
    """Pastas que não valem a pena vasculhar (ocultas, de programas, do sistema)."""
    if nome.startswith(".") or nome in PASTAS_IGNORADAS:
        return True
    if EH_MAC and nome == "Library" and os.path.normcase(atual) == os.path.normcase(HOME):
        return True
    return EH_WINDOWS and oculto(os.path.join(atual, nome))


@ferramenta(
    "Procura arquivos a partir de uma descrição, convertida em filtros (palavras do "
    "nome, tipo, dias, tamanho). Use pelo menos um filtro. Se não achar, tente outras "
    "palavras ou buscar_por_conteudo.",
    {"palavras": ("string", "Palavras que provavelmente estão no nome do arquivo, "
                            "separadas por espaço, ex: 'curriculo luca'"),
     "tipo": ("string", "Tipo: foto, video, audio, documento, pdf, planilha, "
                        "apresentacao, compactado, codigo, projeto_video, instalador"),
     "dias": ("number", "Só arquivos modificados nos últimos N dias"),
     "tamanho_min_mb": ("number", "Tamanho mínimo em MB"),
     "pasta": ("string", "Onde procurar. Padrão: pasta pessoal (use ~ para ela)")})
def buscar_arquivos(palavras="", tipo="", dias=0, tamanho_min_mb=0, pasta="~"):
    raiz = caminho_seguro(pasta or "~")
    termos = [sem_acento(p) for p in re.split(r"[\s,]+", palavras or "") if len(p) > 1]
    tipo = SINONIMOS_TIPO.get(sem_acento(tipo or ""), sem_acento(tipo or ""))
    extensoes = TIPOS.get(tipo)
    if tipo and not extensoes:
        return f"Tipo '{tipo}' desconhecido. Use: {', '.join(TIPOS)}."
    limite_tempo = (datetime.datetime.now().timestamp() - float(dias) * 86400) if dias else 0
    min_bytes = float(tamanho_min_mb or 0) * 1024 * 1024
    achados = []
    for atual, subpastas, arquivos in os.walk(raiz):
        subpastas[:] = [s for s in subpastas if not pasta_ignorada(atual, s)]
        caminho_rel = sem_acento(os.path.relpath(atual, raiz))
        for arq in arquivos:
            if arq.startswith(".") or (EH_WINDOWS and arq.lower() in ("desktop.ini", "thumbs.db")):
                continue
            nome = sem_acento(arq)
            if extensoes and not any(nome.endswith(e) for e in extensoes):
                continue
            pontos = 0
            if termos:
                pontos = sum(2 if t in nome else (1 if t in caminho_rel else 0) for t in termos)
                if pontos == 0:
                    continue
            completo = os.path.join(atual, arq)
            try:
                info = os.stat(completo)
            except OSError:
                continue
            if info.st_mtime < limite_tempo or info.st_size < min_bytes:
                continue
            achados.append((pontos, info.st_mtime, info.st_size, completo))

    if not achados:
        return "Nenhum arquivo encontrado com esses filtros."
    achados.sort(key=lambda a: (a[0], a[1]), reverse=True)
    linhas = [f"{c}  ({tamanho_legivel(s)}, modificado em "
              f"{datetime.datetime.fromtimestamp(m):%d/%m/%Y})"
              for _, m, s, c in achados[:25]]
    total = f"{len(achados)} arquivos encontrados" + (", mostrando 25" if len(achados) > 25 else "")
    return f"{total}:\n" + "\n".join(linhas)


@ferramenta("Procura arquivos pelo texto que existe DENTRO deles (documentos, PDFs, "
            "anotações, códigos). Use quando o usuário lembra do conteúdo, mas não do "
            "nome do arquivo.",
            {"texto": ("string", "Palavras ou frase que aparecem dentro do arquivo")},
            ["texto"])
def buscar_por_conteudo(texto):
    # 1) Índice de pesquisa do sistema: já entende PDF, DOCX, ODT etc.
    if EH_WINDOWS:
        sql = ("SELECT TOP 25 System.ItemPathDisplay FROM SYSTEMINDEX WHERE "
               f"SCOPE='file:{HOME.replace(chr(92), '/')}' AND "
               f"FREETEXT('{texto.replace(chr(39), chr(39) * 2)}')")
        _, saida, _ = powershell(f"""
$con = New-Object -ComObject ADODB.Connection
$rs = New-Object -ComObject ADODB.Recordset
$con.Open("Provider=Search.CollatorDSO;Extended Properties='Application=Windows';")
$rs.Open({ps_str(sql)}, $con)
while (-not $rs.EOF) {{ $rs.Fields.Item('System.ItemPathDisplay').Value; $rs.MoveNext() }}
""", timeout=40)
        caminhos = [l.strip() for l in saida.splitlines() if l.strip() and os.path.isabs(l.strip())]
        if caminhos:
            return "Arquivos com esse conteúdo:\n" + "\n".join(caminhos[:25])
    if EH_MAC and shutil.which("mdfind"):  # Spotlight
        r = rodar(["mdfind", "-onlyin", HOME, texto], timeout=30)
        caminhos = [c for c in r.stdout.splitlines()
                    if c and not any(pasta_ignorada(os.path.dirname(c), parte)
                                     for parte in c.split(os.sep)[1:-1])]
        if caminhos:
            return "Arquivos com esse conteúdo:\n" + "\n".join(caminhos[:25])
    for cmd in (["localsearch", "search"], ["tracker3", "search"]):  # GNOME
        if shutil.which(cmd[0]):
            try:
                r = subprocess.run(cmd + texto.split(), capture_output=True, text=True,
                                   timeout=30, env={**os.environ, "NO_COLOR": "1"})
                caminhos = []
                for uri in re.findall(r"file://[^\s\x1b]+", r.stdout):
                    c = urllib.parse.unquote(uri[7:])
                    if c not in caminhos:
                        caminhos.append(c)
                if caminhos:
                    return "Arquivos com esse conteúdo:\n" + "\n".join(caminhos[:25])
            except (subprocess.TimeoutExpired, OSError):
                pass
            break
    # 2) Plano B: procura em arquivos de texto da pasta pessoal
    alvo = texto.lower()
    achados = []
    for atual, subpastas, arquivos in os.walk(pasta_padrao()):
        subpastas[:] = [s for s in subpastas if not pasta_ignorada(atual, s)]
        for arq in arquivos:
            if os.path.splitext(arq)[1].lower() not in EXTENSOES_TEXTO:
                continue
            completo = os.path.join(atual, arq)
            try:
                if os.path.getsize(completo) > 2_000_000:
                    continue
                with open(completo, encoding="utf-8", errors="ignore") as f:
                    if alvo in f.read().lower():
                        achados.append(completo)
            except OSError:
                continue
            if len(achados) >= 25:
                break
    if achados:
        return "Arquivos com esse conteúdo:\n" + "\n".join(achados)
    return "Nenhum arquivo encontrado com esse conteúdo."


def ler_pdf(caminho, limite=6000):
    """Texto de um PDF com pdftotext (poppler) ou pypdf. None se nenhum estiver instalado."""
    if shutil.which("pdftotext"):
        return rodar(["pdftotext", "-layout", caminho, "-"], timeout=60).stdout
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    texto = ""
    for pagina in PdfReader(caminho).pages:
        texto += (pagina.extract_text() or "") + "\n"
        if len(texto) > limite:
            break
    return texto


@ferramenta("Lê o conteúdo de um arquivo de texto ou PDF.",
            {"arquivo": ("string", "Caminho do arquivo")}, ["arquivo"])
def ler_arquivo(arquivo, limite=6000):
    caminho = caminho_seguro(arquivo)
    if caminho.lower().endswith(".pdf"):
        texto = ler_pdf(caminho, limite)
        if texto is None:
            return ("Para ler PDF, o usuário pode instalar: " + como_instalar_python("pypdf")
                    + ("" if EH_WINDOWS else f"  (ou: {como_instalar('poppler')})"))
    else:
        try:
            with open(caminho, encoding="utf-8") as f:
                texto = f.read(limite + 1)
        except UnicodeDecodeError:
            return "Esse arquivo não é de texto, não consigo ler."
    if len(texto) > limite:
        texto = texto[:limite] + "\n[... arquivo cortado ...]"
    return texto or "(arquivo vazio)"


def _confirmar_criar(args):
    """Pergunta ao substituir um arquivo que já existe ou ao mexer nos arquivos do Lumero."""
    try:
        destino = caminho_seguro(args.get("caminho", ""))
    except PermissionError:
        return False
    return (os.path.exists(destino) or dentro(destino, PASTA_DADOS)
            or dentro(destino, os.path.dirname(ESTE_SCRIPT)))


@ferramenta("Cria um arquivo de texto (script, código, configuração, página HTML...) na "
            "pasta pessoal. Para scripts, use executavel=true. Se o arquivo já existir, o "
            "antigo vai para a lixeira. Não repita o conteúdo na resposta: só diga onde "
            "salvou e como usar.",
            {"caminho": ("string", "Onde salvar, ex: ~/Scripts/organizar_fotos.sh"),
             "conteudo": ("string", "Conteúdo completo do arquivo"),
             "executavel": ("boolean", "true para scripts que serão executados")},
            ["caminho", "conteudo"], confirmar=_confirmar_criar)
def criar_arquivo(caminho, conteudo, executavel=False):
    destino = caminho_seguro(caminho)
    if os.path.isdir(destino):
        return f"Erro: {destino} é uma pasta. Informe o nome do arquivo."
    substituido = ""
    if os.path.exists(destino):
        resultado = mover_para_lixeira(destino)
        if not resultado.startswith("Movido"):
            return f"Erro: não consegui guardar a versão antiga. {resultado}"
        substituido = " (a versão antiga foi para a lixeira)"
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    texto = str(conteudo)
    if not texto.endswith("\n"):
        texto += "\n"
    with open(destino, "w", encoding="utf-8") as f:
        f.write(texto)
    if str(executavel).lower() in ("true", "1", "sim", "yes") and not EH_WINDOWS:
        os.chmod(destino, os.stat(destino).st_mode | 0o111)
    linhas = texto.splitlines()
    for linha in linhas[:12]:  # prévia do que foi salvo
        print(cinza("     │ ") + ciano(linha[:largura() - 8]))
    if len(linhas) > 12:
        print(cinza(f"     │ ... (+{len(linhas) - 12} linhas)"))
    return f"Arquivo salvo em {destino} ({len(linhas)} linhas){substituido}."


@ferramenta("Salva uma nota de texto na pasta 'Notas IA' em Documentos. Se a nota "
            "já existir, adiciona o texto no final.",
            {"titulo": ("string", "Título curto"), "conteudo": ("string", "Texto da nota")},
            ["titulo", "conteudo"])
def salvar_nota(titulo, conteudo):
    os.makedirs(PASTA_NOTAS, exist_ok=True)
    nome = "".join(c for c in titulo if c.isalnum() or c in " -_").strip() or "nota"
    caminho = os.path.join(PASTA_NOTAS, nome + ".md")
    novo = not os.path.exists(caminho)
    with open(caminho, "a", encoding="utf-8") as f:
        if novo:
            f.write(f"# {titulo}\n")
        f.write(f"\n_{datetime.datetime.now():%d/%m/%Y %H:%M}_\n\n{conteudo}\n")
    return f"Nota salva em {caminho}."


# ============================================================================
# Comandos no terminal
#   Linux: bash dentro da sandbox bubblewrap   Mac: bash dentro do sandbox-exec
#   Windows: PowerShell (sempre com a sua confirmação)
# ============================================================================
if EH_WINDOWS:
    SHELL_NOME = "PowerShell"
    COMANDOS_SO_LEITURA = {c.lower() for c in [
        "Get-ChildItem", "gci", "ls", "dir", "Get-Content", "gc", "cat", "type",
        "Select-String", "sls", "Measure-Object", "measure", "Get-Item", "gi",
        "Get-ItemProperty", "gp", "Test-Path", "Resolve-Path", "Get-Location", "pwd",
        "Get-Date", "Get-Process", "ps", "gps", "Get-Service", "gsv", "Get-ComputerInfo",
        "Get-CimInstance", "Get-PSDrive", "Get-Volume", "Get-Disk", "Get-NetIPAddress",
        "Get-NetAdapter", "Sort-Object", "sort", "Select-Object", "select", "Format-Table",
        "ft", "Format-List", "fl", "Group-Object", "group", "Where-Object", "where", "?",
        "Get-FileHash", "whoami", "hostname", "ipconfig", "systeminfo", "tree", "findstr",
        "Write-Output", "echo", "ConvertTo-Json", "Out-String", "ffprobe", "Get-Command",
        "gcm", "Get-Member", "gm", "Get-HotFix", "nvidia-smi", "Get-StartApps",
        "Get-WinEvent", "Get-Acl", "Get-Culture", "Get-TimeZone",
    ]}
    PADROES_PERIGOSOS = ["remove-item", "del ", "erase ", "rd ", "rmdir", "move-item", "mv ",
                         "set-content", "out-file", ">", "format-volume", "clear-content",
                         "rename-item", "stop-process", "kill", "shutdown", "restart-computer",
                         "reg ", "set-itemproperty", "new-itemproperty", "diskpart", "bcdedit"]
    APAGAR_DIRETO = re.compile(r"(?i)(^|[;&|(]\s*)(remove-item|ri|rm|rmdir|rd|del|erase|"
                               r"clear-recyclebin)\b|\.delete\(")
    PEDE_ADMIN = re.compile(r"(?i)(^|[;&|]\s*)(sudo|runas)\b|-verb\s+runas")
else:
    SHELL_NOME = "bash"
    COMANDOS_SO_LEITURA = {
        "ls", "cat", "head", "tail", "grep", "rg", "find", "du", "df", "wc",
        "file", "stat", "tree", "pwd", "echo", "date", "whoami", "uname", "free",
        "lsblk", "ps", "which", "sort", "cut", "tr", "basename", "dirname",
        "realpath", "ffprobe", "pdfinfo", "identify", "md5sum", "sha256sum",
        "uptime", "id", "nproc", "lscpu", "printenv",
        "sw_vers", "mdfind", "mdls", "shasum", "vm_stat",   # macOS
    }
    PADROES_PERIGOSOS = ["rm ", "rmdir", "mv ", "dd ", "shred", "chmod", "chown",
                         "truncate", ">", "-delete", "mkfs", "kill", "diskutil"]
    APAGAR_DIRETO = re.compile(r"(^|[;&|`(]\s*)(rm|rmdir|shred|unlink|srm)\b|-delete\b")
    PEDE_ADMIN = re.compile(r"(^|[;&|]\s*)(sudo|pkexec|su|doas)\b")
OPCOES_PERIGOSAS_FIND = {"-exec", "-execdir", "-delete", "-ok", "-okdir",
                         "-fprint", "-fprint0", "-fprintf", "-fls"}


def somente_leitura(comando):
    """True se o comando só lê informações (pode rodar sem perguntar)."""
    proibidos = (">", "<", "`", "$(", ";", "&", "\n", "||")
    if EH_WINDOWS:
        proibidos += ("@(", "{", "}")
    if any(s in comando for s in proibidos):
        return False
    for trecho in comando.split("|"):
        try:
            partes = shlex.split(trecho, posix=not EH_WINDOWS)
        except ValueError:
            return False
        if not partes:
            return False
        primeiro = partes[0].lower() if EH_WINDOWS else partes[0]
        if EH_WINDOWS and primeiro == "winget" and len(partes) > 1 and partes[1].lower() == "list":
            continue
        if primeiro not in COMANDOS_SO_LEITURA:
            return False
        if primeiro == "find" and OPCOES_PERIGOSAS_FIND & set(partes):
            return False
        if primeiro in ("sort", "tree") and any(
                p.startswith(("-o", "--output")) for p in partes[1:]):
            return False
    return True


def _cortar_saida(texto):
    if len(texto) > 4000:
        texto = "[... início cortado ...]\n" + texto[-4000:]
    return texto


def _perfil_sandbox_mac(rede):
    """Regras do sandbox-exec: lê tudo, escreve só na pasta pessoal e nas pastas temporárias."""
    escrita = [HOME, "/private/tmp", "/private/var/folders", "/dev"]
    regras = ["(version 1)", "(allow default)", "(deny file-write*)",
              "(allow file-write* " + " ".join(f'(subpath "{c}")' for c in escrita) + ")"]
    if not rede:
        regras.append('(deny network-outbound (remote ip "*:*"))')
    return "\n".join(regras)


def _rodar_unix(comando, pasta):
    """Linux: bubblewrap. Mac: sandbox-exec. Devolve (resultado, aviso)."""
    if EH_MAC:
        # o brew precisa da internet para instalar programas (sempre com a sua confirmação)
        rede = REDE_NOS_COMANDOS or bool(re.match(r"\s*brew\s", comando))
        prefixo = (["sandbox-exec", "-p", _perfil_sandbox_mac(rede)]
                   if shutil.which("sandbox-exec") else [])
        r = rodar(prefixo + ["/bin/bash", "-c", comando], timeout=TEMPO_LIMITE, cwd=pasta)
        if prefixo and r.returncode in (65, 71) and "sandbox" in r.stderr.lower():
            # versões futuras do macOS podem tirar o sandbox-exec: roda sem ele
            r = rodar(["/bin/bash", "-c", comando], timeout=TEMPO_LIMITE, cwd=pasta)
            return r, " (sem sandbox)"
        return r, "" if prefixo else " (sem sandbox)"
    sandbox = ["bwrap",
               "--ro-bind", "/", "/",       # sistema somente leitura
               "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
               "--bind", HOME, HOME,        # só a pasta pessoal pode ser alterada
               "--unshare-pid", "--die-with-parent", "--new-session",
               "--chdir", pasta]
    for extra in PASTAS_PERMITIDAS[1:]:     # pendrives e HDs externos também
        if os.path.isdir(extra):
            sandbox[sandbox.index("--unshare-pid"):sandbox.index("--unshare-pid")] = [
                "--bind", extra, extra]
    if not REDE_NOS_COMANDOS:
        sandbox.append("--unshare-net")
    return rodar(sandbox + ["bash", "-c", comando], timeout=TEMPO_LIMITE), ""


@ferramenta(
    ("Executa um comando do PowerShell no Windows. Use quando nenhuma outra ferramenta "
     "servir: converter arquivos (ffmpeg), compactar (Compress-Archive), renomear, criar "
     "pastas, ver informações do sistema etc. Roda com as permissões do usuário (sem "
     "administrador). Não use comandos interativos. Para apagar arquivos use a ferramenta lixeira.")
    if EH_WINDOWS else
    ("Executa um comando de terminal (bash). Use quando nenhuma outra ferramenta servir: "
     "converter arquivos (ffmpeg), compactar, renomear, criar pastas, ver informações do "
     "sistema etc. Roda sem sudo e só pode alterar arquivos dentro da pasta pessoal. Não "
     "use comandos interativos." + (" No Mac, instale programas com 'brew install NOME'."
                                    if EH_MAC else "")),
    {"comando": ("string", f"Comando {SHELL_NOME} completo"),
     "pasta": ("string", "Pasta onde rodar. Padrão: a pasta do projeto ou a pessoal")},
    ["comando"])
def rodar_comando(comando, pasta=""):
    if PEDE_ADMIN.search(comando.strip()):
        return ("Comandos de administrador não funcionam aqui. Use a ferramenta "
                "rodar_comando_admin" + ("." if EH_WINDOWS else " (sem escrever 'sudo')."))
    if USAR_LIXEIRA and APAGAR_DIRETO.search(comando):
        return ("Comando NÃO executado: apagar arquivos direto está desativado. "
                "Use a ferramenta lixeira (dá para recuperar depois).")
    if EH_LINUX and not shutil.which("bwrap"):
        return ("A sandbox não está instalada. O usuário pode rodar: "
                + como_instalar("bubblewrap"))
    pasta = caminho_seguro(pasta or pasta_padrao())
    if not os.path.isdir(pasta):
        return f"A pasta {pasta} não existe."
    aviso = ""
    if EH_WINDOWS:
        codigo, saida, erros = powershell(
            f"Set-Location -LiteralPath {ps_str(pasta)}\n{comando}\n"
            "if ($LASTEXITCODE) { exit $LASTEXITCODE }", timeout=TEMPO_LIMITE)
    else:
        r, aviso = _rodar_unix(comando, pasta)
        codigo, saida, erros = r.returncode, r.stdout, r.stderr
    if "TimeoutExpired" in str(erros) or "timed out" in str(erros):
        return f"O comando passou de {TEMPO_LIMITE} segundos e foi interrompido."
    texto = (saida + ("\n[erros]\n" + erros if str(erros).strip() else "")).strip()
    return f"Código de saída: {codigo}{aviso}\n{_cortar_saida(texto) or '(sem saída)'}"


def confirmar_comando(args):
    comando = str(args.get("comando", ""))
    pasta_cmd = caminho_seguro(args.get("pasta") or pasta_padrao())  # recusa pastas fora antes de perguntar
    if COMANDOS_LEITURA_LIVRES and somente_leitura(comando):
        return True
    if (USAR_LIXEIRA and APAGAR_DIRETO.search(comando)) or PEDE_ADMIN.search(comando):
        return True  # nem pergunta: rodar_comando vai recusar sem executar nada
    perigoso = any(p in comando.lower() for p in PADROES_PERIGOSOS)
    cor = vermelho if perigoso else amarelo
    larg = min(largura(), 80) - 2
    sinal = "PS> " if EH_WINDOWS else "$ "
    print("  " + cor("╭" + "─" * (larg - 2) + "╮"))
    print("  " + cor("│") + negrito(" Rodar este comando?"))
    print("  " + cor("│") + cinza(f"   pasta: {pasta_cmd.replace(HOME, '~', 1)}"))
    for linha in comando.splitlines() or [""]:
        print("  " + cor("│") + "   " + ciano(sinal + linha))
    if perigoso:
        print("  " + cor("│") + vermelho(" ⚠️  Pode apagar ou sobrescrever arquivos!"))
    print("  " + cor("╰" + "─" * (larg - 2) + "╯"))
    return perguntar("  Digite " + negrito("sim") + " para executar: ").strip().lower() == "sim"


# ============================================================================
# Comandos de administrador, sempre com a janela de senha do sistema
#   Linux: pkexec   Mac: osascript "with administrator privileges"   Windows: UAC
# ============================================================================
if EH_WINDOWS:
    _DESCRICAO_ADMIN = (
        "Executa um comando do PowerShell como ADMINISTRADOR. Use só para o que exige: "
        "instalar, atualizar ou remover programas (winget install --id NOME -e "
        "--accept-source-agreements --accept-package-agreements), serviços do Windows, "
        "configurações do sistema. Use sempre opções não interativas. O usuário confirma "
        "aqui e depois na janela do Windows (UAC).")
elif EH_MAC:
    _DESCRICAO_ADMIN = (
        "Executa um comando como ADMINISTRADOR (root) no Mac. Use só para o que exige sudo: "
        "arquivos do sistema, pmset, serviços (launchctl do sistema), softwareupdate. NÃO use "
        "para o brew (ele roda sem administrador, com rodar_comando). NÃO escreva 'sudo'. O "
        "usuário confirma e digita a senha numa janela do macOS.")
else:
    _DESCRICAO_ADMIN = (
        "Executa um comando como ADMINISTRADOR (root). Use só para o que exige sudo: "
        f"instalar ou remover programas ({GERENCIADOR or 'gerenciador de pacotes'}), "
        "atualizar o sistema, gerenciar serviços do sistema (systemctl), editar arquivos de "
        "configuração em /etc. NÃO escreva 'sudo' no comando. Use sempre opções não "
        "interativas (" + {"dnf": "dnf install -y", "apt": "apt-get install -y",
                           "pacman": "pacman -S --noconfirm",
                           "zypper": "zypper --non-interactive install"}.get(GERENCIADOR, "-y")
        + "). O usuário confirma e digita a senha numa janela do sistema.")


def _admin_linux(comando):
    if not shutil.which("pkexec"):
        return "O pkexec não está instalado. O usuário pode rodar: " + como_instalar("polkit")
    print(cinza("     🔐 Digite sua senha na janela que abriu... (Ctrl+C cancela)"))
    proc = subprocess.Popen(["pkexec", "bash", "-c", comando], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            text=True, bufsize=1, errors="replace")
    saida = []
    try:
        for linha in proc.stdout:  # mostra a saída ao vivo
            saida.append(linha)
            print(cinza("     │ " + linha.rstrip()[:largura() - 8]))
    except KeyboardInterrupt:
        proc.wait()
        return "O usuário interrompeu o comando no meio da execução."
    codigo = proc.wait()
    texto = "".join(saida).strip()
    if codigo in (126, 127) and not texto:
        return ("O usuário cancelou a janela de senha ou a senha não foi aceita. "
                "O comando NÃO foi executado.")
    return f"Código de saída: {codigo}\n{_cortar_saida(texto) or '(sem saída)'}"


def _admin_mac(comando):
    print(cinza("     🔐 Digite sua senha na janela do macOS... (Ctrl+C cancela)"))
    script = (f"do shell script {as_str(comando + ' 2>&1')} with prompt "
              f"{as_str('O Lumero quer rodar um comando como administrador.')} "
              "with administrator privileges")
    spinner = Spinner("Executando como administrador").iniciar()
    try:
        codigo, saida, erros = osascript(script, timeout=None)
    except KeyboardInterrupt:
        return "O usuário parou de esperar. O comando pode continuar rodando em segundo plano."
    finally:
        spinner.parar()
    if codigo and "-128" in erros:
        return "O usuário cancelou a janela de senha. O comando NÃO foi executado."
    if codigo:
        achado = re.search(r"\((-?\d+)\)\s*$", erros)
        return (f"Código de saída: {achado.group(1) if achado else codigo}\n"
                f"{_cortar_saida(erros) or '(sem saída)'}")
    return f"Código de saída: 0\n{_cortar_saida(saida) or '(sem saída)'}"


def _admin_windows(comando):
    pasta = os.path.join(PASTA_DADOS, "tmp")
    os.makedirs(pasta, exist_ok=True)
    base = os.path.join(pasta, f"admin-{time.time_ns()}")
    script, arq_saida, arq_codigo = base + ".ps1", base + ".txt", base + ".codigo"
    with open(script, "w", encoding="utf-8-sig") as f:
        f.write("$ProgressPreference = 'SilentlyContinue'\n"
                "$c = 0\n"
                "try {\n"
                f"  & {{\n{comando}\n  }} *>&1 | Out-File -LiteralPath {ps_str(arq_saida)} "
                "-Encoding utf8 -Width 300\n"
                "  if ($LASTEXITCODE) { $c = $LASTEXITCODE }\n"
                "} catch {\n"
                f"  $_ | Out-File -LiteralPath {ps_str(arq_saida)} -Append -Encoding utf8\n"
                "  $c = 1\n"
                "}\n"
                f"Set-Content -LiteralPath {ps_str(arq_codigo)} -Value $c\n")
    print(cinza("     🛡️  Confirme na janela do Windows (UAC) que vai aparecer..."))
    lancador = ("try {\n"
                "  Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList "
                f"'-NoProfile','-ExecutionPolicy','Bypass','-File',{ps_str(chr(34) + script + chr(34))}\n"
                "  exit 0\n"
                "} catch { exit 5 }\n")
    spinner = Spinner("Executando como administrador").iniciar()
    try:
        codigo_lancador, _, _ = powershell(lancador, timeout=None)
    except KeyboardInterrupt:
        return ("O usuário parou de esperar. O comando pode continuar rodando como "
                "administrador em segundo plano.")
    finally:
        spinner.parar()
    try:
        if codigo_lancador == 5 or not os.path.exists(arq_codigo):
            return ("O usuário recusou a janela do Windows (UAC) ou ela foi fechada. "
                    "O comando NÃO foi executado.")
        with open(arq_codigo, encoding="utf-8-sig", errors="replace") as f:
            codigo = f.read().strip() or "0"
        texto = ""
        if os.path.exists(arq_saida):
            with open(arq_saida, encoding="utf-8-sig", errors="replace") as f:
                texto = f.read().strip()
    finally:
        for arq in (script, arq_saida, arq_codigo):
            try:
                os.remove(arq)
            except OSError:
                pass
    return f"Código de saída: {codigo}\n{_cortar_saida(texto) or '(sem saída)'}"


@ferramenta(_DESCRICAO_ADMIN,
            {"comando": ("string", f"Comando {SHELL_NOME} completo, sem 'sudo'"),
             "motivo": ("string", "Explicação curta do que o comando faz e por quê")},
            ["comando", "motivo"])
def rodar_comando_admin(comando, motivo=""):
    comando = re.sub(r"(?i)^\s*sudo\s+", "", comando.strip())
    if EH_WINDOWS:
        return _admin_windows(comando)
    if EH_MAC:
        return _admin_mac(comando)
    return _admin_linux(comando)


def confirmar_admin(args):
    comando = re.sub(r"(?i)^\s*sudo\s+", "", str(args.get("comando", "")).strip())
    larg = min(largura(), 80) - 2
    print("  " + vermelho("╭" + "─" * (larg - 2) + "╮"))
    print("  " + vermelho("│") + negrito(" Rodar como ADMINISTRADOR?"))
    if args.get("motivo"):
        print(quebrar(cinza(str(args["motivo"])), "  " + vermelho("│") + "   ",
                      "  " + vermelho("│") + "   "))
    for linha in comando.splitlines() or [""]:
        print("  " + vermelho("│") + "   " + ciano(("PS# " if EH_WINDOWS else "# ") + linha))
    print("  " + vermelho("│") + amarelo(" ⚠️  Como administrador, este comando pode alterar TODO o sistema."))
    print("  " + vermelho("╰" + "─" * (larg - 2) + "╯"))
    return perguntar("  Digite " + negrito("sim") + " para continuar: ").strip().lower() == "sim"


# ============================================================================
# Autoedição: o assistente pode alterar o próprio script (com sua permissão)
# ============================================================================
ESTE_SCRIPT = os.path.realpath(__file__)
PASTA_BACKUPS = os.path.join(PASTA_DADOS, "backups")
REINICIAR = {"pendente": False}
TRECHOS_DE_SEGURANCA = ["bwrap", "caminho_seguro", "PASTAS_PERMITIDAS", "confirmar",
                        "input(", "somente_leitura", "COMANDOS_SO_LEITURA",
                        "unshare", "PADROES_PERIGOSOS", "TRECHOS_DE_SEGURANCA",
                        "pkexec", "confirmar_admin", "rodar_comando_admin"]


def ler_proprio_codigo():
    with open(ESTE_SCRIPT, encoding="utf-8") as f:
        return f.read()


@ferramenta("Mostra trechos do código-fonte deste próprio assistente. Sem 'busca', "
            "mostra um resumo (configurações e funções). Com 'busca', mostra as linhas "
            "em volta do texto procurado. Use antes de editar_proprio_codigo.",
            {"busca": ("string", "Texto a procurar no código, ex: 'def abrir_site' ou 'CONTEXTO ='")},
            ativa=AUTOEDICAO)
def ver_proprio_codigo(busca=""):
    linhas = ler_proprio_codigo().splitlines()
    if not busca:
        resumo = [f"{i}: {l}" for i, l in enumerate(linhas, 1)
                  if re.match(r"^(def |[A-Z_]+ = |# [A-ZÁ-Ú])", l)]
        return "\n".join(resumo)[:5000]
    trechos, vistos = [], set()
    for i, linha in enumerate(linhas):
        if busca in linha and i not in vistos:
            ini, fim = max(0, i - 8), min(len(linhas), i + 25)
            vistos.update(range(ini, fim))
            trechos.append("\n".join(f"{n + 1}: {linhas[n]}" for n in range(ini, fim)))
        if len(trechos) >= 3:
            break
    if not trechos:
        return f"'{busca}' não aparece no código."
    return ("\n...\n".join(trechos))[:5000]


def testar_codigo(codigo):
    """Confere se o código novo carrega sem erro. Devolve None se estiver tudo certo."""
    try:
        compile(codigo, ESTE_SCRIPT, "exec")
    except SyntaxError as erro:
        return f"Erro de sintaxe na linha {erro.lineno}: {erro.msg}"
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                     encoding="utf-8") as tmp:
        tmp.write(codigo)
    try:
        teste = ("import importlib.util, sys; "
                 "e = importlib.util.spec_from_file_location('teste', sys.argv[1]); "
                 "m = importlib.util.module_from_spec(e); e.loader.exec_module(m)")
        r = subprocess.run([sys.executable, "-c", teste, tmp.name],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return "O código novo dá erro ao carregar:\n" + r.stderr.strip()[-1500:]
    except subprocess.TimeoutExpired:
        return "O código novo travou ao carregar."
    finally:
        os.unlink(tmp.name)
    return None


def aplicar_codigo(novo, explicacao):
    atual = ler_proprio_codigo()
    diff = list(difflib.unified_diff(atual.splitlines(), novo.splitlines(),
                                     "atual", "novo", n=2, lineterm=""))
    mexe_seguranca = any(t in l for l in diff[2:] if l[:1] in "+-"
                         for t in TRECHOS_DE_SEGURANCA)
    cor = vermelho if mexe_seguranca else amarelo
    print("  " + cor("╭─") + negrito(" Alterar o próprio script?"))
    print("  " + cor("│") + cinza(f"  motivo: {explicacao}"))
    for linha in diff[2:80]:
        pintar = verde if linha.startswith("+") else vermelho if linha.startswith("-") \
            else ciano if linha.startswith("@@") else cinza
        print("  " + cor("│") + "  " + pintar(linha))
    if len(diff) > 80:
        print("  " + cor("│") + cinza(f"  ... (+{len(diff) - 80} linhas)"))
    if mexe_seguranca:
        print("  " + cor("│") + vermelho("  ⚠️  ATENÇÃO: mexe nas PROTEÇÕES DE SEGURANÇA!"))
    print("  " + cor("╰─"))
    if perguntar("  Digite " + negrito("sim") + " para aplicar: ").strip().lower() != "sim":
        return "O usuário não permitiu a alteração."
    os.makedirs(PASTA_BACKUPS, exist_ok=True)
    backup = os.path.join(PASTA_BACKUPS,
                          f"assistente-{datetime.datetime.now():%Y%m%d-%H%M%S-%f}.py")
    shutil.copy2(ESTE_SCRIPT, backup)
    with open(ESTE_SCRIPT, "w", encoding="utf-8") as f:
        f.write(novo)
    REINICIAR["pendente"] = True
    return (f"Alteração salva. Backup em {backup}. "
            "O assistente vai reiniciar depois desta resposta para aplicar.")


@ferramenta("Altera o código-fonte deste próprio assistente: troca um trecho exato "
            "por outro. Use para criar ferramentas novas, mudar configurações ou "
            "comportamento quando o usuário pedir. Antes, use ver_proprio_codigo e "
            "copie texto_antigo EXATAMENTE como está (com espaços e indentação). "
            "O código é testado e o usuário confirma antes de salvar.",
            {"texto_antigo": ("string", "Trecho exato que existe hoje no código (precisa aparecer uma única vez)"),
             "texto_novo": ("string", "Trecho que vai substituir o antigo"),
             "explicacao": ("string", "Explicação curta do que a mudança faz")},
            ["texto_antigo", "texto_novo", "explicacao"],
            ativa=AUTOEDICAO)
def editar_proprio_codigo(texto_antigo, texto_novo, explicacao=""):
    atual = ler_proprio_codigo()
    vezes = atual.count(texto_antigo)
    if vezes == 0:
        return ("texto_antigo não foi encontrado no código. Use ver_proprio_codigo e "
                "copie o trecho exatamente, com a mesma indentação.")
    if vezes > 1:
        return (f"texto_antigo aparece {vezes} vezes. Inclua mais linhas em volta "
                "para ficar único.")
    novo = atual.replace(texto_antigo, texto_novo, 1)
    # cada alteração vira uma nova geração do script
    novo = re.sub(r"^GERACAO = (\d+)", lambda m: f"GERACAO = {int(m.group(1)) + 1}",
                  novo, count=1, flags=re.M)
    erro = testar_codigo(novo)
    if erro:
        return f"Alteração NÃO aplicada. {erro}\nCorrija e tente de novo."
    return aplicar_codigo(novo, explicacao)


@ferramenta("Desfaz a última alteração que o assistente fez no próprio script, "
            "voltando ao backup mais recente.",
            ativa=AUTOEDICAO)
def desfazer_alteracao_script():
    backups = sorted(glob.glob(os.path.join(PASTA_BACKUPS, "assistente-*.py")))
    if not backups:
        return "Não há backups para restaurar."
    with open(backups[-1], encoding="utf-8") as f:
        anterior = f.read()
    resultado = aplicar_codigo(anterior, f"voltar para o backup {os.path.basename(backups[-1])}")
    if REINICIAR["pendente"]:
        os.remove(sorted(glob.glob(os.path.join(PASTA_BACKUPS, "assistente-*.py")))[-1])
        os.remove(backups[-1])
    return resultado


# ============================================================================
# Lixeira: apagar sem perder para sempre
#   Linux: gio trash (ou a lixeira do padrão freedesktop)   Mac: lixeira do Finder
#   Windows: Lixeira do Explorador de Arquivos
# ============================================================================
LIXEIRA_FREEDESKTOP = os.path.join(os.environ.get("XDG_DATA_HOME") or
                                   os.path.join(HOME, ".local", "share"), "Trash")
ARQ_LIXEIRA_MAC = os.path.join(PASTA_DADOS, "lixeira_mac.json")


def _lixeira_linux(caminho):
    if shutil.which("gio"):
        r = rodar(["gio", "trash", caminho], timeout=120)
        return r.returncode == 0, r.stderr.strip()
    # sem o gio: segue a especificação da lixeira do freedesktop (KDE, GNOME, XFCE...)
    if os.stat(caminho, follow_symlinks=False).st_dev != os.stat(HOME).st_dev:
        return False, "fica em outro disco e o gio não está instalado"
    arquivos = os.path.join(LIXEIRA_FREEDESKTOP, "files")
    infos = os.path.join(LIXEIRA_FREEDESKTOP, "info")
    os.makedirs(arquivos, exist_ok=True)
    os.makedirs(infos, exist_ok=True)
    nome, n = os.path.basename(caminho), 1
    base, ext = os.path.splitext(nome)
    while os.path.lexists(os.path.join(arquivos, nome)) or os.path.exists(
            os.path.join(infos, nome + ".trashinfo")):
        n += 1
        nome = f"{base}.{n}{ext}"
    with open(os.path.join(infos, nome + ".trashinfo"), "w", encoding="utf-8") as f:
        f.write(f"[Trash Info]\nPath={urllib.parse.quote(caminho)}\n"
                f"DeletionDate={datetime.datetime.now():%Y-%m-%dT%H:%M:%S}\n")
    shutil.move(caminho, os.path.join(arquivos, nome))
    return True, ""


def _lixeira_mac(caminho):
    script = ("ObjC.import('Foundation');"
              "var saida = Ref();"
              f"var ok = $.NSFileManager.defaultManager.trashItemAtURLResultingItemURLError("
              f"$.NSURL.fileURLWithPath({json.dumps(caminho)}), saida, null);"
              "ok ? ObjC.unwrap(saida[0].path) : 'ERRO';")
    codigo, saida, erros = osascript(script, js=True, timeout=120)
    if codigo or not saida or saida == "ERRO":
        return False, erros or "o Finder não conseguiu mover para a lixeira"
    registro = _ler_json(ARQ_LIXEIRA_MAC, [])
    registro.append({"lixeira": saida, "original": caminho,
                     "quando": f"{datetime.datetime.now():%d/%m/%Y %H:%M}"})
    _gravar_json(ARQ_LIXEIRA_MAC, registro[-500:])
    return True, ""


def _lixeira_windows(caminho):
    """Manda para a Lixeira usando a mesma função do Explorador de Arquivos."""
    from ctypes import wintypes

    if ctypes.windll.kernel32.GetDriveTypeW(os.path.splitdrive(caminho)[0] + "\\") == 2:
        return False, ("pendrives não têm lixeira no Windows (seria apagado para sempre), "
                       "então não apaguei")

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT),
                    ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                    ("fFlags", ctypes.c_uint16), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]
    # FO_DELETE + ALLOWUNDO (lixeira) + sem perguntas/janelas
    operacao = SHFILEOPSTRUCTW(None, 3, caminho + "\0", None, 0x40 | 0x10 | 0x4 | 0x400,
                               False, None, None)
    resultado = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operacao))
    if resultado == 0 and not operacao.fAnyOperationsAborted:
        return True, ""
    return False, "o Windows não conseguiu mover para a lixeira"


def mover_para_lixeira(caminhos):
    itens = [c.strip() for c in re.split(r"[\n;]", str(caminhos)) if c.strip()]
    feitos, erros = [], []
    for item in itens:
        try:
            caminho = caminho_seguro(item)
        except PermissionError as erro:
            erros.append(f"{item}: {erro}")
            continue
        if any(os.path.normcase(caminho).rstrip("\\/") == os.path.normcase(b).rstrip("\\/")
               for b in PASTAS_PERMITIDAS + [HOME]):
            erros.append(f"{caminho}: não posso mandar a pasta inteira para a lixeira")
            continue
        if not os.path.lexists(caminho):
            erros.append(f"{caminho}: não existe")
            continue
        try:
            funcao = (_lixeira_windows if EH_WINDOWS else
                      _lixeira_mac if EH_MAC else _lixeira_linux)
            ok, motivo = funcao(caminho)
        except OSError as erro:
            ok, motivo = False, str(erro)
        if ok:
            feitos.append(caminho)
        else:
            erros.append(f"{caminho}: {motivo}")
    partes = []
    if feitos:
        partes.append("Movido para a lixeira:\n" + "\n".join(feitos))
    if erros:
        partes.append("Erro: não consegui apagar:\n" + "\n".join(erros))
    return "\n".join(partes) or "Nada para apagar."


def _itens_lixeira():
    """Lista de (identificador, caminho original)."""
    if EH_WINDOWS:
        dados = ps_json("""
$lixeira = (New-Object -ComObject Shell.Application).NameSpace(10)
@($lixeira.Items() | ForEach-Object {
    [pscustomobject]@{ nome = $_.Name; origem = $_.ExtendedProperty('System.Recycle.DeletedFrom'); id = $_.Path }
}) | ConvertTo-Json -Compress
""")
        return [(d.get("id", ""), os.path.join(d.get("origem") or "", d.get("nome") or ""))
                for d in dados if d.get("id")]
    if EH_MAC:
        itens, registro = [], _ler_json(ARQ_LIXEIRA_MAC, [])
        restantes = []
        for r in registro:
            try:
                os.lstat(r["lixeira"])
            except FileNotFoundError:
                continue  # a lixeira foi esvaziada ou o item foi devolvido
            except OSError:
                pass      # o macOS pode bloquear a leitura da lixeira: mantém o registro
            restantes.append(r)
            itens.append((r["lixeira"], r["original"]))
        if len(restantes) != len(registro):
            _gravar_json(ARQ_LIXEIRA_MAC, restantes)
        return itens
    if shutil.which("gio"):
        r = rodar(["gio", "trash", "--list"])
        itens = [tuple(l.split("\t", 1)) for l in r.stdout.splitlines() if "\t" in l]
        if itens:
            return itens
    itens = []  # sem o gvfs (fora do GNOME): lê a lixeira direto
    for info in glob.glob(os.path.join(LIXEIRA_FREEDESKTOP, "info", "*.trashinfo")):
        try:
            with open(info, encoding="utf-8") as f:
                achado = re.search(r"^Path=(.+)$", f.read(), re.M)
        except OSError:
            continue
        if achado:
            itens.append((info, urllib.parse.unquote(achado.group(1).strip())))
    return itens


def listar_lixeira():
    itens = _itens_lixeira()
    if not itens:
        return "A lixeira está vazia." + (" (No Mac só aparecem os itens que o Lumero apagou.)"
                                         if EH_MAC else "")
    return f"{len(itens)} itens na lixeira:\n" + "\n".join(o for _, o in itens[:50])


def restaurar_da_lixeira(nome):
    alvo = sem_acento(nome)
    achados = [(u, o) for u, o in _itens_lixeira() if alvo in sem_acento(o)]
    if not achados:
        return "Nenhum item da lixeira corresponde a esse nome."
    if len(achados) > 1:
        return ("Vários itens correspondem, seja mais específico:\n"
                + "\n".join(o for _, o in achados[:20]))
    ident, original = achados[0]
    if os.path.lexists(original):
        return f"Erro: já existe um arquivo em {original}. Renomeie ou mova ele antes."
    if EH_WINDOWS:
        codigo, _, erros = powershell(f"""
$lixeira = (New-Object -ComObject Shell.Application).NameSpace(10)
$item = $lixeira.Items() | Where-Object {{ $_.Path -eq {ps_str(ident)} }} | Select-Object -First 1
if (-not $item) {{ exit 2 }}
$item.InvokeVerb('undelete')
""")
        if codigo != 0:
            return f"Erro ao restaurar. {erros}".strip()
    elif EH_MAC:
        try:
            os.makedirs(os.path.dirname(original), exist_ok=True)
            shutil.move(ident, original)
        except PermissionError:
            return ("O macOS não deixou o terminal mexer na lixeira. Abra a Lixeira no "
                    "Finder, clique com o botão direito no item e escolha 'Devolver'.")
        except OSError as erro:
            return f"Erro ao restaurar: {erro}"
    elif shutil.which("gio") and ident.startswith("trash:"):
        r = rodar(["gio", "trash", "--restore", ident])
        if r.returncode != 0:
            return f"Erro ao restaurar: {r.stderr.strip()}"
    else:
        arquivo = os.path.join(LIXEIRA_FREEDESKTOP, "files",
                               os.path.basename(ident)[:-len(".trashinfo")])
        try:
            os.makedirs(os.path.dirname(original), exist_ok=True)
            shutil.move(arquivo, original)
            os.remove(ident)
        except OSError as erro:
            return f"Erro ao restaurar: {erro}"
    return f"Restaurado: {original}"


# ============================================================================
# Memória permanente (vale para todas as conversas)
# ============================================================================
ARQ_MEMORIA = os.path.join(PASTA_DADOS, "memoria.md")


def ler_memoria():
    try:
        with open(ARQ_MEMORIA, encoding="utf-8") as f:
            return [l.strip()[2:] for l in f if l.strip().startswith("- ")]
    except OSError:
        return []


def gravar_memoria(fatos):
    os.makedirs(PASTA_DADOS, exist_ok=True)
    with open(ARQ_MEMORIA, "w", encoding="utf-8") as f:
        f.write("# Memória do assistente\n\n" + "".join(f"- {x}\n" for x in fatos))


def lembrar_fato(fato):
    fatos = ler_memoria()
    fato = " ".join(str(fato).split())
    if any(sem_acento(fato) == sem_acento(f) for f in fatos):
        return "Esse fato já está na memória."
    if sum(len(f) for f in fatos) + len(fato) > LIMITE_MEMORIA:
        return "Erro: a memória está cheia. Peça ao usuário para esquecer algo antes."
    gravar_memoria(fatos + [fato])
    return f"Guardado na memória: {fato}"


def esquecer_fato(trecho):
    fatos = ler_memoria()
    alvo = sem_acento(trecho)
    ficam = [f for f in fatos if alvo not in sem_acento(f)]
    saem = [f for f in fatos if alvo in sem_acento(f)]
    if not saem:
        return "Nenhum fato da memória contém esse texto."
    gravar_memoria(ficam)
    return "Esquecido:\n" + "\n".join(saem)


def ver_memoria():
    fatos = ler_memoria()
    return "Memória:\n" + "\n".join(f"- {f}" for f in fatos) if fatos else "A memória está vazia."


# ============================================================================
# Lembretes de verdade (systemd): funcionam com o assistente fechado
# ============================================================================
PASTA_UNIDADES = os.path.join(HOME, ".config/systemd/user")
PASTA_AGENTES_MAC = os.path.join(HOME, "Library", "LaunchAgents")
PASTA_LEMBRETES = os.path.join(PASTA_DADOS, "lembretes")
PREFIXO_TAREFA = "Lumero-Lembrete-"           # Windows: Agendador de Tarefas
PREFIXO_AGENTE = "com.lumero.lembrete-"       # Mac: launchd
AVISO_PS1 = r"""
$msg = __MENSAGEM__
try {
    [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
    [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
    $texto = [Security.SecurityElement]::Escape($msg)
    $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
    $xml.LoadXml("<toast scenario='reminder'><visual><binding template='ToastGeneric'><text>🔔 Lembrete</text><text>$texto</text></binding></visual><actions><action content='OK' arguments='ok' activationType='foreground'/></actions><audio src='ms-winsoundevent:Notification.Reminder'/></toast>")
    $app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($xml))
} catch {
    (New-Object -ComObject WScript.Shell).Popup($msg, 0, 'Lembrete', 64) | Out-Null
}
Unregister-ScheduledTask -TaskName __TAREFA__ -Confirm:$false -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $PSCommandPath -ErrorAction SilentlyContinue
"""


def _interpretar_horario(texto):
    texto = texto.strip().lower().replace("h", ":").replace("::", ":").rstrip(":")
    agora = datetime.datetime.now()
    for formato in ("%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M", "%d/%m %H:%M", "%H:%M"):
        try:
            dt = datetime.datetime.strptime(texto, formato)
        except ValueError:
            continue
        if formato == "%H:%M":
            dt = agora.replace(hour=dt.hour, minute=dt.minute, second=0, microsecond=0)
            if dt <= agora:
                dt += datetime.timedelta(days=1)
        elif formato == "%d/%m %H:%M":
            dt = dt.replace(year=agora.year)
            if dt <= agora:
                dt = dt.replace(year=agora.year + 1)
        return dt
    if re.fullmatch(r"\d{1,2}", texto):
        return _interpretar_horario(texto + ":00")
    raise ValueError(f"não entendi o horário '{texto}'. Use HH:MM ou DD/MM/AAAA HH:MM")


def _systemctl(*args):
    return rodar(["systemctl", "--user", *args])


def _quando_do_lembrete(minutos, horario):
    if horario:
        return _interpretar_horario(str(horario))
    if minutos:
        return datetime.datetime.now() + datetime.timedelta(minutes=float(minutos))
    raise ValueError("informe 'minutos' ou 'horario'.")


def _lembrete_windows(ident, mensagem, quando):
    script = os.path.join(PASTA_LEMBRETES, ident + ".ps1")
    with open(script, "w", encoding="utf-8-sig") as f:
        f.write(AVISO_PS1.replace("__MENSAGEM__", ps_str(mensagem))
                         .replace("__TAREFA__", ps_str(ident)))
    argumentos = f'-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{script}"'
    codigo, _, erros = powershell(f"""
$acao = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument {ps_str(argumentos)}
$quando = [datetime]::ParseExact({ps_str(f"{quando:%Y-%m-%dT%H:%M:%S}")}, 'yyyy-MM-ddTHH:mm:ss', $null)
$gatilho = New-ScheduledTaskTrigger -Once -At $quando
$config = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName {ps_str(ident)} -Action $acao `
    -Trigger $gatilho -Settings $config -Description {ps_str(str(mensagem)[:200])} | Out-Null
""")
    if codigo != 0:
        try:
            os.remove(script)
        except OSError:
            pass
        return erros[:500] or "o Agendador de Tarefas recusou"
    return ""


def _lembrete_mac(ident, mensagem, quando):
    import plistlib
    os.makedirs(PASTA_AGENTES_MAC, exist_ok=True)
    script = os.path.join(PASTA_LEMBRETES, ident + ".sh")
    plist = os.path.join(PASTA_AGENTES_MAC, ident + ".plist")
    aviso = (f"display notification {as_str(mensagem)} with title {as_str('🔔 Lembrete')} "
             f"subtitle \"Lumero\" sound name \"Glass\"")
    with open(script, "w", encoding="utf-8") as f:
        f.write(f"""#!/bin/bash
osascript -e {shlex.quote(aviso)}
osascript -e {shlex.quote(f'display alert "🔔 Lembrete" message {as_str(mensagem)} giving up after 600')} >/dev/null 2>&1 &
sleep 2
rm -f {shlex.quote(plist)} {shlex.quote(script)} {shlex.quote(os.path.join(PASTA_LEMBRETES, ident + ".json"))}
launchctl bootout gui/$(id -u)/{ident} 2>/dev/null || launchctl remove {ident}
""")
    os.chmod(script, 0o755)
    with open(plist, "wb") as f:
        plistlib.dump({"Label": ident, "ProgramArguments": ["/bin/bash", script],
                       "StartCalendarInterval": {"Month": quando.month, "Day": quando.day,
                                                 "Hour": quando.hour, "Minute": quando.minute},
                       "LimitLoadToSessionType": "Aqua"}, f)
    r = rodar(["launchctl", "bootstrap", f"gui/{os.getuid()}", plist])
    if r.returncode != 0:
        r = rodar(["launchctl", "load", plist])
    if r.returncode != 0:
        for arq in (plist, script):
            try:
                os.remove(arq)
            except OSError:
                pass
        return r.stderr.strip() or "o launchd recusou"
    return ""


def _lembrete_linux(ident, mensagem, quando):
    if not shutil.which("systemctl"):
        return "systemd não encontrado"
    os.makedirs(PASTA_UNIDADES, exist_ok=True)
    script = os.path.join(PASTA_LEMBRETES, ident + ".sh")
    unidade = os.path.join(PASTA_UNIDADES, ident)
    with open(script, "w", encoding="utf-8") as f:
        f.write(f"""#!/bin/bash
# Mostra a notificação (tenta por até 3 min, caso o PC tenha acabado de ligar)
for i in $(seq 1 36); do
    notify-send -u critical -a "Lumero" -i lumero "🔔 Lembrete" {shlex.quote(str(mensagem))} && break
    sleep 5
done
SOM=/usr/share/sounds/freedesktop/stereo/complete.oga
paplay "$SOM" 2>/dev/null || pw-play "$SOM" 2>/dev/null
systemctl --user disable {ident}.timer
rm -f {shlex.quote(unidade)}.timer {shlex.quote(unidade)}.service {shlex.quote(script)}
systemctl --user daemon-reload
""")
    with open(unidade + ".service", "w", encoding="utf-8") as f:
        f.write(f"[Unit]\nDescription=Lembrete: {str(mensagem)[:100]}\n\n"
                f"[Service]\nType=oneshot\nExecStart=/bin/bash \"{script}\"\n")
    with open(unidade + ".timer", "w", encoding="utf-8") as f:
        f.write(f"[Unit]\nDescription=Lembrete: {str(mensagem)[:100]}\n\n"
                f"[Timer]\nOnCalendar={quando:%Y-%m-%d %H:%M:%S}\nPersistent=true\n"
                f"AccuracySec=1s\n\n[Install]\nWantedBy=timers.target\n")
    _systemctl("daemon-reload")
    r = _systemctl("enable", "--now", ident + ".timer")
    return "" if r.returncode == 0 else (r.stderr.strip() or "o systemd recusou")


def criar_lembrete(mensagem, minutos=0, horario=""):
    try:
        quando = _quando_do_lembrete(minutos, horario)
    except ValueError as erro:
        return f"Erro: {erro}"
    os.makedirs(PASTA_LEMBRETES, exist_ok=True)
    marca = f"{datetime.datetime.now():%Y%m%d%H%M%S%f}"
    if EH_WINDOWS:
        ident = PREFIXO_TAREFA + marca
        erro = _lembrete_windows(ident, mensagem, quando)
    elif EH_MAC:
        ident = PREFIXO_AGENTE + marca
        erro = _lembrete_mac(ident, mensagem, quando)
    else:
        ident = "lembrete-" + marca
        erro = _lembrete_linux(ident, mensagem, quando)
    if erro:
        return f"Erro ao criar o lembrete: {erro}"
    if EH_MAC:  # o launchd não guarda o texto: fica num arquivo ao lado
        _gravar_json(os.path.join(PASTA_LEMBRETES, ident + ".json"),
                     {"texto": str(mensagem), "quando": f"{quando:%Y-%m-%d %H:%M:%S}"})
    return f"Lembrete criado para {quando:%d/%m/%Y às %H:%M}: {mensagem}"


def _lembretes():
    """Lista de (identificador, quando em dd/mm/aaaa hh:mm, texto) em ordem de horário."""
    itens = []

    def adicionar(ident, quando, texto, formato):
        try:
            quando_br = datetime.datetime.strptime(quando, formato).strftime("%d/%m/%Y %H:%M")
        except ValueError:
            quando_br = quando
        itens.append((quando, ident, quando_br, texto))

    if EH_WINDOWS:
        dados = ps_json(f"""
@(Get-ScheduledTask -TaskName '{PREFIXO_TAREFA}*' -ErrorAction SilentlyContinue | ForEach-Object {{
    [pscustomobject]@{{ nome = $_.TaskName; texto = $_.Description; quando = [string]$_.Triggers[0].StartBoundary }}
}}) | ConvertTo-Json -Compress
""")
        for d in dados:
            adicionar(d.get("nome", ""), (d.get("quando") or "")[:19], d.get("texto") or "",
                      "%Y-%m-%dT%H:%M:%S")
    elif EH_MAC:
        for plist in glob.glob(os.path.join(PASTA_AGENTES_MAC, PREFIXO_AGENTE + "*.plist")):
            ident = os.path.basename(plist)[:-6]
            info = _ler_json(os.path.join(PASTA_LEMBRETES, ident + ".json"), {})
            adicionar(ident, info.get("quando", ""), info.get("texto", ""), "%Y-%m-%d %H:%M:%S")
    else:
        for timer in glob.glob(os.path.join(PASTA_UNIDADES, "lembrete-*.timer")):
            texto, quando = "", ""
            with open(timer, encoding="utf-8") as f:
                for linha in f:
                    if linha.startswith("Description=Lembrete: "):
                        texto = linha.split(": ", 1)[1].strip()
                    elif linha.startswith("OnCalendar="):
                        quando = linha.split("=", 1)[1].strip()
            adicionar(os.path.basename(timer)[:-6], quando, texto, "%Y-%m-%d %H:%M:%S")
    return [i[1:] for i in sorted(itens)]


def listar_lembretes():
    itens = _lembretes()
    if not itens:
        return "Nenhum lembrete agendado."
    return "Lembretes:\n" + "\n".join(f"{i}. {q} — {t}" for i, (_, q, t) in enumerate(itens, 1))


def cancelar_lembrete(qual):
    itens = _lembretes()
    qual = str(qual).strip()
    if qual.isdigit() and 1 <= int(qual) <= len(itens):
        escolhidos = [itens[int(qual) - 1]]
    else:
        escolhidos = [i for i in itens if sem_acento(qual) in sem_acento(i[2])]
    if not escolhidos:
        return "Nenhum lembrete encontrado com isso."
    if len(escolhidos) > 1:
        return "Vários lembretes correspondem, use o número:\n" + listar_lembretes()
    ident, quando, texto = escolhidos[0]
    if EH_WINDOWS:
        powershell(f"Unregister-ScheduledTask -TaskName {ps_str(ident)} "
                   "-Confirm:$false -ErrorAction SilentlyContinue")
        arquivos = [os.path.join(PASTA_LEMBRETES, ident + ".ps1")]
    elif EH_MAC:
        plist = os.path.join(PASTA_AGENTES_MAC, ident + ".plist")
        if rodar(["launchctl", "bootout", f"gui/{os.getuid()}/{ident}"]).returncode != 0:
            rodar(["launchctl", "unload", plist])
        arquivos = [plist] + [os.path.join(PASTA_LEMBRETES, ident + e) for e in (".sh", ".json")]
    else:
        _systemctl("disable", "--now", ident + ".timer")
        arquivos = [os.path.join(PASTA_UNIDADES, ident + ".timer"),
                    os.path.join(PASTA_UNIDADES, ident + ".service"),
                    os.path.join(PASTA_LEMBRETES, ident + ".sh")]
    for arq in arquivos:
        if os.path.exists(arq):
            os.remove(arq)
    if EH_LINUX:
        _systemctl("daemon-reload")
    return f"Lembrete cancelado: {quando} — {texto}"


# ============================================================================
# Visão: entender imagens com um modelo que enxerga
# ============================================================================
EXTENSOES_VISAO = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff")
ARQ_DESCRICOES = os.path.join(PASTA_DADOS, "descricoes_fotos.json")


def ollama_api(caminho, dados=None, timeout=900):
    req = urllib.request.Request(OLLAMA.rsplit("/api/", 1)[0] + caminho,
                                 data=json.dumps(dados).encode() if dados else None,
                                 headers={"Content-Type": "application/json"})
    local = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with local.open(req, timeout=timeout) as r:
        return json.load(r)


def modelo_instalado(nome):
    try:
        nomes = {m["name"] for m in ollama_api("/api/tags").get("models", [])}
    except Exception:
        return False
    return nome in nomes or f"{nome}:latest" in nomes


def imagem_base64(caminho, tamanho=1024):
    """Reduz a imagem (fotos de câmera são enormes) e devolve em base64."""
    import base64
    try:
        import gi
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf
        imagem = GdkPixbuf.Pixbuf.new_from_file_at_scale(caminho, tamanho, tamanho, True)
        ok, dados = imagem.save_to_bufferv("jpeg", ["quality"], ["85"])
        if ok:
            return base64.b64encode(dados).decode()
    except Exception:
        pass
    with open(caminho, "rb") as f:
        return base64.b64encode(f.read()).decode()


def olhar(caminho, pergunta):
    resposta = ollama_api("/api/chat", {
        "model": MODELO_VISAO, "stream": False, "options": {"num_ctx": 4096},
        "messages": [{"role": "user", "images": [imagem_base64(caminho)],
                      "content": pergunta + " Responda em português do Brasil."}]})
    return resposta["message"]["content"].strip()


def aviso_visao():
    return (f"Erro: o modelo de visão {MODELO_VISAO} não está instalado. O usuário "
            f"precisa liberar a internet do Ollama e rodar: ollama pull {MODELO_VISAO}")


@ferramenta("Olha uma imagem e responde sobre ela: descrever, ler texto, identificar "
            "objetos, pessoas, lugares.",
            {"arquivo": ("string", "Caminho da imagem"),
             "pergunta": ("string", "O que perguntar sobre a imagem")}, ["arquivo"],
            ativa=bool(MODELO_VISAO))
def descrever_imagem(arquivo, pergunta="Descreva esta imagem em detalhes."):
    caminho = caminho_seguro(arquivo)
    if not os.path.isfile(caminho):
        return f"Erro: {caminho} não existe."
    if not caminho.lower().endswith(EXTENSOES_VISAO):
        return "Erro: formato de imagem não suportado (use JPG, PNG, WEBP...)."
    if not modelo_instalado(MODELO_VISAO):
        return aviso_visao()
    print(cinza(f"     👁️  Olhando a imagem com {MODELO_VISAO}... (pode demorar)"))
    return olhar(caminho, pergunta)


@ferramenta("Procura fotos pelo que aparece NELAS (ex: 'cachorro na praia', 'bolo de "
            "aniversário'). Na primeira vez analisa as fotos uma a uma (é lento); depois "
            "fica rápido porque guarda as descrições.",
            {"descricao": ("string", "O que aparece nas fotos procuradas"),
             "pasta": ("string", "Pasta das fotos. Padrão: Imagens"),
             "limite": ("number", "Quantas fotos novas analisar agora (padrão 20)")},
            ["descricao"], ativa=bool(MODELO_VISAO) and BUSCA_FOTOS)
def buscar_fotos_por_conteudo(descricao, pasta="", limite=20):
    raiz = caminho_seguro(pasta or pasta_usuario("PICTURES", "Imagens"))
    if not modelo_instalado(MODELO_VISAO):
        return aviso_visao()
    try:
        with open(ARQ_DESCRICOES, encoding="utf-8") as f:
            cache = json.load(f)
    except (OSError, ValueError):
        cache = {}
    fotos = []
    for atual, subpastas, arquivos in os.walk(raiz):
        subpastas[:] = [s for s in subpastas if not s.startswith(".")]
        fotos += [os.path.join(atual, a) for a in arquivos if a.lower().endswith(EXTENSOES_VISAO)]
    fotos.sort(key=lambda c: os.path.getmtime(c), reverse=True)
    pendentes = [c for c in fotos
                 if cache.get(c, {}).get("mtime") != os.path.getmtime(c)][:int(limite or 20)]
    for i, caminho in enumerate(pendentes, 1):
        print(f"\r\033[K" + cinza(f"     👁️  Analisando foto {i}/{len(pendentes)}: "
                                   f"{os.path.basename(caminho)[:40]}"), end="", flush=True)
        try:
            desc = olhar(caminho, "Liste numa linha o que aparece nesta foto: pessoas, "
                                  "animais, objetos, lugar, ocasião, cores e textos visíveis.")
        except Exception as erro:
            desc = f"(erro: {erro})"
        cache[caminho] = {"mtime": os.path.getmtime(caminho), "desc": desc}
        os.makedirs(PASTA_DADOS, exist_ok=True)
        with open(ARQ_DESCRICOES, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    if pendentes:
        print("\r\033[K", end="")
    vazias = {"de", "da", "do", "das", "dos", "com", "uma", "um", "na", "no", "em",
              "foto", "fotos", "que", "tem", "aparece", "e", "a", "o"}
    termos = [t for t in re.findall(r"\w+", sem_acento(descricao)) if t not in vazias and len(t) > 2]
    pontuadas = []
    for caminho in fotos:
        desc = cache.get(caminho, {}).get("desc")
        if desc:
            pontos = sum(1 for t in termos if t[:5] in sem_acento(desc))
            if pontos:
                pontuadas.append((pontos, caminho, desc))
    pontuadas.sort(reverse=True)
    faltam = sum(1 for c in fotos if c not in cache)
    rodape = (f"\n({faltam} fotos ainda não foram analisadas; peça de novo para analisar mais.)"
              if faltam else "")
    if not pontuadas:
        return "Nenhuma foto analisada corresponde à descrição." + rodape
    return ("Fotos encontradas:\n" + "\n".join(f"{c}\n   {d[:150]}" for _, c, d in pontuadas[:15])
            + rodape)


# ============================================================================
# Sistema
# ============================================================================
def data_hoje():
    dias = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
            "sexta-feira", "sábado", "domingo"]
    hoje = datetime.date.today()
    return f"{dias[hoje.weekday()]}, {hoje:%d/%m/%Y}"


@ferramenta("Informa data e hora atuais.")
def data_hora():
    dias = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
            "sexta-feira", "sábado", "domingo"]
    agora = datetime.datetime.now()
    return f"{dias[agora.weekday()]}, {agora:%d/%m/%Y %H:%M}"


def _psutil():
    """psutil mede CPU, RAM, bateria e processos em qualquer sistema (instalado pelo instalador)."""
    try:
        import psutil
        return psutil
    except ImportError:
        return None


def _cpu_total():
    with open("/proc/stat") as f:
        valores = [int(v) for v in f.readline().split()[1:]]
    return sum(valores), valores[3] + valores[4]  # total, ocioso


def _processos(nome):
    pids = []
    for pid in os.listdir("/proc"):
        if pid.isdigit():
            try:
                with open(f"/proc/{pid}/comm") as f:
                    if f.read().strip() == nome:
                        pids.append(pid)
            except OSError:
                pass
    return pids


def _tempo_cpu(pid):
    try:
        with open(f"/proc/{pid}/stat") as f:
            campos = f.read().rsplit(")", 1)[1].split()
        return int(campos[11]) + int(campos[12])  # utime + stime
    except (OSError, IndexError):
        return 0


def _ram_mb(pid):
    try:
        with open(f"/proc/{pid}/status") as f:
            for linha in f:
                if linha.startswith("VmRSS:"):
                    return int(linha.split()[1]) / 1024
    except OSError:
        pass
    return 0


def _memoria_gb():
    """(total, usada) em GB."""
    ps = _psutil()
    if ps:
        m = ps.virtual_memory()
        return m.total / 1024 ** 3, (m.total - m.available) / 1024 ** 3
    if EH_LINUX:
        mem = {}
        with open("/proc/meminfo") as f:
            for linha in f:
                chave, valor = linha.split(":")
                mem[chave] = int(valor.split()[0]) / 1024 / 1024
        return mem["MemTotal"], mem["MemTotal"] - mem["MemAvailable"]
    if EH_MAC:
        total = int(rodar(["sysctl", "-n", "hw.memsize"]).stdout.strip() or 0) / 1024 ** 3
        return total, 0.0
    if EH_WINDOWS:
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        estado = MEMORYSTATUSEX()
        estado.dwLength = ctypes.sizeof(estado)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(estado))
        return (estado.ullTotalPhys / 1024 ** 3,
                (estado.ullTotalPhys - estado.ullAvailPhys) / 1024 ** 3)
    return 0.0, 0.0


def _uso_processos_psutil(ps):
    """CPU total e uso da IA e do Lumero medidos com o psutil."""
    grupos = {"IA (Ollama)": [], "Este assistente": []}
    for proc in ps.process_iter(["name", "pid"]):
        nome = (proc.info.get("name") or "").lower()
        if nome.startswith("ollama") or nome == "llama-server" or nome.startswith("llama-server"):
            grupos["IA (Ollama)"].append(proc)
        elif proc.info.get("pid") == os.getpid():
            grupos["Este assistente"].append(proc)
    for procs in grupos.values():
        for proc in procs:
            try:
                proc.cpu_percent(None)
            except ps.Error:
                pass
    ps.cpu_percent(None)
    time.sleep(0.7)
    total = ps.cpu_percent(None)
    nucleos = ps.cpu_count() or 1
    resultado = {}
    for grupo, procs in grupos.items():
        cpu, ram = 0.0, 0.0
        for proc in procs:
            try:
                cpu += proc.cpu_percent(None) / nucleos
                ram += proc.memory_info().rss / 1024 / 1024
            except ps.Error:
                pass
        resultado[grupo] = (cpu, ram, bool(procs), [str(p.pid) for p in procs])
    return total, resultado


def uso_recursos():
    ps = _psutil()
    total_gb, usada_gb = _memoria_gb()
    if ps:
        cpu_total, grupos = _uso_processos_psutil(ps)
    elif EH_LINUX:
        pids = {"IA (Ollama)": _processos("ollama"), "Este assistente": [str(os.getpid())]}
        total1, ocioso1 = _cpu_total()
        antes = {g: sum(_tempo_cpu(p) for p in lista) for g, lista in pids.items()}
        time.sleep(0.7)
        total2, ocioso2 = _cpu_total()
        dt = max(1, total2 - total1)
        cpu_total = 100 * (1 - (ocioso2 - ocioso1) / dt)
        grupos = {g: (100 * (sum(_tempo_cpu(p) for p in lista) - antes[g]) / dt,
                      sum(_ram_mb(p) for p in lista), bool(lista), lista)
                  for g, lista in pids.items()}
    else:
        return ("Para medir CPU e RAM, o usuário pode instalar: " + como_instalar_python("psutil")
                + f"\nRAM total: {total_gb:.1f} GB")

    linhas = [f"CPU total: {cpu_total:.0f}% ({os.cpu_count()} núcleos)"]
    if total_gb:
        linhas.append(f"RAM total: {usada_gb:.1f} de {total_gb:.1f} GB "
                      f"({100 * usada_gb / total_gb:.0f}%)")
    for grupo, (cpu, ram, rodando, _) in grupos.items():
        if not rodando:
            linhas.append(f"{grupo}: não está rodando")
            continue
        ram_txt = f"{ram / 1024:.1f} GB" if ram >= 1024 else f"{ram:.0f} MB"
        porcentagem = f" ({100 * ram / 1024 / total_gb:.0f}% da RAM)" if total_gb else ""
        linhas.append(f"{grupo}: CPU {cpu:.0f}%, RAM {ram_txt}{porcentagem}")

    if shutil.which("nvidia-smi"):
        r = rodar(["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,"
                   "memory.total", "--format=csv,noheader,nounits"], timeout=10)
        for linha in r.stdout.strip().splitlines():
            try:
                nome, uso, usada_gpu, total_gpu = [x.strip() for x in linha.split(",")]
            except ValueError:
                continue
            linhas.append(f"GPU {nome}: {uso}% de uso, {usada_gpu} de {total_gpu} MB de memória")
        r = rodar(["nvidia-smi", "--query-compute-apps=pid,used_memory",
                   "--format=csv,noheader,nounits"], timeout=10)
        pids_ia = set(grupos["IA (Ollama)"][3])
        mem_ia = 0
        for l in r.stdout.strip().splitlines():
            partes = [x.strip() for x in l.split(",")]
            if len(partes) == 2 and partes[0] in pids_ia and partes[1].isdigit():
                mem_ia += int(partes[1])
        linhas.append(f"IA na GPU NVIDIA: {mem_ia} MB" if mem_ia
                      else "IA na GPU NVIDIA: não está usando (roda na CPU)")
    elif EH_MAC and platform.machine() == "arm64":
        linhas.append("GPU: Apple Silicon (o Ollama usa a GPU integrada automaticamente)")

    if shutil.which("ollama") or caminho_ollama():
        r = rodar([caminho_ollama() or "ollama", "ps"], timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            linhas.append("Modelos carregados (ollama ps):\n" + r.stdout.strip())
    return "\n".join(linhas)


def _bateria():
    """(porcentagem, estado em português) ou None se não tiver bateria."""
    ps = _psutil()
    if ps and hasattr(ps, "sensors_battery"):
        try:
            b = ps.sensors_battery()
        except Exception:
            b = None
        if b:
            estado = ("na tomada" if b.power_plugged else "na bateria")
            if b.power_plugged and b.percent >= 99:
                estado = "carregada"
            return round(b.percent), estado
    if EH_LINUX:
        for bat in ("BAT0", "BAT1", "BAT2"):
            base = f"/sys/class/power_supply/{bat}"
            try:
                with open(f"{base}/capacity") as f:
                    carga = f.read().strip()
                with open(f"{base}/status") as f:
                    status = f.read().strip()
            except OSError:
                continue
            traducao = {"Charging": "carregando", "Discharging": "na bateria",
                        "Full": "carregada", "Not charging": "na tomada"}
            return carga, traducao.get(status, status)
    if EH_MAC:
        saida = rodar(["pmset", "-g", "batt"]).stdout
        achado = re.search(r"(\d+)%;\s*([^;]+);", saida)
        if achado:
            traducao = {"charging": "carregando", "discharging": "na bateria",
                        "charged": "carregada", "finishing charge": "carregando",
                        "AC attached": "na tomada"}
            return achado.group(1), traducao.get(achado.group(2).strip(), achado.group(2).strip())
    return None


def info_sistema():
    linhas = []
    bateria = _bateria()
    if bateria:
        linhas.append(f"Bateria: {bateria[0]}% ({bateria[1]})")
    total, usada = _memoria_gb()
    if total:
        linhas.append(f"RAM: {usada:.1f} GB usados de {total:.1f} GB")
    disco = shutil.disk_usage(HOME)
    linhas.append(f"Disco: {disco.free / 1e9:.0f} GB livres de {disco.total / 1e9:.0f} GB")
    return "\n".join(linhas)


VOLUME_CS = r"""
using System.Runtime.InteropServices;
[Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioEndpointVolume {
  int f(); int g(); int h(); int i();
  int SetMasterVolumeLevelScalar(float fLevel, System.Guid pguidEventContext);
  int j();
  int GetMasterVolumeLevelScalar(out float pfLevel);
  int k(); int l(); int m(); int n();
  int SetMute([MarshalAs(UnmanagedType.Bool)] bool bMute, System.Guid pguidEventContext);
  int GetMute(out bool pbMute);
}
[Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice { int Activate(ref System.Guid id, int clsCtx, int activationParams, out IAudioEndpointVolume aev); }
[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator { int f(); int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice endpoint); }
[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class MMDeviceEnumeratorComObject { }
public class VolumeLumero {
  static IAudioEndpointVolume Vol() {
    var enumerador = new MMDeviceEnumeratorComObject() as IMMDeviceEnumerator;
    IMMDevice dispositivo = null;
    Marshal.ThrowExceptionForHR(enumerador.GetDefaultAudioEndpoint(0, 1, out dispositivo));
    IAudioEndpointVolume volume = null;
    var id = typeof(IAudioEndpointVolume).GUID;
    Marshal.ThrowExceptionForHR(dispositivo.Activate(ref id, 23, 0, out volume));
    return volume;
  }
  public static float Volume {
    get { float v = -1; Marshal.ThrowExceptionForHR(Vol().GetMasterVolumeLevelScalar(out v)); return v; }
    set { Marshal.ThrowExceptionForHR(Vol().SetMasterVolumeLevelScalar(value, System.Guid.Empty)); }
  }
  public static bool Mudo {
    get { bool m; Marshal.ThrowExceptionForHR(Vol().GetMute(out m)); return m; }
    set { Marshal.ThrowExceptionForHR(Vol().SetMute(value, System.Guid.Empty)); }
  }
}
"""


@ferramenta("Ajusta o volume do som: número de 0 a 100, ou 'mudo' para "
            "silenciar/desilenciar.",
            {"nivel": ("string", "Número de 0 a 100, ou 'mudo'")}, ["nivel"])
def ajustar_volume(nivel):
    nivel = str(nivel).strip().lower().rstrip("%")
    mudo = nivel in ("mudo", "mute", "silenciar", "desmutar", "desilenciar")
    valor = 0 if mudo else max(0, min(100, int(float(nivel))))
    if EH_WINDOWS:
        acao = ("[VolumeLumero]::Mudo = -not [VolumeLumero]::Mudo; [VolumeLumero]::Mudo" if mudo
                else f"[VolumeLumero]::Mudo = $false; [VolumeLumero]::Volume = {valor / 100}")
        codigo, saida, erros = powershell(f"Add-Type -TypeDefinition @'\n{VOLUME_CS}\n'@\n{acao}")
        if codigo != 0:
            return f"Erro ao mudar o volume: {erros[:300]}"
        if mudo:
            return "Som silenciado." if saida.strip().lower() == "true" else "Som ligado de novo."
    elif EH_MAC:
        script = ("set volume output muted not (output muted of (get volume settings))" if mudo
                  else f"set volume output volume {valor} without output muted")
        codigo, _, erros = osascript(script)
        if codigo:
            return f"Erro ao mudar o volume: {erros[:300]}"
    elif shutil.which("wpctl"):
        alvo = "@DEFAULT_AUDIO_SINK@"
        r = rodar(["wpctl", "set-mute", alvo, "toggle"] if mudo
                  else ["wpctl", "set-volume", alvo, f"{valor}%"])
        if r.returncode:
            return f"Erro ao mudar o volume: {r.stderr.strip()[:300]}"
        if not mudo:
            rodar(["wpctl", "set-mute", alvo, "0"])
    elif shutil.which("pactl"):
        r = rodar(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"] if mudo
                  else ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{valor}%"])
        if r.returncode:
            return f"Erro ao mudar o volume: {r.stderr.strip()[:300]}"
    elif shutil.which("amixer"):
        rodar(["amixer", "-q", "set", "Master", "toggle" if mudo else f"{valor}%"])
    else:
        return "Erro: não achei o controle de som (wpctl, pactl ou amixer)."
    return "Som silenciado/desilenciado." if mudo else f"Volume ajustado para {valor}%."


# ============================================================================
# Ferramentas agrupadas (menos ferramentas = modelo pequeno se confunde menos)
# ============================================================================
@ferramenta("Abre um arquivo com o programa padrão (foto, PDF, vídeo...) ou uma pasta "
            "no gerenciador de arquivos.",
            {"caminho": ("string", "Caminho do arquivo ou da pasta, ex: ~/Downloads")},
            ["caminho"])
def abrir(caminho):
    if os.path.isdir(caminho_seguro(caminho)):
        return abrir_pasta(caminho)
    return abrir_arquivo(caminho)


def _confirmar_lixeira(args):
    return str(args.get("acao", "")).lower() == "apagar"


@ferramenta("Lixeira. acao='apagar' manda arquivos/pastas para a lixeira (use SEMPRE "
            "isto para apagar); acao='listar' mostra o que tem nela; acao='restaurar' "
            "devolve um arquivo para o lugar original.",
            {"acao": ("string", "apagar, listar ou restaurar"),
             "caminhos": ("string", "Para apagar: um ou mais caminhos, um por linha"),
             "nome": ("string", "Para restaurar: nome ou parte do caminho original")},
            ["acao"], confirmar=_confirmar_lixeira)
def lixeira(acao, caminhos="", nome=""):
    acao = str(acao).lower()
    if acao == "apagar":
        return mover_para_lixeira(caminhos)
    if acao == "listar":
        return listar_lixeira()
    if acao == "restaurar":
        return restaurar_da_lixeira(nome or caminhos)
    return "Erro: acao deve ser apagar, listar ou restaurar."


@ferramenta("Memória permanente (vale para todas as conversas). acao='lembrar' guarda um "
            "fato que o usuário pediu para lembrar; acao='esquecer' apaga fatos que "
            "contêm o texto; acao='ver' mostra tudo.",
            {"acao": ("string", "lembrar, esquecer ou ver"),
             "texto": ("string", "O fato a lembrar, ou o trecho a esquecer")}, ["acao"])
def memoria(acao, texto=""):
    acao = str(acao).lower()
    if acao == "lembrar":
        return lembrar_fato(texto)
    if acao == "esquecer":
        return esquecer_fato(texto)
    if acao == "ver":
        return ver_memoria()
    return "Erro: acao deve ser lembrar, esquecer ou ver."


@ferramenta("Lembretes que aparecem como notificação na hora certa, mesmo com o "
            "assistente fechado. acao='criar' (com mensagem e minutos OU horario, ex: "
            "'15:30', '20/11 09:00'); acao='listar'; acao='cancelar' (com qual = número "
            "ou parte do texto).",
            {"acao": ("string", "criar, listar ou cancelar"),
             "mensagem": ("string", "Texto do lembrete"),
             "minutos": ("number", "Daqui a quantos minutos"),
             "horario": ("string", "Horário ou data e horário"),
             "qual": ("string", "Para cancelar: número ou parte do texto")}, ["acao"])
def lembretes(acao, mensagem="", minutos=0, horario="", qual=""):
    acao = str(acao).lower()
    if acao == "criar":
        if not mensagem:
            return "Erro: informe a mensagem do lembrete."
        return criar_lembrete(mensagem, minutos, horario)
    if acao == "listar":
        return listar_lembretes()
    if acao == "cancelar":
        return cancelar_lembrete(qual or mensagem)
    return "Erro: acao deve ser criar, listar ou cancelar."


# ============================================================================
# Cuidados com o notebook: temperatura, energia e o próprio Ollama
# ============================================================================
def temperatura_cpu():
    """Temperatura do processador em °C (None se não der para ler).
    O Linux mostra sem senha; Windows e Mac não deixam ler sem administrador."""
    if not EH_LINUX:
        return None
    for hwmon in glob.glob("/sys/class/hwmon/hwmon*"):
        try:
            with open(os.path.join(hwmon, "name")) as f:
                nome = f.read().strip()
            if nome not in ("coretemp", "k10temp", "zenpower"):
                continue
            for rotulo in glob.glob(os.path.join(hwmon, "temp*_label")):
                with open(rotulo) as f:
                    if f.read().strip().startswith(("Package", "Tctl", "Tdie")):
                        with open(rotulo.replace("_label", "_input")) as g:
                            return int(g.read()) / 1000
        except (OSError, ValueError):
            continue
    for zona in glob.glob("/sys/class/thermal/thermal_zone*"):
        try:
            with open(os.path.join(zona, "type")) as f:
                if f.read().strip() in ("x86_pkg_temp", "cpu-thermal", "cpu_thermal"):
                    with open(os.path.join(zona, "temp")) as g:
                        return int(g.read()) / 1000
        except (OSError, ValueError):
            continue
    return None


def turbo_ligado():
    if not EH_LINUX:
        return None
    for arquivo, ligado in (("/sys/devices/system/cpu/intel_pstate/no_turbo", "0"),
                            ("/sys/devices/system/cpu/cpufreq/boost", "1")):
        try:
            with open(arquivo) as f:
                return f.read().strip() == ligado
        except OSError:
            continue
    return None


def esperar_esfriar():
    """Se o processador estiver quente demais, espera ele esfriar antes de continuar."""
    temp = temperatura_cpu()
    if temp is None or temp < TEMPERATURA_PAUSA:
        return
    spinner = Spinner(f"Esperando o processador esfriar ({temp:.0f}°C)").iniciar()
    inicio = time.time()
    try:
        while time.time() - inicio < 120:
            time.sleep(2)
            temp = temperatura_cpu() or 0
            spinner.texto = f"Esperando o processador esfriar ({temp:.0f}°C)"
            if temp <= TEMPERATURA_RETOMA:
                break
    finally:
        spinner.parar()


# ----------------------------------------------------------------------------
# Ollama: liga quando o Lumero abre e desliga quando ele fecha
#   Linux com o serviço do instalador: systemctl (liberado sem senha pelo polkit)
#   Windows, Mac e Linux sem serviço: "ollama serve" escondido, só enquanto o Lumero roda
# ----------------------------------------------------------------------------
# se o assistente reiniciou sozinho (autoedição), ele continua "dono" do Ollama
OLLAMA_LIGADO_POR_MIM = {"sim": os.environ.get("LUMERO_DESLIGAR_OLLAMA") == "1",
                         "pid": int(os.environ.get("LUMERO_OLLAMA_PID") or 0)}
OLLAMA_AMBIENTE = {             # mesmas economias do serviço do Linux
    "OLLAMA_HOST": "127.0.0.1:11434",
    "OLLAMA_KEEP_ALIVE": "30m",
    "OLLAMA_MAX_LOADED_MODELS": "1",
    "OLLAMA_NUM_PARALLEL": "1",
}


def caminho_ollama():
    """Onde está o programa ollama (também nos lugares onde os instaladores costumam pôr)."""
    achado = shutil.which("ollama")
    if achado:
        return achado
    candidatos = []
    if EH_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or os.path.join(HOME, "AppData", "Local")
        candidatos = [os.path.join(base, "Programs", "Ollama", "ollama.exe"),
                      os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                                   "Ollama", "ollama.exe")]
    elif EH_MAC:
        candidatos = ["/Applications/Ollama.app/Contents/Resources/ollama",
                      os.path.join(HOME, "Applications/Ollama.app/Contents/Resources/ollama"),
                      "/opt/homebrew/bin/ollama", "/usr/local/bin/ollama"]
    else:
        candidatos = ["/usr/local/bin/ollama", "/usr/bin/ollama"]
    return next((c for c in candidatos if os.path.exists(c)), "")


def ollama_responde():
    try:
        ollama_api("/api/version", timeout=3)
        return True
    except Exception:
        return False


def _ollama_servico_systemd():
    return (EH_LINUX and shutil.which("systemctl") is not None
            and rodar(["systemctl", "cat", "ollama.service"], timeout=10).returncode == 0)


def _ligar_ollama_direto():
    programa = caminho_ollama()
    if not programa:
        return "O Ollama não está instalado. Rode o instalador do Lumero de novo."
    os.makedirs(PASTA_DADOS, exist_ok=True)
    log = open(os.path.join(PASTA_DADOS, "ollama.log"), "ab")
    ambiente = {**os.environ, **OLLAMA_AMBIENTE, "OLLAMA_CONTEXT_LENGTH": str(CONTEXTO)}
    extra = ({"creationflags": SEM_JANELA | 0x00000200} if EH_WINDOWS  # NEW_PROCESS_GROUP
             else {"start_new_session": True})
    proc = subprocess.Popen([programa, "serve"], stdout=log, stderr=log,
                            stdin=subprocess.DEVNULL, env=ambiente, **extra)
    OLLAMA_LIGADO_POR_MIM["pid"] = proc.pid
    return None


def garantir_ollama():
    """Liga o Ollama se ele estiver desligado. Devolve uma mensagem de erro, ou None se
    estiver tudo certo."""
    if ollama_responde():
        return None
    local = urllib.parse.urlparse(OLLAMA).hostname in ("127.0.0.1", "localhost")
    if not (GERENCIAR_OLLAMA and local):
        return "Não consegui falar com o Ollama."
    spinner = Spinner("Ligando o Ollama").iniciar()
    try:
        if _ollama_servico_systemd():
            r = rodar(["systemctl", "start", "ollama"], timeout=60)
            if r.returncode != 0:
                return f"Não consegui ligar o Ollama: {r.stderr.strip()[:200]}"
        else:
            erro = _ligar_ollama_direto()
            if erro:
                return erro
        for _ in range(60):
            if ollama_responde():
                OLLAMA_LIGADO_POR_MIM["sim"] = True
                return None
            time.sleep(0.5)
        return "O Ollama foi ligado, mas não respondeu."
    finally:
        spinner.parar()


def desligar_ollama():
    if not (GERENCIAR_OLLAMA and OLLAMA_LIGADO_POR_MIM["sim"]):
        return
    pid = OLLAMA_LIGADO_POR_MIM["pid"]
    if pid:  # foi o Lumero que rodou "ollama serve": encerra ele e os modelos que abriu
        if EH_WINDOWS:
            rodar(["taskkill", "/PID", str(pid), "/T", "/F"], timeout=20)
        else:
            try:
                os.killpg(pid, signal.SIGTERM)
            except (OSError, AttributeError):
                pass
    elif _ollama_servico_systemd():
        rodar(["systemctl", "stop", "ollama"], timeout=60)


def _saude_bateria():
    """Capacidade atual comparada com a original, em %."""
    if EH_LINUX:
        for bat in ("BAT0", "BAT1", "BAT2"):
            base = f"/sys/class/power_supply/{bat}"
            for cheia, projeto in (("energy_full", "energy_full_design"),
                                   ("charge_full", "charge_full_design")):
                try:
                    with open(f"{base}/{cheia}") as f:
                        a = int(f.read())
                    with open(f"{base}/{projeto}") as f:
                        b = int(f.read())
                    return 100 * a / b
                except (OSError, ValueError, ZeroDivisionError):
                    continue
    elif EH_MAC:
        saida = rodar(["system_profiler", "SPPowerDataType"], timeout=30).stdout
        achado = re.search(r"Maximum Capacity:\s*(\d+)%", saida)
        if achado:
            return float(achado.group(1))
    elif EH_WINDOWS:
        _, saida, _ = powershell(
            "$a = (Get-CimInstance -Namespace root\\wmi -ClassName BatteryFullChargedCapacity "
            "-ErrorAction SilentlyContinue | Select-Object -First 1).FullChargedCapacity\n"
            "$b = (Get-CimInstance -Namespace root\\wmi -ClassName BatteryStaticData "
            "-ErrorAction SilentlyContinue | Select-Object -First 1).DesignedCapacity\n"
            "if ($a -and $b) { [math]::Round(100 * $a / $b) }")
        if saida.strip().replace(",", ".").replace(".", "", 1).isdigit():
            return float(saida.strip().replace(",", "."))
    return None


@ferramenta("Mostra o estado do computador: temperatura, uso de CPU e RAM, quanto a IA "
            "está usando, bateria, modo de energia e disco.")
def estado_do_pc():
    linhas = [f"Sistema: {NOME_SISTEMA}"]
    temp = temperatura_cpu()
    if temp is not None:
        alerta = " ⚠️ quente" if temp >= TEMPERATURA_PAUSA else ""
        linhas.append(f"Temperatura do processador: {temp:.0f}°C{alerta}")
    if EH_LINUX:
        for hwmon in glob.glob("/sys/class/hwmon/hwmon*"):
            try:
                with open(os.path.join(hwmon, "fan1_input")) as f:
                    linhas.append(f"Ventoinha: {int(f.read())} RPM")
                    break
            except (OSError, ValueError):
                continue
    turbo = turbo_ligado()
    if turbo is not None:
        linhas.append("Turbo do processador: " + ("ligado" if turbo else
                      "desligado (modo econômico da IA)"))
    modo = _modo_energia_atual()
    if modo:
        linhas.append(f"Modo de energia: {modo}")
    saude = _saude_bateria()
    if saude:
        linhas.append(f"Saúde da bateria: {saude:.0f}% da capacidade original"
                      + (" (precisa trocar)" if saude < 40 else ""))
    linhas += [l for l in info_sistema().splitlines() if not l.startswith("RAM:")]
    linhas.append(uso_recursos())
    return "\n".join(linhas)


MODOS_ENERGIA_PT = {"power-saver": "economia", "balanced": "equilibrado",
                    "performance": "desempenho"}
# Windows: planos clássicos (powercfg) e modos do Windows 11 (sobreposição)
PLANOS_WINDOWS = {"power-saver": "SCHEME_MAX", "balanced": "SCHEME_BALANCED",
                  "performance": "SCHEME_MIN"}
SOBREPOSICAO_WINDOWS = {"power-saver": "961cc777-2547-4f9d-8174-7d86181b8a7a",
                        "balanced": "00000000-0000-0000-0000-000000000000",
                        "performance": "ded574b5-45a0-4f42-8737-46345c09c238"}


def _modo_energia_atual():
    if EH_LINUX and shutil.which("powerprofilesctl"):
        atual = rodar(["powerprofilesctl", "get"]).stdout.strip()
        return MODOS_ENERGIA_PT.get(atual, atual)
    if EH_MAC:
        saida = rodar(["pmset", "-g"]).stdout
        achado = re.search(r"lowpowermode\s+(\d)", saida)
        if achado:
            return "economia (Modo de Pouca Energia)" if achado.group(1) == "1" else "normal"
    if EH_WINDOWS:
        saida = rodar(["powercfg", "/getactivescheme"]).stdout
        achado = re.search(r"\(([^)]+)\)", saida)
        return achado.group(1) if achado else ""
    return ""


@ferramenta("Mostra ou muda o modo de energia do computador: economia (mais fresco e "
            "silencioso), equilibrado ou desempenho.",
            {"modo": ("string", "economia, equilibrado ou desempenho (vazio = só mostrar)")})
def modo_energia(modo=""):
    if not modo:
        atual = _modo_energia_atual()
        return f"Modo de energia atual: {atual}" if atual else "Não consegui ler o modo de energia."
    alvo = {"economia": "power-saver", "economico": "power-saver", "equilibrado": "balanced",
            "normal": "balanced", "desempenho": "performance"}.get(sem_acento(modo), modo)
    if alvo not in MODOS_ENERGIA_PT:
        return "Erro: use economia, equilibrado ou desempenho."
    if EH_LINUX:
        if not shutil.which("powerprofilesctl"):
            return ("Erro: powerprofilesctl não encontrado (instale o power-profiles-daemon "
                    "ou o tuned-ppd).")
        r = rodar(["powerprofilesctl", "set", alvo])
        if r.returncode != 0:
            return f"Erro: {r.stderr.strip()[:200]}"
    elif EH_MAC:  # o Modo de Pouca Energia pede a senha de administrador
        resultado = _admin_mac(f"pmset -a lowpowermode {1 if alvo == 'power-saver' else 0}")
        if not resultado.startswith("Código de saída: 0"):
            return resultado
        if alvo == "performance":
            return "Modo de Pouca Energia desligado (o Mac já usa o desempenho máximo)."
    elif EH_WINDOWS:
        r = rodar(["powercfg", "/overlaysetactive", SOBREPOSICAO_WINDOWS[alvo]])
        if r.returncode != 0:  # Windows 10 ou plano personalizado: troca o plano inteiro
            r = rodar(["powercfg", "/setactive", PLANOS_WINDOWS[alvo]])
        if r.returncode != 0:
            return f"Erro: o Windows não aceitou esse modo. {r.stdout.strip()[:200]}"
    return f"Modo de energia: {MODOS_ENERGIA_PT.get(alvo, alvo)}."


@ferramenta("Ajusta o brilho da tela de 0 a 100.",
            {"nivel": ("number", "Brilho de 0 a 100")}, ["nivel"])
def ajustar_brilho(nivel):
    valor = max(5, min(100, int(float(nivel))))  # nunca deixa a tela totalmente preta
    if EH_WINDOWS:
        codigo, _, erros = powershell(
            "Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods "
            "-ErrorAction Stop | Invoke-CimMethod -MethodName WmiSetBrightness "
            f"-Arguments @{{Timeout=1; Brightness={valor}}} | Out-Null")
        if codigo:
            return "Erro: o Windows só muda o brilho de telas de notebook. " + erros[:150]
    elif EH_MAC:
        if not shutil.which("brightness"):
            return ("O macOS não tem um comando de brilho. O usuário pode instalar com "
                    "'brew install brightness' (ou usar as teclas de brilho).")
        r = rodar(["brightness", f"{valor / 100:.2f}"])
        if r.returncode:
            return f"Erro ao mudar o brilho: {r.stderr.strip()[:200]}"
    else:
        r = rodar(["gdbus", "call", "--session", "--dest", "org.gnome.SettingsDaemon.Power",
                   "--object-path", "/org/gnome/SettingsDaemon/Power", "--method",
                   "org.freedesktop.DBus.Properties.Set", "org.gnome.SettingsDaemon.Power.Screen",
                   "Brightness", f"<int32 {valor}>"])
        if r.returncode != 0 and shutil.which("brightnessctl"):
            r = rodar(["brightnessctl", "set", f"{valor}%"])
        if r.returncode != 0:
            kde = shutil.which("qdbus6") or shutil.which("qdbus")
            if kde:
                caminho = "/org/kde/Solid/PowerManagement/Actions/BrightnessControl"
                servico = "org.kde.Solid.PowerManagement"
                maximo = rodar([kde, servico, caminho, "brightnessMax"]).stdout.strip()
                if maximo.isdigit():
                    r = rodar([kde, servico, caminho, "setBrightness",
                               str(int(int(maximo) * valor / 100))])
        if r.returncode != 0:
            return ("Erro ao mudar o brilho. Fora do GNOME/KDE o usuário pode instalar o "
                    "brightnessctl: " + como_instalar("brightnessctl"))
    return f"Brilho ajustado para {valor}%."


@ferramenta("Suspende, desliga, reinicia ou bloqueia o computador. Sempre pede "
            "confirmação ao usuário.",
            {"acao": ("string", "suspender, desligar, reiniciar ou bloquear")}, ["acao"],
            confirmar=True)
def energia(acao):
    if EH_WINDOWS:
        comandos = {"suspender": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
                    "desligar": ["shutdown", "/s", "/t", "0"],
                    "reiniciar": ["shutdown", "/r", "/t", "0"],
                    "bloquear": ["rundll32.exe", "user32.dll,LockWorkStation"]}
    elif EH_MAC:
        comandos = {"suspender": ["pmset", "sleepnow"],
                    "desligar": ["osascript", "-e", 'tell application "System Events" to shut down'],
                    "reiniciar": ["osascript", "-e", 'tell application "System Events" to restart'],
                    "bloquear": ["pmset", "displaysleepnow"]}
    else:
        comandos = {"suspender": ["systemctl", "suspend"], "desligar": ["systemctl", "poweroff"],
                    "reiniciar": ["systemctl", "reboot"],
                    "bloquear": ["loginctl", "lock-session"]}
    escolha = sem_acento(acao)
    comando = comandos.get(escolha)
    if not comando:
        return "Erro: acao deve ser suspender, desligar, reiniciar ou bloquear."
    if escolha != "bloquear":
        desligar_ollama()
    executar(comando)
    return f"Ok: {acao}."


# ============================================================================
# Mais ferramentas úteis
# ============================================================================
@ferramenta("Faz contas com precisão (modelos pequenos erram contas de cabeça). Aceita "
            "+ - * / ** %, parênteses e funções como sqrt, round, sin, cos, log, pi.",
            {"expressao": ("string", "Conta a fazer, ex: (1200 * 0.15) + 30 ou sqrt(2)")},
            ["expressao"])
def calcular(expressao):
    import ast
    import math
    import operator
    permitidos = {k: getattr(math, k) for k in ("sqrt", "sin", "cos", "tan", "log", "log10",
                                                "exp", "pi", "e", "floor", "ceil", "factorial")}
    permitidos.update(round=round, abs=abs, min=min, max=max)
    ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
           ast.FloorDiv: operator.floordiv, ast.USub: operator.neg, ast.UAdd: operator.pos}

    def avaliar(no):
        if isinstance(no, ast.Expression):
            return avaliar(no.body)
        if isinstance(no, ast.Constant) and isinstance(no.value, (int, float)):
            return no.value
        if isinstance(no, ast.BinOp) and type(no.op) in ops:
            esquerda, direita = avaliar(no.left), avaliar(no.right)
            if isinstance(no.op, ast.Pow) and abs(direita) > 1000:
                raise ValueError("expoente grande demais")
            return ops[type(no.op)](esquerda, direita)
        if isinstance(no, ast.UnaryOp) and type(no.op) in ops:
            return ops[type(no.op)](avaliar(no.operand))
        if isinstance(no, ast.Name) and no.id in permitidos:
            return permitidos[no.id]
        if isinstance(no, ast.Call) and isinstance(no.func, ast.Name) and no.func.id in permitidos:
            return permitidos[no.func.id](*[avaliar(a) for a in no.args])
        raise ValueError("só aceito números, operações e funções matemáticas")

    texto = str(expressao).replace(",", ".").replace("×", "*").replace("÷", "/").replace("^", "**")
    try:
        resultado = avaliar(ast.parse(texto, mode="eval"))
    except ZeroDivisionError:
        return "Erro: divisão por zero."
    except Exception as erro:
        return f"Erro na conta: {erro}"
    if isinstance(resultado, float) and resultado.is_integer() and abs(resultado) < 1e15:
        resultado = int(resultado)
    if isinstance(resultado, float):
        resultado = round(resultado, 10)
    return f"{expressao} = {resultado}"


@ferramenta("Previsão do tempo de uma cidade (agora e próximos 3 dias).",
            {"cidade": ("string", "Nome da cidade, ex: Campo Grande")}, ["cidade"],
            precisa_internet=True)
def previsao_tempo(cidade):
    url = "https://wttr.in/" + urllib.parse.quote(cidade) + "?format=j1&lang=pt"
    dados = json.loads(baixar(url)[0])
    agora = dados["current_condition"][0]
    descricao = (agora.get("lang_pt") or agora.get("weatherDesc") or [{}])[0].get("value", "")
    linhas = [f"{cidade} agora: {agora['temp_C']}°C (sensação {agora['FeelsLikeC']}°C), "
              f"{descricao.lower()}, umidade {agora['humidity']}%"]
    for dia in dados.get("weather", [])[:3]:
        data = datetime.datetime.strptime(dia["date"], "%Y-%m-%d").strftime("%d/%m")
        chuva = max(int(h.get("chanceofrain", 0)) for h in dia.get("hourly", [{}]))
        linhas.append(f"{data}: mín {dia['mintempC']}°C, máx {dia['maxtempC']}°C, "
                      f"chance de chuva até {chuva}%")
    return "\n".join(linhas)


@ferramenta("Área de transferência (copiar e colar). acao='ler' devolve o que o usuário "
            "copiou; acao='copiar' coloca um texto nela para o usuário colar.",
            {"acao": ("string", "ler ou copiar"),
             "texto": ("string", "Para copiar: o texto")}, ["acao"])
def area_transferencia(acao, texto=""):
    acao = str(acao).lower()
    if acao not in ("ler", "copiar"):
        return "Erro: acao deve ser ler ou copiar."
    if EH_WINDOWS:
        if acao == "ler":
            _, conteudo, _ = powershell("Get-Clipboard -Raw")
        else:
            codigo, _, erros = powershell(f"Set-Clipboard -Value {ps_str(texto)}")
            if codigo:
                return f"Erro ao copiar: {erros[:200]}"
    elif EH_MAC:
        if acao == "ler":
            conteudo = rodar(["pbpaste"], timeout=5).stdout
        else:
            rodar(["pbcopy"], timeout=5, input=str(texto))
    else:
        wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
        if acao == "ler":
            opcoes = ([["wl-paste", "--no-newline"]] if wayland else []) + [
                ["xclip", "-o", "-selection", "clipboard"], ["xsel", "--clipboard", "--output"]]
        else:
            opcoes = ([["wl-copy"]] if wayland else []) + [
                ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]
        comando = next((c for c in opcoes if shutil.which(c[0])), None)
        if not comando:
            return "Erro: instale o wl-clipboard: " + como_instalar(
                "wl-clipboard" if wayland else "xclip")
        r = rodar(comando, timeout=5, **({} if acao == "ler" else {"input": str(texto)}))
        conteudo = r.stdout
    if acao == "copiar":
        return "Texto copiado. O usuário já pode colar com " + ("Cmd+V." if EH_MAC else "Ctrl+V.")
    if not conteudo.strip():
        return "A área de transferência está vazia (ou tem uma imagem)."
    return conteudo[:6000] + ("\n[... cortado ...]" if len(conteudo) > 6000 else "")


# ============================================================================
# Ferramentas extras (carregadas sob demanda, por grupo)
# ============================================================================
def _sem_sobrescrever(caminho):
    """Se o arquivo já existe, acrescenta (2), (3)... ao nome."""
    if not os.path.exists(caminho):
        return caminho
    base, ext = os.path.splitext(caminho)
    n = 2
    while os.path.exists(f"{base} ({n}){ext}"):
        n += 1
    return f"{base} ({n}){ext}"


def _lista_de_arquivos(alvo, extensoes=None):
    """Aceita um arquivo, uma pasta ou vários caminhos (um por linha)."""
    arquivos = []
    for item in [c.strip() for c in re.split(r"[\n;]", str(alvo or "")) if c.strip()]:
        caminho = caminho_seguro(item)
        if os.path.isdir(caminho):
            for nome in sorted(os.listdir(caminho)):
                completo = os.path.join(caminho, nome)
                if os.path.isfile(completo) and not nome.startswith("."):
                    arquivos.append(completo)
        elif os.path.isfile(caminho):
            arquivos.append(caminho)
    if extensoes:
        arquivos = [a for a in arquivos if a.lower().endswith(tuple(extensoes))]
    return arquivos


# ---------------------------------------------------------------- mídia (ffmpeg)
_ENCODERS = {"lista": None}


def _encoder_video():
    if _ENCODERS["lista"] is None:
        _ENCODERS["lista"] = rodar(["ffmpeg", "-hide_banner", "-encoders"]).stdout
    for nome in ("libx264", "libopenh264", "h264_videotoolbox", "h264_mf", "h264_vaapi", "mpeg4"):
        if re.search(rf"\s{nome}\s", _ENCODERS["lista"]):
            return nome
    return "mpeg4"


def _rodar_ffmpeg(entrada_args, saida, descricao):
    # nice + 2 threads: não esquenta o notebook nem disputa com a IA
    comando = ((["nice", "-n", "10"] if shutil.which("nice") else [])
               + ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
               + entrada_args + ["-threads", "2", saida])
    extra = {"creationflags": SEM_JANELA | 0x00004000} if EH_WINDOWS else {}  # prioridade baixa
    spinner = Spinner(descricao).iniciar()
    try:
        r = subprocess.run(comando, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                           encoding="utf-8", errors="replace", **extra)
    except KeyboardInterrupt:
        return "O usuário interrompeu a conversão."
    finally:
        spinner.parar()
    if r.returncode != 0 or not os.path.exists(saida):
        return f"Erro do ffmpeg: {r.stderr.strip()[-400:]}"
    return f"Pronto: {saida} ({tamanho_legivel(os.path.getsize(saida))})"


def _segundos(texto):
    """'1:30' -> 90; '01:02:03' -> 3723; '45' -> 45."""
    partes = [float(p) for p in str(texto).replace(",", ".").split(":")]
    total = 0.0
    for p in partes:
        total = total * 60 + p
    return total


@ferramenta("Vídeo e áudio (ffmpeg). acao: 'info' (duração, resolução), 'reduzir' (vídeo "
            "menor, qualidade baixa/media/alta), 'extrair_audio' (MP3), 'cortar' (inicio e "
            "fim, ex: 1:30), 'gif' (inicio e duracao em segundos), 'converter' (formato: "
            "mp4, mkv, webm, mp3, wav...), 'transcrever' (áudio/vídeo para texto).",
            {"acao": ("string", "info, reduzir, extrair_audio, cortar, gif, converter ou transcrever"),
             "arquivo": ("string", "Caminho do vídeo ou áudio"),
             "inicio": ("string", "Para cortar/gif: início, ex: 0:45"),
             "fim": ("string", "Para cortar: fim, ex: 2:10"),
             "duracao": ("number", "Para gif: segundos (máx. 15)"),
             "qualidade": ("string", "Para reduzir: baixa, media ou alta"),
             "formato": ("string", "Para converter: extensão de destino")},
            ["acao", "arquivo"], grupo="midia")
def midia(acao, arquivo, inicio="0", fim="", duracao=5, qualidade="media", formato=""):
    if not shutil.which("ffmpeg"):
        return "Erro: instale o ffmpeg com: " + como_instalar("ffmpeg")
    origem = caminho_seguro(arquivo)
    if not os.path.isfile(origem):
        return f"Erro: {origem} não existe."
    base, ext = os.path.splitext(origem)
    acao = sem_acento(acao)
    if acao == "info":
        r = rodar(["ffprobe", "-v", "error", "-show_entries",
                   "format=duration,size,bit_rate:stream=codec_type,codec_name,width,height",
                   "-of", "json", origem])
        dados = json.loads(r.stdout or "{}")
        fmt = dados.get("format", {})
        linhas = [f"Duração: {float(fmt.get('duration', 0)) / 60:.1f} min",
                  f"Tamanho: {tamanho_legivel(int(fmt.get('size', 0)))}"]
        for st in dados.get("streams", []):
            if st.get("codec_type") == "video":
                linhas.append(f"Vídeo: {st.get('codec_name')} {st.get('width')}x{st.get('height')}")
            elif st.get("codec_type") == "audio":
                linhas.append(f"Áudio: {st.get('codec_name')}")
        return "\n".join(linhas)
    if acao == "reduzir":
        crf = {"baixa": "33", "media": "28", "alta": "23"}.get(sem_acento(qualidade), "28")
        enc = _encoder_video()
        qual = (["-crf", crf] if enc == "libx264" else
                ["-b:v", {"33": "800k", "28": "1500k", "23": "3000k"}[crf]])
        saida = _sem_sobrescrever(base + "-reduzido.mp4")
        return _rodar_ffmpeg(["-i", origem, "-vf", "scale=-2:'min(720,ih)'", "-c:v", enc] + qual
                             + ["-c:a", "aac", "-b:a", "128k"], saida, "Reduzindo o vídeo")
    if acao == "extrair_audio":
        tem_mp3 = "libmp3lame" in rodar(["ffmpeg", "-hide_banner", "-encoders"]).stdout
        saida = _sem_sobrescrever(base + (".mp3" if tem_mp3 else ".m4a"))
        codec = ["-c:a", "libmp3lame", "-q:a", "2"] if tem_mp3 else ["-c:a", "aac", "-b:a", "192k"]
        return _rodar_ffmpeg(["-i", origem, "-vn"] + codec, saida, "Extraindo o áudio")
    if acao == "cortar":
        if not fim:
            return "Erro: informe o fim do trecho (ex: 2:10)."
        saida = _sem_sobrescrever(base + "-corte" + ext)
        return _rodar_ffmpeg(["-ss", str(_segundos(inicio)), "-to", str(_segundos(fim)),
                              "-i", origem, "-c", "copy"], saida, "Cortando o trecho")
    if acao == "gif":
        segundos = min(15.0, float(duracao or 5))
        saida = _sem_sobrescrever(base + ".gif")
        return _rodar_ffmpeg(["-ss", str(_segundos(inicio)), "-t", str(segundos), "-i", origem,
                              "-vf", "fps=10,scale=480:-1:flags=lanczos"], saida, "Criando o GIF")
    if acao == "converter":
        formato = str(formato).strip(". ").lower()
        if not formato:
            return "Erro: informe o formato (ex: mp4, mp3, mkv)."
        saida = _sem_sobrescrever(f"{base}.{formato}")
        extra = ["-c:v", _encoder_video()] if formato in ("mp4", "mov") else []
        return _rodar_ffmpeg(["-i", origem] + extra, saida, f"Convertendo para {formato}")
    if acao == "transcrever":
        try:
            _carregar_whisper()
        except ImportError:
            return "Erro: a transcrição usa a voz do Lumero. Rode o instalador da voz."
        wav = os.path.join(tempfile.gettempdir(), f"transcrever-{os.getpid()}.wav")
        erro = _rodar_ffmpeg(["-i", origem, "-vn", "-ac", "1", "-ar", "16000"], wav,
                             "Preparando o áudio")
        if erro.startswith("Erro"):
            return erro
        spinner = Spinner("Transcrevendo (pode levar alguns minutos)").iniciar()
        try:
            texto = _WHISPER["modelo"](wav).strip()
        finally:
            spinner.parar()
            os.remove(wav)
        destino = _sem_sobrescrever(base + "-transcricao.txt")
        with open(destino, "w", encoding="utf-8") as f:
            f.write(texto + "\n")
        return f"Transcrição salva em {destino}. Começo:\n{texto[:1500]}"
    return "Erro: acao inválida."


# ---------------------------------------------------------------- fotos em lote (Pillow)
EXT_FOTOS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif")
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
         "setembro", "outubro", "novembro", "dezembro"]


def _abrir_foto(caminho):
    from PIL import Image, ImageOps
    if caminho.lower().endswith((".heic", ".heif")):
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except ImportError:
            raise RuntimeError("para HEIC instale: " + como_instalar_python("pillow-heif"))
    imagem = Image.open(caminho)
    return ImageOps.exif_transpose(imagem)


def _data_da_foto(caminho):
    try:
        from PIL import Image
        with Image.open(caminho) as im:
            exif = im.getexif()
            texto = exif.get_ifd(0x8769).get(36867) or exif.get(306)  # DateTimeOriginal / DateTime
            if texto:
                return datetime.datetime.strptime(str(texto)[:19], "%Y:%m:%d %H:%M:%S")
    except Exception:
        pass
    return datetime.datetime.fromtimestamp(os.path.getmtime(caminho))


def _confirmar_fotos(args):
    return sem_acento(args.get("acao", "")) == "organizar_por_data" and \
        str(args.get("executar", "")).lower() in ("true", "1", "sim")


@ferramenta("Fotos em lote (as originais não são alteradas; o resultado vai para uma "
            "subpasta). acao: 'redimensionar' (tamanho = lado maior em pixels), 'comprimir' "
            "(qualidade 1-95), 'converter' (formato jpg, png ou webp), 'organizar_por_data' "
            "(move para pastas ano/mês; primeiro mostra o plano, depois executar=true).",
            {"acao": ("string", "redimensionar, comprimir, converter ou organizar_por_data"),
             "alvo": ("string", "Uma foto, uma pasta ou vários caminhos (um por linha)"),
             "tamanho": ("number", "Lado maior em pixels (padrão 1920)"),
             "qualidade": ("number", "Qualidade JPG/WEBP de 1 a 95 (padrão 80)"),
             "formato": ("string", "jpg, png ou webp"),
             "executar": ("boolean", "Para organizar: false mostra o plano, true executa")},
            ["acao", "alvo"], confirmar=_confirmar_fotos, grupo="fotos")
def fotos(acao, alvo, tamanho=1920, qualidade=80, formato="jpg", executar=False):
    try:
        import PIL  # noqa: F401
    except ImportError:
        return "Erro: instale com: " + como_instalar_python("pillow")
    lista = _lista_de_arquivos(alvo, EXT_FOTOS)
    if not lista:
        return "Nenhuma foto encontrada nesse caminho."
    acao = sem_acento(acao)
    if acao == "organizar_por_data":
        raiz = caminho_seguro(alvo) if os.path.isdir(caminho_seguro(alvo)) else os.path.dirname(lista[0])
        plano = []
        for foto in lista:
            data = _data_da_foto(foto)
            pasta = os.path.join(raiz, str(data.year), f"{data.month:02d}-{MESES[data.month - 1]}")
            plano.append((foto, pasta))
        resumo = {}
        for _, pasta in plano:
            resumo[os.path.relpath(pasta, raiz)] = resumo.get(os.path.relpath(pasta, raiz), 0) + 1
        texto = "\n".join(f"{p}: {n} fotos" for p, n in sorted(resumo.items()))
        if str(executar).lower() not in ("true", "1", "sim"):
            return f"Plano ({len(plano)} fotos em {raiz}):\n{texto}\nPara executar, chame de novo com executar=true."
        for foto, pasta in plano:
            os.makedirs(pasta, exist_ok=True)
            shutil.move(foto, _sem_sobrescrever(os.path.join(pasta, os.path.basename(foto))))
        return f"{len(plano)} fotos organizadas em {raiz}:\n{texto}"
    nomes_pasta = {"redimensionar": "redimensionadas", "comprimir": "comprimidas",
                   "converter": "convertidas"}
    if acao not in nomes_pasta:
        return "Erro: acao inválida."
    formato = str(formato or "jpg").lower().strip(".").replace("jpeg", "jpg")
    feitas, erros, antes, depois = 0, [], 0, 0
    spinner = Spinner(f"Processando {len(lista)} fotos").iniciar()
    try:
        for foto in lista:
            try:
                imagem = _abrir_foto(foto)
                destino_dir = os.path.join(os.path.dirname(foto), nomes_pasta[acao])
                os.makedirs(destino_dir, exist_ok=True)
                nome = os.path.splitext(os.path.basename(foto))[0]
                ext = formato if acao == "converter" else \
                    ("jpg" if foto.lower().endswith((".heic", ".heif", ".bmp", ".tif", ".tiff"))
                     else os.path.splitext(foto)[1].lstrip(".").lower().replace("jpeg", "jpg"))
                if acao == "redimensionar":
                    imagem.thumbnail((int(tamanho), int(tamanho)))
                destino = _sem_sobrescrever(os.path.join(destino_dir, f"{nome}.{ext}"))
                opcoes = {}
                if ext in ("jpg", "webp"):
                    imagem = imagem.convert("RGB")
                    opcoes = {"quality": max(1, min(95, int(qualidade))), "optimize": True}
                imagem.save(destino, "JPEG" if ext == "jpg" else ext.upper(), **opcoes)
                antes += os.path.getsize(foto)
                depois += os.path.getsize(destino)
                feitas += 1
            except Exception as erro:
                erros.append(f"{os.path.basename(foto)}: {erro}")
    finally:
        spinner.parar()
    texto = (f"{feitas} fotos salvas em '{nomes_pasta[acao]}' "
             f"({tamanho_legivel(antes)} → {tamanho_legivel(depois)}).")
    if erros:
        texto += "\nErro em:\n" + "\n".join(erros[:10])
    return texto


# ---------------------------------------------------------------- espaço, organizar, compactar
@ferramenta("Espaço em disco (só mostra, não apaga nada; para apagar use lixeira). acao: "
            "'maiores' (arquivos e pastas que mais ocupam), 'duplicados' (arquivos "
            "iguais), 'antigos' (arquivos sem uso há mais de 'dias', padrão em Downloads).",
            {"acao": ("string", "maiores, duplicados ou antigos"),
             "pasta": ("string", "Onde procurar (padrão: pasta pessoal; antigos: Downloads)"),
             "dias": ("number", "Para antigos: quantos dias (padrão 90)")},
            ["acao"], grupo="arquivos")
def espaco_disco(acao, pasta="", dias=90):
    import hashlib
    acao = sem_acento(acao)
    raiz = caminho_seguro(pasta or (pasta_usuario("DOWNLOAD", "Downloads") if acao == "antigos" else "~"))
    ignorar = {".cache", ".local", "node_modules", ".git", "__pycache__", ".var"}
    todos = []
    spinner = Spinner("Analisando o disco").iniciar()
    try:
        for atual, subpastas, arquivos in os.walk(raiz):
            subpastas[:] = [s for s in subpastas if s not in ignorar and not s.startswith(".")]
            for nome in arquivos:
                completo = os.path.join(atual, nome)
                try:
                    info = os.lstat(completo)
                except OSError:
                    continue
                if not os.path.islink(completo):
                    todos.append((completo, info.st_size, max(info.st_atime, info.st_mtime)))
    finally:
        spinner.parar()
    if acao == "maiores":
        pastas = {}
        for caminho, tam, _ in todos:
            rel = os.path.relpath(caminho, raiz).split(os.sep)
            if len(rel) > 1:
                pastas[rel[0]] = pastas.get(rel[0], 0) + tam
        linhas = ["Pastas que mais ocupam:"]
        linhas += [f"  {tamanho_legivel(t):>8}  {p}/" for p, t in sorted(pastas.items(), key=lambda x: -x[1])[:8]]
        linhas.append("Maiores arquivos:")
        linhas += [f"  {tamanho_legivel(t):>8}  {c}" for c, t, _ in sorted(todos, key=lambda x: -x[1])[:15]]
        return "\n".join(linhas)
    if acao == "duplicados":
        por_tamanho = {}
        for caminho, tam, _ in todos:
            if tam > 100_000:  # ignora arquivos pequenos
                por_tamanho.setdefault(tam, []).append(caminho)
        grupos = []
        for tam, caminhos in por_tamanho.items():
            if len(caminhos) < 2:
                continue
            por_hash = {}
            for c in caminhos:
                try:
                    h = hashlib.sha1()
                    with open(c, "rb") as f:
                        for bloco in iter(lambda: f.read(1 << 20), b""):
                            h.update(bloco)
                    por_hash.setdefault(h.hexdigest(), []).append(c)
                except OSError:
                    pass
            grupos += [(tam, cs) for cs in por_hash.values() if len(cs) > 1]
        if not grupos:
            return "Nenhum arquivo duplicado encontrado (acima de 100 KB)."
        grupos.sort(key=lambda g: -g[0] * (len(g[1]) - 1))
        desperdicio = sum(t * (len(cs) - 1) for t, cs in grupos)
        linhas = [f"{len(grupos)} grupos de arquivos iguais ({tamanho_legivel(desperdicio)} repetidos):"]
        for tam, cs in grupos[:12]:
            linhas.append(f"  {tamanho_legivel(tam)} cada:")
            linhas += [f"    {c}" for c in cs[:5]]
        return "\n".join(linhas)
    if acao == "antigos":
        limite = time.time() - float(dias or 90) * 86400
        velhos = sorted([(c, t) for c, t, uso in todos if uso < limite], key=lambda x: -x[1])
        if not velhos:
            return f"Nenhum arquivo sem uso há mais de {dias} dias em {raiz}."
        total = sum(t for _, t in velhos)
        return (f"{len(velhos)} arquivos sem uso há mais de {dias} dias ({tamanho_legivel(total)}):\n"
                + "\n".join(f"  {tamanho_legivel(t):>8}  {c}" for c, t in velhos[:25]))
    return "Erro: acao inválida."


CATEGORIAS_PASTA = {"foto": "Imagens", "video": "Vídeos", "audio": "Músicas",
                    "documento": "Documentos", "planilha": "Planilhas",
                    "apresentacao": "Apresentações", "compactado": "Compactados",
                    "instalador": "Instaladores", "codigo": "Código"}


def _confirmar_organizar(args):
    return str(args.get("executar", "")).lower() in ("true", "1", "sim")


@ferramenta("Organiza os arquivos soltos de uma pasta em subpastas, por 'tipo' (Imagens, "
            "Vídeos, Documentos...) ou por 'mes'. Primeiro mostra o plano; para fazer de "
            "verdade, chame de novo com executar=true.",
            {"pasta": ("string", "Pasta a organizar (padrão: Downloads)"),
             "por": ("string", "tipo ou mes"),
             "executar": ("boolean", "false mostra o plano, true move os arquivos")},
            confirmar=_confirmar_organizar, grupo="arquivos")
def organizar_pasta(pasta="", por="tipo", executar=False):
    raiz = caminho_seguro(pasta or pasta_usuario("DOWNLOAD", "Downloads"))
    plano = []
    for nome in sorted(os.listdir(raiz)):
        completo = os.path.join(raiz, nome)
        if not os.path.isfile(completo) or nome.startswith("."):
            continue
        if sem_acento(por).startswith("mes"):
            data = datetime.datetime.fromtimestamp(os.path.getmtime(completo))
            destino = f"{data.year}-{data.month:02d}"
        else:
            ext = os.path.splitext(nome)[1].lower()
            destino = next((CATEGORIAS_PASTA[t] for t, exts in TIPOS.items()
                            if t in CATEGORIAS_PASTA and ext in exts), "Outros")
        plano.append((completo, destino))
    if not plano:
        return f"Não há arquivos soltos em {raiz}."
    resumo = {}
    for _, d in plano:
        resumo[d] = resumo.get(d, 0) + 1
    texto = "\n".join(f"  {d}/: {n} arquivos" for d, n in sorted(resumo.items()))
    if str(executar).lower() not in ("true", "1", "sim"):
        return f"Plano para {raiz} ({len(plano)} arquivos):\n{texto}\nPara executar, chame com executar=true."
    for completo, destino in plano:
        os.makedirs(os.path.join(raiz, destino), exist_ok=True)
        shutil.move(completo, _sem_sobrescrever(os.path.join(raiz, destino, os.path.basename(completo))))
    return f"{len(plano)} arquivos organizados em {raiz}:\n{texto}"


@ferramenta("Compacta arquivos/pastas em ZIP (acao 'compactar') ou extrai ZIP, TAR, 7Z e RAR "
            "(acao 'extrair', numa pasta com o nome do arquivo).",
            {"acao": ("string", "compactar ou extrair"),
             "caminhos": ("string", "O que compactar (um por linha) ou o arquivo a extrair"),
             "destino": ("string", "Para compactar: nome do .zip (opcional)")},
            ["acao", "caminhos"], grupo="arquivos")
def compactar(acao, caminhos, destino=""):
    import zipfile
    itens = [caminho_seguro(c.strip()) for c in re.split(r"[\n;]", str(caminhos)) if c.strip()]
    if not itens or not all(os.path.exists(i) for i in itens):
        return "Erro: caminho não encontrado."
    if sem_acento(acao) == "compactar":
        if destino:
            saida = caminho_seguro(destino if destino.endswith(".zip") else destino + ".zip")
        else:
            saida = os.path.splitext(itens[0])[0].rstrip("/") + ".zip"
        saida = _sem_sobrescrever(saida)
        spinner = Spinner("Compactando").iniciar()
        try:
            with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as z:
                for item in itens:
                    if os.path.isdir(item):
                        base = os.path.dirname(item.rstrip("/"))
                        for atual, _, arquivos in os.walk(item):
                            for nome in arquivos:
                                completo = os.path.join(atual, nome)
                                z.write(completo, os.path.relpath(completo, base))
                    else:
                        z.write(item, os.path.basename(item))
        finally:
            spinner.parar()
        return f"Compactado em {saida} ({tamanho_legivel(os.path.getsize(saida))})."
    if sem_acento(acao) == "extrair":
        arquivo = itens[0]
        nome = os.path.basename(arquivo)
        for ext in (".tar.gz", ".tar.xz", ".tar.bz2", ".tgz", ".zip", ".tar", ".7z", ".rar"):
            if nome.lower().endswith(ext):
                nome = nome[: -len(ext)]
                break
        pasta = _sem_sobrescrever(os.path.join(os.path.dirname(arquivo), nome))
        spinner = Spinner("Extraindo").iniciar()
        try:
            if arquivo.lower().endswith((".7z", ".rar")):
                programa = (shutil.which("7z") or shutil.which("7za") or shutil.which("7zz")
                            or next((c for c in (r"C:\Program Files\7-Zip\7z.exe",
                                                 r"C:\Program Files (x86)\7-Zip\7z.exe")
                                     if EH_WINDOWS and os.path.exists(c)), None))
                if not programa:
                    return "Erro: para 7z/rar instale: " + como_instalar("7zip")
                r = rodar([programa, "x", "-y", f"-o{pasta}", arquivo], timeout=3600)
                if r.returncode != 0:
                    return f"Erro ao extrair: {r.stderr.strip()[-300:]}"
            else:
                shutil.unpack_archive(arquivo, pasta)
        except (shutil.ReadError, ValueError, OSError) as erro:
            return f"Erro ao extrair: {erro}"
        finally:
            spinner.parar()
        return f"Extraído em {pasta} ({len(os.listdir(pasta))} itens)."
    return "Erro: acao deve ser compactar ou extrair."


# ---------------------------------------------------------------- sistema, rede e processos
def _confirmar_sistema(args):
    return sem_acento(args.get("acao", "")) in ("atualizar", "reconectar_wifi")


def _ip_local():
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("1.1.1.1", 80))   # UDP: não manda nada, só escolhe a placa de rede
            return s.getsockname()[0]
    except OSError:
        return ""


def _contar_atualizacoes():
    """Lista de (origem, quantidade, exemplos)."""
    resultado = []
    if EH_WINDOWS:
        r = rodar(["winget", "upgrade", "--accept-source-agreements"], timeout=300)
        linhas = [l for l in r.stdout.splitlines() if re.search(r"\s\S+\.\S+\s", l)
                  and not l.startswith(("Nome", "Name", "-"))]
        resultado.append(("programas (winget)", len(linhas), [l.split()[0] for l in linhas[:8]]))
        return resultado
    if EH_MAC:
        r = rodar(["softwareupdate", "-l"], timeout=300)
        itens = re.findall(r"\* Label: (.+)", r.stdout + r.stderr)
        resultado.append(("macOS", len(itens), itens[:5]))
        if shutil.which("brew"):
            r = rodar(["brew", "outdated", "--quiet"], timeout=300)
            itens = r.stdout.split()
            resultado.append(("Homebrew", len(itens), itens[:10]))
        return resultado
    if GERENCIADOR == "dnf":
        r = rodar(["dnf", "check-update", "-q"], timeout=300)
        pacotes = [l.split()[0].rsplit(".", 1)[0] for l in r.stdout.splitlines()
                   if l.strip() and not l.startswith(" ") and "." in l.split()[0]] \
            if r.returncode == 100 else []
    elif GERENCIADOR == "apt":
        r = rodar(["apt", "list", "--upgradable"], timeout=300)
        pacotes = [l.split("/")[0] for l in r.stdout.splitlines() if "/" in l]
    elif GERENCIADOR == "pacman":
        comando = ["checkupdates"] if shutil.which("checkupdates") else ["pacman", "-Qu"]
        r = rodar(comando, timeout=300)
        pacotes = [l.split()[0] for l in r.stdout.splitlines() if l.strip()]
    elif GERENCIADOR == "zypper":
        r = rodar(["zypper", "--non-interactive", "--quiet", "list-updates"], timeout=300)
        pacotes = [l.split("|")[2].strip() for l in r.stdout.splitlines()
                   if l.startswith("v ") and l.count("|") >= 3]
    else:
        pacotes = []
    resultado.append((f"pacotes do sistema ({GERENCIADOR or '?'})", len(pacotes), pacotes[:15]))
    if shutil.which("flatpak"):
        r = rodar(["flatpak", "remote-ls", "--updates", "--columns=application"], timeout=120)
        flat = [l for l in r.stdout.splitlines() if l.strip()]
        resultado.append(("aplicativos Flatpak", len(flat), flat[:10]))
    if shutil.which("snap"):
        r = rodar(["snap", "refresh", "--list"], timeout=120)
        snaps = [l.split()[0] for l in r.stdout.splitlines()[1:] if l.strip()]
        resultado.append(("aplicativos Snap", len(snaps), snaps[:10]))
    return resultado


def _comando_atualizar():
    extras = (" && (command -v flatpak >/dev/null && flatpak update -y --noninteractive || true)"
              " && (command -v snap >/dev/null && snap refresh || true)")
    return {"dnf": "dnf upgrade -y --refresh",
            "apt": "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get -y upgrade",
            "pacman": "pacman -Syu --noconfirm",
            "zypper": "zypper --non-interactive refresh && zypper --non-interactive update",
            }.get(GERENCIADOR, "true") + extras


def _wifi_mac():
    portas = rodar(["networksetup", "-listallhardwareports"]).stdout
    achado = re.search(r"Hardware Port: (?:Wi-Fi|AirPort)\s*\nDevice: (\S+)", portas)
    return achado.group(1) if achado else "en0"


def _rede():
    linhas = []
    if EH_WINDOWS:
        saida = rodar(["netsh", "wlan", "show", "interfaces"]).stdout
        campos = dict((k.strip(), v.strip()) for k, v in
                      (l.split(":", 1) for l in saida.splitlines() if ":" in l))
        ssid = campos.get("SSID")
        if ssid:
            sinal = campos.get("Sinal") or campos.get("Signal") or "?"
            linhas.append(f"Wi-Fi: {ssid} · sinal {sinal}")
    elif EH_MAC:
        saida = rodar(["networksetup", "-getairportnetwork", _wifi_mac()]).stdout
        achado = re.search(r"Network:\s*(.+)", saida)
        if achado:
            linhas.append("Wi-Fi: " + achado.group(1).strip())
    elif shutil.which("nmcli"):
        r = rodar(["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL,RATE", "dev", "wifi"])
        for l in r.stdout.splitlines():
            partes = l.split(":")
            if partes[0] in ("sim", "yes") and len(partes) >= 4:
                linhas.append(f"Wi-Fi: {partes[1]} · sinal {partes[2]}% · {partes[3]}")
        r = rodar(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"])
        for l in r.stdout.splitlines():
            dev, tipo, estado, conexao = (l.split(":") + ["", "", "", ""])[:4]
            if tipo in ("wifi", "ethernet"):
                linhas.append(f"{dev} ({tipo}): {estado} {conexao}".strip())
    ip = _ip_local()
    if ip:
        linhas.append(f"IP local: {ip}")
    return "\n".join(linhas) or "Não consegui ler o estado da rede."


def _reconectar_wifi():
    if EH_WINDOWS:
        saida = rodar(["netsh", "wlan", "show", "interfaces"]).stdout
        perfil = re.search(r"(?:Perfil|Profile)\s*:\s*(.+)", saida)
        if not perfil:
            return "Erro: não achei uma rede Wi-Fi conectada."
        rodar(["netsh", "wlan", "disconnect"])
        time.sleep(2)
        r = rodar(["netsh", "wlan", "connect", f"name={perfil.group(1).strip()}"])
    elif EH_MAC:
        placa = _wifi_mac()
        rodar(["networksetup", "-setairportpower", placa, "off"])
        time.sleep(2)
        r = rodar(["networksetup", "-setairportpower", placa, "on"])
    else:
        if not shutil.which("nmcli"):
            return "Erro: o nmcli (NetworkManager) não está instalado."
        r = rodar(["nmcli", "-t", "-f", "DEVICE,TYPE", "device"])
        dev = next((l.split(":")[0] for l in r.stdout.splitlines() if l.endswith(":wifi")), None)
        if not dev:
            return "Erro: não achei a placa de Wi-Fi."
        rodar(["nmcli", "device", "disconnect", dev])
        time.sleep(2)
        r = rodar(["nmcli", "device", "connect", dev])
    return "Wi-Fi reconectado." if r.returncode == 0 else f"Erro: {(r.stderr or r.stdout).strip()[:200]}"


def _por_que_desligou():
    if EH_WINDOWS:
        dados = ps_json("""
@(Get-WinEvent -FilterHashtable @{LogName='System'; Id=41,1074,6006,6008,42,107} -MaxEvents 8 -ErrorAction SilentlyContinue |
  ForEach-Object { [pscustomobject]@{ id = $_.Id; quando = $_.TimeCreated.ToString('dd/MM/yyyy HH:mm'); texto = ($_.Message -split "`n")[0] } }) |
  ConvertTo-Json -Compress
""")
        if not dados:
            return "Não consegui ler os registros do Windows."
        causas = {41: "o Windows desligou sem aviso: corte de energia, bateria acabou ou travamento",
                  6008: "desligamento inesperado (corte de energia ou travamento)",
                  1074: "desligamento normal pedido por um programa ou pelo usuário",
                  6006: "desligamento normal",
                  42: "o computador entrou em suspensão", 107: "o computador voltou da suspensão"}
        ultimo = next((d for d in dados if d.get("id") in (41, 6008, 1074, 6006)), dados[0])
        return (f"Causa provável: {causas.get(ultimo.get('id'), 'desconhecida')}.\n\n"
                "Últimos eventos de energia:\n" + "\n".join(
                    f"{d.get('quando')} · evento {d.get('id')}: {str(d.get('texto'))[:120]}"
                    for d in dados))
    if EH_MAC:
        r = rodar(["log", "show", "--last", "7d", "--style", "compact", "--predicate",
                   'eventMessage contains "Previous shutdown cause"'], timeout=180)
        achados = re.findall(r"Previous shutdown cause:\s*(-?\d+)", r.stdout)
        if not achados:
            return "Não achei registros de desligamento nos últimos 7 dias."
        codigo = int(achados[-1])
        causas = {5: "desligamento normal (pelo menu ou comando)",
                  3: "desligamento forçado (botão de energia segurado)",
                  0: "falta de energia (bateria acabou ou carregador desconectado)",
                  -3: "superaquecimento", -86: "superaquecimento (proteção térmica)",
                  -95: "superaquecimento (proteção térmica)"}
        causa = causas.get(codigo, f"problema de hardware ou do sistema (código {codigo})")
        return f"Causa provável do último desligamento: {causa}."
    fim = rodar(["journalctl", "-b", "-1", "-n", "25", "--no-pager", "-o", "short"]).stdout
    avisos = rodar(["journalctl", "-b", "-1", "-p", "warning", "-n", "40", "--no-pager"]).stdout
    tudo = (fim + avisos).lower()
    if not fim.strip():
        return "Não consegui ler os registros (talvez seja o primeiro boot salvo)."
    if any(p in tudo for p in ("critical temperature", "thermal", "overheat")):
        causa = "superaquecimento: o processador passou do limite de temperatura"
    elif any(p in tudo for p in ("reached target system power off", "reached target shutdown",
                                 "systemd-shutdown", "power key pressed", "system is powering down")):
        causa = "desligamento normal (pelo menu, botão de energia ou comando)"
    elif "suspend" in fim.lower()[-800:]:
        causa = "o computador foi suspenso e não voltou (pode ter acabado a bateria suspenso)"
    else:
        causa = ("os registros param de repente, sem aviso: corte de energia (bateria/carregador) "
                 "ou travamento forte")
    return f"Causa provável: {causa}.\n\nÚltimas linhas antes de desligar:\n" + "\n".join(
        l[:160] for l in fim.strip().splitlines()[-12:])


@ferramenta("Sistema e rede. acao: 'atualizacoes' (vê se há atualizações), 'atualizar' "
            "(atualiza o sistema e os programas; pede senha), 'rede' (Wi-Fi, sinal, IP), "
            "'testar_internet' (conexão e velocidade), 'reconectar_wifi', "
            "'por_que_desligou' (analisa os registros do último desligamento).",
            {"acao": ("string", "atualizacoes, atualizar, rede, testar_internet, "
                                "reconectar_wifi ou por_que_desligou")},
            ["acao"], confirmar=_confirmar_sistema, grupo="sistema")
def sistema(acao):
    acao = sem_acento(acao)
    if acao == "atualizacoes":
        spinner = Spinner("Procurando atualizações").iniciar()
        try:
            contagem = _contar_atualizacoes()
        finally:
            spinner.parar()
        if not any(n for _, n, _ in contagem):
            return "Está tudo atualizado."
        return "\n".join(f"{n} {origem} para atualizar" + (f" (ex: {', '.join(ex)})" if ex else "")
                         for origem, n, ex in contagem)
    if acao == "atualizar":
        if EH_WINDOWS:
            return rodar_comando_admin(
                "winget upgrade --all --silent --accept-source-agreements "
                "--accept-package-agreements", "atualizar os programas")
        if EH_MAC:
            partes = []
            if shutil.which("brew"):
                spinner = Spinner("Atualizando o Homebrew").iniciar()
                try:
                    r = rodar(["brew", "upgrade"], timeout=3600)
                finally:
                    spinner.parar()
                partes.append(f"Homebrew: código {r.returncode}\n{_cortar_saida(r.stdout + r.stderr)[-1500:]}")
            partes.append(rodar_comando_admin("softwareupdate -i -a", "atualizar o macOS"))
            return "\n\n".join(partes)
        return rodar_comando_admin(_comando_atualizar(), "atualizar o sistema")
    if acao == "rede":
        return _rede()
    if acao == "testar_internet":
        linhas = []
        ping = (["ping", "-n", "3", "-w", "2000", "1.1.1.1"] if EH_WINDOWS else
                ["ping", "-c", "3", "-t", "6", "1.1.1.1"] if EH_MAC else
                ["ping", "-c", "3", "-W", "2", "1.1.1.1"])
        r = rodar(ping, timeout=20)
        m = (re.search(r"= [\d.]+/([\d.]+)/", r.stdout) or
             re.search(r"(?:Média|Average|Media)\s*=\s*(\d+)\s*ms", r.stdout))
        linhas.append(f"Ping: {m.group(1)} ms" if m else "Ping: sem resposta (sem internet?)")
        try:
            import socket
            socket.gethostbyname("google.com")
            linhas.append("DNS: funcionando")
        except OSError:
            linhas.append("DNS: falhou (sites não abrem pelo nome)")
        try:
            inicio = time.time()
            req = urllib.request.Request("https://speed.cloudflare.com/__down?bytes=10000000",
                                         headers={"User-Agent": NAVEGADOR_UA})
            with urllib.request.urlopen(req, timeout=30) as resposta:
                recebidos = len(resposta.read())
            segundos = max(0.01, time.time() - inicio)
            linhas.append(f"Download: ~{recebidos * 8 / segundos / 1e6:.0f} Mbps")
        except Exception:
            linhas.append("Download: não consegui medir")
        return "\n".join(linhas)
    if acao == "reconectar_wifi":
        return _reconectar_wifi()
    if acao == "por_que_desligou":
        spinner = Spinner("Lendo os registros do sistema").iniciar()
        try:
            return _por_que_desligou()
        finally:
            spinner.parar()
    return "Erro: acao inválida."


if EH_WINDOWS:
    PROCESSOS_PROTEGIDOS = {"explorer.exe", "dwm.exe", "winlogon.exe", "csrss.exe",
                            "svchost.exe", "lsass.exe", "services.exe", "ollama.exe",
                            "ollama app.exe", "sihost.exe", "ctfmon.exe"}
elif EH_MAC:
    PROCESSOS_PROTEGIDOS = {"WindowServer", "loginwindow", "Finder", "Dock", "SystemUIServer",
                            "launchd", "ollama", "Ollama", "ControlCenter"}
else:
    PROCESSOS_PROTEGIDOS = {"gnome-shell", "systemd", "Xwayland", "pipewire", "wireplumber",
                            "gnome-session-binary", "dbus-broker", "dbus-daemon", "ollama",
                            "gdm", "plasmashell", "kwin_wayland", "kwin_x11", "sddm",
                            "xfce4-session", "cinnamon", "Xorg"}


def processo_vivo(pid):
    ps = _psutil()
    if ps:
        return ps.pid_exists(int(pid))
    if EH_WINDOWS:  # os.kill(pid, 0) no Windows mandaria Ctrl+C!
        return str(pid) in rodar(["tasklist", "/FI", f"PID eq {pid}", "/NH"]).stdout
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def encerrar_arvore(pid):
    """Fecha um processo e os que ele abriu."""
    if EH_WINDOWS:
        rodar(["taskkill", "/PID", str(pid), "/T", "/F"], timeout=20)
        return
    try:
        os.killpg(int(pid), signal.SIGTERM)
    except OSError:
        try:
            os.kill(int(pid), signal.SIGTERM)
        except OSError:
            pass


def _meus_processos():
    """Lista de (pid, cpu%, ram_mb, nome) dos programas do usuário."""
    ps = _psutil()
    if ps:
        meus = []
        try:
            eu = ps.Process().username()
        except ps.Error:
            eu = None
        procs = []
        for proc in ps.process_iter(["pid", "name", "username"]):
            if proc.info.get("username") == eu and proc.info["pid"] != os.getpid():
                try:
                    proc.cpu_percent(None)
                    procs.append(proc)
                except ps.Error:
                    pass
        time.sleep(0.5)
        for proc in procs:
            try:
                meus.append((proc.pid, proc.cpu_percent(None), proc.memory_info().rss / 1024 ** 2,
                             proc.info.get("name") or "?"))
            except ps.Error:
                pass
        return sorted(meus, key=lambda m: m[1], reverse=True)
    if EH_WINDOWS:
        return []
    opcoes = ["-o", "pid=,pcpu=,rss=,comm="]
    r = rodar(["ps", "-U", str(os.getuid())] + opcoes)
    meus = []
    for l in r.stdout.strip().splitlines():
        try:
            pid, cpu, rss, nome = l.split(None, 3)
            meus.append((int(pid), float(cpu.replace(",", ".")), int(rss) / 1024,
                         os.path.basename(nome.strip())))
        except ValueError:
            continue
    return sorted((m for m in meus if m[0] != os.getpid()), key=lambda m: m[1], reverse=True)


def _confirmar_processos(args):
    return sem_acento(args.get("acao", "")) == "encerrar"


@ferramenta("Programas rodando. acao='listar' mostra os que mais usam CPU e RAM (bom para "
            "saber o que está esquentando ou travando); acao='encerrar' fecha um programa "
            "pelo nome ou número (PID).",
            {"acao": ("string", "listar ou encerrar"),
             "alvo": ("string", "Para encerrar: nome do programa ou PID")},
            ["acao"], confirmar=_confirmar_processos, grupo="sistema")
def processos(acao, alvo=""):
    lista = _meus_processos()
    if not lista and EH_WINDOWS:
        return "Erro: para ver os programas, instale: " + como_instalar_python("psutil")
    if sem_acento(acao) == "listar":
        linhas = ["   PID   CPU    RAM  PROGRAMA"]
        for pid, cpu, ram, nome in lista[:12]:
            linhas.append(f"{pid:>6} {cpu:5.0f}% {ram:5.0f}M  {nome}")
        temp = temperatura_cpu()
        if temp:
            linhas.append(f"Temperatura do processador: {temp:.0f}°C")
        return "\n".join(linhas)
    if sem_acento(acao) == "encerrar":
        alvo = str(alvo).strip()
        candidatos = [(pid, nome) for pid, _, _, nome in lista
                      if (alvo.isdigit() and str(pid) == alvo)
                      or (not alvo.isdigit() and alvo.lower() in nome.lower())]
        if not candidatos:
            return f"Nenhum programa seu chamado '{alvo}' está rodando."
        if any(n in PROCESSOS_PROTEGIDOS or n.lower() in PROCESSOS_PROTEGIDOS
               for _, n in candidatos):
            return "Erro: esse programa é parte do sistema; não vou encerrar."
        ps = _psutil()
        for pid, _ in candidatos:
            try:
                if ps:
                    ps.Process(pid).terminate()
                elif EH_WINDOWS:
                    rodar(["taskkill", "/PID", str(pid)])
                else:
                    os.kill(pid, signal.SIGTERM)
            except Exception:
                pass
        return f"Encerrado: {', '.join(sorted({n for _, n in candidatos}))} ({len(candidatos)} processo(s))."
    return "Erro: acao deve ser listar ou encerrar."


# ---------------------------------------------------------------- ler a tela
def _print_portal():
    """Linux: tira um print pela permissão do sistema (na 1ª vez ele pergunta se pode)."""
    import gi
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib
    barramento = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    token = f"lumero{random.randint(1000, 99999)}"
    remetente = barramento.get_unique_name()[1:].replace(".", "_")
    pedido = f"/org/freedesktop/portal/desktop/request/{remetente}/{token}"
    resultado, laco = {}, GLib.MainLoop()

    def resposta(_con, _rem, _obj, _iface, _sinal, params):
        codigo, dados = params.unpack()
        resultado.update(codigo=codigo, uri=dados.get("uri"))
        laco.quit()

    inscricao = barramento.signal_subscribe("org.freedesktop.portal.Desktop",
                                            "org.freedesktop.portal.Request", "Response",
                                            pedido, None, Gio.DBusSignalFlags.NONE, resposta)
    barramento.call_sync("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
                         "org.freedesktop.portal.Screenshot", "Screenshot",
                         GLib.Variant("(sa{sv})", ("", {"handle_token": GLib.Variant("s", token),
                                                        "interactive": GLib.Variant("b", False)})),
                         GLib.VariantType("(o)"), Gio.DBusCallFlags.NONE, -1, None)
    GLib.timeout_add_seconds(60, laco.quit)
    laco.run()
    barramento.signal_unsubscribe(inscricao)
    if resultado.get("codigo") != 0 or not resultado.get("uri"):
        raise RuntimeError("o print foi negado ou cancelado")
    return urllib.parse.unquote(resultado["uri"].replace("file://", "", 1))


def capturar_tela():
    """Tira um print da tela inteira e devolve o caminho do arquivo."""
    pasta = os.path.join(PASTA_DADOS, "prints")
    os.makedirs(pasta, exist_ok=True)
    destino = os.path.join(pasta, f"print-{datetime.datetime.now():%Y%m%d-%H%M%S}.png")
    if EH_WINDOWS:
        codigo, _, erros = powershell(f"""
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$tela = [System.Windows.Forms.SystemInformation]::VirtualScreen
$imagem = New-Object System.Drawing.Bitmap $tela.Width, $tela.Height
$g = [System.Drawing.Graphics]::FromImage($imagem)
$g.CopyFromScreen($tela.Left, $tela.Top, 0, 0, $imagem.Size)
$imagem.Save({ps_str(destino)}, [System.Drawing.Imaging.ImageFormat]::Png)
""")
        if codigo or not os.path.exists(destino):
            raise RuntimeError(erros[:200] or "não consegui tirar o print")
        return destino
    if EH_MAC:  # na 1ª vez o macOS pede a permissão "Gravação de Tela" para o Terminal
        r = rodar(["screencapture", "-x", destino], timeout=30)
        if r.returncode or not os.path.exists(destino):
            raise RuntimeError("o macOS não deixou tirar o print. Libere o Terminal em Ajustes "
                               "do Sistema > Privacidade e Segurança > Gravação de Tela.")
        return destino
    try:
        return _print_portal()
    except Exception as erro_portal:
        alternativas = [["grim", destino], ["spectacle", "-b", "-n", "-f", "-o", destino],
                        ["gnome-screenshot", "-f", destino], ["scrot", destino],
                        ["import", "-window", "root", destino]]
        for comando in alternativas:
            if shutil.which(comando[0]):
                rodar(comando, timeout=30)
                if os.path.exists(destino):
                    return destino
        raise RuntimeError(f"não consegui tirar o print ({erro_portal})")


AVISO_PRINT = {"windows": "", "mac": " (na 1ª vez o macOS pede permissão de Gravação de Tela)",
               "linux": " (na 1ª vez o sistema pergunta se pode)"}[SO]


@ferramenta("Tira um print da tela e responde sobre o que aparece (ler um erro, explicar "
            "uma janela, descrever a tela).",
            {"pergunta": ("string", "O que perguntar sobre a tela")},
            ativa=bool(MODELO_VISAO), grupo="tela")
def ler_tela(pergunta="Descreva o que aparece na tela e leia os textos importantes."):
    try:
        print(cinza(f"     📸 Tirando o print{AVISO_PRINT}..."))
        imagem = capturar_tela()
    except Exception as erro:
        return f"Erro ao tirar o print: {erro}"
    if not modelo_instalado(MODELO_VISAO):
        return aviso_visao()
    print(cinza(f"     👁️  Olhando o print ({os.path.basename(imagem)})..."))
    return olhar(imagem, pergunta) + f"\n(print salvo em {imagem})"


# ---------------------------------------------------------------- tarefas e cronômetro
ARQ_TAREFAS = os.path.join(PASTA_DADOS, "tarefas.json")
ARQ_CRONOMETRO = os.path.join(PASTA_DADOS, "cronometro.json")


def _ler_json(arquivo, padrao):
    try:
        with open(arquivo, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return padrao


def _gravar_json(arquivo, dados):
    os.makedirs(PASTA_DADOS, exist_ok=True)
    with open(arquivo, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=1)


@ferramenta("Lista de tarefas (to-do). acao: 'adicionar' (texto), 'listar', 'concluir' "
            "(numero), 'remover' (numero), 'limpar_concluidas'.",
            {"acao": ("string", "adicionar, listar, concluir, remover ou limpar_concluidas"),
             "texto": ("string", "Para adicionar: a tarefa"),
             "numero": ("number", "Para concluir/remover: número da tarefa")},
            ["acao"], grupo="tarefas")
def tarefas(acao, texto="", numero=0):
    lista = _ler_json(ARQ_TAREFAS, [])
    acao = sem_acento(acao)
    if acao == "adicionar":
        if not texto:
            return "Erro: informe a tarefa."
        lista.append({"texto": str(texto).strip(), "feita": False,
                      "criada": f"{datetime.datetime.now():%d/%m %H:%M}"})
        _gravar_json(ARQ_TAREFAS, lista)
        return f"Tarefa {len(lista)} adicionada: {texto}"
    if acao in ("concluir", "remover"):
        n = int(float(numero or 0))
        if not 1 <= n <= len(lista):
            return "Erro: número de tarefa inválido. Use listar para ver os números."
        if acao == "concluir":
            lista[n - 1]["feita"] = True
            _gravar_json(ARQ_TAREFAS, lista)
            return f"Concluída: {lista[n - 1]['texto']}"
        removida = lista.pop(n - 1)
        _gravar_json(ARQ_TAREFAS, lista)
        return f"Removida: {removida['texto']}"
    if acao == "limpar_concluidas":
        restantes = [t for t in lista if not t["feita"]]
        _gravar_json(ARQ_TAREFAS, restantes)
        return f"{len(lista) - len(restantes)} tarefas concluídas removidas."
    if acao == "listar":
        if not lista:
            return "Nenhuma tarefa."
        pendentes = sum(1 for t in lista if not t["feita"])
        return (f"{pendentes} pendentes de {len(lista)}:\n"
                + "\n".join(f"{i}. {'✓' if t['feita'] else '☐'} {t['texto']}" for i, t in enumerate(lista, 1)))
    return "Erro: acao inválida."


@ferramenta("Cronômetro e pomodoro. acao: 'pomodoro' (foco por 'minutos', padrão 25, e "
            "avisa a pausa de 5 min), 'iniciar', 'ver' ou 'parar' o cronômetro.",
            {"acao": ("string", "pomodoro, iniciar, ver ou parar"),
             "minutos": ("number", "Para pomodoro: minutos de foco")},
            ["acao"], grupo="tarefas")
def cronometro(acao, minutos=25):
    acao = sem_acento(acao)
    if acao == "pomodoro":
        foco = float(minutos or 25)
        r1 = criar_lembrete(f"Pausa! {foco:g} minutos de foco concluídos. Descanse 5 minutos.", foco)
        r2 = criar_lembrete("Fim da pausa: hora de voltar ao foco.", foco + 5)
        if r1.startswith("Erro") or r2.startswith("Erro"):
            return f"Erro ao agendar: {r1} {r2}"
        return f"Pomodoro iniciado: foco por {foco:g} min, depois pausa de 5 min. Vou avisar nos dois momentos."
    estado = _ler_json(ARQ_CRONOMETRO, {})
    if acao == "iniciar":
        _gravar_json(ARQ_CRONOMETRO, {"inicio": time.time()})
        return "Cronômetro iniciado."
    if not estado.get("inicio"):
        return "O cronômetro não está rodando."
    decorrido = int(time.time() - estado["inicio"])
    texto = f"{decorrido // 3600}h {decorrido % 3600 // 60:02d}min {decorrido % 60:02d}s"
    if acao == "parar":
        _gravar_json(ARQ_CRONOMETRO, {})
        return f"Cronômetro parado: {texto}."
    return f"Cronômetro: {texto}."


# ---------------------------------------------------------------- Brasil: cotação, CEP, notícias
@ferramenta("Informações do Brasil. acao: 'cotacao' (valor = moedas, ex: dolar, euro, "
            "bitcoin), 'cep' (valor = CEP), 'noticias' (manchetes do dia; valor = tema "
            "opcional).",
            {"acao": ("string", "cotacao, cep ou noticias"),
             "valor": ("string", "Moedas, CEP ou tema das notícias")},
            ["acao"], precisa_internet=True, grupo="brasil")
def brasil(acao, valor=""):
    acao = sem_acento(acao)
    if acao == "cotacao":
        nomes = {"dolar": "USD", "euro": "EUR", "libra": "GBP", "bitcoin": "BTC", "iene": "JPY",
                 "peso": "ARS", "dolar canadense": "CAD", "franco": "CHF"}
        pedidas = [m.strip() for m in sem_acento(valor or "dolar, euro").replace(" e ", ",").split(",")]
        codigos = [nomes.get(m, m.upper()) for m in pedidas if m]
        url = "https://economia.awesomeapi.com.br/json/last/" + ",".join(f"{c}-BRL" for c in codigos)
        dados = json.loads(baixar(url)[0])
        linhas = []
        for chave, info in dados.items():
            if isinstance(info, dict) and "bid" in info:
                linhas.append(f"{info.get('name', chave)}: R$ {float(info['bid']):.4f} "
                              f"({float(info.get('pctChange', 0)):+.2f}% hoje, {info.get('create_date', '')[:16]})")
        return "\n".join(linhas) or "Não encontrei essa moeda."
    if acao == "cep":
        cep = re.sub(r"\D", "", str(valor))
        if len(cep) != 8:
            return "Erro: o CEP precisa ter 8 números."
        dados = json.loads(baixar(f"https://viacep.com.br/ws/{cep}/json/")[0])
        if dados.get("erro"):
            return "CEP não encontrado."
        return (f"{dados.get('logradouro', '')} {dados.get('complemento', '')}".strip()
                + f"\n{dados.get('bairro', '')} — {dados.get('localidade', '')}/{dados.get('uf', '')}"
                + f"\nCEP {dados.get('cep', '')} · DDD {dados.get('ddd', '')}")
    if acao == "noticias":
        import xml.etree.ElementTree as ET
        xml_texto, _ = baixar("https://g1.globo.com/rss/g1/")
        raiz = ET.fromstring(xml_texto)
        itens = [(i.findtext("title", "").strip(), i.findtext("link", "").strip())
                 for i in raiz.iter("item")]
        if valor:
            tema = sem_acento(valor)
            itens = [i for i in itens if tema in sem_acento(i[0])] or itens
        return "Manchetes do g1:\n" + "\n".join(f"- {t}\n  {l}" for t, l in itens[:8])
    return "Erro: acao inválida."


# ---------------------------------------------------------------- programação: git e servidor
def _confirmar_git(args):
    return sem_acento(args.get("acao", "")) == "commit"


@ferramenta("Git de um projeto. acao: 'status', 'historico' (últimos commits), 'diff' "
            "(mudanças ainda não salvas), 'sugerir_commit' (mostra as mudanças para você "
            "escrever a mensagem), 'commit' (salva tudo com a mensagem).",
            {"acao": ("string", "status, historico, diff, sugerir_commit ou commit"),
             "pasta": ("string", "Pasta do projeto (padrão: o projeto aberto)"),
             "mensagem": ("string", "Para commit: a mensagem")},
            ["acao"], confirmar=_confirmar_git, grupo="programacao")
def git(acao, pasta="", mensagem=""):
    if not shutil.which("git"):
        return "Erro: instale o git: " + como_instalar("git")
    raiz = caminho_seguro(pasta or pasta_padrao())

    def g(*args):
        r = rodar(["git", "-C", raiz, *args], timeout=60, encoding="utf-8")
        return (r.stdout + r.stderr).strip()

    if "true" not in g("rev-parse", "--is-inside-work-tree"):
        return f"{raiz} não é um repositório git."
    acao = sem_acento(acao)
    if acao == "status":
        return g("status", "--short", "--branch") or "Nada mudou."
    if acao == "historico":
        return g("log", "--oneline", "--decorate", "-15")
    if acao in ("diff", "sugerir_commit"):
        resumo = g("status", "--short")
        diff = g("diff", "HEAD", "--stat") + "\n\n" + g("diff", "HEAD")
        if not resumo:
            return "Não há mudanças para commitar."
        texto = f"Arquivos mudados:\n{resumo}\n\n{diff[:5000]}"
        if acao == "sugerir_commit":
            texto += "\n\nEscreva uma mensagem de commit curta, no imperativo, e pergunte se pode fazer o commit."
        return texto
    if acao == "commit":
        if not mensagem:
            return "Erro: informe a mensagem do commit."
        g("add", "-A")
        return g("commit", "-m", mensagem)
    return "Erro: acao inválida."


ARQ_SERVIDORES = os.path.join(PASTA_DADOS, "servidores.json")


def _confirmar_servidor(args):
    return sem_acento(args.get("acao", "")) == "iniciar"


@ferramenta("Servidor de desenvolvimento local. acao: 'iniciar' (detecta PHP, npm ou "
            "HTML estático), 'parar', 'status', 'abrir' (no navegador), 'logs'.",
            {"acao": ("string", "iniciar, parar, status, abrir ou logs"),
             "pasta": ("string", "Pasta do projeto (padrão: o projeto aberto)"),
             "porta": ("number", "Porta (padrão 8000)")},
            ["acao"], confirmar=_confirmar_servidor, grupo="programacao")
def servidor_dev(acao, pasta="", porta=8000):
    servidores = _ler_json(ARQ_SERVIDORES, {})
    # descarta os que já pararam
    servidores = {c: i for c, i in servidores.items() if processo_vivo(i["pid"])}
    acao = sem_acento(acao)
    if acao == "status":
        _gravar_json(ARQ_SERVIDORES, servidores)
        if not servidores:
            return "Nenhum servidor rodando."
        return "\n".join(f"{i['tipo']} em http://127.0.0.1:{i['porta']} · {p} (PID {i['pid']})"
                         for p, i in servidores.items())
    raiz = caminho_seguro(pasta or pasta_padrao())
    info = servidores.get(raiz)
    if acao == "iniciar":
        if info:
            return f"Já está rodando em http://127.0.0.1:{info['porta']}"
        porta = int(porta or 8000)
        if glob.glob(os.path.join(raiz, "*.php")) and shutil.which("php"):
            tipo, comando = "PHP", [shutil.which("php"), "-S", f"127.0.0.1:{porta}", "-t", raiz]
        elif os.path.exists(os.path.join(raiz, "package.json")) and shutil.which("npm"):
            tipo, comando = "npm", [shutil.which("npm"), "run", "dev", "--", "--port", str(porta)]
        else:
            tipo, comando = "estático", [sys.executable, "-m", "http.server", str(porta),
                                         "--bind", "127.0.0.1", "--directory", raiz]
        os.makedirs(os.path.join(PASTA_DADOS, "servidores"), exist_ok=True)
        log = os.path.join(PASTA_DADOS, "servidores", re.sub(r"\W", "_", raiz) + ".log")
        extra = ({"creationflags": SEM_JANELA | 0x00000200} if EH_WINDOWS
                 else {"start_new_session": True})
        with open(log, "w") as saida:
            proc = subprocess.Popen(comando, cwd=raiz, stdout=saida, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, **extra)
        time.sleep(1.5)
        if proc.poll() is not None:
            with open(log, encoding="utf-8", errors="replace") as f:
                return f"Erro: o servidor fechou. Log:\n{f.read()[-800:]}"
        servidores[raiz] = {"pid": proc.pid, "porta": porta, "tipo": tipo, "log": log}
        _gravar_json(ARQ_SERVIDORES, servidores)
        return f"Servidor {tipo} rodando em http://127.0.0.1:{porta} (continua ligado mesmo se fechar o assistente)."
    if not info:
        return "Não há servidor rodando nessa pasta. Use status para ver os que estão rodando."
    if acao == "parar":
        encerrar_arvore(info["pid"])
        servidores.pop(raiz)
        _gravar_json(ARQ_SERVIDORES, servidores)
        return "Servidor parado."
    if acao == "abrir":
        abrir_externo(f"http://127.0.0.1:{info['porta']}")
        return f"Aberto http://127.0.0.1:{info['porta']} no navegador."
    if acao == "logs":
        with open(info["log"], encoding="utf-8", errors="replace") as f:
            return f.read()[-3000:] or "(log vazio)"
    return "Erro: acao inválida."


# ============================================================================
# Conversa com o Ollama
# ============================================================================
USO_CONTEXTO = {"tokens": 0}


def conversar(mensagens, pensar=False):
    """Envia a conversa ao Ollama e mostra a resposta enquanto ela é gerada."""
    dados = json.dumps({
        "model": MODELO, "messages": mensagens, "stream": True, "think": pensar,
        "tools": ferramentas_ativas(),
        "options": {"num_ctx": CONTEXTO},
    }).encode()
    req = urllib.request.Request(OLLAMA, data=dados,
                                 headers={"Content-Type": "application/json"})
    abridor = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    esperar_esfriar()
    conteudo, pensamento, chamadas = "", "", []
    spinner, render = Spinner(pensando=pensar).iniciar(), None
    ultima_medida = time.time()
    try:
        with abridor.open(req, timeout=600) as resposta:
            for linha in resposta:
                if not linha.strip():
                    continue
                parte = json.loads(linha)
                if parte.get("error"):
                    raise RuntimeError(parte["error"])
                msg = parte.get("message") or {}
                if time.time() - ultima_medida > 3:  # confere a temperatura a cada 3 s
                    ultima_medida = time.time()
                    temp = temperatura_cpu()
                    if temp and temp >= TEMPERATURA_CRITICA:
                        raise RuntimeError(f"o processador chegou a {temp:.0f}°C, parei a "
                                           "resposta para proteger o notebook")
                if msg.get("thinking"):
                    pensamento += msg["thinking"]
                    spinner.extra = f" · ✻ raciocinando, ~{len(pensamento) // 4} tokens"
                if msg.get("content"):
                    if render is None:
                        spinner.parar()
                        render = Renderizador()
                    conteudo += msg["content"]
                    render.alimentar(msg["content"])
                if msg.get("tool_calls"):
                    chamadas.extend(msg["tool_calls"])
                if parte.get("done"):
                    USO_CONTEXTO["tokens"] = (parte.get("prompt_eval_count") or 0) + \
                        (parte.get("eval_count") or 0)
                    break
    finally:
        spinner.parar()
        if render:
            render.fim()
    if pensamento:
        ULTIMO_PENSAMENTO["texto"] = pensamento
    mensagem = {"role": "assistant", "content": conteudo}
    if pensamento:
        mensagem["thinking"] = pensamento
    if chamadas:
        mensagem["tool_calls"] = chamadas
    return mensagem


def rodar_ferramenta(chamada):
    nome = chamada["function"]["name"]
    args = chamada["function"].get("arguments") or {}
    if isinstance(args, str):
        args = json.loads(args or "{}")
    info = FERRAMENTAS.get(nome)
    mostrar_chamada(nome, args)
    if not info:
        resultado = f"Erro: ferramenta desconhecida: {nome}"
        mostrar_resultado(resultado)
        return resultado
    try:
        if nome == "rodar_comando_admin" and not confirmar_admin(args):
            resultado = "O usuário não permitiu esse comando de administrador."
        elif nome == "rodar_comando" and not confirmar_comando(args):
            resultado = "O usuário não permitiu esse comando."
        elif (info["confirmar"](args) if callable(info["confirmar"]) else info["confirmar"]) and perguntar(
                "  Permitir? Digite " + negrito("s") + " para sim: ").strip().lower() != "s":
            resultado = "O usuário não permitiu essa ação."
        else:
            resultado = str(info["func"](**args))
    except TypeError as erro:
        resultado = f"Erro: parâmetros errados para {nome}: {erro}"
    except Exception as erro:
        resultado = f"Erro ao executar {nome}: {erro}"
    mostrar_resultado(resultado, max_linhas=6 if nome == "rodar_comando" else 4)
    return resultado


if EH_WINDOWS:
    DICA_ADMIN_PROMPT = ("Para o que exige administrador (instalar programas com winget, "
                         "serviços e configurações do Windows), use rodar_comando_admin. ")
elif EH_MAC:
    DICA_ADMIN_PROMPT = ("Instale programas com 'brew install' em rodar_comando (sem sudo). "
                         "Para o que exige administrador (arquivos do sistema, pmset), use "
                         "rodar_comando_admin, sem escrever 'sudo'. ")
else:
    DICA_ADMIN_PROMPT = ("Não use sudo em rodar_comando. Para o que exige administrador "
                         f"(instalar programas com {GERENCIADOR or 'o gerenciador de pacotes'}, "
                         "atualizar o sistema, serviços do sistema, arquivos em /etc), use "
                         "rodar_comando_admin, sem escrever 'sudo' e com opções não "
                         "interativas como -y. ")


def prompt_sistema():
    internet = ("Para perguntas sobre fatos, notícias ou qualquer coisa que você não "
                "tenha certeza, use pesquisar_internet e depois ler_pagina, e diga a "
                "fonte (site) na resposta. " if PESQUISA_INTERNET else
                "Você não tem acesso à internet. ")
    return (
        f"Você é o Lumero, um assistente pessoal que roda localmente no computador do usuário "
        f"({NOME_SISTEMA}). "
        "Responda em português do Brasil, de forma curta e direta: o computador é "
        "lento, então cada palavra a mais demora. "
        f"Hoje é {data_hoje()}. A pasta pessoal do usuário é {HOME}. "
        + (f"O nome do usuário é {NOME_USUARIO}: chame-o pelo nome de vez em quando, de forma "
           "natural (por exemplo ao cumprimentar ou concluir uma tarefa), sem repetir em toda frase. "
           "Se ele pedir para ser chamado de outro jeito, diga que é só usar o comando /nome. "
           if NOME_USUARIO else "") +
        "Para saber a hora exata, use data_hora. "
        f"Você está na geração {GERACAO} do seu script. "
        "Use as ferramentas sempre que o pedido envolver o computador, arquivos, "
        "programas, sites ou informações que você não sabe. Não invente resultados. "
        + internet +
        "Para achar arquivos descritos pelo usuário, use buscar_arquivos convertendo "
        "a descrição em palavras, tipo e data; se não achar, tente outras palavras ou "
        "buscar_por_conteudo. Prefira ferramentas específicas; use rodar_comando só "
        f"quando nenhuma outra servir (os comandos são em {SHELL_NOME}). "
        + DICA_ADMIN_PROMPT
        + ("Se o usuário pedir para mudar você mesmo (novas funções, configurações, "
           "comportamento), use ver_proprio_codigo para achar o trecho e depois "
           "editar_proprio_codigo, copiando texto_antigo exatamente. Faça mudanças "
           "pequenas e uma de cada vez. " if AUTOEDICAO else "") +
        "Para apagar arquivos use lixeira (acao 'apagar'). Se o usuário pedir para "
        "lembrar algo para sempre, use memoria; para avisar num horário, lembretes. "
        "Para contas, use calcular em vez de calcular de cabeça. Quando pedirem um "
        "script ou programa, salve com criar_arquivo (na pasta do projeto, se houver; "
        "senão em ~/Scripts) "
        "e, se fizer sentido, ofereça testar com rodar_comando. "
        + projeto_no_prompt()
        + memoria_no_prompt()
    )


def projeto_no_prompt():
    if not PASTA_PROJETO:
        return ""
    tipos = f" ({', '.join(TIPOS_PROJETO)})" if TIPOS_PROJETO else ""
    return (f"\n\nO usuário abriu você dentro do projeto {PASTA_PROJETO}{tipos}. Quando ele "
            "disser 'este projeto', 'aqui', 'o código' ou não disser a pasta, trabalhe nessa "
            "pasta: comandos, git, servidor, criar e ler arquivos usam ela por padrão.")


def memoria_no_prompt():
    fatos = ler_memoria()
    if not fatos:
        return ""
    return ("\n\nO que você sabe sobre o usuário (memória permanente):\n"
            + "\n".join(f"- {f}" for f in fatos))


# ============================================================================
# Resumo automático, salvar e retomar conversas
# ============================================================================
PASTA_CONVERSAS = os.path.join(PASTA_DADOS, "conversas")


def resumir_conversa(mensagens, manter=6):
    """Troca o começo da conversa por um resumo, para caber na memória do modelo."""
    if len(mensagens) <= manter + 2:
        return False
    corte = len(mensagens) - manter
    while corte > 1 and mensagens[corte]["role"] != "user":
        corte -= 1  # começa a parte mantida numa mensagem do usuário
    if corte <= 1:
        return False
    linhas = []
    for m in mensagens[1:corte]:
        texto = (m.get("content") or "").strip()
        if m["role"] == "tool":
            linhas.append(f"[resultado de {m.get('tool_name', 'ferramenta')}]: {texto[:400]}")
        elif m.get("tool_calls"):
            nomes = ", ".join(c["function"]["name"] for c in m["tool_calls"])
            linhas.append(f"assistente usou: {nomes}" + (f" — {texto[:300]}" if texto else ""))
        elif texto:
            quem = "usuário" if m["role"] == "user" else "assistente"
            linhas.append(f"{quem}: {texto[:1200]}")
    transcricao = "\n".join(linhas)[-int(CONTEXTO * 2.5):]
    spinner = Spinner("Resumindo a conversa").iniciar()
    try:
        resposta = ollama_api("/api/chat", {
            "model": MODELO, "stream": False, "think": False,
            "options": {"num_ctx": CONTEXTO},
            "messages": [{"role": "user", "content":
                          "Resuma em português, em até 15 linhas, esta conversa entre um "
                          "usuário e seu assistente. Guarde fatos, decisões, nomes de "
                          "arquivos, pastas, comandos e pedidos ainda pendentes.\n\n"
                          + transcricao}]})
    finally:
        spinner.parar()
    resumo = resposta["message"]["content"].strip()
    antes = len(mensagens)
    mensagens[:] = ([mensagens[0],
                     {"role": "user", "content": "[Resumo da conversa até aqui]\n" + resumo},
                     {"role": "assistant", "content": "Entendido, continuo a partir do resumo."}]
                    + mensagens[corte:])
    print(cinza(f"\n  ⎿  Conversa resumida para economizar memória "
                f"({antes} → {len(mensagens)} mensagens)."))
    return True


def salvar_conversa(mensagens, nome=None):
    os.makedirs(PASTA_CONVERSAS, exist_ok=True)
    titulo = next((m["content"] for m in mensagens[1:] if m["role"] == "user"
                   and not m["content"].startswith("[Resumo")), "conversa")
    if not nome:
        nome = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
    nome = re.sub(r"[^\w\- ]", "", nome).strip() or "conversa"
    caminho = os.path.join(PASTA_CONVERSAS, nome + ".json")
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump({"titulo": titulo[:80], "data": f"{datetime.datetime.now():%d/%m/%Y %H:%M}",
                   "mensagens": mensagens[1:]}, f, ensure_ascii=False, indent=1)
    return caminho


def conversas_salvas():
    arquivos = glob.glob(os.path.join(PASTA_CONVERSAS, "*.json"))
    arquivos.sort(key=os.path.getmtime, reverse=True)
    itens = []
    for arq in arquivos:
        try:
            with open(arq, encoding="utf-8") as f:
                dados = json.load(f)
            itens.append((arq, dados.get("data", ""), dados.get("titulo", "")))
        except (OSError, ValueError):
            pass
    return itens


def retomar_conversa(mensagens, qual=""):
    itens = conversas_salvas()
    if not itens:
        return "Não há conversas salvas."
    if not qual:
        escolhido = next((i for i in itens if os.path.basename(i[0]) == "ultima.json"), itens[0])
    elif qual.isdigit() and 1 <= int(qual) <= len(itens):
        escolhido = itens[int(qual) - 1]
    else:
        achados = [i for i in itens if sem_acento(qual) in sem_acento(os.path.basename(i[0]) + i[2])]
        if not achados:
            return f"Nenhuma conversa com '{qual}'. Use /conversas para ver a lista."
        escolhido = achados[0]
    with open(escolhido[0], encoding="utf-8") as f:
        dados = json.load(f)
    mensagens[:] = [{"role": "system", "content": prompt_sistema()}] + dados["mensagens"]
    return f"Conversa retomada: {escolhido[2]} ({escolhido[1]}, {len(dados['mensagens'])} mensagens)"


# ============================================================================
# Voz: falar com o assistente e ouvir as respostas (tudo offline)
# ============================================================================
PASTA_VOZ = os.path.join(PASTA_DADOS, "voz")
FALAR_RESPOSTAS = {"ligado": False}
_WHISPER = {"modelo": None}
_FALA_ATUAL = {"processos": []}


def _carregar_whisper():
    """Usa o pywhispercpp (whisper.cpp) ou, se não houver, o faster-whisper."""
    if _WHISPER["modelo"] is not None:
        return
    pasta = os.path.join(PASTA_VOZ, "whisper")
    os.makedirs(pasta, exist_ok=True)
    print(cinza("     Carregando o reconhecimento de voz (na 1ª vez baixa o modelo)..."))
    try:
        from pywhispercpp.model import Model
        modelo = Model(WHISPER_MODELO, models_dir=pasta, redirect_whispercpp_logs_to=None,
                       n_threads=max(1, min(4, (os.cpu_count() or 2) - 1)))
        _WHISPER["modelo"] = lambda arq: " ".join(
            seg.text.strip() for seg in modelo.transcribe(arq, language="pt"))
        return
    except ImportError:
        pass
    from faster_whisper import WhisperModel
    modelo = WhisperModel(WHISPER_MODELO, device="cpu", compute_type="int8", download_root=pasta)
    _WHISPER["modelo"] = lambda arq: " ".join(
        seg.text.strip() for seg in modelo.transcribe(arq, language="pt")[0])


def _gravar_pipewire(arquivo):
    gravador = subprocess.Popen(["pw-record", "--rate", "16000", "--channels", "1",
                                 "--format", "s16", arquivo],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    inicio = time.time()
    try:
        perguntar("  " + vermelho("●") + " Gravando... fale e aperte " + negrito("Enter") + " para parar ")
    finally:
        time.sleep(max(0.0, 0.6 - (time.time() - inicio)))  # deixa o gravador iniciar
        gravador.send_signal(signal.SIGINT)  # o pw-record fecha o arquivo direitinho
        try:
            gravador.wait(timeout=5)
        except subprocess.TimeoutExpired:
            gravador.kill()
    return None


def _gravar_sounddevice(arquivo):
    try:
        import numpy
        import sounddevice
    except (ImportError, OSError):
        return "Microfone não configurado. Rode o instalador da voz do Lumero."
    blocos = []
    try:
        with sounddevice.InputStream(samplerate=16000, channels=1, dtype="int16",
                                     callback=lambda dados, *_: blocos.append(dados.copy())):
            perguntar("  " + vermelho("●") + " Gravando... fale e aperte " + negrito("Enter")
                      + " para parar ")
    except KeyboardInterrupt:
        raise
    except Exception as erro:
        return f"Não consegui usar o microfone: {erro}"
    if not blocos:
        return "A gravação ficou vazia. Confira o microfone."
    import wave
    with wave.open(arquivo, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(numpy.concatenate(blocos).tobytes())
    return None


def gravar_e_transcrever():
    try:
        _carregar_whisper()
    except ImportError:
        return None, "Reconhecimento de voz não instalado. Rode o instalador da voz do Lumero."
    arquivo = os.path.join(tempfile.gettempdir(), f"lumero-voz-{os.getpid()}.wav")
    if EH_LINUX and shutil.which("pw-record"):
        erro = _gravar_pipewire(arquivo)
    else:
        erro = _gravar_sounddevice(arquivo)
    if erro:
        return None, erro
    if not os.path.exists(arquivo) or os.path.getsize(arquivo) < 16000:
        return None, "A gravação ficou vazia ou curta demais. Confira o microfone."
    spinner = Spinner("Transcrevendo").iniciar()
    try:
        texto = _WHISPER["modelo"](arquivo).strip()
    finally:
        spinner.parar()
        try:
            os.remove(arquivo)
        except OSError:
            pass
    return texto, None if texto else "Não entendi nada no áudio."


def parar_fala():
    for p in _FALA_ATUAL["processos"]:
        if p.poll() is None:
            p.terminate()
    _FALA_ATUAL["processos"] = []
    if EH_WINDOWS:
        import winsound
        winsound.PlaySound(None, 0)  # para o som que estiver tocando


FALA_WINDOWS_PS1 = """
Add-Type -AssemblyName System.Speech
$voz = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $escolhida = $null
    if (__VOZ__) { $escolhida = $voz.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Name -like ('*' + __VOZ__ + '*') } | Select-Object -First 1 }
    if (-not $escolhida) { $escolhida = $voz.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -eq 'pt-BR' } | Select-Object -First 1 }
    if ($escolhida) { $voz.SelectVoice($escolhida.VoiceInfo.Name) }
} catch {}
$voz.Rate = 1
$voz.Speak((Get-Content -LiteralPath __ARQUIVO__ -Raw -Encoding UTF8))
"""


def _tocar_wav(wav):
    if EH_WINDOWS:
        import winsound
        winsound.PlaySound(wav, winsound.SND_FILENAME)
        return
    tocador = (["afplay"] if EH_MAC else
               next(([c] for c in ("pw-play", "paplay", "aplay") if shutil.which(c)), None))
    if tocador:
        p = subprocess.Popen(tocador + [wav], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _FALA_ATUAL["processos"].append(p)
        p.wait()


def _python_piper():
    pasta = os.path.join(PASTA_VOZ, "piper-venv")
    return os.path.join(pasta, "Scripts", "python.exe") if EH_WINDOWS else \
        os.path.join(pasta, "bin", "python")


def falar(texto):
    """Lê a resposta em voz alta, sem travar o assistente."""
    texto = re.sub(r"```.*?```", " (código) ", texto, flags=re.S)
    texto = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", texto)
    texto = re.sub(r"https?://\S+", "", texto)
    texto = re.sub(r"[*_`#>|]", "", texto).strip()[:1500]
    if not texto:
        return
    python_piper = _python_piper()
    voz_piper = os.path.exists(os.path.join(PASTA_VOZ, VOZ_PIPER + ".onnx"))
    pasta = os.path.join(PASTA_DADOS, "tmp")
    os.makedirs(pasta, exist_ok=True)

    def tocar():
        if os.path.exists(python_piper) and voz_piper:  # voz neural (Piper), igual em todo sistema
            wav = os.path.join(pasta, f"fala-{os.getpid()}.wav")
            p = subprocess.Popen([python_piper, "-m", "piper", "-m", VOZ_PIPER, "--data-dir",
                                  PASTA_VOZ, "-f", wav, "--", texto], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, creationflags=SEM_JANELA)
            _FALA_ATUAL["processos"].append(p)
            if p.wait() == 0:
                _tocar_wav(wav)
            return
        if EH_WINDOWS:   # voz do próprio Windows (Maria, Francisca...)
            arq_texto = os.path.join(pasta, "fala.txt")
            script = os.path.join(pasta, "fala.ps1")
            with open(arq_texto, "w", encoding="utf-8-sig") as f:
                f.write(texto)
            with open(script, "w", encoding="utf-8-sig") as f:
                f.write(FALA_WINDOWS_PS1.replace("__VOZ__", ps_str(VOZ_SISTEMA))
                                        .replace("__ARQUIVO__", ps_str(arq_texto)))
            comando = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script]
        elif EH_MAC:     # voz do próprio macOS (Luciana)
            comando = ["say", "-v", VOZ_SISTEMA or "Luciana", texto]
        elif shutil.which("espeak-ng"):
            comando = ["espeak-ng", "-v", VOZ_SISTEMA or "pt-br", "-s", "165", texto]
        else:
            return
        p = subprocess.Popen(comando, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=SEM_JANELA)
        _FALA_ATUAL["processos"].append(p)
        p.wait()

    parar_fala()
    threading.Thread(target=tocar, daemon=True).start()


# ============================================================================
# Laço principal
# ============================================================================
def processar(texto, mensagens):
    """Manda uma mensagem do usuário para a IA e executa as ferramentas pedidas."""
    parar_fala()
    mensagens[0]["content"] = prompt_sistema()  # atualiza data, memória etc.
    if USO_CONTEXTO["tokens"] > CONTEXTO * 0.7 or len(mensagens) > 60:
        try:
            resumir_conversa(mensagens)
            USO_CONTEXTO["tokens"] = 0
        except Exception as erro:
            print(vermelho(f"\n  ⎿  Não consegui resumir ({erro}); cortando mensagens antigas."))
            mensagens[:] = mensagens[:1] + mensagens[-30:]
            while len(mensagens) > 1 and mensagens[1]["role"] != "user":
                mensagens.pop(1)

    pensar, texto = decidir_pensar(texto)
    for grupo in ativar_grupos(texto):
        print(cinza(f"  ⎿  ferramentas de {NOMES_GRUPOS.get(grupo, grupo)} ligadas"))
    mensagens.append({"role": "user", "content": texto})
    resposta = None
    usadas = []
    CONTEXTO_SUGESTAO["proxima"] = ""
    try:
        resposta = conversar(mensagens, pensar)
        mensagens.append(resposta)
        rodadas = 0
        while resposta.get("tool_calls") and rodadas < 8:
            resultados = []
            for chamada in resposta["tool_calls"]:
                usadas.append(chamada["function"]["name"])
                resultado = rodar_ferramenta(chamada)
                resultados.append(resultado)
                mensagens.append({"role": "tool", "content": resultado,
                                  "tool_name": chamada["function"]["name"]})
            pensar = pensar_na_proxima_rodada(pensar, resposta["tool_calls"], resultados)
            resposta = conversar(mensagens, pensar)
            mensagens.append(resposta)
            rodadas += 1
    except KeyboardInterrupt:
        print(vermelho("\n  ⎿  Interrompido pelo usuário"))
        mensagens.append({"role": "assistant", "content": "(resposta interrompida pelo usuário)"})
        return
    except urllib.error.URLError:
        print(vermelho("\n  ⎿  Não consegui falar com o Ollama. Tentando ligar de novo..."))
        if garantir_ollama() is None:
            print(cinza("     Pronto, pode mandar a mensagem de novo."))
        mensagens.pop()
        return
    except RuntimeError as erro:
        print(vermelho(f"\n  ⎿  Erro do Ollama: {erro}"))
        mensagens.pop()
        return

    preparar_sugestao(resposta.get("content") if resposta else "", usadas)
    if FALAR_RESPOSTAS["ligado"] and resposta and resposta.get("content"):
        falar(resposta["content"])
    try:
        salvar_conversa(mensagens, "ultima")
    except OSError:
        pass


def main():
    preparar_historico()
    erro = garantir_ollama()
    cabecalho()
    if erro:
        dica = ("" if "instalado" in erro else
                "Confira com: systemctl status ollama" if _ollama_servico_systemd() else
                f"Veja o registro em {os.path.join(PASTA_DADOS, 'ollama.log')}")
        print(vermelho(f"\n  ⎿  {erro} {dica}"))
    mensagens = [{"role": "system", "content": prompt_sistema()}]
    ctrl_c = 0

    while True:
        try:
            texto = ler_entrada().strip()
            ctrl_c = 0
        except EOFError:
            break
        except KeyboardInterrupt:
            ctrl_c += 1
            if ctrl_c >= 2:
                break
            print(cinza("  Pressione Ctrl+C de novo para sair"))
            continue
        if not texto:
            continue
        if texto.startswith("/"):
            acao = tratar_comando(texto, mensagens)
            if acao == "sair":
                break
            if isinstance(acao, tuple) and acao[0] == "mensagem":
                processar(acao[1], mensagens)
        elif texto.lower() in ("sair", "exit"):
            break
        else:
            processar(texto, mensagens)

        if REINICIAR["pendente"]:
            print(cinza("\n  🔄 Reiniciando o assistente para aplicar a alteração..."))
            if OLLAMA_LIGADO_POR_MIM["sim"]:  # o Ollama segue ligado e será desligado depois
                os.environ["LUMERO_DESLIGAR_OLLAMA"] = "1"
                os.environ["LUMERO_OLLAMA_PID"] = str(OLLAMA_LIGADO_POR_MIM["pid"] or "")
            if EH_WINDOWS:  # no Windows o execv abre outro console: roda o novo e espera
                os._exit(subprocess.call([sys.executable, ESTE_SCRIPT] + sys.argv[1:]))
            os.execv(sys.executable, [sys.executable, ESTE_SCRIPT] + sys.argv[1:])

    parar_fala()
    desligar_ollama()
    print(cinza("\n  Até mais!"))
    os._exit(0)


if __name__ == "__main__":
    if "--versao" in sys.argv or "--version" in sys.argv:
        print(f"Lumero {VERSAO} (geração {GERACAO}) · {NOME_SISTEMA}")
        sys.exit(0)
    main()
