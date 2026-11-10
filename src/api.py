"""Fachada do motor de roteamento ciclavel.

Ponto unico de importacao da API publica. Os modulos ficam na raiz de
``src/`` e tambem podem ser importados por nome curto (por exemplo,
``from search import search_profile``); esta fachada reune tudo quando se
prefere um unico ``import api``.

Mapa das camadas
----------------

* **Grafo ciclavel** (``graph.*``): modelo, superficie, restricoes,
  simplificacao, validacao e serializacao (JSON/GeoJSON).
* **OSM** (``osm.*``): download via Overpass, parsing e construcao do grafo.
* **Elevacao** (``elevation``): provedores de altitude, cache e perfil
  amostrado ao longo da aresta.
* **Snapping** (``snapping``): grafo temporario de consulta para origem e
  destino.
* **Fisica** (``physical.*``): travessia (tempo, energia, velocidade) e
  modelo energetico (energia eletrica em Wh e viabilidade de bateria).
* **Busca e selecao** (``search.*``): A* multiobjetivo sobre a fronteira
  Pareto e a selecao por perfil (ranking, diversidade, explicacao e
  estimativa energetica).

A fisica e sempre a mesma: o perfil **nao** altera o modelo fisico. Ele muda
apenas quais metricas entram na fronteira Pareto e como as rotas sao
ordenadas e selecionadas. A estimativa energetica (Wh) e um estagio posterior
a selecao.

Example:
    >>> from api import route_profile_for
    >>> route_profile_for("electric").id
    'electric'

Version:
    A versao publica esta em ``api.__version__`` (SemVer). Ver
    ``CHANGELOG.md`` para o historico e a politica de estabilidade.
"""

from graph.model import BicycleAccess, CyclingGraph, Edge, EdgeSegment, ElevationSample, Node
from graph.restrictions import AccessRestriction, parse_conditional_restrictions
from graph.simplify import SimplifyOptions, SimplifyStats, simplify_graph
from graph.surface import (
    OSM_SURFACE_MAP,
    OSM_TRACKTYPE_MAP,
    SURFACE_PRIORITY,
    Surface,
    SurfaceStatus,
    surface_from_tags,
    surface_observation,
    surface_priority,
)
from physical import (
    BicycleModel,
    BatteryConfig,
    BatteryFeasibility,
    CALIBRATED_LEVEL,
    CyclistModel,
    EdgeProfile,
    EnergyEstimate,
    EnergyModel,
    Environment,
    GENERIC_LEVEL,
    GenericEnergyConfig,
    JOULES_PER_WH,
    PERSONALIZED_LEVEL,
    PhysicalTraversal,
    RouteMetrics,
    TraversalPath,
    TraversalResult,
    assess_battery,
    traverse_edge,
)
from search import (
    PROFILE_CONFIG,
    PROFILE_IDS,
    PROFILE_NAMES,
    PROFILE_OBJECTIVES,
    PROFILES,
    BalancedWeights,
    CandidateMetrics,
    DeduplicationMode,
    DiversityConfig,
    DiversityFallback,
    DiversityMetric,
    DiversityRelaxation,
    FrontierManager,
    FrontierMap,
    Heuristic,
    HeuristicBounds,
    LexicographicQueue,
    MetricSource,
    MultiObjectiveAStar,
    Objective,
    ObjectiveEvaluator,
    ObjectiveSet,
    ObjectiveValues,
    ParetoFrontier,
    PhysicalState,
    PhysicalTraversalModel,
    ProfileRanker,
    ProfileSearchRequest,
    ProfileSearchResponse,
    RankedCandidate,
    RankedRoute,
    RankingStrategy,
    RankingTolerance,
    Route,
    RouteCandidate,
    RouteCandidatePool,
    RouteDeduplicator,
    RouteDiversity,
    RouteEnergyEstimate,
    RouteExplanation,
    RouteExplainer,
    RouteObjective,
    RouteObjectiveEvaluator,
    RouteProfile,
    RouteSelectionRequest,
    RouteSelectionResult,
    RouteSelector,
    ScoreReference,
    SearchConfig,
    SearchProfile,
    SearchResult,
    SearchState,
    SelectedRoute,
    SelectionConfig,
    SelectionMetadata,
    SelectionReason,
    SelectionResult,
    SpeedBucketDominance,
    TraversalModel,
    UNKNOWN_SPEED,
    advance_state,
    dominates,
    edge_jaccard,
    epsilon_dominates,
    estimate_route_energy,
    estimate_routes_energy,
    evaluate,
    evaluate_metrics,
    evaluate_route,
    explain_route,
    initial_state,
    is_too_similar,
    model_max_speed,
    objectives_for,
    order_routes,
    profile_for,
    profile_score,
    rank_candidates,
    rank_routes,
    route_diversity,
    route_edges,
    route_from_state,
    route_similarity,
    route_profile_for,
    routes_from_result,
    search_profile,
    select_candidates,
    select_from_result,
    select_routes,
    shared_distance_ratio,
)
from snapping import (
    QueryGraph,
    SnapCandidate,
    SnapError,
    SnapOptions,
    SnapResult,
    SpatialSnapper,
    build_query_graph,
)

