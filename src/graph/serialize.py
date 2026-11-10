"""Serializacao (JSON/GeoJSON) e resumo estatistico do grafo.

O formato JSON e versionado (``FORMAT``/``VERSION``). ``graph_from_dict``
recusa payloads de formato ou versao desconhecidos, de modo que uma mudanca
incompativel exige subir ``VERSION``.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .model import BicycleAccess, CyclingGraph, Edge, EdgeSegment, ElevationSample, Node
from .restrictions import AccessRestriction
from .surface import SURFACE_PRIORITY, Surface, SurfaceStatus

FORMAT = "roteamento.cycling-graph"
VERSION = 2


def graph_to_dict(graph: CyclingGraph) -> dict[str, Any]:
    """Converte o grafo em um dicionario pronto para JSON.

    Nodes e edges saem ordenados por ``id`` (saida deterministica).

    Args:
        graph: Grafo a serializar.

    Returns:
        Dicionario com ``format``, ``version``, ``metadata``, ``nodes`` e
        ``edges``.
    """
    nodes = [
        {
            "id": node.id,
            "lat": node.lat,
            "lon": node.lon,
            "elevation_m": node.elevation_m,
            "osm_id": node.osm_id,
            "tags": dict(node.tags),
        }
        for node in sorted(graph.nodes.values(), key=lambda n: str(n.id))
    ]

    edges = []
    for edge in sorted(graph.edges.values(), key=lambda e: e.id):
        edges.append(
            {
                "id": edge.id,
                "source": edge.source,
                "target": edge.target,
                "geometry": [[lat, lon] for lat, lon in edge.geometry],
                "segments": [_segment_to_dict(segment) for segment in edge.segments],
            }
        )

    return {
        "format": FORMAT,
        "version": VERSION,
        "metadata": _jsonable(dict(graph.metadata)),
        "nodes": nodes,
        "edges": edges,
    }


def graph_from_dict(payload: dict[str, Any]) -> CyclingGraph:
    """Reconstroi o grafo a partir do dicionario serializado.

    Args:
        payload: Dicionario no formato produzido por :func:`graph_to_dict`.

    Returns:
        O ``CyclingGraph`` reconstruido.

    Raises:
        ValueError: Se ``format`` ou ``version`` forem desconhecidos.
    """
    if payload.get("format") != FORMAT:
        raise ValueError(f"formato inesperado: {payload.get('format')!r}")
    version = payload.get("version")
    if version not in (VERSION,):
        raise ValueError(f"versao nao suportada: {version!r} (esperado {VERSION})")

    graph = CyclingGraph()
    graph.metadata = dict(payload.get("metadata") or {})

    for raw in payload.get("nodes", []):
        graph.add_node(
            Node(
                id=raw["id"],
                lat=float(raw["lat"]),
                lon=float(raw["lon"]),
                elevation_m=raw.get("elevation_m"),
                osm_id=raw.get("osm_id"),
                tags=dict(raw.get("tags") or {}),
            )
        )

    for raw in payload.get("edges", []):
        segments = tuple(_segment_from_dict(item) for item in raw.get("segments") or ())
        graph.add_edge(
            Edge(
                id=str(raw["id"]),
                source=raw["source"],
                target=raw["target"],
                segments=segments,
                geometry=tuple(
                    (float(lat), float(lon)) for lat, lon in raw.get("geometry") or ()
                ),
            )
        )

    return graph


def save_json(graph: CyclingGraph, path: str | Path) -> Path:
    """Grava o grafo em JSON (UTF-8, identado) e devolve o caminho final.

    Cria os diretorios pais se necessario.

    Args:
        graph: Grafo a gravar.
        path: Destino do arquivo ``.json``.

    Returns:
        O ``Path`` gravado.
    """
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(graph_to_dict(graph), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return destination


def load_json(path: str | Path) -> CyclingGraph:
    """Le um grafo de um arquivo JSON produzido por :func:`save_json`.

    Args:
        path: Caminho do arquivo JSON.

    Returns:
        O ``CyclingGraph`` carregado.

    Raises:
        ValueError: Se o formato ou a versao nao forem suportados.
    """
    return graph_from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def to_geojson(graph: CyclingGraph) -> dict[str, Any]:
    """Converte o grafo em uma ``FeatureCollection`` do GeoJSON.

    Gera uma ``Point`` por no e uma ``LineString`` por aresta, com atributos
    (distancia, superficie, elevacao, acesso) em ``properties``.

    Args:
        graph: Grafo a converter.

    Returns:
        Dicionario GeoJSON (``FeatureCollection``).
    """
    features: list[dict[str, Any]] = []

    for node in graph.nodes.values():
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [node.lon, node.lat]},
                "properties": {
                    "kind": "node",
                    "id": node.id,
                    "elevation_m": node.elevation_m,
                },
            }
        )

    for edge in graph.edges.values():
        geometry = edge.geometry or (
            (graph.get_node(edge.source).lat, graph.get_node(edge.source).lon),
            (graph.get_node(edge.target).lat, graph.get_node(edge.target).lon),
        )
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[lon, lat] for lat, lon in geometry],
                },
                "properties": {
                    "kind": "edge",
                    "id": edge.id,
                    "source": edge.source,
                    "target": edge.target,
                    "distance_m": edge.distance_m,
                    "surface": edge.surface.value,
                    "surface_status": edge.surface_status.value,
                    "surface_priority": edge.surface_priority,
                    "elevation_gain_m": edge.elevation_gain_m,
                    "elevation_loss_m": edge.elevation_loss_m,
                    "elevation_source": edge.elevation_source,
                    "segment_count": edge.segment_count,
                    "highway": edge.highway,
                    "name": edge.name,
                    "osm_way_id": edge.osm_way_id,
                    "bicycle_access": edge.bicycle_access.value,
                },
            }
        )

    return {"type": "FeatureCollection", "features": features}


def save_geojson(graph: CyclingGraph, path: str | Path) -> Path:
    """Grava o grafo em GeoJSON (UTF-8) e devolve o caminho final.

    Args:
        graph: Grafo a gravar.
        path: Destino do arquivo ``.geojson``.

    Returns:
        O ``Path`` gravado.
    """
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(to_geojson(graph), ensure_ascii=False),
        encoding="utf-8",
    )
    return destination


def summarize(graph: CyclingGraph) -> dict[str, Any]:
    """Resume o grafo: totais, cobertura de elevacao e distribuicao por superficie.

    Args:
        graph: Grafo a resumir.

    Returns:
        Dicionario com contagens (nos/arestas/segmentos), comprimento e
        elevacao totais, cobertura de elevacao e distribuicoes por superficie,
        proveniencia e prioridade.
    """
    length_by_surface: dict[str, float] = defaultdict(float)
    edges_by_surface: Counter[str] = Counter()
    length_by_priority: dict[int, float] = defaultdict(float)
    length_by_status: dict[str, float] = defaultdict(float)

    total_length = 0.0
    total_gain = 0.0
    total_loss = 0.0
    with_elevation = 0
    dismount_length = 0.0
    segments_total = 0
    elevation_sources: Counter[str] = Counter()

    for edge in graph.edges.values():
        total_length += edge.distance_m
        total_gain += edge.elevation_gain_m
        total_loss += edge.elevation_loss_m
        if edge.has_elevation:
            with_elevation += 1
        if edge.bicycle_access is BicycleAccess.DISMOUNT:
            dismount_length += edge.distance_m
        if edge.elevation_source:
            elevation_sources[edge.elevation_source] += 1

        for segment in edge.segments:
            segments_total += 1
            length_by_surface[segment.surface.value] += segment.distance_m
            length_by_status[segment.surface_status.value] += segment.distance_m
            length_by_priority[segment.surface_priority] += segment.distance_m
            edges_by_surface[segment.surface.value] += 1

    return {
        "nodes": graph.node_count,
        "edges": graph.edge_count,
        "segments": segments_total,
        "total_length_m": round(total_length, 1),
        "total_length_km": round(total_length / 1000.0, 3),
        "total_ascent_m": round(total_gain, 1),
        "total_descent_m": round(total_loss, 1),
        "edges_with_elevation": with_elevation,
        "elevation_coverage": round(with_elevation / graph.edge_count, 3)
        if graph.edge_count
        else 0.0,
        "elevation_sources": dict(sorted(elevation_sources.items())),
        "dismount_length_m": round(dismount_length, 1),
        "length_by_surface_m": {
            key: round(value, 1) for key, value in sorted(length_by_surface.items())
        },
        "length_by_surface_status_m": {
            key: round(value, 1) for key, value in sorted(length_by_status.items())
        },
        "edges_by_surface": dict(sorted(edges_by_surface.items())),
        "length_by_priority_m": {
            str(key): round(value, 1) for key, value in sorted(length_by_priority.items())
        },
        "surface_priorities": {
            surface.value: SURFACE_PRIORITY[surface] for surface in Surface
        },
        "simplification": graph.metadata.get("simplification"),
    }


# --------------------------------------------------------------------------
def _segment_to_dict(segment: EdgeSegment) -> dict[str, Any]:
    return {
        "id": segment.id,
        "distance_m": segment.distance_m,
        "surface": segment.surface.value,
        "surface_status": segment.surface_status.value,
        "surface_priority": segment.surface_priority,
        "elevation_gain_m": segment.elevation_gain_m,
        "elevation_loss_m": segment.elevation_loss_m,
        "min_elevation_m": segment.min_elevation_m,
        "max_elevation_m": segment.max_elevation_m,
        "elevation_source": segment.elevation_source,
        "elevation_resolution_m": segment.elevation_resolution_m,
        "elevation_profile": [
            [sample.distance_m, sample.elevation_m, sample.source, sample.resolution_m]
            for sample in segment.elevation_profile
        ],
        "highway": segment.highway,
        "name": segment.name,
        "osm_way_id": segment.osm_way_id,
        "bicycle_access": segment.bicycle_access.value,
        "max_speed_kmh": segment.max_speed_kmh,
        "restrictions": [
            {
                "scope": restriction.scope,
                "value": restriction.value,
                "condition": restriction.condition,
                "raw": restriction.raw,
            }
            for restriction in segment.restrictions
        ],
        "geometry": [[lat, lon] for lat, lon in segment.geometry],
        "tags": dict(segment.tags),
    }


def _segment_from_dict(raw: dict[str, Any]) -> EdgeSegment:
    profile = tuple(
        ElevationSample(
            distance_m=float(item[0]),
            elevation_m=float(item[1]),
            source=str(item[2]) if len(item) > 2 and item[2] is not None else "",
            resolution_m=float(item[3])
            if len(item) > 3 and item[3] is not None
            else None,
        )
        for item in raw.get("elevation_profile") or ()
    )
    return EdgeSegment(
        id=str(raw["id"]),
        distance_m=float(raw["distance_m"]),
        surface=Surface(raw.get("surface", "unknown")),
        surface_status=SurfaceStatus(raw.get("surface_status", "unknown")),
        elevation_gain_m=float(raw.get("elevation_gain_m") or 0.0),
        elevation_loss_m=float(raw.get("elevation_loss_m") or 0.0),
        min_elevation_m=raw.get("min_elevation_m"),
        max_elevation_m=raw.get("max_elevation_m"),
        elevation_profile=profile,
        highway=raw.get("highway"),
        name=raw.get("name"),
        osm_way_id=raw.get("osm_way_id"),
        bicycle_access=BicycleAccess(raw.get("bicycle_access", "yes")),
        max_speed_kmh=raw.get("max_speed_kmh"),
        restrictions=tuple(
            AccessRestriction(
                scope=item["scope"],
                value=item["value"],
                condition=item.get("condition"),
                raw=item.get("raw", ""),
            )
            for item in raw.get("restrictions") or ()
        ),
        geometry=tuple(
            (float(lat), float(lon)) for lat, lon in raw.get("geometry") or ()
        ),
        tags=dict(raw.get("tags") or {}),
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value
