# ArchClip

Histórico da área de transferência para Arch Linux, com a usabilidade do
`Win + V` do Windows: uma linha do tempo dos últimos itens copiados — textos e
imagens —, do mais recente ao mais antigo, com a possibilidade de fixar os que
você não quer perder.

Feito em Python 3 + GTK4/libadwaita, com foco em **GNOME sobre Wayland**.

---

## O que ele faz

- **Linha do tempo** dos itens copiados, do mais recente para o mais antigo.
- **Textos e imagens** (prints do `Print Screen`, imagens copiadas do
  navegador, etc.), com miniatura na lista.
- **Fixar itens** (alfinete): ficam no topo e nunca são descartados pelo
  limite do histórico.
- **Limite configurável** de itens não fixados (padrão: 25, como no Windows).
- **Busca** no histórico, ignorando maiúsculas e acentos — "acao", "AÇÃO" e
  "ação" acham a mesma coisa — e filtros por *Tudo / Fixados / Texto /
  Imagens*.
- **`Super + V` funcionando de verdade**: o ArchClip registra o atalho no
  GNOME e libera a combinação do atalho nativo (que abre a lista de
  notificações). O `Super + M` continua abrindo as notificações.
- **Atalho configurável** pela interface, capturando a combinação que você
  digitar.
- **Início automático** com o sistema.
- **Atualizações automáticas** a partir das releases do GitHub.
- **Pausar a captura** (`Ctrl + Espaço`) — para copiar algo sensível sem
  deixar rastro no histórico.
- **Ignora gerenciadores de senha** — seleções marcadas como secretas
  (KeePassXC, Bitwarden e afins) não entram no histórico.
- **Captura em segundo plano no GNOME**, por uma extensão do GNOME Shell — o
  Mutter não implementa data-control, e sem isso nenhum daemon enxerga a
  seleção. Veja *Como a captura funciona*.

---

## Instalação

### Dependências

```bash
sudo pacman -S --needed python python-gobject gtk4 libadwaita wl-clipboard
```

E o **GNOME 45 ou mais novo**, porque a captura depende de uma extensão do
GNOME Shell — veja *Como a captura funciona*.

Opcionais:

```bash
sudo pacman -S xclip      # sessões X11
sudo pacman -S ydotool    # colar automaticamente após escolher um item
```

### Instalar

```bash
git clone https://github.com/Theuszma/ArchLinux-Clipboard.git
cd ArchLinux-Clipboard
./install.sh
```

O script verifica as dependências, instala em
`~/.local/share/archclip/`, cria o launcher `~/.local/bin/archclip`, registra
o app no menu, instala a extensão do GNOME Shell e sobe o daemon já com o
`Super + V` configurado.

> **Faça logout/login depois de instalar.** O GNOME Shell varre o diretório de
> extensões uma vez, no começo da sessão, e no Wayland não pode se reiniciar —
> então uma extensão recém-instalada só passa a rodar no próximo login. O
> install.sh já deixa ela marcada como habilitada; enquanto isso não acontece,
> a janela abre e funciona, mas o histórico não enche.

> Se `~/.local/bin` não estiver no seu `PATH`, o script avisa. Adicione ao
> `~/.bashrc` ou `~/.zshrc`:
> `export PATH="$HOME/.local/bin:$PATH"`

Se o `Super + V` não responder logo de cara, faça logout/login — o
`gnome-settings-daemon` recarrega os atalhos no início da sessão.

### Desinstalar

```bash
./uninstall.sh              # remove tudo, inclusive o histórico
./uninstall.sh --keep-data  # preserva histórico e configuração
```

A desinstalação devolve ao GNOME os atalhos que o ArchClip tinha tomado e
remove a extensão do Shell.

---

## Uso

| Ação | Atalho |
|---|---|
| Abrir/fechar o histórico | `Super + V` (configurável) |
| Navegar pela lista | `↑` / `↓` |
| Copiar o item selecionado | `Enter` ou clique |
| Buscar | comece a digitar |
| Limpar a busca / fechar | `Esc` |
| Fixar/desafixar o selecionado | `Ctrl + P` |
| Remover o selecionado | `Delete` |
| Pausar/retomar a captura | `Ctrl + Espaço` |
| Configurações | `Ctrl + ,` |
| Encerrar o daemon | `Ctrl + Q` |

A pausa vale só para a sessão atual: reiniciar o ArchClip volta a capturar.
Um histórico que continuasse pausado depois do reboot, em silêncio, seria
pegadinha — você acharia que está gravando quando não está.

Escolher um item o coloca na área de transferência e fecha a janela — aí é só
dar `Ctrl + V` no aplicativo de destino. Com o `ydotool` instalado, a opção
*Colar automaticamente* dispensa esse último passo.

### Navegar na tela com o histórico aberto

