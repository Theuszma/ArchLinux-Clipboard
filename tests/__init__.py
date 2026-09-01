"""Suíte de testes do ArchClip.

`archclip.util` resolve os caminhos XDG no momento do import, então
apontamos as variáveis para um sandbox descartável ANTES que qualquer
módulo do pacote seja importado. Este `__init__` é carregado primeiro
tanto pelo `unittest discover` quanto por `python -m unittest tests.x`.
"""

import atexit
import os
import shutil
import tempfile

SANDBOX = tempfile.mkdtemp(prefix="archclip-tests-")

os.environ["XDG_CONFIG_HOME"] = os.path.join(SANDBOX, "config")
os.environ["XDG_DATA_HOME"] = os.path.join(SANDBOX, "data")
os.environ["XDG_CACHE_HOME"] = os.path.join(SANDBOX, "cache")

atexit.register(shutil.rmtree, SANDBOX, ignore_errors=True)
