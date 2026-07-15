import logging

import pytest

from emhass.inverter_blocks import (
    _OPTIONAL_OPTIM_CONF_BLOCK_DEFAULTS,
    _OPTIONAL_PLANT_CONF_BLOCK_DEFAULTS,
    _RESERVED_PV_SOURCE_KEYS,
    INVERTER_BLOCK_CONFIGS_KEY,
    MULTI_INVERTER_MODE_KEY,
    MULTI_INVERTER_MODE_MULTI,
    is_public_safe_multi_block_battery_model,
    is_public_safe_multi_block_hybrid_model,
    merge_inverter_block_runtime_overrides,
    parse_inverter_block_configs,
    project_public_inverter_config,
)

_EXPECTED_RESERVED_PV_SOURCE_KEYS = frozenset(
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


def _root_optim_conf() -> dict:
    return {
        "set_use_pv": True,
        "set_use_battery": True,
        "number_of_deferrable_loads": 0,
    }


def _root_plant_conf() -> dict:
    return {
        "inverter_is_hybrid": True,
        "compute_curtailment": False,
        "battery_discharge_power_max": 5000,
        "battery_charge_power_max": 4600,
        "battery_discharge_efficiency": 0.95,
        "battery_charge_efficiency": 0.95,
        "battery_nominal_energy_capacity": 13300,
        "battery_minimum_state_of_charge": 0.10,
        "battery_maximum_state_of_charge": 0.95,
        "battery_target_state_of_charge": 0.90,
    }


def _valid_block() -> dict:
    return {
        "set_use_pv": True,
        "set_use_battery": True,
        "inverter_is_hybrid": True,
        "compute_curtailment": False,
        "battery_discharge_power_max": 5000,
        "battery_charge_power_max": 4600,
        "battery_discharge_efficiency": 0.95,
        "battery_charge_efficiency": 0.95,
        "battery_nominal_energy_capacity": 13300,
        "battery_minimum_state_of_charge": 0.10,
        "battery_maximum_state_of_charge": 0.95,
        "battery_target_state_of_charge": 0.90,
        "inverter_ac_output_max": 5000,
        "inverter_ac_input_max": 5000,
        "inverter_efficiency_dc_ac": 1.0,
        "inverter_efficiency_ac_dc": 1.0,
    }


def _parse(input_conf: dict, *, multi_inverter_mode: str = "single"):
    optim_conf = _root_optim_conf()
    plant_conf = _root_plant_conf()
    plant_conf[MULTI_INVERTER_MODE_KEY] = multi_inverter_mode
    return parse_inverter_block_configs(input_conf, optim_conf, plant_conf)


def _base_params_with_extra_block(set_use_pv: bool = True, set_use_battery: bool = True) -> dict:
    block = _valid_block()
    block["set_use_pv"] = set_use_pv
    block["set_use_battery"] = set_use_battery
    if not set_use_battery:
        for key in [
            "battery_discharge_power_max",
            "battery_charge_power_max",
            "battery_discharge_efficiency",
            "battery_charge_efficiency",
            "battery_nominal_energy_capacity",
            "battery_minimum_state_of_charge",
            "battery_maximum_state_of_charge",
            "battery_target_state_of_charge",
        ]:
            del block[key]
    return {
        "plant_conf": {MULTI_INVERTER_MODE_KEY: MULTI_INVERTER_MODE_MULTI},
        "hybrid_inverter_config_1": block,
    }


def test_no_extra_blocks_returns_only_root_block():
    optim_conf = _root_optim_conf()
    plant_conf = _root_plant_conf()

    blocks = parse_inverter_block_configs({}, optim_conf, plant_conf)

    assert list(blocks) == [0]
    assert blocks[0].optim_conf is optim_conf
    assert blocks[0].plant_conf is plant_conf
    assert plant_conf[INVERTER_BLOCK_CONFIGS_KEY] is blocks


def test_valid_extra_block_is_parsed_without_inheriting_root_values_in_multi_mode():
    input_conf = {"hybrid_inverter_config_1": _valid_block()}

    blocks = _parse(input_conf, multi_inverter_mode=MULTI_INVERTER_MODE_MULTI)

    assert list(blocks) == [0, 1]
    assert blocks[1].index == 1
    assert blocks[1].optim_conf["set_use_battery"] is True
    assert blocks[1].plant_conf["battery_nominal_energy_capacity"] == 13300
    assert "sensor_power_load_no_var_loads" not in blocks[1].optim_conf
    assert "sensor_power_load_no_var_loads" not in blocks[1].plant_conf


def test_optional_block_defaults_are_canonical_and_sparse_blocks_remain_sparse():
    blocks = _parse(
        {"hybrid_inverter_config_1": _valid_block()},
        multi_inverter_mode=MULTI_INVERTER_MODE_MULTI,
    )

    assert _OPTIONAL_OPTIM_CONF_BLOCK_DEFAULTS == {
        "set_use_pv": False,
        "set_use_battery": False,
        "set_battery_dynamic": False,
        "battery_dynamic_max": 0.9,
        "battery_dynamic_min": -0.9,
        "weight_battery_discharge": 0.0,
        "weight_battery_charge": 0.0,
        "battery_soc_deficit_threshold": 0.40,
        "battery_soc_deficit_cost": 0.0,
        "battery_soc_surplus_threshold": 0.90,
        "battery_soc_surplus_cost": 0.0,
    }
    assert _OPTIONAL_PLANT_CONF_BLOCK_DEFAULTS == {
        "inverter_is_hybrid": False,
        "compute_curtailment": False,
        "battery_stress_cost": 0.0,
        "battery_stress_segments": 10,
        "inverter_stress_cost": 0.0,
        "inverter_stress_segments": 10,
    }
    assert (
        set(_OPTIONAL_OPTIM_CONF_BLOCK_DEFAULTS) - {"set_use_pv", "set_use_battery"}
    ).isdisjoint(blocks[1].optim_conf)
    assert (
        set(_OPTIONAL_PLANT_CONF_BLOCK_DEFAULTS) - {"inverter_is_hybrid", "compute_curtailment"}
    ).isdisjoint(blocks[1].plant_conf)


def test_extra_block_stress_configuration_uses_plant_conf():
    block = _valid_block()
    block.update(
        {
            "battery_stress_cost": 0.3,
            "battery_stress_segments": 7,
            "inverter_stress_cost": 0.5,
            "inverter_stress_segments": 9,
        }
    )

    blocks = _parse(
        {"hybrid_inverter_config_1": block},
        multi_inverter_mode=MULTI_INVERTER_MODE_MULTI,
    )

    assert blocks[1].plant_conf["battery_stress_cost"] == 0.3
    assert blocks[1].plant_conf["battery_stress_segments"] == 7
    assert blocks[1].plant_conf["inverter_stress_cost"] == 0.5
    assert blocks[1].plant_conf["inverter_stress_segments"] == 9
    assert "battery_stress_cost" not in blocks[1].optim_conf
    assert "battery_stress_segments" not in blocks[1].optim_conf


def test_default_single_mode_ignores_indexed_config():
    blocks = _parse({"hybrid_inverter_config_1": _valid_block()})

    assert list(blocks) == [0]


def test_default_single_mode_ignores_indexed_config_holes():
    blocks = _parse({"hybrid_inverter_config_2": _valid_block()})

    assert list(blocks) == [0]


def test_public_safe_battery_model_uses_indexed_topology_not_legacy_root_flags():
    indexed_block = _valid_block()
    indexed_block.update(
        {
            "set_use_pv": False,
            "set_use_battery": True,
            "inverter_is_hybrid": False,
            "compute_curtailment": False,
        }
    )
    optim_conf = _root_optim_conf()
    optim_conf["set_use_battery"] = False
    optim_conf["set_use_pv"] = True
    plant_conf = _root_plant_conf()
    plant_conf.update(
        {
            MULTI_INVERTER_MODE_KEY: MULTI_INVERTER_MODE_MULTI,
            "inverter_is_hybrid": True,
            "compute_curtailment": True,
        }
    )
    parse_inverter_block_configs(
        {"hybrid_inverter_config_1": indexed_block},
        optim_conf,
        plant_conf,
    )

    assert is_public_safe_multi_block_battery_model(optim_conf, plant_conf)


def test_public_safe_hybrid_model_uses_indexed_topology_not_legacy_root_flags():
    indexed_block = _valid_block()
    indexed_block["set_use_pv"] = False
    optim_conf = _root_optim_conf()
    optim_conf["set_use_battery"] = False
    plant_conf = _root_plant_conf()
    plant_conf.update(
        {
            MULTI_INVERTER_MODE_KEY: MULTI_INVERTER_MODE_MULTI,
            "multi_hybrid_inverter_pv_mode": "split_pv",
            "inverter_is_hybrid": False,
        }
    )
    parse_inverter_block_configs(
        {"hybrid_inverter_config_1": indexed_block},
        optim_conf,
        plant_conf,
    )

    assert is_public_safe_multi_block_hybrid_model(optim_conf, plant_conf)


@pytest.mark.parametrize(
    "model_admission",
    [
        is_public_safe_multi_block_battery_model,
        is_public_safe_multi_block_hybrid_model,
    ],
)
def test_public_safe_multi_block_models_preserve_site_direction_lock(model_admission):
    optim_conf = _root_optim_conf()
    optim_conf["battery_mode_lock"] = "per_inverter"
    plant_conf = _root_plant_conf()
    plant_conf[INVERTER_BLOCK_CONFIGS_KEY] = {1: object()}

    assert not model_admission(optim_conf, plant_conf)


def test_project_public_inverter_config_copies_block_one_without_root_fallbacks():
    optim_conf = _root_optim_conf()
    optim_conf.update(
        {
            "set_battery_dynamic": True,
            "weight_battery_charge": 0.7,
        }
    )
    plant_conf = _root_plant_conf()
    plant_conf.update(
        {
            MULTI_INVERTER_MODE_KEY: MULTI_INVERTER_MODE_MULTI,
            "maximum_power_from_grid": 6000,
            "battery_stress_cost": 0.8,
            "inverter_stress_cost": 0.6,
        }
    )
    indexed_block = _valid_block()
    indexed_block.update(
        {
            "set_use_pv": False,
            "set_use_battery": True,
            "inverter_is_hybrid": False,
            "compute_curtailment": False,
            "battery_charge_power_max": 4200,
        }
    )
    parsed_blocks = parse_inverter_block_configs(
        {"hybrid_inverter_config_1": indexed_block},
        optim_conf,
        plant_conf,
    )

    projected_optim_conf, projected_plant_conf = project_public_inverter_config(
        optim_conf,
        plant_conf,
    )

    assert projected_optim_conf is not optim_conf
    assert projected_plant_conf is not plant_conf
    assert projected_optim_conf["set_use_pv"] is False
    assert projected_optim_conf["set_use_battery"] is True
    assert projected_optim_conf["set_battery_dynamic"] is False
    assert projected_optim_conf["weight_battery_charge"] == 0.0
    assert projected_plant_conf["inverter_is_hybrid"] is False
    assert projected_plant_conf["battery_charge_power_max"] == 4200
    assert projected_plant_conf["battery_stress_cost"] == 0.0
    assert projected_plant_conf["inverter_stress_cost"] == 0.0
    assert projected_plant_conf["maximum_power_from_grid"] == 6000
    assert projected_plant_conf[INVERTER_BLOCK_CONFIGS_KEY] is parsed_blocks
    assert optim_conf["set_battery_dynamic"] is True
    assert plant_conf["battery_stress_cost"] == 0.8
    assert plant_conf["inverter_stress_cost"] == 0.6


def test_project_public_inverter_config_leaves_single_mode_values_unchanged():
    optim_conf = _root_optim_conf()
    plant_conf = _root_plant_conf()
    parsed_blocks = parse_inverter_block_configs({}, optim_conf, plant_conf)

    projected_optim_conf, projected_plant_conf = project_public_inverter_config(
        optim_conf,
        plant_conf,
    )

    assert projected_optim_conf == optim_conf
    assert projected_plant_conf == plant_conf
    assert projected_optim_conf is not optim_conf
    assert projected_plant_conf is not plant_conf
    assert projected_plant_conf[INVERTER_BLOCK_CONFIGS_KEY] is parsed_blocks


def test_multi_mode_requires_hybrid_inverter_config_1():
    with pytest.raises(ValueError, match="multi_inverter_mode=multi.*hybrid_inverter_config_1"):
        _parse({}, multi_inverter_mode=MULTI_INVERTER_MODE_MULTI)


def test_static_hybrid_inverter_config_0_is_ignored_with_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="emhass.inverter_blocks"):
        blocks = _parse(
            {
                "hybrid_inverter_config_0": _valid_block(),
                "hybrid_inverter_config_1": _valid_block(),
            },
            multi_inverter_mode=MULTI_INVERTER_MODE_MULTI,
        )

    assert list(blocks) == [0, 1]
    assert "hybrid_inverter_config_0 is ignored" in caplog.text


