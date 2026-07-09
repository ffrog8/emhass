"""Internal inverter-block helpers for flat and indexed inverter config.

Block 0 is backed by the existing flat configuration dictionaries. Step 2 adds
indexed ``hybrid_inverter_config_N`` parsing and validation here so public config
paths can share one block-local contract while multi-block solving remains
disabled outside this module.
"""

import logging
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

HYBRID_INVERTER_CONFIG_PREFIX = "hybrid_inverter_config_"
INVERTER_BLOCK_CONFIGS_KEY = "_inverter_block_configs"
MULTI_BLOCK_SOLVE_DISABLED_MESSAGE = "multi-block solve not enabled"
MULTI_INVERTER_MODE_KEY = "multi_inverter_mode"
MULTI_INVERTER_MODE_SINGLE = "single"
MULTI_INVERTER_MODE_MULTI = "multi"
MULTI_INVERTER_MODE_VALUES = frozenset({MULTI_INVERTER_MODE_SINGLE, MULTI_INVERTER_MODE_MULTI})
_LOGGER = logging.getLogger(__name__)

_BLOCK_KEY_RE = re.compile(r"^hybrid_inverter_config_(\d+)$")

_OPTIM_CONF_BLOCK_KEYS = frozenset(
    {
        "set_use_pv",
        "set_use_battery",
        "set_battery_dynamic",
        "battery_dynamic_max",
        "battery_dynamic_min",
        "weight_battery_discharge",
        "weight_battery_charge",
        "battery_stress_cost",
        "battery_stress_segments",
        "battery_soc_deficit_threshold",
        "battery_soc_deficit_cost",
        "battery_soc_surplus_threshold",
        "battery_soc_surplus_cost",
    }
)

_PLANT_CONF_BLOCK_KEYS = frozenset(
    {
        "inverter_is_hybrid",
        "compute_curtailment",
        "battery_discharge_power_max",
        "battery_charge_power_max",
        "battery_discharge_efficiency",
        "battery_charge_efficiency",
        "battery_nominal_energy_capacity",
        "battery_minimum_state_of_charge",
        "battery_maximum_state_of_charge",
        "battery_target_state_of_charge",
        "inverter_ac_output_max",
        "inverter_ac_input_max",
        "inverter_efficiency_dc_ac",
        "inverter_efficiency_ac_dc",
        "inverter_stress_cost",
        "inverter_stress_segments",
    }
)

_REQUIRED_BATTERY_KEYS = frozenset(
    {
        "battery_discharge_power_max",
        "battery_charge_power_max",
        "battery_discharge_efficiency",
        "battery_charge_efficiency",
        "battery_nominal_energy_capacity",
        "battery_minimum_state_of_charge",
        "battery_maximum_state_of_charge",
        "battery_target_state_of_charge",
    }
)

_REQUIRED_HYBRID_INVERTER_KEYS = frozenset(
    {
        "inverter_ac_output_max",
        "inverter_ac_input_max",
        "inverter_efficiency_dc_ac",
        "inverter_efficiency_ac_dc",
    }
)

_RESERVED_PV_SOURCE_KEYS = frozenset(
    {
        "sensor_power_photovoltaics",
        "sensor_power_photovoltaics_forecast",
        "pv_module_model",
        "pv_inverter_model",
        "surface_tilt",
        "surface_azimuth",
        "modules_per_string",
        "strings_per_inverter",
        "set_use_adjusted_pv",
        "adjusted_pv_regression_model",
        "adjusted_pv_solar_elevation_threshold",
        "adjusted_pv_model_max_age",
    }
)

_RUNTIME_SOC_BLOCK_KEYS = frozenset(
    {
        "soc_init",
        "soc_final",
        "soc_target",
        "soc_target_timestep",
    }
)

