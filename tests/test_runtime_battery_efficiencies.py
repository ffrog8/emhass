"""Scalar battery efficiency overrides through real public MPC requests."""

import asyncio
import copy
import json
import logging
import pathlib
import pickle

import numpy as np
import pandas as pd
import pytest

from emhass import utils, web_server
from emhass.command_line import OptimizationCache


@pytest.fixture
def efficiency_site(tmp_path, monkeypatch, request):
    options = getattr(request, "param", {})
    root = pathlib.Path(__file__).resolve().parents[1]
    conf = {
        "data_path": tmp_path,
        "root_path": root / "src/emhass",
        "config_path": tmp_path / "config.json",
        "defaults_path": root / "src/emhass/data/config_defaults.json",
        "associations_path": root / "src/emhass/data/associations.csv",
    }
    config = json.loads(conf["defaults_path"].read_text())
    config.update(
        {
            "number_of_deferrable_loads": 0,
            "set_use_pv": True,
            "set_use_battery": True,
            "set_use_adjusted_pv": False,
            "set_nocharge_from_grid": False,
            "set_nodischarge_to_grid": True,
            "inverter_is_hybrid": True,
            "compute_curtailment": True,
            "inverter_ac_output_max": 5000,
            "inverter_ac_input_max": 5000,
            "inverter_efficiency_dc_ac": 1.0,
            "inverter_efficiency_ac_dc": 1.0,
            "battery_minimum_state_of_charge": 0.1,
            "battery_maximum_state_of_charge": 0.9,
            "battery_target_state_of_charge": 0.5,
            "battery_charge_efficiency": options.get("flat_charge", 0.85),
            "battery_discharge_efficiency": options.get("flat_discharge", 0.85),
            "battery_nominal_energy_capacity": 10000,
            "multi_inverter_mode": options.get("mode", "multi"),
            "multi_hybrid_inverter_pv_mode": "split_pv",
            "battery_mode_lock": "site",
            "num_threads": 1,
        }
    )
    efficiencies = options.get("static", [(0.85, 0.85), (0.85, 0.85)])
    if config["multi_inverter_mode"] == "multi":
        for index, (charge, discharge) in enumerate(efficiencies, 1):
            config[f"hybrid_inverter_config_{index}"] = {
                "set_use_pv": True,
                "set_use_battery": True,
                "inverter_is_hybrid": True,
                "compute_curtailment": True,
                "battery_discharge_power_max": 3000,
                "battery_charge_power_max": 3000,
                "battery_discharge_efficiency": discharge,
                "battery_charge_efficiency": charge,
                "battery_nominal_energy_capacity": 10000 if index == 1 else 16000,
                "battery_minimum_state_of_charge": 0.1,
                "battery_maximum_state_of_charge": 0.9,
                "battery_target_state_of_charge": 0.5,
                "inverter_ac_output_max": 5000,
                "inverter_ac_input_max": 5000,
                "inverter_efficiency_dc_ac": 1.0,
                "inverter_efficiency_ac_dc": 1.0,
            }
    config["battery_soc_power_profiles"] = [{}] * (
        len(efficiencies) if config["multi_inverter_mode"] == "multi" else 1
    )
    conf["config_path"].write_text(json.dumps(config))

    async def build():
        _, secrets = await utils.build_secrets(conf, logging.getLogger(__name__), no_response=True)
        return await utils.build_params(conf, secrets, config, logging.getLogger(__name__))

    params = asyncio.run(build())
    params["retrieve_hass_conf"]["long_lived_token"] = ""
    saved_params = tmp_path / "params.pkl"
    saved_params.write_bytes(pickle.dumps((conf, params)))
    monkeypatch.setattr(web_server, "emhass_conf", conf)
    monkeypatch.setattr(web_server, "continual_publish_thread", [])
    handler = logging.FileHandler(tmp_path / "action_logs.txt")
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    old_level = web_server.app.logger.level
    web_server.app.logger.setLevel(logging.DEBUG)
    web_server.app.logger.addHandler(handler)
    OptimizationCache.clear()

    async def post(payload):
        response = await web_server.app.test_client().post("/action/naive-mpc-optim", json=payload)
        body = await response.get_data(as_text=True)
        result_path = tmp_path / "opt_res_latest.csv"
        result = pd.read_csv(result_path) if result_path.exists() else None
        return response.status_code, body, result

    yield post, conf, params
    OptimizationCache.clear()
    web_server.app.logger.removeHandler(handler)
    web_server.app.logger.setLevel(old_level)
    handler.close()


