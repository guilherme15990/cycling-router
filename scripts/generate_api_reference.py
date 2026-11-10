"""Gera ``docs/api.md`` a partir de ``api.__all__`` (assinaturas exatas via ``inspect``).

As assinaturas sao extraidas por introspeccao, de modo que o documento nunca
diverge do codigo. O texto de cada camada e curado aqui. Rode com:

    python scripts/generate_api_reference.py

O script falha se algum simbolo de ``api.__all__`` nao estiver em nenhuma
camada, evitando que a referencia fique incompleta ao adicionar nomes novos.
"""

from __future__ import annotations

import inspect
import re
import sys
from enum import EnumMeta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import api  # noqa: E402

# Ordem e texto das camadas. Os nomes vem exatamente de ``api.__all__``.
LAYERS: list[tuple[str, str, list[str]]] = [
    (
        "Grafo ciclavel: modelo",
        "Estruturas centrais do grafo: nos, segmentos, arestas direcionadas e o "
        "conteiner ``CyclingGraph``.",
        ["BicycleAccess", "CyclingGraph", "Edge", "EdgeSegment", "ElevationSample", "Node"],
    ),
    (
        "Grafo ciclavel: superficie",
        "Classificacao observavel de superficie e a politica de prioridade "
        "(ordinal) do roteador.",
        [
            "OSM_SURFACE_MAP",
            "OSM_TRACKTYPE_MAP",
            "SURFACE_PRIORITY",
            "Surface",
            "SurfaceStatus",
            "surface_from_tags",
            "surface_observation",
            "surface_priority",
        ],
    ),
    (
        "Grafo ciclavel: restricoes de acesso",
        "Restricoes de acesso preservadas das tags OSM, sem avaliacao temporal.",
        ["AccessRestriction", "parse_conditional_restrictions"],
    ),
    (
        "Grafo ciclavel: simplificacao",
        "Contracao de nos de grau 2 sem perder atributos fisicos nem de acesso.",
        ["SimplifyOptions", "SimplifyStats", "simplify_graph"],
    ),
    (
        "Snapping (grafo de consulta)",
        "Conexao de origem/destino a rede: opcoes, candidatos, resultado e o "
        "grafo temporario de consulta.",
        [
            "QueryGraph",
            "SnapCandidate",
            "SnapError",
            "SnapOptions",
            "SnapResult",
            "SpatialSnapper",
            "build_query_graph",
        ],
    ),
    (
        "Fisica: travessia",
        "Modelos do ciclista e da bicicleta, perfis de aresta e a simulacao de "
        "travessia (tempo, energia e velocidade).",
        [
            "BicycleModel",
            "CyclistModel",
            "EdgeProfile",
            "Environment",
            "PhysicalTraversal",
            "RouteMetrics",
            "TraversalPath",
            "TraversalResult",
            "traverse_edge",
        ],
    ),
    (
        "Fisica: energia e bateria",
        "Modelo energetico (energia mecanica -> eletrica em Wh) e viabilidade de "
        "bateria. O perfil eletrico usa energia **mecanica** na fronteira Pareto; a "
        "conversao para Wh e um estagio posterior a selecao.",
        [
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
        ],
    ),
    (
        "Busca: objetivos e perfis",
        "Objetivos, perfis declarativos (fastest/shortest/flattest/balanced/"
        "electric), tolerancias e configuracao de diversidade.",
        [
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
        ],
    ),
    (
        "Busca: estado, fronteira e A*",
        "Nucleo do A* multiobjetivo: estado, dominancia, fronteira Pareto, fila "
        "lexicografica e heuristica admissivel.",
        [
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
        ],
    ),
    (
        "Busca: reconstrucao e avaliacao de rotas",
        "Reconstrucao da fronteira em rotas e avaliacao de objetivos.",
        [
            "Route",
            "evaluate",
            "evaluate_metrics",
            "evaluate_route",
            "route_from_state",
            "routes_from_result",
        ],
    ),
    (
        "Selecao: candidatas, ranking e diversidade",
        "Pool de candidatas (com deduplicacao), ranking por perfil e diversidade.",
        [
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
        ],
    ),
    (
        "Selecao: N rotas, explicacao e pipeline",
        "Escolha das N rotas (com fallback de diversidade), explicacao e o "
        "contrato de alto nivel ``search_profile``.",
        [
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
        ],
    ),
    (
        "Energia da rota (pos-selecao)",
        "Estimativa de energia eletrica de uma rota, alinhada as rotas "
        "selecionadas.",
        ["RouteEnergyEstimate", "estimate_route_energy", "estimate_routes_energy"],
    ),
]

