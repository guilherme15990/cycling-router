"""Camada de busca multiobjetivo (MOA*) e selecao por perfil.

A busca A* multiobjetivo integra estado, dominancia, fronteira e fila:

* ``ObjectiveSet`` / ``Objective`` / ``SearchProfile`` e objetivos por perfil;
* dominancia de Pareto com discretizacao de velocidade (``SpeedBucketDominance``);
* ``PhysicalState`` / ``SearchState`` (metricas acumuladas + estado fisico);
* ``ParetoFrontier``, ``FrontierMap`` e ``FrontierManager``;
* ``Heuristic`` (limites inferiores admissiveis) e ``SearchConfig``;
* ``LexicographicQueue`` (fila de prioridade por perfil);
* ``TraversalModel`` / ``PhysicalTraversalModel`` (adaptador do modelo fisico);
* ``MultiObjectiveAStar`` / ``SearchResult`` (fronteira completa de destino).

A **selecao por perfil** e uma camada independente, posterior a busca:

* ``RouteProfile`` e configuracao declarativa (``profiles.py``);
* ``Route`` / reconstrucao (``route.py``) e ``ObjectiveEvaluator``
  (``evaluator.py``);
* diversidade por ``edge_jaccard`` / ``shared_distance_ratio`` (``diversity.py``);
* ranking lexicografico com tolerancia e score normalizado (``ranking.py``);
* selecao das N rotas com fallback (``selection.py``);
* explicacao comparando com as candidatas reais (``explanation.py``);
* contrato busca<->selecao (``pipeline.py``).

O modelo fisico continua sendo a unica fonte de tempo e energia: esta camada
apenas acumula metricas e mantem alternativas nao dominadas. O perfil **nao**
altera a fisica.
"""

from .astar import (
    MultiObjectiveAStar,
    SearchResult,
    edge_ids_of,
    is_feasible,
    model_max_speed,
    order_labels,
)
from .candidates import (
    CandidateMetrics,
    DeduplicationMode,
    RouteCandidate,
    RouteCandidatePool,
    RouteDeduplicator,
)
from .config import SearchConfig
from .diversity import (
    RouteDiversity,
    edge_jaccard,
    is_too_similar,
    route_diversity,
    route_similarity,
    shared_distance_ratio,
)
from .dominance import (
    DEFAULT_SPEED_STEP_MPS,
    Dominance,
    SpeedBucketDominance,
    speed_bucket,
)
from .energy import (
    RouteEnergyEstimate,
    estimate_route_energy,
    estimate_routes_energy,
)
from .evaluator import (
    MetricSource,
    ObjectiveEvaluator,
    ObjectiveValues,
    RouteObjectiveEvaluator,
    evaluate,
    evaluate_metrics,
    evaluate_route,
    objective_value,
)
from .explanation import RouteExplanation, RouteExplainer, explain_route
from .frontier import FrontierManager, FrontierMap, ParetoFrontier
from .heuristic import (
    DEFAULT_MAX_SPEED_MPS,
    SUPPORTED_OBJECTIVES,
    Heuristic,
    HeuristicBounds,
)
from .objectives import (
    PROFILE_NAMES,
    PROFILE_OBJECTIVES,
    PROFILES,
    Objective,
    ObjectiveSet,
    SearchProfile,
    dominates,
    epsilon_dominates,
    objectives_for,
    profile_for,
)
from .pipeline import (
    ProfileSearchRequest,
    ProfileSearchResponse,
    SelectionMetadata,
    search_profile,
)
from .profiles import (
    PROFILE_CONFIG,
    PROFILE_IDS,
    BalancedWeights,
    DiversityConfig,
    DiversityFallback,
    DiversityMetric,
    DiversityRelaxation,
    RankingStrategy,
    RankingTolerance,
    RouteObjective,
    RouteProfile,
    ScoreReference,
    route_profile_for,
)
from .queue import LexicographicQueue
from .ranking import (
    ProfileRanker,
    RankedCandidate,
    RankedRoute,
    order_routes,
    profile_score,
    rank_candidates,
    rank_routes,
)
from .route import (
    Route,
    route_edge_lengths,
    route_from_state,
    routes_from_result,
)
from .selection import (
    RouteSelectionRequest,
    RouteSelectionResult,
    RouteSelector,
    SelectedRoute,
    SelectionConfig,
    SelectionReason,
    SelectionResult,
    select_candidates,
    select_from_result,
    select_routes,
)
from .state import (
    PhysicalState,
    SearchState,
    advance_state,
    initial_state,
    route_edges,
)
from .traversal_model import (
    UNKNOWN_SPEED,
    PhysicalTraversalModel,
    TraversalModel,
)

__all__ = [
    "BalancedWeights",
    "CandidateMetrics",
    "DEFAULT_MAX_SPEED_MPS",
    "DEFAULT_SPEED_STEP_MPS",
    "DeduplicationMode",
    "Dominance",
    "DiversityConfig",
    "DiversityFallback",
    "DiversityMetric",
    "DiversityRelaxation",
    "FrontierManager",
    "FrontierMap",
    "Heuristic",
    "HeuristicBounds",
    "LexicographicQueue",
    "MetricSource",
    "MultiObjectiveAStar",
    "Objective",
    "ObjectiveEvaluator",
    "ObjectiveSet",
    "ObjectiveValues",
    "PROFILE_CONFIG",
    "PROFILE_IDS",
    "PROFILE_NAMES",
    "PROFILE_OBJECTIVES",
    "PROFILES",
    "ParetoFrontier",
    "PhysicalState",
    "PhysicalTraversalModel",
    "ProfileRanker",
    "ProfileSearchRequest",
    "ProfileSearchResponse",
    "RankedCandidate",
    "RankedRoute",
    "RankingStrategy",
    "RankingTolerance",
    "Route",
    "RouteCandidate",
    "RouteCandidatePool",
    "RouteDeduplicator",
    "RouteDiversity",
    "RouteEnergyEstimate",
    "RouteExplanation",
    "RouteExplainer",
    "RouteObjective",
    "RouteObjectiveEvaluator",
    "RouteProfile",
    "RouteSelectionRequest",
    "RouteSelectionResult",
    "RouteSelector",
    "SUPPORTED_OBJECTIVES",
    "ScoreReference",
    "SearchConfig",
    "SearchProfile",
    "SearchResult",
    "SearchState",
    "SelectedRoute",
    "SelectionConfig",
    "SelectionMetadata",
    "SelectionReason",
    "SelectionResult",
    "SpeedBucketDominance",
    "TraversalModel",
    "UNKNOWN_SPEED",
    "advance_state",
    "dominates",
    "edge_ids_of",
    "edge_jaccard",
    "epsilon_dominates",
    "estimate_route_energy",
    "estimate_routes_energy",
    "evaluate",
    "evaluate_metrics",
    "evaluate_route",
    "explain_route",
    "initial_state",
    "is_feasible",
    "is_too_similar",
    "model_max_speed",
    "objective_value",
    "objectives_for",
    "order_labels",
    "order_routes",
    "profile_for",
    "profile_score",
    "rank_candidates",
    "rank_routes",
    "route_diversity",
    "route_edge_lengths",
    "route_edges",
    "route_from_state",
    "route_profile_for",
    "route_similarity",
    "routes_from_result",
    "search_profile",
    "select_candidates",
    "select_from_result",
    "select_routes",
    "shared_distance_ratio",
    "speed_bucket",
]