Por padrão a janela some assim que você clica em outro lugar, como o Win+V.
Ligando *Manter sempre visível* (em *Configurações → Geral → Janela*), ela
fica por cima das outras: dá para trocar de aplicativo, rolar uma página e
voltar a escolher um item sem reabrir nada. Enquanto a opção está ligada,
*Fechar ao perder o foco* fica desativada — seria fechar justamente quando
você vai usar a tela.

Quem levanta a janela é a extensão do GNOME Shell (`SetWindowAbove`): no
Wayland um aplicativo comum não decide o próprio empilhamento. Sem a extensão
no ar, a opção aparece desabilitada explicando o porquê. Ela só sobe janelas
do próprio ArchClip — um serviço que levantasse qualquer janela seria
brinquedo para qualquer processo da sessão.

### Linha de comando

```bash
archclip              # abre a janela (subindo o daemon se preciso)
archclip --daemon     # só o daemon, sem janela
archclip --toggle     # abre/fecha (é o que o atalho global executa)
archclip --settings   # configurações
archclip --quit       # encerra o daemon
archclip --version
```

---

## Como o `Super + V` é sobrescrito

No Wayland, um aplicativo comum **não pode** capturar teclas globalmente —
quem decide isso é o compositor. Então o ArchClip não "rouba" a tecla; ele
reconfigura o GNOME:

1. Varre os schemas de atalho do GNOME (`org.gnome.shell.keybindings`,
   `org.gnome.desktop.wm.keybindings`, `org.gnome.mutter.*`, media-keys)
   procurando quem já usa a combinação escolhida.
2. Remove a combinação desses atalhos — no caso do `Super + V`, isso é o
   `toggle-message-tray`, que por padrão vale `['<Super>v', '<Super>m']` e
   passa a valer só `['<Super>m']`.
3. Grava um *custom keybinding* apontando para `archclip --toggle`.

Os valores originais ficam salvos em `overridden_bindings`, dentro do
`config.json`, e a interface tem um botão **Restaurar atalhos originais** que
os devolve — o `uninstall.sh` faz o mesmo.

Ao apertar o atalho, o `gnome-settings-daemon` executa `archclip --toggle`,
que fala com o daemon já rodando por D-Bus (sem carregar GTK) para abrir a
janela rapidamente.

---

## Como a captura funciona

No Wayland, um cliente comum só recebe eventos de seleção **enquanto tem foco
de teclado** — inútil para um daemon em segundo plano. Os compositores
resolvem isso com os protocolos `wlr-data-control-unstable-v1` /
`ext-data-control-v1`, que é o que o `wl-paste --watch` usa.

**O Mutter não implementa nenhum dos dois, e isso não é falta de versão.** É
decisão de projeto do GNOME: esses protocolos deixam qualquer cliente ler tudo
o que você copia, sem consentimento. Dá para conferir na sua máquina:

```bash
wl-paste --watch echo
# Watch mode requires a compositor that supports the data-control protocol

strings /usr/lib/libmutter-*.so.0.0.0 | grep -i data_control
# (nada)
```

Quem consegue vigiar a seleção no GNOME é código rodando **dentro do próprio
Shell**, onde o `MetaSelection` mora — é a mesma saída que o GPaste, o Pano e
o Clipboard Indicator usam. Daí a extensão em `extension/`, que publica na
sessão o serviço `io.github.theuszma.ArchClip.Shell`:

| Membro | Para quê |
|---|---|
| `SelectionChanged(as)` | sinal: a seleção mudou, e estes são os tipos MIME |
| `GetMimetypes() → as` | tipos MIME da seleção atual |
| `GetSelection(s) → ay` | conteúdo da seleção num tipo MIME |
| `SetSelection(s, ay)` | põe conteúdo na seleção (colar do histórico) |
| `SetWindowAbove(b)` | mantém a janela do ArchClip por cima das outras |

O sinal carrega só a lista de tipos, nunca o conteúdo: quem quiser o dado
precisa pedir. Toda decisão sobre o que guardar — texto ou imagem, tamanho
máximo, dica de gerenciador de senha — fica no daemon, que é quem tem a sua
configuração. A extensão não guarda nada.

Ao receber o sinal, o daemon acorda a thread do monitor, lê os tipos MIME,
escolhe o melhor (imagem > texto) e guarda. Copiar um item de volta usa o
`SetSelection`: quem passa a ser dono da seleção é o Shell, então o conteúdo
continua colável mesmo depois de encerrar o ArchClip.

Fora do GNOME o daemon cai no `wl-paste --watch` (funciona no Sway, no
Hyprland e em qualquer compositor com data-control) e, no X11, no `xclip`
consultado periodicamente. O modo em uso aparece em `Monitor.mode`:
`signal`, `watch` ou `poll`.

Conteúdos idênticos não duplicam: o item existente volta ao topo da lista.

