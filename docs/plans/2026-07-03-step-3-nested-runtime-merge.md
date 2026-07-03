# Step 3 Nested Runtime Merge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add nested runtime overrides for already configured `hybrid_inverter_config_N` blocks while keeping multi-block solving disabled.

**Architecture:** Use an overlay-then-parse flow. Static config remains the source of configured block indexes, flat runtime keys continue to override block `0`, nested `hybrid_inverter_config_N` runtime objects may partially override existing block `N >= 1`, and the parsed private block state is rebuilt after runtime merge before the disabled solve gate fires.

**Tech Stack:** Python `>=3.10,<3.13`, EMHASS config dictionaries, `orjson`, pytest, generated OpenAPI JSON, Markdown docs. Local verification currently uses the existing `emhass-multi-batt-tests-vscode` helper container.

---

## Context And Rationale

Step 2 added static indexed block parsing and a pre-runtime disabled solve gate. Step 3 must move the public action path one step further:

1. Parse static config.
2. Decode and validate runtime payload.
3. Merge flat runtime keys into block `0` through existing behaviour.
4. Merge nested runtime keys only into configured `hybrid_inverter_config_N` blocks.
5. Rebuild `plant_conf["_inverter_block_configs"]`.
6. Raise `multi-block solve not enabled` before `RetrieveHass`, `Forecast`, cache use, or `Optimization` construction.

This preserves compatibility and lets Home Assistant callers validate the final Step 3 payload shape without silently ignoring nested blocks.

## Agent Inputs And Dispute Resolution

Three planning agents reviewed orthogonal slices:

- Runtime mechanics: recommended overlay-then-parse ownership in `inverter_blocks.py`, with `set_input_data_dict()` gate moved after `treat_runtimeparams()`.
- API/security/schema: identified raw runtime payload logging in `web_server._load_params_and_runtime()` as a Step 3 security blocker and recommended permissive OpenAPI documentation for dynamic nested blocks.
- Test/regression: recommended narrow TDD tests for nested block invalidity, configured-only enforcement, one invalid nested key, scalar block override merge, command-line gate ordering, and redacted logging.

Two review agents returned `CHANGES_REQUIRED`. Their corrections are binding in this plan:

- Block `0` remains flat. `hybrid_inverter_config_0` must always fail, including at runtime.
- Runtime-only SOC keys must not enter static block config validation.
- Parsed block state must be rebuilt inside `treat_runtimeparams()` after nested runtime merge.
- Nested `pv_power_forecast` and all PV source/model keys remain rejected until Step 4.
- Raw runtime payload logging must be redacted in Step 3.
- `runtime_params.json` may document the pattern key only; it must not duplicate static config keys or add numbered block defaults.

## In Scope

- Nested runtime object detection for `hybrid_inverter_config_N`.
- Rejecting `hybrid_inverter_config_0` in runtime payloads.
- Rejecting runtime block indexes that do not exist in static config.
- Rejecting non-dict nested runtime blocks.
- Rejecting site-level, secret, publishing, deferrable, unknown, and PV-source keys in nested runtime blocks.
- Merging scalar block-local config overrides for configured blocks, for example `battery_charge_power_max`.
- Capturing runtime-only per-block SOC keys separately: `soc_init`, `soc_final`, `soc_target`, `soc_target_timestep`.
- Rebuilding private parsed block state after runtime merge.
- Moving the command-line disabled solve gate after runtime merge and before any external data, forecast, cache, or optimizer setup.
- Redacting runtime payload logs.
- Updating runtime docs/OpenAPI/runtime metadata to describe dynamic nested block syntax.
- Updating `multi-batt.md` tracker from Step 3 `Not started` to `In progress` or `Review` only when implementation starts or local verification completes.

## Out Of Scope

- Accepting nested `hybrid_inverter_config_N.pv_power_forecast`.
- Resolving `split_pv`, `site_pv`, PV double-count detection, or per-block PV acquisition.
- Enabling multi-block optimization.
- Adding per-block CVXPY variables, result columns, aggregate totals, publisher suffixes, command bridge code, site lock, or per-block deferrables.
- Adding static defaults or `param_definitions.json` entries for numbered blocks.
- Changing legacy golden expectations.
- Making `/action/{action_name}` OpenAPI request schema closed. Existing runtime remains permissive.

## Files

Create:

- No new source modules are required.

Modify:

- `src/emhass/inverter_blocks.py`
- `src/emhass/utils.py`
- `src/emhass/command_line.py`
- `src/emhass/web_server.py`
- `src/emhass/static/data/runtime_params.json`
- `src/emhass/static/openapi.json`
- `scripts/generate_openapi.py`
- `docs/config.md`
- `docs/passing_data.md`
- `multi-batt.md`
- `tests/test_hybrid_inverter_config.py`
- `tests/test_utils.py`
- `tests/test_command_line_utils.py`
- `tests/test_web_server.py`
- `tests/test_runtime_params.py`
- `tests/test_openapi.py`
- `tests/test_schema_contract.py`

Do not modify:

- `src/emhass/optimization.py`, except if a narrow existing guard regression requires no-op import maintenance. The optimizer guard from Step 2 should remain unchanged.
- `docs/plan_output_schema.md`
- `docs/publish_data.md`
- Publisher code.
- Result schema code.

## Verification Environment

The command examples use the local helper container by prefixing the concrete
inner command with `tail -f /dev/null | docker exec -i -w /workspace
emhass-multi-batt-tests-vscode`.

External reviewers without that container should run the same inner command in the repository's documented Python environment. For example:

```bash
uv run pytest tests/test_utils.py -q
```

Do not substitute different test selections when verifying this plan's exit criteria.

## Runtime Contract

Flat runtime payloads remain unchanged:

```json
{
  "soc_init": 0.42,
  "soc_final": 0.90,
  "battery_charge_power_max": 4600,
  "battery_discharge_power_max": 5000
}
```

Nested runtime payloads apply only to configured extra blocks:

```json
{
  "soc_init": 0.42,
  "soc_final": 0.90,
  "battery_charge_power_max": 4600,
  "battery_discharge_power_max": 5000,
  "hybrid_inverter_config_1": {
    "soc_init": 0.51,
    "soc_final": 0.90,
    "soc_target": 0.86,
    "soc_target_timestep": 12,
    "battery_charge_power_max": 4200,
    "battery_discharge_power_max": 4500
  }
}
```

Rules:

- Flat keys override block `0`.
- Nested block keys override the matching configured block `N >= 1`.
- Runtime cannot create `hybrid_inverter_config_N`.
- `hybrid_inverter_config_0` is invalid.
- Nested runtime blocks are partial overlays. They do not need to repeat all static block keys.
- `soc_init`, `soc_final`, `soc_target`, and `soc_target_timestep` are runtime-only. They must not be stored as public/static `optim_conf` or `plant_conf` keys and must not appear in serialized public config JSON. Validated values may live only in private parsed block state and nested `passed_data`.
- Nested scalar config overrides are validated using the same block-local validation as static config after overlay.
- Per-timestep cap arrays are future work. If `battery_charge_power_max` or `battery_discharge_power_max` is a list/dict in a nested block, fail validation.
- Nested `pv_power_forecast` is Step 4 and must hard-fail in Step 3.

## Task 1: Red Runtime Merge Tests

**Files:**

- Modify: `tests/test_utils.py`
- Modify: `tests/test_hybrid_inverter_config.py`

- [ ] **Step 1: Add reusable configured-block fixture helpers**

Use the existing `TestUtils` setup and Step 2 block helpers. Add a local helper in `tests/test_utils.py` if needed:

```python
def _configured_extra_block() -> dict:
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
```

- [ ] **Step 2: Add nested block `0` rejection test**

Add:

```python
async def test_treat_runtimeparams_rejects_nested_hybrid_inverter_config_0(self):
    params = orjson.loads(self.params_json)
    params["hybrid_inverter_config_1"] = _configured_extra_block()
    runtimeparams = {
        "hybrid_inverter_config_0": {
            "soc_init": 0.4,
        }
    }

    with self.assertRaisesRegex(ValueError, "hybrid_inverter_config_0"):
        await utils.treat_runtimeparams(
            orjson.dumps(runtimeparams).decode("utf-8"),
            params,
            *utils.get_yaml_parse(params, logger),
            "naive-mpc-optim",
            logger,
            emhass_conf,
        )
```

Expected before implementation: fails because nested block `0` is ignored.

- [ ] **Step 3: Add runtime block without config rejection test**

Add:

```python
async def test_treat_runtimeparams_rejects_runtime_block_without_config_block(self):
    params = orjson.loads(self.params_json)
    runtimeparams = {
        "hybrid_inverter_config_1": {
            "soc_init": 0.4,
        }
    }

    with self.assertRaisesRegex(ValueError, "without matching configured block"):
        await utils.treat_runtimeparams(
            orjson.dumps(runtimeparams).decode("utf-8"),
            params,
            *utils.get_yaml_parse(params, logger),
            "naive-mpc-optim",
            logger,
            emhass_conf,
        )
```

Expected before implementation: fails because nested block `1` is ignored.

- [ ] **Step 4: Add invalid nested key rejection tests**

Use site-level, secret, publishing, deferrable, unknown, runtime PV forecast,
and reserved config-time PV source/model keys:

Ensure `tests/test_utils.py` imports `_RESERVED_PV_SOURCE_KEYS` from
`emhass.inverter_blocks` for this contract test.

```python
async def test_treat_runtimeparams_rejects_invalid_nested_runtime_keys_for_configured_block(self):
    invalid_keys = tuple(
        dict.fromkeys(
            (
                "maximum_power_from_grid",
                "long_lived_token",
                "influxdb_password",
                "continual_publish",
                "number_of_deferrable_loads",
                "not_a_real_block_key",
                "pv_power_forecast",
            )
            + tuple(_RESERVED_PV_SOURCE_KEYS)
        )
    )
    required_reserved_pv_keys = (
        "sensor_power_photovoltaics",
        "set_total_pv_sell",
        "compute_curtailment",
    )
    for required_key in required_reserved_pv_keys:
        assert required_key in invalid_keys

    for invalid_key in invalid_keys:
        params = orjson.loads(self.params_json)
        params["hybrid_inverter_config_1"] = _configured_extra_block()
        runtimeparams = {
            "hybrid_inverter_config_1": {
                invalid_key: 1234,
            }
        }

        with self.assertRaisesRegex(ValueError, invalid_key):
            await utils.treat_runtimeparams(
                orjson.dumps(runtimeparams).decode("utf-8"),
                params,
                *utils.get_yaml_parse(params, logger),
                "naive-mpc-optim",
                logger,
                emhass_conf,
            )
```

This test must use all reserved PV source/model keys from the implementation
constant, not one representative key.

Expected before implementation: fails because nested runtime keys are ignored.

- [ ] **Step 5: Add non-dict nested block rejection test**

Add:

```python
async def test_treat_runtimeparams_rejects_non_dict_nested_runtime_block(self):
    params = orjson.loads(self.params_json)
    params["hybrid_inverter_config_1"] = _configured_extra_block()
    runtimeparams = {"hybrid_inverter_config_1": "bad"}

    with self.assertRaisesRegex(ValueError, "dictionary"):
        await utils.treat_runtimeparams(
            orjson.dumps(runtimeparams).decode("utf-8"),
            params,
            *utils.get_yaml_parse(params, logger),
            "naive-mpc-optim",
            logger,
            emhass_conf,
        )
```

