# EMHASS Multi Hybrid-Inverter Blocks

## Design Position

Use indexed hybrid inverter / battery blocks, not named batteries.

In multi-block mode, root block `0` is not a fleet aggregate. It remains the
first inverter/battery block. Fleet values are exposed only through explicit
`*_total` result columns.

The existing top-level EMHASS configuration is block `0`. Additional inverter
and battery blocks are configured as:

```yaml
hybrid_inverter_config_1:
  # same block-local battery / hybrid inverter / PV parameter names
  # from the documented allowlist

hybrid_inverter_config_2:
  # same block-local battery / hybrid inverter / PV parameter names
  # from the documented allowlist
```

Do not add a primary interface like:

```yaml
battery_names:
  - bat54
  - bat63
  - bat62
```

Do not use object maps keyed by user-defined battery names in the primary
configuration or runtime API.

This is a compatibility-first fork design:

- EMHASS remains one site-level optimiser.
- Block `0` remains exactly the current single-inverter behaviour.
- Existing top-level scalar configuration remains valid.
- Existing REST payloads remain valid.
- Existing Home Assistant entity names remain valid.
- Extra blocks are additive and index-suffixed.
- `hybrid_inverter_config_0` is invalid. Block `0` exists only as the flat
  top-level config/runtime shape.

The command bridge stays outside EMHASS. EMHASS plans; it does not control
inverters directly.

## Runtime Components

| Component | Role | Interaction |
| --- | --- | --- |
| EMHASS fork | Single site optimiser with indexed inverter/battery blocks | Reads one site load/tariff model plus `hybrid_inverter_config_N` blocks |
| HA runtime builder | Reads SOC, BMS limits, inverter availability, forecasts | Posts normal runtime keys for block `0`, nested keys for blocks `1..N` |
| EMHASS REST API | Same endpoints as today | No new endpoint; extend payload shape only |
| Publisher | Publishes existing entities unchanged for block `0`; suffixed entities for extra blocks | `p_batt_forecast`, `p_batt_forecast_1`, `p_hybrid_inverter_1` |
| Command bridge | Applies the first timestep to each inverter | Existing entity drives inverter `0`; suffixed entity drives inverter `N` |
| Inverters/BMS | Enforce physical limits | Feedback updates next runtime caps |

No asynchronous control and no direct inverter command authority should be added
inside EMHASS.

## Compatibility Contract

| Case | Behaviour |
| --- | --- |
| No `hybrid_inverter_config_N` keys | Existing behaviour, same config, same REST payload, same entity names |
| Existing top-level config | Block `0` |
| Extra inverter/battery block | Add `hybrid_inverter_config_1`, then `_2`, etc. |
| Existing HA entity names | Never renamed |
| Existing REST payload | Still valid |
| Existing automations using `sensor.p_batt_forecast` | Continue to address block `0` only |
| New entities | Always suffixed with extra block index |
| User-defined battery/inverter names | Not part of v1 primary interface |
| `hybrid_inverter_config_0` | Invalid; block `0` is the existing flat config/runtime |

New controls must be inert unless extra blocks are configured:

| Control | Default | Legacy effect |
| --- | --- | --- |
| `multi_hybrid_inverter_pv_mode` | unset / legacy | No behaviour change without extra blocks |
| `battery_mode_lock` | current single-battery lock behaviour for legacy; `site` for multi-block | No behaviour change without extra blocks |

Skipped indexes are invalid. This must hard-fail:

```yaml
hybrid_inverter_config_2: {}
```

without:

```yaml
hybrid_inverter_config_1: {}
```

## Configuration Shape

### Existing Single-Inverter Config

The existing single-inverter configuration remains unchanged and represents
block `0`.

```yaml
set_use_pv: true
set_use_battery: true
inverter_is_hybrid: true

sensor_power_photovoltaics: sensor.power_pv_inverter_0
sensor_power_load_no_var_loads: sensor.power_load_no_var_loads

battery_discharge_power_max: 5000
battery_charge_power_max: 4600
battery_discharge_efficiency: 0.95
battery_charge_efficiency: 0.95
battery_nominal_energy_capacity: 13300
battery_minimum_state_of_charge: 0.10
battery_maximum_state_of_charge: 0.95
battery_target_state_of_charge: 0.90
```

### Additional Hybrid Inverter / Battery Blocks

Extra blocks may contain only block-local parameters in v1. The implementation
should encode this as a concrete allowlist using current EMHASS parameter names.
All other keys hard-error.