_RUNTIME_PV_BLOCK_KEYS = frozenset({"pv_power_forecast"})
_RUNTIME_ONLY_BLOCK_KEYS = _RUNTIME_SOC_BLOCK_KEYS | _RUNTIME_PV_BLOCK_KEYS
_RUNTIME_SCALAR_CONFIG_BLOCK_KEYS = frozenset(
    {
        "battery_charge_power_max",
        "battery_discharge_power_max",
        "battery_minimum_state_of_charge",
        "battery_maximum_state_of_charge",
        "battery_target_state_of_charge",
    }
)
_RUNTIME_SOC_SCALAR_CONFIG_BLOCK_KEYS = frozenset(
    {
        "battery_minimum_state_of_charge",
        "battery_maximum_state_of_charge",
        "battery_target_state_of_charge",
    }
)
_RUNTIME_TARGET_BOUNDS_RELAXED_INDEXES_KEY = "_hybrid_inverter_runtime_target_bounds_relaxed_indexes"

_DEFERRED_RUNTIME_BLOCK_KEYS = frozenset(
    {
        "compute_curtailment",
    }
)

_SITE_LEVEL_FORBIDDEN_KEYS = frozenset(
    {
        "sensor_power_load_no_var_loads",
        "maximum_power_from_grid",
        "maximum_power_to_grid",
        "load_forecast_method",
        "load_cost_forecast_method",
        "production_price_forecast_method",
        "photovoltaic_production_sell_price",
        "set_total_pv_sell",
        "capacity_cost_per_kw",
        "costfun",
        "delta_forecast_daily",
        "optimization_time_step",
        "number_of_deferrable_loads",
        "nominal_power_of_deferrable_loads",
        "minimum_power_of_deferrable_loads",
        "def_load_config",
        "heat_topology",
        "deferrable_load_groups",
        "set_nocharge_from_grid",
        "set_nodischarge_to_grid",
        "set_battery_first_priority",
        "hass_url",
        "long_lived_token",
        "influxdb_host",
        "influxdb_username",
        "influxdb_password",
        "continual_publish",
        "publish_prefix",
    }
)

_POSITIVE_PLANT_KEYS = frozenset(
    {
        "battery_discharge_power_max",
        "battery_charge_power_max",
        "battery_nominal_energy_capacity",
        "inverter_ac_output_max",
        "inverter_ac_input_max",
    }
)

_EFFICIENCY_PLANT_KEYS = frozenset(
    {
        "battery_discharge_efficiency",
        "battery_charge_efficiency",
        "inverter_efficiency_dc_ac",
        "inverter_efficiency_ac_dc",
    }
)


class InverterBlockConfig:
    """Read-only block 0 view over the legacy flat config dictionaries.

    The dictionaries are owned by ``Optimization`` and may be updated by cache-hit
    runtime paths. Properties intentionally read through to those dictionaries so
    block config cannot drift from the legacy flat state.
    """

    def __init__(
        self,
        index: int,
        optim_conf: dict,
        plant_conf: dict,
        runtime_conf: dict | None = None,
    ) -> None:
        self.index = index
        self.optim_conf = optim_conf
        self.plant_conf = plant_conf
        self.runtime_conf = runtime_conf or {}

    @property
    def set_use_battery(self) -> bool:
        return bool(self.optim_conf.get("set_use_battery", False))

    @property
    def set_use_pv(self) -> bool:
        return bool(self.optim_conf.get("set_use_pv", False))

    @property
    def inverter_is_hybrid(self) -> bool:
        return bool(self.plant_conf["inverter_is_hybrid"])

    @property
    def battery_nominal_energy_capacity(self) -> float:
        return self.plant_conf["battery_nominal_energy_capacity"]


def _as_finite_float(value: object, block_index: int, key: str) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError) as err:
        raise ValueError(f"hybrid_inverter_config_{block_index}.{key} must be numeric") from err
    if not math.isfinite(numeric):
        raise ValueError(f"hybrid_inverter_config_{block_index}.{key} must be finite")
    return numeric


def _validate_positive(value: object, block_index: int, key: str) -> None:
    numeric = _as_finite_float(value, block_index, key)
    if numeric <= 0:
        raise ValueError(f"hybrid_inverter_config_{block_index}.{key} must be > 0")


def _validate_efficiency(value: object, block_index: int, key: str) -> None:
    numeric = _as_finite_float(value, block_index, key)
    if numeric <= 0 or numeric > 1:
        raise ValueError(f"hybrid_inverter_config_{block_index}.{key} must satisfy 0 < value <= 1")