Expected before implementation: fails because nested runtime blocks are ignored.

- [ ] **Step 6: Add nested scalar merge test**

Assert flat block `0` values remain flat, nested block `1` config values update only block `1`, and nested SOC runtime values are carried separately.

```python
async def test_treat_runtimeparams_merges_nested_scalar_runtime_into_existing_block_only(self):
    params = orjson.loads(self.params_json)
    params["hybrid_inverter_config_1"] = _configured_extra_block()
    original_block0_charge_limit = params["plant_conf"]["battery_charge_power_max"]
    runtimeparams = {
        "soc_init": 0.42,
        "battery_charge_power_max": 4100,
        "hybrid_inverter_config_1": {
            "soc_init": 0.51,
            "soc_final": 0.90,
            "soc_target": 0.86,
            "soc_target_timestep": 12,
            "battery_charge_power_max": 4200,
            "battery_discharge_power_max": 4500,
        },
    }

    params_json, _, _, plant_conf = await utils.treat_runtimeparams(
        orjson.dumps(runtimeparams).decode("utf-8"),
        params,
        *utils.get_yaml_parse(params, logger),
        "naive-mpc-optim",
        logger,
        emhass_conf,
    )
    params_out = orjson.loads(params_json)
    blocks = plant_conf[INVERTER_BLOCK_CONFIGS_KEY]

    assert params_out["plant_conf"]["battery_charge_power_max"] == 4100
    assert original_block0_charge_limit != 4100
    assert blocks[1].plant_conf["battery_charge_power_max"] == 4200
    assert blocks[1].plant_conf["battery_discharge_power_max"] == 4500
    assert blocks[1].runtime_conf == {
        "soc_init": 0.51,
        "soc_final": 0.90,
        "soc_target": 0.86,
        "soc_target_timestep": 12,
    }
    assert params_out["passed_data"]["hybrid_inverter_config_1"] == blocks[1].runtime_conf
    assert 1 in plant_conf[INVERTER_BLOCK_CONFIGS_KEY]
    assert "_inverter_block_configs" not in params_out["plant_conf"]
```

Expected before implementation: fails because nested runtime is ignored and parsed block state is not rebuilt after merge.

- [ ] **Step 7: Keep Step 2 static PV reserved-key regression aligned**

Expand `tests/test_hybrid_inverter_config.py` parametrization to include every
reserved key listed in `src/emhass/inverter_blocks.py` so static config and
nested runtime config reject the same PV source/model surface until Step 4.

- [ ] **Step 8: Add strict runtime timestep validation tests**

Add:

```python
@pytest.mark.parametrize("bad_value", [1.5, True, -1])
async def test_treat_runtimeparams_rejects_invalid_nested_soc_target_timestep(self, bad_value):
    params = orjson.loads(self.params_json)
    params["hybrid_inverter_config_1"] = _configured_extra_block()
    runtimeparams = {
        "hybrid_inverter_config_1": {
            "soc_init": 0.51,
            "soc_target_timestep": bad_value,
        }
    }

    with self.assertRaisesRegex(ValueError, "soc_target_timestep"):
        await utils.treat_runtimeparams(
            orjson.dumps(runtimeparams).decode("utf-8"),
            params,
            *utils.get_yaml_parse(params, logger),
            "naive-mpc-optim",
            logger,
            emhass_conf,
        )
```

This prevents `int(1.5)` truncation and `True` being accepted as `1`.

- [ ] **Step 9: Run red tests individually**

Run in Docker:

```bash
tail -f /dev/null | docker exec -i -w /workspace emhass-multi-batt-tests-vscode uv run pytest tests/test_utils.py::TestUtils::test_treat_runtimeparams_rejects_nested_hybrid_inverter_config_0 -q
tail -f /dev/null | docker exec -i -w /workspace emhass-multi-batt-tests-vscode uv run pytest tests/test_utils.py::TestUtils::test_treat_runtimeparams_rejects_runtime_block_without_config_block -q
tail -f /dev/null | docker exec -i -w /workspace emhass-multi-batt-tests-vscode uv run pytest tests/test_utils.py::TestUtils::test_treat_runtimeparams_rejects_invalid_nested_runtime_keys_for_configured_block -q
tail -f /dev/null | docker exec -i -w /workspace emhass-multi-batt-tests-vscode uv run pytest tests/test_utils.py::TestUtils::test_treat_runtimeparams_rejects_non_dict_nested_runtime_block -q
tail -f /dev/null | docker exec -i -w /workspace emhass-multi-batt-tests-vscode uv run pytest tests/test_utils.py::TestUtils::test_treat_runtimeparams_merges_nested_scalar_runtime_into_existing_block_only -q
tail -f /dev/null | docker exec -i -w /workspace emhass-multi-batt-tests-vscode uv run pytest tests/test_utils.py::TestUtils::test_treat_runtimeparams_rejects_invalid_nested_soc_target_timestep -q
```

Expected: each new Step 3 test fails for the specific missing behaviour.

## Task 2: Runtime Merge Helpers

**Files:**

- Modify: `src/emhass/inverter_blocks.py`
- Modify: `tests/test_hybrid_inverter_config.py`

- [ ] **Step 1: Add runtime-only key constants**

Add near the Step 2 key sets:

```python
_RUNTIME_ONLY_BLOCK_KEYS = frozenset(
    {
        "soc_init",
        "soc_final",
        "soc_target",
        "soc_target_timestep",
    }
)

_DEFERRED_RUNTIME_BLOCK_KEYS = frozenset(
    {
        "pv_power_forecast",
    }
)
```

- [ ] **Step 2: Extend `InverterBlockConfig` with runtime state**

Change constructor to:

```python
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
```

Block `0` normally gets `{}` in Step 3 because flat runtime already lives in existing `passed_data`.

- [ ] **Step 3: Add nested runtime block index extraction**

Add helper:

```python
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
```

- [ ] **Step 4: Add runtime SOC validators**

Add helpers that validate finite numeric values and configured min/max:

```python
def _validate_runtime_soc(value: object, block_index: int, key: str, plant_conf: Mapping[str, object]) -> float:
    numeric = _validate_soc(value, block_index, key)
    soc_min = float(plant_conf["battery_minimum_state_of_charge"])
    soc_max = float(plant_conf["battery_maximum_state_of_charge"])
    if numeric < soc_min or numeric > soc_max:
        raise ValueError(f"hybrid_inverter_config_{block_index}.{key} must be within configured min/max SOC")
    return numeric
```

For `soc_target_timestep`, validate it as a non-negative integer:

```python
def _validate_runtime_timestep(value: object, block_index: int, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"hybrid_inverter_config_{block_index}.{key} must be an integer")
    if value < 0:
        raise ValueError(f"hybrid_inverter_config_{block_index}.{key} must be >= 0")
    return value
```

- [ ] **Step 5: Add overlay helper**

Add:

```python
def merge_inverter_block_runtime_overrides(
    input_conf: dict[str, object],
    runtimeparams: Mapping[str, object],
) -> dict[int, dict[str, object]]:
    block_runtime_conf: dict[int, dict[str, object]] = {}
    configured_indexes = set(_extract_block_indexes(input_conf))
    allowed_config_keys = _OPTIM_CONF_BLOCK_KEYS | _PLANT_CONF_BLOCK_KEYS
    forbidden_keys = _SITE_LEVEL_FORBIDDEN_KEYS | _RESERVED_PV_SOURCE_KEYS

    for index in _extract_runtime_block_indexes(runtimeparams):
        if index not in configured_indexes:
            raise ValueError(f"hybrid_inverter_config_{index} runtime block has no matching configured block")
        block_key = f"{HYBRID_INVERTER_CONFIG_PREFIX}{index}"
        raw_runtime_block = runtimeparams[block_key]
        if not isinstance(raw_runtime_block, Mapping):
            raise ValueError(f"{block_key} runtime block must be a dictionary")
        static_block = input_conf[block_key]
        if not isinstance(static_block, dict):
            raise ValueError(f"{block_key} configured block must be a dictionary")

        runtime_conf: dict[str, object] = {}
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
            if key in {"battery_charge_power_max", "battery_discharge_power_max"} and isinstance(
                value, list | tuple | dict
            ):
                raise ValueError(f"{block_key}.{key} per-timestep forecasts are future scope")
            static_block[key] = value

        block_runtime_conf[index] = runtime_conf

    return block_runtime_conf
```

- [ ] **Step 6: Validate runtime-only state after overlay**

Add a helper called by `parse_inverter_block_configs`:

```python
def _validate_block_runtime_conf(
    index: int,
    runtime_conf: Mapping[str, object],
    plant_conf: Mapping[str, object],
) -> dict[str, object]:
    validated: dict[str, object] = {}
    for key, value in runtime_conf.items():
        if key in {"soc_init", "soc_final", "soc_target"}:
            validated[key] = _validate_runtime_soc(value, index, key, plant_conf)
        elif key == "soc_target_timestep":
            validated[key] = _validate_runtime_timestep(value, index, key)
        else:
            raise ValueError(f"hybrid_inverter_config_{index}.{key} is not a valid runtime-only key")
    return validated
```

- [ ] **Step 7: Extend parser signature**

Change:

```python
def parse_inverter_block_configs(
    input_conf: Mapping[str, object],
    optim_conf: dict,
    plant_conf: dict,
) -> dict[int, InverterBlockConfig]:
```

to:

```python
def parse_inverter_block_configs(
    input_conf: Mapping[str, object],
    optim_conf: dict,
    plant_conf: dict,
    block_runtime_conf: Mapping[int, Mapping[str, object]] | None = None,
) -> dict[int, InverterBlockConfig]:
```

When creating extra block `N`, validate the runtime conf against the merged block plant config and pass it to `InverterBlockConfig`.

- [ ] **Step 8: Run helper/parser tests**

```bash
tail -f /dev/null | docker exec -i -w /workspace emhass-multi-batt-tests-vscode uv run pytest tests/test_hybrid_inverter_config.py -q
```

Expected: all parser/helper tests pass.

## Task 3: Integrate Merge In `treat_runtimeparams`

**Files:**

- Modify: `src/emhass/utils.py`
- Modify: `tests/test_utils.py`

- [ ] **Step 1: Import helpers**

Add imports:

```python
from emhass.inverter_blocks import (
    HYBRID_INVERTER_CONFIG_PREFIX,
    INVERTER_BLOCK_CONFIGS_KEY,
    merge_inverter_block_runtime_overrides,
    parse_inverter_block_configs,
)
```

Preserve existing imports and avoid duplicate names.

- [ ] **Step 2: Decode runtime params once**

Inside `treat_runtimeparams`, keep the existing public behaviour for `None`, JSON string, and dict inputs. Immediately after decoding runtime params, call:

```python
block_runtime_conf = merge_inverter_block_runtime_overrides(params, runtimeparams)
```

This must happen before the association loop can ignore nested keys and before serialization.

- [ ] **Step 3: Leave flat runtime merge unchanged**

Do not move existing association, MPC SOC, forecast-list, deferrable, ML, or secret runtime handling except as required to decode once. Existing flat runtime tests must remain unchanged.

- [ ] **Step 4: Rebuild parsed block state after merge**

After `retrieve_hass_conf`, `optim_conf`, and `plant_conf` are split from `params`, call:

```python
parse_inverter_block_configs(params, optim_conf, plant_conf, block_runtime_conf)
```

This reattaches private block state for `set_input_data_dict()` to inspect.

- [ ] **Step 5: Keep private state out of serialized params without mutating returned `plant_conf`**

Do not call `params["plant_conf"].pop(INVERTER_BLOCK_CONFIGS_KEY, None)` on the same dictionary object returned as `plant_conf`. That would make `has_extra_inverter_blocks(plant_conf)` miss configured blocks after `treat_runtimeparams()`.

Instead, serialize a public copy:

```python
public_plant_conf = dict(params["plant_conf"])
public_plant_conf.pop(INVERTER_BLOCK_CONFIGS_KEY, None)
params_for_serialization = dict(params)
params_for_serialization["plant_conf"] = public_plant_conf
params_json = orjson.dumps(params_for_serialization, default=str).decode()
```

The returned `plant_conf` object must still include `INVERTER_BLOCK_CONFIGS_KEY`; the serialized `params_json` must not. The nested merge test must assert both facts.

- [ ] **Step 6: Expose nested runtime-only state in `passed_data`**

When `block_runtime_conf` is non-empty, set:

```python
params["passed_data"][f"{HYBRID_INVERTER_CONFIG_PREFIX}{index}"] = dict(validated_runtime_conf)
```

Use the validated runtime state from parsed blocks, not the raw payload.

- [ ] **Step 7: Run runtime merge tests**

```bash
tail -f /dev/null | docker exec -i -w /workspace emhass-multi-batt-tests-vscode uv run pytest tests/test_utils.py::TestUtils::test_treat_runtimeparams_rejects_nested_hybrid_inverter_config_0 tests/test_utils.py::TestUtils::test_treat_runtimeparams_rejects_runtime_block_without_config_block tests/test_utils.py::TestUtils::test_treat_runtimeparams_rejects_invalid_nested_runtime_keys_for_configured_block tests/test_utils.py::TestUtils::test_treat_runtimeparams_rejects_non_dict_nested_runtime_block tests/test_utils.py::TestUtils::test_treat_runtimeparams_merges_nested_scalar_runtime_into_existing_block_only -q
```

Expected: new Step 3 tests pass.

## Task 4: Move Public Disabled Solve Gate After Runtime Merge

**Files:**

- Modify: `src/emhass/command_line.py`
- Modify: `tests/test_command_line_utils.py`
- Keep: `src/emhass/optimization.py` guard unchanged.

- [ ] **Step 1: Update command-line gate test**

Replace or rename `test_valid_extra_hybrid_block_reaches_disabled_multi_block_gate` with:

Ensure `tests/test_command_line_utils.py` imports `emhass.utils as utils` if it does not already.

```python
async def test_valid_extra_hybrid_block_merges_runtime_then_reaches_disabled_multi_block_gate(self):
    params = get_test_params()
    params["hybrid_inverter_config_1"] = _configured_extra_block()
    runtimeparams = {
        "hybrid_inverter_config_1": {
            "soc_init": 0.50,
            "battery_charge_power_max": 4200,
        }
    }

    with patch(
        "emhass.command_line.utils.treat_runtimeparams",
        wraps=utils.treat_runtimeparams,
    ) as mock_treat_runtimeparams:
        with patch("emhass.command_line.RetrieveHass") as mock_retrieve_hass:
            with patch("emhass.command_line.Forecast") as mock_forecast:
                with patch("emhass.command_line.Optimization") as mock_optimization:
                    with pytest.raises(NotImplementedError, match="multi-block solve not enabled"):
                        await set_input_data_dict(
                            emhass_conf,
                            "profit",
                            orjson.dumps(params).decode("utf-8"),
                            orjson.dumps(runtimeparams).decode("utf-8"),
                            "naive-mpc-optim",
                            logger,
                        )

    mock_treat_runtimeparams.assert_awaited_once()
    mock_retrieve_hass.assert_not_called()
    mock_forecast.assert_not_called()
    mock_optimization.assert_not_called()
```

The test must prove:

- `treat_runtimeparams()` is awaited. This assertion must fail before Step 3 if the disabled gate still fires before runtime merge.
- Nested runtime validation/merge occurs before the `NotImplementedError`.
- `RetrieveHass`, `Forecast`, cache lookup, and `Optimization` construction are not reached.

- [ ] **Step 2: Move the gate**

In `set_input_data_dict()`:

1. Remove the current `has_extra_inverter_blocks(plant_conf)` check before `treat_runtimeparams`.
2. Call `treat_runtimeparams()`.
3. Convert returned `params` JSON to dict as today.
4. Immediately check:

```python
if has_extra_inverter_blocks(plant_conf):
    raise NotImplementedError(MULTI_BLOCK_SOLVE_DISABLED_MESSAGE)
```

5. Pop `INVERTER_BLOCK_CONFIGS_KEY` only after the gate for legacy no-extra-block paths.

- [ ] **Step 3: Add external setup guard assertions**

Patch or assert that these are not constructed for a valid extra block:

- `RetrieveHass`
- `Forecast`
- `Optimization`

If existing test structure makes all three expensive to patch, at minimum assert no `RetrieveHass` and no `Optimization`, because those prove the gate is before external setup and solve construction.

- [ ] **Step 4: Run command-line gate tests**

```bash
tail -f /dev/null | docker exec -i -w /workspace emhass-multi-batt-tests-vscode uv run pytest tests/test_command_line_utils.py::TestCommandLineAsyncUtils::test_valid_extra_hybrid_block_merges_runtime_then_reaches_disabled_multi_block_gate -q
```

Expected: pass.

- [ ] **Step 5: Run optimizer guard regression**