| Group | Active extra-block config keys in initial v1 | Notes |
| --- | --- | --- |
| Enablement | `set_use_pv`, `set_use_battery`, `inverter_is_hybrid` | Block-local |
| Battery limits/state | `battery_discharge_power_max`, `battery_charge_power_max`, `battery_discharge_efficiency`, `battery_charge_efficiency`, `battery_nominal_energy_capacity`, `battery_minimum_state_of_charge`, `battery_maximum_state_of_charge`, `battery_target_state_of_charge` | Block-local |
| Battery dynamic/weights | `set_battery_dynamic`, `battery_dynamic_max`, `battery_dynamic_min`, `weight_battery_discharge`, `weight_battery_charge` | Block-local in v1; optional site-total mode can be deferred |
| Battery penalties | `battery_stress_cost`, `battery_stress_segments`, `battery_soc_deficit_threshold`, `battery_soc_deficit_cost`, `battery_soc_surplus_threshold`, `battery_soc_surplus_cost` | Block-local because they shape battery behaviour |
| Hybrid inverter | `inverter_ac_output_max`, `inverter_ac_input_max`, `inverter_efficiency_dc_ac`, `inverter_efficiency_ac_dc`, `inverter_stress_cost`, `inverter_stress_segments` | Block-local |
| Curtailment | `compute_curtailment` | Block-local only in `split_pv` |

PV source keys such as `sensor_power_photovoltaics`,
`sensor_power_photovoltaics_forecast`, `pv_module_model`,
`pv_inverter_model`, `surface_tilt`, `surface_azimuth`,
`modules_per_string`, `strings_per_inverter`, `set_use_adjusted_pv`,
`adjusted_pv_regression_model`, `adjusted_pv_solar_elevation_threshold`, and
`adjusted_pv_model_max_age` are reserved for a later block-local acquisition step
unless Step 4 explicitly implements and tests them. Initial v1 extra-block PV
uses runtime `hybrid_inverter_config_N.pv_power_forecast`.

Site-level parameters are not block-local. Extra blocks must reject load sensors
and forecasts, tariffs, grid import/export limits, deferrable loads, connection
settings, global publish settings, optimisation horizon/time settings, topology
flags such as `set_nocharge_from_grid`, `set_nodischarge_to_grid`, and
`set_battery_first_priority`, and site-level economic controls such as
`capacity_cost_per_kw` unless a later design explicitly adds a block-scoped
meaning for them.

```yaml
# Existing top-level config is inverter/battery block 0.

hybrid_inverter_config_1:
  set_use_pv: true
  set_use_battery: true
  inverter_is_hybrid: true

  # Initial v1 supplies extra-block PV at runtime:
  # hybrid_inverter_config_1.pv_power_forecast

  battery_discharge_power_max: 5000
  battery_charge_power_max: 4600
  battery_discharge_efficiency: 0.95
  battery_charge_efficiency: 0.95
  battery_nominal_energy_capacity: 13300
  battery_minimum_state_of_charge: 0.10
  battery_maximum_state_of_charge: 0.95
  battery_target_state_of_charge: 0.90

hybrid_inverter_config_2:
  set_use_pv: true
  set_use_battery: true
  inverter_is_hybrid: true

  # Initial v1 supplies extra-block PV at runtime:
  # hybrid_inverter_config_2.pv_power_forecast

  battery_discharge_power_max: 5000
  battery_charge_power_max: 4600
  battery_discharge_efficiency: 0.95
  battery_charge_efficiency: 0.95
  battery_nominal_energy_capacity: 26600
  battery_minimum_state_of_charge: 0.10
  battery_maximum_state_of_charge: 0.95
  battery_target_state_of_charge: 0.90
```

This fixes the "large battery fills too late" problem because block `2` has its
own capacity and its own charge-power cap. It cannot borrow block `0` or block
`1` charge power after those batteries fill.

## PV Input Rule

Multi-inverter mode supports two PV input modes.

| Mode | Meaning | Config |
| --- | --- | --- |
| `site_pv` | Existing top-level PV sensor remains total site PV | Extra blocks may define batteries only; no per-inverter PV curtailment |
| `split_pv` | Each block has its own PV forecast in the optimiser | Top-level `sensor_power_photovoltaics` is inverter `0` PV only; initial v1 extra blocks receive PV through runtime `hybrid_inverter_config_N.pv_power_forecast` |

Recommended:

```yaml
multi_hybrid_inverter_pv_mode: split_pv
```

If the top-level PV sensor is total site PV and extra blocks also receive
runtime `pv_power_forecast` values, PV can be double-counted. Future config-time
extra-block PV sources create the same risk. Validation should hard fail when
this is directly detectable. If it cannot be detected from config alone, log a
clear warning that the root PV sensor must be inverter `0` only in `split_pv`
mode.

In v1, `split_pv` should be the primary supported multi-hybrid mode. `site_pv`
is useful for aggregate PV compatibility, but it cannot provide per-inverter
curtailment guarantees and has weaker no-grid-charge/no-discharge reasoning. If
`site_pv` is retained, extra block PV config and runtime forecasts should be
rejected rather than silently ignored.

Initial v1 extra-block PV acquisition is deliberately narrow:

- block `0` uses the existing PV forecast path
- block `N >= 1` uses runtime `hybrid_inverter_config_N.pv_power_forecast`