def _validate_soc(value: object, block_index: int, key: str) -> float:
    numeric = _as_finite_float(value, block_index, key)
    if numeric < 0 or numeric > 1:
        raise ValueError(f"hybrid_inverter_config_{block_index}.{key} must be in [0, 1]")
    return numeric


def _validate_multi_inverter_mode(value: object) -> str:
    if value is None:
        return MULTI_INVERTER_MODE_SINGLE
    if value not in MULTI_INVERTER_MODE_VALUES:
        values = ", ".join(sorted(MULTI_INVERTER_MODE_VALUES))
        raise ValueError(f"{MULTI_INVERTER_MODE_KEY} must be one of: {values}")
    return str(value)


def resolve_multi_inverter_mode(
    plant_conf: Mapping[str, object],
    runtimeparams: Mapping[str, object] | None = None,
) -> str:
    """Return the active single/multi inverter mode for this request."""
    if runtimeparams is not None and MULTI_INVERTER_MODE_KEY in runtimeparams:
        return _validate_multi_inverter_mode(runtimeparams[MULTI_INVERTER_MODE_KEY])
    return _validate_multi_inverter_mode(plant_conf.get(MULTI_INVERTER_MODE_KEY))


def _warn_ignored_config_zero() -> None:
    _LOGGER.warning(
        "hybrid_inverter_config_0 is ignored; use the flat top-level config for "
        "single-inverter mode or hybrid_inverter_config_1..N in multi-inverter mode"
    )


def _warn_if_static_config_zero_present(input_conf: Mapping[str, object]) -> None:
    if f"{HYBRID_INVERTER_CONFIG_PREFIX}0" in input_conf:
        _warn_ignored_config_zero()


def _extract_block_indexes(input_conf: Mapping[str, object], *, warn_on_zero: bool = False) -> list[int]:
    indexes: list[int] = []
    for key in input_conf:
        if not key.startswith(HYBRID_INVERTER_CONFIG_PREFIX):
            continue
        match = _BLOCK_KEY_RE.match(key)
        if match is None:
            raise ValueError(f"{key} must be named hybrid_inverter_config_<positive integer>")
        index = int(match.group(1))
        if index == 0:
            if warn_on_zero:
                _warn_ignored_config_zero()
            continue
        if key != f"{HYBRID_INVERTER_CONFIG_PREFIX}{index}":
            raise ValueError(f"{key} must be named hybrid_inverter_config_<positive integer>")
        indexes.append(index)
    indexes.sort()
    expected = list(range(1, len(indexes) + 1))
    if indexes != expected:
        raise ValueError(f"hybrid_inverter_config indexes must be contiguous from 1; got {indexes}")
    return indexes


def _extract_runtime_block_indexes(runtimeparams: Mapping[str, object]) -> list[int]:
    indexes: list[int] = []
    for key in runtimeparams:
        if not key.startswith(HYBRID_INVERTER_CONFIG_PREFIX):
            continue
        match = _BLOCK_KEY_RE.match(key)
        if match is None:
            raise ValueError(f"{key} must be named hybrid_inverter_config_<positive integer>")
        index = int(match.group(1))
        if index == 0:
            raise ValueError("hybrid_inverter_config_0 is invalid; block 0 uses flat runtime keys")
        if key != f"{HYBRID_INVERTER_CONFIG_PREFIX}{index}":
            raise ValueError(f"{key} must be named hybrid_inverter_config_<positive integer>")
        indexes.append(index)
    return sorted(indexes)


def _validate_block_values(index: int, raw_block: Mapping[str, object], plant_conf: dict[str, object]) -> None:
    for key in _POSITIVE_PLANT_KEYS & raw_block.keys():
        _validate_positive(plant_conf[key], index, key)
    for key in _EFFICIENCY_PLANT_KEYS & raw_block.keys():
        _validate_efficiency(plant_conf[key], index, key)


