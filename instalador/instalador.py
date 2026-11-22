#!/usr/bin/env python3
"""
Instalador com janela do Lumero (Linux, Windows e macOS).

Analisa o computador, mostra os modelos que cabem nele (e onde cada um roda: placa
de vídeo, placa + processador ou só processador), pergunta as opções e roda os
scripts de instalação de cada sistema mostrando o progresso.

Só usa a biblioteca padrão do Python, porque roda antes de instalar qualquer coisa.
A janela é a do próprio sistema quando dá (GTK + WebKit no Linux); se não der, abre
no navegador em modo aplicativo. Tudo fica em 127.0.0.1, com uma senha de sessão.

Opções:  --sem-registro  (Windows, usado pelo Setup.exe)   --sem-app  (Mac, usado pelo .dmg)
         --pacote        (Linux, instalado por .deb/.rpm: só configura o Ollama e os modelos)
         --navegador     abre no navegador em vez da janela própria
"""
import getpass
import http.server
import json
import os
import queue
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import webbrowser

AQUI = os.path.dirname(os.path.realpath(__file__))
RAIZ = os.path.dirname(AQUI)
sys.path.insert(0, AQUI)
import hardware as HW  # noqa: E402

SO = HW.SO
PACOTE = "--pacote" in sys.argv
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07")
ESTADO = {"token": secrets.token_urlsafe(24), "porta": 0, "ocupado": False, "terminou": False,
          "sucesso": False, "ultimo_sinal": time.time(), "janela_nativa": False}
OUVINTES, _TRAVA = [], threading.Lock()
VERSAO = "?"
try:
    with open(os.path.join(RAIZ, "lumero.py"), encoding="utf-8") as _f:
        VERSAO = (re.search(r'^VERSAO = "([^"]+)"', _f.read(), re.M) or [None, "?"])[1]
except OSError:
    pass


def evento(tipo, **dados):
    texto = json.dumps({"tipo": tipo, **dados}, ensure_ascii=False)
    with _TRAVA:
        for fila in OUVINTES:
            fila.put(texto)


# ============================================================================
# O que este sistema oferece
# ============================================================================
def info():
    analise_bateria = HW.tem_bateria()
    return {
        "so": SO, "versao": VERSAO, "pacote": PACOTE, "usuario": getpass.getuser(),
        "nome": HW.nome_sugerido(),
        "opcoes": {
            "bloquear": SO in ("linux", "windows"),
            "eco": SO == "linux" and analise_bateria,
            "extras": SO == "windows",
            "atalho_area": SO == "windows",
            "autostart": SO == "windows",
            "voz": not PACOTE,
        },
    }


# ============================================================================
# Rodar os scripts e transformar a saída em progresso
# ============================================================================
ETAPAS = {
    "pacotes": "Programas necessários",
    "ollama": "Ollama (o motor da IA)",
    "modelos": "Modelos de IA",
    "lumero": "Lumero e atalhos",
    "seguranca": "Segurança e últimos ajustes",
    "voz": "Voz",
}


def _askpass_mac():
    """Janela de senha do macOS para o Homebrew (que usa sudo)."""
    caminho = os.path.join(tempfile.gettempdir(), f"lumero-senha-{os.getpid()}.sh")
    with open(caminho, "w") as f:
        f.write("#!/bin/bash\n"
                "osascript -e 'display dialog \"O instalador do Lumero precisa da sua senha do Mac "
                "para instalar o Homebrew (o instalador de programas).\" default answer \"\" "
                "with hidden answer with title \"Lumero\" with icon caution' "
                "-e 'text returned of result'\n")
    os.chmod(caminho, 0o700)
    return caminho