Top-level PV runtime/config values remain block `0` values in `split_pv`. They
must not be interpreted as fleet PV.

Block-local sensor retrieval, PVLib modelling, CSV inputs, adjusted-PV models,
and other config-time PV acquisition paths are future work unless implemented
with tests in Step 4.

In `split_pv`, result and publish names follow the same block suffix rule:

```text
P_PV
P_PV_1
P_PV_2
P_PV_total

P_PV_curtailment
P_PV_curtailment_1
P_PV_curtailment_2
P_PV_curtailment_total
```

Existing EMHASS PV list support for mixed orientation is not equivalent to
multiple independently constrained hybrid inverter/battery blocks.

## Runtime REST Shape

Block `0` keeps the current runtime shape.

```json
{
  "soc_init": 0.42,
  "soc_final": 0.90,
  "battery_charge_power_max": 4600,
  "battery_discharge_power_max": 5000
}
```

Extra blocks use nested runtime dictionaries with the same key names.

```json
{
  "soc_init": 0.42,
  "soc_final": 0.90,
  "battery_charge_power_max": 4600,
  "battery_discharge_power_max": 5000,

  "hybrid_inverter_config_1": {
    "soc_init": 0.51,
    "soc_final": 0.90,
    "battery_charge_power_max": 4600,
    "battery_discharge_power_max": 5000,
    "pv_power_forecast": [0, 0, 400, 1200]
  },

  "hybrid_inverter_config_2": {
    "soc_init": 0.37,
    "soc_final": 0.90,
    "battery_charge_power_max": 4600,
    "battery_discharge_power_max": 5000,
    "pv_power_forecast": [0, 0, 500, 1800]
  }
}
```

Keep `soc_init` and `soc_final`. Do not replace them with new aliases in v1.
Current `soc_target` semantics stay separate: `soc_target` is a one-sided
intermediate minimum target, not final SOC.

Runtime payload support and `runtime_params.json` are different surfaces.
EMHASS can accept ordinary config keys in runtime payloads through the existing
runtime merge path. That does not make those keys runtime-only metadata.

V1 supports scalar per-block runtime power caps. Per-timestep cap forecast arrays
are future scope unless they are explicitly implemented and tested in the same
PR.

`runtime_params.json` should document true runtime-only keys and the nested block
shape:

```text
hybrid_inverter_config_<N>.<existing_runtime_key>
```

Do not duplicate ordinary config keys such as `battery_charge_power_max` or
`battery_discharge_power_max` in `runtime_params.json`. Existing tests expect
runtime-only keys to stay disjoint from config/default keys.

Nested runtime `hybrid_inverter_config_0` is invalid. Runtime may override block
`0` only through the existing flat top-level keys. Runtime may not create new
blocks in v1; a nested runtime block is valid only when the matching config block
already exists.

The current web endpoint logs runtime parameters. Runtime payloads must not
contain Home Assistant tokens, bridge credentials, inverter credentials, or other
secret material. The endpoint must also avoid logging raw runtime payload values:
log allowed key names, block indexes, scalar summaries, and forecast lengths
only. Redact sensitive key names and token-like values before any logging.

## Published Entity Naming

Rule:

- Block `0`: existing names.
- Block `N >= 1`: append `_<N>`.
- Future nested per-block series `k` inside block `N`: append `_<N>_<k>`.

| Meaning | Block `0` | Block `1` | Block `2` |
| --- | --- | --- | --- |
| Battery power forecast | `sensor.p_batt_forecast` | `sensor.p_batt_forecast_1` | `sensor.p_batt_forecast_2` |
| Battery SOC forecast | `sensor.soc_batt_forecast` | `sensor.soc_batt_forecast_1` | `sensor.soc_batt_forecast_2` |
| Hybrid inverter power | `sensor.p_hybrid_inverter` | `sensor.p_hybrid_inverter_1` | `sensor.p_hybrid_inverter_2` |

Block-local deferrables are reserved for future use. In v1, all deferrable
loads remain site-level and keep existing names:

```text
P_deferrable0
sensor.p_deferrable0
```

The suffix forms `P_deferrable_<block>_<load>` and
`sensor.p_deferrable_<block>_<load>` are reserved.

Per-block HA publishing is not automatic just because result columns exist. The
publisher needs an explicit contract for which suffixed entities are emitted and
how custom entity IDs are overridden.

Existing custom publish controls for block `0` must keep current behaviour,
including `custom_batt_forecast_id`, `custom_batt_soc_forecast_id`,
`custom_hybrid_inverter_id`, `custom_deferrable_forecast_id`, and
`publish_prefix`. Extra blocks should append the block suffix after the resolved
base entity name unless an explicit future option marks a custom entity ID as
absolute.

The command bridge must not assume `/action/...` returns a JSON plan unless a
future endpoint is explicitly added. For v1, the bridge should consume existing
published sensors, saved optimisation output, or another documented current
output path.

## Result Column Naming

