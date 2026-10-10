"""Forecast safeguards adapted from upstream #1151 at request/action boundaries."""

import copy
import logging
import pickle
import shutil
import tempfile
import unittest
from datetime import UTC
from pathlib import Path
from unittest.mock import AsyncMock, patch

import numpy as np
import orjson
import pandas as pd

from emhass import command_line, last_run, plan_store, utils, web_server
from emhass.forecast import Forecast
from emhass.machine_learning_forecaster import MLForecaster

ROOT = Path(__file__).resolve().parents[1]
EMHASS_CONF = {
    "data_path": ROOT / "data",
    "root_path": ROOT / "src/emhass",
    "defaults_path": ROOT / "src/emhass/data/config_defaults.json",
    "associations_path": ROOT / "src/emhass/data/associations.csv",
}
LOGGER = logging.getLogger(__name__)
FORECAST_KEYS = (
    "pv_power_forecast",
    "load_power_forecast",
    "load_cost_forecast",
    "prod_price_forecast",
    "outdoor_temperature_forecast",
)
NOW = pd.Timestamp("2026-06-26T07:00:00", tz=UTC)
LONG = 96
INVALID_VALUES = (float("nan"), float("inf"), float("-inf"), True, np.bool_(False), "2.5", None)


class _ControlledEstimator:
    """Upstream test fixture: fixed fitted-estimator output, real ML prediction path."""

    def __init__(self, values, index):
        self.predictions = pd.Series(values, index=index, name="pred")

    def predict(self, steps, exog=None, last_window=None):
        return self.predictions.iloc[:steps].copy()


