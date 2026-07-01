"""Internal inverter-block wrappers for the legacy single-inverter model.

Step 1 exposes exactly one internal block, index 0, backed by the existing flat
configuration, runtime CVXPY parameters, and variable objects. These dataclasses
must remain dependency-light and must not parse indexed config, own cache keys,
publish results, or become a second source of truth.
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class InverterBlockConfig:
    """Read-only block 0 view over the legacy flat config dictionaries.

    The dictionaries are owned by ``Optimization`` and may be updated by cache-hit
    runtime paths. Properties intentionally read through to those dictionaries so
    block config cannot drift from the legacy flat state.
    """

    index: int
    optim_conf: dict
    plant_conf: dict

    @property
    def set_use_battery(self) -> bool:
        return bool(self.optim_conf["set_use_battery"])

    @property
    def inverter_is_hybrid(self) -> bool:
        return bool(self.plant_conf["inverter_is_hybrid"])

    @property
    def battery_nominal_energy_capacity(self) -> float:
        return self.plant_conf["battery_nominal_energy_capacity"]


@dataclass(frozen=True)
class InverterBlockRuntime:
    """Current CVXPY parameter aliases for block 0 battery runtime state.

    ``Optimization`` rebuilds this wrapper whenever horizon-dependent parameters
    are recreated. The attributes reference the legacy ``self.param_*`` objects;
    callers must update those parameters rather than replacing values here.
    """

    index: int
    soc_init: Any
    soc_final: Any
    soc_low_gap: Any
    soc_high_gap: Any
    soc_low_required: Any
    soc_high_required: Any
    soc_target_floor: Any
    battery_charge_power_max: Any
    battery_discharge_power_max: Any


@dataclass(frozen=True)
class InverterBlockVariables:
    """Current CVXPY variable aliases for block 0 battery and hybrid internals.

    Hybrid and stress variables are created lazily during problem construction,
    so those fields may be ``None`` until ``Optimization`` reaches the matching
    constraint setup path.
    """

    index: int
    p_sto_pos: Any
    p_sto_neg: Any
    soc_low_recovered: Any
    soc_high_recovered: Any
    soc_deficit_cost: Any
    soc_surplus_cost: Any
    p_hybrid_inverter: Any | None = None
    p_dc_ac: Any | None = None
    p_ac_dc: Any | None = None
    is_dc_sourcing: Any | None = None
    batt_stress_cost: Any | None = None
    inv_stress_cost: Any | None = None