Block `0` result columns keep their current names.

| Meaning | Block `0` | Block `1` | Block `2` |
| --- | --- | --- | --- |
| Battery power | `P_batt` | `P_batt_1` | `P_batt_2` |
| Battery SOC | `SOC_opt` | `SOC_opt_1` | `SOC_opt_2` |
| Hybrid inverter | `P_hybrid_inverter` | `P_hybrid_inverter_1` | `P_hybrid_inverter_2` |

Mandatory aggregate diagnostics in multi-block mode:

```text
P_batt_total
SOC_opt_total
P_hybrid_inverter_total
P_PV_total
```

Do not repurpose `P_batt` to mean total fleet power in multi-inverter mode.
Existing `sensor.p_batt_forecast` automations may use `P_batt` as an inverter
`0` command. Sending fleet-wide power through that entity would be dangerous.

`SOC_opt_total` should be defined as total stored energy divided by total nominal
capacity across battery-enabled blocks.

`P_PV_total` should be the sum of block-level AC-side PV contribution used by the
site balance in `split_pv`. If curtailment is enabled, expose
`P_PV_curtailment_total` with the same mandatory diagnostic status.

`SOC_opt`, `SOC_opt_1`, and `SOC_opt_2` stay fractions in result/CSV output.
Published `sensor.soc_batt_forecast`, `sensor.soc_batt_forecast_1`, and
`sensor.soc_batt_forecast_2` stay percent values, matching current EMHASS
publishing behaviour.

`P_batt > 0` remains discharge and `P_batt < 0` remains charge. If an inverter
uses positive charge and negative discharge, the external command bridge applies:

```text
setpoint_i = -P_batt_i
```

## Optimisation Model

Let the inverter/battery block index be:

```text
i = 0..B-1
```

For each block with a battery:

```text
p_sto_pos_i[t] >= 0      # discharge component using current EMHASS battery semantics
p_sto_neg_i[t] <= 0      # charge component using current EMHASS battery semantics

P_batt_i[t] = p_sto_pos_i[t] + p_sto_neg_i[t]
```

Column mapping:

```text
i = 0  -> P_batt
i = 1  -> P_batt_1
i = 2  -> P_batt_2
```

Internal aggregate for site balance:

```text
P_batt_total[t] = sum_i(P_batt_i[t])
```

Stored energy per battery:

```text
E_i[t+1] =
    E_i[t]
  + eta_ch_i * (-p_sto_neg_i[t]) * dt
  - p_sto_pos_i[t] / eta_dis_i * dt
```

SOC bounds:

```text
C_i * soc_min_i <= E_i[t] <= C_i * soc_max_i
```

Final SOC default:

```text
E_i[T] == C_i * soc_final_i
```

Keep equality by default. That matches current EMHASS final SOC behaviour better
than a one-sided `>= target`.

SOC indexing must be explicit:

- `E_i[0]` is the initial stored energy before the first timestep.
- `E_i[t+1]` is stored energy after timestep `t`.
- Published/result `SOC_opt_i[t]` is post-timestep SOC.

Power-limit semantics must preserve current EMHASS behaviour in v1. Do not
reinterpret `battery_charge_power_max` and `battery_discharge_power_max` as a new
DC-side model without a separate migration. Extract the current single-battery
constraints first, then apply the same semantics per block.

Legacy SOC recovery behaviour is unchanged.

In multi-block v1, `soc_init`, `soc_final`, and `soc_target` are validated per
block. Values outside `[0, 1]` hard-fail. Values outside configured min/max SOC
hard-fail unless they are within a small sensor tolerance, in which case they are
clamped with a warning. Existing recovery binaries are not copied per block in
v1. This is a deliberate behaviour choice to keep MILP size bounded.

Hybrid blocks must preserve current AC/DC inverter modelling. Per-block
implementation needs block-indexed versions of the existing hybrid variables and
constraints, including:

```text
p_dc_ac_i[t]
p_ac_dc_i[t]
is_dc_sourcing_i[t]
P_hybrid_inverter_i[t]
```

plus per-block AC/DC conversion limits, curtailment constraints in `split_pv`,
and the existing hybrid inverter sign/efficiency semantics.

## Site Balance

The site remains one net-metered site.

For hybrid blocks, site balance should consume each block's AC-side hybrid
inverter expression, not raw battery/PV DC-side variables. A simplified
AC-coupled block can be represented by net PV and `P_batt_i`, but the hybrid path
must preserve existing `P_hybrid_inverter` logic.

```text
site_supply_i[t] =
  P_hybrid_inverter_i[t]        # hybrid block
  or AC_side_PV_batt_i[t]       # simplified AC-coupled block

P_grid[t]
= site_load[t]
+ site_deferrable_loads[t]
- sum_i(site_supply_i[t])
```

Exact signs must follow existing EMHASS internals. Do not rewrite the grid sign
convention. `P_grid > 0` remains import and `P_grid < 0` remains export.

