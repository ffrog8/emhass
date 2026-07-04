# Step 5 Per-Block Battery Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an internal, private-gated multi-block battery model with per-block charge/discharge variables and SOC constraints, while keeping public multi-block solving disabled until Step 6.

**Architecture:** Keep the public command-line, REST, cache, result schema, and publisher surfaces unchanged. `Optimization` gets a private constructor-only gate for direct internal tests; public code paths must not pass it. Block `0` keeps the existing variable names, result columns, signs, units, and SOC recovery behaviour. Extra blocks get suffixed internal CVXPY variables, per-block SOC math, and private diagnostics only.

**Tech Stack:** Python `>=3.10,<3.13`, CVXPY, pandas/numpy, EMHASS parsed `InverterBlockConfig` wrappers, pytest, ruff. Local verification uses the existing `emhass-multi-batt-tests-vscode` helper container.

---

## Context And Rationale

Steps 2-4 established the public config/runtime shape and still gate public
multi-block solving with `MULTI_BLOCK_SOLVE_DISABLED_MESSAGE`. Step 5 is the
first optimizer-internal slice: it proves that each configured battery block can
have independent power variables, capacity, SOC state, and charge/discharge
limits.

This step must stay reviewable. It should not attempt to implement the complete
hybrid inverter/site topology. Step 6 owns the site charge/discharge lock, Step
7 owns block-indexed hybrid inverter variables, Step 8 owns the full site
balance/topology reconnection, Step 9 owns stable result columns, and Step 10
owns publisher/command bridge documentation.

## Agent Inputs And Resolved Decisions

Three planning agents reviewed orthogonal slices:

- Optimizer architecture: recommended a private constructor gate, suffixed
  extra-block variables, private diagnostics, no public result columns, and no
  hybrid/PV topology in Step 5.
- Test strategy: recommended direct `Optimization` tests in
  `tests/test_optimization.py`, with all new behaviour inspected through
  internal variables/diagnostics and existing public disabled-gate tests kept
  unchanged.
- Docs/schema/tracker scope: recommended no public docs/schema updates by
  default, and `multi-batt.md` tracker updates only during implementation with
  real verification evidence.

Resolved decisions:

1. Add a private keyword-only constructor flag named
   `_allow_internal_multi_block_battery_model=False`.
2. Do not add a config key, runtime key, OpenAPI field, or `param_definitions`
   toggle for Step 5.
3. Direct `Optimization(...)` tests may pass the private flag; command-line,
   web, cache, and publisher code must not pass it.
4. Step 5 tests use battery-only extra blocks:
   `set_use_pv: false`, `set_use_battery: true`,
   `inverter_is_hybrid: false`.
5. Keep block `0` result columns unchanged. Do not expose `P_batt_1`,
   `SOC_opt_1`, `P_batt_total`, or `SOC_opt_total` in the result DataFrame.
6. A private diagnostic dictionary may expose arrays for tests:
   per-block `p_sto_pos`, `p_sto_neg`, `p_batt`, `soc`,
   `stored_energy`, and aggregate `p_batt_total`.
7. A minimal internal non-hybrid balance hook may use `p_batt_total` so private
   battery-only solves are physically meaningful. Do not implement hybrid
   AC/DC site supply, topology-specific no-grid rules for extra blocks, or
   public site-balance semantics in Step 5.
8. Each extra battery block gets its own same-block direction binary `E_<N>`.
   This prevents one battery from charging and discharging at the same timestep.
   It is not the Step 6 site-wide `battery_mode_lock: site`.

## In Scope

- Private internal optimizer gate for Step 5 direct tests.
- Extra-block battery CVXPY parameters:
  - `soc_init_<N>`
  - `soc_final_<N>`
  - `soc_target_floor_<N>`
  - `battery_charge_power_max_<N>`
  - `battery_discharge_power_max_<N>`
- Extra-block battery CVXPY variables:
  - `p_sto_pos_<N>` for discharge, non-negative
  - `p_sto_neg_<N>` for charge, non-positive
  - `E_<N>` for same-block charge/discharge direction
- Per-block SOC evolution using current EMHASS sign/efficiency semantics.
- Per-block SOC min/max bounds.
- Per-block final SOC equality.
- Optional per-block intermediate `soc_target` support only when already
  present in nested runtime state.
