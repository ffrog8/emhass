# Plan / Optimization Output Schema

This page documents the columns of the optimization-result DataFrame and saved
`opt_res_latest.csv` plan output (see [API Reference](emhass.md)).
`publish_data()` consumes that result, publishes the block `0` entity surface
plus supported suffixed entities for extra inverter/battery blocks, and returns
the tracked one-row published-column subset.

Downstream consumers that read the result DataFrame or saved CSV can rely on
this schema as a versioned contract. Consumers that read Home Assistant entities
or the `publish_data()` return value can use the same block `0` columns and the
supported suffixed block columns documented below. Aggregate `*_total` columns
remain diagnostics and are not published as command entities.

## Schema version

Every result DataFrame carries the schema version as a pandas attribute:

```python
result = await publish_data(...)
result.attrs["emhass_schema_version"]
# "1.2"
```

The version string is also exposed as a module-level constant:

```python
from emhass.command_line import EMHASS_SCHEMA_VERSION
```

### Semver rules

| Bump kind | Trigger |
|-----------|---------|
| **Patch** (`1.2` → `1.2.1`) | Documentation clarification, sign convention confirmed, description sharpened. No consumer code change required. |
| **Minor** (`1.2` → `1.3`) | New column added without removing or renaming existing columns. Consumers using `.get(col)` keep working. |
| **Major** (`1.2` → `2.0`) | Column removed, column renamed, sign convention flipped, unit changed, or HA-scaling factor changed for a column. |

Consumers pin to a major version. Code that requires schema ≥ 1.2 should check:

```python
major = int(result.attrs.get("emhass_schema_version", "0").split(".")[0])
if major != 1:
    raise RuntimeError(f"Unexpected EMHASS schema major {major}")
```

## Column table

This table documents the block `0` columns published by `publish_data()`.
These names remain block-local and unchanged.

11 fixed columns plus four variable groups: `P_deferrable{k}`,
`predicted_temp_heater{k}`, `heating_demand_heater{k}` (for each configured
deferrable / thermal load), and `cost_fun_<name>` (one column per cost-function
component the chosen `costfun` decomposes into). `cost_fun_*` columns are posted
to the Home Assistant cost entity but are not returned through the
`cols_published` subset.

