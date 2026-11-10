"""Projecao Web Mercator (Slippy Map) e geometria do viewport.

Modulo **puro** (sem Tk, sem rede). Todas as funcoes falam em ``(lon, lat)``
quando o nome diz ``lonlat`` — o oposto de ``geo``, que usa
``(lat, lon)``. A conversao fica explicita na fronteira (``map_canvas``).

Convencoes:

* ``world`` = coordenadas normalizadas em ``[0, 1]`` (x = oeste->leste,
  y = norte->sul);
* ``pixel`` = pixels na resolucao do zoom ``z`` (mundo = ``256 * 2**z`` px);
* ``tile`` = indice inteiro em uma grade ``2**z x 2**z``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

TILE_SIZE = 256
MIN_ZOOM = 2
MAX_ZOOM = 19

#: Latitude limite do Web Mercator (os polos nao sao representaveis).
MAX_LATITUDE = 85.05112878


def clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


def world_size(zoom: int) -> float:
    """Largura/altura do mundo em pixels no zoom dado."""
    return float(TILE_SIZE) * (2.0**zoom)


def lonlat_to_world(lon: float, lat: float) -> tuple[float, float]:
    """Converte ``(lon, lat)`` em coordenadas normalizadas ``(x, y)``."""
    x = (lon + 180.0) / 360.0
    clamped = clamp(lat, -MAX_LATITUDE, MAX_LATITUDE)
    sin_lat = math.sin(math.radians(clamped))
    y = 0.5 - math.log((1.0 + sin_lat) / (1.0 - sin_lat)) / (4.0 * math.pi)
    return x, y


def world_to_lonlat(x: float, y: float) -> tuple[float, float]:
    """Inversa de :func:`lonlat_to_world`."""
    lon = x * 360.0 - 180.0
    n = math.pi * (1.0 - 2.0 * y)
    lat = math.degrees(math.atan(math.sinh(n)))
    return lon, lat


def lonlat_to_pixel(lon: float, lat: float, zoom: int) -> tuple[float, float]:
    """Coordenada de pixel no mundo no zoom dado."""
    x, y = lonlat_to_world(lon, lat)
    scale = world_size(zoom)
    return x * scale, y * scale


def pixel_to_lonlat(px: float, py: float, zoom: int) -> tuple[float, float]:
    scale = world_size(zoom)
    return world_to_lonlat(px / scale, py / scale)


def pixel_to_tile(px: float, py: float) -> tuple[int, int]:
    """Indice da tile que contem o pixel."""
    return int(math.floor(px / TILE_SIZE)), int(math.floor(py / TILE_SIZE))


def lonlat_to_tile(lon: float, lat: float, zoom: int) -> tuple[int, int]:
    px, py = lonlat_to_pixel(lon, lat, zoom)
    return pixel_to_tile(px, py)


@dataclass
class WebMercatorView:
    """Estado de um viewport: centro geografico, zoom e tamanho em pixels."""

    center_lat: float = 0.0
    center_lon: float = 0.0
    zoom: int = 13
    width: int = 800
    height: int = 600
    min_zoom: int = MIN_ZOOM
    max_zoom: int = MAX_ZOOM

    # ------------------------------------------------------------------ base
    def world_size(self) -> float:
        return world_size(self.zoom)

    def center_pixel(self) -> tuple[float, float]:
        return lonlat_to_pixel(self.center_lon, self.center_lat, self.zoom)

    def origin_pixel(self) -> tuple[float, float]:
        """Pixel do canto superior esquerdo do canvas (mundo)."""
        cx, cy = self.center_pixel()
        return cx - self.width / 2.0, cy - self.height / 2.0

    # ------------------------------------------------------- conversoes
    def canvas_to_lonlat(self, canvas_x: float, canvas_y: float) -> tuple[float, float]:
        ox, oy = self.origin_pixel()
        return pixel_to_lonlat(ox + canvas_x, oy + canvas_y, self.zoom)

    def canvas_to_latlon(self, canvas_x: float, canvas_y: float) -> tuple[float, float]:
        lon, lat = self.canvas_to_lonlat(canvas_x, canvas_y)
        return lat, lon

    def lonlat_to_canvas(self, lon: float, lat: float) -> tuple[float, float]:
        ox, oy = self.origin_pixel()
        px, py = lonlat_to_pixel(lon, lat, self.zoom)
        return px - ox, py - oy

    def latlon_to_canvas(self, lat: float, lon: float) -> tuple[float, float]:
        return self.lonlat_to_canvas(lon, lat)

    # ------------------------------------------------ tiles do viewport
    def tile_range(self) -> tuple[range, range]:
        """Intervalo de tiles (x, y) que cobrem o canvas, recortado ao mundo."""
        count = 2**self.zoom
        ox, oy = self.origin_pixel()
        x0 = int(math.floor(ox / TILE_SIZE))
        y0 = int(math.floor(oy / TILE_SIZE))
        x1 = int(math.floor((ox + self.width) / TILE_SIZE))
        y1 = int(math.floor((oy + self.height) / TILE_SIZE))
        x0 = max(0, min(count - 1, x0))
        x1 = max(0, min(count - 1, x1))
        y0 = max(0, min(count - 1, y0))
        y1 = max(0, min(count - 1, y1))
        return range(x0, x1 + 1), range(y0, y1 + 1)

    def tile_canvas_origin(self, tile_x: int, tile_y: int) -> tuple[float, float]:
        ox, oy = self.origin_pixel()
        return tile_x * TILE_SIZE - ox, tile_y * TILE_SIZE - oy

    # --------------------------------------------------- navegacao
    def pan_by_pixels(self, dx: float, dy: float) -> None:
        """Move o centro para que o conteudo ande ``(dx, dy)`` no canvas."""
        cx, cy = self.center_pixel()
        lon, lat = pixel_to_lonlat(cx - dx, cy - dy, self.zoom)
        self._set_center(lon, lat)

    def set_center(self, lon: float, lat: float) -> None:
        self._set_center(lon, lat)

    def zoom_at(self, new_zoom: int, canvas_x: float, canvas_y: float) -> None:
        """Muda o zoom mantendo fixo o ponto geografico sob ``(canvas_x, canvas_y)``."""
        new_zoom = int(clamp(new_zoom, self.min_zoom, self.max_zoom))
        if new_zoom == self.zoom:
            return
        lon, lat = self.canvas_to_lonlat(canvas_x, canvas_y)
        self.zoom = new_zoom
        px, py = lonlat_to_pixel(lon, lat, self.zoom)
        center_px = px + (self.width / 2.0 - canvas_x)
        center_py = py + (self.height / 2.0 - canvas_y)
        center_lon, center_lat = pixel_to_lonlat(center_px, center_py, self.zoom)
        self._set_center(center_lon, center_lat)

    def zoom_by(self, delta: int, canvas_x: float, canvas_y: float) -> None:
        self.zoom_at(self.zoom + delta, canvas_x, canvas_y)

    def fit_bounds(
        self,
        south: float,
        west: float,
        north: float,
        east: float,
        padding_px: float = 32.0,
    ) -> None:
        """Enquadra uma bbox; escolhe o maior zoom em que ela cabe."""
        center_lon = (west + east) / 2.0
        center_lat = (south + north) / 2.0
        usable_w = max(16.0, self.width - 2.0 * padding_px)
        usable_h = max(16.0, self.height - 2.0 * padding_px)

        best = self.min_zoom
        for zoom in range(self.min_zoom, self.max_zoom + 1):
            x0, y0 = lonlat_to_pixel(west, north, zoom)
            x1, y1 = lonlat_to_pixel(east, south, zoom)
            if (x1 - x0) <= usable_w and (y1 - y0) <= usable_h:
                best = zoom
            else:
                break
        self.zoom = best
        self._set_center(center_lon, center_lat)

    # ------------------------------------------------------------- interno
    def _set_center(self, lon: float, lat: float) -> None:
        self.center_lon = float(clamp(lon, -180.0, 180.0))
        self.center_lat = float(clamp(lat, -MAX_LATITUDE, MAX_LATITUDE))
        # Impede rolar alem das bordas verticais do mundo.
        size = self.world_size()
        cx, cy = self.center_pixel()
        half_h = self.height / 2.0
        cy = clamp(cy, half_h, size - half_h) if size > self.height else size / 2.0
        if abs(cy - self.center_pixel()[1]) > 1e-9:
            _, lat2 = pixel_to_lonlat(cx, cy, self.zoom)
            self.center_lat = float(clamp(lat2, -MAX_LATITUDE, MAX_LATITUDE))
