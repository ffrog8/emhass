# Step 1 Plan: Block 0 Battery and Hybrid Internals Extraction

## Purpose

Step 1 is a behaviour-preserving refactor. It extracts the existing
single-inverter battery and hybrid-inverter internals into one internal block 0
representation while keeping all public behaviour unchanged.

External contract for this step:

- Existing flat configuration remains the only supported configuration shape.
- Existing flat runtime payloads remain the only supported runtime shape.
- Existing result columns remain unchanged.
- Existing Home Assistant publish names remain unchanged.
- No `hybrid_inverter_config_N` parsing, validation, runtime merge, output
  suffixing, or publisher behaviour is introduced.

## Agent Process

Three orthogonal planning agents reviewed the Step 1 scope:

- Optimiser internals: battery variables, hybrid variables, constraints, result
  extraction, and solver-state risks.
- Runtime/config/cache: command-line, REST, cache, and publisher boundaries.
- Testing/compatibility: TDD order, narrow test scope, and Docker verification.

Two agents then audited the synthesized plan. Their corrections are incorporated
below:

- Prefer no `command_line.py` edits; stale wrapper state must be handled inside
  `Optimization`.
- Do not rename CVXPY variables or legacy `self.vars[...]` keys.
- Prefer read-only config references/properties over copied scalar config values.
- Treat `InverterBlockResults` as optional and likely deferred.
- Account for lazy variables created during hybrid constraint and stress setup.
- If adding a new internal test, write it before the implementation and keep it
  narrow.

## Scope

Touch points expected in Step 1:

- `src/emhass/inverter_blocks.py`: new internal dataclass module.
- `src/emhass/optimization.py`: internal routing only.
- `tests/test_optimization.py`: optional narrow internal tests if a real new
  internal contract is created.
- `tests/test_command_line_utils.py`: optional narrow cache-hit extension only
  if block runtime wrappers can otherwise go stale.

Touch points to avoid:

- `src/emhass/command_line.py`, unless there is no other way to refresh stale
  block runtime state. A required command-line change is a design warning.
- `src/emhass/utils.py`.
- Web action payload parsing.
- Publisher code.
- Config/runtime/schema docs.
- Result schema docs.

## Non-goals

Do not implement in Step 1:

- `hybrid_inverter_config_1` or any indexed config parsing.
- Nested runtime payloads.
- Block-local PV acquisition.
- Multi-block battery variables.
- `battery_mode_lock`.
- Suffix or total result columns.
- HA publisher suffixing.
- Command bridge behaviour.
- User-facing docs/schema changes.

## Design Decisions

Use internal `InverterBlock*` names rather than temporary `SingleBlock*` names.
`multi-batt.md` allows equivalent names, and the final design vocabulary is
indexed inverter blocks. Step 1 still creates exactly one block with index `0`.

Add `src/emhass/inverter_blocks.py` as a dependency-light internal module. It
should contain dataclasses only, with no parser, no cache ownership, no runtime
payload handling, and no publishing logic.

Keep all legacy aliases alive:

- Existing `self.param_*` attributes remain available.
- Existing `self.vars[...]` keys remain available.
- CVXPY variable names such as `p_sto_pos`, `p_sto_neg`,
  `p_hybrid_inverter`, `p_dc_ac`, and `p_ac_dc` remain unchanged.
- Result columns such as `P_batt`, `SOC_opt`, and `P_hybrid_inverter` remain
  unchanged.

Block wrappers must reference the existing objects or be rebuilt by
`Optimization` when those objects are recreated. They must not become a second
source of truth.

## Proposed Internal Objects

`InverterBlockConfig`

- Represents block index `0`.
- Reads from existing flat `optim_conf` and `plant_conf`.
- Prefer read-only properties or references to config dictionaries over copied
  scalar values where cache-hit mutation can occur.
- Contains no indexed config parsing.

`InverterBlockRuntime`

- References current block 0 runtime parameters such as `soc_init`,
  `soc_final`, SOC recovery parameters, `soc_target_floor`, and battery
  charge/discharge power caps.
- Must be refreshed or rebuilt inside `Optimization` after horizon resize,
  SOC parameter recreation, and battery power-limit updates.

`InverterBlockVariables`

- References existing CVXPY variables for block 0.
- May be incomplete immediately after `_initialize_decision_variables`, because
  hybrid internals such as `p_dc_ac`, `p_ac_dc`, and `is_dc_sourcing` are
  created in `_add_hybrid_inverter_constraints`.
- Stress variables are also lazy and should not be assumed to exist before
  problem build.

`InverterBlockResults`

- Optional and likely deferred.
- Only add it if it removes real coupling without changing result extraction.
- If added, it may emit only legacy block 0 columns in the existing order.