def test_hybrid_inverter_config_index_must_be_canonical():
    with pytest.raises(ValueError, match="hybrid_inverter_config_01.*positive integer"):
        _parse(
            {"hybrid_inverter_config_01": _valid_block()},
            multi_inverter_mode=MULTI_INVERTER_MODE_MULTI,
        )


@pytest.mark.parametrize(
    "input_conf",
    [
        {"hybrid_inverter_config_2": _valid_block()},
        {
            "hybrid_inverter_config_1": _valid_block(),
            "hybrid_inverter_config_3": _valid_block(),
        },
    ],
)
def test_skipped_hybrid_inverter_indexes_are_invalid(input_conf):
    with pytest.raises(ValueError, match="contiguous|skipped"):
        _parse(input_conf, multi_inverter_mode=MULTI_INVERTER_MODE_MULTI)


@pytest.mark.parametrize(
    "forbidden_key",
    [
        "sensor_power_load_no_var_loads",
        "maximum_power_from_grid",
        "maximum_power_to_grid",
        "set_nocharge_from_grid",
        "set_nodischarge_to_grid",
        "capacity_cost_per_kw",
        "number_of_deferrable_loads",
        "def_load_config",
        "hass_url",
        "long_lived_token",
        "continual_publish",
    ],
)
def test_extra_block_rejects_site_level_keys(forbidden_key):
    block = _valid_block()
    block[forbidden_key] = "bad"

    with pytest.raises(ValueError, match=forbidden_key):
        _parse(
            {"hybrid_inverter_config_1": block},
            multi_inverter_mode=MULTI_INVERTER_MODE_MULTI,
        )


