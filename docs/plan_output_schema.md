# Plan / Optimization Output Schema

This page documents the columns of the optimization-result DataFrame and saved
`opt_res_latest.csv` plan output (see [API Reference](emhass.md)).
`publish_data()` consumes that result, publishes the single-inverter entity
surface in single-inverter mode, and publishes site totals plus supported
suffixed inverter entities in multi-inverter mode.

Downstream consumers that read the result DataFrame or saved CSV can rely on
this schema as a versioned contract. Consumers that read Home Assistant entities
or the `publish_data()` return value can use the single-inverter columns and
the supported suffixed inverter columns documented below. In multi-inverter
mode, unsuffixed inverter columns are site totals and should not be sent to one
inverter as a command.

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

This table documents the unsuffixed columns published by `publish_data()`.
In single-inverter mode these names keep their existing meaning. In
multi-inverter mode, inverter quantities such as `P_batt`,
`SOC_opt`, `P_hybrid_inverter`, and `P_PV` are site totals.

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

## Multi-inverter result columns

The optimizer result DataFrame and saved `opt_res_latest.csv` remain the source
of result columns. In single-inverter mode, existing unsuffixed columns keep
their current meaning.

In multi-inverter mode, unsuffixed inverter quantities are site totals. Active
inverters use one-based suffixes that match `hybrid_inverter_config_N`. The
optimizer does not emit public `_0` columns and does not emit public `*_total`
columns.

| Quantity | Site total column | Inverter example | Unit | Notes |
|----------|-------------------|------------------|------|-------|
| Battery power | `P_batt` | `P_batt_1` | W | Positive = discharge, negative = charge. In multi-inverter mode, do not send unsuffixed `P_batt` to one inverter. |
| Battery state of charge | `SOC_opt` | `SOC_opt_1` | fraction (0..1) | Site total SOC is capacity-weighted across active batteries. All result/CSV SOC columns stay as fractions; HA SOC entities are published as percent values. |
| Hybrid inverter power | `P_hybrid_inverter` | `P_hybrid_inverter_1` | W | AC-side power; positive = DC → AC delivery, negative = AC → DC. |
| PV availability | `P_PV` | `P_PV_1` | W | `P_PV` is an AC-equivalent site PV availability diagnostic in multi-inverter mode. Per-inverter PV columns expose that inverter's forecast. |
| PV curtailment | `P_PV_curtailment` | `P_PV_curtailment_1` | W | Present when any active inverter has curtailment enabled. Positive = curtailed delta. |

Multi-inverter aggregate formulas:

- `P_batt = sum(P_batt_N)` across active battery-backed inverters.
- `SOC_opt = sum(SOC_opt_N * battery_nominal_energy_capacity_N) /
  sum(battery_nominal_energy_capacity_N)` across active batteries.
- `P_hybrid_inverter = sum(P_hybrid_inverter_N)` across active hybrid
  inverters.
- `P_PV = sum(ac_pv_availability_N)` across active PV inverters, where each
  inverter's availability is post-curtailment PV converted through that
  inverter's active solved direction.
- `P_PV_curtailment = sum(P_PV_curtailment_N)` across curtailed PV inverters.

Unsuffixed multi-inverter totals are diagnostics and site-level forecasts. Use
suffixed columns such as `P_batt_1` or `P_hybrid_inverter_2` for
inverter-specific command bridges.

### SOC_opt scaling callout

> ⚠️ **`SOC_opt` is the most common consumer bug.**
>
> The DataFrame value and the CSV export carry each `SOC_opt*` state-of-charge as
> a **fraction in [0, 1]**. When the same unsuffixed or suffixed SOC column is
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
the EMHASS instance advertises a different major. In multi-inverter mode, read
inverter-local sensors such as `sensor.p_batt_forecast_1` for command targets;
the unsuffixed battery, SOC, hybrid inverter, and PV entities are site totals.

## Source helpers

Publish helpers in `src/emhass/command_line.py`:

| Helper | Approximate line range | Columns published |
|--------|------------------------|-------------------|
| `_publish_load_forecast` | 2367-2382 | `P_Load` |
| `_publish_grid_power` | 2643-2658 | `P_grid` |
| `_publish_block_result_group` | 2615-2642 | `P_PV*`, `P_PV_curtailment*`, `P_hybrid_inverter*`, `P_batt*`, `SOC_opt*` |
| `_publish_deferrable_loads` / `_publish_deferrable_states` | 2383-2495 | `P_deferrable{k}` and optional state sensors for `k ∈ [0, N)` |
| `_publish_thermal_loads` | 2518-2588 | `predicted_temp_heater{k}`, `heating_demand_heater{k}` |
| `_publish_costs_and_status` | 2659-2717 | `cost_fun_<name>`, `optim_status`, `unit_load_cost`, `unit_prod_price` |

The aggregator `publish_data` calls these in grouped order and subsets the
result DataFrame to the published columns before returning. Multi-inverter
columns are built in `optimization.py::_add_public_multi_block_result_columns`;
supported suffixed inverter columns are then published through
`_publish_block_result_group`.

## Version history

| Version | Date | Change |
|---------|------|--------|
| 1.2 | 2026-07-07 | Added Home Assistant publisher suffixing and corrected the public multi-inverter contract before release: explicit `multi_inverter_mode`, one-based active inverter configs, unsuffixed site totals, suffixed inverter values, no public `_0` or `*_total` columns, grouped publisher order, and raw runtime logging compatibility. |
| 1.1 | 2026-07-05 | Added the pre-release public multi-inverter optimizer result/CSV columns and aggregate diagnostics. `publish_data()` publishing and return value were still single-inverter only in this version. |
| 1.0 | 2026-05-10 | Initial published schema. Sign conventions derived from `src/emhass/optimization.py` with inline citations. |
