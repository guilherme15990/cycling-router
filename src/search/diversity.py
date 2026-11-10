"""Metricas de diversidade entre rotas.

A diversidade e uma preferencia de **apresentacao**, nao um objetivo fisico da
rota: ela evita encher a lista de alternativas quase iguais. Duas metricas:

* ``EDGE_JACCARD``: ``|E_A intersecao E_B| / |E_A uniao E_B|`` sobre as arestas
  **direcionadas** do caminho. Simples, mas sensivel a pequenas diferencas de
  grafo (duas rotas visualmente iguais podem usar arestas diferentes).
* ``SHARED_DISTANCE_RATIO``: ``D_shared(A,B) / min(D_A, D_B)`` — responde "quanto
  da rota mais curta ja esta presente na outra". E a metrica principal do MVP e
  usa os comprimentos por aresta (``Route.edge_length_map``); quando faltam
  comprimentos, recai para contagem de arestas.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .profiles import DiversityMetric
from .route import Route


def edge_jaccard(a: Route, b: Route) -> float:
    """Similaridade de Jaccard sobre as arestas direcionadas.

    Duas rotas iguais dao ``1.0``; sem aresta em comum dao ``0.0``.
    """
    edges_a = a.edge_set
    edges_b = b.edge_set
    if not edges_a and not edges_b:
        return 1.0
    union = edges_a | edges_b
    if not union:
        return 0.0
    return len(edges_a & edges_b) / len(union)


def shared_distance_ratio(a: Route, b: Route) -> float:
    """Proporcao de distancia compartilhada, em ``[0, 1]``.

    ``R(A,B) = D_shared(A,B) / min(D_A, D_B)``. ``D_shared`` soma, por aresta
    compartilhada, o menor comprimento entre as duas rotas. Quando os
    comprimentos nao estao disponiveis, usa a razao de arestas compartilhadas
    sobre ``min(|A|, |B|)``.
    """
    shared_ids = a.edge_set & b.edge_set
    if not shared_ids:
        return 0.0

    lengths_a = a.edge_length_map
    lengths_b = b.edge_length_map
    shared_distance = sum(
        min(lengths_a.get(edge_id, 0.0), lengths_b.get(edge_id, 0.0))
        for edge_id in shared_ids
    )
    scale = min(a.distance_m, b.distance_m)
    if shared_distance > 0.0 and scale > 0.0:
        return min(1.0, shared_distance / scale)

    # Sem comprimentos confiaveis: recai para contagem de arestas.
    denominator = min(a.edge_count, b.edge_count)
    if denominator <= 0:
        return 0.0
    return len(shared_ids) / denominator


def route_diversity(
    a: Route, b: Route, metric: DiversityMetric
) -> float:
    """Semelhanca entre ``a`` e ``b`` segundo ``metric`` (0 = distintas)."""
    if metric is DiversityMetric.EDGE_JACCARD:
        return edge_jaccard(a, b)
    if metric is DiversityMetric.SHARED_DISTANCE_RATIO:
        return shared_distance_ratio(a, b)
    raise ValueError(f"metrica de diversidade desconhecida: {metric!r}")


def is_too_similar(
    a: Route, b: Route, metric: DiversityMetric, threshold: float
) -> bool:
    """True quando a semelhanca excede ``threshold``."""
    return route_diversity(a, b, metric) > threshold


# Nome historico mantido: similaridade padrao do projeto e o Jaccard de arestas.
def route_similarity(a: Route, b: Route) -> float:
    """Alias de ``edge_jaccard`` (compatibilidade com a API anterior)."""
    return edge_jaccard(a, b)


@dataclass(frozen=True, slots=True)
class RouteDiversity:
    """Componente de diversidade: metrica + limiar configurados juntos.

    Reune o que o ``RouteSelector`` precisa consultar para decidir se uma
    candidata e alternativa suficiente ou apenas uma variacao de outra.
    """

    metric: DiversityMetric = DiversityMetric.SHARED_DISTANCE_RATIO
    threshold: float = 0.7

    def __post_init__(self) -> None:
        threshold = float(self.threshold)
        if not math.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
            raise ValueError(
                "threshold deve estar em [0, 1] "
                f"(recebido {threshold!r})"
            )
        object.__setattr__(self, "threshold", threshold)

    def similarity(self, a: Route, b: Route) -> float:
        return route_diversity(a, b, self.metric)

    def is_too_similar(
        self, a: Route, b: Route, threshold: float | None = None
    ) -> bool:
        limit = self.threshold if threshold is None else threshold
        return self.similarity(a, b) > limit

    def to_dict(self) -> dict[str, object]:
        return {"metric": self.metric.value, "threshold": self.threshold}
