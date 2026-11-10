# Referencia da API

> Gerado automaticamente por `scripts/generate_api_reference.py`. Nao edite a mao.

Versao: **0.11.0** - 135 simbolos publicos (`api.__all__`).

Todas as assinaturas sao extraidas do codigo por introspeccao. A descricao de cada camada e curada; o resumo de cada simbolo vem da propria docstring (use `help(obj)` para o texto completo).

## Sumario

- [Grafo ciclavel: modelo](#grafo-ciclavel-modelo)
- [Grafo ciclavel: superficie](#grafo-ciclavel-superficie)
- [Grafo ciclavel: restricoes de acesso](#grafo-ciclavel-restricoes-de-acesso)
- [Grafo ciclavel: simplificacao](#grafo-ciclavel-simplificacao)
- [Snapping (grafo de consulta)](#snapping-grafo-de-consulta)
- [Fisica: travessia](#fisica-travessia)
- [Fisica: energia e bateria](#fisica-energia-e-bateria)
- [Busca: objetivos e perfis](#busca-objetivos-e-perfis)
- [Busca: estado, fronteira e A*](#busca-estado-fronteira-e-a)
- [Busca: reconstrucao e avaliacao de rotas](#busca-reconstrucao-e-avaliacao-de-rotas)
- [Selecao: candidatas, ranking e diversidade](#selecao-candidatas-ranking-e-diversidade)
- [Selecao: N rotas, explicacao e pipeline](#selecao-n-rotas-explicacao-e-pipeline)
- [Energia da rota (pos-selecao)](#energia-da-rota-pos-selecao)

## Grafo ciclavel: modelo

Estruturas centrais do grafo: nos, segmentos, arestas direcionadas e o conteiner ``CyclingGraph``.

### `BicycleAccess`

```python
class BicycleAccess(str, Enum)
```

Permissao de circulacao observada no OSM.

Valores: `YES`, `DISMOUNT`.

### `CyclingGraph`

```python
class CyclingGraph
```

Grafo direcionado com adjacencia por origem.

### `Edge`

```python
class Edge(id: str, source: Hashable, target: Hashable, segments: tuple[EdgeSegment, ...], geometry: tuple[tuple[float, float], ...] = ())
```

Aresta direcionada composta por um ou mais segmentos consecutivos.

### `EdgeSegment`

```python
class EdgeSegment(id: str, distance_m: float, surface: Surface = <Surface.UNKNOWN: 'unknown'>, surface_status: SurfaceStatus = <SurfaceStatus.UNKNOWN: 'unknown'>, elevation_gain_m: float = 0.0, elevation_loss_m: float = 0.0, min_elevation_m: float | None = None, max_elevation_m: float | None = None, elevation_profile: tuple[ElevationSample, ...] = (), geometry: tuple[tuple[float, float], ...] = (), highway: str | None = None, name: str | None = None, osm_way_id: int | None = None, bicycle_access: BicycleAccess = <BicycleAccess.YES: 'yes'>, max_speed_kmh: float | None = None, restrictions: tuple[AccessRestriction, ...] = (), tags: Mapping[str, str] = <factory>)
```

Trecho com atributos homogeneos entre dois pontos de forma do OSM.

### `ElevationSample`

```python
class ElevationSample(distance_m: float, elevation_m: float, source: str = '', resolution_m: float | None = None)
```

Altitude a ``distance_m`` metros do inicio do segmento.

### `Node`

```python
class Node(id: Hashable, lat: float, lon: float, elevation_m: float | None = None, osm_id: int | None = None, tags: Mapping[str, str] = <factory>)
```

Posicao geografica. ``elevation_m`` e opcional (pode nao existir DEM).

## Grafo ciclavel: superficie

Classificacao observavel de superficie e a politica de prioridade (ordinal) do roteador.

### `OSM_SURFACE_MAP`

```python
OSM_SURFACE_MAP
```

Mapeia valores de ``surface=*`` do OSM para ``Surface``.

### `OSM_TRACKTYPE_MAP`

```python
OSM_TRACKTYPE_MAP
```

Mapeia ``tracktype=grade1..grade5`` para ``Surface``.

### `SURFACE_PRIORITY`

```python
SURFACE_PRIORITY
```

Prioridade ordinal por superficie (1 melhor ... 6 desconhecida).

### `Surface`

```python
class Surface(str, Enum)
```

Valores: `ASPHALT`, `CONCRETE`, `PAVED`, `COMPACTED_GRAVEL`, `GRAVEL`, `DIRT`, `SAND`, `UNKNOWN`.

### `SurfaceStatus`

```python
class SurfaceStatus(str, Enum)
```

Proveniencia da classificacao de superficie.

Valores: `MAPPED`, `UNMAPPED`, `INFERRED`, `UNKNOWN`.

### `surface_from_tags`

```python
surface_from_tags(tags: Mapping[str, str]) -> Surface
```

Atalho somente da superficie observada (ver ``surface_observation``).

### `surface_observation`

```python
surface_observation(tags: Mapping[str, str]) -> tuple[Surface, SurfaceStatus]
```

Deriva superficie e proveniencia apenas do que esta mapeado no OSM.

### `surface_priority`

```python
surface_priority(surface: Surface) -> int
```

Prioridade ordinal de uma superficie (1 = melhor).

## Grafo ciclavel: restricoes de acesso

Restricoes de acesso preservadas das tags OSM, sem avaliacao temporal.

### `AccessRestriction`

```python
class AccessRestriction(scope: str, value: str, condition: str | None, raw: str)
```

Condicao de acesso preservada, ainda nao avaliada.

### `parse_conditional_restrictions`

```python
parse_conditional_restrictions(tags: Mapping[str, str]) -> tuple[AccessRestriction, ...]
```

Extrai todas as tags ``*:conditional`` sem interpretar a condicao.

## Grafo ciclavel: simplificacao

Contracao de nos de grau 2 sem perder atributos fisicos nem de acesso.

### `SimplifyOptions`

```python
class SimplifyOptions(keep_nodes: frozenset[typing.Hashable] = frozenset())
```

``keep_nodes`` protege pontos que precisam existir (ex.: POIs, snapping).

### `SimplifyStats`

```python
class SimplifyStats(nodes_before: int, nodes_after: int, edges_before: int, edges_after: int, contracted_nodes: int, chains: int, multi_segment_edges: int)
```

SimplifyStats(nodes_before: 'int', nodes_after: 'int', edges_before: 'int', edges_after: 'int', contracted_nodes: 'int', chains: 'int', multi_segment_edges: 'int')

### `simplify_graph`

```python
simplify_graph(graph: CyclingGraph, options: SimplifyOptions | None = None) -> tuple[CyclingGraph, SimplifyStats]
```

Retorna um novo grafo com os nos de passagem contraidos.

## Snapping (grafo de consulta)

Conexao de origem/destino a rede: opcoes, candidatos, resultado e o grafo temporario de consulta.

### `QueryGraph`

```python
class QueryGraph(graph: CyclingGraph, origin_id: Hashable, destination_id: Hashable, origin: snapping.SnapCandidate, destination: snapping.SnapCandidate, virtual_nodes: frozenset[typing.Hashable] = <factory>)
```

Grafo temporario pronto para a busca de rotas.

### `SnapCandidate`

```python
class SnapCandidate(label: str, kind: Literal['node', 'edge'], point: tuple[float, float], offset_m: float, node_id: Hashable | None = None, edge_id: str | None = None, segment_id: str | None = None, segment_index: int | None = None, along_m: float | None = None, fraction: float | None = None)
```

Ponto escolhido para conectar a consulta a rede.

### `SnapError`

```python
class SnapError(ValueError)
```

Nao foi possivel conectar o ponto a rede ciclavel.

### `SnapOptions`

```python
class SnapOptions(max_distance_m: float = 100.0, node_preference_m: float = 10.0, node_offset_tolerance_m: float = 2.0, min_split_distance_m: float = 1.0, allow_dismount: bool = True, cell_size_m: float | None = None)
```

Parametros do snapping.

### `SnapResult`

```python
class SnapResult(candidate: snapping.SnapCandidate, node_id: Hashable, virtual: bool, splits: tuple[snapping._EdgeSplit, ...] = (), elevation_m: float | None = None)
```

Plano de conexao de um ponto, aplicavel a uma copia do grafo.

### `SpatialSnapper`

```python
class SpatialSnapper(graph: CyclingGraph, options: snapping.SnapOptions | None = None)
```

Indexa arestas e nos e projeta coordenadas na rede.

### `build_query_graph`

```python
build_query_graph(graph: CyclingGraph, origin: tuple[float, float], destination: tuple[float, float], options: snapping.SnapOptions | None = None) -> snapping.QueryGraph
```

Conecta origem e destino e devolve o grafo temporario de consulta.

## Fisica: travessia

Modelos do ciclista e da bicicleta, perfis de aresta e a simulacao de travessia (tempo, energia e velocidade).

### `BicycleModel`

```python
class BicycleModel(mass_kg: float = 12.0, rolling_resistance: float = 0.005, drag_coefficient: float = 0.9, drivetrain_efficiency: float = 0.97, wheel_radius_m: float = 0.35)
```

Caracteristicas fisicas da bicicleta.

### `CyclistModel`

```python
class CyclistModel(mass_kg: float, max_power_w: float, sustainable_power_w: float, frontal_area_m2: float)
```

Caracteristicas fisicas do ciclista.

### `EdgeProfile`

```python
class EdgeProfile(edge_id: str, distance_m: float, segments: tuple[SegmentProfile, ...], ascent_m: float, descent_m: float, unknown_elevation_m: float)
```

Perfil fisico completo de uma aresta direcionada.

### `Environment`

```python
class Environment(air_density_kg_m3: float = 1.225, headwind_mps: float = 0.0, gravity_m_s2: float = 9.80665, safe_max_speed_mps: float | None = 22.0)
```

Ambiente fisico da travessia.

### `PhysicalTraversal`

```python
class PhysicalTraversal(step_m: float = 5.0, acceleration_limit_mps2: float = 2.0, dismount_speed_mps: float = 1.4)
```

Simula a travessia fisica de arestas do grafo.

### `RouteMetrics`

```python
class RouteMetrics(time_s: float = 0.0, distance_m: float = 0.0, ascent_m: float = 0.0, descent_m: float = 0.0, energy_j: float = 0.0, mechanical_energy_j: float = 0.0, braking_energy_j: float = 0.0, battery_energy_j: float | None = None)
```

Metricas acumuladas de uma rota.

### `TraversalPath`

```python
class TraversalPath(results: tuple[TraversalResult, ...], metrics: RouteMetrics, initial_speed_mps: float, final_speed_mps: float)
```

Resultado de percorrer arestas em continuidade.

### `TraversalResult`

```python
class TraversalResult(time_s: float, distance_m: float, ascent_m: float, descent_m: float, initial_speed_mps: float, final_speed_mps: float, mechanical_energy_j: float, rider_energy_j: float, battery_energy_j: float | None = None, braking_energy_j: float = 0.0, stalled: bool = False, edge_id: str | None = None)
```

Resultado fisico de percorrer uma aresta.

### `traverse_edge`

```python
traverse_edge(edge: Edge, cyclist: CyclistModel, bicycle: BicycleModel, initial_speed_mps: float = 0.0, environment: Environment | None = None, power_w: float | None = None, *, step_m: float = 5.0) -> TraversalResult
```

Atalho para uma travessia isolada, sem reutilizar cache.

## Fisica: energia e bateria

Modelo energetico (energia mecanica -> eletrica em Wh) e viabilidade de bateria. O perfil eletrico usa energia **mecanica** na fronteira Pareto; a conversao para Wh e um estagio posterior a selecao.

### `BatteryConfig`

```python
class BatteryConfig(capacity_wh: float, initial_charge_wh: float | None = None, reserve_ratio: float = 0.1)
```

Bateria opcional: capacidade, carga inicial e reserva desejada.

### `BatteryFeasibility`

```python
class BatteryFeasibility(capacity_wh: float, available_energy_wh: float, estimated_consumption_wh: float, reserve_energy_wh: float)
```

Viabilidade de uma rota com a bateria configurada.

### `CALIBRATED_LEVEL`

```python
CALIBRATED_LEVEL
```

Nivel de estimativa calibrado com dados reais.

### `EnergyEstimate`

```python
class EnergyEstimate(mechanical_energy_j: float, electrical_energy_j: float, efficiency: float, level: str = 'generic')
```

Estimativa de energia de um trecho, rota ou veiculo.

### `EnergyModel`

```python
class EnergyModel(config: GenericEnergyConfig = <factory>, level: str = 'generic')
```

Converte energia mecanica em energia eletrica estimada.

### `GENERIC_LEVEL`

```python
GENERIC_LEVEL
```

Nivel de estimativa com valores de referencia internos.

### `GenericEnergyConfig`

```python
class GenericEnergyConfig(mass_kg: float = 90.0, rolling_resistance: float = 0.008, drag_coefficient: float = 0.9, frontal_area_m2: float = 0.5, drivetrain_efficiency: float = 0.75)
```

Parametros de referencia do modelo energetico generico.

### `JOULES_PER_WH`

```python
JOULES_PER_WH
```

Fator de conversao de energia (1 Wh = 3600 J).

### `PERSONALIZED_LEVEL`

```python
PERSONALIZED_LEVEL
```

Nivel de estimativa com parametros do veiculo informados.

### `assess_battery`

```python
assess_battery(config: BatteryConfig, consumption_wh: float) -> BatteryFeasibility
```

Avalia se a bateria cobre o consumo estimado respeitando a reserva.

## Busca: objetivos e perfis

Objetivos, perfis declarativos (fastest/shortest/flattest/balanced/electric), tolerancias e configuracao de diversidade.

### `BalancedWeights`

```python
class BalancedWeights(time_s: float = 0.3333333333333333, distance_m: float = 0.3333333333333333, ascent_m: float = 0.3333333333333333)
```

Pesos do score normalizado. Devem somar 1.

### `DiversityConfig`

```python
class DiversityConfig(metric: DiversityMetric = <DiversityMetric.SHARED_DISTANCE_RATIO: 'shared_distance_ratio'>, max_similarity: float = 0.7, fallback: DiversityFallback = <DiversityFallback.RELAX_THRESHOLD: 'relax_threshold'>, relaxation: DiversityRelaxation = <factory>)
```

Configuracao de diversidade do perfil.

### `DiversityFallback`

```python
class DiversityFallback(str, Enum)
```

Politica quando a diversidade impede preencher as N rotas.

Valores: `RETURN_FEWER`, `RELAX_THRESHOLD`, `NONE`.

### `DiversityMetric`

```python
class DiversityMetric(str, Enum)
```

Metricas de semelhanca entre caminhos.

Valores: `EDGE_JACCARD`, `SHARED_DISTANCE_RATIO`.

### `DiversityRelaxation`

```python
class DiversityRelaxation(max_threshold: float = 1.0, step: float = 0.1)
```

Limite e passo do relaxamento progressivo da diversidade.

### `MetricSource`

```python
class MetricSource(Protocol)
```

Qualquer objeto com as metricas lidas pelos objetivos.

### `Objective`

```python
class Objective(str, Enum)
```

Metricas que podem participar da dominancia.

Valores: `TIME`, `DISTANCE`, `ASCENT`, `ENERGY`.

### `ObjectiveEvaluator`

```python
class ObjectiveEvaluator(Protocol)
```

Contrato minimo de extracao de valores objetivo.

### `ObjectiveSet`

```python
class ObjectiveSet(name: str, objectives: tuple[str, ...])
```

Conjunto nomeado de objetivos a minimizar.

### `ObjectiveValues`

```python
class ObjectiveValues(time_s: float, distance_m: float, ascent_m: float, energy_j: float)
```

Metricas finais de uma rota, na forma usada pelos objetivos.

### `PROFILE_CONFIG`

```python
PROFILE_CONFIG
```

``RouteProfile`` (selecao) por id de perfil.

### `PROFILE_IDS`

```python
PROFILE_IDS
```

Ids dos perfis de selecao (``profiles.py``).

### `PROFILE_NAMES`

```python
PROFILE_NAMES
```

Ids dos perfis de busca, em ordem estavel (``objectives.py``).

### `PROFILE_OBJECTIVES`

```python
PROFILE_OBJECTIVES
```

``ObjectiveSet`` (objetivos Pareto) por id de perfil.

### `PROFILES`

```python
PROFILES
```

``SearchProfile`` por id de perfil.

### `RankingStrategy`

```python
class RankingStrategy(str, Enum)
```

Como ordenar rotas nao dominadas.

Valores: `LEXICOGRAPHIC`, `WEIGHTED_NORMALIZED`.

### `RankingTolerance`

```python
class RankingTolerance(time_s: float = 0.0, distance_m: float = 0.0, ascent_m: float = 0.0, energy_j: float = 0.0)
```

Tolerancia por objetivo no ranking lexicografico.

### `RouteObjective`

```python
class RouteObjective(str, Enum)
```

Metricas que podem participar da dominancia.

Valores: `TIME`, `DISTANCE`, `ASCENT`, `ENERGY`.

### `RouteObjectiveEvaluator`

```python
class RouteObjectiveEvaluator
```

Implementacao central: le as metricas ja acumuladas na rota.

### `RouteProfile`

```python
class RouteProfile(id: str, objectives: tuple[Objective, ...], ranking_strategy: RankingStrategy, title: str = '', tolerance: RankingTolerance | None = None, weights: BalancedWeights | None = None, references: ScoreReference | None = None, diversity: DiversityConfig = <factory>)
```

Preferencia de rota: objetivos Pareto, ranking e diversidade.

### `ScoreReference`

```python
class ScoreReference(time_s: float = 1800.0, distance_m: float = 10000.0, ascent_m: float = 100.0, energy_j: float = 0.0)
```

Referencias fixas para o score normalizado do perfil equilibrado.

### `SearchProfile`

```python
class SearchProfile(id: str, objectives: tuple[Objective, ...])
```

Perfil de busca: identificador + objetivos ordenados.

### `dominates`

```python
dominates(values_a: collections.abc.Sequence[float], values_b: collections.abc.Sequence[float]) -> bool
```

Dominancia de Pareto por minimizacao.

### `epsilon_dominates`

```python
epsilon_dominates(values_a: collections.abc.Sequence[float], values_b: collections.abc.Sequence[float], epsilon: float) -> bool
```

Dominancia com tolerancia ``epsilon`` por objetivo.

### `objectives_for`

```python
objectives_for(profile: str) -> ObjectiveSet
```

Devolve o ``ObjectiveSet`` de um perfil, normalizando o nome.

### `profile_for`

```python
profile_for(profile: str) -> SearchProfile
```

Devolve o ``SearchProfile`` de um perfil, normalizando o nome.

### `route_profile_for`

```python
route_profile_for(profile: str) -> RouteProfile
```

Devolve o ``RouteProfile`` de um id, normalizando o nome.

## Busca: estado, fronteira e A*

Nucleo do A* multiobjetivo: estado, dominancia, fronteira Pareto, fila lexicografica e heuristica admissivel.

### `FrontierManager`

```python
class FrontierManager(dominance: Dominance, *, max_labels_per_key: int | None = None, on_discard: collections.abc.Callable[[Any], None] | None = None)
```

Fronteiras nao dominadas por chave de estado fisico.

### `FrontierMap`

```python
class FrontierMap(objectives: ObjectiveSet, *, epsilon: float = 0.0, max_labels_per_node: int | None = None, key: collections.abc.Callable[[Any], collections.abc.Sequence[float]] | None = None, on_discard: collections.abc.Callable[[Any], None] | None = None)
```

Fronteiras Pareto separadas por chave.

### `Heuristic`

```python
class Heuristic(graph: CyclingGraph, *, max_speed_mps: float | None = 22.0)
```

Heuristica geometrica admissivel, independente de perfil.

### `HeuristicBounds`

```python
class HeuristicBounds(time_s: float, distance_m: float, ascent_m: float)
```

Limites inferiores por objetivo para alcancar o destino.

### `LexicographicQueue`

```python
class LexicographicQueue
```

Fila de prioridade ordenada por um vetor de prioridade.

### `MultiObjectiveAStar`

```python
class MultiObjectiveAStar(graph: CyclingGraph, traversal: TraversalModel, profile: SearchProfile | str, *, heuristic: Heuristic | None = None, dominance: Dominance | None = None, config: SearchConfig | None = None, initial_speed_mps: float = 0.0)
```

Busca Pareto por perfil sobre um grafo finito.

### `ParetoFrontier`

```python
class ParetoFrontier(objectives: ObjectiveSet, *, key: collections.abc.Callable[[Any], collections.abc.Sequence[float]] | None = None, epsilon: float = 0.0, max_size: int | None = None, on_discard: collections.abc.Callable[[Any], None] | None = None)
```

Colecao de itens nao dominados segundo um ``ObjectiveSet``.

### `PhysicalState`

```python
class PhysicalState(speed_mps: float, kinetic_energy_j: float)
```

Estado fisico necessario para a proxima travessia.

### `PhysicalTraversalModel`

```python
class PhysicalTraversalModel(traversal: PhysicalTraversal, cyclist: CyclistModel, bicycle: BicycleModel, environment: Environment | None = None, power_w: float | None = None)
```

Liga ``PhysicalTraversal`` aos modelos de ciclista, bicicleta e ambiente.

### `SearchConfig`

```python
class SearchConfig(max_labels_per_node: int | None = None, speed_step_mps: float = 0.5, epsilon_dominance: float = 0.0, max_expansions: int | None = None)
```

Parametros de execucao da busca.

### `SearchResult`

```python
class SearchResult(origin: collections.abc.Hashable, destination: collections.abc.Hashable, profile: SearchProfile, labels: tuple[SearchState, ...], expanded: int = 0, generated: int = 0, truncated: bool = False)
```

Fronteira Pareto de destino devolvida por ``MultiObjectiveAStar``.

### `SearchState`

```python
class SearchState(node_id: collections.abc.Hashable, physical_state: PhysicalState, time_s: float = 0.0, distance_m: float = 0.0, ascent_m: float = 0.0, descent_m: float = 0.0, energy_j: float = 0.0, parent: 'SearchState | None' = None, incoming_edge_id: str | None = None, label_id: int = 0, active: bool = True)
```

Label de busca: metricas acumuladas + estado fisico + reconstrucao.

### `SpeedBucketDominance`

```python
class SpeedBucketDominance(objectives: ObjectiveSet, *, speed_step_mps: float = 0.5)
```

Dominancia por objetivos, somente dentro do mesmo no e bucket.

### `TraversalModel`

```python
class TraversalModel(Protocol)
```

Contrato minimo que a busca espera do modelo fisico.

### `UNKNOWN_SPEED`

```python
UNKNOWN_SPEED
```

Sentinela de velocidade inicial desconhecida na busca.

### `advance_state`

```python
advance_state(current: SearchState, edge: Edge, result: TraversalResult, *, mass_kg: float, label_id: int) -> SearchState
```

Acumula a travessia de ``edge`` em uma nova label.

### `initial_state`

```python
initial_state(node_id: collections.abc.Hashable, mass_kg: float, initial_speed_mps: float = 0.0, *, label_id: int = 0) -> SearchState
```

Label inicial na origem, sem custo acumulado.

### `model_max_speed`

```python
model_max_speed(traversal: TraversalModel) -> float | None | _UnknownSpeedSentinel
```

Teto de velocidade **declarado** pelo modelo, se houver.

### `route_edges`

```python
route_edges(state: SearchState) -> list[str | None]
```

Reconstroi a sequencia de arestas da origem ate ``state``.

## Busca: reconstrucao e avaliacao de rotas

Reconstrucao da fronteira em rotas e avaliacao de objetivos.

### `Route`

```python
class Route(edge_ids: tuple[str | None, ...], time_s: float, distance_m: float, ascent_m: float, descent_m: float, energy_j: float, label_id: int = 0, edge_lengths: tuple[float, ...] = ())
```

Rota reconstruida: arestas direcionadas, comprimentos e metricas.

### `evaluate`

```python
evaluate(source: MetricSource, evaluator: ObjectiveEvaluator | None = None) -> ObjectiveValues
```

Atalho: avalia ``source`` com o avaliador dado (ou o central).

### `evaluate_metrics`

```python
evaluate_metrics(metrics: MetricSource, evaluator: ObjectiveEvaluator | None = None) -> ObjectiveValues
```

Compatibilidade: avalia um conjunto de metricas.

### `evaluate_route`

```python
evaluate_route(route: MetricSource, evaluator: ObjectiveEvaluator | None = None) -> ObjectiveValues
```

Compatibilidade: avalia uma rota (mesmo que ``evaluate``).

### `route_from_state`

```python
route_from_state(state: SearchState) -> Route
```

Reconstroi uma ``Route`` de uma label de destino.

### `routes_from_result`

```python
routes_from_result(result: SearchResult) -> tuple[Route, ...]
```

Converte a fronteira de destino de um ``SearchResult`` em rotas.

## Selecao: candidatas, ranking e diversidade

Pool de candidatas (com deduplicacao), ranking por perfil e diversidade.

### `CandidateMetrics`

```python
class CandidateMetrics(time_s: float, distance_m: float, ascent_m: float, descent_m: float, energy_j: float)
```

Metricas finais de uma candidata (objetivos + descida).

### `DeduplicationMode`

```python
class DeduplicationMode(str, Enum)
```

Como decidir que duas candidatas sao a mesma alternativa.

Valores: `PATH`, `METRICS`, `PATH_AND_METRICS`.

### `ProfileRanker`

```python
class ProfileRanker(evaluator: ObjectiveEvaluator | None = None)
```

Componente de ranking: ordena candidatas segundo o perfil.

### `RankedCandidate`

```python
class RankedCandidate(candidate: RouteCandidate, rank: int, profile_score: float | None = None)
```

Candidata ordenada: posicao, candidata e score (None se lexicografico).

### `RankedRoute`

```python
class RankedRoute(route: Route, rank: int, profile_score: float | None = None)
```

Compatibilidade: rota ordenada (sem a identidade da candidata).

### `RouteCandidate`

```python
class RouteCandidate(route_id: str, route: Route, metrics: CandidateMetrics)
```

Alternativa candidata: identidade + rota reconstruida + metricas.

### `RouteCandidatePool`

```python
class RouteCandidatePool(candidates: tuple[RouteCandidate, ...] = (), dropped_duplicates: int = 0)
```

Conjunto de candidatas nao dominadas, ja deduplicado.

### `RouteDeduplicator`

```python
class RouteDeduplicator(mode: DeduplicationMode = <DeduplicationMode.PATH: 'path'>, metric_quantum: float = 0.001)
```

Remove candidatas repetidas mantendo a primeira ocorrencia.

### `RouteDiversity`

```python
class RouteDiversity(metric: DiversityMetric = <DiversityMetric.SHARED_DISTANCE_RATIO: 'shared_distance_ratio'>, threshold: float = 0.7)
```

Componente de diversidade: metrica + limiar configurados juntos.

### `edge_jaccard`

```python
edge_jaccard(a: Route, b: Route) -> float
```

Similaridade de Jaccard sobre as arestas direcionadas.

### `is_too_similar`

```python
is_too_similar(a: Route, b: Route, metric: DiversityMetric, threshold: float) -> bool
```

True quando a semelhanca excede ``threshold``.

### `order_routes`

```python
order_routes(routes: collections.abc.Iterable[Route], profile: RouteProfile, *, evaluator: ObjectiveEvaluator | None = None) -> list[Route]
```

Atalho: apenas as rotas, na ordem de preferencia do perfil.

### `profile_score`

```python
profile_score(route: Route, profile: RouteProfile, *, evaluator: ObjectiveEvaluator | None = None) -> float | None
```

Score escalar do perfil para uma rota (None se lexicografico).

### `rank_candidates`

```python
rank_candidates(candidates: collections.abc.Iterable[RouteCandidate], profile: RouteProfile, *, evaluator: ObjectiveEvaluator | None = None) -> list[RankedCandidate]
```

Ordena candidatas pela preferencia do perfil (rank 0 = melhor).

### `rank_routes`

```python
rank_routes(routes: collections.abc.Iterable[Route], profile: RouteProfile, *, evaluator: ObjectiveEvaluator | None = None) -> list[RankedRoute]
```

Ordena rotas pela preferencia do perfil (rank 0 = melhor).

### `route_diversity`

```python
route_diversity(a: Route, b: Route, metric: DiversityMetric) -> float
```

Semelhanca entre ``a`` e ``b`` segundo ``metric`` (0 = distintas).

### `route_similarity`

```python
route_similarity(a: Route, b: Route) -> float
```

Alias de ``edge_jaccard`` (compatibilidade com a API anterior).

### `shared_distance_ratio`

```python
shared_distance_ratio(a: Route, b: Route) -> float
```

Proporcao de distancia compartilhada, em ``[0, 1]``.

## Selecao: N rotas, explicacao e pipeline

Escolha das N rotas (com fallback de diversidade), explicacao e o contrato de alto nivel ``search_profile``.

### `ProfileSearchRequest`

```python
class ProfileSearchRequest(origin: collections.abc.Hashable, destination: collections.abc.Hashable, profile: RouteProfile, max_routes: int = 3, initial_speed_mps: float = 0.0, energy_model: EnergyModel | None = None, battery: BatteryConfig | None = None)
```

Pedido de busca para um perfil concreto.

### `ProfileSearchResponse`

```python
class ProfileSearchResponse(profile_id: str, routes: tuple[SelectedRoute, ...], pareto_route_count: int, selection: SelectionMetadata, explanations: tuple[RouteExplanation, ...] = (), energy: tuple[RouteEnergyEstimate, ...] = (), reached: bool = False)
```

Resposta: rotas selecionadas + explicacoes alinhadas por indice.

### `RouteExplanation`

```python
class RouteExplanation(headline: str, details: tuple[str, ...] = (), tradeoffs: tuple[str, ...] = ())
```

Justificativa textual de uma rota selecionada.

### `RouteExplainer`

```python
class RouteExplainer(evaluator: ObjectiveEvaluator | None = None)
```

Produz explicacoes derivadas das metricas e do conjunto comparado.

### `RouteSelectionRequest`

```python
class RouteSelectionRequest(max_routes: int, min_routes: int = 1, diversity: DiversityConfig | None = None)
```

Como escolher as N rotas (limite de apresentacao).

### `RouteSelectionResult`

```python
class RouteSelectionResult(selected: tuple[SelectedRoute, ...], pareto_route_count: int, rejected_as_similar_count: int, diversity_relaxed: bool, threshold_used: float | None = None, dropped_duplicates: int = 0)
```

Resultado da selecao.

### `RouteSelector`

```python
class RouteSelector(evaluator: ObjectiveEvaluator | None = None)
```

Componente de selecao: escolhe ate N candidatas diversas.

### `SelectedRoute`

```python
class SelectedRoute(candidate: RouteCandidate, rank: int, profile_score: float | None, selection_reason: SelectionReason)
```

Candidata escolhida: posicao, score do perfil e razao da escolha.

### `SelectionConfig`

```python
class SelectionConfig(max_routes: int, min_routes: int = 1, diversity: DiversityConfig | None = None)
```

Como escolher as N rotas (limite de apresentacao).

### `SelectionMetadata`

```python
class SelectionMetadata(requested_count: int, selected_count: int, diversity_relaxed: bool, selection_strategy: str, threshold_used: float | None = None, dropped_duplicates: int = 0)
```

Metadados da selecao apresentados junto com a resposta.

### `SelectionReason`

```python
class SelectionReason(primary_objective: Objective, primary_value: float, diversity_accepted: bool)
```

Por que a rota entrou: objetivo primario e aceite de diversidade.

### `SelectionResult`

```python
class SelectionResult(selected: tuple[SelectedRoute, ...], pareto_route_count: int, rejected_as_similar_count: int, diversity_relaxed: bool, threshold_used: float | None = None, dropped_duplicates: int = 0)
```

Resultado da selecao.

### `explain_route`

```python
explain_route(route: Route, profile: RouteProfile, reason: SelectionReason, *, candidates: collections.abc.Iterable[Route] = (), evaluator: ObjectiveEvaluator | None = None) -> RouteExplanation
```

Atalho funcional para ``RouteExplainer().explain``.

### `search_profile`

```python
search_profile(graph: CyclingGraph, traversal: TraversalModel, request: ProfileSearchRequest, *, heuristic: Heuristic | None = None, search_config: SearchConfig | None = None, selection_config: SelectionConfig | None = None, deduplicator: RouteDeduplicator | None = None, explain: bool = True) -> ProfileSearchResponse
```

Executa busca + selecao para um ``ProfileSearchRequest``.

### `select_candidates`

```python
select_candidates(candidates: collections.abc.Iterable[RouteCandidate], profile: RouteProfile, config: SelectionConfig | None = None, *, evaluator: ObjectiveEvaluator | None = None) -> SelectionResult
```

Seleciona ate ``config.max_routes`` candidatas, em ordem de preferencia.

### `select_from_result`

```python
select_from_result(result: SearchResult, profile: RouteProfile | str | None = None, config: SelectionConfig | None = None, *, evaluator: ObjectiveEvaluator | None = None, deduplicator: RouteDeduplicator | None = None) -> SelectionResult
```

Atalho: forma o pool a partir de um ``SearchResult`` e seleciona.

### `select_routes`

```python
select_routes(routes: collections.abc.Iterable[Route], profile: RouteProfile, config: SelectionConfig | None = None, *, evaluator: ObjectiveEvaluator | None = None, deduplicator: RouteDeduplicator | None = None) -> SelectionResult
```

Atalho: forma o pool de candidatas (com dedup) e seleciona.

## Energia da rota (pos-selecao)

Estimativa de energia eletrica de uma rota, alinhada as rotas selecionadas.

### `RouteEnergyEstimate`

```python
class RouteEnergyEstimate(route_id: str, estimate: EnergyEstimate, battery: BatteryFeasibility | None = None)
```

Energia estimada de uma rota + viabilidade de bateria (opcional).

### `estimate_route_energy`

```python
estimate_route_energy(route: Route, model: EnergyModel | None = None, *, battery: BatteryConfig | None = None, route_id: str = '') -> RouteEnergyEstimate
```

Converte a energia mecanica de ``route`` em estimativa eletrica.

### `estimate_routes_energy`

```python
estimate_routes_energy(routes: collections.abc.Iterable[Route], model: EnergyModel | None = None, *, battery: BatteryConfig | None = None, route_ids: collections.abc.Iterable[str] | None = None) -> tuple[RouteEnergyEstimate, ...]
```

Estima a energia de varias rotas, alinhando ``route_ids`` por indice.