```bash
tail -f /dev/null | docker exec -i -w /workspace emhass-multi-batt-tests-vscode uv run pytest tests/test_optimization.py::TestOptimization::test_extra_hybrid_block_rejected_before_optimizer_setup -q
```

Expected: pass.

## Task 5: Redact Runtime Payload Logging

**Files:**

- Modify: `src/emhass/web_server.py`
- Modify: `tests/test_web_server.py`

- [ ] **Step 1: Add redaction test**

Add a focused test using the existing patched `/action/naive-mpc-optim` pattern from `tests/test_web_server.py`:

```python
@patch("pathlib.Path.exists")
@patch("emhass.web_server.aiofiles.open")
@patch("emhass.web_server.set_input_data_dict", new_callable=AsyncMock)
@patch("emhass.web_server.naive_mpc_optim", new_callable=AsyncMock)
@patch("emhass.web_server.get_injection_dict")
@patch("emhass.web_server.app.logger")
async def test_action_runtime_logging_redacts_flat_and_nested_secret_values(
    self,
    mock_logger,
    mock_get_inject,
    mock_optim,
    mock_set_input,
    mock_file,
    mock_path_exists,
):
    secret = "super-secret-token"
    nested_secret = "nested-secret-token"
    neutral_token_like_value = "eyJhbGciOiJIUzI1NiJ9.payload.signature"
    runtime_payload = {
        "solcast_api_key": secret,
        "hybrid_inverter_config_1": {
            "long_lived_token": nested_secret,
            "soc_init": 0.5,
            "battery_charge_power_max": 4200,
            "neutral_name": neutral_token_like_value,
        },
        "pv_power_forecast": [0, 100, 200],
    }

    mock_path_exists.return_value = True

    def aiofiles_side_effect(file, mode="r", *args, **kwargs):
        context_mock = AsyncMock()
        file_handle = AsyncMock()
        context_mock.__aenter__.return_value = file_handle
        if "params.pkl" in str(file):
            file_handle.read.return_value = pickle.dumps(
                (pathlib.Path("/config"), {"optim_conf": {}})
            )
        else:
            file_handle.read.return_value = "INFO >> Success"
        return context_mock

    mock_file.side_effect = aiofiles_side_effect
    mock_set_input.return_value = {
        "params": {},
        "retrieve_hass_conf": {"continual_publish": False},
    }
    mock_optim.return_value = MagicMock()
    mock_get_inject.return_value = {"optim_status": "Optimal"}

    response = await self.client.post(
        "/action/naive-mpc-optim",
        json=runtime_payload,
        headers={"Content-Type": "application/json"},
    )

    self.assertEqual(response.status_code, 200)
    actual_payload = orjson.loads(mock_set_input.call_args[0][3])
    self.assertEqual(actual_payload, runtime_payload)

    logged = " ".join(
        " ".join(str(arg) for arg in call.args) for call in mock_logger.info.call_args_list
    )
    self.assertNotIn(secret, logged)
    self.assertNotIn(nested_secret, logged)
    self.assertNotIn(neutral_token_like_value, logged)
    self.assertNotIn("solcast_api_key", logged)
    self.assertNotIn("long_lived_token", logged)
    self.assertNotIn("0.5", logged)
    self.assertNotIn("4200", logged)
    self.assertNotIn("[0, 100, 200]", logged)
    self.assertIn("<list len=3>", logged)
    self.assertIn("hybrid_inverter_config_1", logged)
    self.assertIn("pv_power_forecast", logged)
```

Redaction is log-only; the runtime JSON passed to `set_input_data_dict` must remain unchanged.

- [ ] **Step 2: Add recursive redaction helper**

In `web_server.py`, add a private helper near `_load_params_and_runtime()`:

```python
def _summarize_runtimeparams_for_log(value):
    secret_keys = set(get_keys_to_mask())
    secret_markers = ("token", "secret", "password", "api_key")
    mask = "***"

    def looks_token_like(text: str) -> bool:
        if len(text) >= 24 and "." in text:
            return True
        return len(text) >= 32 and any(ch.isdigit() for ch in text) and any(ch.isalpha() for ch in text)

    def summarize(item, key=""):
        key_text = str(key)
        key_lower = key_text.lower()
        if key_text in secret_keys or any(marker in key_lower for marker in secret_markers):
            return mask
        if isinstance(item, dict):
            summarized = {}
            redacted_index = 0
            for nested_key, nested_value in item.items():
                nested_key_text = str(nested_key)
                if nested_key_text in secret_keys or any(
                    marker in nested_key_text.lower() for marker in secret_markers
                ):
                    summarized[f"<redacted_{redacted_index}>"] = mask
                    redacted_index += 1
                else:
                    summarized[nested_key] = summarize(nested_value, nested_key)
            return summarized
        if isinstance(item, list | tuple):
            return f"<list len={len(item)}>"
        if isinstance(item, str) and looks_token_like(item):
            return mask
        if isinstance(item, int | float | bool):
            return f"<{type(item).__name__}>"
        return item

    return summarize(value)
```

Rules:

- Mask keys from `get_keys_to_mask()`.
- Mask any key containing `token`, `secret`, `password`, or `api_key` case-insensitively.
- Do not log sensitive key names; replace them with neutral placeholders like `<redacted_0>`.
- Mask token-like string values even when their key name is neutral.
- Summarize all lists/tuples as `<list len=N>`.
- Summarize scalar numeric and boolean values by type, for example `<float>`.
- For dicts, recurse.
- Preserve non-sensitive top-level key names and nested block names.

- [ ] **Step 3: Replace raw log call**

Replace:

```python
logger.info("Passed runtime parameters: " + str(runtimeparams))
```

with:

```python
logger.info("Passed runtime parameters: %s", _summarize_runtimeparams_for_log(runtimeparams))
```

- [ ] **Step 4: Run logging tests**