def test_extra_block_rejects_battery_soc_balance_cost_as_site_level_static_key():
    block = _valid_block()
    block["battery_soc_balance_cost"] = 1.0

    with pytest.raises(
        ValueError,
        match=r"hybrid_inverter_config_1\.battery_soc_balance_cost.*not block-local",
    ):
        _parse(
            {"hybrid_inverter_config_1": block},
            multi_inverter_mode=MULTI_INVERTER_MODE_MULTI,
        )


def test_reserved_pv_source_keys_match_expected_contract():
    assert _RESERVED_PV_SOURCE_KEYS == _EXPECTED_RESERVED_PV_SOURCE_KEYS


@pytest.mark.parametrize(
    "reserved_pv_key",
    sorted(_EXPECTED_RESERVED_PV_SOURCE_KEYS),
)
def test_extra_block_rejects_reserved_pv_source_keys_for_step_2(reserved_pv_key):
    block = _valid_block()
    block[reserved_pv_key] = "sensor.power_pv"

    with pytest.raises(ValueError, match=reserved_pv_key):
        _parse(
            {"hybrid_inverter_config_1": block},
            multi_inverter_mode=MULTI_INVERTER_MODE_MULTI,
        )


@pytest.mark.parametrize(
    "missing_key",
    [
        "battery_nominal_energy_capacity",
        "battery_charge_power_max",
        "battery_discharge_power_max",
        "battery_charge_efficiency",
        "battery_discharge_efficiency",
        "battery_minimum_state_of_charge",
        "battery_maximum_state_of_charge",
        "battery_target_state_of_charge",
    ],
)
def test_battery_enabled_extra_block_requires_required_battery_fields(missing_key):
    block = _valid_block()
    del block[missing_key]

    with pytest.raises(ValueError, match=missing_key):
        _parse(
            {"hybrid_inverter_config_1": block},
            multi_inverter_mode=MULTI_INVERTER_MODE_MULTI,
        )


