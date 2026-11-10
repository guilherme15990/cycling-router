"""Camadas de tiles e cache em disco (keyless, sem dependencias externas).

Usamos apenas ``urllib`` (stdlib). Cada camada e um template de URL. O cache
grava os bytes crus em ``<root>/<layer>/<z>/<x>/<y>.<ext>``; tiles ausentes e
falhas de rede viram ``None`` (o chamador decide o que fazer).

Camadas usadas pela GUI:

* OpenStreetMap raster — fundo do mapa;
* Terrarium (Mapzen/AWS) — elevacao embutida nos canais RGB do PNG.
"""

from __future__ import annotations

import os
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

#: OpenStreetMap exige User-Agent identificavel e uso moderado.
DEFAULT_USER_AGENT = "roteamento-gui/0.1 (engine de teste; contato@example.invalid)"


@dataclass(frozen=True)
class TileLayer:
    """Descricao de uma camada de tiles XYZ."""

    name: str
    url_template: str
    extension: str = "png"
    min_zoom: int = 0
    max_zoom: int = 19
    user_agent: str = DEFAULT_USER_AGENT
    attribution: str = ""
    subdomains: tuple[str, ...] = ()

    def url(self, z: int, x: int, y: int) -> str:
        subdomain = self.subdomains[(x + y) % len(self.subdomains)] if self.subdomains else ""
        return self.url_template.format(z=z, x=x, y=y, s=subdomain)

    def supports(self, z: int) -> bool:
        return self.min_zoom <= z <= self.max_zoom


OSM_LAYER = TileLayer(
    name="osm",
    url_template="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    extension="png",
    max_zoom=19,
    attribution="(c) OpenStreetMap contributors",
)

TERRARIUM_LAYER = TileLayer(
    name="terrarium",
    url_template="https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png",
    extension="png",
    min_zoom=0,
    max_zoom=15,
    attribution="Terrarium (Mapzen/AWS) - elevation",
)


class TileCache:
    """Le/grava tiles em disco; busca na rede apenas quando faltam."""

    def __init__(
        self,
        root: str | Path,
        layer: TileLayer,
        *,
        timeout_s: float = 12.0,
    ) -> None:
        self.root = Path(root)
        self.layer = layer
        self.timeout_s = float(timeout_s)
        self._missing: set[tuple[int, int, int]] = set()

    # ------------------------------------------------------------- caminho
    def path(self, z: int, x: int, y: int) -> Path:
        return self.root / self.layer.name / str(z) / str(x) / f"{y}.{self.layer.extension}"

    # --------------------------------------------------------------- leitura
    def cached(self, z: int, x: int, y: int) -> bytes | None:
        """Bytes do tile em disco, se existir."""
        path = self.path(z, x, y)
        try:
            data = path.read_bytes()
        except OSError:
            return None
        return data or None

    def get(
        self, z: int, x: int, y: int, *, allow_download: bool = True
    ) -> bytes | None:
        """Bytes do tile (cache primeiro, depois rede). ``None`` em falha."""
        if not self.layer.supports(z):
            return None
        data = self.cached(z, x, y)
        if data is not None:
            return data
        key = (z, x, y)
        if not allow_download or key in self._missing:
            return None
        data = self._download(z, x, y)
        if data is None:
            self._missing.add(key)
            return None
        self._store(z, x, y, data)
        return data

    def prefetch(self, z: int, x: int, y: int) -> bytes | None:
        return self.get(z, x, y, allow_download=True)

    # --------------------------------------------------------------- interno
    def _download(self, z: int, x: int, y: int) -> bytes | None:
        url = self.layer.url(z, x, y)
        request = urllib.request.Request(
            url, headers={"User-Agent": self.layer.user_agent}
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                if getattr(response, "status", 200) != 200:
                    return None
                return response.read()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
            return None

    def _store(self, z: int, x: int, y: int, data: bytes) -> None:
        path = self.path(z, x, y)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Escrita atomica: escreve num temporario e substitui.
        handle, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(handle, "wb") as tmp:
                tmp.write(data)
            os.replace(tmp_name, path)
        except OSError:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def default_cache_root() -> Path:
    """Pasta de cache ao lado da GUI (facil de inspecionar/apagar)."""
    return Path(__file__).resolve().parent.parent / ".tilecache"
