"""Atualizador: versões, origem confiável e extração segura de tarballs."""

import io
import shutil
import tarfile
import tempfile
import time
import unittest
from pathlib import Path

from archclip import updater
from archclip.config import Config
from archclip.updater import is_trusted_url, parse_version


class TestParseVersion(unittest.TestCase):
    def test_prefixo_v(self):
        self.assertEqual(parse_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(parse_version("V1.2.3"), (1, 2, 3))
        self.assertEqual(parse_version("1.2.3"), (1, 2, 3))

    def test_sufixos_descartados(self):
        self.assertEqual(parse_version("1.2.3-beta1"), (1, 2, 3))
        self.assertEqual(parse_version("1.2.3+build7"), (1, 2, 3))

    def test_partes_nao_numericas_viram_zero(self):
        self.assertEqual(parse_version("1.x.3"), (1, 0, 3))

    def test_vazio(self):
        self.assertEqual(parse_version(""), (0,))
        self.assertEqual(parse_version(None), (0,))

    def test_comparacoes(self):
        self.assertLess(parse_version("0.1.0"), parse_version("0.2.0"))
        self.assertLess(parse_version("0.9.0"), parse_version("0.10.0"))
        self.assertLess(parse_version("1.0.0"), parse_version("1.0.1"))
        self.assertEqual(parse_version("1.0.0"), parse_version("v1.0.0"))

    def test_numeros_de_dois_digitos_nao_sao_texto(self):
        # Comparação textual diria que "0.10.0" < "0.9.0"; a de tuplas não.
        self.assertGreater(parse_version("0.10.0"), parse_version("0.9.0"))


class TestTrustedUrl(unittest.TestCase):
    def test_hosts_do_github_aceitos(self):
        for url in (
            "https://api.github.com/repos/a/b/tarball/v1.0.0",
            "https://codeload.github.com/a/b/tar.gz/v1.0.0",
            "https://github.com/a/b/archive/v1.tar.gz",
            "https://objects.githubusercontent.com/x",
        ):
            with self.subTest(url=url):
                self.assertTrue(is_trusted_url(url))

    def test_host_desconhecido_recusado(self):
        self.assertFalse(is_trusted_url("https://evil.example.com/payload.tar.gz"))

    def test_http_puro_recusado(self):
        self.assertFalse(is_trusted_url("http://github.com/a/b.tar.gz"))

    def test_sufixo_forjado_recusado(self):
        # Um atacante registrando "github.com.evil.net" não deve passar.
        self.assertFalse(is_trusted_url("https://github.com.evil.net/x.tar.gz"))

    def test_prefixo_forjado_recusado(self):
        self.assertFalse(is_trusted_url("https://notgithub.com/x.tar.gz"))

    def test_userinfo_nao_engana(self):
        # "https://github.com@evil.net/" tem hostname evil.net.
        self.assertFalse(is_trusted_url("https://github.com@evil.net/x.tar.gz"))

    def test_entradas_degeneradas(self):
        for url in ("", "não é url", "file:///etc/passwd", "ftp://github.com/x"):
            with self.subTest(url=url):
                self.assertFalse(is_trusted_url(url))

    def test_download_recusa_url_nao_confiavel(self):
        with tempfile.TemporaryDirectory() as tmp:
            destino = Path(tmp) / "saida.tar.gz"
            erro = updater._download("https://evil.example.com/x.tar.gz", destino, 5)
            self.assertIn("recusada", erro)
            self.assertFalse(destino.exists())


class TestExtract(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="archclip-extract-"))
        self.destino = self.tmp / "destino"
        self.destino.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make_tar(self, membros):
        """membros: [(nome, conteudo_bytes)] -> caminho do tar.gz."""
        archive = self.tmp / "pacote.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            for nome, conteudo in membros:
                info = tarfile.TarInfo(nome)
                info.size = len(conteudo)
                info.mtime = int(time.time())
                tar.addfile(info, io.BytesIO(conteudo))
        return archive

    def test_extrai_tarball_normal(self):
        archive = self.make_tar([("projeto/archclip/__init__.py", b"x = 1")])
        self.assertEqual(updater._extract(archive, self.destino), "")
        self.assertTrue((self.destino / "projeto" / "archclip" / "__init__.py").is_file())

    def test_recusa_escapar_do_diretorio(self):
        # O clássico path traversal: um membro chamado "../".
        archive = self.make_tar([("../invadido.txt", b"pwned")])
        erro = updater._extract(archive, self.destino)
        self.assertNotEqual(erro, "", "extração deveria ter falhado")
        self.assertFalse((self.tmp / "invadido.txt").exists())

    def test_recusa_caminho_absoluto(self):
        archive = self.make_tar([("/tmp/archclip-invadido.txt", b"pwned")])
        updater._extract(archive, self.destino)
        self.assertFalse(Path("/tmp/archclip-invadido.txt").exists())

    def test_arquivo_corrompido_retorna_erro(self):
        ruim = self.tmp / "ruim.tar.gz"
        ruim.write_bytes(b"isso nao e um tarball")
        self.assertNotEqual(updater._extract(ruim, self.destino), "")

    def test_arquivo_inexistente_retorna_erro(self):
        self.assertNotEqual(updater._extract(self.tmp / "sumiu.tar.gz", self.destino), "")