@pytest.mark.parametrize(
    "missing_key",
    [
        "inverter_ac_output_max",
        "inverter_ac_input_max",
        "inverter_efficiency_dc_ac",
        "inverter_efficiency_ac_dc",
    ],
)
def test_hybrid_extra_block_requires_required_hybrid_inverter_fields(missing_key):
    block = _valid_block()
    del block[missing_key]

    with pytest.raises(ValueError, match=missing_key):
        _parse(
            {"hybrid_inverter_config_1": block},
            multi_inverter_mode=MULTI_INVERTER_MODE_MULTI,
        )


@pytest.mark.parametrize(
    "efficiency_key",
    ["battery_charge_efficiency", "battery_discharge_efficiency"],
)
@pytest.mark.parametrize("value", [0, -0.1, 1.01])
def test_extra_block_rejects_invalid_battery_efficiencies(efficiency_key, value):
    block = _valid_block()
    block[efficiency_key] = value

    with pytest.raises(ValueError, match=efficiency_key):
        _parse(
            {"hybrid_inverter_config_1": block},
            multi_inverter_mode=MULTI_INVERTER_MODE_MULTI,
        )


@pytest.mark.parametrize(
    "updates, pattern",
    [
        ({"battery_minimum_state_of_charge": -0.1}, "battery_minimum_state_of_charge"),
        ({"battery_maximum_state_of_charge": 1.1}, "battery_maximum_state_of_charge"),
        (
            {"battery_minimum_state_of_charge": 0.9, "battery_maximum_state_of_charge": 0.9},
            "minimum.*maximum",
        ),
        ({"battery_target_state_of_charge": 0.05}, "battery_target_state_of_charge"),
    ],
)
def test_extra_block_rejects_invalid_soc_bounds(updates, pattern):
    block = _valid_block()
    block.update(updates)

    with pytest.raises(ValueError, match=pattern):
        _parse(
            {"hybrid_inverter_config_1": block},
            multi_inverter_mode=MULTI_INVERTER_MODE_MULTI,
        )


