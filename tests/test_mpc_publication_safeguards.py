"""Public MPC publication keeps the last accepted plan on a rejected replan."""

import asyncio
import json
import logging
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, patch

import cvxpy as cp
import orjson

from emhass import last_run, plan_store, utils
from emhass.command_line import (
    continual_publish,
    dayahead_forecast_optim,
    naive_mpc_optim,
    publish_data,
    set_input_data_dict,
)


async def _mpc_site(tmp_path, monkeypatch):
    monkeypatch.setattr(last_run, "_cache", None)
    monkeypatch.setattr(plan_store, "_cache", None)
    repo_root = Path(__file__).resolve().parents[1]
    root = repo_root / "src/emhass"
    shutil.copyfile(repo_root / "data/test_df_final.pkl", tmp_path / "test_df_final.pkl")
    conf = {
        "root_path": root,
        "data_path": tmp_path,
        "defaults_path": root / "data/config_defaults.json",
        "associations_path": root / "data/associations.csv",
    }
    config = json.loads(conf["defaults_path"].read_text(encoding="utf-8"))
    config.update(
        set_use_battery=True,
        set_use_pv=False,
        number_of_deferrable_loads=0,
        continual_publish=True,
        num_threads=1,
    )
    logger = logging.getLogger(__name__)
    secrets = {
        "hass_url": "http://127.0.0.1/",
        "long_lived_token": "",
        "time_zone": "UTC",
        "Latitude": 0,
        "Longitude": 0,
        "Altitude": 0,
    }
    params = await utils.build_params(conf, secrets, config, logger)

    async def request(load, publish_prefix="", action="naive-mpc-optim"):
        runtime = {
            "prediction_horizon": 10,
            "pv_power_forecast": [0] * 48,
            "load_power_forecast": [load] * 48,
            "load_cost_forecast": [0.25] * 48,
            "prod_price_forecast": [0] * 48,
            "soc_init": 0.5,
            "soc_final": 0.5,
            "publish_prefix": publish_prefix,
        }
        return await set_input_data_dict(
            conf,
            "profit",
            orjson.dumps(params).decode(),
            orjson.dumps(runtime).decode(),
            action,
            logger,
            get_data_from_file=True,
        )

    return request, logger


def test_failed_mpc_keeps_last_accepted_csv_and_saved_entities(tmp_path, monkeypatch):
    asyncio.run(
        _assert_failed_mpc_keeps_last_accepted_csv_and_saved_entities(tmp_path, monkeypatch)
    )


async def _assert_failed_mpc_keeps_last_accepted_csv_and_saved_entities(tmp_path, monkeypatch):
    request, logger = await _mpc_site(tmp_path, monkeypatch)
    first = await naive_mpc_optim(await request(100), logger)
    assert first["optim_status"].unique().tolist() == ["Optimal"]
    csv_path = tmp_path / "opt_res_latest.csv"
    original_csv = csv_path.read_bytes()
    original_plan = plan_store.read(tmp_path)
    entity_path = tmp_path / "entities"
    original_entities = {
        path.name: path.read_bytes()
        for path in entity_path.iterdir()
        if path.name != "metadata.json"
    }
    original_metadata = json.loads((entity_path / "metadata.json").read_text())
    assert original_entities

    with patch.object(cp.Problem, "solve", side_effect=cp.error.SolverError("injected")):
        rejected = await naive_mpc_optim(await request(200), logger)

    assert rejected["optim_status"].iloc[0] != "Optimal"
    assert csv_path.read_bytes() == original_csv
    assert {
        path.name: path.read_bytes()
        for path in entity_path.iterdir()
        if path.name != "metadata.json"
    } == original_entities
    metadata = json.loads((entity_path / "metadata.json").read_text())
    for name, original in original_metadata.items():
        if isinstance(original, dict):
            assert metadata[name] == {**original, "publication_blocked": True}
        else:
            assert metadata[name] == original
    assert metadata["_optimizer_csv_publication_blocked"]["opt_res_latest.csv"] is True
    assert plan_store.read(tmp_path) == original_plan
    assert last_run.read(tmp_path)["status"] == "error"
    assert last_run.read(tmp_path)["action"] == "naive-mpc-optim"