### Se a extensão não estiver no ar

A janela mostra o que falta e o daemon fica esperando: ele observa o nome no
barramento e, assim que a extensão aparece — no próximo login, ou quando você
liga de novo em *Extensões* —, troca de backend sozinho, sem reiniciar. O
mesmo vale para o caminho inverso: se o GNOME Shell reiniciar ou a extensão
for desligada, ele volta para o `wl-paste` e avisa na janela.

```bash
gnome-extensions info archclip@theuszma.github.io   # deve dizer ACTIVE
```

---

## Configuração

Interface: `archclip --settings` (ou o menu ⋮ da janela).

Arquivo: `~/.config/archclip/config.json`

| Chave | Padrão | O que faz |
|---|---|---|
| `max_items` | `25` | Itens não fixados mantidos |
| `capture_text` / `capture_images` | `true` | O que capturar |
| `max_item_size_mb` | `16` | Ignora conteúdos maiores |
| `hotkey` | `<Super>v` | Atalho global |
| `hotkey_enabled` | `true` | Liga/desliga o registro do atalho |
| `close_on_copy` | `true` | Fecha ao escolher um item |
| `close_on_focus_loss` | `true` | Fecha ao perder o foco (como o Win+V) |
| `keep_on_top` | `false` | Mantém a janela por cima das outras |
| `auto_paste` | `false` | Envia `Ctrl+V` via ydotool/wtype |
| `autostart` | `true` | Inicia junto com a sessão |
| `update_check` | `true` | Consulta releases uma vez por dia |
| `update_auto_install` | `false` | Instala sozinho (veja *Segurança*) |
| `ignore_password_managers` | `true` | Pula seleções marcadas como secretas |
| `clear_on_exit` | `false` | Apaga não fixados ao encerrar |

---

## Onde ficam os dados

```
~/.config/archclip/config.json              configuração
~/.local/share/archclip/history.db          histórico (SQLite)
~/.local/share/archclip/blobs/              imagens copiadas
~/.local/share/archclip/versions/<versão>/  código instalado
~/.local/share/archclip/current             symlink para a versão ativa
~/.cache/archclip/thumbs/                   miniaturas
~/.config/autostart/…ArchClip-daemon.desktop
~/.local/share/gnome-shell/extensions/archclip@theuszma.github.io/
```

Os diretórios são criados com `0700` e os arquivos com `0600` — só o dono lê.

---

## Privacidade e segurança

Vale encarar o que um histórico de área de transferência é: **um arquivo em
texto puro com tudo o que você copiou**, senhas e tokens inclusive, que
sobrevive ao reboot. O Win+V tem exatamente a mesma propriedade. O que o
ArchClip faz a respeito:

- **Permissões restritas.** Banco, blobs, miniaturas e config ficam `0600`,
  em diretórios `0700`. Sem isso, o umask padrão (`644`) deixaria seu
  histórico legível por qualquer outro usuário da máquina.
- **Gerenciadores de senha são ignorados** quando marcam a seleção com
  `x-kde-passwordManagerHint` — KeePassXC e Bitwarden fazem isso. Nem todos
  fazem, então não é garantia.
- **Pausa rápida** (`Ctrl + Espaço`) para trechos sensíveis.
- **Limpar ao encerrar**, opcional, nas configurações.
- **A extensão não guarda nada.** Ela lê a seleção quando o daemon pede e
  entrega; o histórico em disco é só o do daemon, com as permissões acima.
- **Atualizações** só descem de hosts do GitHub, por HTTPS, e a checagem vale
  também para o destino do redirecionamento. A extração exige o
  `filter="data"` do `tarfile` (recusa `..`, caminhos absolutos e links para
  fora da árvore); se o Python for antigo demais para isso, o ArchClip
  desiste em vez de extrair sem proteção.

**O serviço da extensão fica visível na sua sessão D-Bus.** Qualquer processo
rodando como você pode chamar `GetSelection` e ler o que está na área de
transferência — é a mesma exposição que o GNOME evita ao não implementar
data-control, reintroduzida por quem instala a extensão. Vale medir contra o
que já é possível para um processo seu (ler o `history.db`, pedir o clipboard
com `wl-paste` quando tem foco): o ganho de um atacante é conveniência, não
acesso novo. Ainda assim, é uma superfície a mais, e ela existe só enquanto a
extensão está ligada.

**O que ele não faz:** as releases não são assinadas. Com
`update_auto_install` ligado, um comprometimento da conta do GitHub viraria
execução de código na máquina de quem tem o app instalado. Se isso te
incomodar, desligue *Instalar automaticamente* nas configurações — o ArchClip
passa a só avisar que há versão nova.

Nada é enviado para lugar nenhum: a única conexão de rede é a consulta à API
de releases do GitHub.

---

## Atualizações

