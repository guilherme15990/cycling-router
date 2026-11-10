"""Geometria basica: distancias, interpolacao e amostragem ao longo de linhas.

Todas as coordenadas sao pares ``(lat, lon)`` em graus decimais (WGS84).
Distancias horizontais sao calculadas com a formula de haversine, porque a
distancia de uma aresta deve ser o comprimento real do caminho e nao a reta
entre os nos (ver ALGO CICLISTA.md).
"""

from __future__ import annotations

import bisect
import math
from typing import Sequence

Coord = tuple[float, float]

EARTH_RADIUS_M = 6_371_008.8


def haversine_m(a: Coord, b: Coord) -> float:
    """Distancia em metros entre duas coordenadas."""
    lat1, lon1 = a
    lat2, lon2 = b
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    h = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


def cumulative_distances(coords: Sequence[Coord]) -> list[float]:
    """Distancias acumuladas ao longo da polilinha (comeca em 0.0)."""
    if not coords:
        return []
    out = [0.0]
    for previous, current in zip(coords, coords[1:]):
        out.append(out[-1] + haversine_m(previous, current))
    return out


def line_length_m(coords: Sequence[Coord]) -> float:
    if len(coords) < 2:
        return 0.0
    return cumulative_distances(coords)[-1]


def interpolate_along(
    coords: Sequence[Coord],
    cumulative: Sequence[float],
    target_m: float,
) -> Coord:
    """Ponto a ``target_m`` metros do inicio da polilinha."""
    if not coords:
        raise ValueError("polilinha vazia")
    if len(coords) == 1 or cumulative[-1] <= 0.0:
        return coords[0]

    target_m = min(max(target_m, 0.0), cumulative[-1])
    index = bisect.bisect_right(cumulative, target_m) - 1
    index = min(index, len(coords) - 2)

    start_d = cumulative[index]
    end_d = cumulative[index + 1]
    if end_d <= start_d:
        return coords[index]

    ratio = (target_m - start_d) / (end_d - start_d)
    lat1, lon1 = coords[index]
    lat2, lon2 = coords[index + 1]
    return (lat1 + (lat2 - lat1) * ratio, lon1 + (lon2 - lon1) * ratio)


def sample_along(
    coords: Sequence[Coord],
    spacing_m: float,
) -> list[tuple[float, Coord]]:
    """Amostra a polilinha a cada ``spacing_m`` metros, incluindo os extremos.

    Retorna pares ``(distancia_m, coordenada)``. O ultimo intervalo pode ser
    menor que ``spacing_m`` para garantir que o ponto final seja amostrado.
    """
    if not coords:
        return []
    if spacing_m <= 0:
        raise ValueError("spacing_m deve ser positivo")

    cumulative = cumulative_distances(coords)
    total = cumulative[-1]
    if len(coords) == 1 or total <= 0.0:
        return [(0.0, coords[0])]

    samples: list[tuple[float, Coord]] = []
    distance = 0.0
    while distance < total:
        samples.append((distance, interpolate_along(coords, cumulative, distance)))
        distance += spacing_m

    target = total
    last_distance = samples[-1][0] if samples else 0.0
    if target - last_distance < 1e-6:
        samples[-1] = (target, coords[-1])
    else:
        samples.append((target, coords[-1]))
    return samples


def point_at_fraction(coords: Sequence[Coord], fraction: float) -> Coord:
    """Ponto na fracao ``fraction`` (0..1) do comprimento da polilinha."""
    cumulative = cumulative_distances(coords)
    return interpolate_along(coords, cumulative, cumulative[-1] * fraction)


def parse_bbox(text: str) -> tuple[float, float, float, float]:
    """Aceita ``sul,oeste,norte,leste`` (formato Overpass)."""
    parts = [chunk.strip() for chunk in text.split(",")]
    if len(parts) != 4:
        raise ValueError("bbox deve ter 4 valores: sul,oeste,norte,leste")
    south, west, north, east = (float(part) for part in parts)
    if south >= north or west >= east:
        raise ValueError("bbox invalida: sul < norte e oeste < leste")
    if not (-90 <= south <= 90 and -90 <= north <= 90):
        raise ValueError("latitude fora do intervalo [-90, 90]")
    return south, west, north, east


def format_bbox(bbox: tuple[float, float, float, float]) -> str:
    south, west, north, east = bbox
    return f"{south:.7f},{west:.7f},{north:.7f},{east:.7f}"


def parse_coord(text: str) -> tuple[float, float]:
    """Aceita ``lat,lon`` em graus decimais."""
    parts = [chunk.strip() for chunk in text.split(",")]
    if len(parts) != 2:
        raise ValueError("coordenada deve ser 'lat,lon'")
    lat, lon = (float(part) for part in parts)
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        raise ValueError(f"coordenada fora do intervalo: {text!r}")
    return lat, lon


def bbox_of(coords: Sequence[Coord]) -> tuple[float, float, float, float]:
    if not coords:
        raise ValueError("sem coordenadas")
    lats = [c[0] for c in coords]
    lons = [c[1] for c in coords]
    return min(lats), min(lons), max(lats), max(lons)