class TestForecastPreparation(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        scratch = ROOT / ".tmp"
        scratch.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="forecast-validity-", dir=scratch)
        self.addCleanup(temporary.cleanup)
        self.conf = dict(EMHASS_CONF, data_path=Path(temporary.name))
        shutil.copyfile(ROOT / "data/test_df_final.pkl", self.conf["data_path"] / "test_df_final.pkl")
        config = await utils.build_config(EMHASS_CONF, LOGGER, EMHASS_CONF["defaults_path"])
        _, secrets = await utils.build_secrets(EMHASS_CONF, LOGGER, no_response=True)
        self.params = await utils.build_params(EMHASS_CONF, secrets, config, LOGGER)
        self.params["optim_conf"].update(
            {
                "set_use_pv": True,
                "set_use_adjusted_pv": False,
                "set_use_battery": False,
                "set_mix_forecast": False,
                "number_of_deferrable_loads": 0,
            }
        )
        self.params_json = orjson.dumps(self.params).decode()
        command_line.OptimizationCache.clear()
        self.addCleanup(command_line.OptimizationCache.clear)

    @staticmethod
    def valid_runtime():
        return {
            "pv_power_forecast": [1000.0] * LONG,
            "load_power_forecast": [500.0] * LONG,
            "load_cost_forecast": [0.2] * LONG,
            "prod_price_forecast": [0.1] * LONG,
            "outdoor_temperature_forecast": [10.0] * LONG,
        }

    async def prepare(self, runtime, action="dayahead-optim"):
        with (
            patch("emhass.utils._get_now", return_value=NOW.to_pydatetime()),
            patch.object(pd.Timestamp, "now", return_value=NOW),
        ):
            return await command_line.set_input_data_dict(
                self.conf,
                "profit",
                self.params_json,
                copy.deepcopy(runtime),
                action,
                LOGGER,
                get_data_from_file=True,
            )

    async def run_action(self, runtime, action="dayahead-optim"):
        prepared = await self.prepare(runtime, action)
        if not prepared:
            return prepared
        action_fn = (
            command_line.dayahead_forecast_optim
            if action == "dayahead-optim"
            else command_line.naive_mpc_optim
        )
        return await action_fn(prepared, LOGGER, debug=True)

    async def test_invalid_forecasts_fail_before_solving_for_both_actions(self):
        for action in ("dayahead-optim", "naive-mpc-optim"):
            for key in FORECAST_KEYS:
                for bad in INVALID_VALUES:
                    with self.subTest(action=action, key=key, value=bad):
                        runtime = self.valid_runtime()
                        runtime[key][3] = bad
                        runtime[key][9] = bad
                        with (
                            patch.object(command_line.Optimization, "perform_optimization") as solve,
                            self.assertLogs(LOGGER, level="ERROR") as captured,
                        ):
                            result = await self.run_action(runtime, action)
                        self.assertIs(result, False)
                        solve.assert_not_called()
                        self.assertTrue(any(key in line for line in captured.output))
                        diagnostics = [
                            line for line in captured.output if "finite real numbers" in line
                        ]
                        self.assertEqual(len(diagnostics), 1, captured.output)
                        self.assertIn("position 3", diagnostics[0])

    async def test_invalid_mapping_values_are_rejected_before_resampling(self):
        for action in ("dayahead-optim", "naive-mpc-optim"):
            for key in FORECAST_KEYS:
                for bad in INVALID_VALUES:
                    with self.subTest(action=action, key=key, value=bad):
                        runtime = self.valid_runtime()
                        # Invalid sub-step values must not disappear into the
                        # valid point's mean or the later forward/backward fill.
                        runtime[key] = {
                            "2026-06-26T07:00:00+00:00": 20.0,
                            "2026-06-26T07:15:00+00:00": bad,
                            "2026-06-26T08:00:00+00:00": 40.0,
                        }
                        with (
                            patch.object(command_line.Optimization, "perform_optimization") as solve,
                            self.assertLogs(LOGGER, level="ERROR") as captured,
                        ):
                            result = await self.run_action(runtime, action)
                        self.assertIs(result, False)
                        solve.assert_not_called()
                        self.assertTrue(
                            any(key in line and "07:15" in line for line in captured.output),
                            captured.output,
                        )

    async def test_finite_negative_load_is_clipped_with_one_summary_warning(self):
        runtime = self.valid_runtime()
        runtime["load_power_forecast"][3] = -0.881
        runtime["load_power_forecast"][7] = -37.386
        runtime["load_power_forecast"][8] = -5.0
        for action in ("dayahead-optim", "naive-mpc-optim"):
            with self.subTest(action=action):
                with self.assertLogs(LOGGER, level="WARNING") as captured:
                    prepared = await self.prepare(runtime, action)
                load = prepared["df_input_data_dayahead"]["p_load_forecast"]
                self.assertEqual(load.iloc[[3, 7, 8]].tolist(), [0.0, 0.0, 0.0])
                self.assertEqual(load.drop(load.index[[3, 7, 8]]).tolist(), [500.0] * (len(load) - 3))
                warnings = [line for line in captured.output if "clipped to 0 W" in line]
                self.assertEqual(len(warnings), 1, captured.output)
                self.assertIn("3 negative", warnings[0])
                self.assertIn("-37.386", warnings[0])
                self.assertIn(str(load.index[3]), warnings[0])

    async def test_rejected_action_returns_400_and_preserves_last_valid_outputs(self):
        # Seed public plan/run state and saved outputs as they would exist after
        # a valid optimization, then submit invalid JSON values through /action.
        with patch.object(plan_store, "_cache", None), patch.object(last_run, "_cache", None):
            plan_store.record(
                self.conf["data_path"], [{"timestamp": NOW.isoformat(), "P_Load": 500.0}],
                NOW.isoformat(), "1.0",
            )
            last_run.record(self.conf["data_path"], "dayahead-optim", {}, "Optimal", False, 1.0, "1.0")
            before_plan = plan_store.read(self.conf["data_path"])
            before_run = last_run.read(self.conf["data_path"])
            params_path = self.conf["data_path"] / web_server.params_file
            params_path.write_bytes(pickle.dumps((None, self.params)))
            saved = {
                "opt_res_latest.csv": b"timestamp,P_Load\n2026-06-26T07:00:00Z,500\n",
                web_server.injection_dict_file: pickle.dumps({"title": "last valid plan"}),
            }
            for filename, content in saved.items():
                (self.conf["data_path"] / filename).write_bytes(content)
            real_prepare = command_line.set_input_data_dict

            async def from_file(*args, **kwargs):
                return await real_prepare(*args, get_data_from_file=True, **kwargs)

            with (
                patch.object(web_server, "emhass_conf", self.conf),
                patch.object(web_server, "set_input_data_dict", side_effect=from_file),
                patch.object(command_line.Optimization, "perform_optimization") as solve,
                patch.object(command_line, "publish_data", AsyncMock()) as publish,
                patch.object(web_server, "_save_injection_dict", AsyncMock()) as save_injection,
                patch("emhass.utils._get_now", return_value=NOW.to_pydatetime()),
                patch.object(pd.Timestamp, "now", return_value=NOW),
            ):
                client = web_server.app.test_client()
                for action in ("dayahead-optim", "naive-mpc-optim"):
                    for key in FORECAST_KEYS:
                        for bad in (True, "not a number"):
                            with self.subTest(action=action, key=key, value=bad):
                                runtime = self.valid_runtime()
                                runtime[key][3] = bad
                                with self.assertLogs(web_server.app.logger, level="ERROR") as captured:
                                    response = await client.post(f"/action/{action}", json=runtime)
                                self.assertEqual(response.status_code, 400)
                                self.assertTrue(any(key in line for line in captured.output))
                                solve.assert_not_called()
                                publish.assert_not_called()
                                save_injection.assert_not_called()
                                self.assertEqual(plan_store.read(self.conf["data_path"]), before_plan)
                                self.assertEqual(last_run.read(self.conf["data_path"]), before_run)
                                for filename, content in saved.items():
                                    self.assertEqual((self.conf["data_path"] / filename).read_bytes(), content)

    async def test_signed_prices_temperatures_and_positive_load_retain_solver_values(self):
        runtime = self.valid_runtime()
        runtime["load_cost_forecast"] = [-0.05] * LONG
        runtime["prod_price_forecast"] = [-0.12] * LONG
        runtime["outdoor_temperature_forecast"] = [-7.5] * LONG
        for action in ("dayahead-optim", "naive-mpc-optim"):
            with self.subTest(action=action):
                result = await self.run_action(runtime, action)
                self.assertIsInstance(result, pd.DataFrame)
                self.assertEqual(result["optim_status"].unique().tolist(), ["Optimal"])
                self.assertEqual(result["P_Load"].tolist(), [500.0] * len(result))
                self.assertEqual(result["unit_load_cost"].tolist(), [-0.05] * len(result))
                self.assertEqual(result["unit_prod_price"].tolist(), [-0.12] * len(result))
                prepared = await self.prepare(runtime, action)
                self.assertEqual(prepared["params"]["passed_data"]["outdoor_temperature_forecast"], [-7.5] * LONG)

    async def test_supported_stringified_lists_keep_values_and_reject_invalid_members(self):
        for key in FORECAST_KEYS:
            with self.subTest(key=key):
                runtime = self.valid_runtime()
                runtime[key] = repr(runtime[key])
                prepared = await self.prepare(runtime)
                self.assertEqual(prepared["params"]["passed_data"][key], self.valid_runtime()[key])
                runtime[key] = repr([10.0, 10.0, "2.5"] + [10.0] * (LONG - 3))
                with self.assertLogs(LOGGER, level="ERROR"):
                    self.assertIs(await self.run_action(runtime), False)

    async def test_valid_mappings_keep_local_mean_and_utc_hold_fill(self):
        runtime = self.valid_runtime()
        mapping = {
            "2026-06-26T10:00:00+02:00": -4.0,
            "2026-06-26T10:15:00+02:00": -2.0,
            "2026-06-26T09:30:00+00:00": 7.0,
            "2026-06-26T11:00:00+00:00": 1.5,
        }
        for key in ("load_cost_forecast", "prod_price_forecast", "outdoor_temperature_forecast"):
            runtime[key] = mapping
        prepared = await self.prepare(runtime)
        expected = [-3.0, -3.0, -3.0, -3.0, -3.0, 7.0, 7.0, 7.0, 1.5, 1.5]
        for key in ("load_cost_forecast", "prod_price_forecast", "outdoor_temperature_forecast"):
            values = prepared["params"]["passed_data"][key]
            self.assertEqual(values[:10], expected)
            self.assertEqual(values[10:], [1.5] * (len(values) - 10))

    async def test_mapping_point_before_forecast_start_still_anchors_forward_fill(self):
        runtime = self.valid_runtime()
        runtime["load_cost_forecast"] = {
            "2026-06-26T06:30:00+00:00": -0.1,
            "2026-06-26T08:00:00+00:00": 0.2,
        }
        prepared = await self.prepare(runtime)
        values = prepared["params"]["passed_data"]["load_cost_forecast"]
        self.assertEqual(values[:4], [-0.1, -0.1, 0.2, 0.2])

    async def test_long_and_short_lists_preserve_existing_coverage_policy(self):
        runtime = self.valid_runtime()
        prepared = await self.prepare(runtime)
        horizon = len(prepared["df_input_data_dayahead"])
        self.assertEqual(len(prepared["params"]["passed_data"]["load_power_forecast"]), LONG)
        self.params["optim_conf"]["load_forecast_method"] = "list"
        self.params_json = orjson.dumps(self.params).decode()
        runtime["load_power_forecast"] = [500.0] * (horizon - 1)
        with self.assertLogs(LOGGER, level="ERROR") as captured:
            prepared = await self.prepare(runtime)
        # Existing short-list policy logs the mismatch and leaves passed data
        # unavailable. It does not select a new padding policy in this ticket.
        self.assertIs(prepared, False)
        self.assertTrue(any("the length is not correct" in line for line in captured.output))

    async def test_existing_negative_pv_correction_is_preserved(self):
        runtime = self.valid_runtime()
        runtime["pv_power_forecast"][0] = -3.0
        prepared = await self.prepare(runtime)
        self.assertEqual(prepared["p_pv_forecast"].iloc[:2].tolist(), [0.0, 1000.0])

    async def source_runtime(self, method):
        reference = await self.prepare(self.valid_runtime())
        self.forecast_index = reference["df_input_data_dayahead"].index
        self.params["optim_conf"]["load_forecast_method"] = method
        self.params_json = orjson.dumps(self.params).decode()
        runtime = self.valid_runtime()
        runtime.pop("load_power_forecast")
        return runtime

    def write_load_csv(self, values):
        rows = [f"{stamp.isoformat()},{value}" for stamp, value in zip(self.forecast_index, values, strict=True)]
        (self.conf["data_path"] / "data_load_forecast.csv").write_text("\n".join(rows) + "\n")

    async def test_csv_load_is_validated_and_negative_load_clipped_before_optimization(self):
        runtime = await self.source_runtime("csv")
        values = [120.5] * len(self.forecast_index)
        self.write_load_csv(values)
        prepared = await self.prepare(runtime)
        self.assertEqual(prepared["p_load_forecast"].tolist(), values)
        values[2] = -8.25
        self.write_load_csv(values)
        with self.assertLogs(LOGGER, level="WARNING") as captured:
            prepared = await self.prepare(runtime)
        self.assertEqual(prepared["p_load_forecast"].iloc[2], 0.0)
        self.assertTrue(any("clipped to 0 W" in line for line in captured.output))
        for bad in ("nan", "inf", "-inf", "abc", "True"):
            with self.subTest(value=bad):
                values = [120.5] * len(self.forecast_index)
                values[6] = bad
                self.write_load_csv(values)
                with (
                    patch.object(command_line.Optimization, "perform_optimization") as solve,
                    self.assertLogs(LOGGER, level="ERROR") as captured,
                ):
                    self.assertIs(await self.run_action(runtime), False)
                solve.assert_not_called()
                self.assertTrue(any("P_Load" in line for line in captured.output))

    def write_ml_model(self, values):
        model = MLForecaster.__new__(MLForecaster)
        model.forecaster = _ControlledEstimator(values, self.forecast_index)
        model.num_lags = len(values)
        model.var_model = "sensor.power_load_no_var_loads"
        model.data_test = pd.DataFrame({model.var_model: values, "hour": 0})
        model.is_tuned = False
        model.weather_features = []
        model.logger = LOGGER
        (self.conf["data_path"] / "controlled_mlf.pkl").write_bytes(pickle.dumps(model))
        return model

    async def test_native_ml_load_boundary_preserves_raw_predictions(self):
        runtime = await self.source_runtime("mlforecaster")
        runtime["model_type"] = "controlled"
        values = [200.0] * len(self.forecast_index)
        self.write_ml_model(values)
        prepared = await self.prepare(runtime)
        self.assertEqual(prepared["p_load_forecast"].tolist(), values)
        values[1] = -12.0
        model = self.write_ml_model(values)
        with self.assertLogs(LOGGER, level="WARNING") as captured:
            prepared = await self.prepare(runtime)
        self.assertEqual(prepared["p_load_forecast"].iloc[1], 0.0)
        self.assertTrue(any("clipped to 0 W" in line for line in captured.output))
        prepared["params"]["passed_data"]["model_predict_publish"] = False
        raw = await command_line.forecast_model_predict(
            prepared, LOGGER, use_last_window=False, debug=True, mlf=model
        )
        self.assertEqual(raw.tolist(), values)
        for bad in INVALID_VALUES:
            with self.subTest(value=bad):
                values = [200.0] * len(self.forecast_index)
                values[10] = bad
                self.write_ml_model(values)
                with (
                    patch.object(command_line.Optimization, "perform_optimization") as solve,
                    self.assertLogs(LOGGER, level="ERROR") as captured,
                ):
                    self.assertIs(await self.run_action(runtime), False)
                solve.assert_not_called()
                self.assertTrue(any("P_Load" in line for line in captured.output))

    async def mixed_csv_runtime(self):
        runtime = await self.source_runtime("csv")
        runtime.update({"alpha": 0.5, "beta": 0.5})
        history_path = self.conf["data_path"] / "test_df_final.pkl"
        history, days, variables, ha_config = pickle.loads(history_path.read_bytes())
        history[variables[0]] = -1000.0
        history_path.write_bytes(pickle.dumps((history, days, variables, ha_config)))
        self.params["retrieve_hass_conf"].update(
            {
                "sensor_power_load_no_var_loads": variables[0],
                "load_negative": False,
                "set_zero_min": False,
            }
        )
        self.params_json = orjson.dumps(self.params).decode()
        return runtime

    async def test_real_negative_load_blend_is_clipped_after_mixing(self):
        runtime = await self.mixed_csv_runtime()
        self.write_load_csv([100.0] * len(self.forecast_index))
        with self.assertLogs(LOGGER, level="WARNING") as captured:
            prepared = await self.prepare(runtime, "naive-mpc-optim")
        load = prepared["p_load_forecast"]
        self.assertEqual(load.iloc[0], 0.0)
        self.assertEqual(load.iloc[1:].tolist(), [100.0] * (len(load) - 1))
        warnings = [line for line in captured.output if "clipped to 0 W" in line]
        self.assertEqual(len(warnings), 1, captured.output)
        self.assertIn("-450", warnings[0])

    async def test_nonfinite_load_fails_before_mixing_can_round_it(self):
        runtime = await self.mixed_csv_runtime()
        for bad in (float("inf"), float("-inf")):
            with self.subTest(value=bad):
                values = [100.0] * len(self.forecast_index)
                values[0] = bad
                self.write_load_csv(values)
                with self.assertLogs(LOGGER, level="ERROR") as captured:
                    self.assertIs(await self.prepare(runtime, "naive-mpc-optim"), False)
                self.assertTrue(any("P_Load" in line for line in captured.output))

    async def test_injected_nonfinite_blend_result_fails_before_solving(self):
        """Upstream fault injection verifies the boundary after blending."""
        runtime = await self.mixed_csv_runtime()
        self.write_load_csv([100.0] * len(self.forecast_index))
        original_mix = Forecast.get_mix_forecast
        injected = []

        def mix_with_invalid_load(df_now, forecast, alpha, beta, column, *args, **kwargs):
            mixed = original_mix(df_now, forecast, alpha, beta, column, *args, **kwargs)
            if column == self.params["retrieve_hass_conf"]["sensor_power_load_no_var_loads"] + "_positive":
                mixed.iloc[0] = float("nan")
                injected.append(True)
            return mixed

        with (
            patch.object(Forecast, "get_mix_forecast", side_effect=mix_with_invalid_load),
            patch.object(command_line.Optimization, "perform_optimization") as solve,
            self.assertLogs(LOGGER, level="ERROR") as captured,
        ):
            self.assertIs(await self.run_action(runtime, "naive-mpc-optim"), False)
        self.assertEqual(injected, [True])
        solve.assert_not_called()
        self.assertTrue(any("P_Load" in line for line in captured.output))
