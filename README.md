# Lumero

Assistente de IA local que roda no terminal. O modelo de IA fica no seu computador
(Ollama em 127.0.0.1); só a pesquisa na internet sai dele, e dá para desligar.

Funciona no **Linux** (Fedora, Ubuntu/Debian/Mint, Arch/Manjaro, openSUSE), no
**Windows 10/11** e no **macOS 12 ou mais novo** (Apple Silicon e Intel).

## Instalar pelo script (recomendado)

Extraia o zip, abra a pasta `lumero` e:

| Sistema | Como instalar |
|---|---|
| Linux | `bash linux/instalar.sh` |
| macOS | `bash mac/instalar.sh` (no Terminal) |
| Windows | dois cliques em `windows\instalar.cmd` |

O instalador:

- instala o que falta: Python, Ollama, ffmpeg, 7-Zip, git. No Mac usa o Homebrew, no
  Windows usa o winget e no Linux usa o gerenciador da sua distribuição;
- cria o atalho no menu (Ctrl+Alt+A no GNOME e no Windows), o comando `lumero` e o ícone;
- pergunta quais modelos baixar e recomenda um conforme a RAM e a placa de vídeo;
- oferece bloquear a internet do Ollama. No Linux isso é feito pelo systemd e no
  Windows pelo Firewall. A pesquisa do Lumero continua funcionando com o bloqueio;
- no Linux, oferece o modo econômico para notebooks: limita a CPU e desliga o turbo.

Para desinstalar, rode `linux/desinstalar.sh` ou `mac/desinstalar.sh`. No Windows, vá em
Configurações → Aplicativos → Lumero.

## Onde ficam as coisas

| | Linux | macOS | Windows |
|---|---|---|---|
| Lumero e dados | `~/.local/share/lumero` | `~/Library/Application Support/Lumero` | `%LOCALAPPDATA%\Lumero` |
| Configurações | `config.json` nessa pasta | igual | igual |

No `config.json` você muda o modelo, o buscador, o tamanho do contexto e outras opções sem
mexer no script. Exemplo: `{"MODELO": "qwen3.5:2b", "BUSCADOR": "duckduckgo"}`.
As opções de segurança (lixeira, rede nos comandos, autoedição) só mudam no próprio
`lumero.py`, de propósito.

## Segurança em cada sistema

| | Linux | macOS | Windows |
|---|---|---|---|
| Comandos da IA | bash numa sandbox (bubblewrap): só altera a pasta pessoal, sem internet | bash no `sandbox-exec`: só altera a pasta pessoal, sem internet | PowerShell, sempre com a sua confirmação (o Windows não tem sandbox simples) |
| Administrador | janela de senha do sistema (pkexec) | janela de senha do macOS | janela do UAC |
| Apagar | Lixeira | Lixo | Lixeira |

## Instaladores nativos (.deb, .rpm, Arch, .exe, .dmg)

Os pacotes do Linux instalam o Lumero. Na primeira vez que ele abre, oferece instalar e
configurar o Ollama.

O `.exe` e o `.dmg` não têm assinatura digital, que é paga. Por isso:

- **Windows:** o SmartScreen avisa "O Windows protegeu o computador". Clique em
  **Mais informações** → **Executar assim mesmo**.
- **macOS:** arraste o Lumero para Aplicativos e tente abrir. Depois vá em **Ajustes do
  Sistema → Privacidade e Segurança** e clique em **Abrir Mesmo Assim**. Na primeira vez o
  app abre o Terminal e se instala.
