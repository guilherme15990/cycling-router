"""Coordenador da camada fisica: aresta -> perfil -> passos -> resultado.

O ``PhysicalTraversal`` nao decide rota. Ele recebe uma aresta direcionada e o
estado de movimento na entrada, simula os passos e devolve tempo, energia e
velocidade final.

A propagacao de velocidade entre arestas consecutivas pertence a **esta**
camada (ver ``traverse_path``), nao a busca Pareto. A busca apenas carrega o
estado fisico devolvido (``TraversalPath.final_speed_mps``) e o reutiliza como
velocidade inicial da proxima travessia.
"""

from __future__ import annotations

from typing import Sequence

from graph.model import BicycleAccess, Edge
from ._validation import non_negative, positive
from .bicycle import BicycleModel
from .cyclist import CyclistModel
from .edge_profile import EdgeProfile, ProfileStep
from .environment import Environment
from .models import RouteMetrics, TraversalPath, TraversalResult
from .speed import advance_speed

DEFAULT_STEP_M = 5.0
DEFAULT_ACCELERATION_LIMIT_MPS2 = 2.0
DEFAULT_DISMOUNT_SPEED_MPS = 1.4


class PhysicalTraversal:
    """Simula a travessia fisica de arestas do grafo.

    O objeto mantem cache de perfis e passos por ``edge.id``. Como arestas do
    grafo e do grafo de consulta sao imutaveis, o cache e seguro. Se uma nova
    aresta reutilizar o mesmo id, a identidade do objeto invalida o cache.
    """

    def __init__(
        self,
        step_m: float = DEFAULT_STEP_M,
        acceleration_limit_mps2: float = DEFAULT_ACCELERATION_LIMIT_MPS2,
        dismount_speed_mps: float = DEFAULT_DISMOUNT_SPEED_MPS,
    ) -> None:
        positive("step_m", step_m)
        non_negative("acceleration_limit_mps2", acceleration_limit_mps2)
        positive("dismount_speed_mps", dismount_speed_mps)

        self.step_m = float(step_m)
        self.acceleration_limit_mps2 = float(acceleration_limit_mps2)
        self.dismount_speed_mps = float(dismount_speed_mps)
        self._profiles: dict[str, tuple[Edge, EdgeProfile]] = {}
        self._steps: dict[str, tuple[Edge, tuple[ProfileStep, ...]]] = {}

    # ------------------------------------------------------------------ cache
    def profile(self, edge: Edge) -> EdgeProfile:
        cached = self._profiles.get(edge.id)
        if cached is not None and cached[0] is edge:
            return cached[1]
        profile = EdgeProfile.from_edge(edge)
        self._profiles[edge.id] = (edge, profile)
        return profile

    def steps(self, edge: Edge) -> tuple[ProfileStep, ...]:
        cached = self._steps.get(edge.id)
        if cached is not None and cached[0] is edge:
            return cached[1]
        steps = self.profile(edge).steps(self.step_m)
        self._steps[edge.id] = (edge, steps)
        return steps

    # -------------------------------------------------------------- travessia
    def traverse(
        self,
        edge: Edge,
        cyclist: CyclistModel,
        bicycle: BicycleModel,
        initial_speed_mps: float = 0.0,
        environment: Environment | None = None,
        power_w: float | None = None,
    ) -> TraversalResult:
        """Percorre ``edge`` e devolve o resultado fisico.

        Args:
            edge: Aresta direcionada a percorrer.
            cyclist: Modelo do ciclista (massa, potencia, area frontal).
            bicycle: Modelo da bicicleta (massa, rolamento, aerodinamica).
            initial_speed_mps: Velocidade na entrada da aresta, em m/s.
            environment: Ambiente (ar, vento, gravidade). Padrao se omitido.
            power_w: Potencia no pedivela. Se omitida, usa
                ``cyclist.default_power_w``.

        Returns:
            ``TraversalResult`` com tempo, energia mecanica, energia de
            frenagem, subida/descida e velocidade final.

        Raises:
            ValueError: Se ``power_w`` for negativo ou exceder
                ``cyclist.max_power_w``, ou se ``initial_speed_mps`` for
                negativo.
        """
        environment = environment or Environment()
        non_negative("initial_speed_mps", initial_speed_mps)

        power = cyclist.default_power_w if power_w is None else float(power_w)
        non_negative("power_w", power)
        if power > cyclist.max_power_w:
            raise ValueError(
                f"power_w ({power}) excede max_power_w ({cyclist.max_power_w})"
            )

        profile = self.profile(edge)
        steps = self.steps(edge)
        mass = cyclist.mass_kg + bicycle.mass_kg

        speed = max(0.0, float(initial_speed_mps))
        time_s = 0.0
        wheel_energy_j = 0.0
        rider_energy_j = 0.0
        braking_energy_j = 0.0
        stalled = False

        for step in steps:
            if step.bicycle_access is BicycleAccess.DISMOUNT:
                walking_speed = self.dismount_speed_mps
                if speed > walking_speed:
                    braking_energy_j += 0.5 * mass * (
                        speed * speed - walking_speed * walking_speed
                    )
                speed = walking_speed
                time_s += step.distance_m / walking_speed
                continue

            step_result = advance_speed(
                distance_m=step.distance_m,
                slope_rad=step.slope_rad,
                initial_speed_mps=speed,
                available_power_w=power,
                mass_kg=mass,
                frontal_area_m2=cyclist.frontal_area_m2,
                bicycle=bicycle,
                environment=environment,
                max_speed_mps=step.max_speed_mps,
                acceleration_limit_mps2=self.acceleration_limit_mps2,
            )
            time_s += step_result.time_s
            wheel_energy_j += step_result.wheel_energy_j
            rider_energy_j += step_result.rider_energy_j
            braking_energy_j += step_result.braking_energy_j
            stalled = stalled or step_result.stalled
            speed = step_result.final_speed_mps

        return TraversalResult(
            time_s=time_s,
            distance_m=profile.distance_m,
            ascent_m=profile.ascent_m,
            descent_m=profile.descent_m,
            initial_speed_mps=max(0.0, float(initial_speed_mps)),
            final_speed_mps=speed,
            mechanical_energy_j=wheel_energy_j,
            rider_energy_j=rider_energy_j,
            battery_energy_j=None,
            braking_energy_j=braking_energy_j,
            stalled=stalled,
            edge_id=edge.id,
        )

    def traverse_path(
        self,
        edges: Sequence[Edge],
        cyclist: CyclistModel,
        bicycle: BicycleModel,
        initial_speed_mps: float = 0.0,
        environment: Environment | None = None,
        power_w: float | None = None,
    ) -> TraversalPath:
        """Percorre arestas em sequencia propagando a velocidade.

        A velocidade final de cada aresta e a velocidade inicial da proxima.
        Como ``TraversalPath`` se comporta como uma sequencia, os resultados
        individuais continuam acessiveis por indice e iteracao.

        O estado fisico de saida (``final_speed_mps``) fica no proprio
        resultado; a busca Pareto so o transporta para a proxima expansao.
        """
        results: list[TraversalResult] = []
        speed = max(0.0, float(initial_speed_mps))
        for edge in edges:
            result = self.traverse(
                edge,
                cyclist,
                bicycle,
                initial_speed_mps=speed,
                environment=environment,
                power_w=power_w,
            )
            results.append(result)
            speed = result.final_speed_mps

        return TraversalPath(
            results=tuple(results),
            metrics=RouteMetrics.from_results(results),
            initial_speed_mps=max(0.0, float(initial_speed_mps)),
            final_speed_mps=speed,
        )


