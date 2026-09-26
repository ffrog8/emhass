"""Ticket #18: request-scoped sell-price gating through the REST optimisation path."""

import asyncio
import json
import logging
import pathlib
import pickle

import cvxpy as cp
import pandas as pd
import pytest

from emhass import utils, web_server
from emhass.command_line import OptimizationCache


@pytest.fixture
def rest_site(tmp_path, monkeypatch, request):
    options = getattr(request, "param", {})
    if isinstance(options, bool):
        options = {"compute_curtailment": options}
    curtailment = options.get("compute_curtailment", True)
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
            "set_nocharge_from_grid": True,
            "set_nodischarge_to_grid": False,
            "inverter_is_hybrid": True,
            "compute_curtailment": curtailment,
            "inverter_ac_output_max": 5000,
            "inverter_ac_input_max": 5000,
            "inverter_efficiency_dc_ac": 1.0,
            "inverter_efficiency_ac_dc": 1.0,
            "battery_maximum_state_of_charge": 0.9,
            "battery_target_state_of_charge": 0.9,
            "multi_inverter_mode": "multi",
            "multi_hybrid_inverter_pv_mode": "split_pv",
            "battery_mode_lock": "site",
            "num_threads": 1,
        }
    )
    block = {
        "set_use_pv": True,
        "set_use_battery": True,
        "inverter_is_hybrid": True,
        "compute_curtailment": curtailment,
        "battery_discharge_power_max": 3000,
        "battery_charge_power_max": 3000,
        "battery_discharge_efficiency": 0.95,
        "battery_charge_efficiency": 0.95,
        "battery_nominal_energy_capacity": 10000,
        "battery_minimum_state_of_charge": 0.1,
        "battery_maximum_state_of_charge": 0.9,
        "battery_target_state_of_charge": 0.9,
        "inverter_ac_output_max": 5000,
        "inverter_ac_input_max": 5000,
        "inverter_efficiency_dc_ac": 1.0,
        "inverter_efficiency_ac_dc": 1.0,
    }
    config.update(options.get("config", {}))
    if config["multi_inverter_mode"] == "multi":
        for index, efficiency in enumerate(options.get("inverter_efficiencies", [1.0, 1.0]), 1):
            config[f"hybrid_inverter_config_{index}"] = {
                **block,
                "inverter_efficiency_dc_ac": efficiency,
            }
    config["battery_soc_power_profiles"] = [
        {"charge": {"soc_breakpoints": [0.5], "power_max": [3000, 1000]}},
        {"charge": {"soc_breakpoints": [0.5], "power_max": [3000, 1000]}},
    ]

    async def build():
        _, secrets = await utils.build_secrets(conf, logging.getLogger(__name__), no_response=True)
        return await utils.build_params(conf, secrets, config, logging.getLogger(__name__))

    params = asyncio.run(build())
    params["retrieve_hass_conf"]["long_lived_token"] = ""
    (tmp_path / "params.pkl").write_bytes(pickle.dumps((conf, params)))
    monkeypatch.setattr(web_server, "emhass_conf", conf)
    monkeypatch.setattr(web_server, "continual_publish_thread", [])
    handler = logging.FileHandler(tmp_path / "action_logs.txt")
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    old_level = web_server.app.logger.level
    web_server.app.logger.setLevel(logging.INFO)
    web_server.app.logger.addHandler(handler)
    OptimizationCache.clear()

    async def post(payload, action="naive-mpc-optim"):
        response = await web_server.app.test_client().post(f"/action/{action}", json=payload)
        body = await response.get_data(as_text=True)
        result_path = tmp_path / "opt_res_latest.csv"
        result = pd.read_csv(result_path) if result_path.exists() else None
        return response.status_code, body, result

    yield post
    OptimizationCache.clear()
    web_server.app.logger.removeHandler(handler)
    web_server.app.logger.setLevel(old_level)
    handler.close()


