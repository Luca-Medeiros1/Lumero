# Lumero

Assistente de IA que roda **no seu computador**. Ele conversa, pesquisa na internet, acha e
organiza arquivos, roda comandos, cria lembretes e até escreve ferramentas novas para si
mesmo, sempre pedindo a sua permissão antes do que é arriscado.

O modelo de IA roda localmente pelo [Ollama](https://ollama.com), que só escuta o próprio
computador (`127.0.0.1`). As suas conversas não vão para a internet. Só a pesquisa na internet
sai do computador, e dá para desligar.

Funciona no **Linux** (Fedora, Ubuntu/Debian/Mint, Arch/Manjaro, openSUSE), no
**Windows 10/11** e no **macOS 14 ou mais novo** (Apple Silicon e Intel).

## Instalar

Baixe o instalador do seu sistema na página
[**Releases**](../../releases/latest):

| Sistema | Arquivo | Como instalar |
|---|---|---|
| Ubuntu, Debian, Mint | `lumero_X.Y.Z_all.deb` | `sudo apt install ./lumero_*.deb` |
| Fedora, openSUSE | `lumero-X.Y.Z-1.noarch.rpm` | `sudo dnf install ./lumero-*.rpm` |
| Arch, Manjaro | `lumero-X.Y.Z-1-any.pkg.tar.zst` | `sudo pacman -U lumero-*.pkg.tar.zst` |
| Windows | `Lumero-X.Y.Z-Windows-Setup.exe` | dois cliques |
| macOS | `Lumero-X.Y.Z-macOS.dmg` | arraste para Aplicativos e abra |

Ou baixe o código (botão **Code → Download ZIP**), extraia e rode o instalador:

| Sistema | Comando |
|---|---|
| Linux | `bash linux/instalar.sh` |
| macOS | `bash mac/instalar.sh` |
| Windows | dois cliques em `windows\instalar.cmd` |

O `.exe` e o `.dmg` não têm assinatura digital, que é paga. Por isso:

- **Windows:** o SmartScreen avisa "O Windows protegeu o computador". Clique em
  **Mais informações** → **Executar assim mesmo**.
- **macOS:** depois de tentar abrir, vá em **Ajustes do Sistema → Privacidade e Segurança**
  e clique em **Abrir Mesmo Assim**.

### O instalador

O instalador abre uma **janela** com cinco passos:

1. **Boas-vindas:** pergunta como você quer ser chamado. O Lumero usa o seu nome nas conversas.
2. **Computador:** analisa o processador, a RAM, a placa de vídeo e o espaço livre, e diz se a
   IA vai rodar na **placa de vídeo**, no **processador** ou **nos dois**. Você escolhe entre
   automático (placa + processador), só a placa de vídeo ou só o processador.
3. **Modelos:** mostra todos os modelos, com onde cada um roda, a velocidade estimada, o
   tamanho do download e o contexto. O melhor para o seu computador já vem marcado.
4. **Opções:** bloquear a internet do Ollama, voz, ferramentas extras e atalhos.
5. **Instalação:** instala o que falta (Python, Ollama e outros programas) e baixa os modelos,
   mostrando o progresso. A senha é pedida uma vez, pela janela do sistema.

No Mac, o instalador usa o Homebrew. No Windows, usa o winget. No Linux, usa o gerenciador de
pacotes da sua distribuição.

Prefere o terminal? Use `bash linux/instalar.sh --terminal`, `bash mac/instalar.sh --terminal`
ou `windows\instalar.ps1 -Terminal`. As perguntas são as mesmas.

Para desinstalar, use `/desinstalar` no próprio Lumero (ou o item **Desinstalar o Lumero…** no
botão ◐ da janela). Também dá para rodar `linux/desinstalar.sh` ou `mac/desinstalar.sh`, ou, no
Windows, ir em **Configurações → Aplicativos → Lumero**.

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
O instalador do Windows também precisa do **winget**, que já vem no Windows 11 e nas versões
atualizadas do Windows 10. Se não tiver, instale o "Instalador de Aplicativo" pela Microsoft
Store.

### Modelos e onde eles rodam

O Lumero usa a família **Qwen 3.5**. Todos os modelos entendem texto e imagens, usam
ferramentas e conseguem raciocinar antes de responder.

| Modelo | Download | Memória que precisa | Para quem |
|---|---|---|---|
| `qwen3.5:0.8b` | 1,0 GB | ~1,5 GB | computadores bem fracos |
| `qwen3.5:2b` | 2,7 GB | ~3,5 GB | tarefas simples, 8 GB de RAM |
| `qwen3.5:4b` | 3,4 GB | ~4,3 GB | a maioria dos computadores |
| `qwen3.5:9b` | 6,6 GB | ~8 GB | placa com 8 GB+, Mac com 16 GB+ ou 16 GB de RAM |
| `qwen3.5:27b` | 17 GB | ~20 GB | placa com 24 GB ou Mac com 32 GB+ |
| `qwen3.5:35b` | 24 GB | ~28 GB | placa de 12 GB+ com 32 GB de RAM, ou Mac com 48 GB+ |
| `qwen3.5:122b` | 81 GB | ~94 GB | estações de trabalho e Macs com 128 GB |

Para cada modelo, o instalador diz onde ele roda:

- **Placa de vídeo:** o modelo cabe inteiro na memória da placa. É o mais rápido.
- **Placa + processador:** parte fica na placa e o resto na RAM. O Ollama faz essa divisão sozinho.
- **Processador:** sem placa compatível, ou com placa pequena demais (menos de ~4 GB).
- **Não cabe:** o modelo precisa de mais memória do que o computador tem.

O recomendado é o modelo mais esperto que ainda responde numa velocidade boa no seu computador.

Por padrão, o Ollama usa a placa de vídeo quando ela é compatível (NVIDIA, AMD ou Apple). Se a
placa tiver pouca memória (como uma MX150 de 2 GB), o instalador recomenda **só o
processador**: a diferença de velocidade é pequena e o notebook esquenta menos.

Dá para trocar depois, no seletor **IA:** no alto da janela ou com `/processamento`:

| Modo | Como funciona |
|---|---|
| Placa + processador (`auto`) | o Ollama põe na placa o que couber e o resto na RAM |
| Só placa de vídeo (`gpu`) | o modelo inteiro na placa: o mais rápido, mas ele precisa caber nela |
| Só processador (`cpu`) | a placa fica de fora: esquenta menos e gasta menos energia |

No Linux, mudar de "só processador" para um modo com a placa (ou o contrário) altera a
configuração do Ollama, então o sistema pede a sua senha.

**Contexto** é quanto da conversa o modelo lembra de uma vez. O instalador escolhe o contexto
pela memória que sobra depois do modelo:

- de 8K a 32K no processador;
- até 64K numa placa de vídeo;
- até 128K num Mac com memória de sobra.

Contexto maior usa mais memória. No processador, ele também faz a resposta demorar mais para
começar em conversas longas. Quando a conversa passa de 70% do contexto, o Lumero resume as
partes antigas sozinho.

## Usando o Lumero

O Lumero abre numa **janela de chat**, parecida com a do Claude e a do ChatGPT:

- a lista de conversas fica do lado, e elas são salvas sozinhas;
- as respostas são formatadas, com tabelas e blocos de código com botão de copiar;
- dá para anexar imagens e arquivos, arrastando ou colando;
- aparecem os botões **Permitir** e **Negar** antes de qualquer ação arriscada;
- no alto, dá para escolher o modelo, o raciocínio (automático, sempre ou nunca), onde a IA
  roda (placa + processador, só placa ou só processador) e a leitura das respostas em voz alta;
- digitando `/`, aparece o menu de comandos;
- enquanto você digita, aparecem sugestões em cinza tiradas das suas mensagens anteriores.
  Aceite com **Tab** ou **→**;
- embaixo da caixa de texto fica o seletor de **contexto**;
- o botão ◐ troca entre tema claro, escuro ou automático (igual ao sistema).

Quem prefere o terminal tem as mesmas ferramentas, com o comando `lumero`:

| Sistema | Janela de chat | Terminal |
|---|---|---|
| Linux | ícone "Lumero" no menu, `lumero-gui` ou Ctrl+Alt+A (GNOME) | `lumero`, ou botão direito no ícone → Abrir no terminal |
| macOS | Lumero.app (Spotlight ou Launchpad) | `lumero` no Terminal |
| Windows | atalho "Lumero" ou Ctrl+Alt+A | atalho "Lumero (terminal)" |

A janela usa o motor de páginas do próprio sistema: WebKitGTK no Linux, WebKit no macOS e
WebView2 no Windows. Se ele faltar, o chat abre no navegador, no modo aplicativo. Em todos os
casos, a página conversa com o Lumero só dentro do computador (`127.0.0.1`), com uma senha de
sessão.

### O que ele sabe fazer

| Área | Exemplos |
|---|---|
| Internet | pesquisar, ler páginas, abrir sites, previsão do tempo |
| Arquivos | achar arquivos por descrição ou pelo conteúdo, ler PDFs, criar scripts, salvar notas, mandar para a lixeira |
| Computador | abrir programas, estado do PC (temperatura, bateria, RAM), volume, brilho, modo de energia, suspender |
| Imagens | descrever fotos, ler textos em imagens, ler a tela |
| Dia a dia | lembretes com notificação (mesmo com o Lumero fechado), tarefas, pomodoro, contas, área de transferência |
| Memória | lembra fatos sobre você em todas as conversas ("lembra que eu...") |
| Comandos | roda comandos de terminal isolados e, com a senha, comandos de administrador |
| Extras | ligam sozinhos pelo assunto: vídeo e áudio (ffmpeg), fotos em lote, espaço em disco, organizar e compactar pastas, atualizações e processos, cotações e CEP, git e servidor de desenvolvimento |
| Voz | falar pelo microfone e ouvir as respostas, offline (opcional) |

### Comandos

| Comando | O que faz |
|---|---|
| `/ajuda` | mostra os comandos e atalhos |
| `/nova` | começa uma conversa nova |
| `/ferramentas` | lista o que a IA consegue fazer |
| `/modelo [nome]` | mostra ou troca o modelo |
| `/pensar [auto, sempre ou nunca]` | raciocínio antes de responder |
| `/pensamento` | mostra o raciocínio da última resposta |
| `/contexto [16k, 32k ou recomendado]` | mostra o uso ou troca o tamanho do contexto |
| `/compactar` | resume a conversa para liberar contexto |
| `/nome [nome]` | mostra ou troca o nome pelo qual o Lumero te chama |
| `/memoria` | o que a IA lembra sobre você |
| `/estado` | temperatura, bateria, CPU e RAM e uso da IA |
| `/extras [nome ou todos]` | liga grupos de ferramentas extras |
| `/extensoes` | ferramentas que o Lumero criou (veja abaixo) |
| `/conversas` e `/retomar` | lista e reabre conversas salvas |
| `/ouvir` | liga ou desliga a leitura das respostas em voz alta |
| `/tema [auto, claro ou escuro]` | aparência da janela |
| `/processamento [auto, gpu ou cpu]` | onde a IA roda: placa + processador, só placa ou só processador |
| `/desinstalar [lumero, ollama ou tudo]` | remove o Lumero; `ollama` remove também o Ollama e os modelos; `tudo` apaga ainda as conversas e a memória |

Algumas dicas:

- comece a mensagem com `!` para forçar a IA a pensar;
- digite `~/` para completar caminhos de pastas;
- **Shift+Enter** pula linha, **Esc** para a resposta e **Ctrl+Shift+O** abre uma conversa nova.

### Funções novas (extensões)

Peça algo que o Lumero ainda não faz, por exemplo "cria uma ferramenta que converte
temperaturas". Ele escreve uma **extensão**: um arquivo Python pequeno que vira uma ferramenta
nova. Antes de salvar:

1. o código é conferido e testado **sem internet e sem poder gravar nada**. Se der erro, o
   Lumero corrige sozinho;
2. aparece o cartão **Permitir/Negar**, com o código inteiro e o resultado do teste.

Depois de aprovada, a extensão roda sempre isolada (bubblewrap no Linux, sandbox-exec no Mac).
Ela fica sem internet, a não ser que precise e você tenha aprovado, e só pode mexer na sua pasta
pessoal. No Windows não há essa proteção, então cada uso pede permissão antes. O `lumero.py`
nunca é alterado: as extensões ficam na pasta `extensoes/` dos dados do Lumero.

Para gerenciar, use `/extensoes`:

- `/extensoes ver NOME` mostra o código;
- `/extensoes desligar NOME` e `/extensoes ligar NOME`;
- `/extensoes remover NOME` apaga e guarda uma cópia em `extensoes/antigas`.

## Configurações

| | Linux | macOS | Windows |
|---|---|---|---|
| Lumero e dados | `~/.local/share/lumero` | `~/Library/Application Support/Lumero` | `%LOCALAPPDATA%\Lumero` |
| Configurações | `config.json` nessa pasta | igual | igual |

Quase tudo muda pela janela ou pelos comandos, e fica salvo no `config.json`. Dá para editar o
arquivo à mão também. Por exemplo:

```json
{
  "NOME_USUARIO": "Luca",
  "MODELO": "qwen3.5:4b",
  "CONTEXTO": 16384,
  "PENSAR": "auto",
  "TEMA": "auto",
  "PROCESSAMENTO": "auto",
  "BUSCADOR": "duckduckgo",
  "PESQUISA_INTERNET": true,
  "EXTENSOES": true
}
```

Para desligar a pesquisa na internet, use `"PESQUISA_INTERNET": false`. Para impedir a criação
de extensões, use `"EXTENSOES": false`.

As opções de segurança (lixeira, rede nos comandos, autoedição do `lumero.py`) só mudam no
próprio `lumero.py`, de propósito.

## Privacidade e segurança

- **A IA é local.** O Ollama roda no seu computador e só aceita conexões dele mesmo
  (`127.0.0.1`). Ninguém na sua rede consegue usar a sua IA.
- **Ollama sem internet (opcional).** O instalador oferece bloquear a internet do Ollama: no
  Linux pelo systemd e no Windows pelo Firewall. Para baixar outro modelo depois, use
  `lumero-baixar-modelo NOME` (ex.: `lumero-baixar-modelo qwen3.5:9b`), que libera a internet
  só durante o download.
- **A pesquisa é do Lumero.** Quando você pede uma pesquisa, só o termo pesquisado vai para o
  buscador. O bloqueio do Ollama não atrapalha a pesquisa.
- **Comandos isolados.** Os comandos que a IA roda não alteram nada fora da sua pasta pessoal.
- **Nada apaga de vez.** Apagar sempre manda para a lixeira.

| | Linux | macOS | Windows |
|---|---|---|---|
| Comandos da IA | bash numa sandbox (bubblewrap): só altera a pasta pessoal, sem internet | bash no `sandbox-exec`: só altera a pasta pessoal, sem internet | PowerShell, sempre com a sua confirmação (o Windows não tem sandbox simples) |
| Extensões | isoladas (bubblewrap) | isoladas (`sandbox-exec`) | pergunta a cada uso |
| Administrador | janela de senha do sistema (pkexec) | janela de senha do macOS | janela do UAC |
| Apagar | Lixeira | Lixo | Lixeira |

## Para desenvolvedores: gerar os instaladores

A pasta `.github/workflows` gera os instaladores nativos no GitHub Actions. Cada tag `v*`
gera uma release com o `.deb`, o `.rpm`, o pacote do Arch, o `Setup.exe` do Windows e o `.dmg`
do Mac:

```bash
git tag v1.4.0 && git push origin v1.4.0
```

Os pacotes do Linux instalam o Lumero. Na primeira vez que ele abre, aparece o instalador com
janela, que configura o Ollama e baixa os modelos.