def test_extra_block_rejects_non_dict_value():
    with pytest.raises(ValueError, match="hybrid_inverter_config_1.*dictionary"):
        _parse(
            {"hybrid_inverter_config_1": "bad"},
            multi_inverter_mode=MULTI_INVERTER_MODE_MULTI,
        )


def test_extra_block_rejects_battery_keys_when_battery_disabled():
    block = _valid_block()
    block["set_use_battery"] = False

    with pytest.raises(ValueError, match="set_use_battery"):
        _parse(
            {"hybrid_inverter_config_1": block},
            multi_inverter_mode=MULTI_INVERTER_MODE_MULTI,
        )


def test_invalid_multi_inverter_mode_is_rejected():
    with pytest.raises(ValueError, match="multi_inverter_mode.*multi.*single"):
        _parse({}, multi_inverter_mode="bad")


def test_merge_runtime_rejects_nested_block_in_single_mode():
    params = {"hybrid_inverter_config_1": _valid_block()}
    runtime = {
        "hybrid_inverter_config_1": {
            "soc_init": 0.51,
        }
    }

    with pytest.raises(ValueError, match="multi_inverter_mode=multi"):
        merge_inverter_block_runtime_overrides(params, runtime)


def test_merge_runtime_mode_override_enables_configured_nested_block():
    params = {"hybrid_inverter_config_1": _valid_block()}
    runtime = {
        "multi_inverter_mode": "multi",
        "hybrid_inverter_config_1": {
            "soc_init": 0.51,
        },
    }

    runtime_conf = merge_inverter_block_runtime_overrides(params, runtime)

    assert runtime_conf[1]["soc_init"] == 0.51


def test_merge_runtime_accepts_nested_pv_forecast_for_configured_pv_block():
    params = _base_params_with_extra_block(set_use_pv=True)
    runtime = {
        "hybrid_inverter_config_1": {
            "pv_power_forecast": [0, 100, 250],
        }
    }

    runtime_conf = merge_inverter_block_runtime_overrides(params, runtime)

    assert runtime_conf[1]["pv_power_forecast"] == [0, 100, 250]


