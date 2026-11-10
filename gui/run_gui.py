"""Ponto de entrada da GUI.

Uso::

    python gui/run_gui.py [caminho/para/grafo.json]

Se os modulos da engine nao estiverem instalados, adiciona ``src/`` ao
``sys.path`` automaticamente, de modo que a GUI funcione a partir do repositorio.
"""

from __future__ import annotations

import sys
from pathlib import Path

GUI_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = GUI_ROOT.parent
SRC = PROJECT_ROOT / "src"

if str(GUI_ROOT) not in sys.path:
    sys.path.insert(0, str(GUI_ROOT))
if SRC.is_dir() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _default_graph() -> str | None:
    candidate = PROJECT_ROOT / "data" / "se.json"
    return str(candidate) if candidate.is_file() else None


def main() -> int:
    try:
        from routegui.app import main as gui_main
    except ImportError as exc:  # pragma: no cover - depende do ambiente
        print(f"falha ao importar a GUI: {exc}", file=sys.stderr)
        print("requer tkinter (stdlib) e os modulos da engine em src/.", file=sys.stderr)
        return 2

    argv = sys.argv[1:]
    if not argv:
        default = _default_graph()
        if default:
            argv = [default]
    return gui_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