def test_publish_data_does_not_reload_retained_csv_after_rejected_mpc(tmp_path, monkeypatch):
    asyncio.run(_assert_publish_data_does_not_reload_retained_csv(tmp_path, monkeypatch))


async def _assert_publish_data_does_not_reload_retained_csv(tmp_path, monkeypatch):
    request, logger = await _mpc_site(tmp_path, monkeypatch)
    first = await naive_mpc_optim(await request(100), logger)
    assert first["optim_status"].unique().tolist() == ["Optimal"]
    accepted_run = last_run.read(tmp_path)

    with patch.object(cp.Problem, "solve", side_effect=cp.error.SolverError("injected")):
        rejected = await naive_mpc_optim(await request(200), logger)
    assert rejected["optim_status"].iloc[0] == "Failure"
    assert last_run.read(tmp_path)["status"] == "error"

    # A second worker can retain an older process-local last_run cache. The
    # publish request must use the current durable verdict for saved results.
    monkeypatch.setattr(last_run, "_cache", accepted_run)
    publish_input = await request(300)
    publish_input["rh"] = AsyncMock()
    result = await publish_data(publish_input, logger)

    assert result is None
    publish_input["rh"].post_data.assert_not_awaited()


def test_saved_planner_entities_stop_after_rejection_but_independent_forecast_publishes(
    tmp_path, monkeypatch
):
    asyncio.run(_assert_saved_entity_publication_after_rejection(tmp_path, monkeypatch))


async def _assert_saved_entity_publication_after_rejection(tmp_path, monkeypatch):
    request, logger = await _mpc_site(tmp_path, monkeypatch)
    prefix = "mpc_"
    first_input = await request(100, prefix)
    first = await naive_mpc_optim(first_input, logger)
    assert first["optim_status"].unique().tolist() == ["Optimal"]
    forecast_id = "sensor.mpc_independent_load"
    await first_input["rh"].post_data(
        first["P_Load"].rename("independent_load_forecast"),
        0,
        forecast_id,
        "power",
        "W",
        "Independent load forecast",
        type_var="mlforecaster",
        save_entities=True,
        dont_post=True,
    )

    with patch.object(cp.Problem, "solve", side_effect=cp.error.SolverError("injected")):
        rejected = await naive_mpc_optim(await request(200, prefix), logger)
    assert rejected["optim_status"].iloc[0] == "Failure"

    publish_input = await request(300, prefix)
    publish_input["rh"] = AsyncMock()
    result = await publish_data(publish_input, logger)

    assert list(result.columns) == [forecast_id]
    assert [call.kwargs["entity_id"] for call in publish_input["rh"].post_data.await_args_list] == [
        forecast_id
    ]

    recovered = await naive_mpc_optim(await request(300, prefix), logger)
    assert recovered["optim_status"].unique().tolist() == ["Optimal"]
    recovered_input = await request(400, prefix)
    recovered_input["rh"] = AsyncMock()
    fresh = await publish_data(recovered_input, logger)
    assert "sensor.mpc_p_batt_forecast" in fresh.columns
    assert any(
        call.kwargs["entity_id"] == "sensor.mpc_p_batt_forecast"
        for call in recovered_input["rh"].post_data.await_args_list
    )


def test_continual_publish_does_not_reemit_retained_planner_entities(tmp_path, monkeypatch):
    asyncio.run(_assert_continual_publish_skips_rejected_plan(tmp_path, monkeypatch))