def efficiency_payload(direction, mode="multi"):
    payload = {
        "prediction_horizon": 6,
        "pv_power_forecast": [0.0] * 48,
        "load_power_forecast": [0.0 if direction == "charge" else 8000.0] * 48,
        "load_cost_forecast": [0.01 if direction == "charge" else 1.0] * 48,
        "prod_price_forecast": [0.0] * 48,
        "soc_init": 0.5,
        "soc_final": 0.7 if direction == "charge" else 0.3,
    }
    if mode == "multi":
        for index in (1, 2):
            payload[f"hybrid_inverter_config_{index}"] = {
                "soc_init": payload["soc_init"],
                "soc_final": payload["soc_final"],
                "pv_power_forecast": [0.0] * 48,
            }
    return payload


def assert_energy_balances(result, efficiencies, direction, mode="multi"):
    # Independent physical balance in Wh: battery discharge consumes P/eta,
    # charging stores -P*eta. SOC columns describe the end of each 30-minute step.
    for index, (charge, discharge) in enumerate(efficiencies, 1):
        suffix = f"_{index}" if mode == "multi" else ""
        capacity = 10000 if index == 1 else 16000
        powers = result[f"P_batt{suffix}"].to_numpy()
        if direction == "charge":
            assert powers.min() < -100, f"battery {index} did not charge"
        else:
            assert powers.max() > 100, f"battery {index} did not discharge"
        energy_changes = np.maximum(powers, 0) / discharge + np.minimum(powers, 0) * charge
        expected_soc = 0.5 - np.cumsum(energy_changes * 0.5) / capacity
        np.testing.assert_allclose(result[f"SOC_opt{suffix}"], expected_soc, atol=1e-5, rtol=0)
        if mode == "multi" and index > 1:
            # The extra inverter's hard terminal target also proves the solver
            # used these efficiencies, rather than only recomputing result SOC.
            assert result[f"SOC_opt{suffix}"].iloc[-1] == pytest.approx(
                0.7 if direction == "charge" else 0.3, abs=1e-5
            )


@pytest.mark.parametrize("direction", ["charge", "discharge"])
def test_rest_scalar_efficiencies_reach_every_battery_energy_balance(efficiency_site, direction):
    post, _, _ = efficiency_site
    payload = efficiency_payload(direction)
    payload.update(battery_charge_efficiency=0.995, battery_discharge_efficiency=0.985)
    status, body, result = asyncio.run(post(payload))
    assert status == 200, body
    assert_energy_balances(result, [(0.995, 0.985)] * 2, direction)


@pytest.mark.parametrize(
    "efficiency_site", [{"static": [(0.81, 0.83), (0.91, 0.93)]}], indirect=True
)
@pytest.mark.parametrize("direction", ["charge", "discharge"])
@pytest.mark.parametrize("supplied", ["charge", "discharge", "neither"])
def test_rest_omitted_directions_keep_each_batterys_static_efficiency(
    efficiency_site, direction, supplied
):
    post, _, _ = efficiency_site
    payload = efficiency_payload(direction)
    expected = [(0.81, 0.83), (0.91, 0.93)]
    if supplied == "charge":
        payload["battery_charge_efficiency"] = 0.995
        expected = [(0.995, 0.83), (0.995, 0.93)]
    elif supplied == "discharge":
        payload["battery_discharge_efficiency"] = 0.985
        expected = [(0.81, 0.985), (0.91, 0.985)]
    status, body, result = asyncio.run(post(payload))
    assert status == 200, body
    assert_energy_balances(result, expected, direction)