def _validate_battery_block(
    index: int,
    raw_block: Mapping[str, object],
    plant_conf: dict[str, object],
    *,
    validate_target_bounds: bool = True,
) -> None:
    missing = sorted(_REQUIRED_BATTERY_KEYS - raw_block.keys())
    if missing:
        raise ValueError(f"hybrid_inverter_config_{index} missing required battery keys: {missing}")

    soc_min = _validate_soc(
        plant_conf["battery_minimum_state_of_charge"],
        index,
        "battery_minimum_state_of_charge",
    )
    soc_max = _validate_soc(
        plant_conf["battery_maximum_state_of_charge"],
        index,
        "battery_maximum_state_of_charge",
    )
    soc_target = _validate_soc(
        plant_conf["battery_target_state_of_charge"],
        index,
        "battery_target_state_of_charge",
    )
    if soc_min >= soc_max:
        raise ValueError(f"hybrid_inverter_config_{index} battery minimum SOC must be less than maximum SOC")
    if validate_target_bounds and (soc_target < soc_min or soc_target > soc_max):
        raise ValueError(
            f"hybrid_inverter_config_{index}.battery_target_state_of_charge must be within min/max SOC"
        )


def _validate_hybrid_block(index: int, raw_block: Mapping[str, object]) -> None:
    missing = sorted(_REQUIRED_HYBRID_INVERTER_KEYS - raw_block.keys())
    if missing:
        raise ValueError(f"hybrid_inverter_config_{index} missing required hybrid inverter keys: {missing}")


def _validate_runtime_soc_init(
    value: object,
    block_index: int,
    key: str,
    plant_conf: Mapping[str, object],
) -> float:
    numeric = _validate_soc(value, block_index, key)
    soc_min = float(plant_conf["battery_minimum_state_of_charge"])
    soc_max = float(plant_conf["battery_maximum_state_of_charge"])
    if numeric < soc_min:
        _LOGGER.warning(
            "Passed hybrid_inverter_config_%s.%s=%s is lower than soc_min=%s, "
            "keeping real initial SOC for optimization recovery",
            block_index,
            key,
            numeric,
            soc_min,
        )
    if numeric > soc_max:
        _LOGGER.warning(
            "Passed hybrid_inverter_config_%s.%s=%s is greater than soc_max=%s, "
            "keeping real initial SOC for optimization recovery",
            block_index,
            key,
            numeric,
            soc_max,
        )
    return numeric


def _validate_runtime_soc_final(
    value: object,
    block_index: int,
    key: str,
    plant_conf: Mapping[str, object],
) -> float:
    numeric = _validate_soc(value, block_index, key)
    soc_min = float(plant_conf["battery_minimum_state_of_charge"])
    soc_max = float(plant_conf["battery_maximum_state_of_charge"])
    if numeric < soc_min:
        _LOGGER.warning(
            "Passed hybrid_inverter_config_%s.%s=%s is lower than soc_min=%s, "
            "setting %s=soc_min",
            block_index,
            key,
            numeric,
            soc_min,
            key,
        )
        numeric = soc_min
    if numeric > soc_max:
        _LOGGER.warning(
            "Passed hybrid_inverter_config_%s.%s=%s is greater than soc_max=%s, "
            "setting %s=soc_max",
            block_index,
            key,
            numeric,
            soc_max,
            key,
        )
        numeric = soc_max
    return numeric


def _validate_runtime_timestep(value: object, block_index: int, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"hybrid_inverter_config_{block_index}.{key} must be an integer")
    if value < 0:
        raise ValueError(f"hybrid_inverter_config_{block_index}.{key} must be >= 0")
    return value


