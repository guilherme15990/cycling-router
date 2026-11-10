"""Snapping espacial: conecta origem/destino a rede ciclavel.

Esta e uma camada de **preparacao da consulta**, nao do grafo. O grafo base
continua intacto; o resultado e um ``QueryGraph`` novo, com nos virtuais e as
arestas divididas no ponto projetado.

Regras:

* o ponto e projetado no segmento mais proximo de uma aresta utilizavel;
* um no existente so e escolhido quando esta muito perto (padrao: 10 m) e a
  diferenca para o desvio da aresta e pequena (padrao: 2 m);
* se o ponto cai perto das pontas da aresta, a conexao vira um no existente;
* caso contrario, a aresta e dividida em dois trechos temporarios;
* quando existe a aresta inversa, ela tambem e dividida no mesmo ponto.

A divisao preserva os segmentos: distancia, superficie, perfil de elevacao,
restricoes e geometria continuam disponiveis nos fragmentos.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field, replace
from typing import Hashable, Literal, Sequence

from geo import (
    Coord,
    cumulative_distances,
    haversine_m,
    interpolate_along,
)
from graph.model import (
    BicycleAccess,
    CyclingGraph,
    Edge,
    EdgeSegment,
    ElevationSample,
    Node,
)

SnapKind = Literal["node", "edge"]

M_PER_DEG = 111_320.0


class SnapError(ValueError):
    """Nao foi possivel conectar o ponto a rede ciclavel."""


# --------------------------------------------------------------------------
# Opcoes e resultados
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class SnapOptions:
    """Parametros do snapping.

    ``max_distance_m`` limita o desvio aceito. ``node_preference_m`` define
    quando um no existente e preferivel a um ponto interno da aresta; o no
    ainda precisa estar a no maximo ``node_offset_tolerance_m`` do desvio da
    aresta. ``min_split_distance_m`` evita fragmentos quase nulos nas pontas.
    """

    max_distance_m: float = 100.0
    node_preference_m: float = 10.0
    node_offset_tolerance_m: float = 2.0
    min_split_distance_m: float = 1.0
    allow_dismount: bool = True
    cell_size_m: float | None = None


@dataclass(frozen=True)
class SnapCandidate:
    """Ponto escolhido para conectar a consulta a rede.

    Attributes:
        label: Rotulo informado na consulta (ex.: ``"origin"``).
        kind: ``"node"`` (no existente) ou ``"edge"`` (ponto interno).
        point: Coordenada ``(lat, lon)`` do ponto conectado.
        offset_m: Distancia da coordenada original ate o ponto escolhido.
        node_id: No escolhido, quando ``kind == "node"``.
        edge_id: Aresta escolhida, quando ``kind == "edge"``.
        segment_id: Segmento da aresta, quando ``kind == "edge"``.
        segment_index: Indice do segmento na aresta.
        along_m: Distancia do inicio da aresta ate o ponto, em metros.
        fraction: Fracao ``0..1`` do comprimento da aresta.
    """

    label: str
    kind: SnapKind
    point: Coord
    offset_m: float
    node_id: Hashable | None = None
    edge_id: str | None = None
    segment_id: str | None = None
    segment_index: int | None = None
    along_m: float | None = None
    fraction: float | None = None

    @property
    def is_node(self) -> bool:
        return self.kind == "node"

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "kind": self.kind,
            "point": [round(self.point[0], 7), round(self.point[1], 7)],
            "offset_m": round(self.offset_m, 3),
            "node_id": self.node_id,
            "edge_id": self.edge_id,
            "segment_id": self.segment_id,
            "segment_index": self.segment_index,
            "along_m": None if self.along_m is None else round(self.along_m, 3),
            "fraction": None if self.fraction is None else round(self.fraction, 6),
        }


@dataclass(frozen=True)
class _EdgeSplit:
    edge_id: str
    head: Edge
    tail: Edge


@dataclass(frozen=True)
class SnapResult:
    """Plano de conexao de um ponto, aplicavel a uma copia do grafo.

    Attributes:
        candidate: Ponto escolhido (:class:`SnapCandidate`).
        node_id: Id do no que representa a conexao (existente ou virtual).
        virtual: ``True`` se um no novo precisa ser criado.
        splits: Divisões de aresta necessarias (no novo no meio).
        elevation_m: Elevacao interpolada do no virtual, quando disponivel.
    """

    candidate: SnapCandidate
    node_id: Hashable
    virtual: bool
    splits: tuple[_EdgeSplit, ...] = ()
    elevation_m: float | None = None

    def apply(self, graph: CyclingGraph) -> CyclingGraph:
        """Retorna uma copia do grafo com a conexao aplicada.

        Nao altera o grafo original: trabalha sobre ``graph.copy()``.

        Args:
            graph: Grafo de destino da conexao.

        Returns:
            Copia do grafo com o no virtual e as arestas divididas.

        Raises:
            SnapError: Se o no virtual ja existir ou uma aresta a dividir
                estiver ausente no grafo de destino.
        """
        query = graph.copy()

        if self.virtual:
            if self.node_id in query:
                raise SnapError(
                    f"no virtual {self.node_id!r} ja existe no grafo de destino"
                )
            lat, lon = self.candidate.point
            query.add_node(
                Node(
                    id=self.node_id,
                    lat=lat,
                    lon=lon,
                    elevation_m=self.elevation_m,
                    osm_id=None,
                    tags={"virtual": "snap", "snap": self.candidate.label},
                )
            )

        for split in self.splits:
            if split.edge_id not in query.edges:
                raise SnapError(
                    f"aresta {split.edge_id!r} nao existe no grafo de destino"
                )
            query.remove_edge(split.edge_id)
            query.add_edge(split.head)
            query.add_edge(split.tail)

        return query


@dataclass(frozen=True)
class QueryGraph:
    """Grafo temporario pronto para a busca de rotas.

    Attributes:
        graph: Grafo (copia) com origem e destino ja conectados.
        origin_id: Id do no de origem no grafo de consulta.
        destination_id: Id do no de destino no grafo de consulta.
        origin: Candidato escolhido para a origem.
        destination: Candidato escolhido para o destino.
        virtual_nodes: Ids dos nos virtuais criados neste grafo de consulta.
    """

    graph: CyclingGraph
    origin_id: Hashable
    destination_id: Hashable
    origin: SnapCandidate
    destination: SnapCandidate
    virtual_nodes: frozenset[Hashable] = field(default_factory=frozenset)

    def is_connected(self) -> bool:
        """Alcancabilidade direcionada da origem ao destino (BFS).

        Returns:
            ``True`` se existe caminho direcionado de ``origin_id`` ate
            ``destination_id`` no grafo de consulta.
        """
        return _reachable(self.graph, self.origin_id, self.destination_id)


# --------------------------------------------------------------------------
# Snapper
# --------------------------------------------------------------------------
class SpatialSnapper:
    """Indexa arestas e nos e projeta coordenadas na rede."""

    def __init__(
        self,
        graph: CyclingGraph,
        options: SnapOptions | None = None,
    ) -> None:
        self.graph = graph
        self.options = options or SnapOptions()

        reference_lat = _reference_latitude(graph)
        cell_size = self.options.cell_size_m or max(
            64.0, self.options.max_distance_m
        )
        self._edge_index = _GridIndex(cell_size, reference_lat)
        self._node_index = _GridIndex(cell_size, reference_lat)
        self._usable_edges: dict[str, Edge] = {}
        self._reverse_candidates: dict[tuple[Hashable, Hashable], list[Edge]] = (
            defaultdict(list)
        )
        self._out_count: dict[Hashable, int] = defaultdict(int)
        self._in_count: dict[Hashable, int] = defaultdict(int)
        connected_nodes: set[Hashable] = set()

        for edge in graph.edges.values():
            self._reverse_candidates[(edge.source, edge.target)].append(edge)
            if not self._is_usable(edge):
                continue
            self._usable_edges[edge.id] = edge
            self._out_count[edge.source] += 1
            self._in_count[edge.target] += 1
            self._edge_index.add_box(edge.id, _edge_bbox(edge, graph))
            connected_nodes.add(edge.source)
            connected_nodes.add(edge.target)

        for node_id in connected_nodes:
            node = graph.get_node(node_id)
            self._node_index.add_point(node_id, node.lat, node.lon)

    # ------------------------------------------------------------------ API
    def snap(
        self,
        coord: Coord,
        label: str = "point",
        role: Literal["origin", "destination"] | None = None,
    ) -> SnapResult:
        """Conecta ``coord`` a rede e devolve o plano de conexao.

        ``role`` restringe a escolha de nos existentes: a origem precisa ter
        saida utilizavel e o destino precisa ter entrada utilizavel. Pontos
        internos de aresta nao precisam desse filtro, pois a propria aresta ja
        garante o sentido.

        Args:
            coord: Coordenada ``(lat, lon)`` a conectar.
            label: Rotulo usado no :class:`SnapCandidate` e no id do no virtual.
            role: Papel na consulta (``"origin"``/``"destination"``) ou
                ``None`` para uso generico.

        Returns:
            O :class:`SnapResult` com o ponto escolhido e as divisoes de aresta.

        Raises:
            SnapError: Se a coordenada estiver fora do intervalo ou nao houver
                no/aresta utilizavel dentro de ``max_distance_m``.

        Example:
            >>> snapper = SpatialSnapper(graph)
            >>> result = snapper.snap((-23.5487, -46.6326), label="origin", role="origin")
            >>> result.candidate.kind in {"node", "edge"}
            True
        """
        lat, lon = float(coord[0]), float(coord[1])
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            raise SnapError(f"coordenada fora do intervalo: {coord!r}")

        point = (lat, lon)
        node_candidate = self._nearest_node(point, label, role)
        edge_hit = self._nearest_edge(point, label)

        if node_candidate is None and edge_hit is None:
            raise SnapError(
                f"{label}: nenhum no ou aresta utilizavel em ate "
                f"{self.options.max_distance_m:.0f} m"
            )

        # Preferencia por no existente: perto e coerente com o desvio da aresta.
        if node_candidate is not None and node_candidate.offset_m <= (
            self.options.node_preference_m
        ):
            if edge_hit is None or node_candidate.offset_m <= (
                edge_hit[1].offset_m + self.options.node_offset_tolerance_m
            ):
                return _node_result(node_candidate)

        if edge_hit is None:
            return _node_result(node_candidate)  # type: ignore[arg-type]

        edge, projection = edge_hit
        total = edge.distance_m
        floor = min(
            max(self.options.min_split_distance_m, 1e-6), total / 2.0
        )

        # Perto demais das pontas: usa o no existente em vez de criar fragmento.
        # Se o no nao serve para o papel (origem sem saida / destino sem
        # entrada), divide a aresta no limite, mantendo a conexao no sentido.
        if projection.along_m <= floor:
            if self._endpoint_allowed(edge.source, role):
                return _node_result(
                    self._endpoint_candidate(edge.source, point, label)
                )
            projection = self._clamp_projection(edge, projection, floor, point)
        elif projection.along_m >= total - floor:
            if self._endpoint_allowed(edge.target, role):
                return _node_result(
                    self._endpoint_candidate(edge.target, point, label)
                )
            projection = self._clamp_projection(
                edge, projection, total - floor, point
            )

        node_id = self._unique_node_id(label)
        forward = _split_from_projection(edge, projection, node_id, label)

        reverse = self._find_reverse(edge)
        reverse_split: _EdgeSplit | None = None
        if reverse is not None:
            reverse_projection = _locate_along(
                reverse,
                reverse.distance_m - projection.along_m,
                point_override=projection.point,
            )
            if reverse_projection is not None:
                reverse_split = _split_from_projection(
                    reverse, reverse_projection, node_id, label
                )

        segment = edge.segments[projection.segment_index]
        candidate = SnapCandidate(
            label=label,
            kind="edge",
            point=projection.point,
            offset_m=projection.offset_m,
            edge_id=edge.id,
            segment_id=segment.id,
            segment_index=projection.segment_index,
            along_m=projection.along_m,
            fraction=projection.along_m / edge.distance_m,
        )

        splits = [forward.split]
        if reverse_split is not None:
            splits.append(reverse_split.split)
        return SnapResult(
            candidate=candidate,
            node_id=node_id,
            virtual=True,
            splits=tuple(splits),
            elevation_m=forward.elevation,
        )

    def nearest_node(
        self,
        coord: Coord,
        label: str = "point",
        role: Literal["origin", "destination"] | None = None,
    ) -> SnapCandidate | None:
        return self._nearest_node(
            (float(coord[0]), float(coord[1])), label, role
        )

    def nearest_edge(self, coord: Coord, label: str = "point"):
        return self._nearest_edge((float(coord[0]), float(coord[1])), label)

    # ------------------------------------------------------------- internos
    def _is_usable(self, edge: Edge) -> bool:
        if edge.distance_m <= 0.0:
            return False
        if (
            not self.options.allow_dismount
            and edge.bicycle_access is BicycleAccess.DISMOUNT
        ):
            return False
        return True

    def _nearest_node(
        self,
        point: Coord,
        label: str,
        role: Literal["origin", "destination"] | None,
    ) -> SnapCandidate | None:
        best: SnapCandidate | None = None
        for node_id in sorted(self._node_index.query(*point, self.options.max_distance_m), key=str):
            if role == "origin" and self._out_count.get(node_id, 0) == 0:
                continue
            if role == "destination" and self._in_count.get(node_id, 0) == 0:
                continue
            node = self.graph.get_node(node_id)
            distance = haversine_m(point, node.coord)
            if distance > self.options.max_distance_m:
                continue
            if best is None or distance < best.offset_m - 1e-9:
                best = SnapCandidate(
                    label=label,
                    kind="node",
                    point=node.coord,
                    offset_m=distance,
                    node_id=node_id,
                )
        return best

    def _nearest_edge(
        self, point: Coord, label: str
    ) -> tuple[Edge, _Projection] | None:
        best: tuple[Edge, _Projection] | None = None
        for edge_id in sorted(self._edge_index.query(*point, self.options.max_distance_m), key=str):
            edge = self._usable_edges[edge_id]
            projection = _project_edge(edge, point)
            if projection is None or projection.offset_m > self.options.max_distance_m:
                continue
            if best is None or projection.offset_m < best[1].offset_m - 1e-9:
                best = (edge, projection)
        return best

    def _endpoint_candidate(
        self, node_id: Hashable, point: Coord, label: str
    ) -> SnapCandidate:
        node = self.graph.get_node(node_id)
        return SnapCandidate(
            label=label,
            kind="node",
            point=node.coord,
            offset_m=haversine_m(point, node.coord),
            node_id=node_id,
        )

    def _endpoint_allowed(
        self,
        node_id: Hashable,
        role: Literal["origin", "destination"] | None,
    ) -> bool:
        if role == "origin":
            return self._out_count.get(node_id, 0) > 0
        if role == "destination":
            return self._in_count.get(node_id, 0) > 0
        return True

    @staticmethod
    def _clamp_projection(
        edge: Edge,
        projection: _Projection,
        along_m: float,
        point: Coord,
    ) -> _Projection:
        relocated = _locate_along(edge, along_m)
        if relocated is None:
            return projection
        return replace(
            relocated,
            offset_m=haversine_m(point, relocated.point),
        )

    def _unique_node_id(self, label: str) -> str:
        if label in {"origin", "destination"}:
            base = f"__{label}__"
        else:
            slug = "".join(
                character if character.isalnum() else "_"
                for character in label.strip().lower()
            ).strip("_")
            base = f"__snap_{slug or 'point'}__"

        candidate = base
        counter = 2
        while candidate in self.graph:
            candidate = f"{base[:-2]}_{counter}__"
            counter += 1
        return candidate

    def _find_reverse(self, edge: Edge) -> Edge | None:
        for candidate in self._reverse_candidates.get(
            (edge.target, edge.source), ()
        ):
            if candidate.id == edge.id:
                continue
            if not self._is_usable(candidate):
                continue
            if abs(candidate.distance_m - edge.distance_m) > max(
                0.5, 0.02 * edge.distance_m
            ):
                continue
            if _is_reverse_of(edge, candidate):
                return candidate
        return None


# --------------------------------------------------------------------------
# Grafo de consulta
# --------------------------------------------------------------------------
def build_query_graph(
    graph: CyclingGraph,
    origin: Coord,
    destination: Coord,
    options: SnapOptions | None = None,
) -> QueryGraph:
    """Conecta origem e destino e devolve o grafo temporario de consulta.

    O grafo permanente **nao** e alterado: cada ``snap`` trabalha sobre uma
    copia. O grafo de consulta carrega os ids de origem/destino e metadados do
    snapping (``graph.metadata["snapping"]``).

    Args:
        graph: Grafo ciclavel permanente.
        origin: Coordenada ``(lat, lon)`` de origem.
        destination: Coordenada ``(lat, lon)`` de destino.
        options: Parametros do snapping. Usa ``SnapOptions()`` se omitido.

    Returns:
        Um ``QueryGraph`` pronto para a busca.

    Raises:
        SnapError: Se origem ou destino nao puderem ser conectados a rede.

    Example:
        >>> query = build_query_graph(graph, (-23.5487, -46.6326), (-23.5485, -46.6308))
        >>> query.is_connected()
        True
    """
    options = options or SnapOptions()

    origin_result = SpatialSnapper(graph, options).snap(
        origin, label="origin", role="origin"
    )
    origin_graph = origin_result.apply(graph)

    destination_result = SpatialSnapper(origin_graph, options).snap(
        destination, label="destination", role="destination"
    )
    query_graph = destination_result.apply(origin_graph)
    query_graph.metadata["snapping"] = {
        "origin": origin_result.candidate.to_dict(),
        "destination": destination_result.candidate.to_dict(),
        "max_distance_m": options.max_distance_m,
        "node_preference_m": options.node_preference_m,
        "min_split_distance_m": options.min_split_distance_m,
    }

    virtual_nodes: set[Hashable] = set()
    if origin_result.virtual:
        virtual_nodes.add(origin_result.node_id)
    if destination_result.virtual:
        virtual_nodes.add(destination_result.node_id)

    return QueryGraph(
        graph=query_graph,
        origin_id=origin_result.node_id,
        destination_id=destination_result.node_id,
        origin=origin_result.candidate,
        destination=destination_result.candidate,
        virtual_nodes=frozenset(virtual_nodes),
    )


# --------------------------------------------------------------------------
# Projecao e divisao
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class _Projection:
    edge_id: str
    along_m: float
    offset_m: float
    point: Coord
    segment_index: int
    local_m: float
    vertex_index: int
    ratio: float


def _project_edge(edge: Edge, point: Coord) -> _Projection | None:
    best: _Projection | None = None
    segment_offset = 0.0

    for segment_index, segment in enumerate(edge.segments):
        geometry = segment.geometry
        if len(geometry) < 2:
            segment_offset += segment.distance_m
            continue

        cumulative = cumulative_distances(geometry)
        geometry_total = cumulative[-1]
        if geometry_total <= 0.0:
            segment_offset += segment.distance_m
            continue

        scale = segment.distance_m / geometry_total
        for vertex_index in range(len(geometry) - 1):
            ratio, projected, distance = _project_on_vertex_pair(
                point, geometry[vertex_index], geometry[vertex_index + 1]
            )
            local_geometry = cumulative[vertex_index] + ratio * (
                cumulative[vertex_index + 1] - cumulative[vertex_index]
            )
            local_m = local_geometry * scale
            along_m = segment_offset + local_m
            if best is None or distance < best.offset_m - 1e-9:
                best = _Projection(
                    edge_id=edge.id,
                    along_m=along_m,
                    offset_m=distance,
                    point=projected,
                    segment_index=segment_index,
                    local_m=local_m,
                    vertex_index=vertex_index,
                    ratio=ratio,
                )

        segment_offset += segment.distance_m

    return best


def _project_on_vertex_pair(
    point: Coord, start: Coord, end: Coord
) -> tuple[float, Coord, float]:
    """Projecao planar local de ``point`` no segmento ``start``-``end``."""
    kx = M_PER_DEG * math.cos(math.radians(point[0]))
    ky = M_PER_DEG

    ap_x = (point[1] - start[1]) * kx
    ap_y = (point[0] - start[0]) * ky
    ab_x = (end[1] - start[1]) * kx
    ab_y = (end[0] - start[0]) * ky

    denominator = ab_x * ab_x + ab_y * ab_y
    if denominator <= 0.0:
        ratio = 0.0
    else:
        ratio = (ap_x * ab_x + ap_y * ab_y) / denominator
        ratio = min(max(ratio, 0.0), 1.0)

    projected = (
        start[0] + (end[0] - start[0]) * ratio,
        start[1] + (end[1] - start[1]) * ratio,
    )
    return ratio, projected, haversine_m(point, projected)


def _locate_along(
    edge: Edge,
    along_m: float,
    point_override: Coord | None = None,
) -> _Projection | None:
    """Localiza um ponto a ``along_m`` do inicio da aresta."""
    total = edge.distance_m
    if total <= 0.0:
        return None
    along_m = min(max(along_m, 0.0), total)

    segment_offset = 0.0
    for segment_index, segment in enumerate(edge.segments):
        end = segment_offset + segment.distance_m
        if along_m <= end + 1e-9 or segment_index == len(edge.segments) - 1:
            local_m = min(max(along_m - segment_offset, 0.0), segment.distance_m)
            geometry = segment.geometry
            if len(geometry) < 2:
                point = point_override or (
                    geometry[0] if geometry else (0.0, 0.0)
                )
                return _Projection(
                    edge_id=edge.id,
                    along_m=along_m,
                    offset_m=0.0,
                    point=point,
                    segment_index=segment_index,
                    local_m=local_m,
                    vertex_index=0,
                    ratio=0.0,
                )

            cumulative = cumulative_distances(geometry)
            geometry_total = cumulative[-1]
            if geometry_total <= 0.0 or segment.distance_m <= 0.0:
                point = point_override or geometry[0]
                return _Projection(
                    edge_id=edge.id,
                    along_m=along_m,
                    offset_m=0.0,
                    point=point,
                    segment_index=segment_index,
                    local_m=local_m,
                    vertex_index=0,
                    ratio=0.0,
                )

            target = min(
                max(local_m * (geometry_total / segment.distance_m), 0.0),
                geometry_total,
            )
            vertex_index = _vertex_index(cumulative, target)
            start_d = cumulative[vertex_index]
            end_d = cumulative[vertex_index + 1]
            ratio = (
                0.0
                if end_d <= start_d
                else (target - start_d) / (end_d - start_d)
            )
            point = point_override or interpolate_along(
                geometry, cumulative, target
            )
            return _Projection(
                edge_id=edge.id,
                along_m=along_m,
                offset_m=0.0,
                point=point,
                segment_index=segment_index,
                local_m=local_m,
                vertex_index=vertex_index,
                ratio=ratio,
            )

        segment_offset = end

    return None


def _vertex_index(cumulative: Sequence[float], target: float) -> int:
    index = 0
    for current in range(len(cumulative) - 1):
        if cumulative[current] <= target <= cumulative[current + 1]:
            index = current
            break
        if target > cumulative[current]:
            index = current
    return max(0, min(index, len(cumulative) - 2))


@dataclass(frozen=True)
class _SplitOutcome:
    split: _EdgeSplit
    elevation: float | None


def _split_from_projection(
    edge: Edge,
    projection: _Projection,
    node_id: Hashable,
    label: str,
) -> _SplitOutcome:
    segment_index = projection.segment_index
    segment = edge.segments[segment_index]
    local = projection.local_m
    epsilon = 1e-6

    if local <= epsilon:
        head_segments = edge.segments[:segment_index]
        tail_segments = edge.segments[segment_index:]
        elevation = _boundary_elevation(head_segments, tail_segments)
    elif local >= segment.distance_m - epsilon:
        head_segments = edge.segments[: segment_index + 1]
        tail_segments = edge.segments[segment_index + 1 :]
        elevation = _boundary_elevation(head_segments, tail_segments)
    else:
        head_segment, tail_segment, elevation = _split_segment(
            segment, projection, label
        )
        head_segments = edge.segments[:segment_index] + (head_segment,)
        tail_segments = (tail_segment,) + edge.segments[segment_index + 1 :]

    if not head_segments or not tail_segments:
        raise SnapError(
            f"aresta {edge.id!r}: divisao produziria trecho vazio "
            f"(a {local:.3f} m do segmento)"
        )

    head = Edge(
        id=f"{edge.id}:h",
        source=edge.source,
        target=node_id,
        segments=head_segments,
        geometry=_concat_geometry(head_segments),
    )
    tail = Edge(
        id=f"{edge.id}:t",
        source=node_id,
        target=edge.target,
        segments=tail_segments,
        geometry=_concat_geometry(tail_segments),
    )
    return _SplitOutcome(_EdgeSplit(edge.id, head, tail), elevation)


def _split_segment(
    segment: EdgeSegment,
    projection: _Projection,
    label: str,
) -> tuple[EdgeSegment, EdgeSegment, float | None]:
    local = projection.local_m
    tail_distance = segment.distance_m - local

    head_geometry, tail_geometry = _split_geometry(
        segment.geometry, projection.vertex_index, projection.point
    )

    head_profile, tail_profile, split_elevation = _split_profile(
        segment.elevation_profile, local, segment.distance_m
    )

    if segment.elevation_profile:
        head_gain, head_loss = _profile_gain_loss(head_profile)
        # Conserva exatamente o total original (o perfil pode ter arredondado).
        head_gain = min(head_gain, segment.elevation_gain_m)
        head_loss = min(head_loss, segment.elevation_loss_m)
        tail_gain = max(0.0, segment.elevation_gain_m - head_gain)
        tail_loss = max(0.0, segment.elevation_loss_m - head_loss)
        head_min, head_max = _profile_extremes(head_profile)
        tail_min, tail_max = _profile_extremes(tail_profile)
    else:
        ratio = local / segment.distance_m if segment.distance_m else 0.0
        head_gain = segment.elevation_gain_m * ratio
        head_loss = segment.elevation_loss_m * ratio
        tail_gain = segment.elevation_gain_m - head_gain
        tail_loss = segment.elevation_loss_m - head_loss
        head_min = head_max = tail_min = tail_max = None

    suffix = f"@{label}"
    head = replace(
        segment,
        id=f"{segment.id}{suffix}:a",
        distance_m=round(local, 6),
        elevation_gain_m=round(head_gain, 6),
        elevation_loss_m=round(head_loss, 6),
        min_elevation_m=head_min,
        max_elevation_m=head_max,
        elevation_profile=head_profile,
        geometry=head_geometry,
    )
    tail = replace(
        segment,
        id=f"{segment.id}{suffix}:b",
        distance_m=round(tail_distance, 6),
        elevation_gain_m=round(tail_gain, 6),
        elevation_loss_m=round(tail_loss, 6),
        min_elevation_m=tail_min,
        max_elevation_m=tail_max,
        elevation_profile=tail_profile,
        geometry=tail_geometry,
    )
    return head, tail, split_elevation


def _split_geometry(
    geometry: Sequence[Coord],
    vertex_index: int,
    point: Coord,
) -> tuple[tuple[Coord, ...], tuple[Coord, ...]]:
    if len(geometry) < 2:
        if geometry:
            return (geometry[0], point), (point, geometry[-1])
        return (point,), (point,)

    vertex_index = max(0, min(vertex_index, len(geometry) - 2))
    head = _dedupe((*geometry[: vertex_index + 1], point))
    tail = _dedupe((point, *geometry[vertex_index + 1 :]))
    return head, tail


def _split_profile(
    profile: Sequence[ElevationSample],
    local_m: float,
    total_m: float,
) -> tuple[tuple[ElevationSample, ...], tuple[ElevationSample, ...], float | None]:
    if not profile:
        return (), (), None

    local_m = min(max(local_m, 0.0), total_m)
    left: ElevationSample | None = None
    right: ElevationSample | None = None
    for sample in profile:
        if sample.distance_m <= local_m + 1e-9:
            left = sample
        if sample.distance_m >= local_m - 1e-9 and right is None:
            right = sample

    if left is None:
        split_elevation = right.elevation_m if right is not None else profile[0].elevation_m
    elif right is None:
        split_elevation = left.elevation_m
    elif abs(right.distance_m - left.distance_m) <= 1e-12:
        split_elevation = left.elevation_m
    else:
        ratio = (local_m - left.distance_m) / (right.distance_m - left.distance_m)
        split_elevation = left.elevation_m + ratio * (
            right.elevation_m - left.elevation_m
        )

    source = (
        left.source
        if left is not None and left.source
        else (right.source if right is not None else "")
    )
    resolution = (
        left.resolution_m
        if left is not None and left.resolution_m is not None
        else (right.resolution_m if right is not None else None)
    )

    split_sample = ElevationSample(
        distance_m=local_m,
        elevation_m=split_elevation,
        source=source,
        resolution_m=resolution,
    )

    head = [sample for sample in profile if sample.distance_m < local_m - 1e-9]
    head.append(split_sample)

    tail = [
        ElevationSample(
            distance_m=sample.distance_m - local_m,
            elevation_m=sample.elevation_m,
            source=sample.source,
            resolution_m=sample.resolution_m,
        )
        for sample in profile
        if sample.distance_m > local_m + 1e-9
    ]
    tail.insert(
        0,
        ElevationSample(
            distance_m=0.0,
            elevation_m=split_elevation,
            source=source,
            resolution_m=resolution,
        ),
    )

    return tuple(head), tuple(tail), split_elevation


def _profile_gain_loss(
    profile: Sequence[ElevationSample],
) -> tuple[float, float]:
    gain = 0.0
    loss = 0.0
    for previous, current in zip(profile, profile[1:]):
        delta = current.elevation_m - previous.elevation_m
        if delta > 0:
            gain += delta
        else:
            loss -= delta
    return gain, loss


def _profile_extremes(
    profile: Sequence[ElevationSample],
) -> tuple[float | None, float | None]:
    if not profile:
        return None, None
    values = [sample.elevation_m for sample in profile]
    return min(values), max(values)


def _boundary_elevation(
    head_segments: Sequence[EdgeSegment],
    tail_segments: Sequence[EdgeSegment],
) -> float | None:
    for segment in reversed(head_segments):
        if segment.elevation_profile:
            return segment.elevation_profile[-1].elevation_m
    for segment in tail_segments:
        if segment.elevation_profile:
            return segment.elevation_profile[0].elevation_m
    return None


def _concat_geometry(segments: Sequence[EdgeSegment]) -> tuple[Coord, ...]:
    points: list[Coord] = []
    for segment in segments:
        for point in segment.geometry:
            if points and points[-1] == point:
                continue
            points.append(point)
    return tuple(points)


def _dedupe(points: Sequence[Coord]) -> tuple[Coord, ...]:
    deduped: list[Coord] = []
    for point in points:
        if deduped and deduped[-1] == point:
            continue
        deduped.append(point)
    return tuple(deduped)


def _node_result(candidate: SnapCandidate) -> SnapResult:
    if candidate.node_id is None:
        raise SnapError(f"{candidate.label}: candidato de no sem node_id")
    return SnapResult(
        candidate=candidate,
        node_id=candidate.node_id,
        virtual=False,
        splits=(),
        elevation_m=None,
    )


# --------------------------------------------------------------------------
# Utilidades espaciais
# --------------------------------------------------------------------------
class _GridIndex:
    """Grade uniforme em metros aproximados para consultas por raio."""

    def __init__(self, cell_size_m: float, reference_lat: float) -> None:
        self.cell_size_m = max(1.0, float(cell_size_m))
        self._kx = M_PER_DEG * max(0.01, math.cos(math.radians(reference_lat)))
        self._ky = M_PER_DEG
        self._cells: dict[tuple[int, int], list[Hashable]] = defaultdict(list)

    def _key(self, lat: float, lon: float) -> tuple[int, int]:
        x = math.floor(lon * self._kx / self.cell_size_m)
        y = math.floor(lat * self._ky / self.cell_size_m)
        return int(x), int(y)

    def add_point(self, item_id: Hashable, lat: float, lon: float) -> None:
        self.add_box(item_id, (lat, lon, lat, lon))

    def add_box(
        self,
        item_id: Hashable,
        bbox: tuple[float, float, float, float],
    ) -> None:
        south, west, north, east = bbox
        x0, y0 = self._key(south, west)
        x1, y1 = self._key(north, east)
        for x in range(min(x0, x1), max(x0, x1) + 1):
            for y in range(min(y0, y1), max(y0, y1) + 1):
                self._cells[(x, y)].append(item_id)

    def query(self, lat: float, lon: float, radius_m: float) -> set[Hashable]:
        if radius_m <= 0.0:
            radius_m = 0.0
        latitude_delta = radius_m / self._ky
        longitude_delta = radius_m / self._kx
        x0, y0 = self._key(lat - latitude_delta, lon - longitude_delta)
        x1, y1 = self._key(lat + latitude_delta, lon + longitude_delta)

        found: set[Hashable] = set()
        for x in range(min(x0, x1), max(x0, x1) + 1):
            for y in range(min(y0, y1), max(y0, y1) + 1):
                found.update(self._cells.get((x, y), ()))
        return found


def _reference_latitude(graph: CyclingGraph) -> float:
    latitudes = [node.lat for node in graph.nodes.values()]
    if not latitudes:
        return 0.0
    return (min(latitudes) + max(latitudes)) / 2.0


def _edge_bbox(
    edge: Edge, graph: CyclingGraph
) -> tuple[float, float, float, float]:
    points = list(edge.geometry)
    if not points:
        points = [
            point for segment in edge.segments for point in segment.geometry
        ]
    if not points:
        source = graph.get_node(edge.source)
        target = graph.get_node(edge.target)
        return (
            min(source.lat, target.lat),
            min(source.lon, target.lon),
            max(source.lat, target.lat),
            max(source.lon, target.lon),
        )
    latitudes = [point[0] for point in points]
    longitudes = [point[1] for point in points]
    return (
        min(latitudes),
        min(longitudes),
        max(latitudes),
        max(longitudes),
    )


def _is_reverse_of(edge: Edge, candidate: Edge) -> bool:
    expected = [f"{segment.id}:rev" for segment in reversed(edge.segments)]
    if [segment.id for segment in candidate.segments] == expected:
        return True

    if len(edge.geometry) != len(candidate.geometry) or not edge.geometry:
        return False
    for point, other in zip(edge.geometry, reversed(candidate.geometry)):
        if haversine_m(point, other) > 0.5:
            return False
    return True


def _reachable(graph: CyclingGraph, start: Hashable, goal: Hashable) -> bool:
    if start not in graph or goal not in graph:
        return False
    if start == goal:
        return True

    visited = {start}
    stack = [start]
    while stack:
        node_id = stack.pop()
        for edge in graph.out_edges(node_id):
            if edge.target == goal:
                return True
            if edge.target not in visited:
                visited.add(edge.target)
                stack.append(edge.target)
    return False
