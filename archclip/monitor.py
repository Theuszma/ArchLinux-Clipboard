"""Vigia o clipboard em segundo plano e entrega capturas na thread do GTK.

Três modos, escolhidos pelo que o backend oferece:

- `signal`: a extensão do GNOME Shell avisa por D-Bus quando a seleção muda.
- `watch`: `wl-paste --watch` emite uma linha por mudança.
- `poll`: sem evento nenhum, comparamos o conteúdo periodicamente (X11).
"""

from __future__ import annotations

import subprocess
import threading
import time
from typing import Callable, Optional

from .gtkdeps import GLib

from . import clipboard
from .clipboard import Backend
from .config import Config
from .util import sha256_bytes

# Quanto esperar antes de ler a seleção, para o app de origem terminar de
# publicar todos os tipos MIME.
SETTLE_DELAY = 0.05
POLL_INTERVAL = 0.7  # só no fallback X11
STOP_CHECK_INTERVAL = 0.5  # no modo signal, para notar o pedido de parada

# `wl-paste --watch` só funciona onde o compositor expõe data-control, e o
# Mutter não expõe. Insistir não adianta: é característica do compositor, não
# um erro passageiro.
WATCH_UNSUPPORTED_MARKER = "data-control"

CaptureCallback = Callable[[str, bytes], None]
StatusCallback = Callable[[str], None]


class Monitor:
    """Vigia a seleção numa thread dedicada, no melhor modo disponível.

    Os callbacks `on_capture(mime, data)` e `on_status(erro)` são sempre
    invocados na thread principal. `on_status` recebe "" quando a captura
    volta a funcionar.
    """

    def __init__(
        self,
        config: Config,
        backend: Backend,
        on_capture: CaptureCallback,
        on_status: Optional[StatusCallback] = None,
    ) -> None:
        self.config = config
        self.backend = backend
        self.on_capture = on_capture
        self.on_status = on_status

        self._thread: Optional[threading.Thread] = None
        self._process: Optional[subprocess.Popen] = None
        self._stop = threading.Event()
        self._changed = threading.Event()
        self._unsubscribe: Optional[Callable[[], None]] = None
        self._last_digest: str = ""
        self._lock = threading.Lock()

        self.mode = ""
        self.paused = False
        self.last_error: str = ""

    # ------------------------------------------------------------ ciclo de vida

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._changed.clear()

        # A assinatura precisa existir antes da thread, que só reage ao que
        # ela sinaliza.
        self._unsubscribe = self.backend.watch_signal(self._on_change)
        if self._unsubscribe is not None:
            self.mode, target = "signal", self._run_signal
        elif self.backend.watch_command():
            self.mode, target = "watch", self._run_watch
        else:
            self.mode, target = "poll", self._run_poll

        self._thread = threading.Thread(target=target, name="archclip-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._changed.set()  # acorda o modo signal para ele ver a parada
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        process = self._process
        if process and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def note_own_write(self, data: bytes) -> None:
        """Marca conteúdo que nós mesmos colocamos no clipboard.

        Evita que colar um item do histórico dispare uma captura redundante.
        """
        with self._lock:
            self._last_digest = sha256_bytes(data)

    # ----------------------------------------------------------------- loops

    def _on_change(self) -> None:
        """Chamado pela extensão na thread principal: só acorda o worker.

        A leitura em si é bloqueante (round-trip de D-Bus com o Shell), então
        não pode acontecer aqui, ou a janela travaria a cada cópia.
        """
        self._changed.set()

    def _run_signal(self) -> None:
        """GNOME: a extensão do Shell avisa a cada mudança de seleção."""
        # O que já estava no clipboard quando o daemon subiu também conta --
        # é o mesmo que o `wl-paste --watch` faz ao iniciar.
        self._changed.set()
        while not self._stop.is_set():
            if not self._changed.wait(STOP_CHECK_INTERVAL):
                continue
            self._changed.clear()
            if self._stop.is_set():
                return
            self._capture()

    def _run_watch(self) -> None:
        """Wayland: wl-paste --watch emite uma linha a cada mudança."""
        command = self.backend.watch_command()
        while not self._stop.is_set():
            try:
                self._process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=1,
                    text=True,
                )
            except OSError as exc:
                self._fail("Não consegui iniciar wl-paste --watch: {}".format(exc))
                return

            assert self._process.stdout is not None
            for _line in self._process.stdout:
                if self._stop.is_set():
                    break
                time.sleep(SETTLE_DELAY)
                self._capture()

            if self._stop.is_set():
                return

            # wl-paste morreu: ou o compositor reiniciou, ou ele não expõe o
            # protocolo data-control.
            stderr = ""
            if self._process.stderr is not None:
                stderr = self._process.stderr.read().strip()

            if WATCH_UNSUPPORTED_MARKER in stderr:
                # Caso do GNOME. Repetir a cada 3 s só gastaria processo à
                # toa; o que resolve é a extensão do Shell, e quando ela
                # subir o app troca de backend e reinicia o monitor.
                print(
                    "archclip: o compositor não expõe data-control "
                    "(no GNOME é decisão do Mutter, não falta de versão): "
                    "quem vigia a seleção é a extensão do GNOME Shell."
                )
                self._fail(_unsupported_message())
                return

            self._fail(stderr or "wl-paste --watch terminou inesperadamente")
            self._stop.wait(3)

    def _run_poll(self) -> None:
        """X11: sem evento de mudança, comparamos o conteúdo periodicamente."""
        while not self._stop.is_set():
            self._capture()
            self._stop.wait(POLL_INTERVAL)

    # --------------------------------------------------------------- captura

    def _capture(self) -> None:
        if self.paused:
            return
        try:
            types = self.backend.list_types()
        except (clipboard.ClipboardError, OSError, subprocess.SubprocessError) as exc:
            self._fail(str(exc))
            return
        if not types:
            return

        if self.config.get("ignore_password_managers") and clipboard.is_sensitive(types):
            return

        mime = clipboard.pick_type(
            types,
            want_text=self.config.get("capture_text"),
            want_images=self.config.get("capture_images"),
        )
        if mime is None:
            return

        try:
            data = self.backend.read(mime)
        except (clipboard.ClipboardError, OSError, subprocess.SubprocessError) as exc:
            self._fail(str(exc))
            return
        if not data:
            return

        limit = int(self.config.get("max_item_size_mb")) * 1024 * 1024
        if limit and len(data) > limit:
            return

        digest = sha256_bytes(data)
        with self._lock:
            if digest == self._last_digest:
                return
            self._last_digest = digest

        if self.last_error:
            # Voltou a funcionar: avisa a interface para tirar o alerta.
            self.last_error = ""
            self._report("")
        GLib.idle_add(self.on_capture, mime, data)

    def _fail(self, message: str) -> None:
        if message and message != self.last_error:
            self.last_error = message
            print("archclip: monitor:", message)
            self._report(message)

    def _report(self, message: str) -> None:
        if self.on_status is not None:
            GLib.idle_add(self.on_status, message)


def _unsupported_message() -> str:
    """O que fazer, em texto curto o bastante para caber no banner.

    O porquê -- o Mutter não implementa data-control -- vai para a saída
    padrão: numa faixa de duas linhas, a explicação empurraria para fora
    justamente a parte que resolve.
    """
    try:
        from . import shellext
    except ImportError:
        return "o compositor não expõe o protocolo data-control"
    if not shellext.is_gnome():
        return "o compositor não expõe o protocolo data-control"
    return shellext.missing_hint()
