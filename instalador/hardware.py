"""
Análise do computador para o Lumero: processador, memória, placa de vídeo e disco,
e onde cada modelo de IA consegue rodar (placa de vídeo, placa + processador, só
processador) com uma estimativa de velocidade.

Só usa a biblioteca padrão do Python (roda antes de instalar qualquer coisa).
Uso no terminal:  python3 hardware.py          (mostra a análise)
                  python3 hardware.py --json   (para os instaladores)
"""
import json
import os
import platform
import re
import shutil
import subprocess
import sys

SO = "windows" if os.name == "nt" else ("mac" if sys.platform == "darwin" else "linux")
GB = 1024 ** 3

# ----------------------------------------------------------------------------
# Modelos oferecidos (família Qwen 3.5 do Ollama: texto + imagem, ferramentas e
# raciocínio). "ativo_gb" é o quanto do modelo é lido a cada palavra gerada:
# nos modelos MoE (35b e 122b) só uma parte trabalha de cada vez, por isso são
# rápidos para o tamanho.
# ----------------------------------------------------------------------------
MODELOS = [
    {"nome": "qwen3.5:0.8b", "rotulo": "Qwen 3.5 · 0,8B", "tamanho_gb": 1.0, "ativo_gb": 0.75,
     "qualidade": 1, "descricao": "Mínimo: para computadores bem fracos. Responde rápido, mas erra bastante."},
    {"nome": "qwen3.5:2b", "rotulo": "Qwen 3.5 · 2B", "tamanho_gb": 2.7, "ativo_gb": 2.2,
     "qualidade": 2, "descricao": "Leve: bom para tarefas simples e perguntas rápidas."},
    {"nome": "qwen3.5:4b", "rotulo": "Qwen 3.5 · 4B", "tamanho_gb": 3.4, "ativo_gb": 2.9,
     "qualidade": 3, "descricao": "Equilibrado: bom em quase tudo, usa bem as ferramentas."},
    {"nome": "qwen3.5:9b", "rotulo": "Qwen 3.5 · 9B", "tamanho_gb": 6.6, "ativo_gb": 5.8,
     "qualidade": 4, "descricao": "Esperto: bem melhor em raciocínio, código e tarefas com vários passos."},
    {"nome": "qwen3.5:27b", "rotulo": "Qwen 3.5 · 27B", "tamanho_gb": 17.0, "ativo_gb": 15.5,
     "qualidade": 5, "descricao": "Muito esperto: próximo dos modelos da internet. Precisa de placa de vídeo forte."},
    {"nome": "qwen3.5:35b", "rotulo": "Qwen 3.5 · 35B (MoE)", "tamanho_gb": 24.0, "ativo_gb": 2.2,
     "qualidade": 5, "descricao": "Muito esperto e rápido para o tamanho: só ~3B trabalham de cada vez. "
                                   "Precisa de bastante memória."},
    {"nome": "qwen3.5:122b", "rotulo": "Qwen 3.5 · 122B (MoE)", "tamanho_gb": 81.0, "ativo_gb": 7.0,
     "qualidade": 6, "descricao": "Topo de linha: para estações de trabalho com muita memória."},
]

VELOCIDADES = [(15, "rapido", "rápido"), (6, "bom", "bom"), (2.5, "lento", "lento"),
               (0, "muito_lento", "muito lento")]


def _rodar(comando, timeout=15):
    try:
        r = subprocess.run(comando, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace",
                           creationflags=0x08000000 if SO == "windows" else 0)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


# ============================================================================
# Processador e memória
# ============================================================================
def processador():
    nome, avx2 = platform.processor() or "", None
    if SO == "linux":
        try:
            with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as f:
                texto = f.read()
            achado = re.search(r"^model name\s*:\s*(.+)$", texto, re.M)
            nome = achado.group(1).strip() if achado else nome
            bandeiras = re.search(r"^flags\s*:\s*(.+)$", texto, re.M)
            avx2 = bool(bandeiras and " avx2" in " " + bandeiras.group(1))
            if platform.machine() in ("aarch64", "arm64"):
                avx2 = None
        except OSError:
            pass
    elif SO == "mac":
        nome = _rodar(["sysctl", "-n", "machdep.cpu.brand_string"]).strip() or nome
        if platform.machine() == "x86_64":
            avx2 = "AVX2" in _rodar(["sysctl", "-n", "machdep.cpu.leaf7_features"])
    else:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
                nome = winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
        except OSError:
            pass
        try:
            import ctypes
            avx2 = bool(ctypes.windll.kernel32.IsProcessorFeaturePresent(40))  # AVX2
        except Exception:
            pass
    return {"nome": re.sub(r"\s+", " ", nome or "Processador"), "nucleos": os.cpu_count() or 1,
            "avx2": avx2, "arm": platform.machine().lower() in ("arm64", "aarch64")}


