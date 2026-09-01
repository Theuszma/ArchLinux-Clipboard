"""Aceleradores e autostart.

Estes módulos importam GTK, então a suíte pula tudo onde o PyGObject não
estiver disponível (por exemplo numa máquina de desenvolvimento sem GTK4).
Na Arch com as dependências instaladas, roda normalmente.
"""

import unittest

try:
    from archclip import autostart, hotkey

    GTK_ERROR = ""
except (ImportError, ValueError, SystemExit) as exc:  # gtkdeps aborta sem PyGObject
    autostart = hotkey = None
    GTK_ERROR = str(exc) or "PyGObject/GTK4 indisponível"


@unittest.skipIf(hotkey is None, "GTK indisponível: " + GTK_ERROR)
class TestNormalizeAccel(unittest.TestCase):
    def test_forma_canonica(self):
        self.assertEqual(hotkey.normalize_accel("<Super>v"), "<Super>v")

    def test_caixa_da_tecla_nao_importa_sem_shift(self):
        # O GNOME grava '<Super>v'; a captura pode devolver '<Super>V'.
        self.assertEqual(
            hotkey.normalize_accel("<Super>V"), hotkey.normalize_accel("<Super>v")
        )

    def test_caixa_do_modificador_nao_importa(self):
        self.assertEqual(
            hotkey.normalize_accel("<super>v"), hotkey.normalize_accel("<Super>v")
        )

    def test_shift_e_preservado(self):
        com_shift = hotkey.normalize_accel("<Super><Shift>v")
        self.assertNotEqual(com_shift, hotkey.normalize_accel("<Super>v"))
        self.assertIn("Shift", com_shift)

    def test_acelerador_invalido(self):
        self.assertEqual(hotkey.normalize_accel("isso nao existe"), "")
        self.assertEqual(hotkey.normalize_accel(""), "")


@unittest.skipIf(hotkey is None, "GTK indisponível: " + GTK_ERROR)
class TestValidAccel(unittest.TestCase):
    def test_exige_modificador(self):
        self.assertTrue(hotkey.is_valid_accel("<Super>v"))
        self.assertTrue(hotkey.is_valid_accel("<Control><Alt>v"))
        self.assertTrue(hotkey.is_valid_accel("<Alt>space"))

    def test_tecla_solta_recusada(self):
        # Sem modificador o atalho engoliria uma tecla comum do sistema.
        self.assertFalse(hotkey.is_valid_accel("v"))
        self.assertFalse(hotkey.is_valid_accel("F5"))

    def test_shift_sozinho_nao_basta(self):
        self.assertFalse(hotkey.is_valid_accel("<Shift>v"))

    def test_lixo_recusado(self):
        self.assertFalse(hotkey.is_valid_accel(""))
        self.assertFalse(hotkey.is_valid_accel("<Super>"))


@unittest.skipIf(hotkey is None, "GTK indisponível: " + GTK_ERROR)
class TestAccelLabel(unittest.TestCase):
    def test_rotulo_legivel(self):
        rotulo = hotkey.accel_label("<Super>v")
        self.assertIn("V", rotulo.upper())

    def test_acelerador_invalido_vira_nenhum(self):
        self.assertEqual(hotkey.accel_label("xxx"), "Nenhum")


@unittest.skipIf(hotkey is None, "GTK indisponível: " + GTK_ERROR)
class TestLauncherCommand(unittest.TestCase):
    def test_inclui_o_argumento(self):
        self.assertTrue(hotkey.launcher_command("--toggle").endswith("--toggle"))

    def test_menciona_o_archclip(self):
        self.assertIn("archclip", hotkey.launcher_command("--toggle"))

    def test_comando_nao_vem_vazio(self):
        self.assertNotEqual(hotkey.launcher_command("--daemon").strip(), "")


@unittest.skipIf(hotkey is None, "GTK indisponível: " + GTK_ERROR)
class TestManualBackend(unittest.TestCase):
    def test_backend_manual_nao_registra_sozinho(self):
        backend = hotkey.HotkeyBackend()
        self.assertFalse(backend.automatic)
        self.assertNotEqual(backend.apply("<Super>v"), "")

    def test_instrucoes_trazem_o_comando(self):
        instrucoes = hotkey.HotkeyBackend().instructions("<Super>v")
        self.assertIn("--toggle", instrucoes)


@unittest.skipIf(autostart is None, "GTK indisponível: " + GTK_ERROR)
class TestAutostart(unittest.TestCase):
    def tearDown(self):
        autostart.set_enabled(False)

    def test_liga_e_desliga(self):
        self.assertEqual(autostart.set_enabled(True), "")
        self.assertTrue(autostart.is_enabled())
        self.assertEqual(autostart.set_enabled(False), "")
        self.assertFalse(autostart.is_enabled())

    def test_desligar_duas_vezes_nao_explode(self):
        autostart.set_enabled(False)
        self.assertEqual(autostart.set_enabled(False), "")

    def test_desktop_file_tem_o_essencial(self):
        autostart.set_enabled(True)
        conteudo = autostart.AUTOSTART_FILE.read_text(encoding="utf-8")
        self.assertIn("[Desktop Entry]", conteudo)
        self.assertIn("--daemon", conteudo)
        self.assertIn("X-GNOME-Autostart-enabled=true", conteudo)

    def test_refresh_reescreve_so_se_habilitado(self):
        autostart.set_enabled(False)
        autostart.refresh()
        self.assertFalse(autostart.is_enabled())
        autostart.set_enabled(True)
        autostart.refresh()
        self.assertTrue(autostart.is_enabled())


if __name__ == "__main__":
    unittest.main()