def montar_comandos(op):
    """Lista de (comando, ambiente extra) para este sistema."""
    modelos = [m for m in op.get("modelos", []) if re.fullmatch(r"[\w.:-]+", m)]
    sim = lambda chave: "1" if op.get(chave) else "0"  # noqa: E731
    if SO == "linux":
        raiz_sh = os.path.join(RAIZ, "raiz.sh") if PACOTE else os.path.join(RAIZ, "linux", "raiz.sh")
        root = ["/bin/bash", raiz_sh, "--usuario", getpass.getuser(),
                "--pacotes", "0" if PACOTE else "1", "--voz", sim("voz"), "--ollama", "1",
                "--so-cpu", sim("so_cpu"), "--eco", sim("eco"), "--bloquear", sim("bloquear"),
                "--modelos", " ".join(modelos)]
        if shutil.which("pkexec"):
            root = ["pkexec"] + root
        else:
            return None, ("Este sistema não tem o pkexec (a janela de senha). Instale pelo terminal: "
                          "bash linux/instalar.sh --terminal")
        comandos = [(root, {})]
        if not PACOTE:
            comandos.append((["/bin/bash", os.path.join(RAIZ, "linux", "usuario.sh"),
                              "--modelo", modelos[0] if modelos else "", "--voz", sim("voz")], {}))
        return comandos, None
    if SO == "mac":
        comando = ["/bin/bash", os.path.join(RAIZ, "mac", "instalar.sh"), "--nao-interativo",
                   "--modelos", " ".join(modelos), "--voz" if op.get("voz") else "--sem-voz"]
        if "--sem-app" in sys.argv:
            comando.append("--sem-app")
        return [(comando, {"SUDO_ASKPASS": _askpass_mac()})], None
    comando = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
               os.path.join(RAIZ, "windows", "instalar.ps1"), "-NaoInterativo", "-SemPausa",
               "-Modelos", ",".join(modelos) or ","]
    for chave, chave_ps in (("so_cpu", "-SoCpu"), ("bloquear", "-Bloquear"), ("extras", "-Extras"),
                            ("atalho_area", "-AtalhoArea"), ("manter_autostart", "-ManterAutostart"),
                            ("voz", "-Voz")):
        if op.get(chave):
            comando.append(chave_ps)
    if not op.get("voz"):
        comando.append("-SemVoz")
    if "--sem-registro" in sys.argv:
        comando.append("-SemRegistro")
    return [(comando, {})], None


def rodar_comando(comando, ambiente, ultimas):
    """Roda um script e manda o progresso para a janela. Devolve o código de saída."""
    env = dict(os.environ, **ambiente)
    env["PYTHONIOENCODING"] = "utf-8"
    extra = {"creationflags": 0x08000000} if SO == "windows" else {}
    proc = subprocess.Popen(comando, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, env=env, **extra)
    buffer = b""
    while True:
        pedaco = proc.stdout.read1(4096) if hasattr(proc.stdout, "read1") else proc.stdout.read(1)
        if not pedaco:
            break
        buffer += pedaco
        partes = re.split(rb"[\r\n]", buffer)
        buffer = partes.pop()
        for bruto in partes:
            tratar_linha(bruto, ultimas)
    if buffer:
        tratar_linha(buffer, ultimas)
    return proc.wait()


def tratar_linha(bruto, ultimas):
    linha = ANSI.sub("", bruto.decode("utf-8", "replace")).strip()
    if not linha:
        return
    if linha.startswith("##PASSO "):
        evento("etapa", id=linha.split(None, 1)[1].strip())
        return
    if linha.startswith("##MODELO "):
        evento("modelo", nome=linha.split(None, 1)[1].strip())
        return
    if linha.startswith("##ERRO "):
        evento("log", texto="Erro: " + linha[7:], erro=True)
        ultimas.append(linha[7:])
        return
    if linha.startswith("##"):
        return
    porcentagem = re.search(r"(\d{1,3})%", linha)
    if porcentagem and ("pulling" in linha or "baixando" in linha.lower() or "%" in linha):
        evento("progresso", pct=min(100, int(porcentagem.group(1))), texto=linha[:160])
        return
    ultimas.append(linha)
    del ultimas[:-30]
    evento("log", texto=linha[:400])


def instalar(op):
    comandos, erro = montar_comandos(op)
    if erro:
        evento("fim", sucesso=False, mensagem=erro)
        ESTADO["ocupado"] = False
        return
    ultimas = []
    sucesso, mensagem = True, ""
    try:
        for comando, ambiente in comandos:
            if comando[0] == "pkexec":
                evento("log", texto="Digite a sua senha na janela do sistema para continuar.")
                evento("senha")
            codigo = rodar_comando(comando, ambiente, ultimas)
            if codigo != 0:
                sucesso = False
                if comando[0] == "pkexec" and codigo in (126, 127):
                    mensagem = "A janela de senha foi cancelada ou a senha não foi aceita."
                else:
                    mensagem = next((l for l in reversed(ultimas) if l), "") or f"O instalador parou (código {codigo})."
                break
        if sucesso:
            valores = {}
            nome = HW.limpar_nome(op.get("nome"))
            if nome:
                valores["NOME_USUARIO"] = nome
            if PACOTE and op.get("modelos"):
                valores["MODELO"] = op["modelos"][0]
            if op.get("modelos"):
                item = next((m for m in HW.analisar(bool(op.get("so_cpu")))["modelos"]
                             if m["nome"] == op["modelos"][0]), None)
                if item:
                    valores["CONTEXTO"] = valores["CONTEXTO_RECOMENDADO"] = item["contexto"]
            if valores:
                HW.gravar_config(**valores)
    except Exception as erro:
        sucesso, mensagem = False, f"Erro inesperado: {erro}"
    ESTADO.update(ocupado=False, terminou=True, sucesso=sucesso)
    evento("fim", sucesso=sucesso, mensagem=mensagem)