```bash
tail -f /dev/null | docker exec -i -w /workspace emhass-multi-batt-tests-vscode uv run pytest tests/test_web_server.py::TestWebServer::test_action_runtime_logging_redacts_flat_and_nested_secret_values -q
```

Expected: pass.

## Task 6: Runtime Metadata, OpenAPI, And Docs

**Files:**

- Modify: `src/emhass/static/data/runtime_params.json`
- Modify: `scripts/generate_openapi.py`
- Modify: `src/emhass/static/openapi.json`
- Modify: `docs/config.md`
- Modify: `docs/passing_data.md`
- Modify: `tests/test_runtime_params.py`
- Modify: `tests/test_openapi.py`
- Modify: `tests/test_schema_contract.py`

- [ ] **Step 1: Add runtime params pattern descriptor**

Add one runtime-only metadata entry such as:

```json
"Hybrid inverter runtime blocks": {
  "hybrid_inverter_config_<N>": {
    "friendly_name": "Nested hybrid inverter runtime block",
    "Description": "Runtime-only nested object for an already configured hybrid_inverter_config_N block where N >= 1. Flat top-level runtime keys continue to address block 0. Supports runtime-only SOC keys such as soc_init, soc_final, soc_target, and soc_target_timestep plus scalar block-local config overrides. Runtime cannot create blocks. PV forecasts are Step 4 scope.",
    "input": "object",
    "default_value": null,
    "unit": "none"
  }
}
```

Do not add `hybrid_inverter_config_1`, `hybrid_inverter_config_2`, or top-level duplicates of `battery_charge_power_max`.

- [ ] **Step 2: Add runtime params contract tests**

Add tests that assert:

- No literal numbered `hybrid_inverter_config_\d+` keys exist in `runtime_params.json`.
- `hybrid_inverter_config_<N>` exists.
- Config keys such as `battery_charge_power_max` are not duplicated as runtime-only top-level metadata.
- Existing disjoint-from-config test still passes.
- The generated OpenAPI `RuntimeParams` schema, whether referenced directly or through `$ref`, does not expose literal `hybrid_inverter_config_<N>` as a request property.

- [ ] **Step 3: Add OpenAPI runtime component**

In `scripts/generate_openapi.py`, create a permissive `RuntimeParams` component for `/action/{action_name}` request bodies. It should:

- Include literal properties generated from `runtime_params.json`, excluding the `hybrid_inverter_config_<N>` descriptor entry.
- Convert the `hybrid_inverter_config_<N>` descriptor entry only into `patternProperties`.
- Include `patternProperties` for `^hybrid_inverter_config_[1-9][0-9]*$`.
- Keep `additionalProperties: True`.
- Avoid hardcoded numbered block keys.

Add an OpenAPI contract test that loads `/action/{action_name}` request schema,
resolves `$ref` if present, and asserts against the resolved `RuntimeParams`
schema:

```python
def _resolve_schema_ref(openapi_doc, schema):
    if "$ref" not in schema:
        return schema
    ref = schema["$ref"]
    assert ref.startswith("#/")
    resolved = openapi_doc
    for part in ref.removeprefix("#/").split("/"):
        resolved = resolved[part]
    return resolved


request_schema = request_body_schema["content"]["application/json"]["schema"]
runtime_schema = _resolve_schema_ref(openapi_doc, request_schema)
assert runtime_schema is openapi_doc["components"]["schemas"]["RuntimeParams"]
assert "hybrid_inverter_config_<N>" not in runtime_schema.get("properties", {})
assert "^hybrid_inverter_config_[1-9][0-9]*$" in runtime_schema.get("patternProperties", {})
```

- [ ] **Step 4: Regenerate OpenAPI**

Run in Docker:

```bash
tail -f /dev/null | docker exec -i -w /workspace emhass-multi-batt-tests-vscode uv run python scripts/generate_openapi.py
```

Expected: `src/emhass/static/openapi.json` updates only from the schema generator.

- [ ] **Step 5: Update docs**

In `docs/config.md`, update the indexed block section:

- Step 3 validates nested runtime block values.
- A valid extra block still raises `multi-block solve not enabled`.
- Per-block PV acquisition remains later work.

In `docs/passing_data.md`, add a nested runtime section:

- Show flat block `0` keys and nested block `N >= 1` keys.
- State that runtime blocks must match static config blocks.
- State that `hybrid_inverter_config_0` is invalid.
- State that nested PV forecast keys are future Step 4 scope.
- State that Step 3 validates but does not solve multi-block plans.

- [ ] **Step 6: Run docs/schema tests**

```bash
tail -f /dev/null | docker exec -i -w /workspace emhass-multi-batt-tests-vscode uv run pytest tests/test_runtime_params.py tests/test_openapi.py tests/test_schema_contract.py -q
```

Expected: pass.

## Task 7: Update Tracker And Scope Audit

**Files:**

- Modify: `multi-batt.md`

- [ ] **Step 1: Update Step 3 tracker status**

At implementation start, set Step 3 to `In progress` with branch `multi-batt`.

After local verification and review, set Step 3 to `Review` with:

- targeted tests result
- full suite result if run
- lint result
- review status
- external CI pending

Do not mark Step 3 `Done` until the criteria in `multi-batt.md` are satisfied.

- [ ] **Step 2: Run scope grep**

```bash
rg -n "P_batt_1|SOC_opt_1|P_batt_total|P_hybrid_inverter_total|p_batt_forecast_1|p_deferrable_1|battery_mode_lock|P_PV_1|P_PV_total" src/emhass tests
```

Expected: no matches from Step 3 implementation.

- [ ] **Step 3: Check no superpowers artifacts**

