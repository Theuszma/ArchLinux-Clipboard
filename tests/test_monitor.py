"""Modos do monitor e a política de captura.

`monitor` importa GTK pelo `gtkdeps`, então a suíte pula tudo onde o
PyGObject não estiver disponível.
"""

import time
import unittest

try:
    from gi.repository import GLib

    from archclip.clipboard import Backend, ClipboardError
    from archclip.config import Config
    from archclip.monitor import Monitor, _unsupported_message

    GTK_ERROR = ""
except (ImportError, ValueError, SystemExit) as exc:
    GLib = Backend = ClipboardError = Config = Monitor = None
    _unsupported_message = None
    GTK_ERROR = str(exc) or "PyGObject/GTK4 indisponível"

TEXTO = "text/plain;charset=utf-8"


if Backend is not None:

    class FakeBackend(Backend):
        """Backend controlado pelo teste, sem processo nem D-Bus."""

        name = "fake"

        def __init__(self, types=None, data="conteúdo".encode(), *, com_sinal=True, comando=None):
            self.types = types if types is not None else [TEXTO]
            self.data = data
            self.com_sinal = com_sinal
            self.comando = comando
            self.erro_na_leitura = None
            self.on_change = None
            self.cancelado = False

        def list_types(self):
            return list(self.types)

        def read(self, mime):
            if self.erro_na_leitura is not None:
                raise self.erro_na_leitura
            return self.data

        def write(self, data, mime):
            self.data = data

        def watch_command(self):
            return self.comando

        def watch_signal(self, on_change):
            if not self.com_sinal:
                return None
            self.on_change = on_change

            def cancelar():
                self.cancelado = True

            return cancelar

        def mudou(self, data=None, types=None):
            """Simula a extensão avisando que a seleção mudou."""
            if data is not None:
                self.data = data
            if types is not None:
                self.types = types
            self.on_change()


def bombear(condicao, limite=5.0):
    """Roda o loop do GLib até a condição valer (as capturas vêm por idle_add)."""
    contexto = GLib.MainContext.default()
    fim = time.time() + limite
    while time.time() < fim:
        while contexto.pending():
            contexto.iteration(False)
        if condicao():
            return True
        time.sleep(0.02)
    return False


@unittest.skipIf(Monitor is None, "GTK indisponível: " + GTK_ERROR)
class MonitorTestCase(unittest.TestCase):
    def setUp(self):
        self.capturas = []
        self.status = []
        self.monitores = []

    def tearDown(self):
        for monitor in self.monitores:
            monitor.stop()

    def novo(self, backend, **config):
        configuracao = Config()
        for chave, valor in config.items():
            configuracao.set(chave, valor, save=False)
        monitor = Monitor(
            configuracao,
            backend,
            lambda mime, dados: self.capturas.append((mime, dados)),
            lambda mensagem: self.status.append(mensagem),
        )
        self.monitores.append(monitor)
        return monitor


class TestEscolhaDeModo(MonitorTestCase):
    def test_sinal_tem_prioridade(self):
        # A extensão avisa de graça; nem vale olhar o watch_command.
        monitor = self.novo(FakeBackend(com_sinal=True, comando=["sleep", "5"]))
        monitor.start()
        self.assertEqual(monitor.mode, "signal")

    def test_sem_sinal_cai_no_watch(self):
        monitor = self.novo(FakeBackend(com_sinal=False, comando=["sleep", "5"]))
        monitor.start()
        self.assertEqual(monitor.mode, "watch")

    def test_sem_sinal_e_sem_watch_cai_no_polling(self):
        monitor = self.novo(FakeBackend(com_sinal=False, comando=None))
        monitor.start()
        self.assertEqual(monitor.mode, "poll")

    def test_stop_cancela_a_assinatura(self):
        backend = FakeBackend()
        monitor = self.novo(backend)
        monitor.start()
        monitor.stop()
        self.assertTrue(backend.cancelado)
        self.assertIsNone(monitor._thread)

    def test_start_duas_vezes_nao_duplica_thread(self):
        monitor = self.novo(FakeBackend())
        monitor.start()
        primeira = monitor._thread
        monitor.start()
        self.assertIs(monitor._thread, primeira)


class TestModoSinal(MonitorTestCase):
    def test_captura_o_que_ja_estava_na_selecao(self):
        # Mesmo comportamento do `wl-paste --watch`, que dispara ao iniciar.
        monitor = self.novo(FakeBackend(data="já estava aqui".encode()))
        monitor.start()
        self.assertTrue(bombear(lambda: self.capturas))
        self.assertEqual(self.capturas[0], (TEXTO, "já estava aqui".encode()))

    def test_captura_a_mudanca(self):
        backend = FakeBackend(data=b"primeiro")
        monitor = self.novo(backend)
        monitor.start()
        self.assertTrue(bombear(lambda: self.capturas))
        backend.mudou(b"segundo")
        self.assertTrue(bombear(lambda: len(self.capturas) == 2))
        self.assertEqual(self.capturas[1], (TEXTO, b"segundo"))

    def test_conteudo_repetido_nao_duplica(self):
        backend = FakeBackend(data=b"igual")
        monitor = self.novo(backend)
        monitor.start()
        self.assertTrue(bombear(lambda: self.capturas))
        backend.mudou(b"igual")
        self.assertFalse(bombear(lambda: len(self.capturas) > 1, limite=1.5))

    def test_o_que_nos_escrevemos_nao_volta_como_captura(self):
        backend = FakeBackend(data="do histórico".encode())
        monitor = self.novo(backend)
        monitor.note_own_write("do histórico".encode())
        monitor.start()
        self.assertFalse(bombear(lambda: self.capturas, limite=1.5))

    def test_pausado_nao_captura(self):
        backend = FakeBackend(data=b"segredo")
        monitor = self.novo(backend)
        monitor.paused = True
        monitor.start()
        self.assertFalse(bombear(lambda: self.capturas, limite=1.5))

    def test_imagem_passa_inteira(self):
        imagem = bytes(range(256)) * 200
        backend = FakeBackend(types=["image/png"], data=imagem)
        monitor = self.novo(backend)
        monitor.start()
        self.assertTrue(bombear(lambda: self.capturas))
        self.assertEqual(self.capturas[0], ("image/png", imagem))


