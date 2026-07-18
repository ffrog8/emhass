# EMHASS Multi-Inverter Support

## Design Position

Use explicit multi-inverter configuration, not named batteries and not a public
"block" model.

Single-inverter mode remains the normal/default EMHASS mode. It uses the
existing top-level configuration and preserves existing result columns, REST
payloads, and Home Assistant entity names.

Multi-inverter mode is opt-in. It is active only when `multi_inverter_mode` is
set to `multi` in configuration or in a runtime REST payload. Adding
`hybrid_inverter_config_1` to the config file must not by itself change current
single-inverter behaviour.

In multi-inverter mode, the active inverters are one-based:

```yaml
multi_inverter_mode: multi

hybrid_inverter_config_1:
  # inverter 1: same battery / hybrid inverter / PV parameter names
  # from the documented allowlist

hybrid_inverter_config_2:
  # inverter 2: same battery / hybrid inverter / PV parameter names
  # from the documented allowlist
```

The existing top-level inverter/battery/PV configuration remains the
single-inverter configuration. In multi-inverter mode it is not an active
inverter. This lets users keep an existing aggregate/pseudo-inverter config in
place while testing real per-inverter configs through `hybrid_inverter_config_N`.

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
- Single-inverter mode remains exactly the current behaviour.
- Existing top-level scalar configuration remains valid and remains the normal
  single-inverter surface.
- Existing REST payloads remain valid.
- Existing Home Assistant entity names remain valid in single-inverter mode.
- Multi-inverter mode is explicit and uses `hybrid_inverter_config_1..N`.
- In multi-inverter mode, unsuffixed result/entity names are site totals and
  `_<N>` names are per-inverter values.
- Static `hybrid_inverter_config_0` is accepted only as an ignored compatibility
  placeholder and must log a warning.
- Runtime `hybrid_inverter_config_0` is invalid and must hard-fail.

The command bridge stays outside EMHASS. EMHASS plans; it does not control
inverters directly.

## Runtime Components

| Component | Role | Interaction |
| --- | --- | --- |
| EMHASS fork | Single site optimiser with optional indexed inverter configs | In single mode reads the current top-level config; in multi mode reads one site load/tariff model plus `hybrid_inverter_config_1..N` |
| HA runtime builder | Reads SOC, BMS limits, inverter availability, forecasts | Posts normal runtime keys for single mode; posts nested keys for inverter `1..N` in multi mode |
| EMHASS REST API | Same endpoints as today | No new endpoint; extend payload shape only |
| Publisher | Publishes existing entities unchanged in single mode; publishes totals plus per-inverter suffixed entities in multi mode | `p_batt_forecast` total, `p_batt_forecast_1`, `p_hybrid_inverter_1` |
| Command bridge | Applies the first timestep to each inverter | In multi mode suffixed entities drive inverter `N`; unsuffixed entities are totals only |
| Inverters/BMS | Enforce physical limits | Feedback updates next runtime caps |

No asynchronous control and no direct inverter command authority should be added
inside EMHASS.

## Compatibility Contract

| Case | Behaviour |
| --- | --- |
| `multi_inverter_mode` unset | Single-inverter mode |
| `multi_inverter_mode: single` | Single-inverter mode, even if indexed inverter configs exist |
| Runtime `multi_inverter_mode: single` | Single-inverter mode for that request |
| `multi_inverter_mode: multi` | Multi-inverter mode; require `hybrid_inverter_config_1` |
| Runtime `multi_inverter_mode: multi` | Multi-inverter mode for that request, using configured inverter `1..N` plus nested runtime overrides |
| Existing top-level config | Active only in single-inverter mode; ignored as active inverter config in multi-inverter mode |
| Existing REST payload | Still valid in single-inverter mode |
| Existing HA entity names | Unchanged in single-inverter mode |
| Existing automations using `sensor.p_batt_forecast` | Safe only for single-inverter mode or aggregate monitoring in multi-inverter mode |
| Multi-inverter per-inverter entities | Always suffixed with inverter index `_<N>` |
| User-defined battery/inverter names | Not part of v1 primary interface |
| Static `hybrid_inverter_config_0` | Ignored with a warning |
| Runtime `hybrid_inverter_config_0` | Hard error |

New controls must be inert in single-inverter mode:

| Control | Default | Single-inverter effect |
| --- | --- | --- |
| `multi_inverter_mode` | `single` | Current behaviour |
| `multi_hybrid_inverter_pv_mode` | unset / existing behaviour | No behaviour change |
| `battery_mode_lock` | current single-battery lock behaviour for single mode; `site` for multi-inverter mode | No behaviour change in single mode |

Skipped active inverter indexes are invalid in multi-inverter mode. This must
hard-fail:

```yaml
hybrid_inverter_config_2: {}
```

without:

```yaml
hybrid_inverter_config_1: {}
```

## Configuration Shape

### Existing Single-Inverter Config

The existing single-inverter configuration remains unchanged and is the default
mode.

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

### Multi-Inverter Config

Multi-inverter mode is enabled explicitly:

```yaml
multi_inverter_mode: multi
```

Indexed inverter configs may contain only inverter-local parameters in v1. The
implementation should encode this as a concrete allowlist using current EMHASS
parameter names. All other keys hard-error in multi-inverter mode.

| Group | Active indexed inverter config keys in initial v1 | Notes |
| --- | --- | --- |
| Enablement | `set_use_pv`, `set_use_battery`, `inverter_is_hybrid` | Inverter-local |
| Battery limits/state | `battery_discharge_power_max`, `battery_charge_power_max`, `battery_discharge_efficiency`, `battery_charge_efficiency`, `battery_nominal_energy_capacity`, `battery_minimum_state_of_charge`, `battery_maximum_state_of_charge`, `battery_target_state_of_charge` | Inverter-local |
| Battery dynamic/weights | `set_battery_dynamic`, `battery_dynamic_max`, `battery_dynamic_min`, `weight_battery_discharge`, `weight_battery_charge` | Inverter-local in v1; optional site-total mode can be deferred |
| Battery penalties | `battery_stress_cost`, `battery_stress_segments`, `battery_soc_deficit_threshold`, `battery_soc_deficit_cost`, `battery_soc_surplus_threshold`, `battery_soc_surplus_cost` | Inverter-local because they shape battery behaviour |
| Hybrid inverter | `inverter_ac_output_max`, `inverter_ac_input_max`, `inverter_efficiency_dc_ac`, `inverter_efficiency_ac_dc`, `inverter_stress_cost`, `inverter_stress_segments` | Inverter-local |
| Curtailment | `compute_curtailment` | Inverter-local only in `split_pv` |

PV source keys such as `sensor_power_photovoltaics`,
`sensor_power_photovoltaics_forecast`, `pv_module_model`,
`pv_inverter_model`, `surface_tilt`, `surface_azimuth`,
`modules_per_string`, `strings_per_inverter`, `set_use_adjusted_pv`,
`adjusted_pv_regression_model`, `adjusted_pv_solar_elevation_threshold`, and
`adjusted_pv_model_max_age` are reserved for a later inverter-local acquisition
step unless Step 4 explicitly implements and tests them. Initial v1 indexed PV
uses runtime `hybrid_inverter_config_N.pv_power_forecast`.

Site-level parameters are not inverter-local. Indexed inverter configs must
reject load sensors and forecasts, tariffs, grid import/export limits,
deferrable loads, connection settings, global publish settings, optimisation
horizon/time settings, topology flags such as `set_nocharge_from_grid`,
`set_nodischarge_to_grid`, and `set_battery_first_priority`, and site-level
economic controls such as `capacity_cost_per_kw` unless a later design
explicitly adds an inverter-scoped meaning for them.

