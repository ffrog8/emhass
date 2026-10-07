"""Regression for a cached successful solution surviving a new solver exception."""

import json
import logging
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import cvxpy as cp
import numpy as np
import orjson
import pandas as pd

from emhass import command_line, last_run, plan_store, utils
from emhass.optimization import Optimization


class TestSolverExceptionResults(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        root = Path(utils.__file__).parent
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        solver_env = mock.patch.dict(os.environ, {"LP_SOLVER": "HIGHS"})
        solver_env.start()
        self.addCleanup(solver_env.stop)
        conf = {
            "root_path": root,
            "data_path": Path(temp.name),
            "defaults_path": root / "data/config_defaults.json",
            "associations_path": root / "data/associations.csv",
        }
        self.conf = conf
        config = json.loads(conf["defaults_path"].read_text())
        logger = logging.getLogger("solver_exception_test")
        logger.handlers = [logging.NullHandler()]
        secrets = {
            "hass_url": "http://127.0.0.1/",
            "long_lived_token": "",
            "time_zone": "UTC",
            "Latitude": 0,
            "Longitude": 0,
            "Altitude": 0,
        }
        params = await utils.build_params(conf, secrets, config, logger)
        retrieve, optim, plant = utils.get_yaml_parse(orjson.dumps(params).decode(), logger)
        optim.update(set_use_battery=False, set_use_pv=False, number_of_deferrable_loads=0)
        plant.update(maximum_power_from_grid=5000, maximum_power_to_grid=5000)
        self.opt = Optimization(
            retrieve,
            optim,
            plant,
            "unit_load_cost",
            "unit_prod_price",
            "profit",
            conf,
            logger,
            num_timesteps=2,
        )
        self.df = pd.DataFrame(index=pd.date_range("2026-10-03T01:00:00Z", periods=2, freq="30min"))

    def solve(self, load=100):
        return self.opt.perform_optimization(
            self.df, np.zeros(2), np.full(2, load), np.full(2, 0.25), np.zeros(2)
        )

    def test_primary_exception_uses_current_fallback_not_old_solution(self):
        first = self.solve()
        np.testing.assert_allclose(first["P_grid"], 100)
        primary = self.opt.prob
        real_solve = cp.Problem.solve
        attempted = []

        def fault(problem, *args, **kwargs):
            attempted.append(problem)
            if problem is primary:
                raise cp.error.SolverError("injected primary failure")
            return real_solve(problem, *args, **kwargs)

        with mock.patch.object(cp.Problem, "solve", new=fault):
            result = self.solve(200)
        self.assertEqual(len(attempted), 2, "A new fallback must run after a primary exception")
        self.assertEqual(result["optim_status"].unique().tolist(), ["Optimal (Relaxed)"])
        np.testing.assert_allclose(result["P_grid"], 200)
        self.assertIs(self.opt.prob, primary)
        np.testing.assert_allclose(self.solve(300)["P_grid"], 300)

    def test_both_solver_exceptions_do_not_return_old_success(self):
        self.solve()
        with mock.patch.object(
            cp.Problem, "solve", side_effect=cp.error.SolverError("injected failure")
        ) as solve:
            result = self.solve(200)
        self.assertEqual(solve.call_count, 2)
        self.assertEqual(list(result.columns), ["optim_status"])
        self.assertEqual(result["optim_status"].unique().tolist(), ["Failure"])
        self.assertEqual(self.opt.optim_status, "Failure")
        np.testing.assert_allclose(self.solve(300)["P_grid"], 300)

    def test_fallback_exception_after_setting_values_is_not_success(self):
        self.solve()
        primary = self.opt.prob
        real_solve = cp.Problem.solve

        def fault(problem, *args, **kwargs):
            if problem is not primary:
                real_solve(problem, *args, **kwargs)
            raise cp.error.SolverError("injected exception after solver work")

        with mock.patch.object(cp.Problem, "solve", new=fault):
            result = self.solve(200)
        self.assertEqual(list(result.columns), ["optim_status"])
        self.assertEqual(result["optim_status"].unique().tolist(), ["Failure"])

    def test_first_solve_exception_and_failed_fallback(self):
        with mock.patch.object(
            cp.Problem, "solve", side_effect=cp.error.SolverError("injected failure")
        ):
            result = self.solve(200)
        self.assertEqual(list(result.columns), ["optim_status"])
        self.assertEqual(result["optim_status"].unique().tolist(), ["Failure"])

    def test_failed_fallback_reports_its_current_infeasible_status(self):
        self.solve()
        primary = self.opt.prob

        def fault(problem, *args, **kwargs):
            if problem is primary:
                raise cp.error.SolverError("injected primary failure")
            problem._status = cp.INFEASIBLE
            problem._value = None

        with mock.patch.object(cp.Problem, "solve", new=fault):
            result = self.solve(200)
        self.assertEqual(list(result.columns), ["optim_status"])
        self.assertEqual(result["optim_status"].unique().tolist(), ["Infeasible"])

    def test_exception_records_failed_run_without_replacing_last_valid_plan(self):
        logger = logging.getLogger("solver_exception_test")
        context = {"emhass_conf": self.conf, "stage_times": {}}
        first = self.solve()
        command_line._record_optim_snapshot(
            context, "naive-mpc-optim", first, time.monotonic(), logger
        )
        previous_plan = plan_store.read(self.conf["data_path"])
        self.assertIsNotNone(previous_plan)
        self.assertEqual(last_run.read(self.conf["data_path"])["status"], "ok")
        with mock.patch.object(cp.Problem, "solve", side_effect=cp.error.SolverError("injected")):
            result = self.solve(200)
        command_line._record_optim_snapshot(
            context, "naive-mpc-optim", result, time.monotonic(), logger
        )
        self.assertEqual(last_run.read(self.conf["data_path"])["status"], "error")
        self.assertEqual(plan_store.read(self.conf["data_path"]), previous_plan)

    async def test_exception_result_cannot_enter_ha_publication(self):
        self.solve()
        with mock.patch.object(cp.Problem, "solve", side_effect=cp.error.SolverError("injected")):
            result = self.solve(200)
        with mock.patch.object(command_line, "PublishContext") as publisher:
            published = await command_line.publish_data(
                {"params": {"passed_data": {"publish_prefix": ""}}},
                logging.getLogger("solver_exception_test"),
                opt_res_latest=result,
                dont_post=True,
            )
        self.assertIsNone(published)
        publisher.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
