"""Dominancia de Pareto considerando o estado fisico.

O ponto delicado da busca: duas labels que chegam ao mesmo no com metricas
parecidas podem ter velocidades finais diferentes, e o proximo trecho depende
da velocidade de entrada. Descartar uma delas comparando apenas tempo/distancia
pode remover uma rota fisicamente melhor.

Para o MVP usamos **discretizacao da velocidade**: a fronteira e indexada por
``(no, bucket_de_velocidade)`` e so comparamos labels dentro do mesmo bucket.
E uma aproximacao configuravel — a mesma politica de buckets deve ser usada na
chave de estado e na dominancia.

Nao afirmamos que "velocidade maior domina velocidade menor": isso nao e
universalmente verdadeiro (curvas, limites, frenagem, energia).
"""

from __future__ import annotations

import math
from collections.abc import Hashable
from typing import Any, Protocol, runtime_checkable

from .objectives import ObjectiveSet
from .objectives import dominates as pareto_dominates

DEFAULT_SPEED_STEP_MPS = 0.5


@runtime_checkable
class Dominance(Protocol):
    """Relacao de dominancia entre labels de um mesmo estado fisico."""

    objectives: ObjectiveSet

    def key(self, state: Any) -> Hashable:
        """Chave de fronteira (tipicamente ``(no, bucket)``)."""

    def bucket(self, speed_mps: float) -> int:
        """Intervalo de velocidade de uma velocidade em m/s."""

    def dominates(self, a: Any, b: Any) -> bool:
        """True se ``a`` domina ``b``."""


def speed_bucket(speed_mps: float, step_mps: float) -> int:
    """Intervalo ``[k*step, (k+1)*step)`` a que pertence ``speed_mps``."""
    if not math.isfinite(step_mps) or step_mps <= 0.0:
        raise ValueError(f"step_mps deve ser positivo e finito (recebido {step_mps!r})")
    speed = max(0.0, float(speed_mps))
    return int(speed // step_mps)


class SpeedBucketDominance:
    """Dominancia por objetivos, somente dentro do mesmo no e bucket."""

    def __init__(
        self,
        objectives: ObjectiveSet,
        *,
        speed_step_mps: float = DEFAULT_SPEED_STEP_MPS,
    ) -> None:
        if not math.isfinite(speed_step_mps) or speed_step_mps <= 0.0:
            raise ValueError(
                "speed_step_mps deve ser positivo e finito "
                f"(recebido {speed_step_mps!r})"
            )
        self.objectives = objectives
        self.speed_step_mps = float(speed_step_mps)

    def bucket(self, speed_mps: float) -> int:
        return speed_bucket(speed_mps, self.speed_step_mps)

    def key(self, state: Any) -> tuple[Hashable, int]:
        return (state.node_id, self.bucket(state.physical_state.speed_mps))

    def dominates(self, a: Any, b: Any) -> bool:
        if a.node_id != b.node_id:
            return False
        if self.bucket(a.physical_state.speed_mps) != self.bucket(
            b.physical_state.speed_mps
        ):
            return False
        return pareto_dominates(
            self.objectives.values(a), self.objectives.values(b)
        )