```yaml
multi_inverter_mode: multi

hybrid_inverter_config_1:
  set_use_pv: true
  set_use_battery: true
  inverter_is_hybrid: true

  # Initial v1 supplies indexed PV at runtime:
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

  # Initial v1 supplies indexed PV at runtime:
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

This fixes the "large battery fills too late" problem because inverter `2` has
its own capacity and its own charge-power cap. It cannot borrow inverter `1`
charge power after that battery fills.

## PV Input Rule

Multi-inverter mode supports two PV input modes.

| Mode | Meaning | Config |
| --- | --- | --- |
| `site_pv` | Existing top-level PV sensor remains total site PV | Indexed inverters may define batteries only; no per-inverter PV curtailment |
| `split_pv` | Each PV-enabled indexed inverter has its own PV forecast in the optimiser | Initial v1 indexed PV uses runtime `hybrid_inverter_config_N.pv_power_forecast` |

Recommended:

```yaml
multi_hybrid_inverter_pv_mode: split_pv
```

In multi-inverter mode the top-level PV sensor is not an active inverter PV
source. It remains part of the single-inverter configuration/fallback. Active
per-inverter PV must come from `hybrid_inverter_config_N` sources or runtime
nested forecasts.

If the top-level PV sensor is total site PV and indexed inverter PV forecasts
are also supplied, PV can be double-counted if the implementation accidentally
mixes single-inverter and multi-inverter sources. Validation should hard fail
when this is directly detectable. If it cannot be detected from config alone,
log a clear warning that multi-inverter mode ignores the top-level PV source as
an active inverter source.

In v1, `split_pv` should be the primary supported multi-inverter mode.
`site_pv` is useful for aggregate PV compatibility, but it cannot provide
per-inverter curtailment guarantees and has weaker no-grid-charge/no-discharge
reasoning. If `site_pv` is retained, indexed inverter PV config and runtime
forecasts should be rejected rather than silently ignored.

Initial v1 indexed inverter PV acquisition is deliberately narrow:

- single-inverter mode uses the existing PV forecast path
- multi-inverter mode uses runtime `hybrid_inverter_config_N.pv_power_forecast`
  for each PV-enabled inverter `N`

Top-level PV runtime/config values remain single-inverter values. They must not
be interpreted as fleet PV or inverter `1` PV in multi-inverter mode.

Inverter-local sensor retrieval, PVLib modelling, CSV inputs, adjusted-PV
models, and other config-time PV acquisition paths are future work unless
implemented with tests in Step 4.

In `split_pv`, result and publish names follow the same total/per-inverter rule.
For three configured inverters, where inverter `3` has no PV, expected PV result
columns are:

```text
P_PV          # total PV across PV-enabled inverters
P_PV_1
P_PV_2
```

`P_PV_3` and `sensor.p_pv_forecast_3` should not be produced for an inverter
with `set_use_pv: false`.

Curtailment follows the same pattern:

```text
P_PV_curtailment          # total curtailment
P_PV_curtailment_1
P_PV_curtailment_2
```

Existing EMHASS PV list support for mixed orientation is not equivalent to
multiple independently constrained hybrid inverters with batteries.

## Runtime REST Shape

Single-inverter mode keeps the current runtime shape.

```json
{
  "soc_init": 0.42,
  "soc_final": 0.90,
  "battery_charge_power_max": 4600,
  "battery_discharge_power_max": 5000
}
```

Multi-inverter mode is explicitly selected and uses nested runtime dictionaries
with the same key names for active inverters.

```json
{
  "multi_inverter_mode": "multi",

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

In multi-inverter mode, active inverter SOC and battery/inverter power runtime
values must be nested under `hybrid_inverter_config_N`. Flat single-inverter
runtime SOC and battery/inverter cap keys are not applied to inverter `1`.
Accepting them with a warning is acceptable for transition/testing, but silently
treating flat keys as inverter `1` values is not.

Runtime payload support and `runtime_params.json` are different surfaces.
EMHASS can accept ordinary config keys in runtime payloads through the existing
runtime merge path. That does not make those keys runtime-only metadata.

V1 supports scalar per-inverter runtime power caps. Per-timestep cap forecast
arrays are future scope unless they are explicitly implemented and tested in the
same PR.

`runtime_params.json` should document true runtime-only keys and the nested
inverter shape:

```text
hybrid_inverter_config_<N>.<existing_runtime_key>
```

Do not duplicate ordinary config keys such as `battery_charge_power_max` or
`battery_discharge_power_max` in `runtime_params.json`. Existing tests expect
runtime-only keys to stay disjoint from config/default keys.

Nested runtime `hybrid_inverter_config_0` is invalid. Runtime may not create new
inverters in v1; a nested runtime inverter is valid only when the matching
configured inverter already exists and `multi_inverter_mode` is `multi`.

The current web endpoint logs runtime parameters. Runtime payloads must not
contain Home Assistant tokens, bridge credentials, inverter credentials, or other
secret material. Step 11 intentionally preserves upstream-compatible raw runtime
logging (`Passed runtime parameters: ...`) so the PR does not change debug output
format. Do not add a new runtime log summariser in this PR.

## Published Entity Naming

Rule:

- Single-inverter mode: existing names and meanings.
- Multi-inverter mode: unsuffixed names are site/fleet totals.
- Multi-inverter mode: `_<N>` names are per-inverter values for configured
  inverter `N`.
- Future nested per-inverter series `k` inside inverter `N`: append `_<N>_<k>`.

For three active inverters, battery/SOC publishing produces `N + 1` sensors:
one total plus one per inverter.

| Meaning | Total | Inverter `1` | Inverter `2` | Inverter `3` |
| --- | --- | --- | --- | --- |
| Battery power forecast | `sensor.p_batt_forecast` | `sensor.p_batt_forecast_1` | `sensor.p_batt_forecast_2` | `sensor.p_batt_forecast_3` |
| Battery SOC forecast | `sensor.soc_batt_forecast` | `sensor.soc_batt_forecast_1` | `sensor.soc_batt_forecast_2` | `sensor.soc_batt_forecast_3` |
| Hybrid inverter power | `sensor.p_hybrid_inverter` | `sensor.p_hybrid_inverter_1` | `sensor.p_hybrid_inverter_2` | `sensor.p_hybrid_inverter_3` |
| PV forecast | `sensor.p_pv_forecast` | `sensor.p_pv_forecast_1` | `sensor.p_pv_forecast_2` | only if inverter `3` has PV |

Inverter-local deferrables are reserved for future use. In v1, all deferrable
loads remain site-level and keep existing names:

```text
P_deferrable0
sensor.p_deferrable0
```

The suffix forms `P_deferrable_<inverter>_<load>` and
`sensor.p_deferrable_<inverter>_<load>` are reserved.

Per-inverter HA publishing is not automatic just because result columns exist. The
publisher needs an explicit contract for which suffixed entities are emitted and
how custom entity IDs are overridden.

Existing custom publish controls must keep current single-inverter behaviour,
including `custom_batt_forecast_id`, `custom_batt_soc_forecast_id`,
`custom_hybrid_inverter_id`, `custom_deferrable_forecast_id`, and
`publish_prefix`. In multi-inverter mode, per-inverter entities should append
the inverter suffix after the resolved base entity name unless an explicit
future option marks a custom entity ID as absolute.

Publisher order should group comparable values together:

```text
load
grid
PV total, PV_1, PV_2, ...
curtailment total, curtailment_1, curtailment_2, ...
hybrid inverter total, hybrid inverter_1, hybrid inverter_2, ...
battery total, battery_1, battery_2, ...
SOC total, SOC_1, SOC_2, ...
site deferrables / thermal
cost, status, unit prices
```

The command bridge must not assume `/action/...` returns a JSON plan unless a
future endpoint is explicitly added. For v1, the bridge should consume existing
published sensors, saved optimisation output, or another documented current
output path.

## Result Column Naming

Single-inverter mode keeps current result column names and meanings.

Multi-inverter mode uses unsuffixed totals plus one-based per-inverter suffixes.

| Meaning | Total | Inverter `1` | Inverter `2` | Inverter `3` |
| --- | --- | --- | --- | --- |
| Battery power | `P_batt` | `P_batt_1` | `P_batt_2` | `P_batt_3` |
| Battery SOC | `SOC_opt` | `SOC_opt_1` | `SOC_opt_2` | `SOC_opt_3` |
| Hybrid inverter | `P_hybrid_inverter` | `P_hybrid_inverter_1` | `P_hybrid_inverter_2` | `P_hybrid_inverter_3` |
| PV | `P_PV` | `P_PV_1` | `P_PV_2` | only if inverter `3` has PV |

Do not emit `_0` result columns. Step 11 should remove or replace the previous
`*_total` public diagnostics for these fields because the unsuffixed names
become the totals in multi-inverter mode. If transitional aliases are ever
added, they must be explicitly documented and tested; they are not part of this
Step 11 contract.

`SOC_opt` in multi-inverter mode is the fleet SOC diagnostic: total stored
energy divided by total nominal capacity across battery-enabled inverters.

`P_PV` should be an AC-equivalent post-curtailment PV availability diagnostic in
`split_pv`. It is not source tracking and is not actual AC-side PV source
attribution. If curtailment is enabled, expose `P_PV_curtailment` as the total
curtailment column and `P_PV_curtailment_N` per PV-enabled inverter.

`SOC_opt`, `SOC_opt_1`, `SOC_opt_2`, and `SOC_opt_3` stay fractions in
result/CSV output. Published SOC sensors stay percent values, matching current
EMHASS publishing behaviour.

`P_batt > 0` remains discharge and `P_batt < 0` remains charge. If an inverter
uses positive charge and negative discharge, the external command bridge applies:

```text
setpoint_N = -P_batt_N
```

In multi-inverter mode, `P_batt` / `sensor.p_batt_forecast` is the total and
must not be sent as a command to a single inverter.

## Optimisation Model

Let the active multi-inverter index be:

```text
N = 1..B
```

For each active inverter with a battery:

```text
p_sto_pos_N[t] >= 0      # discharge component using current EMHASS battery semantics
p_sto_neg_N[t] <= 0      # charge component using current EMHASS battery semantics

P_batt_N[t] = p_sto_pos_N[t] + p_sto_neg_N[t]
```

Column mapping:

```text
inverter 1 -> P_batt_1
inverter 2 -> P_batt_2
inverter 3 -> P_batt_3
total      -> P_batt
```

Internal aggregate for site balance:

```text
P_batt[t] = sum_N(P_batt_N[t])
```

Stored energy per battery:

```text
E_N[t+1] =
    E_N[t]
  + eta_ch_N * (-p_sto_neg_N[t]) * dt
  - p_sto_pos_N[t] / eta_dis_N * dt
```

SOC bounds:

```text
C_N * soc_min_N <= E_N[t] <= C_N * soc_max_N
```

Final SOC default:

```text
E_N[T] == C_N * soc_final_N
```

Keep equality by default. That matches current EMHASS final SOC behaviour better
than a one-sided `>= target`.

SOC indexing must be explicit:

- `E_N[0]` is the initial stored energy before the first timestep.
- `E_N[t+1]` is stored energy after timestep `t`.
- Published/result `SOC_opt_N[t]` is post-timestep SOC for inverter `N`.
- Published/result `SOC_opt[t]` in multi-inverter mode is the fleet stored
  energy divided by fleet nominal capacity.

Power-limit semantics must preserve current EMHASS behaviour in v1. Do not
reinterpret `battery_charge_power_max` and `battery_discharge_power_max` as a new
DC-side model without a separate migration. Extract the current single-battery
constraints first, then apply the same semantics per inverter.

Single-inverter SOC recovery behaviour is unchanged.

In multi-inverter v1, `soc_init`, `soc_final`, and `soc_target` are validated
per active inverter. Values outside `[0, 1]` hard-fail. Values outside
configured min/max SOC hard-fail unless they are within a small sensor
tolerance, in which case they are clamped with a warning. Existing recovery
binaries are not copied per inverter in v1. This is a deliberate behaviour
choice to keep MILP size bounded.

Hybrid inverters must preserve current AC/DC inverter modelling. Per-inverter
implementation needs indexed versions of the existing hybrid variables and
constraints, including:

```text
p_dc_ac_N[t]
p_ac_dc_N[t]
is_dc_sourcing_N[t]
P_hybrid_inverter_N[t]
```

plus per-inverter AC/DC conversion limits, curtailment constraints in `split_pv`,
and the existing hybrid inverter sign/efficiency semantics.

## Site Balance

The site remains one net-metered site.

For hybrid inverters, site balance should consume each inverter's AC-side hybrid
inverter expression, not raw battery/PV DC-side variables. A simplified
AC-coupled inverter can be represented by net PV and `P_batt_N`, but the hybrid
path must preserve existing `P_hybrid_inverter` logic.

```text
site_supply_N[t] =
  P_hybrid_inverter_N[t]        # hybrid inverter
  or AC_side_PV_batt_N[t]       # simplified AC-coupled inverter

P_grid[t]
= site_load[t]
+ site_deferrable_loads[t]
- sum_N(site_supply_N[t])
```

Exact signs must follow existing EMHASS internals. Do not rewrite the grid sign
convention. `P_grid > 0` remains import and `P_grid < 0` remains export.

Site import/export limits remain site-level:

```yaml
maximum_power_from_grid: ...
maximum_power_to_grid: ...
```

Per-inverter limits and site/grid limits are different concepts and must
not be collapsed into one scalar.

If `battery_charge_power_site_max` or `battery_discharge_power_site_max` are
added, define them explicitly as aggregate site-side battery constraints:

```text
sum_N(p_sto_pos_N[t]) <= battery_discharge_power_site_max
-sum_N(p_sto_neg_N[t]) <= battery_charge_power_site_max
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
  but not mixed charge/discharge across active inverters.
```

This prevents hidden round-tripping:

```text
inverter 1 discharges
inverter 2 charges
site aggregate looks harmless
actual batteries cycle internally
```

Optional unsafe mode:

```yaml
battery_mode_lock: none
```

`none` should be deferred unless per-inverter self-lock binaries are
implemented. Without either a shared site lock or per-inverter self-lock, one
inverter can charge and discharge internally in the same timestep, and aggregate
constraints can hide one battery charging while another discharges. It is
incompatible with claims of strict no-grid-charge or no-discharge-to-grid
enforcement.

The site lock should reuse the current battery direction binary concept where
possible and should not introduce per-inverter charge/discharge binaries in v1.

Concrete site-lock shape:

```text
E_site[t] in {0, 1}
p_sto_pos_N[t] <= discharge_limit_N[t] * E_site[t]
p_sto_neg_N[t] >= -charge_limit_N[t] * (1 - E_site[t])
```

The exact `charge_limit_N` and `discharge_limit_N` expressions should be the
current EMHASS-compatible per-inverter power-limit expressions, not rederived
semantics.

## Existing EMHASS Flags

| Existing flag | Multi-inverter behaviour |
| --- | --- |
| `set_nocharge_from_grid` | Apply using existing aggregate topology logic over total `P_batt`, not per-inverter naive clipping |
| `set_nodischarge_to_grid` | Reuse existing topology-specific logic; do not simplify |
| `set_battery_dynamic` | Default per inverter; optional site-total mode can be deferred |
| `weight_battery_charge` | Single-inverter mode uses the top-level value; multi-inverter mode uses per-inverter values inside `hybrid_inverter_config_N` |
| `weight_battery_discharge` | Same |
| `maximum_power_from_grid` | Site-level only |
| `maximum_power_to_grid` | Site-level only |
| `compute_curtailment` | Per inverter only in `split_pv` mode |
| Deferrable loads | Site-level in v1; inverter-local deferrables are reserved for future use |

Do not simplify `set_nodischarge_to_grid`. Current EMHASS distinguishes hybrid
and AC-coupled behaviour. Parallel inverters must preserve that behaviour at the
aggregate site/topology level.

`set_nocharge_from_grid` currently behaves as an aggregate topology rule, not a
full physical source-tracking proof. If v1 claims strict "no grid energy into
batteries" under curtailment/import edge cases, it needs stronger constraints and
specific tests.

## What This Fixes

| Current limitation | Design fix |
| --- | --- |
| EMHASS only models one inverter/battery | Add explicit multi-inverter mode with indexed `hybrid_inverter_config_1..N` |
| "One big battery" workaround fails when individual SOC/power limits differ | Each inverter has separate capacity, SOC, charge cap, discharge cap |
| One inverter can curtail while another cannot | `compute_curtailment` becomes inverter-local in `split_pv` mode |
| Inverter/site limits can be confused with grid export | Per-inverter battery/hybrid limits plus site-level `maximum_power_to_grid` |
| Existing single-inverter users are disrupted by new config | Single-inverter mode remains default; indexed configs are inert unless multi mode is explicitly selected |
| Aggregate dashboards need fleet values while commands need inverter values | Unsuffixed values are totals in multi mode; `_N` values are per-inverter command inputs |

## Scope Limits

| Feature | v1 support |
| --- | --- |
| Net-metered parallel site | Yes |
| Multiple hybrid inverters with batteries | Yes |
| Per-inverter battery capacity and charge/discharge caps | Yes |
| Per-inverter PV forecast/model | Initial v1 supports indexed runtime `pv_power_forecast`; inverter-local sensor/PVLib/CSV support is deferred unless Step 4 explicitly implements it |
| Per-inverter curtailment ability | Yes |
| Existing config unchanged | Yes |
| Existing entity names unchanged in single-inverter mode | Yes |
| Multi-inverter aggregate entity names | Unsuffixed totals |
| Multi-inverter per-inverter entity names | `_1.._N` suffixes |
| Per-inverter deferrable loads | Reserved for future use |
| Separate grid meters | No |
| Per-phase constraints | No |
| Different export tariff per inverter | No, unless there is separate metering; net metering makes this physically ambiguous |
| Battery-to-battery energy transfer modelling | No |
| User-defined battery names | No |
| SOC-dependent piecewise power curves | Defer |
| Soft/minimum final SOC modes | Defer |
| Per-inverter custom publishing overrides | Defer unless needed for command bridge |

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
clearer. Internal code may keep `InverterBlock*` because it groups inverter,
battery, PV, runtime, variables, and results. Public docs and user-facing errors
should use "inverter" / "multi-inverter", not "block".

Parsing:

```text
single-inverter mode = existing top-level config
multi-inverter mode  = hybrid_inverter_config_1..N
hybrid_inverter_config_0 = ignored static compatibility placeholder only
```

Do not move the whole config system to a new list-of-dicts model. That would be
cleaner architecturally but worse for compatibility.

Keep the optimiser boundary narrow. Internal inverter objects should create
per-inverter parameters, variables, storage constraints, and result columns.
Existing site-level grid balance, tariffs, import/export limits, and topology
rules should continue to live at the site optimisation layer.

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
exit criteria. Rows for Steps 1-10 describe the implementation terminology and
public contract used at the time; Step 11 supersedes the public multi-inverter
naming and mode contract before external review. Step 12 is a review-readiness
step for browser configuration coverage, clean migration/fallback documentation,
fixing the publish-data split-PV validation bug, and aligning nested SOC runtime
and battery-limit handling with existing EMHASS behaviour; it should not change
optimiser result semantics or Home Assistant entity naming. Step 13 adds a
soft multi-inverter SOC balancing preference without changing single-inverter
behaviour or introducing a PV-headroom public setting before that behaviour is
implemented.

### Step 0: Single-Inverter Behaviour Freeze

This is a non-negotiable gate before refactoring. Add golden tests for the
current single-inverter path and keep them passing through every later step.

| Test | Required result |
| --- | --- |
| Existing config, no indexed inverter configs | Same optimisation output |
| Existing REST payload | Same output |
| Existing HA publish names | Same entities |
| Existing `P_batt`, `SOC_opt`, `P_grid` signs/units | Same semantics |
| Existing no-grid-charge/no-discharge flags | Same behaviour |

### Implementation Tracker

| Step | Status | PR/branch | Scope | Public behaviour | Exit criteria | Docs/schema |
| --- | --- | --- | --- | --- | --- | --- |
| 0. Single-inverter behaviour freeze | Done | `multi-batt` @ `701b2c2c` | Added golden/characterisation coverage for the existing single-inverter path before refactoring. | None | Commit records coverage for no-extra-config optimisation output, flat REST payload behaviour, HA publish names, `P_batt`/`SOC_opt`/`P_grid` signs and units, and existing no-grid-charge/no-discharge flag behaviour. | None |
| 1. Extract block `0` battery + hybrid internals | Done | `multi-batt` @ `ca5e6189` | Introduced internal block `0` wrappers for battery and hybrid inverter config/runtime/variables/results while keeping exactly one internal block. | None | Step 0 golden tests still matched current behaviour. No `hybrid_inverter_config_1`, no new columns, no publisher changes. | Developer notes only if needed |
| 2. Parse indexed config, allowlist, validation, cache invalidation | Done | `multi-batt` @ `e88d0294` | Added `hybrid_inverter_config_N` parsing, contiguous index validation, block-local allowlist enforcement, disabled multi-block solve gates, and structural cache keys. | Extra blocks validate, then raise "multi-block solve not enabled". | Local verification passed: Step 2 targeted tests `214 passed, 7 skipped`; full suite `694 passed, 7 skipped, 28 xfailed, 4 subtests passed`; `ruff check` passed; `git diff --check` passed; two final review agents approved. External CI not run locally. | `param_definitions.json`, config defaults/associations, config docs, generated OpenAPI artifact updated to satisfy repository artifact checks |
| 3. Add nested runtime merge | Done | `multi-batt` Step 3 commit | Flat runtime keys override block `0`; `hybrid_inverter_config_N.*` overrides existing configured block `N`. Runtime cannot create blocks. | Still no multi-block solve. | Local focused verification passed for runtime merge, command-line gate, web redaction, parser/optimizer guard, runtime/OpenAPI/schema, docs build, lint, and single-inverter compatibility guard. Two independent audits confirmed Step 3 is implemented and complete. Full `pytest tests/` hit three Solcast forecast quota-state failures in the shared helper container; those nodes passed with isolated `TMPDIR`. External CI not run locally. | `runtime_params.json`, OpenAPI/runtime docs |
| 4. Resolve per-block PV sources | Done | `multi-batt` Step 4 commit | Implemented runtime `hybrid_inverter_config_N.pv_power_forecast` validation for configured extra PV-enabled blocks in `split_pv`. Block `0` remains on the existing PV path; block-local sensor retrieval/PVLib/CSV support is deferred. Multi-block solve remains disabled. | Validated inputs only. | Local verification passed: combined focused Step 4/single-inverter guard tests `116 passed, 7 skipped`; `ruff check` passed; docs build passed; `git diff --check` passed. Two independent completion agents confirmed "Step 4 per-block PV sources is implemented and is complete." External CI not run locally. | Config/runtime PV docs |
| 5. Add per-block battery variables and SOC constraints | Done | `multi-batt` Step 5 commit | Added private-gated internal per-block battery variables, same-block direction gates, SOC constraints, aggregate private diagnostics, and focused tests. | Internal/private constructor path only; public multi-block solve still raises `multi-block solve not enabled` before external setup. | Local verification passed: focused Step 5/public-gate/single-inverter guard tests `15 passed`; `ruff check` passed; `git diff --check` passed; public docs/schema/command/web/forecast drift check had no output. Two independent completion agents confirmed "Step 5 is implemented and is complete." External CI not run locally. | No public docs/schema changes |
| 6. Add `battery_mode_lock: site` | Done | `multi-batt` Step 6 commit | Added the static `battery_mode_lock` config key, strict public battery-only multi-block admission, site-level binary mode variables, and constraints so all public multi-block batteries charge/idle or discharge/idle together. | First safe public multi-block battery-only solve path is admitted when PV, hybrid, curtailment, and topology flags are disabled; unsupported multi-block structures still raise before solving. | Local verification passed: combined focused optimization/command/parser/schema/single-inverter run `342 passed, 7 skipped, 191 warnings, 8 subtests passed`; docs build via `uv run sphinx-build -b html docs docs/_build` passed with 11 warnings; `ruff check .` passed; `git diff --check` passed; two final review agents approved. External CI not run locally. | Config defaults, associations, parameter definitions, generated OpenAPI artifact, config docs, and runtime docs updated |
| 7. Add block-indexed hybrid inverter variables/constraints | Done | `multi-batt` Step 7 commit | Implemented block-indexed `p_dc_ac_i`, `p_ac_dc_i`, `is_dc_sourcing_i`, `p_hybrid_inverter_i`, per-block AC/DC limits, split-PV curtailment constraints, cache-safe nested runtime PV updates, and minimal AC-side site supply connection. | At Step 7, public path admitted only split-PV, battery-backed hybrid blocks with `battery_mode_lock: site` and nested runtime `pv_power_forecast` for every extra PV block; topology flag admission was deferred to Step 8. | Local verification passed: command-line/cache subset `6 passed, 45 deselected, 3 subtests passed`; direct cache-key regression `1 passed`; focused cache group `3 passed, 28 deselected`; optimizer subset `10 passed, 183 deselected, 10 warnings, 15 subtests passed`; Step 5/6 guard subset `8 passed, 185 deselected, 8 warnings`; schema/OpenAPI/config `85 passed, 7 skipped`; single-inverter command-line guard `4 passed, 47 deselected`; `sphinx-build`, `ruff check .`, and `git diff --check` passed. Two read-only auditors confirmed Step 7 is implemented and complete. External CI not run locally. | Config/runtime docs and parameter/OpenAPI descriptions updated. |
| 8. Enforce topology and site import/export constraints | Done | `multi-batt` @ `e05dd846` | Kept and verified existing aggregate site import/export limits on `p_grid_pos` and `p_grid_neg`, and admitted top-level `set_nocharge_from_grid`, `set_nodischarge_to_grid`, and `set_battery_first_priority` for public split-PV hybrid multi-block solving. `set_battery_first_priority` is admitted for public battery-only multi-block solving. `set_nocharge_from_grid` and `set_nodischarge_to_grid` still reject for public battery-only multi-block solving, and all three topology flags remain invalid inside `hybrid_inverter_config_N`. | Split-PV hybrid multi-block solves can use the supported topology flags with aggregate site semantics. `set_nocharge_from_grid` uses aggregate raw split-PV plus aggregate signed battery charging; it is not block-local source tracking. `set_nodischarge_to_grid` uses site hybrid mode semantics where shared site discharge mode implies import/non-export grid direction. `set_battery_first_priority` uses aggregate fleet stored energy. `maximum_power_from_grid` and `maximum_power_to_grid` remain aggregate site limits on `p_grid_pos` and `p_grid_neg`. | Local verification passed: focused red tests failed before implementation for expected admission/topology reasons; focused green command passed `12 passed, 9 warnings, 16 subtests passed`; Step 8 topology subset `6 passed, 194 deselected`; command-line admission subset `2 passed, 49 deselected, 5 subtests passed`; Step 7 hybrid guard subset `17 passed, 183 deselected, 17 subtests passed`; Step 5/6 guard subset `11 passed, 189 deselected, 2 subtests passed`; cache subset `2 passed, 44 deselected, 3 subtests passed`; issue #834 guards `2 passed`; issue #936 guards `3 passed`; existing grid flag guards `2 passed`; grid power-limit guards `2 passed, 198 deselected`; no-Step-9-columns guard `1 passed`; schema/OpenAPI/hybrid config tests `85 passed, 7 skipped`; Sphinx docs build passed with 13 existing project warnings; `ruff check .`, `py_compile`, and `git diff --check` passed. `docs/plans/` is ignored and `git ls-files docs/plans` returned no tracked files. Two final read-only auditors approved after tracker corrections, and two confirmation subagents confirmed `Step 8 is implemented and is complete.` External CI not run locally. | Config/runtime docs and parameter/OpenAPI descriptions updated |
| 9. Add result columns and aggregate diagnostics | Done | `multi-batt` Step 9 commit | Added the pre-Step-11 public multi-block optimizer result/CSV columns while keeping block `0` names unchanged: `P_batt_N`, `SOC_opt_N`, `P_hybrid_inverter_N`, `P_PV_N`, and `P_PV_curtailment_N` for extra blocks. Added aggregate diagnostics `P_batt_total`, `SOC_opt_total`, `P_hybrid_inverter_total`, `P_PV_total`, and `P_PV_curtailment_total` when curtailment exists. Step 11 supersedes this public naming contract before external review. | Stable pre-Step-11 optimizer result/CSV schema for multi-block plans. `P_PV_total` is an AC-equivalent post-curtailment PV availability diagnostic, not source tracking. `publish_data()` and Home Assistant publishing remain single-inverter output until Step 10. | Local verification passed: Step 9 result-column subset `6 passed, 6 warnings`; schema/publisher/OpenAPI subset `4 passed`; Step 7/8 topology subset `8 passed, 196 deselected`; Step 5/6 battery subset `11 passed, 193 deselected, 2 subtests passed`; no-Step-10 publisher subset `2 passed, 49 deselected`; schema/OpenAPI/config subset `88 passed, 7 skipped`; targeted utility fixture regressions `3 passed`; full canonical `pytest tests/` passed `791 passed, 7 skipped, 28 xfailed, 294 warnings, 31 subtests passed`; Sphinx docs build passed with 14 existing project warnings; `ruff check .`, `py_compile`, `git diff --check`, OpenAPI regeneration, and committed OpenAPI match passed. Two final read-only auditors found no blocking issues; low-risk audit feedback was incorporated. Two independent completion subagents confirmed `Step 9 is implemented and is complete`. External CI not run locally. | `docs/plan_output_schema.md`, generated OpenAPI artifact |
| 10. Add HA publisher suffixing and command bridge examples | Done | `multi-batt` Step 10 commit | Published supported extra block battery/SOC/hybrid/PV result columns with `_<N>` entity suffixes while keeping block `0` entities unchanged. Added command bridge examples as docs only. | Stable HA entity surface. Aggregate totals remain diagnostics and block-local deferrables remain reserved/future. | Local verification passed: Step 10 focused publisher/schema tests `3 passed`; OpenAPI/schema subset `35 passed, 7 skipped`; publisher/deferrable guard subset `7 passed, 101 deselected`; Step 9 result-column guard subset `5 passed, 199 deselected, 5 warnings`; full canonical `pytest tests/` passed `792 passed, 7 skipped, 28 xfailed, 294 warnings`; Sphinx docs build passed with no warnings reported in the final run; `ruff check .` passed; `git diff --check` passed; `git ls-files docs/plans` returned no tracked files. Two independent final auditors confirmed `Step 10 is implemented and is complete`. External CI not run locally. | `docs/publish_data.md`, `docs/plan_output_schema.md`, generated OpenAPI artifact |
| 11. Correct public multi-inverter contract | Done | `multi-batt` working tree | Added explicit `multi_inverter_mode`, kept single-inverter mode as the default, changed public multi-inverter numbering to active inverters `1..N`, retained raw upstream runtime logging, grouped publisher output by forecast family, and converted multi-inverter result/entity semantics to unsuffixed site totals plus `_1.._N` inverter-specific values. | Single-inverter mode remains unchanged and ignores indexed inverter config. Multi-inverter mode is explicit. Top-level inverter/battery/PV config is ignored as an active inverter in multi mode; configured `hybrid_inverter_config_1..N` are active; static `_0` is ignored with a warning; runtime `_0` hard-fails; runtime nested blocks cannot create inverters; PV-disabled hybrid battery inverters do not emit PV columns/entities; battery/SOC publishing emits `N + 1` values: total plus one per active inverter. | Local verification passed: new PV-disabled first-inverter regression `1 passed`; adjacent parser/result/publisher subset `61 passed`; full Step 11 regression set `613 passed, 7 skipped, 215 warnings, 31 subtests passed`; `ruff check` on touched Python/tests passed; `git diff --check` passed. Earlier Step 11 docs build passed with existing project warnings and no Step 11-specific documentation build failure. Two independent auditors returned `NO BLOCKERS` after the final PV-disabled inverter fix. External CI not run locally. | `multi-batt.md`, config/runtime/publish/result docs, config defaults/associations, parameter/runtime definitions, generated OpenAPI artifact |
| 12. Publish-data validation fix, nested runtime compatibility, browser config support tests, and migration guide | Done | `multi-batt` working tree | Fixed the multi-inverter `publish-data` bug at the action/input-preparation boundary so publishing saved results does not require split-PV runtime forecasts. Aligned nested multi-inverter runtime handling with released EMHASS top-level behaviour for scalar charge/discharge caps, SOC bounds, target SOC defaults, `soc_init` recovery, and `soc_final` clamping. Added review-readiness coverage proving the existing browser configuration surface still renders and saves supported scalar config fields while preserving manual indexed inverter sections. Added a concise upstream-facing migration and fallback guide. | `publish-data` can publish a saved multi-inverter result without callers resending nested PV forecasts or `multi_inverter_mode`; saved result columns determine total and `_N` per-inverter publication. Nested inverter runtime behaves like current top-level EMHASS runtime for supported battery fields. No result-column semantics or Home Assistant entity naming changes. Multi-inverter configs remain advanced/manual indexed config until a deliberate UI editor design exists. | Local verification passed: nested/runtime parser subset `76 passed`; command-line/publish suite `112 passed, 6 warnings`; multi-inverter optimizer selector `39 passed, 168 deselected, 39 warnings`; schema/web suite `62 passed, 8 skipped`; host Node JS list-view save replay `1 passed`; Sphinx docs build passed with 15 existing project warnings; `git diff --check` passed. Two independent auditors confirmed the runtime/publish and docs/browser findings were resolved after focused re-audit. External CI not run locally. | `docs/config.md`, browser config script/test coverage, focused runtime/publish tests; keep `multi-batt.md` out of upstream PR material |
| 13. Add soft multi-inverter SOC balancing | Not started | TBD | Add a site-level soft objective term that discourages active multi-inverter batteries from drifting away from the capacity-weighted fleet SOC. Add only `battery_soc_balance_cost`; do not expose `battery_pv_headroom_cost` until PV-headroom behaviour is implemented. | Single-inverter mode remains unchanged. Multi-inverter mode remains physically constrained by existing SOC bounds, power caps, grid limits, topology flags, and mode lock. The upstream default is `battery_soc_balance_cost: 0.0` for compatibility; documentation and local test configs may recommend `0.05` as a practical starting value for most multi-inverter sites. | Exit requires focused validation, cache, optimiser, and docs/schema tests: zero cost is an exact no-op, positive cost changes a deterministic equal-economic-cost multi-inverter case toward capacity-weighted SOC balance, heterogeneous capacities balance SOC fraction rather than equal kWh, runtime override works, nested usage is rejected, and single-inverter output is unaffected. | Config defaults, parameter/runtime metadata, config docs; no publisher/result-column/entity changes |

Per-timestep runtime cap forecasts, final-constraint modes, tie-break modes, and
SOC-dependent power curves should wait until the v1 indexed-inverter model is
stable.

### Step 11 Detailed Plan

Step 11 is a design correction before external review. It should be implemented
as a reviewable sequence of narrow commits, not as another broad rewrite.

1. Land the small compatibility fixes already identified:
   - restore upstream-compatible raw runtime logging for
     `Passed runtime parameters: ...`
   - group publisher post order by measurement family
   - keep the local ignored test config aligned with the physical site, including
     `set_use_pv: false` for the inverter that has no solar

2. Add explicit mode selection:
   - add `multi_inverter_mode` with values `single` and `multi`
   - default to `single`
   - allow config and runtime override
   - ensure indexed configs are inert in `single` mode
   - include the mode in optimiser cache keys when it changes structure

3. Update parsing and validation:
   - static `hybrid_inverter_config_0` is ignored with one clear warning
   - runtime `hybrid_inverter_config_0` hard-fails
   - `multi` mode requires contiguous `hybrid_inverter_config_1..N`
   - nested runtime `hybrid_inverter_config_N` is valid only for configured
     inverter `N` while `multi` mode is active
   - flat single-inverter SOC/battery/inverter runtime keys are not mapped to
     inverter `1` in multi mode

4. Remap active optimiser inverters:
   - single-inverter mode continues to use the current top-level path
   - multi-inverter mode builds active inverter objects from
     `hybrid_inverter_config_1..N`
   - top-level inverter/battery/PV values are ignored as active inverter values
     in multi mode
   - no `_0` result columns are produced

5. Rename multi-inverter result semantics:
   - `P_batt`, `SOC_opt`, `P_hybrid_inverter`, and `P_PV` are totals in multi
     mode
   - `P_batt_1..N`, `SOC_opt_1..N`, `P_hybrid_inverter_1..N`, and `P_PV_1..N`
     are per-inverter values
   - remove or replace previous public `*_total` diagnostics unless a separate
     compatibility alias design is approved
   - define total `SOC_opt` as stored-energy weighted fleet SOC

6. Update publisher semantics:
   - single-inverter mode publishes existing entities unchanged
   - multi-inverter mode publishes total unsuffixed entities plus `_1.._N`
     per-inverter entities
   - battery and SOC forecasts publish `N + 1` sensors in multi mode
   - PV-disabled inverters do not publish per-inverter PV forecast sensors
   - friendly names and docs should say `inverter N`, not `block N`
   - command bridge examples must use suffixed per-inverter sensors

7. Update docs/schema:
   - update config docs, runtime docs, publish docs, and plan output schema
   - update `runtime_params.json`, OpenAPI, parameter definitions/defaults, and
     associations only where the public surface actually changes
   - keep public terminology as single-inverter / multi-inverter

8. Verification:
   - keep Step 0 single-inverter golden tests unchanged and passing
   - add a test where indexed configs are present but mode is `single`, proving
     identical single-inverter output/entities
   - add config/runtime activation tests for `multi`
   - add static `_0` warning and runtime `_0` rejection tests
   - add contiguous active inverter index tests
   - add result-column tests for unsuffixed totals plus `_1.._N`
   - update publisher tests for `N + 1` battery/SOC sensors and grouped order
   - add PV-disabled inverter publish/result tests
   - run focused command-line, optimisation, web, schema/OpenAPI, docs, Ruff,
     and `git diff --check`

### Step 12 Detailed Plan

Step 12 is a review-readiness and bug-fix step. It should not rename result
columns or change Home Assistant entity naming. Its purpose is to fix
publish-only validation, restore nested runtime compatibility with the released
top-level REST contract, reduce upstream review risk by proving the existing
browser configuration surface still works, and replace design handoff prose with
concise user-facing migration documentation.

1. Keep `multi-batt.md` out of upstream PR material:
   - treat this file as local project tracking only
   - do not include it in an upstream implementation PR unless maintainers ask
     for an RFC/design appendix
   - keep any implementation docs in the existing public documentation files

2. Fix the multi-inverter `publish-data` split-PV validation bug:
   - `publish-data` should publish the saved optimisation result and should not
     require callers to resend `hybrid_inverter_config_N.pv_power_forecast`
   - implement the fix in action-specific input preparation, not only inside
     `publish_data()`: `publish-data` should build only the minimal publishing
     context, while optimisation actions still build forecast and optimiser
     inputs
   - split-PV nested runtime PV validation should remain required for
     optimisation actions that build a new input horizon
   - publishing a saved multi-inverter result must not validate nested PV arrays
     against a freshly generated default horizon
   - `publish-data` must not require callers to resend `multi_inverter_mode` or
     nested optimiser runtime to publish a saved multi-inverter result; saved
     result columns determine total and `_N` per-inverter publication
   - `publish-data` should still process publishing controls that affect the
     act of publishing, including `publish_prefix`, existing custom publish
     entity descriptors, and existing `continual_publish` behaviour
   - optimiser-only runtime fields that cannot affect a saved result, including
     load/price/PV forecast arrays, nested PV forecasts, nested SOC values,
     nested caps, and solver inputs, should be ignored or rejected with a clear
     action-specific message during `publish-data`
   - static config needed to create `RetrieveHass` and publishing entity
     descriptors should still be parsed; `Forecast` and `Optimization` objects
     should not be created for publish-only actions
   - add a regression where optimisation uses a 47-slot horizon and
     `publish-data` is called with an empty or prefix-only payload
   - prove that the saved result publishes supported unsuffixed total entities
     and `_N` per-inverter entities without a validation-only PV padding
     workaround
   - add prefix/fallback regressions:
     - empty payload publishes from `opt_res_latest.csv`
     - prefix-only payload with no matching saved entity JSON falls back to
       `opt_res_latest.csv`
     - prefix-only payload with matching saved entity JSON keeps the existing
       saved-entity publish behaviour
   - stale saved results must not be revalidated against a fresh forecast
     horizon; publish should select the closest timestamp from the saved result
     and fail only when the saved result is missing or incomplete
   - keep partial-publish/error reporting behaviour explicit; do not hide real
     Home Assistant post failures behind this fix

3. Align nested inverter battery runtime behaviour with existing EMHASS:
   - allow nested scalar runtime `battery_charge_power_max` and
     `battery_discharge_power_max` when the matching configured inverter has
     `set_use_battery: true`
   - apply those scalar caps to the matching inverter for the current request
     just as the existing top-level REST payload applies fleet battery caps
   - reject non-finite, non-numeric, zero, or negative nested scalar caps
   - keep per-timestep cap forecast arrays out of v1 unless explicitly designed
     and tested separately
   - allow nested runtime
     `battery_minimum_state_of_charge` and
     `battery_maximum_state_of_charge` when the matching configured inverter has
     `set_use_battery: true`
   - allow nested runtime `battery_target_state_of_charge` as the independent
     default for both nested `soc_init` and nested `soc_final`; passing only one
     of `soc_init` or `soc_final` must not copy that value to the other
   - apply runtime SOC bounds before interpreting nested `soc_init`,
     `soc_final`, `soc_target`, and `battery_target_state_of_charge`
   - if `soc_init` is outside the effective bounds, warn and keep the supplied
     value for optimisation recovery, matching the existing top-level behaviour
   - add per-inverter SOC recovery parameters/constraints where required so an
     out-of-bounds nested `soc_init` can recover like the released top-level
     path rather than merely avoiding early validation and then becoming
     infeasible at the first stored-energy bound
   - if `soc_final` is below the effective minimum, warn and set it to the
     effective minimum, matching the existing top-level behaviour
   - if `soc_final` is above the effective maximum, warn and set it to the
     effective maximum, matching the existing top-level behaviour
   - keep invalid effective SOC bounds as hard errors, including non-finite
     values, values outside `[0, 1]`, and minimum greater than or equal to
     maximum
   - document that nested battery caps and SOC bounds are request-time
     overrides, not a replacement for maintaining sane static inverter config
   - document the compatibility mapping from existing top-level REST payloads:
     `battery_charge_power_max`, `battery_discharge_power_max`, `soc_init`,
     `soc_final`, `battery_minimum_state_of_charge`,
     `battery_maximum_state_of_charge`, and `battery_target_state_of_charge`
     should have per-inverter nested equivalents in multi-inverter mode

4. Classify runtime keys before changing validation:

   | Runtime key group | Multi-inverter runtime location |
   | --- | --- |
   | Per-inverter split-PV forecast | Nested `hybrid_inverter_config_N.pv_power_forecast` for PV-enabled split-PV inverters during optimisation actions |
   | Per-inverter battery runtime | Nested `soc_init`, `soc_final`, `soc_target`, `soc_target_timestep`, SOC bounds, target SOC, scalar charge cap, and scalar discharge cap |
   | Site forecasts and horizon | Top level only: `prediction_horizon`, `load_power_forecast`, top-level `pv_power_forecast`, `load_cost_forecast`, `prod_price_forecast` |
   | Deferrable runtime | Top level only: `number_of_deferrable_loads` and all deferrable schedule/power arrays |
   | Cost/solver controls | Top level only: `alpha`, `beta`, `current_period_peak`, and optimiser action inputs |
   | Publish controls | Top level only: `publish_prefix`, custom publish entity descriptors, `entity_save`, and `continual_publish` |
   | Forecast/cache controls | Top level only: weather/history/cache/runtime forecast controls |

   Top-level-only runtime keys should remain invalid inside
   `hybrid_inverter_config_N` and should be covered by focused validation tests.

5. Add browser/static config support tests:
   - verify `/configuration` still serves the browser configuration page
   - verify `/get-config` and `/set-config` still round-trip supported scalar
     config fields after adding `multi_inverter_mode`,
     `multi_hybrid_inverter_pv_mode`, and `battery_mode_lock`; use real
     temporary config/defaults/associations data rather than mocked conversion
     helpers so the test proves persistence through the existing config
     pipeline
   - verify the three browser-supported scalar config fields are aligned across
     `param_definitions.json`, `config_defaults.json`, and `associations.csv`
   - verify indexed `hybrid_inverter_config_N` sections are not emitted as
     repeated generated UI defaults in `param_definitions.json` or
     `config_defaults.json`
   - verify the JavaScript config renderer can render the added scalar fields
     without missing input-type handlers, broken escaping, or malformed HTML
   - Node replay or static DOM-light renderer tests are sufficient for the
     current UI architecture; do not add Playwright unless the existing renderer
     cannot be exercised otherwise
   - add targeted select-render assertions for the three added scalar fields,
     because generic input-type coverage only proves a handler exists

6. State the browser UI contract clearly:
   - the existing browser config UI remains supported for scalar/global config
     fields
   - indexed inverter configs are advanced/manual config in v1
   - no generated browser editor for arbitrary `hybrid_inverter_config_N`
     dictionaries is promised in this step
   - future first-class UI editing for indexed inverter configs should be a
     separate design, because it needs dynamic repeated sections and validation
     feedback that the current scalar metadata model does not provide

7. Add a clean migration and fallback guide:
   - put the migration/fallback checklist in one public location, preferably
     `docs/config.md`; keep `docs/passing_data.md`, `docs/publish_data.md`, and
     `docs/plan_output_schema.md` to short cross-references or local deltas
   - start from an existing working single-inverter config
   - leave the top-level config unchanged
   - add `hybrid_inverter_config_1..N` sections while leaving
     `multi_inverter_mode` unset or `single`
   - restart/validate and confirm existing single-inverter output and entity
     names are unchanged
   - set `multi_inverter_mode: multi`
   - for split-PV hybrid systems, set
     `multi_hybrid_inverter_pv_mode: split_pv` and provide nested runtime
     `hybrid_inverter_config_N.pv_power_forecast` for each PV-enabled inverter
   - verify result columns and published entities: unsuffixed values are site
     totals, `_1.._N` values are inverter-specific, and no `_0` values exist
   - fall back by setting `multi_inverter_mode: single` or removing the mode
     override; the unchanged top-level config resumes the existing
     single-inverter path

8. Tighten public docs for upstream review:
   - reduce design-history language in public docs
   - avoid local terminology such as tracker steps or project-specific battery
     examples
   - keep docs focused on user-visible configuration, runtime payloads, result
     columns, published entities, sign conventions, and fallback behaviour
   - keep topology caveats short and tied to concrete supported flags
   - remove or rewrite any text that implies `multi-batt.md` is public product
     documentation
   - keep the 47-slot horizon case as a regression-test detail only; public docs
     should describe that `publish-data` publishes saved results without
     requiring runtime PV forecasts

9. Verification:
   - run targeted publish-data regression tests proving split-PV multi-inverter
     publishing does not require nested runtime PV forecasts
   - exercise the failing route, not only direct `publish_data()`: cover
     `set_input_data_dict(..., "publish-data")` with `{}` and with
     `{"publish_prefix": "..."}` under split-PV multi-inverter config and prove
     no `Forecast` or `Optimization` object is created
   - POST `/action/publish-data` with a saved 47-row multi-inverter
     `opt_res_latest.csv` and no nested PV runtime arrays
   - include a 47-slot saved-result publish regression so the old 48-slot
     validation failure cannot return
   - run targeted nested battery runtime tests proving scalar cap overrides,
     effective runtime bounds, warning-only/recovery-capable `soc_init`,
     clamped `soc_final`, independent target-SOC defaults for omitted
     `soc_init`/`soc_final`, and hard errors for invalid effective bounds or
     caps
   - run validation tests proving top-level-only runtime keys are rejected inside
     `hybrid_inverter_config_N`
   - keep single-inverter `dayahead-optim` and `naive-mpc-optim` runtime
     validation unchanged, especially forecast payload shape and length checks
   - run targeted web/config tests for `/configuration`, `/get-config`,
     `/set-config`, static metadata, and JavaScript renderer coverage
   - run schema/OpenAPI drift tests after any doc/schema metadata edits
   - run docs build
   - run `ruff check` for any touched Python tests
   - run `git diff --check`
   - report that no optimiser result semantics or Home Assistant entity naming
     changed in Step 12

### Step 13 Detailed Plan

Step 13 adds one solver-compatible soft preference for multi-inverter battery
coordination. It should be narrow and reviewable: add SOC balancing only, keep
PV headroom deferred, and avoid changing the public result or publish surface.

Two independent plan reviewers agreed that the linear formulation is compatible
with the existing CVXPY/HiGHS optimiser style, and both recommended keeping the
released default disabled for compatibility while documenting `0.05` as the
recommended multi-inverter starting value.

1. Add one public setting:
   - add top-level `battery_soc_balance_cost`
   - default it to `0.0` in upstream defaults
   - document the recommended multi-inverter starting value as `0.05`
   - define units as virtual `currency/kWh/h`
   - allow top-level runtime override if the runtime schema requires explicit
     listing for scalar optimiser controls
   - reject negative, non-finite, and non-numeric values
   - reject `hybrid_inverter_config_N.battery_soc_balance_cost` in static config
     and runtime payloads because this is a site-level coordination policy

2. Do not add PV headroom as a no-op public key:
   - do not add `battery_pv_headroom_cost` to defaults, schemas, docs, or runtime
     params in this step
   - keep PV-headroom policy as future work requiring its own objective
     definition and tests
   - local discussion may continue to use `battery_pv_headroom_cost: 0.0` as a
     design placeholder, but the implementation must not expose it until it has
     real behaviour

3. Implement SOC balancing as a soft objective:
   - apply only when `multi_inverter_mode: multi`
   - apply only when at least two active battery-enabled inverters exist
   - apply only when `battery_soc_balance_cost > 0`
   - build from existing per-inverter stored-energy expressions, not from
     result columns or published entities
   - do not add hard balancing constraints
   - do not change single-inverter behaviour even if the setting is positive

4. Use capacity-weighted fleet SOC:

   ```text
   fleet_soc[t] = sum_i(stored_energy_i[t]) / sum_i(capacity_i)
   target_energy_i[t] = capacity_i * fleet_soc[t]
   ```

   This balances SOC fraction while respecting different battery capacities.
   It matches the current multi-inverter total `SOC_opt` semantics better than
   equal-kWh balancing.

5. Add linear deviation variables:

   ```text
   deviation_i[t] >= stored_energy_i[t] - target_energy_i[t]
   deviation_i[t] >= target_energy_i[t] - stored_energy_i[t]
   deviation_i[t] >= 0
   ```

   Penalise:

   ```text
   0.5 * battery_soc_balance_cost * time_step
       * sum_i,t(deviation_i[t] / 1000)
   ```

   The `0.5` avoids double-counting fleet imbalance because one battery above
   the fleet target and another below it represent the same rebalance gap.

6. Keep cache behaviour correct:
   - include the setting in structural cache invalidation if enabling it creates
     new variables or constraints
   - add a regression where a cached optimiser path is reused after changing
     `battery_soc_balance_cost` from `0.0` to positive and from positive back to
     `0.0`

7. Add focused tests:
   - validation accepts finite nonnegative values and rejects negative, NaN,
     infinity, and nonnumeric values
   - nested config/runtime use hard-fails
   - single-inverter mode is unaffected by a positive value
   - multi-inverter mode with absent or `0.0` cost is a behavioural no-op
   - positive cost changes a deterministic equal-economic-cost case toward
     balanced SOC without changing total physical feasibility
   - heterogeneous capacities converge toward equal SOC fraction, not equal kWh
   - total `P_batt` and total `SOC_opt` remain coherent
   - runtime override can enable and disable the soft objective safely

8. Update docs/schema narrowly:
   - update config defaults and parameter metadata
   - update runtime metadata only if this scalar is exposed as a runtime
     override
   - update `docs/config.md` with unit, default, recommended `0.05`, tuning
     guidance, and a clear note that it is a soft preference
   - do not change plan output schema, Home Assistant publish docs, entity names,
     result-column names, or command bridge examples

9. Verification:
   - run focused config/runtime validation tests
   - run focused multi-inverter optimiser tests
   - run single-inverter golden/compatibility guard tests touched by this path
   - run schema/browser metadata checks affected by config metadata edits
   - run docs build if public docs change
   - run `ruff check` for touched Python/tests
   - run `git diff --check`

## Validation Rules

| Rule | Result |
| --- | --- |
| `multi_inverter_mode` unset | Single-inverter mode |
| `multi_inverter_mode: single` | Single-inverter mode |
| Indexed configs present while mode is `single` | Ignored for active optimisation; warn clearly if useful, but do not change output |
| `multi_inverter_mode: multi` without `hybrid_inverter_config_1` | Hard error |
| Static `hybrid_inverter_config_0` appears in config | Ignore with warning |
| Nested runtime `hybrid_inverter_config_0` appears | Hard error |
| Active inverter index skipped in multi mode | Hard error |
| Indexed inverter contains `sensor_power_load_no_var_loads` | Hard error unless explicitly allowed; load is site-level |
| Indexed inverter contains a config-time PV source/model key before Step 4 implements that source | Hard error in initial v1 |
| `site_pv` and indexed inverter contains a PV source or PV runtime forecast | Hard error in v1 |
| `split_pv` and top-level PV appears to be site total | Hard error if detectable; otherwise clear warning that top-level PV is not active inverter PV in multi mode |
| Active inverter has `set_use_battery: true` but missing battery capacity/power | Hard error |
| Indexed inverter contains deferrable-load config | Hard error in v1 |
| Indexed inverter has custom entity base | Suffix still appended unless explicitly marked absolute |
| Runtime inverter present without matching configured active inverter | Hard error |
| Runtime nested key is not valid for that inverter | Hard error |
| Runtime nested inverter appears while mode is `single` | Hard error unless a documented transition warning/ignore rule is implemented |
| Runtime values are non-finite or negative where power/capacity is required positive | Hard error |
| Efficiency is outside `0 < efficiency <= 1` | Hard error |
| `battery_minimum_state_of_charge >= battery_maximum_state_of_charge` | Hard error |
| Per-timestep runtime cap forecast appears without explicit feature support | Hard error in v1 |
| Future-only final-constraint mode field appears | Hard error in v1 |
| Future-only SOC-dependent power-curve field appears | Hard error in v1 |
| Flat single-inverter SOC/battery/inverter runtime key appears in multi mode | Warn/ignore for active inverters; never map to inverter `1` silently |

Structural fields must participate in cache invalidation:

- mode (`single` vs `multi`)
- number of active inverters
- active inverter indexes
- multi-inverter PV mode
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
| Add `hybrid_inverter_config_1` but leave mode `single` | Identical single-inverter outputs and HA entities |
| Runtime `multi_inverter_mode: multi` with configured `hybrid_inverter_config_1..N` | Multi-inverter solve is active |
| Static `hybrid_inverter_config_0` | Ignored with warning |
| Runtime `hybrid_inverter_config_0` | Hard validation error |
| Multi mode with skipped inverter index | Hard validation error |
| Multi mode with three battery-enabled inverters | Publishes `sensor.p_batt_forecast` total plus `sensor.p_batt_forecast_1`, `_2`, `_3` |
| Multi mode with three battery-enabled inverters | Publishes `sensor.soc_batt_forecast` fleet SOC plus `sensor.soc_batt_forecast_1`, `_2`, `_3` |
| Multi result columns | `P_batt`, `SOC_opt`, `P_hybrid_inverter`, and `P_PV` are totals; `_1.._N` columns are per-inverter |
| No `_0` result/publish names | No `P_batt_0`, `SOC_opt_0`, `sensor.p_batt_forecast_0`, etc. |
| `split_pv` with indexed PV | `P_PV` total and `P_PV_N` per PV-enabled inverter are produced; curtailment uses the same suffix rule |
| PV-disabled inverter | No `P_PV_N` result or `sensor.p_pv_forecast_N` publish entity for that inverter |
| Initial v1 indexed inverter config-time PV source | Hard validation error unless Step 4 explicitly implemented that source |
| Battery 62 has 2x capacity, same charge cap | Optimiser starts charging early enough; no fleet-power borrowing |
| Inverter 1 full | `P_batt_1` cannot charge while `P_batt_2`/`P_batt_3` may charge |
| Inverter 3 still empty after 1/2 full | `P_batt_3` continues charging at its own cap |
| `battery_mode_lock: site` | No mixed charge/discharge across active inverters |
| Site grid import/export limits | Enforced on aggregate site flow |
| AC/DC efficiency or curtailment differs from raw PV plus battery power | `P_grid` uses `P_hybrid_inverter_N` / AC-side site supply, not raw DC-side variables |
| `set_nodischarge_to_grid` hybrid path | Existing topology behaviour preserved |
| `set_nodischarge_to_grid` AC-coupled path | Existing topology behaviour preserved |
| `set_nocharge_from_grid` with curtailment/import edge case | Behaviour is either preserved and documented or strengthened and tested |
| `P_batt` sign | Positive discharge, negative charge |
| Command bridge in multi mode | Uses `setpoint_N = -P_batt_N`; never uses total `P_batt` for one inverter |
| Runtime inverter without configured active inverter | Hard validation error |
| Skipped config index | Hard validation error |
| `split_pv` double-count risk | Hard validation error if detectable |
| Cache structural change | Rebuilds optimiser |
| Runtime SOC/scalar-cap value change only | Reuses optimiser parameters when shape is unchanged |
| Aggregate values | Unsuffixed `P_batt`, `SOC_opt`, `P_hybrid_inverter`, and `P_PV` equal their documented formulas in multi mode |
| Publisher order | Comparable values are grouped by measurement family |
| Runtime logging | `Passed runtime parameters:` keeps upstream raw value formatting |
| Future-only SOC modes or SOC power curves | Hard validation error in v1 |

## Documentation and Schema Cadence

Docs and schema updates should land with the public surface they describe, not as
one final cleanup PR.

| Implementation point | Docs/schema update |
| --- | --- |
| Parser and validation | `src/emhass/static/data/param_definitions.json`, `src/emhass/data/config_defaults.json`, `src/emhass/data/associations.csv`, config docs, add-on/options surface if applicable, and cache-key docs/tests |
| Runtime merge | `src/emhass/static/data/runtime_params.json`, OpenAPI/runtime docs |
| PV source resolution | PV mode and runtime forecast examples |
| Result builder | `docs/plan_output_schema.md` with unsuffixed totals and per-inverter columns |
| Publisher | `docs/publish_data.md` with total/per-inverter publishing and command bridge expectations |
| Release preparation | Migration notes and full examples |

Migration note:

Existing single-inverter configs remain unchanged. Multi-inverter mode is
explicit and uses the same inverter-local battery / hybrid inverter / PV
parameter names nested under `hybrid_inverter_config_1..N`. The top-level config
remains the normal single-inverter config and is not an active inverter in multi
mode.

## Revised Conclusion

Use explicit multi-inverter mode with indexed hybrid inverter configs:

```yaml
multi_inverter_mode: multi

hybrid_inverter_config_1:
  ...
hybrid_inverter_config_2:
  ...
```

Use existing names unchanged in single-inverter mode. In multi-inverter mode,
unsuffixed names are totals and suffixed names are per-inverter:

```text
p_batt_forecast      # total
p_batt_forecast_1    # inverter 1
p_batt_forecast_2    # inverter 2
p_batt_forecast_3    # inverter 3

p_deferrable0
```

This is the corrected compatibility-first design. It preserves the normal
single-inverter path, makes multi-inverter behaviour explicit, keeps aggregate
dashboard values intuitive, and gives each inverter/battery its own SOC,
capacity, and charge/discharge limits inside one site optimisation.

## References

- EMHASS configuration documentation: https://emhass.readthedocs.io/en/latest/config.html
- EMHASS stable configuration documentation: https://emhass.readthedocs.io/en/stable/config.html
- EMHASS runtime data documentation: https://emhass.readthedocs.io/en/latest/passing_data.html
- EMHASS publish data documentation: https://emhass.readthedocs.io/en/latest/publish_data.html
- EMHASS plan output schema: https://emhass.readthedocs.io/en/latest/plan_output_schema.html
- GitHub discussion #870, multiple solar inverters and batteries: https://github.com/davidusb-geek/emhass/discussions/870
- GitHub discussion #544, multiple inverters and batteries: https://github.com/davidusb-geek/emhass/discussions/544
- GitHub issue #220, inverter output and feed-in mismatch: https://github.com/davidusb-geek/emhass/issues/220