def test_merge_runtime_accepts_nested_pv_forecast_without_battery_soc_bounds():
    params = _base_params_with_extra_block(set_use_pv=True, set_use_battery=False)
    runtime = {
        "hybrid_inverter_config_1": {
            "pv_power_forecast": [0, 100, 250],
        }
    }

    runtime_conf = merge_inverter_block_runtime_overrides(params, runtime)

    assert runtime_conf[1]["pv_power_forecast"] == [0, 100, 250]


def test_merge_runtime_accepts_nested_battery_cap_overrides():
    params = _base_params_with_extra_block(set_use_pv=False)
    runtime = {
        "hybrid_inverter_config_1": {
            "battery_charge_power_max": 4200,
            "battery_discharge_power_max": 4300,
        }
    }

    runtime_conf = merge_inverter_block_runtime_overrides(params, runtime)

    assert runtime_conf[1] == {
        "soc_init": 0.90,
        "soc_final": 0.90,
    }
    assert params["hybrid_inverter_config_1"]["battery_charge_power_max"] == 4200
    assert params["hybrid_inverter_config_1"]["battery_discharge_power_max"] == 4300


@pytest.mark.parametrize(
    "soc_target",
    [True, "0.50", float("nan"), float("inf"), -0.01, 1.01],
)
def test_merge_runtime_rejects_invalid_nested_soc_target(soc_target):
    params = _base_params_with_extra_block(set_use_pv=False)

    with pytest.raises(ValueError, match=r"soc_target.*(numeric|finite|\[0, 1\])"):
        merge_inverter_block_runtime_overrides(
            params,
            {"hybrid_inverter_config_1": {"soc_target": soc_target}},
        )


def test_merge_runtime_preserves_valid_nested_soc_target_for_effective_limit_clamp():
    params = _base_params_with_extra_block(set_use_pv=False)

    runtime_conf = merge_inverter_block_runtime_overrides(
        params,
        {
            "hybrid_inverter_config_1": {
                "battery_minimum_state_of_charge": 0.25,
                "battery_maximum_state_of_charge": 0.50,
                "soc_target": 0.75,
            }
        },
    )

    assert runtime_conf[1]["soc_target"] == 0.75


def test_merge_runtime_soc_final_uses_effective_runtime_bounds_and_clamps(caplog):
    params = _base_params_with_extra_block(set_use_pv=False)
    runtime = {
        "hybrid_inverter_config_1": {
            "battery_minimum_state_of_charge": 0.25,
            "battery_maximum_state_of_charge": 1.0,
            "battery_target_state_of_charge": 0.50,
            "soc_final": 0.0,
        }
    }

    with caplog.at_level(logging.WARNING, logger="emhass.inverter_blocks"):
        runtime_conf = merge_inverter_block_runtime_overrides(params, runtime)

    assert runtime_conf[1]["soc_init"] == 0.50
    assert runtime_conf[1]["soc_final"] == 0.25
    assert params["hybrid_inverter_config_1"]["battery_minimum_state_of_charge"] == 0.25
    assert params["hybrid_inverter_config_1"]["battery_maximum_state_of_charge"] == 1.0
    assert "soc_final=0.0 is lower than soc_min=0.25" in caplog.text


def test_merge_runtime_bounds_can_make_static_target_out_of_range_without_hard_fail(caplog):
    params = _base_params_with_extra_block(set_use_pv=False)
    runtime = {
        "hybrid_inverter_config_1": {
            "battery_minimum_state_of_charge": 0.95,
            "battery_maximum_state_of_charge": 1.0,
        }
    }

    with caplog.at_level(logging.WARNING, logger="emhass.inverter_blocks"):
        runtime_conf = merge_inverter_block_runtime_overrides(params, runtime)

    assert runtime_conf[1]["soc_init"] == 0.90
    assert runtime_conf[1]["soc_final"] == 0.95
    assert params["hybrid_inverter_config_1"]["battery_minimum_state_of_charge"] == 0.95
    assert "soc_init=0.9 is lower than soc_min=0.95" in caplog.text
    assert "soc_final=0.9 is lower than soc_min=0.95" in caplog.text

    optim_conf = _root_optim_conf()
    plant_conf = params["plant_conf"]
    blocks = parse_inverter_block_configs(params, optim_conf, plant_conf, runtime_conf)
    assert blocks[1].runtime_conf["soc_final"] == 0.95
    assert blocks[1].plant_conf["battery_target_state_of_charge"] == 0.90
    assert "_hybrid_inverter_runtime_target_bounds_relaxed_indexes" not in plant_conf