```bash
git -C /home/coder/git/emhass-multi-batt ls-files | rg '(^|/)superpowers(/|$)'
git -C /home/coder/git/emhass-multi-batt check-ignore -v docs/superpowers/plans/example.md
```

Expected: no tracked superpowers files; ignore rule matches generated files under `docs/superpowers/`.

## Final Verification

Run the narrow checks first:

```bash
tail -f /dev/null | docker exec -i -w /workspace emhass-multi-batt-tests-vscode uv run pytest tests/test_utils.py tests/test_command_line_utils.py::TestCommandLineAsyncUtils tests/test_web_server.py::TestWebServer tests/test_runtime_params.py tests/test_openapi.py tests/test_schema_contract.py -q --durations=10
```

Run guard checks:

```bash
tail -f /dev/null | docker exec -i -w /workspace emhass-multi-batt-tests-vscode uv run pytest tests/test_hybrid_inverter_config.py tests/test_optimization.py::TestOptimization::test_extra_hybrid_block_rejected_before_optimizer_setup -q
```

Run legacy compatibility guard:

```bash
tail -f /dev/null | docker exec -i -w /workspace emhass-multi-batt-tests-vscode uv run pytest tests/test_optimization.py::TestOptimization::test_internal_inverter_block_zero_wraps_legacy_flat_state tests/test_optimization.py::TestOptimization::test_single_inverter_no_extra_block_matches_complete_output_golden tests/test_optimization.py::TestOptimization::test_default_single_inverter_no_extra_block_matches_complete_output_golden tests/test_optimization.py::TestOptimization::test_legacy_battery_result_signs_units_and_grid_balance tests/test_optimization.py::TestOptimization::test_legacy_grid_charge_and_discharge_flags_block_only_forbidden_paths tests/test_optimization.py::TestOptimization::test_legacy_hybrid_grid_charge_and_discharge_flags_block_forbidden_paths tests/test_optimization.py::TestOptimization::test_inverter_stress_cost_discharge_spread tests/test_optimization.py::TestOptimization::test_nodischarge_to_grid_ac_coupled_feasible_issue936 tests/test_optimization.py::TestOptimization::test_nodischarge_to_grid_hybrid_still_blocks_discharge_issue936 tests/test_command_line_utils.py::TestCommandLineAsyncUtils::test_naive_mpc_flat_runtime_payload_preserves_scalar_battery_inputs tests/test_command_line_utils.py::TestCommandLineAsyncUtils::test_naive_mpc_flat_runtime_payload_matches_complete_output_golden tests/test_command_line_utils.py::TestCommandLineAsyncUtils::test_default_publish_descriptors_keep_legacy_single_inverter_names tests/test_command_line_utils.py::TestCommandLineAsyncUtils::test_publish_data_uses_legacy_single_inverter_entity_pairs tests/test_web_server.py::TestWebServer::test_action_naive_mpc_preserves_flat_runtime_payload -q --durations=10
```

Run lint and whitespace checks:

```bash
tail -f /dev/null | docker exec -i -w /workspace emhass-multi-batt-tests-vscode uv run ruff check src/emhass/inverter_blocks.py src/emhass/utils.py src/emhass/command_line.py src/emhass/web_server.py tests/test_hybrid_inverter_config.py tests/test_utils.py tests/test_command_line_utils.py tests/test_web_server.py tests/test_runtime_params.py tests/test_openapi.py tests/test_schema_contract.py
git -C /home/coder/git/emhass-multi-batt diff --check
```

Run docs build because Step 3 edits `docs/config.md` and `docs/passing_data.md`:

```bash
tail -f /dev/null | docker exec -i -w /workspace emhass-multi-batt-tests-vscode uv run sphinx-build -b html docs docs/_build
```

Run full suite before final claim:

```bash
tail -f /dev/null | docker exec -i -w /workspace emhass-multi-batt-tests-vscode uv run pytest tests/ -q --durations=10
```

Clean generated runtime artifact if present:

```bash
rm -f /home/coder/git/emhass-multi-batt/data/last_run.json
```

## Commit Guidance

Commit only after local verification and review:

```bash
git -C /home/coder/git/emhass-multi-batt add docs/plans/2026-07-03-step-3-nested-runtime-merge.md src/emhass/inverter_blocks.py src/emhass/utils.py src/emhass/command_line.py src/emhass/web_server.py src/emhass/static/data/runtime_params.json src/emhass/static/openapi.json scripts/generate_openapi.py docs/config.md docs/passing_data.md multi-batt.md tests/test_hybrid_inverter_config.py tests/test_utils.py tests/test_command_line_utils.py tests/test_web_server.py tests/test_runtime_params.py tests/test_openapi.py tests/test_schema_contract.py
git -C /home/coder/git/emhass-multi-batt commit -m "feat: merge indexed inverter runtime params"
```

Use the configured Git identity. Do not include `docs/superpowers` artifacts.

## Acceptance Criteria

Step 3 is ready for review when:

- Flat runtime payloads still behave exactly as before.
- `hybrid_inverter_config_0` runtime payloads hard-fail.
- Runtime nested blocks without matching static blocks hard-fail.
- Nested site-level, secret, unknown, and PV forecast/source keys hard-fail.
- Nested scalar cap overrides update only the matching configured block.
- Nested SOC runtime values are stored outside static config and exposed in nested `passed_data`.
- Static parsed block state is rebuilt after runtime merge.
- Public action path validates nested runtime and then raises `multi-block solve not enabled` before external setup.
- Optimizer-level Step 2 guard remains intact.
- Runtime payload logs redact flat and nested secret values.
- `runtime_params.json`, OpenAPI, and docs describe dynamic nested runtime syntax without numbered defaults or duplicated config keys.
- No Step 4+ PV acquisition, Step 5+ optimization variables, Step 9 result columns, or Step 10 publisher changes are present.
