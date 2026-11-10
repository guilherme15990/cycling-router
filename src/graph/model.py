"""Modelo do grafo ciclavel: nos, segmentos, arestas direcionadas e grafo.

Uma aresta pode representar varios segmentos consecutivos (apos a
simplificacao). Cada segmento guarda os proprios atributos: distancia,
superficie (com proveniencia), perfil de elevacao e restricoes. Assim a
contracao de nos de grau 2 nao perde dados fisicos nem de acesso.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Hashable, Iterator, Mapping, Sequence

from .restrictions import AccessRestriction
from .surface import SURFACE_PRIORITY, Surface, SurfaceStatus

Coord = tuple[float, float]


class GraphError(ValueError):
    """Erro de consistencia ao montar o grafo."""


class BicycleAccess(str, Enum):
    """Permissao de circulacao observada no OSM."""

    YES = "yes"
    DISMOUNT = "dismount"


@dataclass(frozen=True, slots=True)
class ElevationSample:
    """Altitude a ``distance_m`` metros do inicio do segmento.

    ``source`` e ``resolution_m`` preservam a proveniencia: a camada Flattest
    precisa saber se o perfil vem de SRTM 30 m, de ``ele=*`` esparso ou de um
    DEM de alta resolucao.
    """

    distance_m: float
    elevation_m: float
    source: str = ""
    resolution_m: float | None = None


@dataclass(frozen=True, slots=True)
class EdgeSegment:
    """Trecho com atributos homogeneos entre dois pontos de forma do OSM."""

    id: str
    distance_m: float
    surface: Surface = Surface.UNKNOWN
    surface_status: SurfaceStatus = SurfaceStatus.UNKNOWN

    elevation_gain_m: float = 0.0
    elevation_loss_m: float = 0.0
    min_elevation_m: float | None = None
    max_elevation_m: float | None = None
    elevation_profile: tuple[ElevationSample, ...] = ()

    geometry: tuple[Coord, ...] = ()
    highway: str | None = None
    name: str | None = None
    osm_way_id: int | None = None
    bicycle_access: BicycleAccess = BicycleAccess.YES
    max_speed_kmh: float | None = None
    restrictions: tuple[AccessRestriction, ...] = ()
    tags: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.distance_m <= 0:
            raise GraphError(f"segmento {self.id}: distance_m deve ser positiva")
        if self.elevation_gain_m < 0 or self.elevation_loss_m < 0:
            raise GraphError(f"segmento {self.id}: ganho/perda nao podem ser negativos")

    @property
    def surface_priority(self) -> int:
        return SURFACE_PRIORITY[self.surface]

    @property
    def has_elevation(self) -> bool:
        return len(self.elevation_profile) >= 2

    @property
    def elevation_source(self) -> str | None:
        return self.elevation_profile[0].source if self.elevation_profile else None

    @property
    def elevation_resolution_m(self) -> float | None:
        values = {
            sample.resolution_m
            for sample in self.elevation_profile
            if sample.resolution_m is not None
        }
        return max(values) if values else None

    @property
    def elevation_delta_m(self) -> float | None:
        if not self.has_elevation:
            return None
        return self.elevation_profile[-1].elevation_m - self.elevation_profile[0].elevation_m

    def reversed_segment(self, segment_id: str | None = None) -> "EdgeSegment":
        total = self.distance_m
        profile = tuple(
            ElevationSample(
                distance_m=total - sample.distance_m,
                elevation_m=sample.elevation_m,
                source=sample.source,
                resolution_m=sample.resolution_m,
            )
            for sample in reversed(self.elevation_profile)
        )
        return replace(
            self,
            id=segment_id or f"{self.id}:rev",
            elevation_gain_m=self.elevation_loss_m,
            elevation_loss_m=self.elevation_gain_m,
            elevation_profile=profile,
            geometry=tuple(reversed(self.geometry)),
        )


@dataclass(frozen=True, slots=True)
class Edge:
    """Aresta direcionada composta por um ou mais segmentos consecutivos."""

    id: str
    source: Hashable
    target: Hashable
    segments: tuple[EdgeSegment, ...]
    geometry: tuple[Coord, ...] = ()

    def __post_init__(self) -> None:
        if self.source == self.target:
            raise GraphError(f"aresta {self.id}: origem e destino iguais")
        if not self.segments:
            raise GraphError(f"aresta {self.id}: sem segmentos")
        if self.distance_m <= 0:
            raise GraphError(f"aresta {self.id}: distance_m deve ser positiva")

    # ------------------------------------------------------------ geometria
    @property
    def distance_m(self) -> float:
        return round(sum(segment.distance_m for segment in self.segments), 3)

    @property
    def segment_count(self) -> int:
        return len(self.segments)

    # ----------------------------------------------------------- superficie
    @property
    def surface(self) -> Surface:
        """Superficie dominante por comprimento (a verdade fica nos segmentos)."""
        return _dominant((segment.surface, segment.distance_m) for segment in self.segments)

    @property
    def surface_priority(self) -> int:
        return SURFACE_PRIORITY[self.surface]

    @property
    def surface_status(self) -> SurfaceStatus:
        statuses = {segment.surface_status for segment in self.segments}
        if statuses == {SurfaceStatus.MAPPED}:
            return SurfaceStatus.MAPPED
        if SurfaceStatus.INFERRED in statuses:
            return SurfaceStatus.INFERRED
        if statuses == {SurfaceStatus.UNKNOWN}:
            return SurfaceStatus.UNKNOWN
        return SurfaceStatus.UNMAPPED

    @property
    def surfaces(self) -> frozenset[Surface]:
        return frozenset(segment.surface for segment in self.segments)

    # ------------------------------------------------------------ elevacao
    @property
    def elevation_gain_m(self) -> float:
        return round(sum(segment.elevation_gain_m for segment in self.segments), 3)

    @property
    def elevation_loss_m(self) -> float:
        return round(sum(segment.elevation_loss_m for segment in self.segments), 3)

    @property
    def min_elevation_m(self) -> float | None:
        values = {
            segment.min_elevation_m
            for segment in self.segments
            if segment.min_elevation_m is not None
        }
        return min(values) if values else None

    @property
    def max_elevation_m(self) -> float | None:
        values = {
            segment.max_elevation_m
            for segment in self.segments
            if segment.max_elevation_m is not None
        }
        return max(values) if values else None

    @property
    def elevation_profile(self) -> tuple[ElevationSample, ...]:
        """Perfil consolidado, com distancias relativas ao inicio da aresta."""
        samples: list[ElevationSample] = []
        offset = 0.0
        for segment in self.segments:
            for sample in segment.elevation_profile:
                samples.append(
                    ElevationSample(
                        distance_m=offset + sample.distance_m,
                        elevation_m=sample.elevation_m,
                        source=sample.source,
                        resolution_m=sample.resolution_m,
                    )
                )
            offset += segment.distance_m
        return tuple(samples)

    @property
    def has_elevation(self) -> bool:
        return any(segment.has_elevation for segment in self.segments)

    @property
    def elevation_source(self) -> str | None:
        sources = {
            segment.elevation_source
            for segment in self.segments
            if segment.elevation_source
        }
        if not sources:
            return None
        return sources.pop() if len(sources) == 1 else "mixed"

    @property
    def elevation_resolution_m(self) -> float | None:
        values = {
            segment.elevation_resolution_m
            for segment in self.segments
            if segment.elevation_resolution_m is not None
        }
        return max(values) if values else None

    @property
    def elevation_delta_m(self) -> float | None:
        profile = self.elevation_profile
        if len(profile) < 2:
            return None
        return profile[-1].elevation_m - profile[0].elevation_m

    # ------------------------------------------------------------ atributos
    @property
    def highway(self) -> str | None:
        return _dominant(
            (segment.highway, segment.distance_m) for segment in self.segments
        )

    @property
    def name(self) -> str | None:
        return _dominant(
            (segment.name, segment.distance_m) for segment in self.segments
        )

    @property
    def osm_way_id(self) -> int | None:
        values = {segment.osm_way_id for segment in self.segments}
        return values.pop() if len(values) == 1 else None

    @property
    def bicycle_access(self) -> BicycleAccess:
        if any(
            segment.bicycle_access is BicycleAccess.DISMOUNT
            for segment in self.segments
        ):
            return BicycleAccess.DISMOUNT
        return BicycleAccess.YES

    @property
    def max_speed_kmh(self) -> float | None:
        values = [
            segment.max_speed_kmh
            for segment in self.segments
            if segment.max_speed_kmh is not None
        ]
        return min(values) if values else None

    @property
    def restrictions(self) -> tuple[AccessRestriction, ...]:
        return tuple(
            restriction
            for segment in self.segments
            for restriction in segment.restrictions
        )

    @property
    def tags(self) -> Mapping[str, str]:
        if len(self.segments) == 1:
            return self.segments[0].tags
        return {}

    def reversed_edge(self, edge_id: str | None = None) -> "Edge":
        return replace(
            self,
            id=edge_id or f"{self.id}:rev",
            source=self.target,
            target=self.source,
            segments=tuple(
                segment.reversed_segment(f"{segment.id}:rev")
                for segment in reversed(self.segments)
            ),
            geometry=tuple(reversed(self.geometry)),
        )


def _dominant(
    pairs: Sequence[tuple[Any, float]] | Iterator[tuple[Any, float]],
) -> Any:
    weights: dict[Any, float] = {}
    order: dict[Any, int] = {}
    for index, (value, length) in enumerate(pairs):
        if value is None:
            continue
        weights[value] = weights.get(value, 0.0) + length
        order.setdefault(value, index)

    if not weights:
        return None
    return max(weights, key=lambda value: (weights[value], -order[value]))


@dataclass(frozen=True, slots=True)
class Node:
    """Posicao geografica. ``elevation_m`` e opcional (pode nao existir DEM)."""

    id: Hashable
    lat: float
    lon: float
    elevation_m: float | None = None
    osm_id: int | None = None
    tags: Mapping[str, str] = field(default_factory=dict)

    @property
    def coord(self) -> tuple[float, float]:
        return (self.lat, self.lon)


class CyclingGraph:
    """Grafo direcionado com adjacencia por origem.

    Arestas paralelas sao permitidas (ruas duplicadas existem no OSM). A
    identidade de uma aresta e o seu ``id``.
    """

    def __init__(self) -> None:
        self._nodes: dict[Hashable, Node] = {}
        self._edges: dict[str, Edge] = {}
        self._outgoing: dict[Hashable, list[str]] = {}
        self.metadata: dict[str, Any] = {}

    # ------------------------------------------------------------------ nos
    def add_node(self, node: Node) -> None:
        if node.id in self._nodes:
            raise GraphError(f"no duplicado: {node.id}")
        self._nodes[node.id] = node
        self._outgoing.setdefault(node.id, [])

    def get_node(self, node_id: Hashable) -> Node:
        try:
            return self._nodes[node_id]
        except KeyError as exc:
            raise GraphError(f"no desconhecido: {node_id}") from exc

    def set_node_elevation(self, node_id: Hashable, elevation_m: float | None) -> None:
        node = self.get_node(node_id)
        self._nodes[node_id] = replace(node, elevation_m=elevation_m)

    @property
    def nodes(self) -> Mapping[Hashable, Node]:
        return self._nodes

    def node_ids(self) -> Iterator[Hashable]:
        return iter(self._nodes)

    # -------------------------------------------------------------- arestas
    def add_edge(self, edge: Edge) -> None:
        if edge.source not in self._nodes:
            raise GraphError(f"aresta {edge.id}: origem desconhecida {edge.source!r}")
        if edge.target not in self._nodes:
            raise GraphError(f"aresta {edge.id}: destino desconhecido {edge.target!r}")
        if edge.id in self._edges:
            raise GraphError(f"aresta duplicada: {edge.id}")

        self._edges[edge.id] = edge
        self._outgoing[edge.source].append(edge.id)

    def add_bidirectional(self, edge: Edge, reverse_id: str | None = None) -> tuple[Edge, Edge]:
        """Adiciona a aresta e a sua inversa (ganho/perda trocados)."""
        self.add_edge(edge)
        reverse = edge.reversed_edge(reverse_id)
        self.add_edge(reverse)
        return edge, reverse

    def replace_edge(self, edge: Edge) -> None:
        """Substitui uma aresta existente (usado ao anexar elevacao)."""
        if edge.id not in self._edges:
            raise GraphError(f"aresta inexistente: {edge.id}")
        self._edges[edge.id] = edge

    def get_edge(self, edge_id: str) -> Edge:
        try:
            return self._edges[edge_id]
        except KeyError as exc:
            raise GraphError(f"aresta desconhecida: {edge_id}") from exc

    @property
    def edges(self) -> Mapping[str, Edge]:
        return self._edges

    def out_edges(self, node_id: Hashable) -> list[Edge]:
        return [self._edges[edge_id] for edge_id in self._outgoing.get(node_id, ())]

    def neighbors(self, node_id: Hashable) -> list[Node]:
        return [self._nodes[edge.target] for edge in self.out_edges(node_id)]

    def in_edges(self, node_id: Hashable) -> list[Edge]:
        return [edge for edge in self._edges.values() if edge.target == node_id]

    def copy(self) -> "CyclingGraph":
        """Copia estrutural rasa (nos e arestas sao imutaveis)."""
        clone = CyclingGraph()
        clone._nodes = dict(self._nodes)
        clone._edges = dict(self._edges)
        clone._outgoing = {
            node_id: list(edge_ids) for node_id, edge_ids in self._outgoing.items()
        }
        clone.metadata = dict(self.metadata)
        return clone

    def remove_edge(self, edge_id: str) -> Edge:
        try:
            edge = self._edges.pop(edge_id)
        except KeyError as exc:
            raise GraphError(f"aresta inexistente: {edge_id}") from exc
        self._outgoing[edge.source].remove(edge_id)
        return edge

    @property
    def edge_count(self) -> int:
        return len(self._edges)

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    def __len__(self) -> int:
        return len(self._edges)

    def __contains__(self, node_id: object) -> bool:
        return node_id in self._nodes