async def _assert_continual_publish_skips_rejected_plan(tmp_path, monkeypatch):
    request, logger = await _mpc_site(tmp_path, monkeypatch)
    first = await naive_mpc_optim(await request(100, "mpc_"), logger)
    assert first["optim_status"].unique().tolist() == ["Optimal"]
    with patch.object(cp.Problem, "solve", side_effect=cp.error.SolverError("injected")):
        rejected = await naive_mpc_optim(await request(200, "mpc_"), logger)
    assert rejected["optim_status"].iloc[0] == "Failure"

    publish_input = await request(300, "mpc_")
    publish_input["rh"] = AsyncMock()
    sleeps = 0

    async def one_cycle(_seconds):
        nonlocal sleeps
        sleeps += 1
        if sleeps > 1:
            raise asyncio.CancelledError

    with patch("emhass.command_line.asyncio.sleep", new=one_cycle):
        try:
            await continual_publish(publish_input, tmp_path / "entities", logger)
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("continual_publish did not stop after one cycle")
    assert sleeps == 2
    publish_input["rh"].post_data.assert_not_awaited()


def test_successful_dayahead_does_not_revive_rejected_mpc_artifacts(tmp_path, monkeypatch):
    asyncio.run(_assert_dayahead_does_not_revive_rejected_mpc_artifacts(tmp_path, monkeypatch))


async def _assert_dayahead_does_not_revive_rejected_mpc_artifacts(tmp_path, monkeypatch):
    request, logger = await _mpc_site(tmp_path, monkeypatch)
    first = await naive_mpc_optim(await request(100, "mpc_"), logger)
    assert first["optim_status"].unique().tolist() == ["Optimal"]
    old_csv = (tmp_path / "opt_res_latest.csv").read_bytes()
    with patch.object(cp.Problem, "solve", side_effect=cp.error.SolverError("injected")):
        rejected = await naive_mpc_optim(await request(200, "mpc_"), logger)
    assert rejected["optim_status"].iloc[0] == "Failure"

    dayahead = await dayahead_forecast_optim(
        await request(900, "dh_", "dayahead-optim"), logger, save_data_to_file=True
    )
    assert dayahead["optim_status"].unique().tolist() == ["Optimal"]
    assert last_run.read(tmp_path)["action"] == "dayahead-optim"
    assert last_run.read(tmp_path)["status"] == "ok"
    assert (tmp_path / "opt_res_latest.csv").read_bytes() == old_csv

    default_input = await request(500, action="publish-data")
    default_input["rh"] = AsyncMock()
    assert await publish_data(default_input, logger) is None
    default_input["rh"].post_data.assert_not_awaited()

    old_prefix_input = await request(500, "mpc_", "publish-data")
    old_prefix_input["rh"] = AsyncMock()
    assert await publish_data(old_prefix_input, logger) is None
    old_prefix_input["rh"].post_data.assert_not_awaited()

    fresh_input = await request(500, "dh_", "publish-data")
    fresh_input["rh"] = AsyncMock()
    fresh = await publish_data(fresh_input, logger)
    assert fresh["sensor.dh_p_load_forecast"].iloc[0] == 900.0


def test_primary_failure_with_relaxed_fallback_does_not_publish_a_fresh_mpc_plan(
    tmp_path, monkeypatch
):
    asyncio.run(_assert_relaxed_fallback_is_not_a_fresh_mpc_plan(tmp_path, monkeypatch))


async def _assert_relaxed_fallback_is_not_a_fresh_mpc_plan(tmp_path, monkeypatch):
    request, logger = await _mpc_site(tmp_path, monkeypatch)
    first = await naive_mpc_optim(await request(100), logger)
    assert first["optim_status"].unique().tolist() == ["Optimal"]
    old_csv = (tmp_path / "opt_res_latest.csv").read_bytes()
    old_plan = plan_store.read(tmp_path)
    real_solve = cp.Problem.solve
    attempts = []

    def fail_primary(problem, *args, **kwargs):
        attempts.append(problem)
        if len(attempts) == 1:
            raise cp.error.SolverError("injected primary failure")
        return real_solve(problem, *args, **kwargs)

    with patch.object(cp.Problem, "solve", new=fail_primary):
        rejected = await naive_mpc_optim(await request(200), logger)

    assert len(attempts) == 2
    assert rejected["optim_status"].iloc[0] != "Optimal"
    assert (tmp_path / "opt_res_latest.csv").read_bytes() == old_csv
    assert plan_store.read(tmp_path) == old_plan
    assert last_run.read(tmp_path)["status"] == "error"
