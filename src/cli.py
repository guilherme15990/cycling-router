"""Linha de comando do motor de roteamento.

Exemplos:

    roteamento build --bbox -23.56,-46.66,-23.54,-46.62 --out centro.json
    roteamento stats centro.json
    roteamento geojson centro.json centro.geojson
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from elevation import (
    ChainElevation,
    OpenTopoDataElevation,
    OsmTagElevation,
    RasterDemElevation,
    SqliteElevationCache,
)
from geo import parse_bbox, parse_coord
from graph.model import Edge
from graph.serialize import load_json, save_geojson, save_json, summarize
from graph.simplify import simplify_graph
from graph.validate import validate_graph
from osm.build import BuildOptions, attach_elevation, build_graph
from osm.overpass import DEFAULT_ENDPOINTS, DEFAULT_HIGHWAYS, OverpassClient
from physical import (
    BicycleModel,
    CyclistModel,
    Environment,
    PhysicalTraversal,
    TraversalResult,
)
from snapping import SnapError, SnapOptions, build_query_graph

DEFAULT_CACHE_DIR = Path(".cache") / "roteamento"


def main(argv: list[str] | None = None) -> int:
    _configure_stdout()
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not hasattr(args, "handler"):
        parser.print_help()
        return 2
    return args.handler(args)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="roteamento",
        description=(
            "Grafo ciclavel, snapping e modelo fisico a partir do OpenStreetMap."
        ),
    )
    subparsers = parser.add_subparsers(dest="command")

    build = subparsers.add_parser(
        "build", help="baixa dados do OSM e monta o grafo ciclavel"
    )
    build.add_argument(
        "--bbox",
        required=True,
        help="sul,oeste,norte,leste em graus decimais (formato Overpass)",
    )
    build.add_argument("--out", default="graph.json", help="arquivo JSON de saida")
    build.add_argument(
        "--geojson", dest="geojson_out", default=None, help="arquivo GeoJSON opcional"
    )
    build.add_argument(
        "--elevation",
        choices=("osm", "opentopodata", "dem", "none"),
        default="opentopodata",
        help=(
            "fonte de elevacao: 'opentopodata' combina ele=* do OSM com SRTM 30m "
            "(padrao, com cache); 'osm' usa so as tags (rapido, cobertura baixa); "
            "'dem' le um GeoTIFF local; 'none' desliga"
        ),
    )
    build.add_argument("--dem", default=None, help="caminho do GeoTIFF (com --elevation dem)")
    build.add_argument(
        "--spacing",
        type=float,
        default=25.0,
        help="espacamento em metros das amostras de elevacao (padrao: 25)",
    )
    build.add_argument(
        "--smoothing",
        type=int,
        default=3,
        help=(
            "janela (amostras) da media movel no perfil de elevacao; "
            "1 desliga (padrao: 3)"
        ),
    )
    build.add_argument(
        "--overpass",
        default=DEFAULT_ENDPOINTS[0],
        help=f"endpoint Overpass (padrao: {DEFAULT_ENDPOINTS[0]})",
    )
    build.add_argument(
        "--highways",
        default=None,
        help="lista de highway=* separada por virgula (padrao: rede ciclavel urbana)",
    )
    build.add_argument("--allow-footway", action="store_true")
    build.add_argument("--no-dismount", action="store_true")
    build.add_argument(
        "--no-simplify",
        action="store_true",
        help="nao contrai nos de grau 2 (mantem a topologia crua do OSM)",
    )
    build.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
    build.add_argument("--no-cache", action="store_true")
    build.add_argument("--timeout", type=int, default=180, help="timeout do Overpass (s)")
    build.set_defaults(handler=cmd_build)

    stats = subparsers.add_parser("stats", help="resumo e validacao de um grafo salvo")
    stats.add_argument("path")
    stats.add_argument("--json", action="store_true", help="imprime o resumo em JSON")
    stats.add_argument("--issues", action="store_true", help="lista todos os problemas")
    stats.set_defaults(handler=cmd_stats)

    geojson = subparsers.add_parser("geojson", help="converte o grafo para GeoJSON")
    geojson.add_argument("path")
    geojson.add_argument("out")
    geojson.set_defaults(handler=cmd_geojson)

    validate = subparsers.add_parser("validate", help="valida a consistencia do grafo")
    validate.add_argument("path")
    validate.add_argument(
        "--strict",
        action="store_true",
        help="retorna codigo 1 se houver qualquer problema (inclusive avisos)",
    )
    validate.set_defaults(handler=cmd_validate)

    snap = subparsers.add_parser(
        "snap",
        help="conecta origem/destino ao grafo e monta o grafo de consulta",
    )
    snap.add_argument("path", help="grafo salvo em JSON")
    snap.add_argument("--origin", required=True, help="origem no formato lat,lon")
    snap.add_argument(
        "--destination", required=True, help="destino no formato lat,lon"
    )
    snap.add_argument(
        "--max-distance",
        type=float,
        default=100.0,
        help="desvio maximo aceito em metros (padrao: 100)",
    )
    snap.add_argument(
        "--node-preference",
        type=float,
        default=10.0,
        help="distancia maxima para preferir um no existente (padrao: 10 m)",
    )
    snap.add_argument(
        "--node-tolerance",
        type=float,
        default=2.0,
        help="folga do no em relacao ao desvio da aresta (padrao: 2 m)",
    )
    snap.add_argument(
        "--min-split",
        type=float,
        default=1.0,
        help="distancia minima das pontas para dividir a aresta (padrao: 1 m)",
    )
    snap.add_argument(
        "--no-dismount",
        action="store_true",
        help="nao conecta em trechos bicycle=dismount",
    )
    snap.add_argument(
        "--out-query",
        default=None,
        help="salva o grafo de consulta (JSON) no caminho indicado",
    )
    snap.add_argument(
        "--json", action="store_true", help="imprime o resultado em JSON"
    )
    snap.set_defaults(handler=cmd_snap)

    physical = subparsers.add_parser(
        "physical",
        help="estima tempo e energia fisica de uma aresta",
    )
    physical.add_argument("path", help="grafo salvo em JSON")
    physical.add_argument("--edge", required=True, help="id da aresta")
    physical.add_argument(
        "--initial-speed",
        type=float,
        default=0.0,
        help="velocidade inicial em m/s (padrao: 0)",
    )
    physical.add_argument(
        "--power",
        type=float,
        default=None,
        help="potencia no pedivela em W (padrao: 200 W ou --max-power)",
    )
    physical.add_argument(
        "--max-power",
        type=float,
        default=600.0,
        help="potencia maxima do ciclista em W (padrao: 600)",
    )
    physical.add_argument(
        "--cyclist-mass", type=float, default=75.0, help="massa do ciclista (kg)"
    )
    physical.add_argument(
        "--frontal-area", type=float, default=0.5, help="area frontal (m2)"
    )
    physical.add_argument(
        "--bike-mass", type=float, default=12.0, help="massa da bicicleta (kg)"
    )
    physical.add_argument(
        "--crr",
        type=float,
        default=0.005,
        help="coeficiente de resistencia ao rolamento (padrao: 0.005)",
    )
    physical.add_argument(
        "--cd",
        type=float,
        default=0.9,
        help="coeficiente aerodinamico (padrao: 0.9)",
    )
    physical.add_argument(
        "--efficiency",
        type=float,
        default=0.97,
        help="eficiencia da transmissao (padrao: 0.97)",
    )
    physical.add_argument(
        "--step",
        type=float,
        default=5.0,
        help="passo espacial da simulacao em metros (padrao: 5)",
    )
    physical.add_argument(
        "--safe-max-speed",
        type=float,
        default=22.0,
        help="limite global de velocidade em m/s (padrao: 22; 0 desliga)",
    )
    physical.add_argument(
        "--air-density", type=float, default=1.225, help="densidade do ar (kg/m3)"
    )
    physical.add_argument(
        "--headwind",
        type=float,
        default=0.0,
        help="vento de frente em m/s (negativo = cauda; padrao: 0)",
    )
    physical.add_argument(
        "--dismount-speed",
        type=float,
        default=1.4,
        help="velocidade a pe em trechos dismount (m/s; padrao: 1.4)",
    )
    physical.add_argument(
        "--json", action="store_true", help="imprime o resultado em JSON"
    )
    physical.set_defaults(handler=cmd_physical)

    return parser


# --------------------------------------------------------------------------
# Comandos
# --------------------------------------------------------------------------
def cmd_build(args: argparse.Namespace) -> int:
    bbox = parse_bbox(args.bbox)
    highways = (
        tuple(item.strip() for item in args.highways.split(",") if item.strip())
        if args.highways
        else DEFAULT_HIGHWAYS
    )

    cache_dir = None if args.no_cache else Path(args.cache_dir)
    client = OverpassClient(
        endpoint=args.overpass,
        cache_dir=cache_dir,
        timeout_s=float(args.timeout),
    )

    print(f"Overpass: {args.overpass}")
    print(f"bbox: {bbox}")
    data = client.fetch(bbox, highways=highways, timeout_s=args.timeout)
    print(f"OSM: {len(data.nodes)} nos, {len(data.ways)} vias")

    options = BuildOptions(
        allow_footway=args.allow_footway,
        allow_dismount=not args.no_dismount,
    )
    graph, build_stats = build_graph(data, options)
    print(
        "vias selecionadas: "
        f"{build_stats.ways_selected}/{build_stats.ways_total} | "
        f"trechos: {build_stats.segments}"
    )
    if build_stats.skipped_missing_nodes:
        print(f"  ignorados por nos ausentes: {build_stats.skipped_missing_nodes}")
    if build_stats.skipped_short:
        print(f"  ignorados por comprimento minimo: {build_stats.skipped_short}")

    provider = _make_provider(args, data)
    if provider is None:
        print("elevacao: desligada")
    else:
        print(f"elevacao: {getattr(provider, 'name', provider)} (espacamento {args.spacing} m)")
        attach_elevation(
            graph,
            provider,
            spacing_m=args.spacing,
            smoothing=args.smoothing,
        )
        if isinstance(provider, SqliteElevationCache):
            provider.close()

    if not args.no_simplify:
        simplified, simplify_stats = simplify_graph(graph)
        print(
            "simplificacao: "
            f"{simplify_stats.nodes_before} -> {simplify_stats.nodes_after} nos | "
            f"{simplify_stats.edges_before} -> {simplify_stats.edges_after} arestas | "
            f"{simplify_stats.contracted_nodes} nos contraidos | "
            f"{simplify_stats.multi_segment_edges} arestas multi-segmento"
        )
        graph = simplified

    issues = validate_graph(graph)
    errors = sum(1 for issue in issues if issue.severity == "error")
    if errors:
        print(f"ATENCAO: {errors} erro(s) de consistencia; use 'roteamento validate'")
    else:
        print("consistencia: ok")

    destination = save_json(graph, args.out)
    summary = summarize(graph)
    print(
        f"grafo: {summary['nodes']} nos, {summary['edges']} arestas, "
        f"{summary['total_length_km']} km"
    )
    print(f"salvo em: {destination}")

    if args.geojson_out:
        save_geojson(graph, args.geojson_out)
        print(f"geojson: {args.geojson_out}")

    _print_surface_table(summary)
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    graph = load_json(args.path)
    summary = summarize(graph)
    issues = validate_graph(graph)

    if args.json:
        print(json.dumps({**summary, "issues": [str(i) for i in issues]}, indent=2))
        return 0

    print(f"arquivo: {args.path}")
    print(
        f"nos: {summary['nodes']}  arestas: {summary['edges']}  "
        f"segmentos: {summary['segments']}"
    )
    simplification = summary.get("simplification")
    if simplification:
        print(
            "simplificacao: "
            f"{simplification['contracted_nodes']} nos contraidos, "
            f"{simplification['multi_segment_edges']} arestas multi-segmento"
        )
    print(
        f"comprimento: {summary['total_length_km']} km | "
        f"subida acumulada: {summary['total_ascent_m']} m | "
        f"descida acumulada: {summary['total_descent_m']} m"
    )
    print(
        f"elevacao por aresta: {summary['elevation_coverage'] * 100:.1f}% "
        f"({summary['edges_with_elevation']}/{summary['edges']})"
    )
    if summary["elevation_sources"]:
        sources = ", ".join(
            f"{name} ({count})" for name, count in summary["elevation_sources"].items()
        )
        print(f"fonte de elevacao: {sources}")
    if summary["dismount_length_m"]:
        print(f"trechos com bicycle=dismount: {summary['dismount_length_m']} m")

    _print_surface_table(summary)

    errors = [issue for issue in issues if issue.severity == "error"]
    warnings = [issue for issue in issues if issue.severity == "warning"]
    print(f"validacao: {len(errors)} erro(s), {len(warnings)} aviso(s)")
    if args.issues:
        for issue in issues:
            print(f"  {issue}")
    return 1 if errors else 0


def cmd_geojson(args: argparse.Namespace) -> int:
    graph = load_json(args.path)
    save_geojson(graph, args.out)
    print(f"salvo em: {args.out}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    graph = load_json(args.path)
    issues = validate_graph(graph)
    for issue in issues:
        print(issue)

    errors = sum(1 for issue in issues if issue.severity == "error")
    warnings = sum(1 for issue in issues if issue.severity == "warning")
    print(f"total: {errors} erro(s), {warnings} aviso(s)")

    if errors or (args.strict and warnings):
        return 1
    return 0


def cmd_snap(args: argparse.Namespace) -> int:
    graph = load_json(args.path)
    options = SnapOptions(
        max_distance_m=args.max_distance,
        node_preference_m=args.node_preference,
        node_offset_tolerance_m=args.node_tolerance,
        min_split_distance_m=args.min_split,
        allow_dismount=not args.no_dismount,
    )

    try:
        query = build_query_graph(
            graph,
            parse_coord(args.origin),
            parse_coord(args.destination),
            options,
        )
    except SnapError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1

    summary = {
        "origin": query.origin.to_dict(),
        "destination": query.destination.to_dict(),
        "connected": query.is_connected(),
        "query": {
            "nodes": query.graph.node_count,
            "edges": query.graph.edge_count,
            "segments": sum(
                edge.segment_count for edge in query.graph.edges.values()
            ),
            "virtual_nodes": sorted(str(node_id) for node_id in query.virtual_nodes),
        },
    }

    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    else:
        _print_snap(summary)

    if args.out_query:
        destination = save_json(query.graph, args.out_query)
        if not args.json:
            print(f"salvo em: {destination}")

    return 0


def cmd_physical(args: argparse.Namespace) -> int:
    graph = load_json(args.path)
    try:
        edge = graph.get_edge(args.edge)
    except Exception as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1

    max_power = max(args.max_power, args.power or 0.0)
    sustainable = (
        args.power if args.power is not None else min(200.0, max_power)
    )
    try:
        cyclist = CyclistModel(
            mass_kg=args.cyclist_mass,
            max_power_w=max_power,
            sustainable_power_w=sustainable,
            frontal_area_m2=args.frontal_area,
        )
        bicycle = BicycleModel(
            mass_kg=args.bike_mass,
            rolling_resistance=args.crr,
            drag_coefficient=args.cd,
            drivetrain_efficiency=args.efficiency,
        )
        environment = Environment(
            air_density_kg_m3=args.air_density,
            headwind_mps=args.headwind,
            safe_max_speed_mps=(
                args.safe_max_speed if args.safe_max_speed > 0 else None
            ),
        )
        traversal = PhysicalTraversal(
            step_m=args.step,
            dismount_speed_mps=args.dismount_speed,
        )
        result = traversal.traverse(
            edge,
            cyclist,
            bicycle,
            initial_speed_mps=args.initial_speed,
            environment=environment,
            power_w=args.power,
        )
    except ValueError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    else:
        _print_physical(edge, result, cyclist, bicycle)

    return 0


# --------------------------------------------------------------------------
# Utilitarios
# --------------------------------------------------------------------------
def _make_provider(args: argparse.Namespace, data: object):
    if args.elevation == "none":
        return None

    if args.elevation == "dem":
        if not args.dem:
            raise SystemExit("--elevation dem exige --dem caminho/para/dem.tif")
        provider = RasterDemElevation(args.dem)
    elif args.elevation == "opentopodata":
        from osm.parse import OverpassData

        assert isinstance(data, OverpassData)
        provider = ChainElevation(
            OsmTagElevation.from_nodes(data.nodes.values()),
            OpenTopoDataElevation(),
        )
    else:  # osm
        from osm.parse import OverpassData

        assert isinstance(data, OverpassData)
        provider = OsmTagElevation.from_nodes(data.nodes.values())

    if args.no_cache:
        return provider
    return SqliteElevationCache(provider, Path(args.cache_dir) / "elevation.sqlite")


def _print_snap(summary: dict) -> None:
    for key, label in (("origin", "origem"), ("destination", "destino")):
        item = summary[key]
        if item["kind"] == "node":
            print(
                f"{label}: no {item['node_id']} "
                f"(offset {item['offset_m']:.1f} m)"
            )
        else:
            fraction = item["fraction"] or 0.0
            along = item["along_m"] or 0.0
            print(
                f"{label}: aresta {item['edge_id']} "
                f"(offset {item['offset_m']:.1f} m, fracao {fraction:.3f}, "
                f"{along:.1f} m)"
            )

    print(f"conectado: {'sim' if summary['connected'] else 'nao'}")
    query = summary["query"]
    print(
        f"grafo de consulta: {query['nodes']} nos, {query['edges']} arestas, "
        f"{query['segments']} segmentos"
    )


def _print_physical(
    edge: Edge,
    result: TraversalResult,
    cyclist: CyclistModel,
    bicycle: BicycleModel,
) -> None:
    print(
        f"aresta: {edge.id} | {edge.distance_m:.1f} m | "
        f"{edge.segment_count} segmento(s)"
    )
    print(
        f"perfil: subida {result.ascent_m:.1f} m | "
        f"descida {result.descent_m:.1f} m"
    )
    print(
        f"tempo: {result.time_s:.1f} s | "
        f"velocidade media: {result.average_speed_kmh:.1f} km/h"
    )
    print(
        f"velocidade: {result.initial_speed_mps:.2f} -> "
        f"{result.final_speed_mps:.2f} m/s"
    )
    print(
        f"energia: mecanica {result.mechanical_energy_j / 1000.0:.1f} kJ | "
        f"ciclista {result.rider_energy_j / 1000.0:.1f} kJ | "
        f"frenagem {result.braking_energy_j / 1000.0:.1f} kJ"
    )
    print(
        f"massa total: {cyclist.mass_kg + bicycle.mass_kg:.1f} kg | "
        f"potencia: {cyclist.sustainable_power_w:.0f} W | "
        f"eficiencia: {bicycle.drivetrain_efficiency:.2f}"
    )
    if result.stalled:
        print("aviso: o modelo estagnou em baixa velocidade")


def _print_surface_table(summary: dict) -> None:
    surface_lengths: dict[str, float] = summary["length_by_surface_m"]
    total = sum(surface_lengths.values()) or 1.0
    print("superficie:")
    for surface, length in sorted(
        surface_lengths.items(), key=lambda item: item[1], reverse=True
    ):
        share = 100.0 * length / total
        print(f"  {surface:<16} {length / 1000.0:8.3f} km  {share:5.1f}%")

    status_lengths: dict[str, float] = summary.get("length_by_surface_status_m") or {}
    if status_lengths:
        total_status = sum(status_lengths.values()) or 1.0
        print("proveniencia da superficie:")
        for status, length in sorted(
            status_lengths.items(), key=lambda item: item[1], reverse=True
        ):
            share = 100.0 * length / total_status
            print(f"  {status:<16} {length / 1000.0:8.3f} km  {share:5.1f}%")


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