- Private diagnostics for focused tests.
- Focused tests for one extra battery, battery 62-style 2x capacity with same
  charge cap, full-block charge blocking, min-SOC discharge blocking, and no
  fleet-power borrowing.
- Focused tests proving extra blocks do not charge and discharge within the
  same block at the same timestep.
- Legacy and public disabled-gate regression tests.

## Out Of Scope

- Public multi-block solve enablement.
- `battery_mode_lock: site`.
- Mixed charge/discharge prevention across blocks.
- Hybrid inverter per-block variables: `p_dc_ac_i`, `p_ac_dc_i`,
  `is_dc_sourcing_i`, `P_hybrid_inverter_i`.
- Per-block PV optimizer variables or curtailment constraints.
- Full site topology reconnection for `set_nocharge_from_grid`,
  `set_nodischarge_to_grid`, import/export limits, or hybrid AC/DC paths.
- Public result columns: `P_batt_1`, `SOC_opt_1`, `P_batt_total`,
  `SOC_opt_total`.
- Publisher suffixes, HA entity changes, command bridge examples.
- Runtime/OpenAPI/schema changes.
- Changes to legacy golden expected output.

## Files

Modify during implementation:

- `src/emhass/inverter_blocks.py`
- `src/emhass/optimization.py`
- `tests/test_optimization.py`

Modify only if a focused gate regression requires it:

- `tests/test_command_line_utils.py`

Update only during implementation status changes:

- `multi-batt.md`

Do not modify for Step 5 unless a blocker is discovered and reviewed:

- `src/emhass/command_line.py`
- `src/emhass/web_server.py`
- `src/emhass/forecast.py`
- publisher code
- result schema code
- `docs/config.md`
- `docs/passing_data.md`
- `docs/plan_output_schema.md`
- `docs/publish_data.md`
- `src/emhass/static/data/runtime_params.json`
- `src/emhass/static/openapi.json`
- `scripts/generate_openapi.py`
- `src/emhass/static/data/param_definitions.json`
- `src/emhass/data/config_defaults.json`
- `src/emhass/data/associations.csv`

## Verification Environment

Run commands inside the existing helper container with the mandatory keepalive
wrapper:

```bash
tail -f /dev/null | docker exec -i -w /workspace emhass-multi-batt-tests-vscode <inner command>
```

External reviewers without that container should run the same inner command in
the repository's documented Python environment, for example:

```bash
uv run pytest tests/test_optimization.py -q
```

## Runtime And Optimizer Contract

Public runtime/config behaviour is unchanged. Public paths with extra
`hybrid_inverter_config_N` blocks continue to validate input and then raise:

```text
multi-block solve not enabled
```

Only direct internal tests may construct:

```python
Optimization(
    retrieve_hass_conf,
    optim_conf,
    plant_conf,
    var_load_cost,
    var_prod_price,
    costfun,
    emhass_conf,
    logger,
    _allow_internal_multi_block_battery_model=True,
)
```

The private flag must not be accepted through YAML, REST runtime payloads,
OpenAPI, Home Assistant add-on config, or command-line entry points.

Block `0` remains the existing battery block:

- variable names: `p_sto_pos`, `p_sto_neg`
- result columns: `P_batt`, `SOC_opt`
- sign: `P_batt > 0` means discharge, `P_batt < 0` means charge
- SOC unit: fraction `0..1`
- SOC recovery binaries: unchanged

Extra blocks use internal names only:

- `p_sto_pos_1`, `p_sto_neg_1`
- `p_sto_pos_2`, `p_sto_neg_2`
- `E_1`, `E_2`

Private diagnostics after solve should be internal-only, for example:

```python
opt._battery_block_diagnostics == {
    "blocks": {
        0: {
            "p_sto_pos": array,
            "p_sto_neg": array,
            "p_batt": array,
            "soc": array,
            "stored_energy": array,
        },
        1: {
            "p_sto_pos": array,
            "p_sto_neg": array,
            "p_batt": array,
            "soc": array,
            "stored_energy": array,
        },
    },
    "p_batt_total": array,
}
```

Do not serialize this object, publish it, or document it as a public API.

## Implementation Tasks

### Task 0: Mark Step 5 Implementation Start

**Files:**

- Modify: `multi-batt.md`

- [ ] **Step 1: Update the tracker row**

Change Step 5 from `Not started` to `In progress`. Keep the evidence field
honest:

```markdown
Implementation started; local verification pending.
```

- [ ] **Step 2: Verify only the tracker changed**