def _validate_block_runtime_conf(
    index: int,
    runtime_conf: Mapping[str, object],
    plant_conf: Mapping[str, object],
    set_use_battery: bool,
    set_use_pv: bool,
    fill_battery_defaults: bool = False,
) -> dict[str, object]:
    runtime_keys = set(runtime_conf)
    invalid_runtime_keys = runtime_keys - _RUNTIME_ONLY_BLOCK_KEYS
    if invalid_runtime_keys:
        key = sorted(invalid_runtime_keys, key=str)[0]
        raise ValueError(f"hybrid_inverter_config_{index}.{key} is not a valid runtime-only key")

    soc_runtime_keys = runtime_keys & _RUNTIME_SOC_BLOCK_KEYS
    if soc_runtime_keys and not set_use_battery:
        key = sorted(soc_runtime_keys, key=str)[0]
        raise ValueError(f"hybrid_inverter_config_{index}.{key} requires set_use_battery true")

    required_soc_bound_keys = {
        "battery_minimum_state_of_charge",
        "battery_maximum_state_of_charge",
    }
    missing_soc_bound_keys = required_soc_bound_keys - plant_conf.keys()
    if soc_runtime_keys and missing_soc_bound_keys:
        key = sorted(soc_runtime_keys, key=str)[0]
        missing = sorted(missing_soc_bound_keys)
        raise ValueError(
            f"hybrid_inverter_config_{index}.{key} requires configured battery SOC bounds: {missing}"
        )

    pv_runtime_keys = runtime_keys & _RUNTIME_PV_BLOCK_KEYS
    if pv_runtime_keys and not set_use_pv:
        key = sorted(pv_runtime_keys, key=str)[0]
        raise ValueError(f"hybrid_inverter_config_{index}.{key} requires set_use_pv true")

    validated: dict[str, object] = {}
    for key, value in runtime_conf.items():
        if key == "soc_init":
            validated[key] = _validate_runtime_soc_init(value, index, key, plant_conf)
        elif key == "soc_final":
            validated[key] = _validate_runtime_soc_final(value, index, key, plant_conf)
        elif key == "soc_target":
            validated[key] = _validate_soc(value, index, key)
        elif key == "soc_target_timestep":
            validated[key] = _validate_runtime_timestep(value, index, key)
        elif key in _RUNTIME_PV_BLOCK_KEYS:
            validated[key] = value
    if fill_battery_defaults and set_use_battery:
        target_soc = float(plant_conf["battery_target_state_of_charge"])
        if "soc_init" not in validated:
            validated["soc_init"] = _validate_runtime_soc_init(
                target_soc,
                index,
                "soc_init",
                plant_conf,
            )
        if "soc_final" not in validated:
            validated["soc_final"] = _validate_runtime_soc_final(
                target_soc,
                index,
                "soc_final",
                plant_conf,
            )
    return validated


def _split_block_config(
    index: int,
    raw_block: Mapping[str, object],
    runtime_conf: Mapping[str, object] | None = None,
    *,
    validate_target_bounds: bool = True,
) -> InverterBlockConfig:
    optim_conf: dict[str, object] = {}
    plant_conf: dict[str, object] = {}
    allowed_keys = _OPTIM_CONF_BLOCK_KEYS | _PLANT_CONF_BLOCK_KEYS
    forbidden_keys = _SITE_LEVEL_FORBIDDEN_KEYS | _RESERVED_PV_SOURCE_KEYS

    for key, value in raw_block.items():
        if key in forbidden_keys:
            raise ValueError(f"hybrid_inverter_config_{index}.{key} is not block-local in Step 2")
        if key not in allowed_keys:
            raise ValueError(f"hybrid_inverter_config_{index}.{key} is not a valid block key")
        if key in _OPTIM_CONF_BLOCK_KEYS:
            optim_conf[key] = value
        else:
            plant_conf[key] = value

    _validate_block_values(index, raw_block, plant_conf)
    set_use_battery = bool(optim_conf.get("set_use_battery", False))
    present_battery_keys = _REQUIRED_BATTERY_KEYS & raw_block.keys()
    if not set_use_battery and present_battery_keys:
        raise ValueError(f"hybrid_inverter_config_{index} contains battery keys but set_use_battery is not true")
    if set_use_battery:
        _validate_battery_block(
            index,
            raw_block,
            plant_conf,
            validate_target_bounds=validate_target_bounds,
        )
    if bool(plant_conf.get("inverter_is_hybrid", False)):
        _validate_hybrid_block(index, raw_block)

    set_use_pv = bool(optim_conf.get("set_use_pv", False))
    validated_runtime_conf = _validate_block_runtime_conf(
        index,
        runtime_conf or {},
        plant_conf,
        set_use_battery,
        set_use_pv,
        fill_battery_defaults=runtime_conf is not None,
    )
    return InverterBlockConfig(
        index=index,
        optim_conf=optim_conf,
        plant_conf=plant_conf,
        runtime_conf=validated_runtime_conf,
    )


