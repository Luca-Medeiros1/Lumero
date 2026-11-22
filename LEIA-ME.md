# Lumero

Assistente de IA local que roda no terminal. O modelo de IA fica no seu computador
(Ollama em 127.0.0.1); só a pesquisa na internet sai dele, e dá para desligar.

Funciona no **Linux** (Fedora, Ubuntu/Debian/Mint, Arch/Manjaro, openSUSE), no
**Windows 10/11** e no **macOS 14 ou mais novo** (Apple Silicon e Intel).

## Janela de chat ou terminal

O Lumero abre numa **janela de chat**, parecida com a do Claude e a do ChatGPT. Ela tem:

- a lista de conversas do lado;
- respostas formatadas, com tabelas e blocos de código com botão de copiar;
- anexos de imagens e arquivos (é só arrastar ou colar);
- os botões **Permitir** e **Negar** antes de qualquer ação arriscada;
- a escolha do modelo e do raciocínio.

Quem prefere o terminal tem as mesmas ferramentas, com o comando `lumero`:

| Sistema | Janela de chat | Terminal |
|---|---|---|
| Linux | ícone "Lumero" no menu ou `lumero-gui` | `lumero`, ou botão direito no ícone → Abrir no terminal |
| macOS | Lumero.app (Spotlight ou Launchpad) | `lumero` no Terminal |
| Windows | atalho "Lumero" (Ctrl+Alt+A) | atalho "Lumero (terminal)" |

A janela usa o motor de páginas do próprio sistema: WebKitGTK no Linux, WebKit no macOS e
WebView2 no Windows. Se ele faltar, o chat abre no navegador no modo aplicativo. Em todos
os casos, nada sai do computador: a página conversa com o Lumero em `127.0.0.1`, com uma
senha de sessão.

## Requisitos mínimos

| | Mínimo | Recomendado |
|---|---|---|
| Sistema | Windows 10 22H2 ou 11 (64 bits) · macOS 14 Sonoma · Linux 64 bits com systemd | o mais atualizado |
| Processador | 64 bits (x86-64 ou ARM64), de 4 núcleos | 6 núcleos ou mais, ou Apple M1 ou mais novo |
| Memória RAM | 8 GB | 16 GB |
| Placa de vídeo | não precisa: roda só no processador, mais devagar | NVIDIA com 6 GB ou mais, ou a GPU integrada do Apple M1/M2/M3/M4 |
| Espaço livre | 10 GB | 20 GB, para ter mais de um modelo |
| Internet | só para instalar e baixar os modelos | |

No Windows, uma placa NVIDIA precisa do driver 452.39 ou mais novo para o Ollama usar ela.
No Windows, o instalador também precisa do **winget**, que já vem no Windows 11 e nas
versões atualizadas do Windows 10. Se não tiver, instale o "Instalador de Aplicativo" pela
Microsoft Store.

### Qual modelo usar

| Modelo | Memória RAM | Para quem |
|---|---|---|
| `qwen3.5:2b` | 8 GB | computadores mais fracos: responde mais rápido, mas erra mais |
| `qwen3.5:4b` | 8 GB (melhor com 12 GB) | a maioria dos computadores: o equilíbrio entre velocidade e acerto |
| `qwen3.5:9b` | 16 GB | placa NVIDIA com 8 GB ou mais, ou Mac Apple Silicon com 16 GB ou mais |

O instalador olha a RAM e a placa de vídeo e já recomenda um modelo. Sem placa de vídeo,
cada resposta pode levar de alguns segundos a mais de um minuto, conforme o processador.

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
- no Linux, oferece o modo econômico para notebooks: limita a CPU e desliga o turbo;
- traz junto a memória e as conversas da versão antiga, a "assistente-ia".

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

A pasta `.github/workflows` gera os instaladores nativos no GitHub Actions:

1. Crie um repositório no GitHub e envie esta pasta.
2. Crie uma tag: `git tag v1.0.0 && git push --tags`.
3. Em alguns minutos, a aba **Releases** terá:
   - `lumero_1.0.0_all.deb`: Ubuntu, Debian, Mint (`sudo apt install ./lumero_*.deb`)
   - `lumero-1.0.0-1.noarch.rpm`: Fedora, openSUSE (`sudo dnf install ./lumero-*.rpm`)
   - `lumero-1.0.0-1-any.pkg.tar.zst`: Arch, Manjaro (`sudo pacman -U lumero-*.pkg.tar.zst`)
   - `Lumero-1.0.0-Windows-Setup.exe`
   - `Lumero-1.0.0-macOS.dmg`

Os pacotes do Linux instalam o Lumero. Na primeira vez que ele abre, oferece instalar e
configurar o Ollama.

O `.exe` e o `.dmg` não têm assinatura digital, que é paga. Por isso:

- **Windows:** o SmartScreen avisa "O Windows protegeu o computador". Clique em
  **Mais informações** → **Executar assim mesmo**.
- **macOS:** arraste o Lumero para Aplicativos e tente abrir. Depois vá em **Ajustes do
  Sistema → Privacidade e Segurança** e clique em **Abrir Mesmo Assim**. Na primeira vez o
  app abre o Terminal e se instala.
