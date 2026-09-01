"""Histórico: ordenação, deduplicação, fixação, limite e busca."""

import os
import shutil
import stat
import tempfile
import time
import unittest
from pathlib import Path

from archclip.storage import Store, like_pattern, normalize_search

BACKSLASH = chr(92)
PNG_BYTES = b"\x89PNG\r\n\x1a\nconteudo-falso-de-imagem"


class StoreTestCase(unittest.TestCase):
    """Base com um banco novo por teste."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="archclip-store-")
        self.store = Store(Path(self.tmp) / "history.db")

    def tearDown(self):
        # clear() também apaga os blobs, que vivem num diretório compartilhado.
        self.store.clear(keep_pinned=False)
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ids(self, **kwargs):
        return [item.id for item in self.store.list(**kwargs)]


class TestAddAndDedupe(StoreTestCase):
    def test_guarda_texto(self):
        item = self.store.add_text("olá mundo")
        self.assertIsNotNone(item)
        self.assertEqual(item.kind, "text")
        self.assertEqual(item.text, "olá mundo")
        self.assertFalse(item.pinned)

    def test_preserva_acentuacao_e_unicode(self):
        original = "ação, coração, ÀÉÎÕÜ, ç, 日本語, emoji 🎉"
        item = self.store.add_text(original)
        # Releitura do banco, não o objeto em memória.
        self.assertEqual(self.store.get(item.id).text, original)

    def test_texto_vazio_ignorado(self):
        self.assertIsNone(self.store.add_text(""))
        self.assertIsNone(self.store.add_text("   \n\t "))
        self.assertEqual(self.store.count(), (0, 0))

    def test_duplicata_nao_cria_item_novo(self):
        primeiro = self.store.add_text("repetido")
        segundo = self.store.add_text("repetido")
        self.assertEqual(primeiro.id, segundo.id)
        self.assertEqual(self.store.count()[0], 1)

    def test_duplicata_volta_ao_topo(self):
        a = self.store.add_text("antigo")
        time.sleep(0.01)
        b = self.store.add_text("recente")
        self.assertEqual(self.ids(), [b.id, a.id])
        time.sleep(0.01)
        self.store.add_text("antigo")
        self.assertEqual(self.ids(), [a.id, b.id])

    def test_guarda_imagem_com_dimensoes(self):
        item = self.store.add_image(PNG_BYTES, "image/png", 800, 600)
        self.assertEqual(item.kind, "image")
        self.assertTrue(item.is_image)
        self.assertEqual((item.width, item.height), (800, 600))
        self.assertTrue(os.path.isfile(item.blob_path))
        self.assertEqual(Path(item.blob_path).read_bytes(), PNG_BYTES)

    def test_imagem_vazia_ignorada(self):
        self.assertIsNone(self.store.add_image(b"", "image/png"))


class TestOrdering(StoreTestCase):
    def test_mais_recente_primeiro(self):
        a = self.store.add_text("um")
        time.sleep(0.01)
        b = self.store.add_text("dois")
        time.sleep(0.01)
        c = self.store.add_text("tres")
        self.assertEqual(self.ids(), [c.id, b.id, a.id])

    def test_fixados_vao_para_o_topo(self):
        a = self.store.add_text("um")
        time.sleep(0.01)
        b = self.store.add_text("dois")
        time.sleep(0.01)
        c = self.store.add_text("tres")
        self.store.set_pinned(a.id, True)
        self.assertEqual(self.ids(), [a.id, c.id, b.id])

    def test_toggle_pin_alterna_e_retorna_estado(self):
        item = self.store.add_text("alvo")
        self.assertTrue(self.store.toggle_pin(item.id))
        self.assertTrue(self.store.get(item.id).pinned)
        self.assertFalse(self.store.toggle_pin(item.id))
        self.assertFalse(self.store.get(item.id).pinned)

    def test_toggle_pin_em_item_inexistente(self):
        self.assertFalse(self.store.toggle_pin(9999))

    def test_count_total_e_fixados(self):
        self.store.add_text("um")
        alvo = self.store.add_text("dois")
        self.store.set_pinned(alvo.id, True)
        self.assertEqual(self.store.count(), (2, 1))


class TestFilters(StoreTestCase):
    def setUp(self):
        super().setUp()
        self.texto = self.store.add_text("um texto qualquer")
        self.imagem = self.store.add_image(PNG_BYTES, "image/png", 10, 10)
        self.fixado = self.store.add_text("item fixado")
        self.store.set_pinned(self.fixado.id, True)

    def test_filtra_por_tipo(self):
        self.assertEqual(self.ids(kind="image"), [self.imagem.id])
        self.assertIn(self.texto.id, self.ids(kind="text"))
        self.assertNotIn(self.imagem.id, self.ids(kind="text"))

    def test_filtra_fixados(self):
        self.assertEqual(self.ids(pinned_only=True), [self.fixado.id])

    def test_limit_respeitado(self):
        self.assertEqual(len(self.store.list(limit=1)), 1)


class TestSearch(StoreTestCase):
    def test_encontra_no_inicio(self):
        item = self.store.add_text("cabecalho do documento")
        self.assertEqual(self.ids(query="cabecalho"), [item.id])

    def test_encontra_alem_do_corte_do_preview(self):
        # `preview` guarda só 400 caracteres; a busca precisa ver o conteúdo.
        item = self.store.add_text("inicio " + ("x" * 600) + " AGULHA")
        self.assertEqual(self.ids(query="AGULHA"), [item.id])

    def test_ignora_caixa(self):
        item = self.store.add_text("Relatorio Final")
        self.assertEqual(self.ids(query="relatorio"), [item.id])
        self.assertEqual(self.ids(query="RELATORIO"), [item.id])

    def test_ignora_acentuacao_nos_dois_sentidos(self):
        item = self.store.add_text("prestação de contas do coração")
        for termo in ("prestacao", "prestação", "PRESTACAO", "PRESTAÇÃO", "coracao"):
            with self.subTest(termo=termo):
                self.assertEqual(self.ids(query=termo), [item.id])

    def test_cedilha_e_til_dobram_a_caixa(self):
        item = self.store.add_text("informação")
        self.assertEqual(self.ids(query="INFORMAÇÃO"), [item.id])

    def test_porcento_e_literal(self):
        alvo = self.store.add_text("desconto de 100% hoje")
        self.store.add_text("nada a ver")
        self.assertEqual(self.ids(query="100%"), [alvo.id])

    def test_underscore_nao_vira_curinga(self):
        alvo = self.store.add_text("variavel a_b definida")
        self.store.add_text("variavel axb definida")
        self.assertEqual(self.ids(query="a_b"), [alvo.id])

    def test_busca_sem_resultado(self):
        self.store.add_text("alguma coisa")
        self.assertEqual(self.store.list(query="inexistente"), [])

    def test_query_em_branco_lista_tudo(self):
        self.store.add_text("um")
        self.store.add_text("dois")
        self.assertEqual(len(self.store.list(query="   ")), 2)

    def test_busca_encontra_imagem_pelo_preview(self):
        imagem = self.store.add_image(PNG_BYTES, "image/png", 4, 2)
        self.assertEqual(self.ids(query="imagem"), [imagem.id])


class TestTrim(StoreTestCase):
    def test_descarta_os_mais_antigos(self):
        for n in range(10):
            self.store.add_text("item {}".format(n))
            time.sleep(0.002)
        removidos = self.store.trim(3)
        self.assertEqual(removidos, 7)
        self.assertEqual(self.store.count()[0], 3)
        # Os que sobraram são os três mais recentes.
        self.assertEqual(
            [item.text for item in self.store.list()],
            ["item 9", "item 8", "item 7"],
        )

    def test_preserva_fixados_alem_do_limite(self):
        fixado = self.store.add_text("valioso")
        self.store.set_pinned(fixado.id, True)
        time.sleep(0.002)
        for n in range(10):
            self.store.add_text("descartavel {}".format(n))
            time.sleep(0.002)

        self.store.trim(2)
        total, pinned = self.store.count()
        self.assertEqual((total, pinned), (3, 1))
        self.assertIsNotNone(self.store.get(fixado.id))

    def test_trim_sem_excedente_nao_faz_nada(self):
        self.store.add_text("unico")
        self.assertEqual(self.store.trim(10), 0)

    def test_trim_com_limite_invalido_e_no_op(self):
        self.store.add_text("intocavel")
        self.assertEqual(self.store.trim(0), 0)
        self.assertEqual(self.store.trim(-5), 0)
        self.assertEqual(self.store.count()[0], 1)

    def test_trim_apaga_o_blob_da_imagem(self):
        imagem = self.store.add_image(PNG_BYTES, "image/png", 4, 4)
        blob = imagem.blob_path
        time.sleep(0.002)
        self.store.add_text("mais novo")
        self.store.trim(1)
        self.assertIsNone(self.store.get(imagem.id))
        self.assertFalse(os.path.isfile(blob))


class TestDeleteAndClear(StoreTestCase):
    def test_delete_remove_o_blob(self):
        imagem = self.store.add_image(PNG_BYTES, "image/png", 4, 4)
        blob = imagem.blob_path
        self.store.delete(imagem.id)
        self.assertIsNone(self.store.get(imagem.id))
        self.assertFalse(os.path.isfile(blob))

    def test_delete_de_item_inexistente_nao_explode(self):
        self.store.delete(9999)

    def test_clear_mantem_fixados(self):
        fixado = self.store.add_text("fica")
        self.store.set_pinned(fixado.id, True)
        self.store.add_text("some")
        removidos = self.store.clear(keep_pinned=True)
        self.assertEqual(removidos, 1)
        self.assertEqual(self.store.count(), (1, 1))

    def test_clear_total(self):
        fixado = self.store.add_text("nem esse escapa")
        self.store.set_pinned(fixado.id, True)
        self.store.add_text("outro")
        self.store.clear(keep_pinned=False)
        self.assertEqual(self.store.count(), (0, 0))


class TestHelpers(unittest.TestCase):
    def test_like_pattern_escapa_curingas(self):
        self.assertEqual(like_pattern("50%"), "%50" + BACKSLASH + "%%")
        self.assertEqual(like_pattern("a_b"), "%a" + BACKSLASH + "_b%")
        self.assertEqual(like_pattern(BACKSLASH), "%" + BACKSLASH + BACKSLASH + "%")

    def test_like_pattern_texto_simples(self):
        self.assertEqual(like_pattern("abc"), "%abc%")

    def test_normalize_search(self):
        self.assertEqual(normalize_search("Ação"), "acao")
        self.assertEqual(normalize_search("CORAÇÃO"), "coracao")
        self.assertEqual(normalize_search("Über"), "uber")
        self.assertEqual(normalize_search("já"), "ja")

    def test_normalize_search_com_vazios(self):
        # A coluna `text` é NULL para imagens: a função recebe None do SQLite.
        self.assertEqual(normalize_search(None), "")
        self.assertEqual(normalize_search(""), "")

    def test_normalize_search_preserva_nao_latinos(self):
        self.assertEqual(normalize_search("日本語"), "日本語")


@unittest.skipUnless(os.name == "posix", "permissões POSIX só valem no Linux")
class TestPermissions(StoreTestCase):
    def test_banco_restrito_ao_dono(self):
        db = Path(self.tmp) / "history.db"
        self.assertEqual(stat.S_IMODE(os.stat(db).st_mode), 0o600)

    def test_blob_restrito_ao_dono(self):
        imagem = self.store.add_image(PNG_BYTES, "image/png", 4, 4)
        self.assertEqual(stat.S_IMODE(os.stat(imagem.blob_path).st_mode), 0o600)

    def test_diretorio_de_dados_restrito(self):
        from archclip import util

        self.assertEqual(stat.S_IMODE(os.stat(util.DATA_DIR).st_mode), 0o700)


class TestItemDataclass(StoreTestCase):
    def test_is_image(self):
        texto = self.store.add_text("texto")
        imagem = self.store.add_image(PNG_BYTES, "image/png", 1, 1)
        self.assertFalse(texto.is_image)
        self.assertTrue(imagem.is_image)

    def test_get_inexistente_retorna_none(self):
        self.assertIsNone(self.store.get(4242))

    def test_schema_tem_indices(self):
        # Ordenação e filtro por tipo são as consultas quentes.
        rows = self.store.db.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
        nomes = {row["name"] for row in rows}
        self.assertIn("idx_items_order", nomes)
        self.assertIn("idx_items_kind", nomes)


if __name__ == "__main__":
    unittest.main()
