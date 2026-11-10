"""GUI simples para rotear e testar a engine.

Pacote separado do pacote da engine (modulos em ``src/``): nao e empacotado nem
descoberto pelos testes do projeto. Exporta apenas utilitarios puros
(projecao Web Mercator e decodificacao Terrarium), que podem ser testados sem
Tk nem rede.
"""

from __future__ import annotations

__version__ = "0.1.0"
