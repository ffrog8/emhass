<div align="center">
  <br>
  <img alt="EMHASS" src="https://raw.githubusercontent.com/davidusb-geek/emhass/master/docs/images/logo_docs.png" width="700px">
  <h1>Energy Management for Home Assistant</h1>
  <strong></strong>
</div>
<br>

<p align="center">
  <a style="text-decoration:none" href="https://pypi.org/project/emhass/">
    <img alt="PyPI - Version" src="https://img.shields.io/pypi/v/emhass">
  </a>
  <a style="text-decoration:none" href="https://anaconda.org/channels/davidusb/packages/emhass/overview">
    <img alt="Conda - Version" src="https://img.shields.io/conda/v/davidusb/emhass">
  </a>
  <a style="text-decoration:none" href="https://github.com/davidusb-geek/emhass/actions">
    <img alt="EMHASS GitHub Workflow Status" src="https://github.com/davidusb-geek/emhass/actions/workflows/publish_docker.yaml/badge.svg?event=release">
  </a>
  <a style="text-decoration:none" href="https://github.com/davidusb-geek/emhass/blob/master/LICENSE">
    <img alt="GitHub" src="https://img.shields.io/github/license/davidusb-geek/emhass">
  </a>
  <a style="text-decoration:none" href="https://pypi.org/project/emhass/">
    <img alt="PyPI - Python Version" src="https://img.shields.io/pypi/pyversions/emhass">
  </a>
  <a style="text-decoration:none" href="https://pypi.org/project/emhass/">
    <img alt="PyPI - Status" src="https://img.shields.io/pypi/status/emhass">
  </a>
  <a style="text-decoration:none" href="https://emhass.readthedocs.io/en/latest/">
    <img alt="Read the Docs" src="https://img.shields.io/readthedocs/emhass">
  </a>
    <a hstyle="text-decoration:none" ref="https://codecov.io/github/davidusb-geek/emhass" >
    <img src="https://codecov.io/github/davidusb-geek/emhass/branch/master/graph/badge.svg?token=BW7KSCHN90"/>
  </a>
  <a hstyle="text-decoration:none" ref="https://github.com/davidusb-geek/emhass/actions/workflows/codeql.yml" >
    <img src="https://github.com/davidusb-geek/emhass/actions/workflows/codeql.yml/badge.svg?branch=master&event=schedule"/>
  </a>
  <a style="text-decoration:none" href="https://sonarcloud.io/summary/new_code?id=davidusb-geek_emhass">
    <img alt="SonarQube security rating" src="https://sonarcloud.io/api/project_badges/measure?project=davidusb-geek_emhass&metric=security_rating">
  </a>
  <a style="text-decoration:none" href="https://sonarcloud.io/summary/new_code?id=davidusb-geek_emhass">
    <img alt="SonarQube security Vulnerabilities" src="https://sonarcloud.io/api/project_badges/measure?project=davidusb-geek_emhass&metric=vulnerabilities">
  </a>
  <a style="text-decoration:none" href="https://sonarcloud.io/summary/new_code?id=davidusb-geek_emhass">
    <img alt="SonarQube reliability" src="https://sonarcloud.io/api/project_badges/measure?project=davidusb-geek_emhass&metric=reliability_rating">
  </a>
  <a style="text-decoration:none" href="https://sonarcloud.io/summary/new_code?id=davidusb-geek_emhass">
    <img alt="SonarQube bugs" src="https://sonarcloud.io/api/project_badges/measure?project=davidusb-geek_emhass&metric=bugs">
  </a>
  
</p>

<div align="center">
 <a style="text-decoration:none" href="https://emhass.readthedocs.io/en/latest/">
      <img src="https://raw.githubusercontent.com/davidusb-geek/emhass/master/docs/images/Documentation_button.svg" alt="Documentation">
  </a>
   <a style="text-decoration:none" href="https://community.home-assistant.io/t/emhass-an-energy-management-for-home-assistant/338126">
      <img src="https://raw.githubusercontent.com/davidusb-geek/emhass/master/docs/images/Community_button.svg" alt="Community">
  </a>
  <a style="text-decoration:none" href="https://github.com/davidusb-geek/emhass/issues">
      <img src="https://raw.githubusercontent.com/davidusb-geek/emhass/master/docs/images/Issues_button.svg" alt="Issues">
  </a>
  <a style="text-decoration:none" href="https://github.com/davidusb-geek/emhass-add-on">
     <img src="https://raw.githubusercontent.com/davidusb-geek/emhass/master/docs/images/EMHASS_Add_on_button.svg" alt="EMHASS Add-on">
  </a>
</div>

<br>
<p align="left">
EMHASS is a Python module designed to optimize your home energy interfacing with Home Assistant.
</p>

## Introduction

EMHASS (Energy Management for Home Assistant) is an optimization tool designed for residential households. The package uses a Linear Programming approach to optimize energy usage while considering factors such as electricity prices, power generation from solar panels, and energy storage from batteries. EMHASS provides a high degree of configurability, making it easy to integrate with Home Assistant and other smart home systems. Whether you have solar panels, energy storage, or just a controllable load, EMHASS can provide an optimized daily schedule for your devices, allowing you to save money and minimize your environmental impact.