Run:

```bash
git -C /home/coder/git/emhass-multi-batt diff -- multi-batt.md
git -C /home/coder/git/emhass-multi-batt diff --check
```

Expected: Step 5 row changed; whitespace check passes.

### Task 1: Add Red Tests And Local Helpers

**Files:**

- Modify: `tests/test_optimization.py`

- [ ] **Step 1: Add deterministic Step 5 helper methods**

Add helpers near the existing `TestOptimization` helper methods:

```python
def _make_multi_block_battery_df(self, periods=2):
    dates = pd.date_range(
        start=pd.Timestamp("2024-01-01 00:00:00", tz=self.retrieve_hass_conf["time_zone"]),
        periods=periods,
        freq=self.retrieve_hass_conf["optimization_time_step"],
    )
    df = pd.DataFrame(index=dates)
    df["p_pv_forecast"] = 0.0
    df["p_load_forecast"] = 0.0
    df["unit_load_cost"] = 0.25
    df["unit_prod_price"] = 0.05
    return df

def _battery_only_confs(self):
    optim_conf = copy.deepcopy(self.optim_conf)
    plant_conf = copy.deepcopy(self.plant_conf)
    optim_conf.update(
        {
            "set_use_pv": False,
            "set_use_battery": True,
            "number_of_deferrable_loads": 0,
            "set_nocharge_from_grid": False,
            "set_nodischarge_to_grid": False,
            "set_battery_dynamic": False,
            "set_battery_first_priority": False,
        }
    )
    plant_conf.update(
        {
            "inverter_is_hybrid": False,
            "compute_curtailment": False,
            "battery_discharge_efficiency": 1.0,
            "battery_charge_efficiency": 1.0,
            "battery_minimum_state_of_charge": 0.0,
            "battery_maximum_state_of_charge": 1.0,
            "battery_target_state_of_charge": 0.0,
            "battery_nominal_energy_capacity": 1000,
            "battery_charge_power_max": 1000,
            "battery_discharge_power_max": 1000,
        }
    )
    return optim_conf, plant_conf

def _extra_battery_block(
    self,
    *,
    capacity=1000,
    charge_power=1000,
    discharge_power=1000,
    soc_min=0.0,
    soc_max=1.0,
    soc_target=0.0,
):
    return {
        "set_use_pv": False,
        "set_use_battery": True,
        "inverter_is_hybrid": False,
        "compute_curtailment": False,
        "battery_discharge_power_max": discharge_power,
        "battery_charge_power_max": charge_power,
        "battery_discharge_efficiency": 1.0,
        "battery_charge_efficiency": 1.0,
        "battery_nominal_energy_capacity": capacity,
        "battery_minimum_state_of_charge": soc_min,
        "battery_maximum_state_of_charge": soc_max,
        "battery_target_state_of_charge": soc_target,
        "inverter_ac_output_max": 1000,
        "inverter_ac_input_max": 1000,
        "inverter_efficiency_dc_ac": 1.0,
        "inverter_efficiency_ac_dc": 1.0,
    }

def _block_power(self, opt, index):
    diagnostics = opt._battery_block_diagnostics
    return diagnostics["blocks"][index]["p_batt"]

def _block_discharge(self, opt, index):
    diagnostics = opt._battery_block_diagnostics
    return diagnostics["blocks"][index]["p_sto_pos"]

def _block_charge(self, opt, index):
    diagnostics = opt._battery_block_diagnostics
    return diagnostics["blocks"][index]["p_sto_neg"]
```

If current helper style makes these names awkward, keep the same semantics and
keep them local to `tests/test_optimization.py`.

- [ ] **Step 2: Add the private-gate test**

Add:

```python
def test_internal_multi_block_battery_model_requires_private_flag(self):
    optim_conf, plant_conf = self._battery_only_confs()
    parse_inverter_block_configs(
        {"hybrid_inverter_config_1": self._extra_battery_block()},
        optim_conf,
        plant_conf,
    )

    with self.assertRaisesRegex(NotImplementedError, MULTI_BLOCK_SOLVE_DISABLED_MESSAGE):
        self.create_optimization(optim_conf=optim_conf, plant_conf=plant_conf)

    opt = self.create_optimization(
        optim_conf=optim_conf,
        plant_conf=plant_conf,
        _allow_internal_multi_block_battery_model=True,
    )

    self.assertEqual(sorted(opt.inverter_block_config), [0, 1])
```

