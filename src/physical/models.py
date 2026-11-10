"""Estruturas de saida da camada fisica."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True, slots=True)
class TraversalResult:
    """Resultado fisico de percorrer uma aresta.

    ``mechanical_energy_j`` e o trabalho aplicado na roda. ``rider_energy_j``
    e o trabalho no pedivela (roda / eficiencia). ``battery_energy_j`` fica
    ``None`` enquanto a bicicleta for convencional.
    """

    time_s: float
    distance_m: float
    ascent_m: float
    descent_m: float
    initial_speed_mps: float
    final_speed_mps: float
    mechanical_energy_j: float
    rider_energy_j: float
    battery_energy_j: float | None = None
    braking_energy_j: float = 0.0
    stalled: bool = False
    edge_id: str | None = None

    @property
    def average_speed_mps(self) -> float:
        if self.time_s <= 0.0:
            return 0.0
        return self.distance_m / self.time_s

    @property
    def average_speed_kmh(self) -> float:
        return 3.6 * self.average_speed_mps

    def to_metrics(self) -> "RouteMetrics":
        return RouteMetrics(
            time_s=self.time_s,
            distance_m=self.distance_m,
            ascent_m=self.ascent_m,
            descent_m=self.descent_m,
            energy_j=self.rider_energy_j,
            mechanical_energy_j=self.mechanical_energy_j,
            braking_energy_j=self.braking_energy_j,
            battery_energy_j=self.battery_energy_j,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "edge_id": self.edge_id,
            "time_s": round(self.time_s, 3),
            "distance_m": round(self.distance_m, 3),
            "ascent_m": round(self.ascent_m, 3),
            "descent_m": round(self.descent_m, 3),
            "initial_speed_mps": round(self.initial_speed_mps, 3),
            "final_speed_mps": round(self.final_speed_mps, 3),
            "average_speed_mps": round(self.average_speed_mps, 3),
            "average_speed_kmh": round(self.average_speed_kmh, 3),
            "mechanical_energy_j": round(self.mechanical_energy_j, 3),
            "rider_energy_j": round(self.rider_energy_j, 3),
            "battery_energy_j": (
                None
                if self.battery_energy_j is None
                else round(self.battery_energy_j, 3)
            ),
            "braking_energy_j": round(self.braking_energy_j, 3),
            "stalled": self.stalled,
        }


@dataclass(frozen=True, slots=True)
class RouteMetrics:
    """Metricas acumuladas de uma rota.

    A busca Pareto pode somar ``TraversalResult`` sem conhecer as equacoes
    fisicas. ``energy_j`` e a energia do ciclista (pedivela).
    """

    time_s: float = 0.0
    distance_m: float = 0.0
    ascent_m: float = 0.0
    descent_m: float = 0.0
    energy_j: float = 0.0
    mechanical_energy_j: float = 0.0
    braking_energy_j: float = 0.0
    battery_energy_j: float | None = None

    @property
    def average_speed_mps(self) -> float:
        if self.time_s <= 0.0:
            return 0.0
        return self.distance_m / self.time_s

    @property
    def average_speed_kmh(self) -> float:
        return 3.6 * self.average_speed_mps

    def add(self, result: TraversalResult) -> "RouteMetrics":
        battery: float | None = None
        if (
            self.battery_energy_j is not None
            and result.battery_energy_j is not None
        ):
            battery = self.battery_energy_j + result.battery_energy_j

        return RouteMetrics(
            time_s=self.time_s + result.time_s,
            distance_m=self.distance_m + result.distance_m,
            ascent_m=self.ascent_m + result.ascent_m,
            descent_m=self.descent_m + result.descent_m,
            energy_j=self.energy_j + result.rider_energy_j,
            mechanical_energy_j=self.mechanical_energy_j
            + result.mechanical_energy_j,
            braking_energy_j=self.braking_energy_j + result.braking_energy_j,
            battery_energy_j=battery,
        )

    @classmethod
    def from_results(
        cls, results: list[TraversalResult] | tuple[TraversalResult, ...]
    ) -> "RouteMetrics":
        metrics = cls()
        for result in results:
            metrics = metrics.add(result)
        return metrics

    def to_dict(self) -> dict[str, object]:
        return {
            "time_s": round(self.time_s, 3),
            "distance_m": round(self.distance_m, 3),
            "ascent_m": round(self.ascent_m, 3),
            "descent_m": round(self.descent_m, 3),
            "energy_j": round(self.energy_j, 3),
            "mechanical_energy_j": round(self.mechanical_energy_j, 3),
            "braking_energy_j": round(self.braking_energy_j, 3),
            "battery_energy_j": (
                None
                if self.battery_energy_j is None
                else round(self.battery_energy_j, 3)
            ),
            "average_speed_mps": round(self.average_speed_mps, 3),
            "average_speed_kmh": round(self.average_speed_kmh, 3),
        }


@dataclass(frozen=True, slots=True)
class TraversalPath:
    """Resultado de percorrer arestas em continuidade.

    O modelo fisico propaga a velocidade entre arestas consecutivas: a
    velocidade final de uma aresta e a velocidade inicial da proxima. Por
    isso ``final_speed_mps`` e um **estado fisico de saida**, nao uma metrica
    a ser recalculada pela busca.

    A busca Pareto apenas carrega esse estado: ao expandir um label, ela
    reutiliza ``final_speed_mps`` como ``initial_speed_mps`` da proxima
    travessia. Ela nao deve reconstruir a dinamica por conta propria.

    Pensado para comportar, no futuro, outros componentes de estado (por
    exemplo ``battery_wh`` ou ``fatigue_state``) sem quebrar a interface.
    """

    results: tuple[TraversalResult, ...]
    metrics: RouteMetrics
    initial_speed_mps: float
    final_speed_mps: float

    def __iter__(self) -> Iterator[TraversalResult]:
        return iter(self.results)

    def __len__(self) -> int:
        return len(self.results)

    def __getitem__(self, index: int) -> TraversalResult:
        return self.results[index]

    @property
    def edge_ids(self) -> tuple[str | None, ...]:
        return tuple(result.edge_id for result in self.results)

    def to_dict(self) -> dict[str, object]:
        return {
            "initial_speed_mps": round(self.initial_speed_mps, 3),
            "final_speed_mps": round(self.final_speed_mps, 3),
            "edges": len(self.results),
            "metrics": self.metrics.to_dict(),
        }
