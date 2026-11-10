"""Simplificacao topologica: contrai nos de grau 2 sem perder atributos.

O caso tipico no OSM e uma avenida dividida em varias ``way`` s que so se
encontram em pontos intermediarios. Topologicamente esses pontos nao sao
decisoes de navegacao e podem sumir:

    A --- B --- C --- D   ->   A ----------- D

Mas a aresta consolidada continua guardando os segmentos originais, cada um
com distancia, superficie, perfil de elevacao e restricoes proprias. Se A-B e
asfalto e B-C e gravel, a mudanca sobrevive na lista de segmentos.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Hashable

from .model import CyclingGraph, Edge, GraphError

Coord = tuple[float, float]


@dataclass(frozen=True)
class SimplifyOptions:
    """``keep_nodes`` protege pontos que precisam existir (ex.: POIs, snapping)."""

    keep_nodes: frozenset[Hashable] = frozenset()


@dataclass(frozen=True)
class SimplifyStats:
    nodes_before: int
    nodes_after: int
    edges_before: int
    edges_after: int
    contracted_nodes: int
    chains: int
    multi_segment_edges: int

    @property
    def node_reduction(self) -> float:
        if not self.nodes_before:
            return 0.0
        return 1.0 - self.nodes_after / self.nodes_before


def simplify_graph(
    graph: CyclingGraph,
    options: SimplifyOptions | None = None,
) -> tuple[CyclingGraph, SimplifyStats]:
    """Retorna um novo grafo com os nos de passagem contraidos."""
    options = options or SimplifyOptions()
    incoming, outgoing = _incidence(graph)
    candidates = _contraction_candidates(graph, incoming, outgoing)
    candidates -= set(options.keep_nodes)
    candidates -= _cycle_nodes(graph, candidates)

    anchors = [node_id for node_id in graph.nodes if node_id not in candidates]
    contracted = graph.node_count - len(anchors)

    simplified = CyclingGraph()
    simplified.metadata = dict(graph.metadata)
    simplified.metadata["simplified"] = True

    for node_id in anchors:
        simplified.add_node(graph.get_node(node_id))

    consumed: set[str] = set()
    chains = 0

    for anchor in sorted(anchors, key=str):
        for edge in sorted(outgoing.get(anchor, ()), key=lambda item: item.id):
            if edge.id in consumed:
                continue

            segments = list(edge.segments)
            consumed.add(edge.id)
            current = edge
            node = edge.target

            while node in candidates:
                next_edges = [
                    candidate
                    for candidate in outgoing.get(node, ())
                    if candidate.id not in consumed and candidate.target != current.source
                ]
                if not next_edges:
                    next_edges = [
                        candidate
                        for candidate in outgoing.get(node, ())
                        if candidate.id not in consumed
                    ]
                if not next_edges:
                    break

                following = sorted(next_edges, key=lambda item: item.id)[0]
                consumed.add(following.id)
                segments.extend(following.segments)
                current = following
                node = following.target

            if node == anchor:
                # Ciclo inteiramente contraivel: nao deveria chegar aqui.
                continue

            merged = Edge(
                id=f"e{chains}",
                source=anchor,
                target=node,
                segments=tuple(segments),
                geometry=_concat_geometry(segment.geometry for segment in segments),
            )
            simplified.add_edge(merged)
            chains += 1

    leftover = set(graph.edges) - consumed
    if leftover:
        raise GraphError(
            f"simplificacao incompleta: {len(leftover)} aresta(s) sem cadeia, "
            f"ex.: {sorted(leftover)[:3]}"
        )

    stats = SimplifyStats(
        nodes_before=graph.node_count,
        nodes_after=simplified.node_count,
        edges_before=graph.edge_count,
        edges_after=simplified.edge_count,
        contracted_nodes=contracted,
        chains=chains,
        multi_segment_edges=sum(
            1 for edge in simplified.edges.values() if edge.segment_count > 1
        ),
    )
    simplified.metadata["simplification"] = {
        "contracted_nodes": stats.contracted_nodes,
        "chains": stats.chains,
        "multi_segment_edges": stats.multi_segment_edges,
    }
    return simplified, stats


# --------------------------------------------------------------------------
# Identificacao dos nos contraiveis
# --------------------------------------------------------------------------
def _incidence(
    graph: CyclingGraph,
) -> tuple[dict[object, list[Edge]], dict[object, list[Edge]]]:
    incoming: dict[object, list[Edge]] = defaultdict(list)
    outgoing: dict[object, list[Edge]] = defaultdict(list)
    for edge in graph.edges.values():
        outgoing[edge.source].append(edge)
        incoming[edge.target].append(edge)
    return incoming, outgoing


def _contraction_candidates(
    graph: CyclingGraph,
    incoming: dict[object, list[Edge]],
    outgoing: dict[object, list[Edge]],
) -> set[object]:
    parallel_endpoints: set[object] = set()
    multiplicity = Counter((edge.source, edge.target) for edge in graph.edges.values())
    for (source, target), count in multiplicity.items():
        if count > 1:
            parallel_endpoints.add(source)
            parallel_endpoints.add(target)

    candidates: set[object] = set()
    for node_id in graph.nodes:
        if node_id in parallel_endpoints:
            continue

        ins = incoming.get(node_id, ())
        outs = outgoing.get(node_id, ())

        # Passagem pura: mesmo numero de entradas e saidas (1 em one-way,
        # 2 em via de mao dupla), sempre com dois vizinhos distintos.
        if len(ins) != len(outs) or len(ins) not in (1, 2):
            continue

        neighbors = {edge.source for edge in ins} | {edge.target for edge in outs}
        if len(neighbors) != 2:
            continue
        if len({edge.source for edge in ins}) != len(ins):
            continue
        if len({edge.target for edge in outs}) != len(outs):
            continue

        candidates.add(node_id)

    return candidates


def _cycle_nodes(graph: CyclingGraph, candidates: set[Hashable]) -> set[Hashable]:
    """Ciclos formados so por candidatos precisam manter um no quebra-ciclo."""
    adjacency: dict[Hashable, set[Hashable]] = {node: set() for node in candidates}
    for edge in graph.edges.values():
        if edge.source in candidates and edge.target in candidates:
            adjacency[edge.source].add(edge.target)
            adjacency[edge.target].add(edge.source)

    visited: set[Hashable] = set()
    cycles: set[Hashable] = set()

    for start in candidates:
        if start in visited:
            continue
        component: list[Hashable] = []
        stack = [start]
        while stack:
            node = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            component.append(node)
            stack.extend(adjacency[node] - visited)

        if len(component) >= 3 and all(len(adjacency[node]) == 2 for node in component):
            cycles.update(component)

    return cycles


def _concat_geometry(geometries) -> tuple[Coord, ...]:
    points: list[Coord] = []
    for geometry in geometries:
        for point in geometry:
            if points and points[-1] == point:
                continue
            points.append(point)
    return tuple(points)