Expected before implementation: fail with `TypeError` for unexpected private
constructor argument, or still raise `NotImplementedError`.

- [ ] **Step 3: Add the extra variable construction test**

Add:

```python
def test_internal_multi_block_battery_model_creates_independent_block_variables(self):
    optim_conf, plant_conf = self._battery_only_confs()
    parse_inverter_block_configs(
        {"hybrid_inverter_config_1": self._extra_battery_block()},
        optim_conf,
        plant_conf,
    )

    opt = self.create_optimization(
        optim_conf=optim_conf,
        plant_conf=plant_conf,
        _allow_internal_multi_block_battery_model=True,
    )

    self.assertEqual(sorted(opt.inverter_block_variables), [0, 1])
    self.assertIs(opt.inverter_block_variables[0].p_sto_pos, opt.vars["p_sto_pos"])
    self.assertIs(opt.inverter_block_variables[0].p_sto_neg, opt.vars["p_sto_neg"])
    self.assertIs(opt.inverter_block_variables[1].p_sto_pos, opt.vars["p_sto_pos_1"])
    self.assertIs(opt.inverter_block_variables[1].p_sto_neg, opt.vars["p_sto_neg_1"])
    self.assertIs(opt.inverter_block_variables[1].battery_mode, opt.vars["E_1"])
    self.assertIsNot(
        opt.inverter_block_variables[1].p_sto_pos,
        opt.inverter_block_variables[0].p_sto_pos,
    )
```

Expected before implementation: fail because block `1` variables do not exist.

- [ ] **Step 4: Add behavioural red tests**

Add tests with these exact names:

```python
def test_internal_multi_block_one_extra_battery_can_solve(self):
    ...

def test_internal_multi_block_battery_62_double_capacity_uses_own_charge_cap_each_timestep(self):
    ...

def test_internal_multi_block_full_block_cannot_charge_while_extra_block_charges(self):
    ...

def test_internal_multi_block_min_soc_block_cannot_discharge_while_extra_block_discharges(self):
    ...
```

Each test must assert internal diagnostics, not public result columns. The
`battery_62` test should use contiguous block `1`; the name documents the real
site scenario, not a config index.

- [ ] **Step 5: Run the red tests**

Run:

```bash
tail -f /dev/null | docker exec -i -w /workspace emhass-multi-batt-tests-vscode uv run pytest tests/test_optimization.py::TestOptimization::test_internal_multi_block_battery_model_requires_private_flag tests/test_optimization.py::TestOptimization::test_internal_multi_block_battery_model_creates_independent_block_variables -q
```

Expected before implementation: fail for the missing private gate and missing
extra-block variables.

### Task 2: Add The Private Internal Optimizer Gate

**Files:**

- Modify: `src/emhass/optimization.py`
- Modify: `tests/test_optimization.py`

- [ ] **Step 1: Add a keyword-only private constructor flag**

Update `Optimization.__init__` to accept:

```python
_allow_internal_multi_block_battery_model: bool = False,
```

Store:

```python
self._allow_internal_multi_block_battery_model = _allow_internal_multi_block_battery_model
```

Keep the existing guard, but bypass it only when the private flag is true:

```python
if has_extra_inverter_blocks(self.plant_conf) and not self._allow_internal_multi_block_battery_model:
    raise NotImplementedError(MULTI_BLOCK_SOLVE_DISABLED_MESSAGE)
```

- [ ] **Step 2: Update the test helper to forward the private flag**

In `TestOptimization.create_optimization()`, pass through:

```python
kwargs.get("_allow_internal_multi_block_battery_model", False)
```

Use the keyword name directly when calling `Optimization`.

- [ ] **Step 3: Fail fast for unsupported private-path blocks**

Add an internal validation helper in `Optimization`:

```python
def _validate_internal_multi_block_battery_model_scope(self) -> None:
    ...
```

It should run only when the private flag is true and extra blocks exist. It must
raise `NotImplementedError` for extra blocks that are outside Step 5 scope:

- `set_use_battery` is false
- `set_use_pv` is true
- `inverter_is_hybrid` is true
- `compute_curtailment` is true
- extra-block battery stress settings are enabled
- extra-block `set_battery_dynamic` is true
- extra-block battery dynamic ramp fields are non-default
- extra-block `weight_battery_charge` or `weight_battery_discharge` are
  configured with non-default values
