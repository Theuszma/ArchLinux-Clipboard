"""Ponte D-Bus com a extensão do GNOME Shell.

`shellext` importa o GIO, então a suíte pula tudo onde o PyGObject não
estiver disponível -- mesma regra do `test_hotkey`.
"""

import json
import unittest
from pathlib import Path

try:
    from gi.repository import GLib

    from archclip import shellext
    from archclip.clipboard import ClipboardError

    GI_ERROR = ""
except (ImportError, ValueError, SystemExit) as exc:
    GLib = shellext = ClipboardError = None
    GI_ERROR = str(exc) or "PyGObject indisponível"

EXTENSION_DIR = Path(__file__).resolve().parent.parent / "extension"


class FakeBus:
    """Conexão de sessão de mentira, para não precisar de um Shell rodando."""

    def __init__(self, reply=None, error=None):
        self.reply = reply
        self.error = error
        self.calls = []
        self.subscriptions = []
        self.unsubscribed = []

    def call_sync(self, name, path, interface, method, params, reply_type, flags, timeout, cancellable):
        self.calls.append((name, path, interface, method, params, timeout))
        if self.error is not None:
            raise self.error
        return self.reply

    def signal_subscribe(self, sender, interface, member, path, arg0, flags, callback):
        self.subscriptions.append((sender, interface, member, path, callback))
        return 42

    def signal_unsubscribe(self, subscription):
        self.unsubscribed.append(subscription)


@unittest.skipIf(shellext is None, "PyGObject indisponível: " + GI_ERROR)
class TestShellBackend(unittest.TestCase):
    def test_list_types(self):
        bus = FakeBus(GLib.Variant("(as)", (["image/png", "text/plain"],)))
        self.assertEqual(
            shellext.ShellBackend(bus).list_types(), ["image/png", "text/plain"]
        )

    def test_list_types_vazio(self):
        bus = FakeBus(GLib.Variant("(as)", ([],)))
        self.assertEqual(shellext.ShellBackend(bus).list_types(), [])

    def test_read_devolve_bytes(self):
        dados = b"\x89PNG\r\n\x1a\n conte\xc3\xbado bin\xc3\xa1rio \x00\xff"
        bus = FakeBus(GLib.Variant("(ay)", (dados,)))
        self.assertEqual(shellext.ShellBackend(bus).read("image/png"), dados)

    def test_read_de_selecao_vazia(self):
        bus = FakeBus(GLib.Variant("(ay)", (b"",)))
        self.assertEqual(shellext.ShellBackend(bus).read("text/plain"), b"")

    def test_read_pede_o_tipo_certo(self):
        bus = FakeBus(GLib.Variant("(ay)", (b"x",)))
        shellext.ShellBackend(bus).read("image/png")
        _name, _path, _iface, method, params, timeout = bus.calls[0]
        self.assertEqual(method, "GetSelection")
        self.assertEqual(params.unpack(), ("image/png",))
        # A extensão desiste de uma transferência em 10 s; esperar menos que
        # isso trocaria o erro dela, específico, pelo nosso timeout.
        self.assertGreater(timeout, 10000)

    def test_write_manda_mime_e_dados(self):
        bus = FakeBus()
        shellext.ShellBackend(bus).write(b"copiado", "text/plain;charset=utf-8")
        _name, _path, _iface, method, params, _timeout = bus.calls[0]
        self.assertEqual(method, "SetSelection")
        mime, dados = params.unpack()
        self.assertEqual(mime, "text/plain;charset=utf-8")
        self.assertEqual(bytes(dados), b"copiado")

    def test_erro_de_dbus_vira_clipboard_error(self):
        bus = FakeBus(error=GLib.Error("o Shell não respondeu"))
        with self.assertRaises(ClipboardError) as capturado:
            shellext.ShellBackend(bus).list_types()
        self.assertIn("o Shell não respondeu", str(capturado.exception))

    def test_erro_diz_de_onde_veio(self):
        bus = FakeBus(error=GLib.Error("qualquer coisa"))
        with self.assertRaises(ClipboardError) as capturado:
            shellext.ShellBackend(bus).read("text/plain")
        self.assertIn("extensão do GNOME Shell", str(capturado.exception))

    def test_watch_signal_assina_o_sinal_certo(self):
        bus = FakeBus()
        backend = shellext.ShellBackend(bus)
        cancelar = backend.watch_signal(lambda: None)
        sender, interface, member, path, _callback = bus.subscriptions[0]
        self.assertEqual(sender, shellext.BUS_NAME)
        self.assertEqual(interface, shellext.INTERFACE)
        self.assertEqual(member, "SelectionChanged")
        self.assertEqual(path, shellext.OBJECT_PATH)
        cancelar()
        self.assertEqual(bus.unsubscribed, [42])

    def test_watch_signal_chama_de_volta(self):
        bus = FakeBus()
        avisos = []
        shellext.ShellBackend(bus).watch_signal(lambda: avisos.append(1))
        _sender, _iface, _member, _path, callback = bus.subscriptions[0]
        # O GIO passa (conexão, remetente, caminho, interface, sinal, params).
        callback(bus, ":1.7", shellext.OBJECT_PATH, shellext.INTERFACE,
                 "SelectionChanged", GLib.Variant("(as)", (["text/plain"],)))
        self.assertEqual(len(avisos), 1)

    def test_set_window_above_manda_o_booleano(self):
        bus = FakeBus()
        shellext.ShellBackend(bus)  # a janela não é assunto do backend
        erro = shellext.set_window_above(True, connection=bus)
        self.assertEqual(erro, "")
        _name, _path, _iface, method, params, _timeout = bus.calls[0]
        self.assertEqual(method, "SetWindowAbove")
        self.assertEqual(params.unpack(), (True,))

    def test_set_window_above_devolve_o_erro(self):
        bus = FakeBus(error=GLib.Error("método desconhecido"))
        self.assertIn("método desconhecido", shellext.set_window_above(False, connection=bus))

    def test_has_method_le_a_introspeccao(self):
        xml = '<node><interface name="x"><method name="SetWindowAbove"/></interface></node>'
        bus = FakeBus(GLib.Variant("(s)", (xml,)))
        self.assertTrue(shellext.has_method("SetWindowAbove", connection=bus))
        self.assertFalse(shellext.has_method("GetSelection", connection=bus))

    def test_has_method_sem_extensao_e_falso(self):
        bus = FakeBus(error=GLib.Error("sem ninguém no barramento"))
        self.assertFalse(shellext.has_method("SetWindowAbove", connection=bus))

    def test_backend_tem_nome_proprio(self):
        # O app usa esse nome para saber se já está no backend certo.
        self.assertEqual(shellext.ShellBackend(FakeBus()).name, "gnome-shell")