def memoria_gb():
    if SO == "linux":
        try:
            with open("/proc/meminfo") as f:
                for linha in f:
                    if linha.startswith("MemTotal:"):
                        return int(linha.split()[1]) / 1024 / 1024
        except OSError:
            pass
    elif SO == "mac":
        valor = _rodar(["sysctl", "-n", "hw.memsize"]).strip()
        if valor.isdigit():
            return int(valor) / GB
    else:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        estado = MEMORYSTATUSEX()
        estado.dwLength = ctypes.sizeof(estado)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(estado)):
            return estado.ullTotalPhys / GB
    return 8.0


def tem_bateria():
    if SO == "linux":
        import glob
        return bool(glob.glob("/sys/class/power_supply/BAT*"))
    if SO == "mac":
        return "InternalBattery" in _rodar(["pmset", "-g", "batt"])
    try:
        import ctypes

        class SYSTEM_POWER_STATUS(ctypes.Structure):
            _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                        ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                        ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]
        estado = SYSTEM_POWER_STATUS()
        if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(estado)):
            return estado.BatteryFlag not in (128, 255)  # 128 = sem bateria
    except Exception:
        pass
    return False


def disco_livre_gb():
    pasta = os.path.expanduser("~")
    try:
        return shutil.disk_usage(pasta).free / GB
    except OSError:
        return 0.0


# ============================================================================
# Placas de vídeo
# ============================================================================
def _nvidia_smi():
    programa = shutil.which("nvidia-smi")
    if not programa and SO == "windows":
        candidato = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "nvidia-smi.exe")
        programa = candidato if os.path.exists(candidato) else None
    if not programa:
        return None
    placas = []
    saida = _rodar([programa, "--query-gpu=name,memory.total,compute_cap,driver_version",
                    "--format=csv,noheader,nounits"])
    if not saida:  # drivers antigos não têm compute_cap
        saida = _rodar([programa, "--query-gpu=name,memory.total,driver_version",
                        "--format=csv,noheader,nounits"])
        linhas = [l.split(",") for l in saida.strip().splitlines() if l.strip()]
        linhas = [[p[0], p[1], "", p[2]] for p in linhas if len(p) >= 3]
    else:
        linhas = [l.split(",") for l in saida.strip().splitlines() if l.strip()]
    for partes in linhas:
        if len(partes) < 4:
            continue
        nome, memoria, cc, driver = (p.strip() for p in partes[:4])
        try:
            vram = float(memoria) / 1024
        except ValueError:
            vram = 0.0
        try:
            capacidade = float(cc) if cc and cc != "[N/A]" else None
        except ValueError:
            capacidade = None
        placas.append({"fabricante": "nvidia", "nome": nome, "vram_gb": vram, "dedicada": True,
                       "driver": driver, "capacidade": capacidade})
    return placas


def _placas_linux():
    import glob
    placas = []
    for dispositivo in sorted(glob.glob("/sys/class/drm/card[0-9]*/device")):
        if os.path.basename(os.path.dirname(dispositivo)).count("-"):
            continue  # card0-HDMI-A-1 etc. são saídas de vídeo, não placas
        try:
            with open(os.path.join(dispositivo, "vendor")) as f:
                fabricante = {"0x10de": "nvidia", "0x1002": "amd", "0x8086": "intel"}.get(f.read().strip())
        except OSError:
            continue
        if not fabricante:
            continue
        nome = ""
        slot = os.path.basename(os.path.realpath(dispositivo))
        if shutil.which("lspci"):
            linha = _rodar(["lspci", "-s", slot]).strip()
            nome = linha.split(": ", 1)[1] if ": " in linha else linha
            nome = re.sub(r"\s*\(rev [0-9a-f]+\)", "", nome)
            nome = re.sub(r"^.*?Corporation\s+|^Advanced Micro Devices, Inc\.\s*", "", nome)
        vram = 0.0
        try:
            with open(os.path.join(dispositivo, "mem_info_vram_total")) as f:
                vram = int(f.read()) / GB
        except (OSError, ValueError):
            pass
        dedicada = (fabricante == "nvidia" or (fabricante == "amd" and vram >= 2)
                    or (fabricante == "intel" and "arc" in nome.lower() and vram >= 2))
        placas.append({"fabricante": fabricante, "nome": nome or fabricante.upper(), "vram_gb": vram,
                       "dedicada": dedicada, "driver": None, "capacidade": None})
    return placas