- extra-block SOC penalty settings are configured or enabled:
  `battery_soc_deficit_threshold`, `battery_soc_deficit_cost`,
  `battery_soc_surplus_threshold`, or `battery_soc_surplus_cost`

The error message should name the unsupported block and feature.

- [ ] **Step 4: Run the private-gate test**

Run:

```bash
tail -f /dev/null | docker exec -i -w /workspace emhass-multi-batt-tests-vscode uv run pytest tests/test_optimization.py::TestOptimization::test_internal_multi_block_battery_model_requires_private_flag -q
```

Expected: pass.

### Task 3: Add Extra-Block Runtime Parameters And Variables

**Files:**

- Modify: `src/emhass/inverter_blocks.py`
- Modify: `src/emhass/optimization.py`
- Modify: `tests/test_optimization.py`

- [ ] **Step 1: Extend the dataclasses with optional internal fields**

In `InverterBlockVariables`, add optional fields:

```python
p_batt: Any | None = None
stored_energy: Any | None = None
soc: Any | None = None
battery_mode: Any | None = None
```

Keep existing fields and defaults unchanged.

- [ ] **Step 2: Create extra-block CVXPY parameters**

In `Optimization`, add a helper:

```python
def _init_extra_inverter_block_battery_params(self) -> None:
    self.param_extra_block_battery = {}
    if not self._allow_internal_multi_block_battery_model:
        return
    for index, block in sorted(self.inverter_block_config.items()):
        if index == 0:
            continue
        if not block.set_use_battery:
            continue
        self.param_extra_block_battery[index] = {
            "soc_init": cp.Parameter(nonneg=True, name=f"soc_init_{index}"),
            "soc_final": cp.Parameter(nonneg=True, name=f"soc_final_{index}"),
            "soc_target_floor": cp.Parameter(self.num_timesteps, nonneg=True, name=f"soc_target_floor_{index}"),
            "battery_charge_power_max": cp.Parameter(nonneg=True, name=f"battery_charge_power_max_{index}"),
            "battery_discharge_power_max": cp.Parameter(nonneg=True, name=f"battery_discharge_power_max_{index}"),
        }
        self.param_extra_block_battery[index]["soc_target_floor"].value = np.zeros(
            self.num_timesteps
        )
```

Call it after block config refresh and after horizon resizing. The exact code
may be split into small helpers if that better matches `optimization.py`.

- [ ] **Step 3: Refresh runtime wrappers for extra blocks**

Update `_refresh_inverter_block_runtime()` so private extra blocks get
`InverterBlockRuntime` entries referencing the new parameters. For extra
blocks, SOC recovery fields may be `None` because Step 5 does not copy recovery
binaries beyond block `0`.

- [ ] **Step 4: Create suffixed extra-block battery variables**

In `_initialize_decision_variables()`, after existing block `0` battery
variables are created, add for each private extra battery block:

```python
vars_dict[f"p_sto_pos_{index}"] = cp.Variable(
    n, nonneg=True, name=f"p_sto_pos_{index}"
)
vars_dict[f"p_sto_neg_{index}"] = cp.Variable(
    n, nonpos=True, name=f"p_sto_neg_{index}"
)
vars_dict[f"E_{index}"] = cp.Variable(n, boolean=True, name=f"E_{index}")
```

Add direct charge/discharge cap constraints using the extra-block parameters.
Do not rename or replace block `0` variables.

- [ ] **Step 5: Refresh variable wrappers for extra blocks**

Update `_refresh_inverter_block_variables()` so private extra blocks get
`InverterBlockVariables` entries referencing `p_sto_pos_<N>`,
`p_sto_neg_<N>`, and `E_<N>`.

- [ ] **Step 6: Run the variable construction test**

Run:

```bash
tail -f /dev/null | docker exec -i -w /workspace emhass-multi-batt-tests-vscode uv run pytest tests/test_optimization.py::TestOptimization::test_internal_multi_block_battery_model_creates_independent_block_variables -q
```

Expected: pass.

### Task 4: Add Extra-Block SOC Constraints And Diagnostics

**Files:**

- Modify: `src/emhass/optimization.py`
- Modify: `tests/test_optimization.py`

- [ ] **Step 1: Extract reusable per-block SOC math**

Add a helper that returns expressions without changing block `0` semantics:

```python
def _build_battery_soc_expressions(
    self,
    *,
    block_config,
    block_runtime,
    block_variables,
):
    p_sto_pos = block_variables.p_sto_pos
    p_sto_neg = block_variables.p_sto_neg
    cap = block_config.plant_conf["battery_nominal_energy_capacity"]
    eff_dis = block_config.plant_conf["battery_discharge_efficiency"]
    eff_chg = block_config.plant_conf["battery_charge_efficiency"]
    power_flow = (p_sto_pos * (1 / eff_dis)) + (p_sto_neg * eff_chg)
    energy_change = power_flow * self.time_step
    cumulative_energy = cp.cumsum(energy_change)
    stored_energy = (block_runtime.soc_init * cap) - cumulative_energy
    soc = stored_energy / cap
    p_batt = p_sto_pos + p_sto_neg
    return p_batt, stored_energy, soc
```

If this extraction would make the diff larger than a direct extra-block helper,
keep block `0` code unchanged and add the helper only for extra blocks.

- [ ] **Step 2: Add extra-block SOC constraints**

In `_add_battery_constraints()`, preserve the existing block `0` path. Then add
a small private extra-block loop:

```python
for index, block_config in self._extra_battery_block_configs():
    block_runtime = self.inverter_block_runtime[index]
    block_variables = self.inverter_block_variables[index]
    p_batt, stored_energy, soc = self._build_battery_soc_expressions(
        block_config=block_config,
        block_runtime=block_runtime,
        block_variables=block_variables,
    )
    cap = block_config.plant_conf["battery_nominal_energy_capacity"]
    min_energy = block_config.plant_conf["battery_minimum_state_of_charge"] * cap
    max_energy = block_config.plant_conf["battery_maximum_state_of_charge"] * cap
    eff_dis = block_config.plant_conf["battery_discharge_efficiency"]
    eff_chg = block_config.plant_conf["battery_charge_efficiency"]
    constraints.append(
        block_variables.p_sto_pos
        <= eff_dis * block_runtime.battery_discharge_power_max * block_variables.battery_mode
    )
    constraints.append(
        block_variables.p_sto_neg
        >= -(1 / eff_chg)
        * block_runtime.battery_charge_power_max
        * (1 - block_variables.battery_mode)
    )
    constraints.append(stored_energy >= min_energy)
    constraints.append(stored_energy <= max_energy)
    constraints.append(stored_energy[-1] == block_runtime.soc_final * cap)
    constraints.append(stored_energy >= block_runtime.soc_target_floor)
    ...
```

Store expressions on the block variable wrapper or a private expression mapping
so diagnostics can be built after solve.

- [ ] **Step 3: Set extra-block runtime parameter values in `perform_optimization()`**

For each private extra block, derive:

- `soc_init`: nested runtime `soc_init`, else block target SOC
- `soc_final`: nested runtime `soc_final`, else `soc_init`
- `battery_charge_power_max`: nested runtime scalar override if present, else
  block plant config
- `battery_discharge_power_max`: nested runtime scalar override if present, else
  block plant config
- `soc_target_floor`: a stored-energy Wh vector. It is all zeros unless nested
  `soc_target` is present; when present, set the target timestep to
  `soc_target * cap`, matching the existing block `0` semantics.

Validate values are already parsed by Step 3; do not add public recovery
behaviour for extra blocks in Step 5.

- [ ] **Step 4: Build private diagnostics after solve**

After extracting solver values, populate:

```python
self._battery_block_diagnostics = {
    "blocks": {
        index: {
            "p_sto_pos": p_sto_pos_array,
            "p_sto_neg": p_sto_neg_array,
            "p_batt": p_batt_array,
            "soc": soc_array,
            "stored_energy": stored_energy_array,
        }
        for index in sorted_block_indexes
    },
    "p_batt_total": p_batt_total_array,
}
```

Do not add these diagnostics to the returned DataFrame.

- [ ] **Step 5: Add the minimal non-hybrid internal balance hook**

When the private Step 5 path is active and all extra blocks are non-hybrid
battery-only, use the internal `p_batt_total` expression in the existing
non-hybrid main power balance instead of block `0` battery power alone.

Do not change hybrid balance, no-grid-charge/no-discharge topology rules, or
site import/export semantics beyond this internal test path.

### Task 5: Add Behavioural Battery Tests

**Files:**

- Modify: `tests/test_optimization.py`

- [ ] **Step 1: Add one-extra-battery solve test**