@unittest.skipIf(shellext is None, "PyGObject indisponível: " + GI_ERROR)
class TestAmbiente(unittest.TestCase):
    def test_is_gnome_le_o_xdg_current_desktop(self):
        import os

        original = os.environ.get("XDG_CURRENT_DESKTOP")
        try:
            os.environ["XDG_CURRENT_DESKTOP"] = "ubuntu:GNOME"
            self.assertTrue(shellext.is_gnome())
            os.environ["XDG_CURRENT_DESKTOP"] = "sway"
            self.assertFalse(shellext.is_gnome())
        finally:
            if original is None:
                os.environ.pop("XDG_CURRENT_DESKTOP", None)
            else:
                os.environ["XDG_CURRENT_DESKTOP"] = original

    def test_extension_dir_respeita_xdg_data_home(self):
        caminho = shellext.extension_dir()
        self.assertEqual(caminho.name, shellext.UUID)
        self.assertEqual(caminho.parent.name, "extensions")
        self.assertEqual(caminho.parent.parent.name, "gnome-shell")

    def test_missing_hint_diz_o_que_fazer(self):
        dica = shellext.missing_hint()
        self.assertTrue("install.sh" in dica or "gnome-extensions enable" in dica)


@unittest.skipIf(not EXTENSION_DIR.exists(), "extension/ não está junto (instalação)")
@unittest.skipIf(shellext is None, "PyGObject indisponível: " + GI_ERROR)
class TestContratoComAExtensao(unittest.TestCase):
    """O Python e o JS precisam concordar em nomes; nada os liga em runtime."""

    @classmethod
    def setUpClass(cls):
        cls.metadata = json.loads((EXTENSION_DIR / "metadata.json").read_text(encoding="utf-8"))
        cls.source = (EXTENSION_DIR / "extension.js").read_text(encoding="utf-8")

    def test_uuid_bate_com_o_metadata(self):
        self.assertEqual(self.metadata["uuid"], shellext.UUID)

    def test_metadata_cobre_gnome_45_em_diante(self):
        # Antes do 45 as extensões não eram módulos ES; o extension.js é ESM.
        versoes = self.metadata["shell-version"]
        self.assertTrue(all(int(v.split(".")[0]) >= 45 for v in versoes), versoes)

    def test_nome_do_barramento_e_caminho_batem(self):
        self.assertIn(shellext.BUS_NAME, self.source)
        self.assertIn(shellext.OBJECT_PATH, self.source)

    def test_a_extensao_declara_os_metodos_que_chamamos(self):
        for metodo in ("GetMimetypes", "GetSelection", "SetSelection", "SetWindowAbove"):
            with self.subTest(metodo=metodo):
                self.assertIn('<method name="{}"'.format(metodo), self.source)

    def test_a_extensao_declara_o_sinal_que_assinamos(self):
        self.assertIn('<signal name="SelectionChanged"', self.source)

    def test_a_extensao_desfaz_o_que_faz(self):
        # Sem isso o serviço continuaria no ar depois de desligada.
        self.assertIn("bus_unown_name", self.source)
        self.assertIn("unexport", self.source)
        # E uma janela presa acima de todas seria um estrago sem dono.
        self.assertIn("unmake_above", self.source)

    def test_so_janelas_do_arquiclip_sobem(self):
        # Um serviço que levantasse qualquer janela seria brinquedo de
        # qualquer processo da sessão.
        self.assertIn("const APP_ID = 'io.github.theuszma.ArchClip'", self.source)
        self.assertIn("_isOurWindow", self.source)


if __name__ == "__main__":
    unittest.main()