def request_payload():
    return {
        "prediction_horizon": 6,
        "pv_power_forecast": [1000.0] * 48,
        "load_power_forecast": [500.0] * 48,
        "load_cost_forecast": [0.5] * 48,
        "prod_price_forecast": [0.1, 0.2, 0.3, 0.4, 0.3, 0.4] * 8,
        "soc_init": 0.9,
        "soc_final": 0.9,
        "hybrid_inverter_config_1": {
            "soc_init": 0.9,
            "soc_final": 0.9,
            "pv_power_forecast": [1000.0] * 48,
        },
        "hybrid_inverter_config_2": {
            "soc_init": 0.9,
            "soc_final": 0.9,
            "pv_power_forecast": [2000.0] * 48,
        },
    }


def battery_export_payload():
    """Stored energy exceeds all six periods' discharge capacity.

    Export is attractive even in the first two cheap periods unless blocked;
    the test therefore detects a missing threshold rather than price arbitrage.
    """
    payload = request_payload()
    payload["pv_power_forecast"] = [0.0] * 48
    payload["load_power_forecast"] = [0.0] * 48
    for index in (1, 2):
        payload[f"hybrid_inverter_config_{index}"].update(
            {
                # The extra block has an existing hard terminal SOC equality;
                # retain it when an all-blocked request has no discharge sink.
                "soc_final": 0.5 if index == 1 else 0.9,
                "pv_power_forecast": [0.0] * 48,
                "battery_discharge_power_max": 1000,
            }
        )
    return payload


def test_rest_blocks_battery_export_below_and_at_threshold(rest_site):
    payload = battery_export_payload()
    payload["grid_export_sell_price_threshold"] = 0.2
    status, body, result = asyncio.run(rest_site(payload))
    assert status == 200, body
    assert result["P_grid_neg"].iloc[:2].abs().max() <= 1e-5
    assert (result["P_grid_neg"].iloc[2:] < -100).any()
    assert {"P_batt_1", "P_batt_2", "P_PV_1", "P_PV_2"} <= set(result.columns)


@pytest.mark.parametrize(
    "value", [None, True, False, "0.2", "bad", [], {}, float("inf"), float("nan")]
)
def test_rest_rejects_invalid_threshold(rest_site, value):
    payload = request_payload()
    payload["grid_export_sell_price_threshold"] = value
    status, body, result = asyncio.run(rest_site(payload))
    assert status == 400, body
    assert "grid_export_sell_price_threshold must be a finite number" in body
    assert result is None


@pytest.mark.parametrize("threshold", [0, -0.2])
def test_rest_accepts_zero_and_negative_thresholds(rest_site, threshold):
    payload = battery_export_payload()
    payload["grid_export_sell_price_threshold"] = threshold
    payload["prod_price_forecast"] = [threshold - 0.1, threshold, 0.3, 0.4, 0.3, 0.4] * 8
    status, body, result = asyncio.run(rest_site(payload))
    assert status == 200, body
    assert result["P_grid_neg"].iloc[:2].abs().max() <= 1e-5
    assert (result["P_grid_neg"].iloc[2:] < -100).any()


def test_successive_requests_change_and_clear_threshold_on_cached_problem(rest_site, caplog):
    caplog.set_level(logging.DEBUG, logger=web_server.app.logger.name)

    async def run():
        payload = battery_export_payload()
        status, body, baseline = await rest_site(payload)
        assert status == 200, body
        for threshold in (0.5, 0.2, 0.5):
            payload["grid_export_sell_price_threshold"] = threshold
            status, body, result = await rest_site(payload)
            assert status == 200, body
            blocked = result["unit_prod_price"] <= threshold
            assert result.loc[blocked, "P_grid_neg"].abs().max() <= 1e-5
            if threshold == 0.2:
                assert (result.loc[~blocked, "P_grid_neg"] < -100).any()
        del payload["grid_export_sell_price_threshold"]
        status, body, omitted = await rest_site(payload)
        assert status == 200, body
        assert (omitted["P_grid_neg"].iloc[:2] < -100).all()
        assert omitted["cost_fun_profit"].sum() == pytest.approx(baseline["cost_fun_profit"].sum())

    asyncio.run(run())
    assert caplog.text.count("OptimizationCache HIT") == 4


