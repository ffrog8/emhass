#!/usr/bin/env python3
"""Run reproducible SOC power-profile benchmarks through EMHASS's public mode seam.

The runner owns fixture loading, cache-state labeling, timing aggregation, and
JSON reporting. EMHASS remains responsible for configuration normalization,
forecast preparation, optimization, and result schedules.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import importlib.metadata
import json
import logging
import os
import pathlib
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Any

import cvxpy as cp
import numpy as np
import orjson

from emhass import utils
from emhass.command_line import OptimizationCache, naive_mpc_optim, set_input_data_dict

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_CORPUS_PATH = PROJECT_ROOT / "benchmarks" / "soc_power_profiles" / "payloads.json"


def summarize_timings(samples: list[float]) -> dict[str, float]:
    """Summarize a non-empty timing sample in seconds."""
    if not samples:
        raise ValueError("at least one timing sample is required")
    return {
        "minimum_s": min(samples),
        "median_s": statistics.median(samples),
        "p95_s": float(np.percentile(samples, 95)),
        "maximum_s": max(samples),
    }


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(*args: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), *args],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _resolved_packages() -> dict[str, str]:
    """Record installed versions without assuming upstream has a tracked lock file."""
    packages: dict[str, str] = {}
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name")
        if name:
            packages[name.lower()] = distribution.version
    return dict(sorted(packages.items()))


def _logger() -> logging.Logger:
    logger = logging.getLogger("soc_power_profile_benchmark")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    logger.setLevel(logging.ERROR)
    return logger


def _emhass_conf(data_path: pathlib.Path | None = None) -> dict[str, pathlib.Path]:
    root_path = PROJECT_ROOT / "src" / "emhass"
    return {
        "data_path": data_path or PROJECT_ROOT / "data",
        "root_path": root_path,
        "config_path": PROJECT_ROOT / "config.json",
        "defaults_path": root_path / "data" / "config_defaults.json",
        "associations_path": root_path / "data" / "associations.csv",
    }


async def _build_params(
    configuration: dict[str, Any],
    solver: dict[str, Any],
    runtime: dict[str, Any],
    logger: logging.Logger,
    emhass_conf: dict[str, pathlib.Path],
) -> dict[str, Any]:
    config = json.loads(emhass_conf["defaults_path"].read_text(encoding="utf-8"))
    config.update(copy.deepcopy(configuration))
    config.update(
        {
            "lp_solver": solver["name"],
            "lp_solver_timeout": solver["timeout_s"],
            "lp_solver_mip_rel_gap": solver["mip_relative_gap"],
            "num_threads": solver["threads"],
        }
    )
    _, secrets = await utils.build_secrets(emhass_conf, logger, no_response=True)
    params = await utils.build_params(emhass_conf, secrets, config, logger)
    if params is False:
        raise RuntimeError("EMHASS rejected benchmark configuration")
    params["passed_data"] = copy.deepcopy(runtime)
    return params


def _solver_seconds(opt: Any) -> float:
    value = opt.prob.solver_stats.solve_time
    return max(float(value or 0.0), 0.0)


def _schedule(result: Any, prefix: str) -> dict[str, list[float]]:
    return {
        column: [float(value) for value in result[column].to_numpy()]
        for column in result.columns
        if column == prefix or column.startswith(f"{prefix}_")
    }


async def _run_payload(
    payload: dict[str, Any],
    corpus: dict[str, Any],
    repetitions: int,
    logger: logging.Logger,
    emhass_conf: dict[str, pathlib.Path],
) -> dict[str, Any]:
    OptimizationCache.clear()
    params = await _build_params(
        payload["configuration"],
        corpus["solver"],
        payload["runtime"],
        logger,
        emhass_conf,
    )
    params_json = orjson.dumps(params).decode("utf-8")
    runtime_json = orjson.dumps(payload["runtime"]).decode("utf-8")
    runs = []

    for repetition in range(repetitions):
        end_to_end_start = time.perf_counter()
        setup_start = time.perf_counter()
        input_data = await set_input_data_dict(
            emhass_conf,
            payload["configuration"]["costfun"],
            params_json,
            runtime_json,
            corpus["mode"],
            logger,
            get_data_from_file=True,
        )
        setup_seconds = time.perf_counter() - setup_start
        if not isinstance(input_data, dict):
            raise RuntimeError(f"input preparation failed for payload {payload['name']!r}")

        result = await naive_mpc_optim(input_data, logger, debug=True)
        end_to_end_seconds = time.perf_counter() - end_to_end_start
        if not hasattr(result, "columns"):
            raise RuntimeError(f"optimization failed for payload {payload['name']!r}")

        stage_times = input_data["stage_times"]
        solve_call_seconds = float(stage_times.get("optim_solve.solve", 0.0))
        solver_seconds = _solver_seconds(input_data["opt"])
        runs.append(
            {
                "repetition": repetition + 1,
                "cache_state": "cold" if repetition == 0 else "warm",
                "solver_status": input_data["opt"].optim_status,
                "objective": float(input_data["opt"].prob.value),
                "power_schedule_w": _schedule(result, "P_batt"),
                "soc_schedule_fraction": _schedule(result, "SOC_opt"),
                "timings_s": {
                    "input_setup": setup_seconds,
                    "model_construction": float(
                        stage_times.get("optim_solve.build", 0.0)
                    ),
                    "canonicalization_and_wrapper": max(
                        solve_call_seconds - solver_seconds, 0.0
                    ),
                    "solver": solver_seconds,
                    "result_extraction": float(
                        stage_times.get("optim_solve.extract", 0.0)
                    ),
                    "optimization_mode": float(stage_times.get("optim_solve", 0.0)),
                    "end_to_end": end_to_end_seconds,
                },
            }
        )

    timing_names = runs[0]["timings_s"]
    timing_summary = {
        f"{name}_s": summarize_timings(
            [run["timings_s"][name] for run in runs]
        )
        for name in timing_names
    }
    return {
        "name": payload["name"],
        "description": payload["description"],
        "prediction_horizon": payload["runtime"]["prediction_horizon"],
        "runs": runs,
        "timing_summary": timing_summary,
    }


async def run_benchmarks(
    corpus_path: pathlib.Path = DEFAULT_CORPUS_PATH,
    repetitions: int | None = None,
) -> dict[str, Any]:
    """Execute every corpus payload through set_input_data_dict and naive_mpc_optim."""
    corpus_path = corpus_path.resolve()
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    if repetitions is None:
        repetitions = int(corpus["default_repetitions"])
    if repetitions < 1:
        raise ValueError("repetitions must be at least one")
    if corpus["mode"] != "naive-mpc-optim":
        raise ValueError("this runner currently supports the naive-mpc-optim corpus")
    if corpus["solver"]["name"] not in cp.installed_solvers():
        raise RuntimeError(
            f"configured solver {corpus['solver']['name']!r} is not installed"
        )

    logger = _logger()
    payload_reports = []
    with tempfile.TemporaryDirectory(prefix="emhass-soc-profile-benchmark-") as data_dir:
        benchmark_data_path = pathlib.Path(data_dir)
        shutil.copyfile(
            PROJECT_ROOT / "data" / "test_df_final.pkl",
            benchmark_data_path / "test_df_final.pkl",
        )
        emhass_conf = _emhass_conf(benchmark_data_path)
        for payload in corpus["payloads"]:
            payload_reports.append(
                await _run_payload(
                    payload, corpus, repetitions, logger, emhass_conf
                )
            )

    pyproject_path = PROJECT_ROOT / "pyproject.toml"
    lock_path = PROJECT_ROOT / "uv.lock"
    base_commit = corpus["base_commit"]
    tested_commit = _git("rev-parse", "HEAD")
    branch = _git("branch", "--show-current")
    commits_since_base = _git("rev-list", f"{base_commit}..HEAD")
    tracked_lock = _git("ls-files", "uv.lock") == "uv.lock"
    return {
        "schema_version": corpus["schema_version"],
        "repetitions": repetitions,
        "corpus_sha256": _sha256(corpus_path),
        "reproduction": {
            "base_commit": base_commit,
            "tested_commit": tested_commit,
            "branch": branch,
            "commits_since_base": (
                commits_since_base.splitlines() if commits_since_base is not None else None
            ),
            "git_metadata_limitation": (
                None
                if tested_commit is not None
                else "Git worktree metadata is not mounted in this execution environment."
            ),
            "pyproject_sha256": _sha256(pyproject_path),
            "dependency_lock": {
                "tracked": tracked_lock,
                "path": "uv.lock" if tracked_lock else None,
                "sha256": _sha256(lock_path) if tracked_lock else None,
                "limitation": (
                    None
                    if tracked_lock
                    else "The upstream fixed point does not track a dependency lock."
                ),
            },
            "resolved_packages": _resolved_packages(),
            "solver": copy.deepcopy(corpus["solver"]),
            "environment": {
                "python": sys.version,
                "platform": platform.platform(),
                "machine": platform.machine(),
                "processor": platform.processor(),
                "cpu_count": os.cpu_count(),
            },
        },
        "timing_notes": {
            "model_construction": (
                "Existing optim_solve.build instrumentation covers model expression and "
                "problem construction inside perform_optimization."
            ),
            "canonicalization_and_wrapper": (
                "Derived as the instrumented CVXPY solve-call wall time minus solver_stats."
                "solve_time; current instrumentation cannot isolate canonicalization from "
                "the remaining CVXPY wrapper overhead."
            ),
            "end_to_end": (
                "Runner wall time around input preparation and the complete optimisation mode."
            ),
        },
        "payloads": payload_reports,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark unchanged and SOC-profile EMHASS branches with identical payloads."
    )
    parser.add_argument(
        "--corpus",
        type=pathlib.Path,
        default=DEFAULT_CORPUS_PATH,
        help="JSON payload corpus (default: benchmarks/soc_power_profiles/payloads.json)",
    )
    parser.add_argument(
        "--repetitions",
        type=int,
        help="Runs per payload; first is cold and remaining runs are warm-cache.",
    )
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        help="Write JSON to this path instead of stdout.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    report = asyncio.run(run_benchmarks(args.corpus, args.repetitions))
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(f"{rendered}\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