def merge_inverter_block_runtime_overrides(
    input_conf: dict[str, object],
    runtimeparams: Mapping[str, object],
) -> dict[int, dict[str, object]]:
    block_runtime_conf: dict[int, dict[str, object]] = {}
    scalar_config_overrides_by_index: dict[int, dict[str, object]] = {}
    relaxed_target_bound_indexes: set[int] = set()
    plant_conf = input_conf.get("plant_conf", {})
    if not isinstance(plant_conf, Mapping):
        plant_conf = {}
    multi_inverter_mode = resolve_multi_inverter_mode(plant_conf, runtimeparams)
    if (
        isinstance(input_conf.get("plant_conf"), dict)
        and (
            MULTI_INVERTER_MODE_KEY in runtimeparams
            or MULTI_INVERTER_MODE_KEY in plant_conf
        )
    ):
        input_conf["plant_conf"][MULTI_INVERTER_MODE_KEY] = multi_inverter_mode

    runtime_indexes = _extract_runtime_block_indexes(runtimeparams)
    if multi_inverter_mode == MULTI_INVERTER_MODE_SINGLE:
        if runtime_indexes:
            raise ValueError(
                "nested hybrid_inverter_config_N runtime blocks require "
                "multi_inverter_mode=multi"
            )
        return block_runtime_conf

    configured_indexes = set(_extract_block_indexes(input_conf, warn_on_zero=False))
    if not configured_indexes:
        if runtime_indexes:
            index = runtime_indexes[0]
            raise ValueError(
                f"hybrid_inverter_config_{index} runtime block without matching configured block"
            )
        raise ValueError("multi_inverter_mode=multi requires hybrid_inverter_config_1")
    allowed_config_keys = _OPTIM_CONF_BLOCK_KEYS | _PLANT_CONF_BLOCK_KEYS
    forbidden_keys = _SITE_LEVEL_FORBIDDEN_KEYS | _RESERVED_PV_SOURCE_KEYS

    for index in runtime_indexes:
        if index not in configured_indexes:
            raise ValueError(
                f"hybrid_inverter_config_{index} runtime block without matching configured block"
            )
        block_key = f"{HYBRID_INVERTER_CONFIG_PREFIX}{index}"
        raw_runtime_block = runtimeparams[block_key]
        if not isinstance(raw_runtime_block, Mapping):
            raise ValueError(f"{block_key} runtime block must be a dictionary")
        static_block = input_conf[block_key]
        if not isinstance(static_block, dict):
            raise ValueError(f"{block_key} configured block must be a dictionary")

        runtime_conf: dict[str, object] = {}
        scalar_config_overrides: dict[str, object] = {}
        candidate_static_block = dict(static_block)
        for key, value in raw_runtime_block.items():
            if key in _DEFERRED_RUNTIME_BLOCK_KEYS:
                raise ValueError(f"{block_key}.{key} is Step 4 PV runtime scope")
            if key in forbidden_keys:
                raise ValueError(f"{block_key}.{key} is not block-local at runtime")
            if key in _RUNTIME_ONLY_BLOCK_KEYS:
                runtime_conf[key] = value
                continue
            if key not in allowed_config_keys:
                raise ValueError(f"{block_key}.{key} is not a valid runtime block key")
            if key not in _RUNTIME_SCALAR_CONFIG_BLOCK_KEYS:
                raise ValueError(f"{block_key}.{key} is not a valid runtime override key")
            if key in {
                "battery_charge_power_max",
                "battery_discharge_power_max",
            } and isinstance(value, list | tuple | dict):
                raise ValueError(f"{block_key}.{key} per-timestep forecasts are future scope")
            scalar_config_overrides[key] = value
            candidate_static_block[key] = value

        relax_target_bounds = bool(
            _RUNTIME_SOC_SCALAR_CONFIG_BLOCK_KEYS & scalar_config_overrides.keys()
        )
        parsed_block = _split_block_config(
            index,
            candidate_static_block,
            runtime_conf,
            validate_target_bounds=not relax_target_bounds,
        )
        block_runtime_conf[index] = parsed_block.runtime_conf
        scalar_config_overrides_by_index[index] = scalar_config_overrides
        if relax_target_bounds:
            relaxed_target_bound_indexes.add(index)

    for index, scalar_config_overrides in scalar_config_overrides_by_index.items():
        block_key = f"{HYBRID_INVERTER_CONFIG_PREFIX}{index}"
        input_conf[block_key].update(scalar_config_overrides)
    if isinstance(input_conf.get("plant_conf"), dict):
        if relaxed_target_bound_indexes:
            input_conf["plant_conf"][_RUNTIME_TARGET_BOUNDS_RELAXED_INDEXES_KEY] = sorted(
                relaxed_target_bound_indexes
            )
        else:
            input_conf["plant_conf"].pop(_RUNTIME_TARGET_BOUNDS_RELAXED_INDEXES_KEY, None)
    return block_runtime_conf


