"""Perfil fisico de uma aresta: passos, inclinacao, superficie e limites.

O perfil e derivado dos segmentos da camada de grafo. Ele nao altera a aresta:
apenas organiza a travessia em passos pequenos, alinhados as amostras de
elevacao, para que a simulacao preserve subidas e descidas reais.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from graph.model import BicycleAccess, Edge, EdgeSegment
from graph.surface import Surface

_EPS = 1e-9


@dataclass(frozen=True, slots=True)
class SegmentProfile:
    """Resumo fisico de um ``EdgeSegment``."""

    segment_id: str
    distance_m: float
    surface: Surface
    bicycle_access: BicycleAccess
    max_speed_mps: float | None
    elevation_profile: tuple[tuple[float, float], ...]
    has_elevation: bool
    start_elevation_m: float | None
    end_elevation_m: float | None

    @property
    def elevation_delta_m(self) -> float | None:
        if self.start_elevation_m is None or self.end_elevation_m is None:
            return None
        return self.end_elevation_m - self.start_elevation_m


@dataclass(frozen=True, slots=True)
class ProfileStep:
    """Trecho curto e homogeneo usado pela simulacao dinamica."""

    start_m: float
    distance_m: float
    slope_rad: float
    elevation_start_m: float | None
    elevation_end_m: float | None
    surface: Surface
    bicycle_access: BicycleAccess
    max_speed_mps: float | None
    segment_id: str

    @property
    def elevation_delta_m(self) -> float | None:
        if self.elevation_start_m is None or self.elevation_end_m is None:
            return None
        return self.elevation_end_m - self.elevation_start_m

    @property
    def gradient_percent(self) -> float | None:
        if self.elevation_delta_m is None or self.distance_m <= 0.0:
            return None
        return 100.0 * self.elevation_delta_m / self.distance_m


@dataclass(frozen=True, slots=True)
class EdgeProfile:
    """Perfil fisico completo de uma aresta direcionada."""

    edge_id: str
    distance_m: float
    segments: tuple[SegmentProfile, ...]
    ascent_m: float
    descent_m: float
    unknown_elevation_m: float

    @property
    def has_elevation(self) -> bool:
        return any(segment.has_elevation for segment in self.segments)

    @property
    def segment_count(self) -> int:
        return len(self.segments)

    @classmethod
    def from_edge(cls, edge: Edge) -> "EdgeProfile":
        """Extrai o perfil fisico sem modificar a aresta."""
        segments: list[SegmentProfile] = []
        ascent = 0.0
        descent = 0.0
        unknown = 0.0

        for segment in edge.segments:
            points = _clean_profile(segment)
            has_elevation = len(points) >= 2
            start = points[0][1] if points else None
            end = points[-1][1] if points else None
            if len(points) == 1:
                start = end = points[0][1]

            segments.append(
                SegmentProfile(
                    segment_id=segment.id,
                    distance_m=segment.distance_m,
                    surface=segment.surface,
                    bicycle_access=segment.bicycle_access,
                    max_speed_mps=_max_speed_mps(segment),
                    elevation_profile=points,
                    has_elevation=has_elevation,
                    start_elevation_m=start,
                    end_elevation_m=end,
                )
            )
            ascent += segment.elevation_gain_m
            descent += segment.elevation_loss_m
            if not has_elevation:
                unknown += segment.distance_m

        return cls(
            edge_id=edge.id,
            distance_m=edge.distance_m,
            segments=tuple(segments),
            ascent_m=ascent,
            descent_m=descent,
            unknown_elevation_m=unknown,
        )

    def steps(self, step_m: float = 5.0) -> tuple[ProfileStep, ...]:
        """Divide a aresta em passos de no maximo ``step_m`` metros.

        As fronteiras das amostras de elevacao sao sempre respeitadas. Assim,
        um pico intermediario nao e suavizado por um passo maior.
        """
        if not math.isfinite(step_m) or step_m <= 0.0:
            raise ValueError(f"step_m deve ser positivo e finito (recebido {step_m!r})")

        steps: list[ProfileStep] = []
        for segment in self.segments:
            steps.extend(_segment_steps(segment, step_m))
        return tuple(steps)

    def to_dict(self) -> dict[str, object]:
        return {
            "edge_id": self.edge_id,
            "distance_m": round(self.distance_m, 3),
            "ascent_m": round(self.ascent_m, 3),
            "descent_m": round(self.descent_m, 3),
            "has_elevation": self.has_elevation,
            "unknown_elevation_m": round(self.unknown_elevation_m, 3),
            "segments": self.segment_count,
        }


def _clean_profile(segment: EdgeSegment) -> tuple[tuple[float, float], ...]:
    """Normaliza distancias/altitudes e remove duplicatas exatas."""
    if not segment.elevation_profile:
        return ()

    points: list[tuple[float, float]] = []
    for sample in segment.elevation_profile:
        distance = min(max(float(sample.distance_m), 0.0), segment.distance_m)
        points.append((distance, float(sample.elevation_m)))
    points.sort(key=lambda item: item[0])

    cleaned: list[tuple[float, float]] = []
    for distance, elevation in points:
        if cleaned and abs(distance - cleaned[-1][0]) <= _EPS:
            cleaned[-1] = (distance, elevation)
        else:
            cleaned.append((distance, elevation))
    return tuple(cleaned)


def _max_speed_mps(segment: EdgeSegment) -> float | None:
    if segment.max_speed_kmh is None:
        return None
    value = float(segment.max_speed_kmh)
    if not math.isfinite(value) or value <= 0.0:
        return None
    return value / 3.6


def _segment_steps(segment: SegmentProfile, step_m: float) -> list[ProfileStep]:
    points = segment.elevation_profile
    if len(points) < 2:
        elevation = points[0][1] if len(points) == 1 else None
        return _flat_steps(segment, 0.0, segment.distance_m, elevation, step_m)

    steps: list[ProfileStep] = []
    cursor = 0.0
    for index, (distance, elevation) in enumerate(points):
        if distance > cursor + _EPS:
            # Lacuna antes da primeira amostra (ou entre amostras): sem
            # inclinacao conhecida.
            steps.extend(_flat_steps(segment, cursor, distance, None, step_m))

        if index + 1 < len(points):
            next_distance, next_elevation = points[index + 1]
            if next_distance > distance + _EPS:
                steps.extend(
                    _sloped_steps(
                        segment,
                        distance,
                        next_distance,
                        elevation,
                        next_elevation,
                        step_m,
                    )
                )
                cursor = next_distance
            else:
                cursor = max(cursor, distance)
        else:
            cursor = max(cursor, distance)

    if cursor < segment.distance_m - _EPS:
        steps.extend(_flat_steps(segment, cursor, segment.distance_m, None, step_m))
    return steps


def _flat_steps(
    segment: SegmentProfile,
    start_m: float,
    end_m: float,
    elevation_m: float | None,
    step_m: float,
) -> list[ProfileStep]:
    length = end_m - start_m
    if length <= _EPS:
        return []

    count = max(1, math.ceil(length / step_m - _EPS))
    sub_length = length / count
    return [
        ProfileStep(
            start_m=start_m + index * sub_length,
            distance_m=sub_length,
            slope_rad=0.0,
            elevation_start_m=elevation_m,
            elevation_end_m=elevation_m,
            surface=segment.surface,
            bicycle_access=segment.bicycle_access,
            max_speed_mps=segment.max_speed_mps,
            segment_id=segment.segment_id,
        )
        for index in range(count)
    ]


def _sloped_steps(
    segment: SegmentProfile,
    start_m: float,
    end_m: float,
    start_elevation_m: float,
    end_elevation_m: float,
    step_m: float,
) -> list[ProfileStep]:
    length = end_m - start_m
    if length <= _EPS:
        return []

    count = max(1, math.ceil(length / step_m - _EPS))
    sub_length = length / count
    delta = (end_elevation_m - start_elevation_m) / count
    slope = math.atan2(delta, sub_length)

    steps: list[ProfileStep] = []
    for index in range(count):
        low = start_elevation_m + index * delta
        high = start_elevation_m + (index + 1) * delta
        steps.append(
            ProfileStep(
                start_m=start_m + index * sub_length,
                distance_m=sub_length,
                slope_rad=slope,
                elevation_start_m=low,
                elevation_end_m=high,
                surface=segment.surface,
                bicycle_access=segment.bicycle_access,
                max_speed_mps=segment.max_speed_mps,
                segment_id=segment.segment_id,
            )
        )
    return steps