Use `periods=2`, lossless efficiencies, no PV, no load, and a nested runtime
state requiring block `1` to move SOC. Assert:

- solver status is in `VALID_OPTIMAL_STATUSES`
- block `1` diagnostic `p_batt` is nonzero
- block `1` SOC ends at requested final SOC
- block `1` has no timestep where both `p_sto_pos` and `p_sto_neg` are nonzero
- returned DataFrame does not contain `P_batt_1` or `P_batt_total`

- [ ] **Step 2: Add battery 62 no-borrowing test**

Use block `0` capacity `1000 Wh`, block `1` capacity `2000 Wh`, both charge caps
`1000 W`, two 30-minute timesteps, and `soc_init=0.0`, `soc_final=0.5` for both.

Assert:

- block `1` gains `1000 Wh`
- block `1` charge magnitude never exceeds `1000 W`
- block `1` cannot use block `0`'s charge cap
- internal `p_batt_total` equals the sum of block `0` and block `1` power arrays
  within tolerance

- [ ] **Step 3: Add full-block charge blocking test**

Use block `0` min/max/initial/final at maximum SOC and block `1` below target.

Assert:

- block `0` charge component is zero within tolerance
- block `1` charge component is negative in at least one timestep

It is valid to assert each individual block does not charge and discharge in
the same timestep. Do not assert site-wide mixed charge/discharge locking across
different blocks; Step 6 owns that.

- [ ] **Step 4: Add min-SOC discharge blocking test**

Use block `0` min/max/initial/final at minimum SOC and block `1` above target.

Assert:

- block `0` discharge component is zero within tolerance
- block `1` discharge component is positive in at least one timestep
- block `1` has no timestep where both charge and discharge components are
  nonzero

- [ ] **Step 5: Run the focused Step 5 tests**

Run:

```bash
tail -f /dev/null | docker exec -i -w /workspace emhass-multi-batt-tests-vscode uv run pytest tests/test_optimization.py::TestOptimization::test_internal_multi_block_battery_model_requires_private_flag tests/test_optimization.py::TestOptimization::test_internal_multi_block_battery_model_creates_independent_block_variables tests/test_optimization.py::TestOptimization::test_internal_multi_block_one_extra_battery_can_solve tests/test_optimization.py::TestOptimization::test_internal_multi_block_battery_62_double_capacity_uses_own_charge_cap_each_timestep tests/test_optimization.py::TestOptimization::test_internal_multi_block_full_block_cannot_charge_while_extra_block_charges tests/test_optimization.py::TestOptimization::test_internal_multi_block_min_soc_block_cannot_discharge_while_extra_block_discharges -q --durations=10
```

Expected: all Step 5 tests pass.

### Task 6: Preserve Public Gates And Legacy Behaviour

**Files:**

- Modify only if a focused regression proves it necessary:
  `tests/test_command_line_utils.py`

- [ ] **Step 1: Run public gate tests**

Run:

```bash
tail -f /dev/null | docker exec -i -w /workspace emhass-multi-batt-tests-vscode uv run pytest tests/test_optimization.py::TestOptimization::test_extra_hybrid_block_rejected_before_optimizer_setup tests/test_command_line_utils.py::TestCommandLineAsyncUtils::test_valid_extra_hybrid_block_merges_runtime_then_reaches_disabled_multi_block_gate tests/test_command_line_utils.py::TestCommandLineAsyncUtils::test_split_pv_nested_pv_forecast_validates_then_reaches_disabled_multi_block_gate -q --durations=10
```

Expected: pass. Public paths still reach `multi-block solve not enabled`.

- [ ] **Step 2: Run legacy golden guard tests**

Run:

```bash
tail -f /dev/null | docker exec -i -w /workspace emhass-multi-batt-tests-vscode uv run pytest tests/test_optimization.py::TestOptimization::test_internal_inverter_block_zero_wraps_legacy_flat_state tests/test_optimization.py::TestOptimization::test_single_inverter_no_extra_block_matches_complete_output_golden tests/test_optimization.py::TestOptimization::test_default_single_inverter_no_extra_block_matches_complete_output_golden tests/test_optimization.py::TestOptimization::test_legacy_battery_result_signs_units_and_grid_balance tests/test_optimization.py::TestOptimization::test_legacy_grid_charge_and_discharge_flags_block_only_forbidden_paths tests/test_optimization.py::TestOptimization::test_legacy_hybrid_grid_charge_and_discharge_flags_block_forbidden_paths -q --durations=10
```