def test_above_threshold_does_not_force_economically_unwanted_export(rest_site):
    payload = request_payload()
    payload["grid_export_sell_price_threshold"] = -0.2
    payload["prod_price_forecast"] = [-0.1] * 48
    status, body, result = asyncio.run(rest_site(payload))
    assert status == 200, body
    assert result["P_grid_neg"].abs().max() <= 1e-5
    assert result["P_PV_curtailment"].sum() > 0


@pytest.mark.parametrize("failure_status", [cp.USER_LIMIT, cp.INFEASIBLE])
def test_threshold_survives_solver_fallback_and_next_cached_request(
    rest_site, monkeypatch, failure_status
):
    # CVXPY is the external solver boundary. Fail just its first attempt, then
    # solve the fallback and the next request with the real solver.
    original_solve = cp.Problem.solve
    attempts = []

    def fail_first(problem, *args, **kwargs):
        attempts.append(problem)
        if len(attempts) == 1:
            problem._status = failure_status
            problem._value = None
            return None
        return original_solve(problem, *args, **kwargs)

    monkeypatch.setattr(cp.Problem, "solve", fail_first)

    async def run():
        payload = battery_export_payload()
        payload["grid_export_sell_price_threshold"] = 0.2
        status, body, result = await rest_site(payload)
        assert status == 200, body
        assert len(attempts) == 2
        assert result["P_grid_neg"].iloc[:2].abs().max() <= 1e-5
        expected = "Optimal" if failure_status == cp.USER_LIMIT else "Optimal (Relaxed)"
        assert result["optim_status"].eq(expected).all()
        del payload["grid_export_sell_price_threshold"]
        status, body, result = await rest_site(payload)
        assert status == 200, body
        assert (result["P_grid_neg"].iloc[:2] < -100).all()
        assert attempts[2] is attempts[0]

    asyncio.run(run())


@pytest.mark.parametrize("rest_site", [False], indirect=True)
def test_surplus_solar_remains_exportable_with_full_batteries_and_no_curtailment(rest_site):
    payload = request_payload()
    payload["grid_export_sell_price_threshold"] = 1
    for index in (1, 2):
        payload[f"hybrid_inverter_config_{index}"].update(
            {
                "battery_charge_power_max": 1,
                "battery_discharge_power_max": 1,
            }
        )
    status, body, result = asyncio.run(rest_site(payload))
    assert status == 200, body
    assert result["optim_status"].eq("Optimal").all()
    # 3 kW solar minus 0.5 kW household demand must remain exportable.
    assert (result["P_grid_neg"] < -2400).all()


def test_threshold_blocks_battery_export_without_solar(rest_site):
    payload = request_payload()
    payload["grid_export_sell_price_threshold"] = 0.2
    payload["load_power_forecast"] = [0.0] * 48
    payload["pv_power_forecast"] = [0.0] * 48
    for index in (1, 2):
        payload[f"hybrid_inverter_config_{index}"].update(
            {
                "soc_final": 0.5,
                "pv_power_forecast": [0.0] * 48,
            }
        )
    status, body, result = asyncio.run(rest_site(payload))
    assert status == 200, body
    assert result["P_grid_neg"].iloc[:2].abs().max() <= 1e-5
    assert (result["P_grid_neg"].iloc[2:] < -100).any()
    assert result["P_batt_1"].sum() > 100
    assert result["P_batt_2"].sum() > 100


