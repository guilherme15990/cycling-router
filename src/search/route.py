"""Rota reconstruida: sequencia de arestas direcionadas + metricas finais.

Etapa **posterior** a busca. Uma ``Route`` e apenas um dado: a busca entrega a
fronteira Pareto de destino e a reconstrucao transforma cada label em uma rota
com metricas finais. A rota nao conhece a fila A* nem recalcula fisica.

``edge_ids`` preserva a **direcao**: uma rua percorrida em sentidos opostos gera
arestas diferentes. ``edge_lengths`` e paralelo a ``edge_ids`` e guarda o
comprimento de cada aresta, derivado das diferencas de ``distance_m`` na cadeia
de ``parent`` — e o insumo da metrica de distancia compartilhada.
"""

from __future__ import annotations

from dataclasses import dataclass

from .astar import SearchResult
from .state import SearchState, route_edges


@dataclass(frozen=True, slots=True)
class Route:
    """Rota reconstruida: arestas direcionadas, comprimentos e metricas.

    ``edge_lengths`` e paralelo a ``edge_ids`` (mesmo comprimento quando
    disponivel). Quando ausente, as metricas de diversidade caem para contagem
    de arestas.
    """

    edge_ids: tuple[str | None, ...]
    time_s: float
    distance_m: float
    ascent_m: float
    descent_m: float
    energy_j: float
    label_id: int = 0
    edge_lengths: tuple[float, ...] = ()

    @property
    def edge_set(self) -> frozenset[str | None]:
        return frozenset(self.edge_ids)

    @property
    def edge_count(self) -> int:
        return len(self.edge_ids)

    @property
    def edge_length_map(self) -> dict[str | None, float]:
        """Comprimento total por aresta (soma arestas repetidas).

        Usada pela metrica de distancia compartilhada. Arestas sem comprimento
        conhecido entram com ``0.0`` e a metrica recai para contagem.
        """
        lengths = self.edge_lengths
        mapping: dict[str | None, float] = {}
        for index, edge_id in enumerate(self.edge_ids):
            length = float(lengths[index]) if index < len(lengths) else 0.0
            mapping[edge_id] = mapping.get(edge_id, 0.0) + length
        return mapping

    def to_dict(self) -> dict[str, object]:
        return {
            "label_id": self.label_id,
            "edges": list(self.edge_ids),
            "edge_count": self.edge_count,
            "time_s": round(self.time_s, 3),
            "distance_m": round(self.distance_m, 3),
            "ascent_m": round(self.ascent_m, 3),
            "descent_m": round(self.descent_m, 3),
            "energy_j": round(self.energy_j, 3),
        }


def route_edge_lengths(state: SearchState) -> list[float]:
    """Comprimento de cada aresta da rota (diferencas de ``distance_m``).

    Paralelo a ``route_edges``: o custo da aresta de entrada de uma label e a
    diferenca entre a distancia acumulada dela e a do ``parent``.
    """
    lengths: list[float] = []
    node: SearchState | None = state
    while node is not None and node.parent is not None:
        lengths.append(node.distance_m - node.parent.distance_m)
        node = node.parent
    lengths.reverse()
    return lengths


def route_from_state(state: SearchState) -> Route:
    """Reconstroi uma ``Route`` de uma label de destino."""
    return Route(
        edge_ids=tuple(route_edges(state)),
        time_s=state.time_s,
        distance_m=state.distance_m,
        ascent_m=state.ascent_m,
        descent_m=state.descent_m,
        energy_j=state.energy_j,
        label_id=state.label_id,
        edge_lengths=tuple(route_edge_lengths(state)),
    )


def routes_from_result(result: SearchResult) -> tuple[Route, ...]:
    """Converte a fronteira de destino de um ``SearchResult`` em rotas."""
    return tuple(route_from_state(label) for label in result.labels)
