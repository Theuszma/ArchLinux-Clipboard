"""Configuração: padrões, persistência atômica, resiliência e observadores."""

import json
import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path

from archclip.config import DEFAULTS, Config


class ConfigTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="archclip-config-")
        self.path = Path(self.tmp) / "config.json"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def load(self):
        return Config(self.path)


class TestDefaults(ConfigTestCase):
    def test_padroes_sem_arquivo(self):
        config = self.load()
        self.assertEqual(config.get("max_items"), 25)
        self.assertTrue(config.get("capture_text"))
        self.assertTrue(config.get("capture_images"))
        self.assertEqual(config.get("hotkey"), "<Super>v")

    def test_auto_install_vem_desligado(self):
        # Releases não são assinadas: instalar sozinho é opt-in consciente.
        self.assertFalse(DEFAULTS["update_auto_install"])
        self.assertFalse(self.load().get("update_auto_install"))

    def test_procurar_atualizacoes_vem_ligado(self):
        self.assertTrue(self.load().get("update_check"))

    def test_getitem_equivale_a_get(self):
        config = self.load()
        self.assertEqual(config["max_items"], config.get("max_items"))

    def test_chave_desconhecida_retorna_default_informado(self):
        self.assertEqual(self.load().get("nao_existe", "fallback"), "fallback")


class TestPersistence(ConfigTestCase):
    def test_roundtrip(self):
        config = self.load()
        config.set("max_items", 99)
        config.set("hotkey", "<Control><Alt>v")
        recarregado = self.load()
        self.assertEqual(recarregado.get("max_items"), 99)
        self.assertEqual(recarregado.get("hotkey"), "<Control><Alt>v")

    def test_grava_json_legivel_com_acentos(self):
        config = self.load()
        config.set("hotkey", "<Super>ç")
        conteudo = self.path.read_text(encoding="utf-8")
        self.assertIn("<Super>ç", conteudo)  # ensure_ascii=False
        self.assertEqual(json.loads(conteudo)["hotkey"], "<Super>ç")

    def test_nao_deixa_arquivo_temporario_para_tras(self):
        config = self.load()
        config.set("max_items", 30)
        restos = [p for p in Path(self.tmp).iterdir() if p.name != "config.json"]
        self.assertEqual(restos, [])

    def test_set_sem_save_nao_toca_o_disco(self):
        config = self.load()
        config.set("max_items", 77, save=False)
        self.assertEqual(config.get("max_items"), 77)
        self.assertFalse(self.path.exists())

    def test_dicionarios_sobrevivem_ao_roundtrip(self):
        config = self.load()
        overrides = {"org.gnome.shell.keybindings:toggle-message-tray": ["<Super>v", "<Super>m"]}
        config.set("overridden_bindings", overrides)
        self.assertEqual(self.load().get("overridden_bindings"), overrides)


class TestResilience(ConfigTestCase):
    def test_json_corrompido_cai_no_padrao(self):
        self.path.write_text("{ isso nao e json", encoding="utf-8")
        self.assertEqual(self.load().get("max_items"), DEFAULTS["max_items"])

    def test_json_valido_mas_nao_dicionario(self):
        self.path.write_text("[1, 2, 3]", encoding="utf-8")
        self.assertEqual(self.load().get("max_items"), DEFAULTS["max_items"])

    def test_chave_desconhecida_e_descartada(self):
        self.path.write_text(
            json.dumps({"max_items": 7, "coisa_estranha": True}), encoding="utf-8"
        )
        config = self.load()
        self.assertEqual(config.get("max_items"), 7)
        # Uma config antiga não pode injetar chaves que o app não conhece.
        config.set("capture_text", False)
        self.assertNotIn("coisa_estranha", json.loads(self.path.read_text(encoding="utf-8")))

    def test_config_parcial_completa_com_padroes(self):
        self.path.write_text(json.dumps({"max_items": 5}), encoding="utf-8")
        config = self.load()
        self.assertEqual(config.get("max_items"), 5)
        self.assertEqual(config.get("hotkey"), DEFAULTS["hotkey"])


class TestObservers(ConfigTestCase):
    def test_observador_recebe_mudanca(self):
        config = self.load()
        vistos = []
        config.connect(lambda k, v: vistos.append((k, v)))
        config.set("max_items", 42)
        self.assertEqual(vistos, [("max_items", 42)])

    def test_set_com_valor_igual_nao_notifica(self):
        config = self.load()
        vistos = []
        config.connect(lambda k, v: vistos.append(k))
        config.set("max_items", 42)
        config.set("max_items", 42)
        self.assertEqual(len(vistos), 1)

    def test_varios_observadores(self):
        config = self.load()
        a, b = [], []
        config.connect(lambda k, v: a.append(k))
        config.connect(lambda k, v: b.append(k))
        config.set("capture_text", False)
        self.assertEqual(a, ["capture_text"])
        self.assertEqual(b, ["capture_text"])


@unittest.skipUnless(os.name == "posix", "permissões POSIX só valem no Linux")
class TestPermissions(ConfigTestCase):
    def test_config_restrita_ao_dono(self):
        self.load().set("max_items", 12)
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
