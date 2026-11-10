"""Ponte entre a GUI e a engine ``roteamento``.

Concentra tudo que depende do pacote principal: carregar o grafo, montar o
modelo fisico, snapping de origem/destino e chamar ``search_profile``. A GUI
so conhece as estruturas simplificadas definidas aqui (``GuiRoute`` e
``RouteComputation``).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from geo import Coord
from graph.model import CyclingGraph
from graph.serialize import load_json
from physical import (
    BicycleModel,
    CyclistModel,
    Environment,
    PhysicalTraversal,
)
from search import (
    CandidateMetrics,
    PhysicalTraversalModel,
    ProfileSearchRequest,
    ProfileSearchResponse,
    route_profile_for,
    search_profile,
)
from snapping import QueryGraph, SnapOptions, build_query_graph


@dataclass(frozen=True)
class EngineSettings:
    """Parametros fisicos editaveis na GUI."""

    cyclist_mass_kg: float = 75.0
    max_power_w: float = 400.0
    sustainable_power_w: float = 200.0
    frontal_area_m2: float = 0.5
    bicycle_mass_kg: float = 12.0
    #: Teto global de seguranca (m/s). ``None`` = ilimitado (fisica e heuristica
    #: acompanham: a heuristica de tempo cai para 0, sempre admissivel).
    safe_max_speed_mps: float | None = 22.0


@dataclass(frozen=True)
class GuiRoute:
    """Rota pronta para desenhar: identidade, geometria e metricas finais."""

    route_id: str
    rank: int
    coords: tuple[Coord, ...]  # (lat, lon)
    metrics: CandidateMetrics
    headline: str = ""
    details: tuple[str, ...] = ()
    tradeoffs: tuple[str, ...] = ()
    #: Energia eletrica estimada (Wh). ``None`` fora do perfil eletrico.
    energy_wh: float | None = None
    #: Mensagem de viabilidade de bateria, quando ha bateria configurada.
    battery_note: str | None = None

    def summary(self) -> str:
        line = (
            f"{self.route_id}  |  {self.metrics.time_s:6.1f} s  "
            f"{self.metrics.distance_m / 1000.0:5.2f} km  "
            f"subida {self.metrics.ascent_m:5.1f} m"
        )
        if self.energy_wh is not None:
            line += f"  ~{self.energy_wh:5.1f} Wh"
        return line


@dataclass(frozen=True)
class RouteComputation:
    """Resultado completo de uma busca, no vocabulario da GUI."""

    query: QueryGraph
    response: ProfileSearchResponse
    routes: tuple[GuiRoute, ...]
    elapsed_s: float = 0.0
    profile_title: str = ""

    @property
    def reached(self) -> bool:
        return self.response.reached

    @property
    def origin_point(self) -> Coord:
        return self.query.origin.point

    @property
    def destination_point(self) -> Coord:
        return self.query.destination.point

    def status(self) -> str:
        if not self.reached:
            return (
                "Destino inalcancavel com este grafo/perfil "
                f"(componentes desconexas?). Pareto de destino: "
                f"{self.response.pareto_route_count}."
            )
        return (
            f"{len(self.routes)} rota(s) selecionada(s) de "
            f"{self.response.pareto_route_count} na fronteira Pareto "
            f"({self.elapsed_s * 1000:.0f} ms)."
        )


# --------------------------------------------------------------------------
# Grafos
# --------------------------------------------------------------------------
def load_graph(path: str | Path) -> CyclingGraph:
    return load_json(path)


def graph_bounds(graph: CyclingGraph) -> tuple[float, float, float, float]:
    """bbox ``(south, west, north, east)`` do grafo."""
    nodes = list(graph.nodes.values())
    lats = [node.lat for node in nodes]
    lons = [node.lon for node in nodes]
    return min(lats), min(lons), max(lats), max(lons)


def graph_center(graph: CyclingGraph) -> Coord:
    south, west, north, east = graph_bounds(graph)
    return (south + north) / 2.0, (west + east) / 2.0


# --------------------------------------------------------------------------
# Modelo fisico
# --------------------------------------------------------------------------
def build_traversal(settings: EngineSettings) -> PhysicalTraversalModel:
    cyclist = CyclistModel(
        mass_kg=settings.cyclist_mass_kg,
        max_power_w=settings.max_power_w,
        sustainable_power_w=settings.sustainable_power_w,
        frontal_area_m2=settings.frontal_area_m2,
    )
    bicycle = BicycleModel(mass_kg=settings.bicycle_mass_kg)
    environment = Environment(safe_max_speed_mps=settings.safe_max_speed_mps)
    return PhysicalTraversalModel(
        PhysicalTraversal(step_m=5.0), cyclist, bicycle, environment
    )


# --------------------------------------------------------------------------
# Engine
# --------------------------------------------------------------------------
class RoutingEngine:
    """Executa o pipeline completo (snapping -> busca -> selecao)."""

    def __init__(
        self, graph: CyclingGraph, snap_options: SnapOptions | None = None
    ) -> None:
        self.graph = graph
        self.snap_options = snap_options or SnapOptions()
        self._traversals: dict[tuple, PhysicalTraversalModel] = {}

    def traversal(self, settings: EngineSettings) -> PhysicalTraversalModel:
        key = (
            settings.cyclist_mass_kg,
            settings.max_power_w,
            settings.sustainable_power_w,
            settings.frontal_area_m2,
            settings.bicycle_mass_kg,
            settings.safe_max_speed_mps,
        )
        traversal = self._traversals.get(key)
        if traversal is None:
            traversal = build_traversal(settings)
            self._traversals[key] = traversal
        return traversal

    def route(
        self,
        origin: Coord,
        destination: Coord,
        *,
        profile_id: str = "fastest",
        max_routes: int = 3,
        initial_speed_mps: float = 0.0,
        settings: EngineSettings | None = None,
    ) -> RouteComputation:
        settings = settings or EngineSettings()
        profile = route_profile_for(profile_id)

        query = build_query_graph(
            self.graph, origin, destination, self.snap_options
        )
        traversal = self.traversal(settings)

        request = ProfileSearchRequest(
            origin=query.origin_id,
            destination=query.destination_id,
            profile=profile,
            max_routes=max_routes,
            initial_speed_mps=initial_speed_mps,
        )

        started = time.perf_counter()
        response = search_profile(query.graph, traversal, request)
        elapsed = time.perf_counter() - started

        routes = _build_gui_routes(query.graph, response)
        return RouteComputation(
            query=query,
            response=response,
            routes=routes,
            elapsed_s=elapsed,
            profile_title=profile.title or profile.id,
        )


# --------------------------------------------------------------------------
# Reconstrucao de geometria
# --------------------------------------------------------------------------
def _edge_geometry(graph: CyclingGraph, edge_id: str | None) -> tuple[Coord, ...]:
    if edge_id is None:
        return ()
    try:
        edge = graph.get_edge(edge_id)
    except Exception:
        return ()
    if edge.geometry:
        return edge.geometry
    source = graph.get_node(edge.source)
    target = graph.get_node(edge.target)
    return (source.coord, target.coord)


def route_coords(graph: CyclingGraph, edge_ids) -> tuple[Coord, ...]:
    """Concatena a geometria das arestas, removendo pontos repetidos."""
    coords: list[Coord] = []
    for edge_id in edge_ids:
        for point in _edge_geometry(graph, edge_id):
            if coords and coords[-1] == point:
                continue
            coords.append(point)
    return tuple(coords)


def _build_gui_routes(
    graph: CyclingGraph, response: ProfileSearchResponse
) -> tuple[GuiRoute, ...]:
    explanations = response.explanations
    estimates = response.energy
    routes: list[GuiRoute] = []
    for index, selected in enumerate(response.routes):
        explanation = explanations[index] if index < len(explanations) else None
        estimate = estimates[index] if index < len(estimates) else None
        battery_note = None
        if estimate is not None and estimate.battery is not None:
            battery_note = estimate.battery.message()
        routes.append(
            GuiRoute(
                route_id=selected.route_id,
                rank=selected.rank,
                coords=route_coords(graph, selected.route.edge_ids),
                metrics=selected.metrics,
                headline=explanation.headline if explanation else "",
                details=tuple(explanation.details) if explanation else (),
                tradeoffs=tuple(explanation.tradeoffs) if explanation else (),
                energy_wh=(
                    None
                    if estimate is None
                    else estimate.electrical_energy_wh
                ),
                battery_note=battery_note,
            )
        )
    return tuple(routes)