class TestFindPackageRoot(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="archclip-root-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make_package(self, base):
        (base / "archclip").mkdir(parents=True)
        (base / "archclip" / "__init__.py").write_text("", encoding="utf-8")

    def test_pacote_na_raiz(self):
        self.make_package(self.tmp)
        self.assertEqual(updater._find_package_root(self.tmp), self.tmp)

    def test_pacote_dentro_do_diretorio_do_github(self):
        # Tarballs do GitHub vêm com um nível extra: Owner-Repo-abc1234/
        interno = self.tmp / "Theuszma-ArchLinux-Clipboard-a1b2c3d"
        interno.mkdir()
        self.make_package(interno)
        self.assertEqual(updater._find_package_root(self.tmp), interno)

    def test_sem_pacote_retorna_none(self):
        (self.tmp / "outra-coisa").mkdir()
        self.assertIsNone(updater._find_package_root(self.tmp))


class TestShouldCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="archclip-check-"))
        self.config = Config(self.tmp / "config.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_desligado_nunca_checa(self):
        self.config.set("update_check", False)
        self.assertFalse(updater.should_check(self.config))

    def test_checa_na_primeira_vez(self):
        self.assertTrue(updater.should_check(self.config))

    def test_nao_repete_dentro_do_intervalo(self):
        self.config.set("update_last_check", time.time())
        self.assertFalse(updater.should_check(self.config))

    def test_checa_de_novo_apos_o_intervalo(self):
        self.config.set("update_last_check", time.time() - updater.CHECK_INTERVAL - 1)
        self.assertTrue(updater.should_check(self.config))


class TestInstallKind(unittest.TestCase):
    def test_kind_conhecido(self):
        self.assertIn(updater.install_kind(), ("local", "package", "source"))

    def test_motivo_coerente_com_o_kind(self):
        kind = updater.install_kind()
        motivo = updater.why_not_self_install()
        if kind == "local":
            self.assertEqual(motivo, "")
            self.assertTrue(updater.can_self_install())
        else:
            self.assertNotEqual(motivo, "")
            self.assertFalse(updater.can_self_install())

    def test_install_recusa_quando_nao_pode(self):
        if updater.can_self_install():
            self.skipTest("instalação local: este caminho não se aplica")
        release = updater.Release(
            version=(9, 9, 9), tag="v9.9.9", notes="", tarball_url="", html_url=""
        )
        ok, mensagem = updater.install(release)
        self.assertFalse(ok)
        self.assertNotEqual(mensagem, "")


class TestRefreshShellExtension(unittest.TestCase):
    def setUp(self):
        self.workdir = Path(tempfile.mkdtemp(prefix="archclip-ext-"))
        self.addCleanup(shutil.rmtree, self.workdir, ignore_errors=True)

        self.version_dir = self.workdir / "versao"
        (self.version_dir / "extension").mkdir(parents=True)
        (self.version_dir / "extension" / "extension.js").write_text("// nova", encoding="utf-8")
        (self.version_dir / "extension" / "metadata.json").write_text("{}", encoding="utf-8")

        self.instalada = updater.SHELL_EXTENSION_DIR
        shutil.rmtree(self.instalada, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.instalada, ignore_errors=True)

    def test_atualiza_quem_ja_tem_a_extensao(self):
        self.instalada.mkdir(parents=True)
        (self.instalada / "extension.js").write_text("// antiga", encoding="utf-8")

        self.assertTrue(updater._refresh_shell_extension(self.version_dir))
        self.assertEqual((self.instalada / "extension.js").read_text(encoding="utf-8"), "// nova")
        self.assertTrue((self.instalada / "metadata.json").exists())

    def test_nao_instala_para_quem_nao_tem(self):
        # Instalar a extensão sozinho, para quem nunca a quis, não é trabalho
        # de uma atualização automática.
        self.assertFalse(updater._refresh_shell_extension(self.version_dir))
        self.assertFalse(self.instalada.exists())

    def test_release_sem_extensao_nao_quebra(self):
        self.instalada.mkdir(parents=True)
        shutil.rmtree(self.version_dir / "extension")
        self.assertFalse(updater._refresh_shell_extension(self.version_dir))


class TestRelease(unittest.TestCase):
    def test_label(self):
        release = updater.Release(
            version=(1, 4, 2), tag="v1.4.2", notes="", tarball_url="", html_url=""
        )
        self.assertEqual(release.label, "1.4.2")


if __name__ == "__main__":
    unittest.main()