@pytest.mark.parametrize(
    "efficiency_site", [{"static": [(0.81, 0.83), (0.91, 0.93)]}], indirect=True
)
@pytest.mark.parametrize("direction", ["charge", "discharge"])
def test_rest_changed_then_reused_and_fresh_efficiencies_are_request_scoped(
    efficiency_site, direction
):
    post, conf, _ = efficiency_site
    saved_files = [conf["config_path"], conf["data_path"] / "params.pkl"]
    original = [path.read_bytes() for path in saved_files]

    async def run():
        payload = efficiency_payload(direction)

        async def checked(overrides, expected):
            status, body, result = await post({**payload, **overrides})
            assert status == 200, body
            assert_energy_balances(result, expected, direction)
            return OptimizationCache._instance, OptimizationCache._instance.prob

        first, _ = await checked(
            {"battery_charge_efficiency": 0.95, "battery_discharge_efficiency": 0.96},
            [(0.95, 0.96)] * 2,
        )
        changed = {"battery_charge_efficiency": 0.995, "battery_discharge_efficiency": 0.985}
        second, second_problem = await checked(changed, [(0.995, 0.985)] * 2)
        assert second is not first  # efficiencies are structural CVXPY coefficients
        cached, cached_problem = await checked(changed, [(0.995, 0.985)] * 2)
        assert cached is second
        assert cached_problem is second_problem
        OptimizationCache.clear()
        fresh, _ = await checked(changed, [(0.995, 0.985)] * 2)
        assert fresh is not second

        # Omit the exercised direction after warming both overrides. The other
        # direction still overrides, while the omitted one returns to static.
        partial = (
            {"battery_discharge_efficiency": 0.985}
            if direction == "charge"
            else {"battery_charge_efficiency": 0.995}
        )
        expected = (
            [(0.81, 0.985), (0.91, 0.985)]
            if direction == "charge"
            else [(0.995, 0.83), (0.995, 0.93)]
        )
        omitted, omitted_problem = await checked(partial, expected)
        assert omitted is not fresh
        repeated, repeated_problem = await checked(partial, expected)
        assert repeated is omitted
        assert repeated_problem is omitted_problem
        static, static_problem = await checked({}, [(0.81, 0.83), (0.91, 0.93)])
        assert static is not omitted
        repeated, repeated_problem = await checked({}, [(0.81, 0.83), (0.91, 0.93)])
        assert repeated is static
        assert repeated_problem is static_problem

    asyncio.run(run())
    assert [path.read_bytes() for path in saved_files] == original


@pytest.mark.parametrize("key", ["battery_charge_efficiency", "battery_discharge_efficiency"])
@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        "0.8",
        "bad",
        [],
        {},
        float("nan"),
        float("inf"),
        float("-inf"),
        0,
        -0.1,
        1.01,
    ],
)
def test_rest_invalid_direction_preserves_last_plan_and_cached_model(efficiency_site, key, value):
    post, conf, _ = efficiency_site

    async def run():
        payload = efficiency_payload("charge")
        valid = {
            **payload,
            "battery_charge_efficiency": 0.995,
            "battery_discharge_efficiency": 0.985,
        }
        status, body, result = await post(valid)
        assert status == 200, body
        assert_energy_balances(result, [(0.995, 0.985)] * 2, "charge")
        model = OptimizationCache._instance
        problem = model.prob
        previous_efficiencies = [
            (
                block.plant_conf["battery_charge_efficiency"],
                block.plant_conf["battery_discharge_efficiency"],
            )
            for block in model.inverter_block_config.values()
            if block.set_use_battery
        ]
        plan_path = conf["data_path"] / "opt_res_latest.csv"
        last_plan = plan_path.read_bytes()
        invalid = {
            **valid,
            "battery_charge_efficiency": 0.8,
            "battery_discharge_efficiency": 0.8,
            key: value,
        }
        status, body, result = await post(invalid)
        assert status == 400, body
        assert key in body
        assert plan_path.read_bytes() == last_plan
        assert OptimizationCache._instance is model
        assert model.prob is problem
        assert [
            (
                block.plant_conf["battery_charge_efficiency"],
                block.plant_conf["battery_discharge_efficiency"],
            )
            for block in model.inverter_block_config.values()
            if block.set_use_battery
        ] == previous_efficiencies
        status, body, result = await post(valid)
        assert status == 200, body
        assert_energy_balances(result, [(0.995, 0.985)] * 2, "charge")
        assert OptimizationCache._instance is model
        assert model.prob is problem

    asyncio.run(run())


@pytest.mark.parametrize(
    "efficiency_site",
    [
        {"mode": "single", "flat_charge": 0.81, "flat_discharge": 0.83},
        {"mode": "single", "flat_charge": [0.81], "flat_discharge": [0.83]},
    ],
    indirect=True,
)
@pytest.mark.parametrize("direction", ["charge", "discharge"])
@pytest.mark.parametrize("supplied", ["both", "charge", "discharge", "neither"])
def test_rest_single_inverter_keeps_scalar_and_static_list_compatibility(
    efficiency_site, direction, supplied
):
    post, _, _ = efficiency_site
    payload = efficiency_payload(direction, mode="single")
    charge, discharge = 0.81, 0.83
    if supplied in ("both", "charge"):
        payload["battery_charge_efficiency"] = charge = 0.995
    if supplied in ("both", "discharge"):
        payload["battery_discharge_efficiency"] = discharge = 0.985
    status, body, result = asyncio.run(post(payload))
    assert status == 200, body
    assert_energy_balances(result, [(charge, discharge)], direction, mode="single")