Expected: pass with no changed expected DataFrames.

- [ ] **Step 3: Run lint and diff checks**

Run:

```bash
tail -f /dev/null | docker exec -i -w /workspace emhass-multi-batt-tests-vscode uv run ruff check src/emhass/inverter_blocks.py src/emhass/optimization.py tests/test_optimization.py tests/test_command_line_utils.py
git -C /home/coder/git/emhass-multi-batt diff --check
```

Expected: pass.

- [ ] **Step 4: Confirm no public docs/schema drift**

Run:

```bash
git -C /home/coder/git/emhass-multi-batt diff -- docs/config.md docs/passing_data.md docs/plan_output_schema.md docs/publish_data.md src/emhass/static/data/runtime_params.json src/emhass/static/openapi.json scripts/generate_openapi.py
```

Expected: no output unless a documented blocker was reviewed and accepted.

### Task 7: Review, Tracker, And Completion Evidence

**Files:**

- Modify: `multi-batt.md`

- [ ] **Step 1: Request two independent audits**

Have two agents independently review:

- Step 5 plan alignment
- private gate not exposed publicly
- tests remain Step 5-scoped
- no public result/schema/publisher drift
- legacy tests still pass
- no broad optimizer rewrite

They must inspect diffs and verification output, not rely on summaries.

- [ ] **Step 2: Resolve audit findings**

Fix any Critical or Important findings before marking Step 5 `Review`.
Challenge only findings that are demonstrably outside Step 5 or contradicted by
code/tests.

- [ ] **Step 3: Update tracker to `Review`**

Update Step 5 in `multi-batt.md` with:

- changed files summary
- public behaviour: still internal/private-gated only
- exact local verification counts
- audit outcome
- external CI status

Do not mark Step 5 `Done` until the user asks for completion confirmation or
the branch/PR is accepted according to the established tracker rules.

## Required Final Verification Set

Before claiming Step 5 implementation is complete, run:

```bash
tail -f /dev/null | docker exec -i -w /workspace emhass-multi-batt-tests-vscode uv run pytest tests/test_optimization.py::TestOptimization::test_internal_multi_block_battery_model_requires_private_flag tests/test_optimization.py::TestOptimization::test_internal_multi_block_battery_model_creates_independent_block_variables tests/test_optimization.py::TestOptimization::test_internal_multi_block_one_extra_battery_can_solve tests/test_optimization.py::TestOptimization::test_internal_multi_block_battery_62_double_capacity_uses_own_charge_cap_each_timestep tests/test_optimization.py::TestOptimization::test_internal_multi_block_full_block_cannot_charge_while_extra_block_charges tests/test_optimization.py::TestOptimization::test_internal_multi_block_min_soc_block_cannot_discharge_while_extra_block_discharges tests/test_optimization.py::TestOptimization::test_extra_hybrid_block_rejected_before_optimizer_setup tests/test_command_line_utils.py::TestCommandLineAsyncUtils::test_valid_extra_hybrid_block_merges_runtime_then_reaches_disabled_multi_block_gate tests/test_command_line_utils.py::TestCommandLineAsyncUtils::test_split_pv_nested_pv_forecast_validates_then_reaches_disabled_multi_block_gate tests/test_optimization.py::TestOptimization::test_internal_inverter_block_zero_wraps_legacy_flat_state tests/test_optimization.py::TestOptimization::test_single_inverter_no_extra_block_matches_complete_output_golden tests/test_optimization.py::TestOptimization::test_default_single_inverter_no_extra_block_matches_complete_output_golden tests/test_optimization.py::TestOptimization::test_legacy_battery_result_signs_units_and_grid_balance tests/test_optimization.py::TestOptimization::test_legacy_grid_charge_and_discharge_flags_block_only_forbidden_paths tests/test_optimization.py::TestOptimization::test_legacy_hybrid_grid_charge_and_discharge_flags_block_forbidden_paths -q --durations=10
```

```bash
tail -f /dev/null | docker exec -i -w /workspace emhass-multi-batt-tests-vscode uv run ruff check src/emhass/inverter_blocks.py src/emhass/optimization.py tests/test_optimization.py tests/test_command_line_utils.py
```

```bash
git -C /home/coder/git/emhass-multi-batt diff --check
```

Report full `pytest tests/` as `DEFERRED` unless it is actually run. External
CI is the validation layer and must be reported separately.