class TestPolitica(MonitorTestCase):
    def test_gerenciador_de_senha_e_ignorado(self):
        backend = FakeBackend(types=[TEXTO, "x-kde-passwordManagerHint"], data=b"senha")
        monitor = self.novo(backend, ignore_password_managers=True)
        monitor.start()
        self.assertFalse(bombear(lambda: self.capturas, limite=1.5))

    def test_dica_de_senha_pode_ser_desligada(self):
        backend = FakeBackend(types=[TEXTO, "x-kde-passwordManagerHint"], data=b"senha")
        monitor = self.novo(backend, ignore_password_managers=False)
        monitor.start()
        self.assertTrue(bombear(lambda: self.capturas))

    def test_conteudo_grande_demais_e_descartado(self):
        backend = FakeBackend(data=b"x" * (2 * 1024 * 1024))
        monitor = self.novo(backend, max_item_size_mb=1)
        monitor.start()
        self.assertFalse(bombear(lambda: self.capturas, limite=1.5))

    def test_imagem_com_captura_de_imagem_desligada(self):
        backend = FakeBackend(types=["image/png"], data=b"png")
        monitor = self.novo(backend, capture_images=False)
        monitor.start()
        self.assertFalse(bombear(lambda: self.capturas, limite=1.5))

    def test_selecao_vazia_nao_vira_item(self):
        backend = FakeBackend(types=[], data=b"")
        monitor = self.novo(backend)
        monitor.start()
        self.assertFalse(bombear(lambda: self.capturas, limite=1.5))


class TestStatus(MonitorTestCase):
    def test_falha_de_leitura_vira_aviso(self):
        backend = FakeBackend()
        backend.erro_na_leitura = ClipboardError("extensão do GNOME Shell: sumiu")
        monitor = self.novo(backend)
        monitor.start()
        self.assertTrue(bombear(lambda: self.status))
        self.assertIn("sumiu", self.status[0])

    def test_voltar_a_funcionar_limpa_o_aviso(self):
        backend = FakeBackend()
        backend.erro_na_leitura = ClipboardError("falhou")
        monitor = self.novo(backend)
        monitor.start()
        self.assertTrue(bombear(lambda: self.status))
        backend.erro_na_leitura = None
        backend.mudou(b"agora vai")
        self.assertTrue(bombear(lambda: self.status[-1] == ""))
        self.assertTrue(self.capturas)

    def test_mesmo_erro_nao_repete_aviso(self):
        backend = FakeBackend(com_sinal=False, comando=None)  # polling, insiste
        backend.erro_na_leitura = ClipboardError("falhou")
        monitor = self.novo(backend)
        monitor.start()
        self.assertTrue(bombear(lambda: self.status))
        self.assertFalse(bombear(lambda: len(self.status) > 1, limite=2.0))


@unittest.skipIf(Monitor is None, "GTK indisponível: " + GTK_ERROR)
class TestMensagemDeWatchSemSuporte(unittest.TestCase):
    def _com_desktop(self, valor):
        import os

        original = os.environ.get("XDG_CURRENT_DESKTOP")
        os.environ["XDG_CURRENT_DESKTOP"] = valor
        try:
            return _unsupported_message()
        finally:
            if original is None:
                os.environ.pop("XDG_CURRENT_DESKTOP", None)
            else:
                os.environ["XDG_CURRENT_DESKTOP"] = original

    def test_no_gnome_aponta_para_a_extensao(self):
        mensagem = self._com_desktop("GNOME")
        self.assertIn("extensão", mensagem)
        self.assertTrue(
            "install.sh" in mensagem or "logout" in mensagem, mensagem
        )

    def test_fora_do_gnome_so_constata(self):
        mensagem = self._com_desktop("sway")
        self.assertIn("data-control", mensagem)
        self.assertNotIn("extensão", mensagem)

    def test_cabe_no_banner_da_janela(self):
        # A faixa da janela corta com reticências, e o corte cairia justamente
        # em cima do que resolve. O porquê vai para a saída padrão.
        prefixo = "Não estou vigiando a área de transferência: "
        for desktop in ("GNOME", "sway"):
            with self.subTest(desktop=desktop):
                self.assertLess(len(prefixo + self._com_desktop(desktop)), 130)


if __name__ == "__main__":
    unittest.main()