@pytest.mark.parametrize("rest_site", [False], indirect=True)
def test_threshold_preserves_consumption_storage_and_solar_export(rest_site):
    payload = request_payload()
    payload["grid_export_sell_price_threshold"] = 1
    for index in (1, 2):
        payload[f"hybrid_inverter_config_{index}"].update(
            {
                "soc_init": 0.2,
                "soc_final": 0.25,
                "pv_power_forecast": [500.0] * 48,
            }
        )
    status, body, result = asyncio.run(rest_site(payload))
    assert status == 200, body
    assert (result["P_batt"] < -100).any()
    assert result["SOC_opt_1"].iloc[-1] == pytest.approx(0.25, abs=1e-5)
    assert result["SOC_opt_2"].iloc[-1] == pytest.approx(0.25, abs=1e-5)
    assert (result["P_grid_neg"] < -100).any()


def test_day_ahead_request_also_enforces_threshold(rest_site):
    payload = battery_export_payload()
    payload.pop("prediction_horizon")
    payload["grid_export_sell_price_threshold"] = 1
    status, body, result = asyncio.run(rest_site(payload, action="dayahead-optim"))
    assert status == 200, body
    assert result["P_grid_neg"].abs().max() <= 1e-5


@pytest.mark.parametrize(
    "rest_site",
    [
        {"compute_curtailment": False},
        {"compute_curtailment": True},
        {"compute_curtailment": False, "inverter_efficiencies": [0.8, 0.9]},
    ],
    indirect=True,
)
def test_battery_can_supply_household_while_solar_exports(rest_site, request):
    payload = request_payload()
    payload["grid_export_sell_price_threshold"] = 1
    payload["prod_price_forecast"] = [0.05] * 48
    for index in (1, 2):
        payload[f"hybrid_inverter_config_{index}"]["soc_final"] = 0.5 if index == 1 else 0.85
    status, body, result = asyncio.run(rest_site(payload))
    assert status == 200, body
    efficiencies = request.node.callspec.params["rest_site"].get(
        "inverter_efficiencies", [1.0, 1.0]
    )
    battery_ac = (
        result["P_batt_1"].clip(lower=0) * efficiencies[0]
        + result["P_batt_2"].clip(lower=0) * efficiencies[1]
    )
    # All batteries share one 500 W allowance, not 500 W each. This is AC
    # demand; DC discharge may be higher to cover inverter conversion losses.
    assert battery_ac.to_numpy() == pytest.approx([500.0] * 6, abs=1e-5)
    expected_solar_ac = 1000 * efficiencies[0] + 2000 * efficiencies[1]
    assert (-result["P_grid_neg"]).to_numpy() == pytest.approx([expected_solar_ac] * 6, abs=1e-5)
    if "P_PV_curtailment" in result:
        assert result["P_PV_curtailment"].abs().max() <= 1e-5


def test_battery_discharge_still_supplies_household_without_solar(rest_site):
    payload = battery_export_payload()
    payload["grid_export_sell_price_threshold"] = 1
    payload["load_power_forecast"] = [500.0] * 48
    status, body, result = asyncio.run(rest_site(payload))
    assert status == 200, body
    assert result["P_batt"].to_numpy() == pytest.approx([500.0] * 6, abs=1e-5)
    assert result["P_grid_neg"].abs().max() <= 1e-5
    assert result["P_grid_pos"].abs().max() <= 1e-5


@pytest.mark.parametrize(
    "rest_site",
    [
        {
            "config": {
                "multi_inverter_mode": "single",
                "inverter_is_hybrid": False,
                "number_of_batteries": 2,
            }
        }
    ],
    indirect=True,
)
def test_ac_coupled_batteries_share_household_allowance(rest_site):
    payload = request_payload()
    payload.pop("hybrid_inverter_config_1")
    payload.pop("hybrid_inverter_config_2")
    payload["grid_export_sell_price_threshold"] = 1
    payload["soc_init"] = [0.9, 0.9]
    payload["soc_final"] = [0.5, 0.5]
    status, body, result = asyncio.run(rest_site(payload))
    assert status == 200, body
    assert result["P_batt"].to_numpy() == pytest.approx([500.0] * 6, abs=1e-5)
    assert (-result["P_grid_neg"]).to_numpy() == pytest.approx([1000.0] * 6, abs=1e-5)


