"""Testes do decodificador PNG e do provedor Terrarium (sem rede)."""

from __future__ import annotations

import struct
import zlib

import pytest

from routegui import terrain
from routegui.terrain import PNG_SIGNATURE, PngError, TerrariumElevation, decode_png


# --------------------------------------------------------------------------
# Codificador PNG minimo para os testes
# --------------------------------------------------------------------------
def _chunk(chunk_type: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _filter_row(filter_type: int, row: bytes, prev: bytes, bpp: int) -> bytes:
    size = len(row)
    out = bytearray(size)
    for i in range(size):
        left = row[i - bpp] if i >= bpp else 0
        up = prev[i]
        up_left = prev[i - bpp] if i >= bpp else 0
        if filter_type == 0:
            value = row[i]
        elif filter_type == 1:
            value = row[i] - left
        elif filter_type == 2:
            value = row[i] - up
        elif filter_type == 3:
            value = row[i] - ((left + up) >> 1)
        elif filter_type == 4:
            value = row[i] - _paeth(left, up, up_left)
        else:
            raise ValueError(filter_type)
        out[i] = value & 0xFF
    return bytes(out)


def encode_png(
    width: int,
    height: int,
    pixels: bytes,
    *,
    color_type: int = 2,
    row_filters: list[int] | None = None,
) -> bytes:
    channels = {0: 1, 2: 3, 4: 2, 6: 4}[color_type]
    stride = width * channels
    filters = row_filters or [0] * height
    assert len(filters) == height

    raw = bytearray()
    prev = bytes(stride)
    for y in range(height):
        row = pixels[y * stride : (y + 1) * stride]
        ftype = filters[y]
        raw.append(ftype)
        raw.extend(_filter_row(ftype, row, prev, channels))
        prev = row

    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    return (
        PNG_SIGNATURE
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(bytes(raw)))
        + _chunk(b"IEND", b"")
    )


# --------------------------------------------------------------------------
# Decodificacao
# --------------------------------------------------------------------------
def _sample_pixels(width: int, height: int, channels: int = 3) -> bytes:
    data = bytearray()
    for y in range(height):
        for x in range(width):
            values = [(x * 7 + y) % 256, (x * 13) % 256, (y * 29) % 256, (x + y) % 256]
            data.extend(values[:channels])
    return bytes(data)


def test_decode_rgb_roundtrip():
    width, height = 5, 4
    pixels = _sample_pixels(width, height)
    image = decode_png(encode_png(width, height, pixels))
    assert (image.width, image.height, image.channels) == (width, height, 3)
    assert image.pixels == pixels
    assert image.pixel(2, 1) == tuple(pixels[(1 * width + 2) * 3 : (1 * width + 2) * 3 + 3])


@pytest.mark.parametrize("filter_type", [0, 1, 2, 3, 4])
def test_decode_all_filter_types(filter_type):
    width, height = 6, 5
    pixels = _sample_pixels(width, height)
    filters = [filter_type] * height
    image = decode_png(encode_png(width, height, pixels, row_filters=filters))
    assert image.pixels == pixels


def test_decode_rgba_roundtrip():
    width, height = 3, 3
    pixels = _sample_pixels(width, height, channels=4)
    image = decode_png(encode_png(width, height, pixels, color_type=6))
    assert image.channels == 4
    assert image.pixels == pixels


def test_decode_rejects_bad_signature():
    with pytest.raises(PngError):
        decode_png(b"not a png at all")


def test_decode_rejects_interlaced():
    ihdr = struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 1)
    data = PNG_SIGNATURE + _chunk(b"IHDR", ihdr) + _chunk(b"IEND", b"")
    with pytest.raises(PngError):
        decode_png(data)


# --------------------------------------------------------------------------
# Codificacao Terrarium
# --------------------------------------------------------------------------
def test_terrarium_elevation_reference_values():
    assert terrain.terrarium_elevation(128, 0, 0) == pytest.approx(0.0)
    assert terrain.terrarium_elevation(128, 1, 0) == pytest.approx(1.0)
    assert terrain.terrarium_elevation(127, 255, 0) == pytest.approx(-1.0)
    assert terrain.terrarium_elevation(128, 0, 128) == pytest.approx(0.5)


def _rgb(pixel_bytes: bytes, x: int, y: int, width: int = 256) -> tuple[int, int, int]:
    index = (y * width + x) * 3
    return tuple(pixel_bytes[index : index + 3])


def _tile_with_elevation(elevation_m: float, width: int = 256, height: int = 256) -> bytes:
    encoded = int(round((elevation_m + 32768.0) * 256.0))
    encoded = max(0, min(256 * 256 * 256 - 1, encoded))
    red = (encoded >> 16) & 0xFF
    green = (encoded >> 8) & 0xFF
    blue = encoded & 0xFF
    pixels = bytes([red, green, blue]) * (width * height)
    return encode_png(width, height, pixels)


def test_provider_reads_known_pixel_and_caches_tile():
    calls: list[tuple[int, int, int]] = []
    tile = _tile_with_elevation(1234.0)

    def fetch(z: int, x: int, y: int):
        calls.append((z, x, y))
        return tile

    provider = TerrariumElevation(fetch, zoom=0)
    # zoom 0, lon/lat 0 -> pixel (128,128) da unica tile.
    values = provider.elevations([(0.0, 0.0), (0.0, 0.0)])
    assert values == [pytest.approx(1234.0), pytest.approx(1234.0)]
    assert len(calls) == 1  # tile decodificado uma vez


def test_provider_returns_none_when_tile_missing():
    provider = TerrariumElevation(lambda z, x, y: None, zoom=12)
    assert provider.elevations([(-23.55, -46.63)]) == [None]


def test_provider_uses_different_tiles_by_position():
    fetched: set[tuple[int, int]] = set()

    def fetch(z: int, x: int, y: int):
        fetched.add((x, y))
        return _tile_with_elevation(100.0)

    provider = TerrariumElevation(fetch, zoom=12)
    provider.elevations([(-23.55, -46.63), (-23.55, -46.60)])
    assert len(fetched) >= 1