Site import/export limits remain site-level:

```yaml
maximum_power_from_grid: ...
maximum_power_to_grid: ...
```

Per-block inverter limits and site/grid limits are different concepts and must
not be collapsed into one scalar.

If `battery_charge_power_site_max` or `battery_discharge_power_site_max` are
added, define them explicitly as aggregate site-side battery constraints:

```text
sum_i(p_sto_pos_i[t]) <= battery_discharge_power_site_max
-sum_i(p_sto_neg_i[t]) <= battery_charge_power_site_max
```

For hybrid inverters, the relationship between AC-side limits, DC-side battery
limits, PV curtailment, and grid export needs topology-specific tests.

## Battery Charge/Discharge Lock

Default for multi-inverter mode:

```yaml
battery_mode_lock: site
```

Meaning:

```text
At a given timestep:
  either all batteries may charge/idle,
  or all batteries may discharge/idle,
  but not mixed charge/discharge across blocks.
```

This prevents hidden round-tripping:

```text
inverter 0 discharges
inverter 1 charges
site aggregate looks harmless
actual batteries cycle internally
```

Optional unsafe mode:

```yaml
battery_mode_lock: none
```

`none` should be deferred unless per-block self-lock binaries are implemented.
Without either a shared site lock or per-block self-lock, one block can charge
and discharge internally in the same timestep, and aggregate constraints can hide
one battery charging while another discharges. It is incompatible with claims of
strict no-grid-charge or no-discharge-to-grid enforcement.

The site lock should reuse the current battery direction binary concept where
possible and should not introduce per-block charge/discharge binaries in v1.

Concrete site-lock shape:

```text
E_site[t] in {0, 1}
p_sto_pos_i[t] <= discharge_limit_i[t] * E_site[t]
p_sto_neg_i[t] >= -charge_limit_i[t] * (1 - E_site[t])
```

The exact `charge_limit_i` and `discharge_limit_i` expressions should be the
current EMHASS-compatible per-block power-limit expressions, not rederived
semantics.

## Existing EMHASS Flags

| Existing flag | Multi-block behaviour |
| --- | --- |
| `set_nocharge_from_grid` | Apply using existing aggregate topology logic over `P_batt_total`, not per-block naive clipping |
| `set_nodischarge_to_grid` | Reuse existing topology-specific logic; do not simplify |
| `set_battery_dynamic` | Default per block; optional site-total mode can be deferred |
| `weight_battery_charge` | Applies to block `0`; extra block override inside `hybrid_inverter_config_N` |
| `weight_battery_discharge` | Applies to block `0`; extra block override inside `hybrid_inverter_config_N` |
| `maximum_power_from_grid` | Site-level only |
| `maximum_power_to_grid` | Site-level only |
| `compute_curtailment` | Per block only in `split_pv` mode |
| Deferrable loads | Site-level in v1; block-local deferrables are reserved for future use |

Do not simplify `set_nodischarge_to_grid`. Current EMHASS distinguishes hybrid
and AC-coupled behaviour. Parallel blocks must preserve that behaviour at the
aggregate site/topology level.

`set_nocharge_from_grid` currently behaves as an aggregate topology rule, not a
full physical source-tracking proof. If v1 claims strict "no grid energy into
batteries" under curtailment/import edge cases, it needs stronger constraints and
specific tests.

## What This Fixes

| Current limitation | Design fix |
| --- | --- |
| EMHASS only models one inverter/battery | Add indexed `hybrid_inverter_config_N` blocks while keeping block `0` unchanged |
| "One big battery" workaround fails when individual SOC/power limits differ | Each block has separate capacity, SOC, charge cap, discharge cap |
| One inverter can curtail while another cannot | `compute_curtailment` becomes block-local in `split_pv` mode |
| Inverter/site limits can be confused with grid export | Per-block inverter/battery limits plus site-level `maximum_power_to_grid` |
| Existing automations break due to renamed sensors | Block `0` names are unchanged; extra blocks are additive only |

## Scope Limits

| Feature | v1 support |
| --- | --- |
| Net-metered parallel site | Yes |
| Multiple hybrid inverter/battery blocks | Yes |
| Per-block battery capacity and charge/discharge caps | Yes |
| Per-block PV forecast/model | Initial v1 supports extra-block runtime `pv_power_forecast`; block-local sensor/PVLib/CSV support is deferred unless Step 4 explicitly implements it |
| Per-block curtailment ability | Yes |
| Existing config unchanged | Yes |
| Existing entity names unchanged | Yes |
| Per-block deferrable loads | Reserved for future use |
| Separate grid meters | No |
| Per-phase constraints | No |
| Different export tariff per inverter | No, unless there is separate metering; net metering makes this physically ambiguous |
| Battery-to-battery energy transfer modelling | No |
| User-defined battery names | No |
| SOC-dependent piecewise power curves | Defer |
| Soft/minimum final SOC modes | Defer |
| Per-block custom publishing overrides | Defer unless needed for command bridge |

