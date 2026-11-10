"""Restricoes de acesso observadas no OSM.

Esta camada **preserva** as condicoes; ela nao decide se a aresta pode ser
usada em um dado momento. A avaliacao temporal pertence a preparacao da
consulta (o mesmo grafo pode ser utilizavel as 8h e proibido as 18h).

A distincao importante:

* restricao -> pode ou nao pode passar (ex.: ``bicycle=no``);
* preferencia -> pode passar, mas o roteador pode evitar (ex.: superficie ruim).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True, slots=True)
class AccessRestriction:
    """Condicao de acesso preservada, ainda nao avaliada.

    Exemplo: ``bicycle:conditional=no @ (Mo-Fr 07:00-10:00)`` vira
    ``scope="bicycle"``, ``value="no"`` e ``condition="(Mo-Fr 07:00-10:00)"``.
    """

    scope: str
    value: str
    condition: str | None
    raw: str

    @property
    def is_conditional(self) -> bool:
        return self.condition is not None


def parse_conditional_restrictions(
    tags: Mapping[str, str],
) -> tuple[AccessRestriction, ...]:
    """Extrai todas as tags ``*:conditional`` sem interpretar a condicao."""
    restrictions: list[AccessRestriction] = []

    for key in sorted(tags):
        if not key.endswith(":conditional"):
            continue
        raw = (tags.get(key) or "").strip()
        if not raw:
            continue
        scope = key[: -len(":conditional")]
        value, condition = _split_value_condition(raw)
        restrictions.append(
            AccessRestriction(
                scope=scope,
                value=value,
                condition=condition,
                raw=raw,
            )
        )

    return tuple(restrictions)


def _split_value_condition(raw: str) -> tuple[str, str | None]:
    """Separa ``valor @ (condicao)``; devolve condicao bruta para avaliacao futura."""
    if "@" not in raw:
        return raw.strip().lower(), None
    value, _, condition = raw.partition("@")
    condition = condition.strip()
    return value.strip().lower(), condition or None
