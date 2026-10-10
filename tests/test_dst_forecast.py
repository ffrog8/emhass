"""DST regressions adapted from upstream #1164 and #1166 for indexed inverters."""

import logging
import tempfile
import unittest
from datetime import UTC
from pathlib import Path
from unittest.mock import patch

import numpy as np
import orjson
import pandas as pd
import pytz

from emhass import utils
from emhass.command_line import naive_mpc_optim, set_input_data_dict
from emhass.forecast import Forecast

ROOT = Path(__file__).resolve().parents[1]
EMHASS_CONF = {
    "data_path": ROOT / "data",
    "root_path": ROOT / "src/emhass",
    "defaults_path": ROOT / "src/emhass/data/config_defaults.json",
    "associations_path": ROOT / "src/emhass/data/associations.csv",
}
LOGGER = logging.getLogger(__name__)


async def default_params():
    config = await utils.build_config(EMHASS_CONF, LOGGER, EMHASS_CONF["defaults_path"])
    _, secrets = await utils.build_secrets(EMHASS_CONF, LOGGER, no_response=True)
    return await utils.build_params(EMHASS_CONF, secrets, config, LOGGER)


class TestDSTForecast(unittest.IsolatedAsyncioTestCase):
    async def assert_mpc_alignment(self, zone, start_text, horizon, last_text, calendar_end):
        params = await default_params()
        params["retrieve_hass_conf"].update({"time_zone": zone, "method_ts_round": "first"})
        params["optim_conf"].update(
            {
                "set_use_pv": True,
                "set_use_battery": True,
                "number_of_deferrable_loads": 0,
                "battery_mode_lock": "site",
                "set_nocharge_from_grid": False,
                "set_nodischarge_to_grid": False,
            }
        )
        params["plant_conf"].update(
            {
                "multi_inverter_mode": "multi",
                "multi_hybrid_inverter_pv_mode": "split_pv",
                "battery_soc_power_profiles": [{}, {}],
                "inverter_is_hybrid": True,
                "compute_curtailment": False,
                "inverter_ac_output_max": 5000,
                "inverter_ac_input_max": 5000,
                "inverter_efficiency_dc_ac": 1.0,
                "inverter_efficiency_ac_dc": 1.0,
            }
        )
        params["hybrid_inverter_config_1"] = {
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
            "battery_target_state_of_charge": 0.50,
            "inverter_ac_output_max": 5000,
            "inverter_ac_input_max": 5000,
            "inverter_efficiency_dc_ac": 1.0,
            "inverter_efficiency_ac_dc": 1.0,
        }
        params["hybrid_inverter_config_2"] = params["hybrid_inverter_config_1"].copy()
        runtime = {
            "optimization_time_step": 5,
            "prediction_horizon": horizon,
            "soc_init": 0.5,
            "soc_final": 0.5,
            "pv_power_forecast": [0.0] * horizon,
            "load_power_forecast": [1500.0 + 3 * i for i in range(horizon)],
            "load_cost_forecast": [0.20 + i / 10000 for i in range(horizon)],
            "prod_price_forecast": [0.05 + i / 20000 for i in range(horizon)],
            "hybrid_inverter_config_1": {
                "soc_init": 0.5,
                "soc_final": 0.5,
                "pv_power_forecast": [100.0 + i for i in range(horizon)],
            },
            "hybrid_inverter_config_2": {
                "soc_init": 0.5,
                "soc_final": 0.5,
                "pv_power_forecast": [200.0 + 2 * i for i in range(horizon)],
            },
        }
        start = pd.Timestamp(start_text, tz=zone)
        expected_index = pd.date_range(start=start, periods=horizon, freq="5min")
        self.assertEqual(expected_index[-1].isoformat(), last_text)
        with patch("emhass.utils._get_now", return_value=start.to_pydatetime().astimezone(UTC)):
            with patch.object(pd.Timestamp, "now", return_value=start):
                prepared = await set_input_data_dict(
                    EMHASS_CONF,
                    "profit",
                    orjson.dumps(params).decode(),
                    orjson.dumps(runtime).decode(),
                    "naive-mpc-optim",
                    LOGGER,
                    get_data_from_file=True,
                )
        self.assertIsInstance(prepared, dict)
        self.assertEqual(prepared["fcst"].end_forecast.isoformat(), calendar_end)
        pd.testing.assert_index_equal(prepared["df_input_data_dayahead"].index, expected_index)
        np.testing.assert_array_equal(
            prepared["df_input_data_dayahead"]["p_load_forecast"], runtime["load_power_forecast"]
        )
        result = await naive_mpc_optim(prepared, LOGGER, debug=True)
        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(len(result), horizon)
        pd.testing.assert_index_equal(result.index, expected_index, exact=False)
        for column, values in (
            ("P_Load", runtime["load_power_forecast"]),
            ("P_PV_1", runtime["hybrid_inverter_config_1"]["pv_power_forecast"]),
            ("P_PV_2", runtime["hybrid_inverter_config_2"]["pv_power_forecast"]),
            ("unit_load_cost", runtime["load_cost_forecast"]),
            ("unit_prod_price", runtime["prod_price_forecast"]),
        ):
            np.testing.assert_allclose(result[column], values, rtol=0, atol=1e-6)
        np.testing.assert_allclose(
            result["P_PV"], [300.0 + 3 * i for i in range(horizon)], rtol=0, atol=1e-6
        )
        self.assertTrue(result.index.is_unique)
        self.assertEqual(result.isna().sum().sum(), 0)

    async def test_sydney_short_day_preserves_requested_mpc_rows_and_inverter_values(self):
        await self.assert_mpc_alignment(
            "Australia/Sydney", "2026-10-03 23:05", 287, "2026-10-04T23:55:00+11:00",
            "2026-10-05T23:05:00+11:00",
        )

    async def test_adelaide_spring_preserves_requested_mpc_rows_and_inverter_values(self):
        await self.assert_mpc_alignment(
            "Australia/Adelaide", "2026-10-03 23:05", 287, "2026-10-04T23:55:00+10:30",
            "2026-10-05T23:05:00+10:30",
        )

    async def test_adelaide_fall_preserves_requested_mpc_rows_and_inverter_values(self):
        await self.assert_mpc_alignment(
            "Australia/Adelaide", "2027-04-03 20:15", 295, "2027-04-04T19:45:00+09:30",
            "2027-04-04T20:15:00+09:30",
        )

    async def test_ordinary_day_preserves_mpc_rows_and_inverter_values(self):
        await self.assert_mpc_alignment(
            "Australia/Adelaide", "2026-10-10 23:05", 287, "2026-10-11T22:55:00+10:30",
            "2026-10-11T23:05:00+10:30",
        )

    async def test_sydney_gap_endpoint_csv_extension_and_cache_trim(self):
        """Upstream #1164: retain minutes in a gap and extend from the frozen start."""
        params = await default_params()
        params_json = orjson.dumps(params).decode()
        retrieve_conf, optim_conf, plant_conf = utils.get_yaml_parse(params_json, LOGGER)
        zone = pytz.timezone("Australia/Sydney")
        retrieve_conf.update(
            {
                "time_zone": zone,
                "optimization_time_step": pd.Timedelta(minutes=5),
                "method_ts_round": "first",
            }
        )
        optim_conf["delta_forecast_daily"] = pd.Timedelta(days=1)
        start = pd.Timestamp("2026-10-03 02:05", tz=zone)
        with patch.object(pd.Timestamp, "now", return_value=start):
            forecast = Forecast(
                retrieve_conf, optim_conf, plant_conf, params_json, EMHASS_CONF, LOGGER,
                get_data_from_file=True,
            )
        self.assertEqual(forecast.start_forecast, start)
        self.assertEqual(forecast.end_forecast.isoformat(), "2026-10-04T03:05:00+11:00")
        self.assertEqual(len(forecast.forecast_dates), 288)
        self.assertEqual(forecast.forecast_dates[-1].isoformat(), "2026-10-04T03:00:00+11:00")
        with patch.object(pd.Timestamp, "now", return_value=start + pd.Timedelta(hours=2)):
            csv_dates = forecast.get_forecast_days_csv(timedelta_days=0)
            extended_dates = forecast.get_forecast_days_csv(timedelta_days=1)
        pd.testing.assert_index_equal(csv_dates, forecast.forecast_dates)
        self.assertEqual(extended_dates[0], start)
        self.assertEqual(len(extended_dates), 564)
        self.assertEqual(extended_dates[-1].isoformat(), "2026-10-05T02:00:00+11:00")
        cached_weather = pd.DataFrame({"yhat": np.arange(564)}, index=extended_dates)
        with tempfile.TemporaryDirectory() as directory:
            trimmed = await forecast.set_cached_forecast_data(
                Path(directory) / "weather.pkl", cached_weather
            )
        pd.testing.assert_index_equal(trimmed.index, csv_dates)
        np.testing.assert_array_equal(trimmed["yhat"], np.arange(288))

    async def test_sydney_repeated_endpoint_and_doubled_weather_cache_window(self):
        params = await default_params()
        params["passed_data"]["weather_forecast_cache"] = True
        params_json = orjson.dumps(params).decode()
        retrieve_conf, optim_conf, plant_conf = utils.get_yaml_parse(params_json, LOGGER)
        zone = pytz.timezone("Australia/Sydney")
        retrieve_conf.update(
            {
                "time_zone": zone,
                "optimization_time_step": pd.Timedelta(minutes=5),
                "method_ts_round": "first",
            }
        )
        optim_conf["delta_forecast_daily"] = pd.Timedelta(days=1)
        start = pd.Timestamp("2027-04-03 02:05", tz=zone)
        with patch.object(pd.Timestamp, "now", return_value=start):
            uncached_params = orjson.loads(params_json)
            uncached_params["passed_data"]["weather_forecast_cache"] = False
            uncached = Forecast(
                retrieve_conf, optim_conf, plant_conf, uncached_params, EMHASS_CONF, LOGGER,
                get_data_from_file=True,
            )
            forecast = Forecast(
                retrieve_conf, optim_conf, plant_conf, params_json, EMHASS_CONF, LOGGER,
                get_data_from_file=True,
            )
        self.assertEqual(uncached.end_forecast.isoformat(), "2027-04-04T02:05:00+10:00")
        self.assertEqual(uncached.end_forecast.tz_convert("UTC"), pd.Timestamp("2027-04-03 16:05Z"))
        self.assertEqual(len(uncached.forecast_dates), 300)
        self.assertEqual(forecast.end_forecast.isoformat(), "2027-04-05T02:05:00+10:00")
        self.assertEqual(len(forecast.forecast_dates), 588)
        csv_dates = forecast.get_forecast_days_csv(timedelta_days=0)
        self.assertEqual(len(csv_dates), 300)
        self.assertEqual(csv_dates[-1].isoformat(), "2027-04-04T02:00:00+10:00")
        self.assertEqual(csv_dates[-1].tz_convert("UTC"), pd.Timestamp("2027-04-03 16:00Z"))
        weather = pd.DataFrame({"yhat": np.arange(588)}, index=forecast.forecast_dates)
        with tempfile.TemporaryDirectory() as directory:
            trimmed = await forecast.set_cached_forecast_data(Path(directory) / "weather.pkl", weather)
        pd.testing.assert_index_equal(trimmed.index, csv_dates)
        np.testing.assert_array_equal(trimmed["yhat"], np.arange(300))

    def assert_runtime_dates(self, zone_name, start_text, count, last_text, extra_days=0):
        zone = pytz.timezone(zone_name)
        start = pd.Timestamp(start_text, tz=zone)
        with patch("emhass.utils._get_now", return_value=start.to_pydatetime().astimezone(UTC)):
            dates = utils.get_forecast_dates(5, 1, zone, timedelta_days=extra_days)
        self.assertEqual(len(dates), count)
        self.assertEqual(dates[0], start.isoformat())
        self.assertEqual(dates[-1], last_text)
        self.assertEqual(len(set(dates)), count)

    def test_runtime_sydney_gap_endpoint(self):
        self.assert_runtime_dates(
            "Australia/Sydney", "2026-10-03 02:05", 288, "2026-10-04T03:00:00+11:00"
        )

    def test_runtime_extension_resolves_from_original_start(self):
        self.assert_runtime_dates(
            "Australia/Sydney", "2026-10-03 02:05", 564, "2026-10-05T02:00:00+11:00", 1
        )

    def test_runtime_sydney_repeated_endpoint_uses_later_instant(self):
        self.assert_runtime_dates(
            "Australia/Sydney", "2027-04-03 02:05", 300, "2027-04-04T02:00:00+10:00"
        )

    def test_runtime_negative_dst_repeated_endpoint_uses_later_instant(self):
        for case in (
            ("Africa/Casablanca", "2026-02-14 02:05", 300, "2026-02-15T02:00:00+00:00"),
            ("Europe/Dublin", "2026-10-24 01:30", 300, "2026-10-25T01:25:00+00:00"),
        ):
            with self.subTest(zone=case[0]):
                self.assert_runtime_dates(*case)

    def test_runtime_negative_dst_gap_advances_by_actual_gap(self):
        for case in (
            ("Africa/Casablanca", "2026-03-21 02:30", 288, "2026-03-22T03:25:00+01:00"),
            ("Europe/Dublin", "2026-03-28 01:30", 288, "2026-03-29T02:25:00+01:00"),
        ):
            with self.subTest(zone=case[0]):
                self.assert_runtime_dates(*case)

    def test_runtime_lord_howe_half_hour_transitions(self):
        for case in (
            ("Australia/Lord_Howe", "2026-10-03 02:15", 288, "2026-10-04T02:40:00+11:00"),
            ("Australia/Lord_Howe", "2026-04-04 01:45", 294, "2026-04-05T01:40:00+10:30"),
        ):
            with self.subTest(start=case[1]):
                self.assert_runtime_dates(*case)

    def test_calendar_zero_days_preserves_fall_back_occurrence(self):
        """Upstream #1164 identity guard retains the selected repeated-hour instant."""
        zone = pytz.timezone("Australia/Sydney")
        first = pd.Timestamp("2027-04-04 02:30").tz_localize(zone, ambiguous=True)
        self.assertEqual(utils.add_local_calendar_days(first, 0, zone), first)

    def test_calendar_optional_timezone_keeps_naive_behavior(self):
        start = pd.Timestamp("2026-10-03 02:05")
        self.assertEqual(utils.add_local_calendar_days(start, 1), pd.Timestamp("2026-10-04 02:05"))