__all__ = [
    # Grafo ciclavel: modelo -------------------------------------------------
    "BicycleAccess",
    "CyclingGraph",
    "Edge",
    "EdgeSegment",
    "ElevationSample",
    "Node",
    # Grafo ciclavel: superficie ---------------------------------------------
    "OSM_SURFACE_MAP",
    "OSM_TRACKTYPE_MAP",
    "SURFACE_PRIORITY",
    "Surface",
    "SurfaceStatus",
    "surface_from_tags",
    "surface_observation",
    "surface_priority",
    # Grafo ciclavel: restricoes de acesso -----------------------------------
    "AccessRestriction",
    "parse_conditional_restrictions",
    # Grafo ciclavel: simplificacao ------------------------------------------
    "SimplifyOptions",
    "SimplifyStats",
    "simplify_graph",
    # Snapping (grafo de consulta) -------------------------------------------
    "QueryGraph",
    "SnapCandidate",
    "SnapError",
    "SnapOptions",
    "SnapResult",
    "SpatialSnapper",
    "build_query_graph",
    # Fisica: travessia ------------------------------------------------------
    "BicycleModel",
    "CyclistModel",
    "EdgeProfile",
    "Environment",
    "PhysicalTraversal",
    "RouteMetrics",
    "TraversalPath",
    "TraversalResult",
    "traverse_edge",
    # Fisica: energia e bateria ----------------------------------------------
    "BatteryConfig",
    "BatteryFeasibility",
    "CALIBRATED_LEVEL",
    "EnergyEstimate",
    "EnergyModel",
    "GENERIC_LEVEL",
    "GenericEnergyConfig",
    "JOULES_PER_WH",
    "PERSONALIZED_LEVEL",
    "assess_battery",
    # Busca: objetivos e perfis ----------------------------------------------
    "BalancedWeights",
    "DiversityConfig",
    "DiversityFallback",
    "DiversityMetric",
    "DiversityRelaxation",
    "MetricSource",
    "Objective",
    "ObjectiveEvaluator",
    "ObjectiveSet",
    "ObjectiveValues",
    "PROFILE_CONFIG",
    "PROFILE_IDS",
    "PROFILE_NAMES",
    "PROFILE_OBJECTIVES",
    "PROFILES",
    "RankingStrategy",
    "RankingTolerance",
    "RouteObjective",
    "RouteObjectiveEvaluator",
    "RouteProfile",
    "ScoreReference",
    "SearchProfile",
    "dominates",
    "epsilon_dominates",
    "objectives_for",
    "profile_for",
    "route_profile_for",
    # Busca: estado, fronteira e A* ------------------------------------------
    "FrontierManager",
    "FrontierMap",
    "Heuristic",
    "HeuristicBounds",
    "LexicographicQueue",
    "MultiObjectiveAStar",
    "ParetoFrontier",
    "PhysicalState",
    "PhysicalTraversalModel",
    "SearchConfig",
    "SearchResult",
    "SearchState",
    "SpeedBucketDominance",
    "TraversalModel",
    "UNKNOWN_SPEED",
    "advance_state",
    "initial_state",
    "model_max_speed",
    "route_edges",
    # Busca: reconstrucao e avaliacao de rotas -------------------------------
    "Route",
    "evaluate",
    "evaluate_metrics",
    "evaluate_route",
    "route_from_state",
    "routes_from_result",
    # Selecao: candidatas, ranking e diversidade -----------------------------
    "CandidateMetrics",
    "DeduplicationMode",
    "ProfileRanker",
    "RankedCandidate",
    "RankedRoute",
    "RouteCandidate",
    "RouteCandidatePool",
    "RouteDeduplicator",
    "RouteDiversity",
    "edge_jaccard",
    "is_too_similar",
    "order_routes",
    "profile_score",
    "rank_candidates",
    "rank_routes",
    "route_diversity",
    "route_similarity",
    "shared_distance_ratio",
    # Selecao: N rotas, explicacao e pipeline --------------------------------
    "ProfileSearchRequest",
    "ProfileSearchResponse",
    "RouteExplanation",
    "RouteExplainer",
    "RouteSelectionRequest",
    "RouteSelectionResult",
    "RouteSelector",
    "SelectedRoute",
    "SelectionConfig",
    "SelectionMetadata",
    "SelectionReason",
    "SelectionResult",
    "explain_route",
    "search_profile",
    "select_candidates",
    "select_from_result",
    "select_routes",
    # Energia da rota (estagio pos-selecao) ----------------------------------
    "RouteEnergyEstimate",
    "estimate_route_energy",
    "estimate_routes_energy",
]

__version__ = "0.11.0"