def parse_inverter_block_configs(
    input_conf: Mapping[str, object],
    optim_conf: dict,
    plant_conf: dict,
    block_runtime_conf: Mapping[int, Mapping[str, object]] | None = None,
) -> dict[int, InverterBlockConfig]:
    blocks: dict[int, InverterBlockConfig] = {
        0: InverterBlockConfig(index=0, optim_conf=optim_conf, plant_conf=plant_conf)
    }
    runtime_conf_by_index = block_runtime_conf or {}
    multi_inverter_mode = resolve_multi_inverter_mode(plant_conf)
    relaxed_target_bound_indexes = set(
        plant_conf.pop(_RUNTIME_TARGET_BOUNDS_RELAXED_INDEXES_KEY, [])
    )
    if multi_inverter_mode == MULTI_INVERTER_MODE_MULTI or MULTI_INVERTER_MODE_KEY in plant_conf:
        plant_conf[MULTI_INVERTER_MODE_KEY] = multi_inverter_mode

    if multi_inverter_mode == MULTI_INVERTER_MODE_SINGLE:
        _warn_if_static_config_zero_present(input_conf)
        if runtime_conf_by_index:
            index = sorted(runtime_conf_by_index)[0]
            raise ValueError(
                f"hybrid_inverter_config_{index} runtime block requires "
                "multi_inverter_mode=multi"
            )
        plant_conf[INVERTER_BLOCK_CONFIGS_KEY] = blocks
        return blocks

    block_indexes = _extract_block_indexes(input_conf, warn_on_zero=True)
    if not block_indexes:
        raise ValueError("multi_inverter_mode=multi requires hybrid_inverter_config_1")

    unknown_runtime_indexes = sorted(set(runtime_conf_by_index) - set(block_indexes))
    if unknown_runtime_indexes:
        index = unknown_runtime_indexes[0]
        raise ValueError(
            f"hybrid_inverter_config_{index} runtime block without matching configured block"
        )

    for index in block_indexes:
        block_key = f"{HYBRID_INVERTER_CONFIG_PREFIX}{index}"
        raw_block = input_conf[block_key]
        if not isinstance(raw_block, Mapping):
            raise ValueError(f"{block_key} must be a dictionary")
        blocks[index] = _split_block_config(
            index,
            raw_block,
            runtime_conf_by_index.get(index),
            validate_target_bounds=index not in relaxed_target_bound_indexes,
        )
    plant_conf[INVERTER_BLOCK_CONFIGS_KEY] = blocks
    return blocks


def has_extra_inverter_blocks(plant_conf: Mapping[str, object]) -> bool:
    """Return whether parsed config includes any non-root inverter blocks."""
    blocks = plant_conf.get(INVERTER_BLOCK_CONFIGS_KEY)
    if not isinstance(blocks, Mapping):
        return False
    return any(index != 0 for index in blocks)


