"""Altimetria keyless via tiles Terrarium + decodificacao PNG em stdlib.

O tile Terrarium e um PNG 8 bits cuja cor codifica a altitude::

    elevacao_m = (R * 256 + G + B / 256) - 32768

Nao ha API JSON nem chave: basta baixar o tile e ler o pixel. Como nao temos
PIL/numpy, o PNG e decodificado aqui com ``zlib`` (IHDR/IDAT + inflate +
"unfilter" das 5 estrategias de filtro). So suportamos o subconjunto que os
tiles usam: 8 bits por canal, sem entrelacamento.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from typing import Callable, Sequence

from geo import Coord

from .proj import TILE_SIZE, lonlat_to_pixel, pixel_to_tile
from .tiles import TERRARIUM_LAYER, TileCache

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
COLOR_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


class PngError(ValueError):
    """PNG fora do subconjunto suportado ou corrompido."""


@dataclass(frozen=True)
class PngImage:
    """Imagem decodificada: pixels RGB(A) em ordem row-major."""

    width: int
    height: int
    channels: int
    pixels: bytes

    def pixel(self, x: int, y: int) -> tuple[int, ...]:
        index = (y * self.width + x) * self.channels
        return tuple(self.pixels[index : index + self.channels])


# --------------------------------------------------------------------------
# Decodificacao PNG
# --------------------------------------------------------------------------
def _iter_chunks(data: bytes):
    if data[:8] != PNG_SIGNATURE:
        raise PngError("assinatura PNG invalida")
    pos = 8
    end = len(data)
    while pos + 12 <= end:
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        chunk_type = data[pos + 4 : pos + 8]
        start = pos + 8
        stop = start + length
        if stop + 4 > end:
            raise PngError("chunk PNG truncado")
        yield chunk_type, data[start:stop]
        pos = stop + 4
        if chunk_type == b"IEND":
            break


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _unfilter_row(filter_type: int, line: bytearray, prev: bytes, bpp: int) -> None:
    size = len(line)
    if filter_type == 0:
        return
    if filter_type == 1:
        for i in range(bpp, size):
            line[i] = (line[i] + line[i - bpp]) & 0xFF
    elif filter_type == 2:
        for i in range(size):
            line[i] = (line[i] + prev[i]) & 0xFF
    elif filter_type == 3:
        for i in range(size):
            left = line[i - bpp] if i >= bpp else 0
            line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
    elif filter_type == 4:
        for i in range(size):
            left = line[i - bpp] if i >= bpp else 0
            up = prev[i]
            up_left = prev[i - bpp] if i >= bpp else 0
            line[i] = (line[i] + _paeth(left, up, up_left)) & 0xFF
    else:
        raise PngError(f"filtro PNG desconhecido: {filter_type}")


def decode_png(data: bytes) -> PngImage:
    """Decodifica um PNG 8 bits nao entrelacado."""
    width = height = 0
    bit_depth = color_type = interlace = 0
    idat = bytearray()

    for chunk_type, chunk in _iter_chunks(data):
        if chunk_type == b"IHDR":
            (
                width,
                height,
                bit_depth,
                color_type,
                _compression,
                _filter,
                interlace,
            ) = struct.unpack(">IIBBBBB", chunk[:13])
        elif chunk_type == b"IDAT":
            idat.extend(chunk)
        elif chunk_type == b"IEND":
            break

    if width <= 0 or height <= 0:
        raise PngError("PNG sem IHDR valido")
    if bit_depth != 8:
        raise PngError(f"apenas PNG 8 bits suportado (recebido {bit_depth})")
    if interlace != 0:
        raise PngError("PNG entrelacado nao suportado")
    if color_type not in COLOR_CHANNELS:
        raise PngError(f"tipo de cor PNG nao suportado: {color_type}")

    channels = COLOR_CHANNELS[color_type]
    stride = width * channels
    raw = zlib.decompress(bytes(idat))
    if len(raw) < (stride + 1) * height:
        raise PngError("dados IDAT insuficientes")

    out = bytearray(stride * height)
    prev = bytes(stride)
    pos = 0
    for row in range(height):
        filter_type = raw[pos]
        pos += 1
        line = bytearray(raw[pos : pos + stride])
        pos += stride
        _unfilter_row(filter_type, line, prev, channels)
        out[row * stride : (row + 1) * stride] = line
        prev = bytes(line)

    return PngImage(width=width, height=height, channels=channels, pixels=bytes(out))


# --------------------------------------------------------------------------
# Terrarium
# --------------------------------------------------------------------------
def terrarium_elevation(red: int, green: int, blue: int) -> float:
    """Altura em metros codificada no pixel Terrarium."""
    return (red * 256.0 + green + blue / 256.0) - 32768.0


def encode_terrarium(red: int, green: int, blue: int) -> float:
    """Alias explicito para leitura do codigo (mesma conta)."""
    return terrarium_elevation(red, green, blue)


def terrarium_zoom_for_resolution(
    resolution_m: float, latitude: float
) -> int:
    """Zoom cuja resolucao no solo mais se aproxima de ``resolution_m``."""
    import math

    cos_lat = max(0.1, math.cos(math.radians(latitude)))
    for zoom in range(0, 16):
        ground = 156543.03392 * cos_lat / (2.0**zoom)
        if ground <= resolution_m:
            return zoom
    return 15


Fetcher = Callable[[int, int, int], "bytes | None"]


class TerrariumElevation:
    """``ElevationProvider`` que le altitude dos tiles Terrarium.

    ``fetch`` recebe ``(z, x, y)`` e devolve os bytes do PNG (ou ``None``).
    Cada tile e decodificado no maximo uma vez (cache em memoria).
    """

    name = "terrarium"

    def __init__(
        self,
        fetch: Fetcher,
        *,
        zoom: int = 12,
        resolution_m: float | None = 30.0,
    ) -> None:
        self._fetch = fetch
        self.zoom = int(zoom)
        self.resolution_m = resolution_m
        self._tiles: dict[tuple[int, int], PngImage | None] = {}

    @classmethod
    def from_cache(cls, cache: TileCache, *, zoom: int = 12) -> "TerrariumElevation":
        def fetch(z: int, x: int, y: int) -> bytes | None:
            return cache.get(z, x, y)

        return cls(fetch, zoom=zoom)

    def _tile(self, x: int, y: int) -> PngImage | None:
        key = (x, y)
        if key not in self._tiles:
            data = self._fetch(self.zoom, x, y)
            image: PngImage | None
            try:
                image = decode_png(data) if data else None
            except (PngError, zlib.error):
                image = None
            self._tiles[key] = image
        return self._tiles[key]

    def elevations(self, coords: Sequence[Coord]) -> list[float | None]:
        """Altitudes na ordem das coordenadas ``(lat, lon)``."""
        result: list[float | None] = []
        for lat, lon in coords:
            px, py = lonlat_to_pixel(lon, lat, self.zoom)
            tile_x, tile_y = pixel_to_tile(px, py)
            image = self._tile(tile_x, tile_y)
            if image is None:
                result.append(None)
                continue
            local_x = int(px) - tile_x * TILE_SIZE
            local_y = int(py) - tile_y * TILE_SIZE
            local_x = min(max(local_x, 0), image.width - 1)
            local_y = min(max(local_y, 0), image.height - 1)
            pixel = image.pixel(local_x, local_y)
            if image.channels < 3:
                # Escala de cinza: usa o mesmo canal nos tres.
                result.append(terrarium_elevation(pixel[0], pixel[0], pixel[0]))
            else:
                result.append(terrarium_elevation(pixel[0], pixel[1], pixel[2]))
        return result