def _placas_windows():
    placas = []
    try:
        import winreg
        classe = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, classe) as raiz:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(raiz, i)
                except OSError:
                    break
                i += 1
                if not sub.isdigit():
                    continue
                try:
                    with winreg.OpenKey(raiz, sub) as k:
                        nome = winreg.QueryValueEx(k, "DriverDesc")[0]
                        vram = 0
                        for valor in ("HardwareInformation.qwMemorySize", "HardwareInformation.MemorySize"):
                            try:
                                dado = winreg.QueryValueEx(k, valor)[0]
                                vram = int.from_bytes(dado, "little") if isinstance(dado, bytes) else int(dado)
                                break
                            except OSError:
                                continue
                except OSError:
                    continue
                n = nome.lower()
                if "basic" in n or "remote" in n or "virtual" in n:
                    continue
                fabricante = ("nvidia" if "nvidia" in n else "amd" if ("amd" in n or "radeon" in n)
                              else "intel" if "intel" in n else "outra")
                vram_gb = vram / GB
                dedicada = (fabricante == "nvidia" or (fabricante == "amd" and vram_gb >= 2)
                            or (fabricante == "intel" and "arc" in n and vram_gb >= 2))
                placas.append({"fabricante": fabricante, "nome": nome, "vram_gb": vram_gb,
                               "dedicada": dedicada, "driver": None, "capacidade": None})
    except Exception:
        pass
    return placas


def _placas_mac():
    if platform.machine() == "arm64":
        chip = _rodar(["sysctl", "-n", "machdep.cpu.brand_string"]).strip() or "Apple Silicon"
        return [{"fabricante": "apple", "nome": f"GPU integrada do {chip}", "vram_gb": 0.0,
                 "dedicada": True, "driver": None, "capacidade": None, "unificada": True}]
    placas = []
    try:
        dados = json.loads(_rodar(["system_profiler", "SPDisplaysDataType", "-json"], timeout=30) or "{}")
        for p in dados.get("SPDisplaysDataType", []):
            nome = p.get("sppci_model", "Placa de vídeo")
            vram_txt = p.get("spdisplays_vram") or p.get("spdisplays_vram_shared") or ""
            achado = re.search(r"(\d+)\s*(GB|MB)", vram_txt)
            vram = (int(achado.group(1)) / (1 if achado.group(2) == "GB" else 1024)) if achado else 0
            placas.append({"fabricante": "amd" if "AMD" in nome or "Radeon" in nome else "intel",
                           "nome": nome, "vram_gb": vram, "dedicada": False,  # o Ollama não usa no Mac Intel
                           "driver": None, "capacidade": None})
    except ValueError:
        pass
    return placas


def placas_de_video():
    if SO == "mac":
        return _placas_mac()
    nvidia = _nvidia_smi() or []
    outras = _placas_linux() if SO == "linux" else _placas_windows()
    # junta: as NVIDIA do nvidia-smi valem mais (têm memória e driver certos)
    if nvidia:
        outras = [p for p in outras if p["fabricante"] != "nvidia"]
    else:
        for p in outras:
            if p["fabricante"] == "nvidia":
                p["sem_driver"] = True
    return nvidia + outras


# ============================================================================
# Análise: dá para usar a placa? quanto sobra de memória?
# ============================================================================
def _banda_gpu(nome, vram):
    """Velocidade de memória aproximada da placa, em GB/s (só para estimar)."""
    n = nome.lower()
    tabela = [("mx1", 48), ("mx2", 56), ("mx3", 56), ("mx4", 64), ("mx5", 64), ("gt 1030", 48),
              ("1050", 112), ("1060", 192), ("1070", 256), ("1080", 320), ("1650", 128), ("1660", 192),
              ("2060", 336), ("2070", 448), ("2080", 448), ("3050", 224), ("3060", 360), ("3070", 448),
              ("3080", 760), ("3090", 936), ("4060", 272), ("4070", 504), ("4080", 717), ("4090", 1008),
              ("5060", 448), ("5070", 672), ("5080", 960), ("5090", 1792)]
    for chave, banda in tabela:
        if chave in n:
            return banda
    return 300 if vram >= 8 else 150


def _banda_apple(nome):
    n = nome.lower()
    if "ultra" in n:
        return 800
    if "max" in n:
        return 400
    if "pro" in n:
        return 200
    if "m4" in n or "m5" in n:
        return 120
    return 100