## Implementation Structure

Keep fork maintenance simple:

```text
src/emhass/inverter_blocks.py
```

Candidate objects:

```text
SingleBlockConfig
SingleBlockRuntime
SingleBlockVariables
SingleBlockResults

InverterBlockConfig
InverterBlockRuntime
InverterBlockVariables
InverterBlockResults
```

Use `SingleBlock*` names only if they make the behaviour-preserving extraction
clearer. Once indexed blocks are active, the public implementation vocabulary
should settle on `InverterBlock*`.

Parsing:

```text
block 0 = existing top-level config
block 1 = hybrid_inverter_config_1
block 2 = hybrid_inverter_config_2
...
```

Do not move the whole config system to a new list-of-dicts model. That would be
cleaner architecturally but worse for compatibility.

Keep the optimiser boundary narrow. Block objects should create per-block
parameters, variables, storage constraints, and result columns. Existing
site-level grid balance, tariffs, import/export limits, and topology rules should
continue to live at the site optimisation layer.

### Progress Tracking

Status values:

- `Not started`: no implementation branch or PR exists for the step.
- `In progress`: code is being changed.
- `Blocked`: a decision, dependency, or failing prerequisite prevents progress.
- `Review`: implementation and local verification are complete; review or CI is
  pending.
- `Done`: merged or otherwise accepted with verification evidence recorded.

Update this table as implementation progresses. Do not mark a step `Done`
without recording the PR/branch and the verification evidence that proved the
exit criteria.

### Step 0: Legacy Behaviour Freeze

This is a non-negotiable gate before refactoring. Add golden tests for the
current single-inverter path and keep them passing through every later step.

| Test | Required result |
| --- | --- |
| Existing config, no extra blocks | Same optimisation output |
| Existing REST payload | Same output |
| Existing HA publish names | Same entities |
| Existing `P_batt`, `SOC_opt`, `P_grid` signs/units | Same semantics |
| Existing no-grid-charge/no-discharge flags | Same behaviour |

### Implementation Tracker

