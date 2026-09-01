"""Utilitários: caminhos, hashing e formatação em pt-BR."""

import os
import stat
import time
import unittest
from datetime import datetime, timedelta

from archclip import util
from archclip.util import elide, human_size, human_time, sha256_bytes


class TestElide(unittest.TestCase):
    def test_colapsa_espacos(self):
        self.assertEqual(elide("a   b\n\nc\td"), "a b c d")

    def test_texto_curto_intacto(self):
        self.assertEqual(elide("curto", 20), "curto")

    def test_corta_com_reticencias(self):
        resultado = elide("x" * 50, 10)
        self.assertEqual(len(resultado), 10)
        self.assertTrue(resultado.endswith("…"))

    def test_limite_exato_nao_corta(self):
        self.assertEqual(elide("abcde", 5), "abcde")

    def test_preserva_acentuacao(self):
        self.assertEqual(elide("ação  e   coração"), "ação e coração")

    def test_string_vazia(self):
        self.assertEqual(elide(""), "")


class TestHumanTime(unittest.TestCase):
    def test_agora(self):
        self.assertEqual(human_time(time.time()), "agora")
        self.assertEqual(human_time(time.time() - 10), "agora")

    def test_minutos(self):
        self.assertEqual(human_time(time.time() - 600), "há 10 min")

    def test_uma_hora_no_singular(self):
        self.assertEqual(human_time(time.time() - 3700), "há 1 h")

    def test_varias_horas(self):
        self.assertEqual(human_time(time.time() - 7300), "há 2 h")

    def test_ontem_mostra_a_hora(self):
        ontem = datetime.now() - timedelta(days=1)
        resultado = human_time(ontem.timestamp())
        self.assertTrue(resultado.startswith("ontem "))
        self.assertRegex(resultado, r"ontem \d{2}:\d{2}")

    def test_dias_atras(self):
        tres_dias = datetime.now() - timedelta(days=3)
        self.assertEqual(human_time(tres_dias.timestamp()), "3 dias atrás")

    def test_data_completa_apos_uma_semana(self):
        antigo = datetime.now() - timedelta(days=30)
        self.assertRegex(human_time(antigo.timestamp()), r"\d{2}/\d{2}/\d{4}")


class TestHumanSize(unittest.TestCase):
    def test_bytes_sem_decimal(self):
        self.assertEqual(human_size(512), "512 B")

    def test_kilobytes(self):
        self.assertEqual(human_size(1536), "1.5 KB")

    def test_megabytes(self):
        self.assertEqual(human_size(5 * 1024 * 1024), "5.0 MB")

    def test_zero(self):
        self.assertEqual(human_size(0), "0 B")


class TestHash(unittest.TestCase):
    def test_deterministico(self):
        self.assertEqual(sha256_bytes(b"abc"), sha256_bytes(b"abc"))

    def test_conteudos_diferentes_diferem(self):
        self.assertNotEqual(sha256_bytes(b"abc"), sha256_bytes(b"abd"))

    def test_tamanho_hexadecimal(self):
        digest = sha256_bytes(b"qualquer coisa")
        self.assertEqual(len(digest), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in digest))


class TestPaths(unittest.TestCase):
    def test_respeita_as_variaveis_xdg(self):
        # O sandbox da suíte define XDG_DATA_HOME; os caminhos devem segui-lo.
        self.assertTrue(str(util.DATA_DIR).startswith(os.environ["XDG_DATA_HOME"]))
        self.assertTrue(str(util.CONFIG_DIR).startswith(os.environ["XDG_CONFIG_HOME"]))
        self.assertTrue(str(util.CACHE_DIR).startswith(os.environ["XDG_CACHE_HOME"]))

    def test_blobs_dentro_de_data(self):
        self.assertEqual(util.BLOB_DIR.parent, util.DATA_DIR)
        self.assertEqual(util.DB_PATH.parent, util.DATA_DIR)

    def test_thumbs_no_cache(self):
        # Miniatura é derivada: cabe no cache, não nos dados.
        self.assertEqual(util.THUMB_DIR.parent, util.CACHE_DIR)

    def test_ensure_dirs_e_idempotente(self):
        util.ensure_dirs()
        util.ensure_dirs()
        for path in (util.CONFIG_DIR, util.DATA_DIR, util.BLOB_DIR, util.THUMB_DIR):
            self.assertTrue(path.is_dir(), path)


class TestHarden(unittest.TestCase):
    def test_modos_restritos_ao_dono(self):
        self.assertEqual(util.DIR_MODE, 0o700)
        self.assertEqual(util.FILE_MODE, 0o600)

    def test_arquivo_inexistente_nao_explode(self):
        util.harden(util.DATA_DIR / "nao-existe", util.FILE_MODE)

    @unittest.skipUnless(os.name == "posix", "permissões POSIX só valem no Linux")
    def test_aplica_o_modo(self):
        util.ensure_dirs()
        alvo = util.DATA_DIR / "arquivo-de-teste"
        alvo.write_text("x", encoding="utf-8")
        try:
            util.harden(alvo, util.FILE_MODE)
            self.assertEqual(stat.S_IMODE(os.stat(alvo).st_mode), 0o600)
        finally:
            alvo.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
