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

---

## Instalação

### Dependências

```bash
sudo pacman -S --needed python python-gobject gtk4 libadwaita wl-clipboard
```

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
o app no menu e sobe o daemon já com o `Super + V` configurado.

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

A desinstalação devolve ao GNOME os atalhos que o ArchClip tinha tomado.

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

O daemon roda `wl-paste --watch` numa thread dedicada: cada mudança de
seleção vira um evento, o ArchClip lê os tipos MIME disponíveis, escolhe o
melhor (imagem > texto) e guarda.

Não usamos a API de clipboard do GDK porque, no Wayland, um cliente só recebe
eventos de seleção enquanto tem foco de teclado — inútil para um daemon em
segundo plano. O `wl-paste --watch` usa o protocolo `ext-data-control-v1`,
implementado pelo Mutter a partir do **GNOME 48**.

> **GNOME 47 ou anterior:** o Mutter ainda não expunha esse protocolo, então a
> captura em segundo plano não funciona. O ArchClip mostra um aviso na janela
> quando o `wl-paste --watch` falha.

Em sessões X11 o fallback é o `xclip`, consultado periodicamente.

Conteúdos idênticos não duplicam: o item existente volta ao topo da lista.

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
- **Atualizações** só descem de hosts do GitHub, por HTTPS, e a checagem vale
  também para o destino do redirecionamento. A extração exige o
  `filter="data"` do `tarfile` (recusa `..`, caminhos absolutos e links para
  fora da árvore); se o Python for antigo demais para isso, o ArchClip
  desiste em vez de extrair sem proteção.

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

Os testes de atalho e autostart importam GTK e se **pulam sozinhos** onde o
PyGObject não estiver disponível; os de permissão POSIX pulam fora do Linux.
Na Arch com as dependências instaladas, a suíte roda inteira.

---

## Estrutura do código

```
archclip/
├── __main__.py     entrada; caminho rápido de D-Bus para --toggle
├── app.py          Adw.Application: daemon, ações, ciclo de vida
├── config.py       config.json com escrita atômica
├── storage.py      histórico em SQLite
├── clipboard.py    leitura/escrita via wl-clipboard ou xclip
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
O daemon não está conseguindo vigiar o clipboard. Teste:

```bash
wl-paste --watch echo
```

Se não imprimir nada ao copiar algo, seu GNOME é anterior ao 48 ou falta o
`wl-clipboard`.

**A janela abre atrás de outras.**
No Wayland o app não controla o próprio posicionamento nem o empilhamento —
isso é decisão do Mutter.

**Copiei uma senha e ela apareceu no histórico.**
Nem todo gerenciador marca a seleção como secreta. Apague o item com
`Delete` ou ligue *Limpar ao encerrar* nas configurações.

---

## Licença

MIT.
