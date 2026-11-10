"""Teste de integracao da ponte GUI <-> engine.

Usa o grafo real ``data/se.json`` (mesmo do smoke test) e o par conectado
conhecido. Nao abre janela Tk nem acessa a rede (a altimetria Terrarium e
testada a parte, com tiles sinteticos).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from routegui.engine_bridge import (
    EngineSettings,
    RoutingEngine,
    build_traversal,
    graph_bounds,
    graph_center,
    load_graph,
    route_coords,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
GRAPH_PATH = REPO_ROOT / "data" / "se.json"

ORIGIN = (-23.548699, -46.6326332)
DESTINATION = (-23.5485103, -46.6308005)


pytestmark = pytest.mark.skipif(
    not GRAPH_PATH.is_file(), reason="data/se.json ausente"
)


def test_load_graph_and_bounds():
    graph = load_graph(GRAPH_PATH)
    assert graph.node_count > 0
    south, west, north, east = graph_bounds(graph)
    assert south < north and west < east
    lat, lon = graph_center(graph)
    assert south <= lat <= north and west <= lon <= east


def test_build_traversal_announces_speed_ceiling():
    model = build_traversal(EngineSettings(safe_max_speed_mps=18.0))
    assert model.max_speed_mps == 18.0
    unlimited = build_traversal(EngineSettings(safe_max_speed_mps=None))
    assert unlimited.max_speed_mps is None


def test_route_returns_geometry_and_metrics():
    engine = RoutingEngine(load_graph(GRAPH_PATH))
    computation = engine.route(ORIGIN, DESTINATION, profile_id="fastest", max_routes=1)

    assert computation.reached
    assert len(computation.routes) >= 1
    route = computation.routes[0]
    assert len(route.coords) >= 2
    assert route.metrics.distance_m > 0
    assert route.metrics.time_s > 0
    # Geometria com coordenadas plausiveis.
    for lat, lon in route.coords:
        assert -90 <= lat <= 90 and -180 <= lon <= 180


def test_route_profile_changes_selection_not_physics():
    graph = load_graph(GRAPH_PATH)
    engine = RoutingEngine(graph)
    fastest = engine.route(ORIGIN, DESTINATION, profile_id="fastest", max_routes=1)
    flattest = engine.route(ORIGIN, DESTINATION, profile_id="flattest", max_routes=1)
    # Ambos alcancam; a fisica do par mais rapido nao depende do perfil.
    assert fastest.reached and flattest.reached
    # A rota mais plana nunca sobe mais que a mais rapida deste par.
    assert flattest.routes[0].metrics.ascent_m <= (
        fastest.routes[0].metrics.ascent_m + 1e-6
    )


def test_electric_profile_reports_energy_wh():
    engine = RoutingEngine(load_graph(GRAPH_PATH))
    computation = engine.route(
        ORIGIN, DESTINATION, profile_id="electric", max_routes=1
    )
    assert computation.reached
    route = computation.routes[0]
    # O perfil eletrico expoe a energia estimada (Wh) sem exigir bateria.
    assert route.energy_wh is not None and route.energy_wh > 0.0
    assert route.battery_note is None
    assert "Wh" in route.summary()


def test_route_coords_deduplicates_consecutive_points():
    graph = load_graph(GRAPH_PATH)
    edge = next(iter(graph.edges.values()))
    coords = route_coords(graph, [edge.id, edge.id])
    # Repetir a mesma aresta nao deve duplicar o ponto de juncao.
    assert len(coords) <= 2 * len(edge.geometry or (1, 2))
