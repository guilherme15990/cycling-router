"""Camada fisica: tempo e energia de travessia de uma aresta.

A camada nao conhece perfis de rota. Ela transforma atributos do grafo
(distancia, elevacao, superficie e limites) em metricas fisicas que a busca
Pareto pode acumular.
"""

from .bicycle import BicycleModel
from .cyclist import CyclistModel
from .edge_profile import EdgeProfile, ProfileStep, SegmentProfile
from .energy import (
    battery_energy_from_wheel_j,
    kinetic_energy_j,
    potential_energy_j,
    rider_energy_from_wheel_j,
    wheel_energy_from_rider_j,
)
from .energy_model import (
    CALIBRATED_LEVEL,
    GENERIC_LEVEL,
    JOULES_PER_WH,
    PERSONALIZED_LEVEL,
    BatteryConfig,
    BatteryFeasibility,
    EnergyEstimate,
    EnergyModel,
    GenericEnergyConfig,
    assess_battery,
)
from .environment import Environment
from .forces import (
    ForceBreakdown,
    aerodynamic_force_n,
    equilibrium_speed_mps,
    forces_at,
    gravity_force_n,
    required_rider_power_w,
    rolling_force_n,
    wheel_power_w,
)
from .models import RouteMetrics, TraversalPath, TraversalResult
from .speed import MIN_SPEED_MPS, SpeedStep, advance_speed
from .traversal import (
    DEFAULT_ACCELERATION_LIMIT_MPS2,
    DEFAULT_DISMOUNT_SPEED_MPS,
    DEFAULT_STEP_M,
    PhysicalTraversal,
    traverse_edge,
)

__all__ = [
    "BicycleModel",
    "BatteryConfig",
    "BatteryFeasibility",
    "CALIBRATED_LEVEL",
    "CyclistModel",
    "DEFAULT_ACCELERATION_LIMIT_MPS2",
    "DEFAULT_DISMOUNT_SPEED_MPS",
    "DEFAULT_STEP_M",
    "EdgeProfile",
    "EnergyEstimate",
    "EnergyModel",
    "Environment",
    "ForceBreakdown",
    "GENERIC_LEVEL",
    "GenericEnergyConfig",
    "JOULES_PER_WH",
    "MIN_SPEED_MPS",
    "PERSONALIZED_LEVEL",
    "PhysicalTraversal",
    "ProfileStep",
    "RouteMetrics",
    "SegmentProfile",
    "SpeedStep",
    "TraversalPath",
    "TraversalResult",
    "advance_speed",
    "aerodynamic_force_n",
    "assess_battery",
    "battery_energy_from_wheel_j",
    "equilibrium_speed_mps",
    "forces_at",
    "gravity_force_n",
    "kinetic_energy_j",
    "potential_energy_j",
    "required_rider_power_w",
    "rider_energy_from_wheel_j",
    "rolling_force_n",
    "traverse_edge",
    "wheel_energy_from_rider_j",
    "wheel_power_w",
]