| Column | Source helper | Unit | Sign convention | Conditional | HA scaling | `type_var` | Notes |
|--------|---------------|------|-----------------|-------------|------------|------------|-------|
| `P_Load` | `_publish_standard_forecasts` | W | positive = consumption | always | 1:1 | `power` | DataFrame column read directly |
| `P_PV` | `_publish_standard_forecasts` | W | positive = production (PV → DC bus) | when `"P_PV"` is in DataFrame | 1:1 | `power` | `custom_pv_forecast_id`. Assigned from `p_pv` forecast input at `optimization.py:2291`. |
| `P_PV_curtailment` | `_publish_standard_forecasts` | W | positive = curtailed delta (subtracts from gross PV in DC balance) | `plant_conf.compute_curtailment = true` | 1:1 | `power` | `custom_pv_curtailment_id`. CVXPY `nonneg=True` at `optimization.py:876`; appears as `(p_pv - p_pv_curtailment)` in DC-balance constraint at line 1131; bounded by `<= param_pv_forecast` at line 2761. |
| `P_hybrid_inverter` | `_publish_standard_forecasts` | W | AC-side power; positive = DC → AC delivery, negative = AC → DC (charging-from-grid via DC bus) | `plant_conf.inverter_is_hybrid = true` | 1:1 | `power` | `custom_hybrid_inverter_id`. Defined at `optimization.py:1140` as `p_hybrid_inverter == (p_dc_ac * eff_dc_ac) - (p_ac_dc * (1.0 / eff_ac_dc))`. |
| `P_deferrable{k}` | `_publish_deferrable_loads` | W | positive = consumption | `k ∈ [0, number_of_deferrable_loads)`; row skipped (error log) if column missing | 1:1 | `deferrable` | `custom_deferrable_forecast_id[k]` |
| `predicted_temp_heater{k}` | `_publish_thermal_loads` | °C | n/a (state) | per `k` where `def_load_config[k]` has `thermal_config` or `thermal_battery` | 1:1 | `temperature` | `custom_predicted_temperature_id[k]`. Semantics depend on heater type: **room (air) temperature** for `thermal_config` loads (kept within `min_temps`/`max_temps` band toward `desired_temps`); **thermal-storage/tank temperature** for `thermal_battery` loads. |
| `heating_demand_heater{k}` | `_publish_thermal_loads` | **kWh** | **thermal energy** the building exchanges with its surroundings, not electrical input. For a heating load (`sense: "heat"`) this is positive (heat the building loses and the source must replace). For a cooling load (`sense: "cool"`) it is zero or **negative**, representing the heat the building gains and the source must remove. | only set for `thermal_battery`-type loads (not bare `thermal_config`) | 1:1 | `energy` | `custom_heating_demand_id[k]`. The thermal-battery model carries a separate `heatpump_cops` parameter (`optimization.py:310`); electrical input = thermal / COP, so the two are decoupled. Unit `"kWh"` confirmed at `utils.py` (`heating_demand_friendly_name`). |
| `P_batt` | `_publish_battery_data` | W | positive = discharge (battery → house), negative = charge (house/grid → battery) | `optim_conf.set_use_battery = true`; row skipped if column missing | 1:1 | `batt` | `custom_batt_forecast_id`. Sum of `p_sto_pos + p_sto_neg` at `optimization.py:2312`. SOC reconstruction at lines 2319-2322 confirms direction: `power_flow = p_sto_pos / eff_dis + p_sto_neg * eff_chg`, then `SOC_opt = soc_init - cumulative_change / cap` (so positive `P_batt` drives SOC down → discharge). |
| `SOC_opt` | `_publish_battery_data` | **fraction (0..1) in CSV; ×100 in HA** | n/a (state) | `optim_conf.set_use_battery = true` | **×100** | `SOC` | See [SOC_opt scaling callout](#soc_opt-scaling-callout) |
| `P_grid` | `_publish_grid_and_costs` | W | positive = import (grid → house), negative = export (house → grid) | always | 1:1 | `power` | `custom_grid_forecast_id`. `P_grid = P_grid_pos + P_grid_neg` at `optimization.py:2299`. `p_grid_pos` is CVXPY `nonneg=True` bounded by `maximum_power_from_grid` (line 803); `p_grid_neg` is `nonpos=True` bounded by `-maximum_power_to_grid` (line 798). |
| `cost_fun_<name>` | `_publish_grid_and_costs` | € | n/a (cost) | always; multi-column (filter on substring `"cost_fun_"`) | 1:1 | `cost_fun` | Components depend on `costfun` (`profit`, `cost`, `self-consumption`). HA single entity `custom_cost_fun_id` aggregates them. Posted to HA but not added to the returned `cols_published` subset. |
| `optim_status` | `_publish_grid_and_costs` | text | n/a | always (defaulted to `"Optimal"` with WARN log if missing) | n/a | `optim_status` | CVXPY status strings: `Optimal`, `Infeasible`, `Unbounded`, etc. `device_class=""`, `unit_of_measurement=""`. |
| `unit_load_cost` | `_publish_grid_and_costs` | €/kWh | n/a (price) | always | 1:1 | `unit_load_cost` | per-timestep tariff series for load |
| `unit_prod_price` | `_publish_grid_and_costs` | €/kWh | n/a (price) | always | 1:1 | `unit_prod_price` | per-timestep sell price series |

## Multi-block result columns

The optimizer result DataFrame and saved `opt_res_latest.csv` remain the source
of result columns. `publish_data()` now publishes supported extra-block battery,
SOC, hybrid inverter, PV, and PV-curtailment columns to suffixed Home Assistant
entities and includes those supported suffixed columns in its one-row return.

Block `0` keeps the legacy unsuffixed names. Extra blocks use the block index as
an `_<N>` suffix. Fleet values are exposed only by explicit `*_total` columns.

| Quantity | Block `0` column | Extra block example | Total column | Unit | Notes |
|----------|------------------|---------------------|--------------|------|-------|
| Battery power | `P_batt` | `P_batt_1` | `P_batt_total` | W | Positive = discharge, negative = charge. `P_batt` remains block `0`, not the fleet total. |
| Battery state of charge | `SOC_opt` | `SOC_opt_1` | `SOC_opt_total` | fraction (0..1) | All `SOC_opt*` result/CSV columns stay as fractions. HA block `0` and suffixed SOC entities are published as percent values. |
| Hybrid inverter power | `P_hybrid_inverter` | `P_hybrid_inverter_1` | `P_hybrid_inverter_total` | W | AC-side power; positive = DC → AC delivery, negative = AC → DC. |
| PV availability | `P_PV` | `P_PV_1` | `P_PV_total` | W | `P_PV_total` is an AC-equivalent PV availability diagnostic. It is not source tracking and is not actual AC-side source attribution. |
| PV curtailment | `P_PV_curtailment` | `P_PV_curtailment_1` | `P_PV_curtailment_total` | W | Present when any block has curtailment enabled. Positive = curtailed delta. |

Aggregate formulas:

- `P_batt_total = sum(P_batt_i)` across battery blocks.
- `SOC_opt_total = sum(SOC_opt_i * battery_nominal_energy_capacity_i) /
  sum(battery_nominal_energy_capacity_i)` across battery blocks.
- `P_hybrid_inverter_total = sum(P_hybrid_inverter_i)` across hybrid inverter
  blocks.
- `P_PV_total = sum(ac_pv_availability_i)` across PV blocks, where each block's
  availability is post-curtailment PV converted through that block's active
  solved inverter direction.
- `P_PV_curtailment_total = sum(P_PV_curtailment_i)` across curtailed PV blocks.

Aggregate totals remain diagnostics. They are not published as inverter command
entities and are not included in the `publish_data()` returned
`cols_published` subset.

### SOC_opt scaling callout

> ⚠️ **`SOC_opt` is the most common consumer bug.**
>
> The DataFrame value and the CSV export carry each `SOC_opt*` state-of-charge as
> a **fraction in [0, 1]**. When the same block `0` or suffixed SOC column is
> published to Home Assistant it is multiplied by **100** to display as a
> percentage. Consumers reading the result DataFrame or the exported CSV must
> therefore multiply by 100 themselves if they expect percent; consumers reading
> HA entities get percent already and must not double-scale.

## Sign conventions

All sign conventions are derived from `src/emhass/optimization.py` (the CVXPY model
definition). Per-column citations are inline in the column table above. Summary:

| Quantity | Positive means | Negative means |
|----------|----------------|----------------|
| `P_PV` | PV production (panels → DC bus) | (always ≥ 0; PV does not consume) |
| `P_PV_curtailment` | curtailed delta (subtracted from gross PV) | (always ≥ 0; CVXPY `nonneg=True`) |
| `P_hybrid_inverter` | DC → AC flow (delivered to house/grid) | AC → DC flow (charging via DC bus) |
| `P_deferrable{k}` | load consumption | (always ≥ 0; loads do not export) |
| `P_batt` | battery discharge (battery → house) | battery charge (house/grid → battery) |
| `P_grid` | import (grid → house) | export (house → grid) |

## Consumer recipes

### Python (pandas)

```python
from emhass.command_line import publish_data, EMHASS_SCHEMA_VERSION

result = await publish_data(input_data_dict, logger)
assert result.attrs["emhass_schema_version"].startswith("1.")

if "SOC_opt" in result.columns:
    soc_percent = result["SOC_opt"] * 100  # CSV holds fraction
```

### Node-RED

A flow that reads the result DataFrame, saved CSV, or published HA entities
should hard-code the major version it was authored against and refuse to run if
the EMHASS instance advertises a different major. Read block-local sensors such
as `sensor.p_batt_forecast_1` for extra blocks, and do not use aggregate
`*_total` diagnostics as inverter command targets.

## Source helpers

Publish helpers in `src/emhass/command_line.py`:

| Helper | Approximate line range | Columns published |
|--------|------------------------|-------------------|
| `_publish_standard_forecasts` | 2367-2429 | `P_Load`, `P_PV`, `P_PV_curtailment`, `P_hybrid_inverter` |
| `_publish_deferrable_loads` | 2430-2564 | `P_deferrable{k}` for `k ∈ [0, N)` |
| `_publish_thermal_loads` | 2565-2609 | `predicted_temp_heater{k}`, `heating_demand_heater{k}` |
| `_publish_battery_data` | 2610-2646 | `P_batt`, `SOC_opt` |
| `_publish_suffixed_block_result_columns` | 2673-2705 | `P_batt_N`, `SOC_opt_N`, `P_hybrid_inverter_N`, `P_PV_N`, `P_PV_curtailment_N` for supported extra blocks |
| `_publish_grid_and_costs` | 2706-2769 | `P_grid`, `cost_fun_<name>`, `optim_status`, `unit_load_cost`, `unit_prod_price` |

The aggregator `publish_data` (~line 2772) calls these in order and subsets the result
DataFrame to the published columns before returning. Multi-block columns are
built in `optimization.py::_add_public_multi_block_result_columns`; supported
extra-block columns are then published through
`_publish_suffixed_block_result_columns`.

## Version history

| Version | Date | Change |
|---------|------|--------|
| 1.2 | 2026-07-06 | Added Home Assistant publisher suffixing and `publish_data()` return columns for supported extra block battery/SOC/hybrid/PV outputs. Aggregate totals remain diagnostics and are not published. |
| 1.1 | 2026-07-05 | Added public multi-block optimizer result/CSV columns and aggregate diagnostics. `publish_data()` publishing and return value were still block `0` only in this version. |
| 1.0 | 2026-05-10 | Initial published schema. Sign conventions derived from `src/emhass/optimization.py` with inline citations. |