def analisar(forcar_cpu=False):
    cpu = processador()
    ram = memoria_gb()
    placas = placas_de_video()
    resultado = {"so": SO, "sistema": nome_do_sistema(), "processador": cpu,
                 "ram_gb": round(ram, 1), "disco_livre_gb": round(disco_livre_gb(), 1),
                 "bateria": tem_bateria(), "placas": placas}

    # memória que sobra para o modelo (o sistema e os programas abertos ficam com o resto)
    ram_livre = max(0.5, ram * 0.8 - 1.5)
    banda_cpu = 20.0 if cpu["avx2"] is not False else 12.0
    if cpu["arm"] and SO == "linux":
        banda_cpu = 15.0

    usar = None  # a placa que o Ollama vai usar
    aviso, modo = "", "cpu"
    for p in placas:
        if p["fabricante"] == "apple":
            usar = dict(p)
            fracao = 0.75 if ram >= 36 else 0.66
            usar["vram_gb"] = ram * fracao
            usar["banda"] = _banda_apple(p["nome"])
            modo = "gpu"
            aviso = (f"O Mac usa a GPU integrada com a memória unificada: até ~{ram * fracao:.0f} GB "
                     "para a IA, bem mais rápido que o processador sozinho.")
            break
    if not usar:
        for p in sorted(placas, key=lambda x: x["vram_gb"], reverse=True):
            if not p["dedicada"]:
                continue
            if p.get("sem_driver"):
                aviso = (f"A placa {p['nome']} está aqui, mas o driver da NVIDIA não está instalado. "
                         "Instale o driver para a IA poder usar a placa. Por enquanto, ela roda no processador.")
                continue
            if p["capacidade"] and p["capacidade"] < 5.0:
                aviso = f"A placa {p['nome']} é antiga demais para o Ollama (precisa de CUDA 5.0 ou mais nova)."
                continue
            if p["vram_gb"] < 3.5:
                aviso = (f"A placa {p['nome']} tem só {p['vram_gb']:.0f} GB de memória: os modelos não "
                         "cabem nela e a ajuda é pequena. Recomendado: usar só o processador "
                         "(esquenta menos e gasta menos energia).")
                resultado["placa_pequena"] = p["nome"]
                continue
            usar = dict(p)
            usar["vram_gb"] = max(0.0, p["vram_gb"] - 0.6)  # a tela também usa um pouco
            usar["banda"] = _banda_gpu(p["nome"], p["vram_gb"])
            modo = "gpu"
            via = {"nvidia": "CUDA", "amd": "ROCm/Vulkan", "intel": "Vulkan"}.get(p["fabricante"], "")
            aviso = (f"A placa {p['nome']} ({p['vram_gb']:.0f} GB) pode rodar a IA ({via}). Modelos que "
                     "cabem nela ficam rápidos; os maiores se dividem entre a placa e o processador.")
            break
        if not usar and not aviso:
            integradas = [p["nome"] for p in placas if not p["dedicada"]]
            aviso = ("Não há placa de vídeo dedicada compatível"
                     + (f" ({', '.join(integradas)} é integrada)" if integradas else "")
                     + ": a IA roda no processador.")
    if forcar_cpu and usar and usar["fabricante"] != "apple":
        usar, modo = None, "cpu"

    resultado["placa_usada"] = usar["nome"] if usar else None
    resultado["modo"] = modo  # gpu (com ajuda da CPU quando não cabe) ou cpu
    resultado["aviso"] = aviso
    resultado["pode_forcar_cpu"] = bool(usar and usar["fabricante"] != "apple") or bool(resultado.get("placa_pequena"))
    resultado["recomenda_so_cpu"] = bool(resultado.get("placa_pequena")) and not usar

    modelos = []
    for m in MODELOS:
        precisa = m["tamanho_gb"] * 1.15 + 0.4  # pesos + contexto de 8 mil tokens
        item = dict(m, precisa_gb=round(precisa, 1))
        if usar and usar["fabricante"] == "apple":
            if precisa <= usar["vram_gb"]:
                onde, vel = "gpu", usar["banda"] * 0.7 / m["ativo_gb"]
            else:
                onde, vel = "nao_cabe", 0
        elif usar and precisa <= usar["vram_gb"]:
            onde, vel = "gpu", usar["banda"] * 0.6 / m["ativo_gb"]
        elif usar and precisa <= usar["vram_gb"] + ram_livre:
            fracao = usar["vram_gb"] / precisa
            tempo = (m["ativo_gb"] * fracao) / (usar["banda"] * 0.6) + \
                    (m["ativo_gb"] * (1 - fracao)) / banda_cpu
            onde, vel = "gpu_cpu", 1 / tempo
            item["fracao_gpu"] = round(fracao * 100)
        elif precisa <= ram_livre:
            onde, vel = "cpu", banda_cpu / m["ativo_gb"]
        else:
            onde, vel = "nao_cabe", 0
        item["onde"] = onde
        item["tokens_s"] = round(vel, 1)
        for limite, chave, texto in VELOCIDADES:
            if vel >= limite:
                item["velocidade"], item["velocidade_texto"] = chave, texto
                break
        if onde == "nao_cabe":
            item["velocidade"], item["velocidade_texto"] = "nao_cabe", "não cabe na memória"
        modelos.append(item)

    # recomendado: o melhor modelo que ainda responde numa velocidade boa
    bons = [m for m in modelos if m["onde"] != "nao_cabe" and m["tokens_s"] >= 6]
    if bons:
        # dividir pouco do modelo com a placa costuma travar mais do que as contas indicam
        def nota(m):
            penalidade = 1 if m["onde"] == "gpu_cpu" and m.get("fracao_gpu", 100) < 60 else 0
            return (m["qualidade"] - penalidade, m["tokens_s"])
        recomendado = max(bons, key=nota)
    else:
        possiveis = [m for m in modelos if m["onde"] != "nao_cabe"]
        recomendado = max(possiveis, key=lambda m: m["tokens_s"]) if possiveis else modelos[0]
    for m in modelos:
        m["recomendado"] = m["nome"] == recomendado["nome"]
    resultado["modelos"] = modelos
    resultado["recomendado"] = recomendado["nome"]
    return resultado