def test_merge_runtime_soc_only_does_not_hide_invalid_static_target():
    params = _base_params_with_extra_block(set_use_pv=False)
    params["hybrid_inverter_config_1"]["battery_target_state_of_charge"] = 0.05

    with pytest.raises(
        ValueError,
        match="battery_target_state_of_charge must be within min/max SOC",
    ):
        merge_inverter_block_runtime_overrides(
            params,
            {"hybrid_inverter_config_1": {"soc_init": 0.50}},
        )


def test_merge_runtime_soc_init_outside_bounds_warns_and_keeps_value(caplog):
    params = _base_params_with_extra_block(set_use_pv=False)
    runtime = {
        "hybrid_inverter_config_1": {
            "battery_minimum_state_of_charge": 0.25,
            "battery_maximum_state_of_charge": 1.0,
            "battery_target_state_of_charge": 0.50,
            "soc_init": 0.10,
        }
    }

    with caplog.at_level(logging.WARNING, logger="emhass.inverter_blocks"):
        runtime_conf = merge_inverter_block_runtime_overrides(params, runtime)

    assert runtime_conf[1]["soc_init"] == 0.10
    assert runtime_conf[1]["soc_final"] == 0.50
    assert "soc_init=0.1 is lower than soc_min=0.25" in caplog.text


def test_merge_runtime_missing_soc_fields_default_independently_from_effective_target():
    params = _base_params_with_extra_block(set_use_pv=False)

    runtime_conf = merge_inverter_block_runtime_overrides(
        params,
        {
            "hybrid_inverter_config_1": {
                "battery_minimum_state_of_charge": 0.20,
                "battery_maximum_state_of_charge": 0.90,
                "battery_target_state_of_charge": 0.40,
                "soc_init": 0.80,
            }
        },
    )
    assert runtime_conf[1]["soc_init"] == 0.80
    assert runtime_conf[1]["soc_final"] == 0.40

    params = _base_params_with_extra_block(set_use_pv=False)
    runtime_conf = merge_inverter_block_runtime_overrides(
        params,
        {
            "hybrid_inverter_config_1": {
                "battery_minimum_state_of_charge": 0.20,
                "battery_maximum_state_of_charge": 0.90,
                "battery_target_state_of_charge": 0.40,
                "soc_final": 0.80,
            }
        },
    )
    assert runtime_conf[1]["soc_init"] == 0.40
    assert runtime_conf[1]["soc_final"] == 0.80


def test_merge_runtime_rejects_nested_pv_forecast_for_non_pv_block():
    params = _base_params_with_extra_block(set_use_pv=False)
    runtime = {
        "hybrid_inverter_config_1": {
            "pv_power_forecast": [0, 100, 250],
        }
    }

    with pytest.raises(ValueError, match="pv_power_forecast.*requires set_use_pv true"):
        merge_inverter_block_runtime_overrides(params, runtime)


def test_merge_runtime_rejects_nested_compute_curtailment():
    params = _base_params_with_extra_block()

    with pytest.raises(ValueError, match="compute_curtailment"):
        merge_inverter_block_runtime_overrides(
            params,
            {"hybrid_inverter_config_1": {"compute_curtailment": True}},
        )


def test_merge_runtime_rejects_nested_site_level_key():
    params = _base_params_with_extra_block()

    with pytest.raises(ValueError, match="maximum_power_from_grid"):
        merge_inverter_block_runtime_overrides(
            params,
            {"hybrid_inverter_config_1": {"maximum_power_from_grid": 5000}},
        )


def test_merge_runtime_rejects_nested_battery_soc_balance_cost_as_site_level_key():
    params = _base_params_with_extra_block()

    with pytest.raises(
        ValueError,
        match=r"hybrid_inverter_config_1\.battery_soc_balance_cost.*not block-local",
    ):
        merge_inverter_block_runtime_overrides(
            params,
            {"hybrid_inverter_config_1": {"battery_soc_balance_cost": 1.0}},
        )