def is_public_safe_multi_block_battery_model(
    optim_conf: Mapping[str, object],
    plant_conf: Mapping[str, object],
) -> bool:
    """Return whether parsed extra blocks match the public Step 6 battery scope."""
    if not has_extra_inverter_blocks(plant_conf):
        return False
    if not optim_conf.get("set_use_battery"):
        return False
    if optim_conf.get("set_use_pv"):
        return False
    if optim_conf.get("battery_mode_lock", "site") != "site":
        return False
    if optim_conf.get("set_nocharge_from_grid"):
        return False
    if optim_conf.get("set_nodischarge_to_grid"):
        return False
    if plant_conf.get("inverter_is_hybrid"):
        return False
    if plant_conf.get("compute_curtailment"):
        return False

    parsed_blocks = plant_conf.get(INVERTER_BLOCK_CONFIGS_KEY)
    if not isinstance(parsed_blocks, Mapping):
        return False

    for index, block in parsed_blocks.items():
        if index == 0:
            continue
        if not block.set_use_battery:
            return False
        if block.set_use_pv:
            return False
        if block.plant_conf.get("inverter_is_hybrid"):
            return False
        if block.plant_conf.get("compute_curtailment"):
            return False
    return True


def is_public_safe_multi_block_hybrid_model(
    optim_conf: Mapping[str, object],
    plant_conf: Mapping[str, object],
) -> bool:
    """Return whether parsed extra blocks match the public split-PV hybrid shape."""
    if not has_extra_inverter_blocks(plant_conf):
        return False
    if optim_conf.get("battery_mode_lock", "site") != "site":
        return False
    if plant_conf.get("multi_hybrid_inverter_pv_mode") != "split_pv":
        return False
    if not optim_conf.get("set_use_battery"):
        return False
    if not plant_conf.get("inverter_is_hybrid"):
        return False

    parsed_blocks = plant_conf.get(INVERTER_BLOCK_CONFIGS_KEY)
    if not isinstance(parsed_blocks, Mapping):
        return False

    for index, block in parsed_blocks.items():
        if index == 0:
            continue
        if not block.set_use_battery:
            return False
        if not block.plant_conf.get("inverter_is_hybrid"):
            return False
        if block.set_use_pv and "pv_power_forecast" not in block.runtime_conf:
            return False
    return True


def is_public_safe_multi_block_model(
    optim_conf: Mapping[str, object],
    plant_conf: Mapping[str, object],
) -> bool:
    """Return whether parsed extra blocks are in a public multi-block shape."""
    return is_public_safe_multi_block_battery_model(
        optim_conf,
        plant_conf,
    ) or is_public_safe_multi_block_hybrid_model(optim_conf, plant_conf)


def _freeze_for_signature(value: object) -> object:
    if isinstance(value, Mapping):
        return tuple(
            (key, _freeze_for_signature(nested_value))
            for key, nested_value in sorted(value.items(), key=lambda item: str(item[0]))
        )
    if isinstance(value, list | tuple):
        return tuple(_freeze_for_signature(item) for item in value)
    return value


def inverter_block_structure_signature(plant_conf: Mapping[str, object]) -> tuple:
    """Return the structural cache signature for parsed non-root blocks.

    Block 0 is the legacy flat config. Skipping it keeps a parsed root-only
    config cache-equivalent to the same flat config before parsing.
    """
    blocks = plant_conf.get(INVERTER_BLOCK_CONFIGS_KEY)
    if not isinstance(blocks, Mapping):
        return ()

    signature = []
    for index, block in sorted(blocks.items()):
        if index == 0:
            continue
        signature.append(
            (
                index,
                _freeze_for_signature(block.optim_conf),
                _freeze_for_signature(block.plant_conf),
            )
        )
    return tuple(signature)


@dataclass(frozen=True)
class InverterBlockRuntime:
    """Current CVXPY parameter aliases for one inverter battery runtime state.

    ``Optimization`` rebuilds this wrapper whenever horizon-dependent parameters
    are recreated. The attributes reference owned CVXPY parameter objects;
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
    pv_forecast: Any | None = None


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
    p_pv_curtailment: Any | None = None
    p_batt: Any | None = None
    stored_energy: Any | None = None
    soc: Any | None = None
    battery_mode: Any | None = None