@pytest.mark.parametrize("value", [1, 0.01])
@pytest.mark.parametrize("direction", ["charge", "discharge"])
def test_rest_accepts_valid_fraction_scalars_at_supported_range(efficiency_site, value, direction):
    post, _, _ = efficiency_site
    payload = efficiency_payload(direction)
    # Small changes keep a low-efficiency terminal request physically feasible.
    payload["lp_solver_mip_rel_gap"] = 0
    payload["soc_final"] = 0.501 if direction == "charge" else 0.499
    if direction == "charge":
        payload["load_cost_forecast"] = [0.0] * 48
    for index in (1, 2):
        payload[f"hybrid_inverter_config_{index}"]["soc_final"] = payload["soc_final"]
    payload.update(battery_charge_efficiency=value, battery_discharge_efficiency=value)
    status, body, result = asyncio.run(post(payload))
    assert status == 200, body
    # This small target stays feasible even at 1% efficiency; verify actual flow.
    for index in (1, 2):
        powers = result[f"P_batt_{index}"].to_numpy()
        assert np.abs(powers).max() > 0.01
        expected = 0.5 - np.cumsum(
            (np.maximum(powers, 0) / value + np.minimum(powers, 0) * value) * 0.5
        ) / (10000 if index == 1 else 16000)
        np.testing.assert_allclose(result[f"SOC_opt_{index}"], expected, atol=1e-5, rtol=0)


def test_public_runtime_preparation_keeps_pv_only_inverter_without_battery(efficiency_site):
    _, conf, params = efficiency_site
    params = copy.deepcopy(params)
    pv_only = {
        "set_use_pv": True,
        "set_use_battery": False,
        "inverter_is_hybrid": False,
        "compute_curtailment": True,
    }
    params["hybrid_inverter_config_3"] = copy.deepcopy(pv_only)
    original_batteries = [
        copy.deepcopy(params[f"hybrid_inverter_config_{index}"]) for index in (1, 2)
    ]
    runtime = efficiency_payload("charge")
    runtime.update(battery_charge_efficiency=0.995, battery_discharge_efficiency=0.985)
    runtime["hybrid_inverter_config_3"] = {"pv_power_forecast": [1000.0] * 48}
    retrieve_hass_conf, optim_conf, plant_conf = utils.get_yaml_parse(
        params, logging.getLogger(__name__)
    )

    async def prepare():
        return await utils.treat_runtimeparams(
            runtime,
            params,
            retrieve_hass_conf,
            optim_conf,
            plant_conf,
            "naive-mpc-optim",
            logging.getLogger(__name__),
            conf,
        )

    _, _, _, plant_conf = asyncio.run(prepare())
    assert params["hybrid_inverter_config_3"] == pv_only
    block = plant_conf["_inverter_block_configs"][3]
    assert block.set_use_pv
    assert not block.set_use_battery
    assert "battery_charge_efficiency" not in block.plant_conf
    assert "battery_discharge_efficiency" not in block.plant_conf
    for index, original in enumerate(original_batteries, 1):
        assert params[f"hybrid_inverter_config_{index}"] == {
            **original,
            "battery_charge_efficiency": 0.995,
            "battery_discharge_efficiency": 0.985,
        }


@pytest.mark.parametrize("key", ["battery_charge_efficiency", "battery_discharge_efficiency"])
@pytest.mark.parametrize("value", [True, float("nan"), 10**400])
def test_public_runtime_preparation_rejects_both_directions_before_efficiency_mutation(
    efficiency_site, key, value
):
    _, conf, params = efficiency_site
    params = copy.deepcopy(params)
    original = {
        name: copy.deepcopy(params[name])
        for name in ("plant_conf", "hybrid_inverter_config_1", "hybrid_inverter_config_2")
    }
    runtime = {
        "multi_inverter_mode": "single",
        "battery_charge_efficiency": 0.995,
        "battery_discharge_efficiency": 0.985,
        key: value,
    }

    async def prepare():
        return await utils.treat_runtimeparams(
            runtime,
            params,
            params["retrieve_hass_conf"],
            params["optim_conf"],
            params["plant_conf"],
            "naive-mpc-optim",
            logging.getLogger(__name__),
            conf,
        )

    with pytest.raises(ValueError, match=key):
        asyncio.run(prepare())
    assert {name: params[name] for name in original} == original