| Step | Status | PR/branch | Scope | Public behaviour | Exit criteria | Docs/schema |
| --- | --- | --- | --- | --- | --- | --- |
| 0. Legacy behaviour freeze | Done | `multi-batt` @ `701b2c2c` | Added golden/characterisation coverage for the existing single-inverter path before refactoring. | None | Commit records coverage for no-extra-block optimisation output, flat REST payload behaviour, legacy HA publish names, `P_batt`/`SOC_opt`/`P_grid` signs and units, and existing no-grid-charge/no-discharge flag behaviour. | None |
| 1. Extract block `0` battery + hybrid internals | Done | `multi-batt` @ `ca5e6189` | Introduced internal block `0` wrappers for battery and hybrid inverter config/runtime/variables/results while keeping exactly one internal block. | None | Step 0 golden tests still matched current behaviour. No `hybrid_inverter_config_1`, no new columns, no publisher changes. | Developer notes only if needed |
| 2. Parse indexed config, allowlist, validation, cache invalidation | Review | `multi-batt` Step 2 commit | Added `hybrid_inverter_config_N` parsing, contiguous index validation, block-local allowlist enforcement, disabled multi-block solve gates, and structural cache keys. | Extra blocks validate, then raise "multi-block solve not enabled". | Local verification passed: Step 2 targeted tests `214 passed, 7 skipped`; full suite `694 passed, 7 skipped, 28 xfailed, 4 subtests passed`; `ruff check` passed; `git diff --check` passed; two final review agents approved. External CI remains pending. | `param_definitions.json`, config defaults/associations, config docs, generated OpenAPI artifact updated to satisfy repository artifact checks |
| 3. Add nested runtime merge | Done | `multi-batt` Step 3 commit | Flat runtime keys override block `0`; `hybrid_inverter_config_N.*` overrides existing configured block `N`. Runtime cannot create blocks. | Still no multi-block solve. | Local focused verification passed for runtime merge, command-line gate, web redaction, parser/optimizer guard, runtime/OpenAPI/schema, docs build, lint, and legacy compatibility guard. Two independent audits confirmed Step 3 is implemented and complete. Full `pytest tests/` hit three Solcast forecast quota-state failures in the shared helper container; those nodes passed with isolated `TMPDIR`. External CI not run locally. | `runtime_params.json`, OpenAPI/runtime docs |
| 4. Resolve per-block PV sources | Not started | TBD | Keep block `0` on the existing PV path. For v1, support extra block PV initially through runtime `hybrid_inverter_config_N.pv_power_forecast`; defer block-local sensor retrieval/PVLib/CSV support unless implemented explicitly. | Validated inputs only. | Tests cover `split_pv`, `site_pv` extra-PV rejection, runtime forecast shape, and detectable double-counting errors. | Config/runtime PV docs |
| 5. Add per-block battery variables and SOC constraints | Not started | TBD | Add `p_sto_pos_i`, `p_sto_neg_i`, `E_i`, `SOC_i`, `P_batt_i`, and `P_batt_total` using current EMHASS power semantics. | Internal or feature-flagged only; do not expose default public multi-block solve before Step 6. | Tests cover one extra battery, battery 62 with 2x capacity, full-block charge blocking, min-SOC discharge blocking, and no fleet-power borrowing. | Draft plan output docs |
| 6. Add `battery_mode_lock: site` | Not started | TBD | Add the site-level binary mode lock so all batteries charge/idle or discharge/idle together. | First safe public multi-block battery solve. Multi-block solve becomes MILP in safe mode. | Tests prove no mixed charge/discharge across blocks; performance smoke test is recorded. | Config docs for mode lock |
| 7. Add block-indexed hybrid inverter variables/constraints | Not started | TBD | Add block-indexed `p_dc_ac_i`, `p_ac_dc_i`, `is_dc_sourcing_i`, `P_hybrid_inverter_i`, per-block AC/DC limits, and split-PV curtailment constraints. | Real hybrid multi-block model. | Hybrid parity tests preserve block `0`; split-PV curtailment tests pass for extra blocks. | Developer notes and config docs as needed |
| 8. Reconnect site balance and topology constraints | Not started | TBD | Use each block's AC-side site supply in `P_grid`; preserve site-level import/export limits and existing `set_nocharge_from_grid` / `set_nodischarge_to_grid` topology logic. | Physically useful optimiser. | Tests cover site import/export limits, hybrid and AC-coupled no-discharge paths, no-charge-from-grid edge cases, unchanged grid sign semantics, and a case where AC/DC efficiency or curtailment makes `P_hybrid_inverter_i` differ from raw PV plus battery power. | Plan output/config docs |
| 9. Add result columns and aggregate diagnostics | Not started | TBD | Add `P_batt_N`, `SOC_opt_N`, `P_hybrid_inverter_N`, PV/curtailment suffixes, and mandatory totals: `P_batt_total`, `SOC_opt_total`, `P_hybrid_inverter_total`, `P_PV_total`, plus `P_PV_curtailment_total` when curtailment exists. | Stable output schema. | Schema/value tests prove block `0` names are unchanged; totals are present; `P_batt_total == sum(P_batt_i)`; `SOC_opt_total` is capacity-weighted SOC; `P_hybrid_inverter_total == sum(P_hybrid_inverter_i)`; `P_PV_total` matches the AC-side PV contribution used by site balance. | `docs/plan_output_schema.md` |
| 10. Add HA publisher suffixing and command bridge examples | Not started | TBD | Publish block `0` names unchanged and extra block entities with `_<N>` suffixes. Do not publish block-local deferrables in v1. Add command bridge examples only; EMHASS still does not directly command inverters. | Stable HA entity surface. | Publish tests cover existing entities, suffixed battery/SOC/hybrid/PV entities, no per-block deferrable entities, and command bridge sign convention examples. | `docs/publish_data.md`, migration notes |

Per-timestep runtime cap forecasts, final-constraint modes, tie-break modes, and
SOC-dependent power curves should wait until the v1 indexed-block model is
stable.

## Validation Rules

| Rule | Result |
| --- | --- |
| No extra config blocks | Legacy mode |
| `hybrid_inverter_config_0` appears in config | Hard error |
| Nested runtime `hybrid_inverter_config_0` appears | Hard error |
| Extra block index skipped | Hard error |
| Extra block contains `sensor_power_load_no_var_loads` | Hard error unless explicitly allowed; load is site-level |
| Extra block contains a config-time PV source/model key before Step 4 implements that source | Hard error in initial v1 |
| `site_pv` and extra block contains a PV source or PV runtime forecast | Hard error in v1 |
| `split_pv` and root PV appears to be site total | Hard error if detectable; otherwise clear warning |
| Extra block has `set_use_battery: true` but missing battery capacity/power | Hard error |
| Extra block contains deferrable-load config | Hard error in v1 |
| Extra block has custom entity base | Suffix still appended unless explicitly marked absolute |
| Runtime block present without matching config block | Hard error |
| Runtime nested key is not valid for that block | Hard error |
| Runtime values are non-finite or negative where power/capacity is required positive | Hard error |
| Efficiency is outside `0 < efficiency <= 1` | Hard error |
| `battery_minimum_state_of_charge >= battery_maximum_state_of_charge` | Hard error |
| Per-timestep runtime cap forecast appears without explicit feature support | Hard error in v1 |
| Future-only final-constraint mode field appears | Hard error in v1 |
| Future-only SOC-dependent power-curve field appears | Hard error in v1 |
| Both legacy scalar and nested value are supplied for block `0` | Hard error unless an explicit precedence rule is documented |

Structural fields must participate in cache invalidation:

- number of blocks
- block indexes
- block PV mode
- battery enabled flags
- PV enabled flags
- capacities
- efficiencies
- min/max SOC bounds
- structural forecast shapes
- mode lock
- topology flags that change constraint shape

Runtime SOC and runtime cap values can be CVXPY parameters only when their shape
does not change.

## Acceptance Tests

| Test | Required result |
| --- | --- |
| Existing single-inverter config | Identical outputs and HA entities |
| Existing REST payload | Identical result |
| Existing `sensor.p_deferrable0` | Still published, unchanged |
| Add `hybrid_inverter_config_1` | New `sensor.p_batt_forecast_1`, `sensor.soc_batt_forecast_1`, etc. |
| `split_pv` with extra block PV | `P_PV_1` and `P_PV_total` result/publish names are produced; curtailment uses the same suffix rule |
| Initial v1 extra block config-time PV source | Hard validation error unless Step 4 explicitly implemented that source |
| Battery 62 has 2x capacity, same charge cap | Optimiser starts charging early enough; no fleet-power borrowing |
| Block 0 full | `P_batt` cannot charge while `P_batt_1`/`P_batt_2` may charge |
| Block 2 still empty after 0/1 full | `P_batt_2` continues charging at its own cap |
| `battery_mode_lock: site` | No mixed charge/discharge across inverter blocks |
| Site grid import/export limits | Enforced on aggregate site flow |
| AC/DC efficiency or curtailment differs from raw PV plus battery power | `P_grid` uses `P_hybrid_inverter_i` / AC-side site supply, not raw DC-side variables |
| `set_nodischarge_to_grid` hybrid path | Existing topology behaviour preserved |
| `set_nodischarge_to_grid` AC-coupled path | Existing topology behaviour preserved |
| `set_nocharge_from_grid` with curtailment/import edge case | Behaviour is either preserved and documented or strengthened and tested |
| `P_batt` sign | Positive discharge, negative charge |
| Command bridge | Uses `setpoint_i = -P_batt_i` |
| Runtime block without config block | Hard validation error |
| Skipped config index | Hard validation error |
| `split_pv` double-count risk | Hard validation error if detectable |
| Cache structural change | Rebuilds optimiser |
| Runtime SOC/scalar-cap value change only | Reuses optimiser parameters when shape is unchanged |
| Aggregate diagnostics values | `P_batt_total`, `SOC_opt_total`, `P_hybrid_inverter_total`, and `P_PV_total` equal their documented formulas |
| Future-only SOC modes or SOC power curves | Hard validation error in v1 |

## Documentation and Schema Cadence

Docs and schema updates should land with the public surface they describe, not as
one final cleanup PR.

| Implementation point | Docs/schema update |
| --- | --- |
| Parser and validation | `src/emhass/static/data/param_definitions.json`, `src/emhass/data/config_defaults.json`, `src/emhass/data/associations.csv`, config docs, add-on/options surface if applicable, and cache-key docs/tests |
| Runtime merge | `src/emhass/static/data/runtime_params.json`, OpenAPI/runtime docs |
| PV source resolution | PV mode and runtime forecast examples |
| Result builder | `docs/plan_output_schema.md` with per-block columns and mandatory totals |
| Publisher | `docs/publish_data.md` with suffixing and command bridge expectations |
| Release preparation | Migration notes and full examples |

Migration note:

Existing single-inverter configs remain unchanged. Extra blocks use the same
block-local battery / hybrid inverter / PV parameter names as the root config,
but nested under `hybrid_inverter_config_N`. The root config is block `0`, not a
fleet aggregate.

## Revised Conclusion

Use indexed hybrid inverter config blocks:

```yaml
# existing config = block 0
hybrid_inverter_config_1:
  ...
hybrid_inverter_config_2:
  ...
```

Use existing names for block `0` and suffix-only additive names for extra blocks:

```text
p_batt_forecast
p_batt_forecast_1
p_batt_forecast_2

p_deferrable0
```

This is the correct compatibility-first design. It still solves the modelling
error because each inverter/battery block gets its own SOC, capacity, and
charge/discharge limits inside one site optimisation.

## References

- EMHASS configuration documentation: https://emhass.readthedocs.io/en/latest/config.html
- EMHASS stable configuration documentation: https://emhass.readthedocs.io/en/stable/config.html
- EMHASS runtime data documentation: https://emhass.readthedocs.io/en/latest/passing_data.html
- EMHASS publish data documentation: https://emhass.readthedocs.io/en/latest/publish_data.html
- EMHASS plan output schema: https://emhass.readthedocs.io/en/latest/plan_output_schema.html
- GitHub discussion #870, multiple solar inverters and batteries: https://github.com/davidusb-geek/emhass/discussions/870
- GitHub discussion #544, multiple inverters and batteries: https://github.com/davidusb-geek/emhass/discussions/544
- GitHub issue #220, inverter output and feed-in mismatch: https://github.com/davidusb-geek/emhass/issues/220