This repository supports scheduling multiple batteries and hybrid inverters within one site-level optimisation.
Each inverter has its own battery limits, efficiencies and state of charge, while the site shares electricity
prices, household demand, flexible loads and grid limits. EMHASS produces schedules; Home Assistant automations
or another control layer apply them to equipment.

## Multi-inverter scheduling

Single-inverter operation is the default. Enable `multi_inverter_mode: multi` to use configured inverters named
`hybrid_inverter_config_1`, `hybrid_inverter_config_2`, and so on. Runtime requests can update the state of charge
and supported limits of those configured inverters. In this mode, inverter-local parameters belong in their
indexed configurations; top-level battery parameters do not override the active indexed batteries.

Supported configurations include battery-only systems and battery-backed hybrid inverters with separate PV
forecasts. For hybrid systems, `multi_hybrid_inverter_pv_mode: split_pv` associates each PV-enabled inverter with
its own nested `pv_power_forecast`. Set `compute_curtailment` on each applicable inverter to allow its available
solar production to be reduced. Public multi-inverter requests require `battery_mode_lock: site`, which prevents
scheduling one battery to charge while another discharges in the same interval.

The optional `battery_soc_balance_cost` discourages differences from the capacity-weighted fleet state of charge.
It is a soft economic preference, subject to each battery's physical limits and the rest of the schedule.

Results contain site totals and individual inverter schedules. For example, `P_batt` is total battery power,
while `P_batt_1` and `SOC_opt_1` describe inverter 1. Battery power is negative for charging and positive for
discharging. State of charge uses fractions in the result and CSV, and percentages in published Home Assistant
sensors. Use the per-inverter values when constructing individual inverter commands.

See the [configuration reference](docs/config.md), [nested runtime inputs](docs/passing_data.md#nested-hybrid-inverter-runtime-configurations)
and [plan output schema](docs/plan_output_schema.md) for supported combinations, units and publishing details.

## Battery power profiles

`battery_soc_power_profiles` describes how each battery's maximum charge or discharge power depends on its
predicted state of charge. This can model charging taper near full capacity and reduced discharge power near
the battery reserve. Profiles can specify charging, discharging or both, and remain bounded by the configured
scalar power limits.

The optimiser selects the power band using the predicted state of charge at the end of each interval. An
interval crossing a breakpoint uses the conservative lower-power limit for the whole interval. In multi-inverter
mode, profile entries follow the battery-enabled indexed inverters in ascending index order.

Profiles add mixed-integer decisions and can increase solve time. A profiled solve that reaches its time limit
can retry using scalar battery limits, without the SoC-dependent profile limits. See the
[battery configuration reference](docs/config.md) for profile validation, timeout and fallback behaviour.

## Prices and battery export

The existing REST optimisation actions accept `load_cost_forecast` and `prod_price_forecast` arrays in
currency/kWh. These are absolute import costs and export revenues; negative values represent payment for
importing or a cost for exporting. Callers can supply their chosen forecast values through these arrays.

The optional request parameter `grid_export_sell_price_threshold` allows scheduled battery export only when
the forecast sell price is strictly above the threshold. At or below it, batteries can still supply household
and scheduled electrical demand, and solar can still export subject to the other site constraints. The threshold
applies to that request only; it neither forces export above the threshold nor replaces the site's other limits.

See [battery export price controls](docs/config.md#request-only-battery-export-sell-price-threshold) and the
[runtime input guide](docs/passing_data.md).

## Rolling optimisation and result handling

Rolling MPC reuses the compiled optimisation model. It gives the solver timestamp-aligned suggestions for later
integer decisions from the previous successful primary solve, leaving the first interval and continuous power
values unspecified. The objective still evaluates the supplied forecasts across the horizon, with the configured
solver tolerance determining how closely the returned schedule must approach the optimum.

A solver exception triggers the fallback path. A result is accepted only from a solve that returns normally
during the current request. If both attempts raise exceptions, the result reports `Failure` without a power
schedule. The last valid published plan remains available, so consumers should check the latest run status and
plan timestamp when deciding whether a schedule is fresh.

`GET /api/v1/plan` exposes the latest plan and `GET /api/v1/last-run` exposes the latest run outcome. See
[rolling MPC and failed solves](docs/mpc_solver_starts.md) for starting-hint ownership and failure behaviour.

## Getting started

General EMHASS documentation is [available here](https://emhass.readthedocs.io/en/latest/).

To get started you can follow our [🚀 Quick Start](/docs/quick_start.md) guide in the documentation.

Here are the guides for:

- [📦 Installation methods](/docs/installation_methods.md)
- [📖 Usage](/docs/usage_guide.md)
- [🤖 Home Assistant Automations](/docs/automations.md)

## Development

Pull requests are very much accepted on this project. For development, you can find some instructions here [Development](/docs/develop.md).

## License

MIT License

Copyright (c) 2021-2026 David HERNANDEZ TORRES

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