def traverse_edge(
    edge: Edge,
    cyclist: CyclistModel,
    bicycle: BicycleModel,
    initial_speed_mps: float = 0.0,
    environment: Environment | None = None,
    power_w: float | None = None,
    *,
    step_m: float = DEFAULT_STEP_M,
) -> TraversalResult:
    """Atalho para uma travessia isolada, sem reutilizar cache.

    Cria um ``PhysicalTraversal`` efemero a cada chamada. Para percorrer varias
    arestas (ou reusar cache de perfis), crie um ``PhysicalTraversal`` e chame
    ``traverse``/``traverse_path``.

    Args:
        edge: Aresta direcionada a percorrer.
        cyclist: Modelo do ciclista.
        bicycle: Modelo da bicicleta.
        initial_speed_mps: Velocidade na entrada da aresta, em m/s.
        environment: Ambiente (padrao se omitido).
        power_w: Potencia no pedivela (padrao do ciclista se omitida).
        step_m: Tamanho do passo espacial da simulacao, em metros.

    Returns:
        ``TraversalResult`` da aresta.

    Example:
        >>> result = traverse_edge(edge, cyclist, bicycle, power_w=200.0)
        >>> round(result.time_s, 3) >= 0.0
        True
    """
    return PhysicalTraversal(step_m=step_m).traverse(
        edge,
        cyclist,
        bicycle,
        initial_speed_mps=initial_speed_mps,
        environment=environment,
        power_w=power_w,
    )
