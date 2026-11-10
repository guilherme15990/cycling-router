"""Configuracao de testes da GUI.

Adiciona ``gui/`` ao ``sys.path`` para importar ``routegui`` sem instalar o
pacote. Rode com::

    python -m pytest gui/tests
"""

from __future__ import annotations

import sys
from pathlib import Path

GUI_ROOT = Path(__file__).resolve().parent.parent
if str(GUI_ROOT) not in sys.path:
    sys.path.insert(0, str(GUI_ROOT))

SRC = GUI_ROOT.parent / "src"
if SRC.is_dir() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