def abrir_lumero():
    home = os.path.expanduser("~")
    if SO == "linux":
        for c in (os.path.join(home, ".local", "bin", "lumero-gui"), "/usr/bin/lumero-gui"):
            if os.path.exists(c):
                subprocess.Popen([c], start_new_session=True, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
                return True
    elif SO == "mac":
        dado = sys.argv[sys.argv.index("--app") + 1] if "--app" in sys.argv[:-1] else None
        for app in ([dado] if dado else []) + [os.path.join(home, "Applications", "Lumero.app"),
                                                "/Applications/Lumero.app"]:
            if os.path.exists(app):
                subprocess.Popen(["open", app])
                return True
    else:
        dados = os.path.join(os.environ.get("LOCALAPPDATA", home), "Lumero")
        pythonw = os.path.join(dados, "venv", "Scripts", "pythonw.exe")
        if os.path.exists(pythonw):
            subprocess.Popen([pythonw, os.path.join(dados, "lumero_gui.py")], creationflags=0x08000000)
            return True
    return False


# ============================================================================
# Servidor da página
# ============================================================================
def _icone():
    for c in (os.path.join(RAIZ, "assets", "lumero.svg"), os.path.join(RAIZ, "lumero.svg")):
        if os.path.exists(c):
            with open(c, "rb") as f:
                return f.read()
    return b""


class Pedido(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _host_ok(self):
        porta = ESTADO["porta"]
        return self.headers.get("Host", "") in (f"127.0.0.1:{porta}", f"localhost:{porta}")

    def _token_ok(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        recebido = self.headers.get("X-Token") or (q.get("t") or [""])[0]
        return secrets.compare_digest(recebido, ESTADO["token"])

    def _enviar(self, codigo, corpo, tipo="application/json; charset=utf-8"):
        dados = corpo if isinstance(corpo, bytes) else json.dumps(corpo, ensure_ascii=False).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(dados)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(dados)

    def do_GET(self):
        if not self._host_ok():
            return self._enviar(403, {"erro": "host"})
        caminho = urllib.parse.urlparse(self.path).path
        if caminho in ("/", "/index.html"):
            with open(os.path.join(AQUI, "instalador.html"), "rb") as f:
                return self._enviar(200, f.read(), "text/html; charset=utf-8")
        if caminho == "/icone.svg":
            return self._enviar(200, _icone(), "image/svg+xml")
        if not self._token_ok():
            return self._enviar(403, {"erro": "token"})
        ESTADO["ultimo_sinal"] = time.time()
        if caminho == "/api/info":
            return self._enviar(200, info())
        if caminho == "/api/analise":
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            return self._enviar(200, HW.analisar(forcar_cpu=(q.get("so_cpu") or ["0"])[0] == "1"))
        if caminho == "/api/eventos":
            return self._eventos()
        return self._enviar(404, {"erro": "não encontrado"})

    def _eventos(self):
        fila = queue.Queue()
        with _TRAVA:
            OUVINTES.append(fila)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(b": ok\n\n")
            self.wfile.flush()
            while True:
                try:
                    self.wfile.write(b"data: " + fila.get(timeout=15).encode() + b"\n\n")
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    ESTADO["ultimo_sinal"] = time.time()
                self.wfile.flush()
        except (OSError, ValueError):
            pass
        finally:
            with _TRAVA:
                if fila in OUVINTES:
                    OUVINTES.remove(fila)
            self.close_connection = True

    def do_POST(self):
        if not self._host_ok() or not self._token_ok():
            return self._enviar(403, {"erro": "sem permissão"})
        ESTADO["ultimo_sinal"] = time.time()
        caminho = urllib.parse.urlparse(self.path).path
        tamanho = int(self.headers.get("Content-Length") or 0)
        try:
            dados = json.loads(self.rfile.read(tamanho) or b"{}") if tamanho else {}
        except ValueError:
            return self._enviar(400, {"erro": "json"})
        if caminho == "/api/instalar":
            if ESTADO["ocupado"]:
                return self._enviar(409, {"erro": "a instalação já está rodando"})
            ESTADO.update(ocupado=True, terminou=False)
            threading.Thread(target=instalar, args=(dados,), daemon=True).start()
            return self._enviar(200, {"ok": True})
        if caminho == "/api/abrir_lumero":
            return self._enviar(200, {"ok": abrir_lumero()})
        if caminho == "/api/sair":
            self._enviar(200, {"ok": True})
            if not ESTADO["ocupado"]:
                threading.Timer(0.5, lambda: os._exit(0)).start()
            return None
        if caminho == "/api/vivo":
            return self._enviar(200, {"ok": True})
        return self._enviar(404, {"erro": "não encontrado"})


class Servidor(http.server.ThreadingHTTPServer):
    daemon_threads = True


# ============================================================================
# Janela
# ============================================================================
def janela_gtk(url):
    """Linux: janela própria com o WebKit do sistema (GTK 4 ou GTK 3). Bloqueia até fechar."""
    import gi
    tentativas = [("4.0", "WebKit", "6.0"), ("3.0", "WebKit2", "4.1"), ("3.0", "WebKit2", "4.0")]
    for versao_gtk, modulo, versao in tentativas:
        try:
            gi.require_version("Gtk", versao_gtk)
            gi.require_version(modulo, versao)
            break
        except (ValueError, ImportError):
            continue
    else:
        raise RuntimeError("sem WebKitGTK")
    from gi.repository import GLib, Gtk
    webkit = __import__("gi.repository." + modulo, fromlist=[modulo])
    GLib.set_prgname("lumero-instalador")
    GLib.set_application_name("Instalador do Lumero")

    def pode_fechar(*_):
        if ESTADO["ocupado"]:
            evento("aviso_fechar")
            return True  # não fecha no meio da instalação
        os._exit(0)

    view = webkit.WebView()
    view.load_uri(url)
    icone = os.path.join(RAIZ, "assets", "lumero.svg")
    if versao_gtk == "4.0":
        app = Gtk.Application(application_id="com.lumero.Instalador")

        def ativar(aplicativo):
            janela = Gtk.ApplicationWindow(application=aplicativo, title="Instalador do Lumero")
            janela.set_default_size(980, 720)
            janela.set_child(view)
            janela.connect("close-request", pode_fechar)
            janela.present()
        app.connect("activate", ativar)
        ESTADO["janela_nativa"] = True
        app.run([])
    else:
        janela = Gtk.Window(title="Instalador do Lumero")
        janela.set_default_size(980, 720)
        if os.path.exists(icone):
            try:
                janela.set_icon_from_file(icone)
            except Exception:
                pass
        janela.add(view)
        janela.connect("delete-event", pode_fechar)
        janela.show_all()
        ESTADO["janela_nativa"] = True
        Gtk.main()


def abrir_janela(url):
    """True se a janela segura o programa até fechar; False se abriu num navegador."""
    if SO == "linux" and "--navegador" not in sys.argv:
        try:
            janela_gtk(url)
            return True
        except Exception as erro:
            print(f"Janela própria indisponível ({erro}); abrindo no navegador.")
    if SO == "windows":
        for base in (os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", "")):
            edge = os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe")
            if base and os.path.exists(edge):
                subprocess.Popen([edge, f"--app={url}", "--window-size=1000,760"])
                return False
    if SO == "linux":
        for nome in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                     "brave-browser", "microsoft-edge"):
            caminho = shutil.which(nome)
            if caminho:
                subprocess.Popen([caminho, f"--app={url}", "--window-size=1000,760"],
                                 start_new_session=True, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
                return False
    webbrowser.open(url)
    return False


def vigiar():
    """Modo navegador: fecha quando a página some (e nada está instalando)."""
    while True:
        time.sleep(5)
        with _TRAVA:
            conectados = len(OUVINTES)
        if not ESTADO["ocupado"] and conectados == 0 and time.time() - ESTADO["ultimo_sinal"] > 90:
            os._exit(0)


def main():
    if "--analise" in sys.argv:  # depuração
        print(json.dumps(HW.analisar(), ensure_ascii=False, indent=1))
        return
    servidor = Servidor(("127.0.0.1", 0), Pedido)
    ESTADO["porta"] = servidor.server_address[1]
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{ESTADO['porta']}/#t={ESTADO['token']}"
    if abrir_janela(url):
        while ESTADO["ocupado"]:  # a janela fechou, mas a instalação ainda roda
            time.sleep(1)
        os._exit(0)
    threading.Thread(target=vigiar, daemon=True).start()
    print(f"Instalador do Lumero aberto no navegador: {url}")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        os._exit(0)


if __name__ == "__main__":
    main()