O daemon consulta as releases do GitHub uma vez por dia e **avisa** quando há
versão nova. Instalar sozinho é opt-in — ligue *Instalar automaticamente* nas
configurações depois de ler a seção de segurança acima. Com a opção ligada, o
que acontece depende de como o ArchClip foi instalado:

- **Via `install.sh`** — baixa o tarball da release, extrai para
  `versions/<nova>` e repõe o symlink `current`. Um aviso pede que você
  reinicie o app. Versões antigas são podadas (as duas mais recentes ficam).
- **Via pacman/AUR** — só avisa; atualizar é trabalho do gerenciador de
  pacotes.
- **Rodando do código-fonte** — só avisa; use `git pull`.

Para publicar uma release: crie a tag `vX.Y.Z` no GitHub com o mesmo valor de
`__version__` em `archclip/__init__.py`.

---

## Testes

Só a biblioteca padrão — nada para instalar:

```bash
python -m unittest discover -v    # ou, mais curto: python -m unittest
```

A suíte cobre a lógica pura: histórico (ordenação, deduplicação, fixação,
limite, remoção de blobs), busca (acentos, caixa, curingas do LIKE, textos
longos), configuração (persistência atômica, resiliência a JSON corrompido),
seleção de tipo MIME, e o atualizador (comparação de versões, allowlist de
host, recusa de path traversal em tarballs).

Cobre também a ponte com a extensão: o `ShellBackend` contra um barramento de
mentira (leitura de binário, erro de D-Bus virando `ClipboardError`,
assinatura do sinal) e o monitor nos três modos, com a política de captura
(pausa, dica de senha, limite de tamanho, deduplicação). Como nada liga o
Python ao JS em tempo de execução, um teste confere que os dois concordam no
UUID, no nome do barramento e nos métodos declarados — é o que pega a extensão
e o daemon saindo de sincronia.

Os testes de atalho, monitor e extensão importam GTK/GIO e se **pulam
sozinhos** onde o PyGObject não estiver disponível; os de permissão POSIX
pulam fora do Linux. Na Arch com as dependências instaladas, a suíte roda
inteira.

---

## Estrutura do código

```
archclip/
├── __main__.py     entrada; caminho rápido de D-Bus para --toggle
├── app.py          Adw.Application: daemon, ações, ciclo de vida
├── config.py       config.json com escrita atômica
├── storage.py      histórico em SQLite
├── clipboard.py    escolha de backend: Shell, wl-clipboard ou xclip
├── shellext.py     ponte D-Bus com a extensão do GNOME Shell
├── monitor.py      thread que vigia mudanças na seleção
├── hotkey.py       registro do atalho e liberação de conflitos no GNOME
├── autostart.py    .desktop em ~/.config/autostart
├── updater.py      releases do GitHub e instalação
├── gtkdeps.py      gi.require_version centralizado
└── ui/
    ├── window.py   janela do histórico
    ├── settings.py preferências e captura de atalho
    ├── rows.py     linha da lista
    └── style.css

extension/          extensão do GNOME Shell (JS), quem vigia a seleção
├── extension.js
└── metadata.json

tests/              suíte em unittest (sem dependências externas)
```

---

## Problemas comuns

**O `Super + V` não faz nada.**
Faça logout/login. Se persistir, confira o registro:

```bash
gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings
gsettings get org.gnome.shell.keybindings toggle-message-tray
```

O primeiro deve conter `.../custom-keybindings/archclip/`; o segundo **não**
deve mais conter `<Super>v`.

**O `Super + V` abre a janela, mas o histórico fica vazio.**
A extensão do Shell não está no ar — a janela diz isso no topo. Confira:

```bash
gnome-extensions info archclip@theuszma.github.io
```

- *não existe* ou *INACTIVE* logo depois de instalar: falta o logout/login,
  porque o GNOME Shell só carrega extensões novas no começo da sessão.
- *ERROR*: veja o que ela reclamou com
  `journalctl --user -b -u gnome-shell | grep -i archclip`.
- *DISABLED*: ligue com `gnome-extensions enable archclip@theuszma.github.io`,
  e confira se as extensões de usuário não estão desligadas de vez
  (`gsettings get org.gnome.shell disable-user-extensions`).

Não adianta testar com `wl-paste --watch`: ele nunca funciona no GNOME, por
mais nova que seja a sua versão — o Mutter não implementa data-control.

**A janela abre atrás de outras.**
No Wayland o app não controla o próprio posicionamento nem o empilhamento —
isso é decisão do Mutter. Para mantê-la à frente, ligue *Manter sempre
visível* nas configurações; quem faz o trabalho é a extensão do Shell.

**Copiei uma senha e ela apareceu no histórico.**
Nem todo gerenciador marca a seleção como secreta. Apague o item com
`Delete` ou ligue *Limpar ao encerrar* nas configurações.

---

## Licença

MIT.
