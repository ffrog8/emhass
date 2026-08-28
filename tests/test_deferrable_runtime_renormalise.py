"""Runtime deferrable-array normalization for the SOC-aware HA payload."""

import asyncio
import json
import pathlib

import orjson

from emhass import utils

root = pathlib.Path(utils.get_root(__file__, num_parent=2))
emhass_conf = {
    "data_path": root / "data/",
    "root_path": root / "src/emhass/",
    "defaults_path": root / "src/emhass/data/config_defaults.json",
    "associations_path": root / "src/emhass/data/associations.csv",
}
logger, _ = utils.get_logger(__name__, emhass_conf, save_to_file=False)

DEFERRABLE_ARRAY_NAMES = (
    "start_timesteps_of_each_deferrable_load",
    "end_timesteps_of_each_deferrable_load",
    "set_deferrable_load_single_constant",
    "treat_deferrable_load_as_semi_cont",
    "set_deferrable_startup_penalty",
    "deferrable_load_max_cost",
    "set_deferrable_max_startups",
    "operating_hours_of_each_deferrable_load",
    "nominal_power_of_deferrable_loads",
)


async def _build_params() -> dict:
    config = json.loads(emhass_conf["defaults_path"].read_text(encoding="utf-8"))
    _, secrets = await utils.build_secrets(emhass_conf, logger, no_response=True)
    params = await utils.build_params(emhass_conf, secrets, config, logger)
    assert params is not False
    return params


async def _apply_runtime(runtimeparams: dict) -> dict:
    params = await _build_params()
    params_json = orjson.dumps(params).decode("utf-8")
    rh_conf, optim_conf, plant_conf = utils.get_yaml_parse(params_json, logger)
    _, _, optim_conf, _ = await utils.treat_runtimeparams(
        orjson.dumps(runtimeparams).decode("utf-8"),
        params_json,
        rh_conf,
        optim_conf,
        plant_conf,
        "naive-mpc-optim",
        logger,
        emhass_conf,
    )
    return optim_conf


def test_soc_aware_single_ev_runtime_shape_is_preserved():
    runtime = {
        "number_of_deferrable_loads": 1,
        "nominal_power_of_deferrable_loads": [7400],
        "operating_timesteps_of_each_deferrable_load": [6],
        "start_timesteps_of_each_deferrable_load": [2],
        "end_timesteps_of_each_deferrable_load": [20],
        "treat_deferrable_load_as_semi_cont": [0],
        "set_deferrable_load_single_constant": [0],
        "minimum_power_of_deferrable_loads": [1200],
    }

    optim_conf = asyncio.run(_apply_runtime(runtime))

    assert optim_conf["number_of_deferrable_loads"] == 1
    for name, expected in runtime.items():
        if name != "number_of_deferrable_loads":
            assert optim_conf[name] == expected


def test_short_runtime_array_is_padded_to_the_final_load_count():
    optim_conf = asyncio.run(
        _apply_runtime(
            {
                "number_of_deferrable_loads": 2,
                "deferrable_load_max_cost": [0.0],
            }
        )
    )

    assert optim_conf["number_of_deferrable_loads"] == 2
    for name in DEFERRABLE_ARRAY_NAMES:
        assert len(optim_conf[name]) == 2, f"{name} was not normalized"
