"""Seleção de tipo MIME e detecção de conteúdo sensível."""

import unittest

from archclip import clipboard
from archclip.clipboard import is_sensitive, pick_type


class TestPickType(unittest.TestCase):
    def test_imagem_tem_prioridade_sobre_texto(self):
        tipos = ["text/plain", "text/plain;charset=utf-8", "image/png"]
        self.assertEqual(pick_type(tipos, True, True), "image/png")

    def test_ordem_de_preferencia_entre_imagens(self):
        self.assertEqual(pick_type(["image/jpeg", "image/png"], True, True), "image/png")
        self.assertEqual(pick_type(["image/jpeg", "image/bmp"], True, True), "image/jpeg")

    def test_texto_utf8_preferido(self):
        tipos = ["text/plain", "text/plain;charset=utf-8", "STRING"]
        self.assertEqual(pick_type(tipos, True, False), "text/plain;charset=utf-8")

    def test_utf8_string_do_x11(self):
        self.assertEqual(pick_type(["UTF8_STRING", "STRING"], True, True), "UTF8_STRING")

    def test_qualquer_text_como_ultimo_recurso(self):
        self.assertEqual(pick_type(["text/html"], True, True), "text/html")
        self.assertEqual(pick_type(["text/csv"], True, True), "text/csv")

    def test_captura_de_imagem_desligada_cai_no_texto(self):
        tipos = ["image/png", "text/plain;charset=utf-8"]
        self.assertEqual(pick_type(tipos, True, False), "text/plain;charset=utf-8")

    def test_captura_de_texto_desligada_pega_so_imagem(self):
        tipos = ["image/png", "text/plain;charset=utf-8"]
        self.assertEqual(pick_type(tipos, False, True), "image/png")

    def test_tudo_desligado_nao_pega_nada(self):
        self.assertIsNone(pick_type(["image/png", "text/plain"], False, False))

    def test_sem_tipo_interessante(self):
        self.assertIsNone(pick_type(["TIMESTAMP", "TARGETS"], True, True))

    def test_lista_vazia(self):
        self.assertIsNone(pick_type([], True, True))

    def test_comparacao_ignora_caixa(self):
        # Alvos do X11 costumam vir em maiúsculas.
        self.assertEqual(pick_type(["IMAGE/PNG"], True, True), "IMAGE/PNG")

    def test_devolve_o_tipo_como_o_sistema_escreveu(self):
        resultado = pick_type(["Text/Plain;charset=UTF-8"], True, False)
        self.assertEqual(resultado, "Text/Plain;charset=UTF-8")


class TestSensitive(unittest.TestCase):
    def test_detecta_dica_de_gerenciador_de_senha(self):
        self.assertTrue(is_sensitive(["text/plain", "x-kde-passwordManagerHint"]))

    def test_ignora_caixa(self):
        self.assertTrue(is_sensitive(["X-KDE-PASSWORDMANAGERHINT"]))

    def test_dica_com_valor_anexado(self):
        self.assertTrue(is_sensitive(["x-kde-passwordManagerHint=secret"]))

    def test_selecao_comum_nao_e_sensivel(self):
        self.assertFalse(is_sensitive(["text/plain", "text/html", "image/png"]))

    def test_lista_vazia(self):
        self.assertFalse(is_sensitive([]))


class TestBackendDetection(unittest.TestCase):
    def test_detect_backend_e_coerente(self):
        backend, erro = clipboard.detect_backend()
        # Ou temos backend e nenhum erro, ou o contrário -- nunca os dois.
        self.assertNotEqual(backend is None, erro == "")

    def test_erro_diz_como_resolver(self):
        backend, erro = clipboard.detect_backend()
        if backend is None:
            self.assertIn("pacman", erro)

    def test_backend_base_nao_promete_watch(self):
        self.assertIsNone(clipboard.Backend().watch_command())

    def test_wayland_usa_watch(self):
        comando = clipboard.WaylandBackend().watch_command()
        self.assertEqual(comando[:2], ["wl-paste", "--watch"])

    def test_x11_nao_tem_watch(self):
        # Sem evento de mudança no X11; o monitor cai no polling.
        self.assertIsNone(clipboard.X11Backend().watch_command())


if __name__ == "__main__":
    unittest.main()