## Implementation Sequence

1. Baseline guard

   Run the Step 0 targeted optimizer, command-line, and web compatibility tests
   before editing. These tests must be unchanged and passing before the refactor.

2. TDD decision

   Choose one path before adding production code:

   - Preferred: add no new tests and rely on Step 0 golden/characterization
     tests.
   - Alternative: write one narrow failing internal test first, usually failing
     due to a missing block dataclass or missing block 0 attribute.

   Do not modify Step 0 tests. If a Step 0 test needs a changed expectation,
   stop and treat that as a behaviour regression.

3. Add the internal dataclass module

   Create `src/emhass/inverter_blocks.py` with a short file header documenting
   the compatibility invariant: Step 1 exposes one internal block, index `0`,
   backed by the legacy flat config/runtime/variable objects.

4. Build block 0 config in `Optimization`

   In `Optimization.__init__`, derive exactly one block config from existing
   flat `optim_conf` and `plant_conf`.

   Enforce internally that the block collection contains exactly one block with
   index `0`. Do not read or validate `hybrid_inverter_config_N`.

5. Build and refresh block runtime inside `Optimization`

   Add an `Optimization` helper that builds or refreshes
   `self.inverter_block_runtime[0]`.

   Call it after existing parameter initialization and after any path that
   recreates or updates block 0 runtime parameters, including:

   - SOC target parameter initialization/resizing.
   - SOC recovery parameter initialization/resizing.
   - `update_battery_power_limits`.
   - relaxed fallback rebuild paths if they recreate relevant objects.

6. Populate block 0 variables without renaming legacy variables

   During `_initialize_decision_variables`, populate
   `self.inverter_block_variables[0]` with references to the existing variables.

   Preserve all existing `self.vars[...]` keys and CVXPY variable names.

   Add or update block variable references after `_add_hybrid_inverter_constraints`
   creates hybrid internals.

7. Route battery internals through block 0 locals

   Where it reduces coupling, route battery objective terms and
   `_add_battery_constraints` through block 0 config/runtime/variables.

   Keep equations, signs, bounds, SOC recovery behaviour, dynamic battery
   behaviour, and no-grid-charge/no-discharge topology branches unchanged.

8. Route hybrid internals through block 0 locals

   Route `_add_hybrid_inverter_constraints` through block 0 variables for
   `p_dc_ac`, `p_ac_dc`, `is_dc_sourcing`, and `P_hybrid_inverter`.

   Keep existing AC/DC limits, curtailment handling, efficiency equations,
   binary source/sink logic, and inverter stress behaviour unchanged.

9. Keep site balance and result schema stable

   Keep `_add_main_power_balance_constraints` mathematically identical for both
   non-hybrid and hybrid paths.

   Prefer leaving `_build_results_dataframe` mostly unchanged. If result
   extraction is touched, preserve exact legacy column names, order, signs,
   units, and absence of `_0`, `_1`, and `_total` columns.

10. Avoid command-line/cache-key changes

   Do not change `OptimizationCacheKey`.

   Do not add block count, block index, nested config, or runtime fields to the
   cache key in Step 1.

   Existing cache-hit calls should remain sufficient. If stale block references
   appear, fix the refresh ownership inside `Optimization`, not in
   `command_line.py`.

## Narrow Test Policy

Default: add no new public behaviour tests.

Existing Step 0 tests already freeze:

- Single-inverter complete output.
- Flat REST/runtime payload behaviour.
- Legacy HA publish names.
- `P_batt`, `SOC_opt`, and `P_grid` signs/units.
- Existing no-grid-charge/no-discharge behaviour.
- Cache-hit battery cap updates.

Acceptable optional internal tests:

- Exactly one internal block exists and its index is `0`.
- One representative battery value and one representative hybrid flag read from
  the existing flat config into block 0.
- One to three critical alias identity checks prove block references point at
  the same objects as legacy `self.param_*` or `self.vars[...]` entries.
- If result extraction is touched, an existing golden should continue to prove
  no suffixed or total columns appear.

Reject Step 1 tests for:

- `hybrid_inverter_config_1`.
- Nested runtime payloads.
- Indexed config validation.
- `_total` result columns.
- `P_batt_1`, `SOC_opt_1`, or suffixed publish names.
- Command bridge behaviour.
- Site battery mode lock.
- Multi-block PV modes.
- Per-block deferrables.

## Docker Verification Plan

Use container execution, not host installs. Docker bind mounts must use the host
path:

```text
/mnt/ssd/docker/apps/emhass-multi-batt:/workspace
```

Helper container setup:

```bash
tail -f /dev/null | docker run -d --name emhass-step1-tests --log-driver json-file --log-opt max-size=20m --log-opt max-file=5 -e PYTHONDONTWRITEBYTECODE=1 -e UV_PROJECT_ENVIRONMENT=/tmp/emhass-venv -v /mnt/ssd/docker/apps/emhass-multi-batt:/workspace -w /workspace ghcr.io/astral-sh/uv:python3.11-bookworm tail -f /dev/null
```

Dependency setup inside the helper container:

```bash
tail -f /dev/null | docker exec -i emhass-step1-tests uv sync --extra test
```

Baseline and targeted checks should use `uv run pytest ...` inside the helper
container.

Targeted optimizer guard:

```bash
tail -f /dev/null | docker exec -i emhass-step1-tests uv run pytest tests/test_optimization.py::TestOptimization::test_single_inverter_no_extra_block_matches_complete_output_golden tests/test_optimization.py::TestOptimization::test_default_single_inverter_no_extra_block_matches_complete_output_golden tests/test_optimization.py::TestOptimization::test_legacy_battery_result_signs_units_and_grid_balance tests/test_optimization.py::TestOptimization::test_legacy_grid_charge_and_discharge_flags_block_only_forbidden_paths tests/test_optimization.py::TestOptimization::test_legacy_hybrid_grid_charge_and_discharge_flags_block_forbidden_paths tests/test_optimization.py::TestOptimization::test_inverter_stress_cost_discharge_spread tests/test_optimization.py::TestOptimization::test_nodischarge_to_grid_ac_coupled_feasible_issue936 tests/test_optimization.py::TestOptimization::test_nodischarge_to_grid_hybrid_still_blocks_discharge_issue936 -q
```

Targeted command-line/web guard:

```bash
tail -f /dev/null | docker exec -i emhass-step1-tests uv run pytest tests/test_command_line_utils.py::TestCommandLineAsyncUtils::test_naive_mpc_flat_runtime_payload_preserves_scalar_battery_inputs tests/test_command_line_utils.py::TestCommandLineAsyncUtils::test_naive_mpc_flat_runtime_payload_matches_complete_output_golden tests/test_command_line_utils.py::TestCommandLineAsyncUtils::test_default_publish_descriptors_keep_legacy_single_inverter_names tests/test_command_line_utils.py::TestCommandLineAsyncUtils::test_publish_data_uses_legacy_single_inverter_entity_pairs tests/test_command_line_utils.py::TestOptimizationCacheIntegration::test_cache_hit_updates_battery_power_limit_parameters tests/test_web_server.py::TestWebServer::test_action_naive_mpc_preserves_flat_runtime_payload -q
```

Relevant-file regression:

```bash
tail -f /dev/null | docker exec -i emhass-step1-tests uv run pytest tests/test_optimization.py tests/test_command_line_utils.py tests/test_web_server.py -q
```

Final suite:

```bash
tail -f /dev/null | docker exec -i emhass-step1-tests uv run pytest tests/
```

`ruff` may be used as an additional lint check only if it is available through
the repo dependency environment. It does not replace optimizer verification.

## Acceptance Criteria

Step 1 is complete only when:

- `Optimization` exposes exactly one internal block with index `0`.
- Block references point at the same CVXPY objects used by legacy
  `self.param_*` and `self.vars[...]` aliases, or are rebuilt before use.
- Existing CVXPY variable names are unchanged.
- Existing result columns and HA publish names are unchanged.
- Step 0 compatibility tests pass unchanged.
- `pytest tests/` passes in Docker.
- No extra-block config, runtime, output, publisher, or command bridge behaviour
  is introduced.
- `OptimizationCacheKey` remains unchanged.
- Cache-hit runtime battery cap updates remain correct.

## Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| Block runtime holds stale parameter references after cache hits or horizon resize | Refresh/rebuild wrappers inside `Optimization` after parameter mutation/recreation |
| Hybrid internals are missing from block variables because they are created late | Update block variable references inside or immediately after `_add_hybrid_inverter_constraints` |
| Result schema drifts due to eager result abstraction | Defer `InverterBlockResults` unless required; keep `_build_results_dataframe` mostly unchanged |
| Tests become brittle by asserting every private CVXPY object | Limit identity checks to one to three critical aliases |
| Refactor accidentally changes topology/no-grid maths | Run targeted battery, hybrid, AC-coupled, and issue936 tests plus full suite |
| Scope drifts into Step 2+ | Reject any change involving indexed config, nested runtime, suffix columns, totals, or publisher suffixing |

## Rollback

If Step 0 goldens fail and the failure is not a clear test harness problem,
revert the Step 1 refactor and keep the Step 0 freeze commit intact. Do not
update golden expectations to match refactor output without an external review
decision that the public behaviour change is intentional.