# Resumos curtos para constantes de modulo (valores, nao classes/funcoes).
CONSTANT_NOTES: dict[str, str] = {
    "OSM_SURFACE_MAP": "Mapeia valores de ``surface=*`` do OSM para ``Surface``.",
    "OSM_TRACKTYPE_MAP": "Mapeia ``tracktype=grade1..grade5`` para ``Surface``.",
    "SURFACE_PRIORITY": "Prioridade ordinal por superficie (1 melhor ... 6 desconhecida).",
    "JOULES_PER_WH": "Fator de conversao de energia (1 Wh = 3600 J).",
    "GENERIC_LEVEL": "Nivel de estimativa com valores de referencia internos.",
    "PERSONALIZED_LEVEL": "Nivel de estimativa com parametros do veiculo informados.",
    "CALIBRATED_LEVEL": "Nivel de estimativa calibrado com dados reais.",
    "PROFILE_IDS": "Ids dos perfis de selecao (``profiles.py``).",
    "PROFILE_NAMES": "Ids dos perfis de busca, em ordem estavel (``objectives.py``).",
    "PROFILE_OBJECTIVES": "``ObjectiveSet`` (objetivos Pareto) por id de perfil.",
    "PROFILES": "``SearchProfile`` por id de perfil.",
    "PROFILE_CONFIG": "``RouteProfile`` (selecao) por id de perfil.",
    "UNKNOWN_SPEED": "Sentinela de velocidade inicial desconhecida na busca.",
}


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


# Prefixos de modulo interno que poluem as assinaturas (a fachada reexporta os
# nomes curtos, entao ``graph.surface.Surface`` sai como ``Surface``).
_MODULE_PREFIX = re.compile(
    r"\b(?:graph|search|physical|osm)(?:\.[a-z_]+)+\."
)


def tidy(text: str) -> str:
    return _MODULE_PREFIX.sub("", text)


def own_doc(obj: object) -> str:
    """Docstring propria (nao herdada), limpa; vazio se ausente."""
    doc = getattr(obj, "__doc__", None)
    return inspect.cleandoc(doc) if doc else ""


def _params(obj: object) -> str:
    """Assinatura de parametros, com anotacoes resolvidas quando possivel."""
    try:
        signature = str(inspect.signature(obj, eval_str=True))
    except (NameError, TypeError, ValueError):
        try:
            signature = str(inspect.signature(obj))
        except (TypeError, ValueError):
            return ""
        # Remove as aspas das anotacoes quando nao foi possivel resolve-las.
        signature = re.sub(r"'([^']*)'", r"\1", signature)
    # Remove uma anotacao de retorno residual (ex.: ``-> None`` em classes).
    return tidy(re.sub(r"\s*->.*$", "", signature).strip())


def render_signature(name: str, obj: object) -> str:
    if inspect.isclass(obj):
        bases = [base for base in obj.__bases__ if base is not object]
        base_text = f"({', '.join(base.__name__ for base in bases)})" if bases else ""
        if isinstance(obj, EnumMeta):
            return f"class {name}{base_text}"
        params = _params(obj)
        params = "" if params in {"()", "(*args, **kwargs)"} else params
        return f"class {name}{base_text}{params}"
    if inspect.isroutine(obj):
        try:
            return tidy(f"{name}{inspect.signature(obj, eval_str=True)}")
        except (NameError, TypeError, ValueError):
            signature = str(inspect.signature(obj))
            return tidy(re.sub(r"'([^']*)'", r"\1", f"{name}{signature}"))
    return name


def render_symbol(name: str, obj: object) -> list[str]:
    lines = [f"### `{name}`", "", "```python", render_signature(name, obj), "```", ""]

    if inspect.isclass(obj) or inspect.isroutine(obj):
        text = own_doc(obj).split("\n\n", 1)[0].replace("\n", " ").strip()
    else:
        text = CONSTANT_NOTES.get(name, "")
    if text:
        lines.append(text)
        lines.append("")
    if isinstance(obj, EnumMeta):
        members = ", ".join(f"`{member.name}`" for member in obj)
        lines.append(f"Valores: {members}.")
        lines.append("")
    return lines


def main() -> int:
    declared = {name for _, _, names in LAYERS for name in names}
    exported = set(api.__all__)
    if declared != exported:
        missing = sorted(exported - declared)
        extra = sorted(declared - exported)
        raise SystemExit(f"camadas desatualizadas; faltam={missing} sobram={extra}")

    out: list[str] = [
        "# Referencia da API",
        "",
        "> Gerado automaticamente por `scripts/generate_api_reference.py`. Nao edite a mao.",
        "",
        f"Versao: **{api.__version__}** - {len(api.__all__)} simbolos publicos "
        "(`api.__all__`).",
        "",
        "Todas as assinaturas sao extraidas do codigo por introspeccao. A "
        "descricao de cada camada e curada; o resumo de cada simbolo vem da "
        "propria docstring (use `help(obj)` para o texto completo).",
        "",
        "## Sumario",
        "",
    ]
    for title, _, _ in LAYERS:
        out.append(f"- [{title}](#{slug(title)})")
    out.append("")

    for title, intro, names in LAYERS:
        out.append(f"## {title}")
        out.append("")
        out.append(intro)
        out.append("")
        for name in names:
            out.extend(render_symbol(name, getattr(api, name)))

    destination = ROOT / "docs" / "api.md"
    destination.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    print(f"escrito {destination} ({len(api.__all__)} simbolos)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