def test_extra_inverter_battery_export_is_blocked_and_solar_export_is_retained(rest_site):
    async def run():
        payload = request_payload()
        payload["load_power_forecast"] = [0.0] * 48
        payload["prod_price_forecast"] = [0.3] * 4 + [0.0] * 44
        for index in (1, 2):
            payload[f"hybrid_inverter_config_{index}"].update(
                {
                    "soc_init": 0.5,
                    "soc_final": 0.5,
                    "pv_power_forecast": [0.0] * 4 + [3000.0] * 44,
                }
            )
        payload["hybrid_inverter_config_1"]["battery_discharge_power_max"] = 1
        status, body, unrestricted = await rest_site(payload)
        assert status == 200, body
        assert unrestricted["P_batt_2"].iloc[:4].max() > 100
        payload["grid_export_sell_price_threshold"] = 0.3
        status, body, restricted = await rest_site(payload)
        assert status == 200, body
        assert restricted["P_batt_2"].clip(lower=0).max() <= 1e-5
        assert restricted["P_grid_neg"].iloc[:4].abs().max() <= 1e-5
        assert (restricted["P_grid_neg"].iloc[4:] < -100).any()

    asyncio.run(run())


def test_cached_requests_update_household_allowance_and_horizon(rest_site, caplog):
    caplog.set_level(logging.DEBUG, logger=web_server.app.logger.name)

    async def run():
        payload = battery_export_payload()
        payload["grid_export_sell_price_threshold"] = 1
        for load, horizon in ((500.0, 6), (900.0, 6), (300.0, 8)):
            payload["load_power_forecast"] = [load] * 48
            payload["prediction_horizon"] = horizon
            status, body, result = await rest_site(payload)
            assert status == 200, body
            assert result["P_batt"].to_numpy() == pytest.approx([load] * horizon, abs=1e-5)
            assert result["P_grid_neg"].abs().max() <= 1e-5

    asyncio.run(run())
    assert caplog.text.count("OptimizationCache HIT") == 1


@pytest.mark.parametrize("rest_site", [False], indirect=True)
def test_existing_physical_export_limit_still_reports_genuine_infeasibility(rest_site):
    payload = request_payload()
    payload["grid_export_sell_price_threshold"] = 1
    payload["maximum_power_to_grid"] = 100
    for index in (1, 2):
        payload[f"hybrid_inverter_config_{index}"]["battery_charge_power_max"] = 1
    status, body, result = asyncio.run(rest_site(payload))
    assert status == 400, body
    assert "infeasible" in body.lower()
    assert result["optim_status"].eq("Infeasible").all()


@pytest.mark.parametrize(
    "rest_site,electrical",
    [
        (
            {
                "config": {
                    "number_of_deferrable_loads": 1,
                    "nominal_power_of_deferrable_loads": [500],
                    "is_electric_load": [True],
                }
            },
            True,
        ),
        (
            {
                "config": {
                    "number_of_deferrable_loads": 1,
                    "nominal_power_of_deferrable_loads": [500],
                    "is_electric_load": [False],
                }
            },
            False,
        ),
    ],
    indirect=["rest_site"],
)
def test_only_scheduled_electrical_loads_increase_battery_allowance(rest_site, electrical):
    payload = request_payload()
    payload["grid_export_sell_price_threshold"] = 1
    payload["load_power_forecast"] = [0.0] * 48
    payload["operating_timesteps_of_each_deferrable_load"] = [6]
    payload["hybrid_inverter_config_1"]["soc_final"] = 0.5
    status, body, result = asyncio.run(rest_site(payload))
    assert status == 200, body
    expected_discharge = 500.0 if electrical else 0.0
    assert result["P_batt"].to_numpy() == pytest.approx([expected_discharge] * 6, abs=1e-5)
    assert (-result["P_grid_neg"]).to_numpy() == pytest.approx([3000.0] * 6, abs=1e-5)