def nome_do_sistema():
    if SO == "windows":
        versao = platform.version()
        build = int(versao.split(".")[-1]) if versao.split(".")[-1].isdigit() else 0
        return "Windows 11" if build >= 22000 else f"Windows {platform.release()}"
    if SO == "mac":
        return f"macOS {platform.mac_ver()[0]}"
    try:
        with open("/etc/os-release") as f:
            dados = dict(l.rstrip().split("=", 1) for l in f if "=" in l)
        return dados.get("PRETTY_NAME", "Linux").strip('"')
    except OSError:
        return "Linux"


ONDE_TEXTO = {"gpu": "placa de vídeo", "gpu_cpu": "placa + processador", "cpu": "processador",
              "nao_cabe": "não cabe"}


def resumo_texto(analise):
    """A análise em texto, para o instalador de terminal."""
    cpu = analise["processador"]
    linhas = [f"    Sistema:        {analise['sistema']}",
              f"    Processador:    {cpu['nome']} ({cpu['nucleos']} núcleos"
              + ("" if cpu["avx2"] is None else (", com AVX2" if cpu["avx2"] else ", sem AVX2: mais lento"))
              + ")",
              f"    Memória RAM:    {analise['ram_gb']:.0f} GB",
              f"    Espaço livre:   {analise['disco_livre_gb']:.0f} GB"]
    for p in analise["placas"]:
        memoria = f" ({p['vram_gb']:.0f} GB)" if p["vram_gb"] and p["fabricante"] != "apple" else ""
        linhas.append(f"    Placa de vídeo: {p['nome']}{memoria}" + ("" if p["dedicada"] else " · integrada"))
    if not analise["placas"]:
        linhas.append("    Placa de vídeo: nenhuma encontrada")
    linhas.append("")
    linhas.append("    " + analise["aviso"])
    return "\n".join(linhas)


if __name__ == "__main__":
    forcar = "--so-cpu" in sys.argv
    analise = analisar(forcar_cpu=forcar)
    if "--json" in sys.argv:
        print(json.dumps(analise, ensure_ascii=False))
        sys.exit(0)
    print(resumo_texto(analise))
    print()
    for i, m in enumerate(analise["modelos"], 1):
        marca = "  ← recomendado" if m["recomendado"] else ""
        if m["onde"] == "nao_cabe":
            print(f"    [{i}] {m['nome']:<14} {m['tamanho_gb']:>5.1f} GB  não cabe na memória deste computador")
        else:
            print(f"    [{i}] {m['nome']:<14} {m['tamanho_gb']:>5.1f} GB  {ONDE_TEXTO[m['onde']]}, "
                  f"{m['velocidade_texto']}{marca}")
