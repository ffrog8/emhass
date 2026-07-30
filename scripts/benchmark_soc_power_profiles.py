#!/usr/bin/env python3
"""Run reproducible SOC power-profile benchmarks through EMHASS's public mode seam.

The runner owns fixture loading, cache-state labeling, timing aggregation, and
JSON reporting. It temporarily overrides the process-wide ``LP_SOLVER``
environment variable, replaces handlers on its named logger, and clears the
process-wide ``OptimizationCache`` before/after benchmark payloads. EMHASS
remains responsible for configuration normalization, forecast preparation,
optimization, and result schedules.
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import contextlib
import copy
import hashlib
import importlib.metadata
import json
import logging
import os
import pathlib
import platform
import re
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
from emhass.soc_power_profiles import (
    BENCHMARK_MAX_ADDED_ROWS,
    BENCHMARK_MAX_SELECTORS,
    model_size_increase,
)

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_CORPUS_PATH = PROJECT_ROOT / "benchmarks" / "soc_power_profiles" / "payloads.json"
OFFLINE_BENCHMARK_SECRETS = {
    "hass_url": "http://127.0.0.1/",
    "long_lived_token": "",
    "time_zone": "UTC",
    "Latitude": 0.0,
    "Longitude": 0.0,
    "Altitude": 0.0,
}


@contextlib.contextmanager
def benchmark_solver_environment(solver_name: str):
    """Force Optimization's environment-selected solver and restore ambient state."""
    previous = os.environ.get("LP_SOLVER")
    os.environ["LP_SOLVER"] = solver_name
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("LP_SOLVER", None)
        else:
            os.environ["LP_SOLVER"] = previous


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


def summarize_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize cold and warm samples independently."""
    timing_summary = {}
    for cache_state in ("cold", "warm"):
        state_runs = [run for run in runs if run["cache_state"] == cache_state]
        if not state_runs:
            continue
        timing_names = state_runs[0]["timings_s"]
        timing_summary[cache_state] = {
            f"{name}_s": summarize_timings(
                [
                    run["timings_s"][name]
                    for run in state_runs
                    if run["timings_s"][name] is not None
                ]
            )
            for name in timing_names
            if any(run["timings_s"][name] is not None for run in state_runs)
        }
    primary_status_counts = collections.Counter(
        str(run["primary_solver_status"]).lower() for run in runs
    )
    final_status_counts = collections.Counter(
        str(run["solver_status"]).lower() for run in runs
    )
    return {
        "timing_summary": timing_summary,
        "absent_profile_objective": runs[0]["objective"],
        "primary_status_counts": dict(sorted(primary_status_counts.items())),
        "final_status_counts": dict(sorted(final_status_counts.items())),
        "primary_timeout_count": sum(
            count
            for status, count in primary_status_counts.items()
            if any(marker in status for marker in ("timeout", "time_limit", "user_limit"))
        ),
        "primary_infeasible_count": sum(
            count for status, count in primary_status_counts.items() if "infeasible" in status
        ),
        "final_unsuccessful_count": sum(
            count for status, count in final_status_counts.items() if not status.startswith("optimal")
        ),
        "relaxed_fallback_count": sum(
            bool(run["relaxed_fallback_used"]) for run in runs
        ),
    }


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_required(repository: pathlib.Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *args],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or "unknown Git error"
        raise RuntimeError(f"unable to verify repository provenance: {detail}")
    return result.stdout.strip()


def verify_repository_provenance(
    repository: pathlib.Path, base_commit: str
) -> dict[str, Any]:
    """Require a clean worktree whose HEAD descends from the recorded base."""
    if re.fullmatch(r"[0-9a-f]{40}", base_commit) is None:
        raise RuntimeError("recorded base commit must be a full 40-character SHA")

    tested_commit = _git_required(repository, "rev-parse", "HEAD")
    dirty_paths = _git_required(
        repository, "status", "--porcelain", "--untracked-files=all"
    )
    if dirty_paths:
        raise RuntimeError(
            "benchmark provenance requires a clean worktree; commit or remove changes first"
        )

    try:
        merge_base = _git_required(repository, "merge-base", base_commit, tested_commit)
    except RuntimeError as error:
        raise RuntimeError(
            "recorded base commit has no merge-base with the tested commit"
        ) from error
    if merge_base != base_commit:
        raise RuntimeError(
            f"recorded base commit is not the merge-base of {tested_commit}"
        )

    commits = _git_required(
        repository, "rev-list", "--reverse", f"{base_commit}..{tested_commit}"
    )
    return {
        "base_commit": base_commit,
        "tested_commit": tested_commit,
        "merge_base": merge_base,
        "worktree_clean": True,
        "branch": _git_required(repository, "branch", "--show-current") or None,
        "commits_since_base": commits.splitlines() if commits else [],
    }


def _resolved_packages() -> dict[str, str]:
    """Record installed versions without assuming upstream has a tracked lock file."""
    packages: dict[str, str] = {}
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name")
        if name:
            packages[name.lower()] = distribution.version
    return dict(sorted(packages.items()))


class _WarningCapture(logging.Handler):
    """Collect warning/error text so primary solver failures survive fallback."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def _logger(capture: _WarningCapture | None = None) -> logging.Logger:
    logger = logging.getLogger("soc_power_profile_benchmark")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    if capture is not None:
        logger.addHandler(capture)
    logger.setLevel(logging.WARNING)
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


async def build_benchmark_params(
    configuration: dict[str, Any],
    solver: dict[str, Any],
    runtime: dict[str, Any],
    logger: logging.Logger | None = None,
    emhass_conf: dict[str, pathlib.Path] | None = None,
) -> dict[str, Any]:
    """Build inputs from fixed offline values, never ambient secrets or location."""
    logger = logger or _logger()
    emhass_conf = emhass_conf or _emhass_conf()
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
    params = await utils.build_params(
        emhass_conf, copy.deepcopy(OFFLINE_BENCHMARK_SECRETS), config, logger
    )
    if params is False:
        raise RuntimeError("EMHASS rejected benchmark configuration")
    params["passed_data"] = copy.deepcopy(runtime)
    return params


def _solver_seconds(opt: Any) -> float:
    value = getattr(opt.prob.solver_stats, "solve_time", None)
    return max(float(value or 0.0), 0.0)


def _safe_number(value: Any) -> float | None:
    if value is None:
        return None
    number = float(value)
    return number if np.isfinite(number) else None


def _schedule(result: Any, prefix: str) -> dict[str, list[float]]:
    return {
        column: [_safe_number(value) for value in result[column].to_numpy()]
        for column in result.columns
        if column == prefix or column.startswith(f"{prefix}_")
    }


def _problem_size(problem: Any) -> dict[str, int]:
    metrics = problem.size_metrics
    boolean_variables = sum(
        int(variable.size)
        for variable in problem.variables()
        if variable.attributes.get("boolean")
    )
    equality_rows = int(metrics.num_scalar_eq_constr)
    inequality_rows = int(metrics.num_scalar_leq_constr)
    return {
        "scalar_variables": int(metrics.num_scalar_variables),
        "boolean_variables": boolean_variables,
        "equality_rows": equality_rows,
        "inequality_rows": inequality_rows,
        "constraint_rows": equality_rows + inequality_rows,
    }


def build_run_record(
    *,
    repetition: int,
    cache_state: str,
    cache_reused: bool,
    result: Any,
    optimization: Any,
    stage_times: dict[str, float],
    setup_seconds: float,
    end_to_end_seconds: float,
    primary_solver_status: str,
    relaxed_fallback_used: bool,
) -> dict[str, Any]:
    """Build one JSON-safe run record, including unsuccessful solver results."""
    solve_call_seconds = float(stage_times.get("optim_solve.solve", 0.0))
    solver_seconds = _solver_seconds(optimization)
    return {
        "repetition": repetition,
        "cache_state": cache_state,
        "cache_reused": cache_reused,
        "primary_solver_status": primary_solver_status,
        "solver_status": optimization.optim_status,
        "relaxed_fallback_used": relaxed_fallback_used,
        "solver_name": optimization.prob.solver_stats.solver_name or "unknown",
        "objective": _safe_number(optimization.prob.value),
        "problem_size": _problem_size(optimization.prob),
        "power_schedule_w": _schedule(result, "P_batt"),
        "soc_schedule_fraction": _schedule(result, "SOC_opt"),
        "timings_s": {
            "input_setup": setup_seconds,
            "model_construction": float(stage_times.get("optim_solve.build", 0.0)),
            "solve_call_including_fallback": solve_call_seconds,
            "canonicalization_and_wrapper": (
                None
                if relaxed_fallback_used
                else max(solve_call_seconds - solver_seconds, 0.0)
            ),
            "final_solver": solver_seconds,
            "result_extraction": float(stage_times.get("optim_solve.extract", 0.0)),
            "optimization_mode": float(stage_times.get("optim_solve", 0.0)),
            "end_to_end": end_to_end_seconds,
        },
    }


def verify_cache_transition(
    *,
    repetition: int,
    had_cached_instance: bool,
    cold_optimization: Any,
    current_optimization: Any,
) -> tuple[str, bool, Any]:
    """Label cache state only after observing the expected object transition."""
    if repetition == 0:
        if had_cached_instance:
            raise RuntimeError("cold benchmark run started with a populated cache")
        return "cold", False, current_optimization
    if not had_cached_instance or current_optimization is not cold_optimization:
        raise RuntimeError("warm benchmark run did not reuse the cold Optimization object")
    return "warm", True, cold_optimization


def primary_solve_outcome(
    messages: list[str], final_status: str
) -> tuple[str, bool]:
    """Recover the primary status logged immediately before relaxed fallback."""
    pattern = re.compile(r"Optimization failed with status: '([^']*)'")
    for message in messages:
        match = pattern.search(message)
        if match:
            return match.group(1) or "failure", True
    return final_status, False


async def _run_payload(
    payload: dict[str, Any],
    corpus: dict[str, Any],
    repetitions: int,
    logger: logging.Logger,
    warning_capture: _WarningCapture,
    emhass_conf: dict[str, pathlib.Path],
) -> dict[str, Any]:
    profiles = copy.deepcopy(payload.get("candidate_profiles"))
    configuration = copy.deepcopy(payload["configuration"])
    if profiles is not None:
        configuration["battery_soc_power_profiles"] = profiles
    params = await build_benchmark_params(
        configuration,
        corpus["solver"],
        payload["runtime"],
        logger,
        emhass_conf,
    )
    params_json = orjson.dumps(params).decode("utf-8")
    runtime_json = orjson.dumps(payload["runtime"]).decode("utf-8")
    runs = []
    cold_optimization = None

    OptimizationCache.clear()
    for repetition in range(repetitions):
        had_cached_instance = OptimizationCache.get_stats()["has_instance"]
        end_to_end_start = time.perf_counter()
        setup_start = time.perf_counter()
        input_data = await set_input_data_dict(
            emhass_conf,
            configuration["costfun"],
            params_json,
            runtime_json,
            corpus["mode"],
            logger,
            get_data_from_file=True,
        )
        setup_seconds = time.perf_counter() - setup_start
        if not isinstance(input_data, dict):
            raise RuntimeError(
                f"input preparation failed for payload {payload['name']!r}"
            )

        warning_start = len(warning_capture.messages)
        result = await naive_mpc_optim(input_data, logger, debug=True)
        end_to_end_seconds = time.perf_counter() - end_to_end_start
        if not hasattr(result, "columns"):
            raise RuntimeError(f"optimization failed for payload {payload['name']!r}")

        cache_state, cache_reused, cold_optimization = verify_cache_transition(
            repetition=repetition,
            had_cached_instance=had_cached_instance,
            cold_optimization=cold_optimization,
            current_optimization=input_data["opt"],
        )
        primary_status, relaxed_fallback_used = primary_solve_outcome(
            warning_capture.messages[warning_start:],
            final_status=str(input_data["opt"].prob.status),
        )
        runs.append(
            build_run_record(
                repetition=repetition + 1,
                cache_state=cache_state,
                cache_reused=cache_reused,
                result=result,
                optimization=input_data["opt"],
                stage_times=input_data["stage_times"],
                setup_seconds=setup_seconds,
                end_to_end_seconds=end_to_end_seconds,
                primary_solver_status=primary_status,
                relaxed_fallback_used=relaxed_fallback_used,
            )
        )

    profile_model_size = model_size_increase(
        profiles, payload["runtime"]["prediction_horizon"]
    )
    return {
        "name": payload["name"],
        "description": payload["description"],
        "prediction_horizon": payload["runtime"]["prediction_horizon"],
        "profile_state": "configured" if profiles is not None else "absent",
        "benchmark_envelope": bool(payload.get("benchmark_envelope")),
        "profile_model_size": profile_model_size,
        "runs": runs,
        **summarize_runs(runs),
    }


def _maximum_absolute_difference(
    first: dict[str, list[float | None]], second: dict[str, list[float | None]]
) -> float:
    if first.keys() != second.keys():
        return float("inf")
    differences = []
    for key in first:
        if len(first[key]) != len(second[key]):
            return float("inf")
        for left, right in zip(first[key], second[key], strict=True):
            if left is None or right is None:
                if left != right:
                    return float("inf")
            else:
                differences.append(abs(left - right))
    return max(differences, default=0.0)


def compare_paired_reports(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    tolerance: float = 1e-6,
) -> dict[str, Any]:
    """Compare reports produced from one corpus under identical environments."""
    parity_fields = {
        "corpus_sha256": (baseline["corpus_sha256"], candidate["corpus_sha256"]),
        "repetitions": (baseline["repetitions"], candidate["repetitions"]),
        "solver": (
            baseline["reproduction"]["solver"],
            candidate["reproduction"]["solver"],
        ),
        "offline_inputs": (
            baseline["reproduction"]["offline_inputs"],
            candidate["reproduction"]["offline_inputs"],
        ),
        "environment": (
            baseline["reproduction"]["environment"],
            candidate["reproduction"]["environment"],
        ),
        "resolved_packages": (
            baseline["reproduction"]["resolved_packages"],
            candidate["reproduction"]["resolved_packages"],
        ),
    }
    mismatches = [name for name, values in parity_fields.items() if values[0] != values[1]]
    if mismatches:
        raise RuntimeError(
            "paired benchmark environment mismatch: " + ", ".join(mismatches)
        )

    baseline_payloads = {payload["name"]: payload for payload in baseline["payloads"]}
    candidate_payloads = {payload["name"]: payload for payload in candidate["payloads"]}
    if baseline_payloads.keys() != candidate_payloads.keys():
        raise RuntimeError("paired benchmark payload names differ")

    comparisons = []
    for name, candidate_payload in candidate_payloads.items():
        baseline_payload = baseline_payloads[name]
        if len(baseline_payload["runs"]) != len(candidate_payload["runs"]):
            raise RuntimeError(f"paired benchmark run count differs for {name!r}")
        run_comparisons = []
        for baseline_run, candidate_run in zip(
            baseline_payload["runs"], candidate_payload["runs"], strict=True
        ):
            if (
                baseline_run["cache_state"] != candidate_run["cache_state"]
                or baseline_run["repetition"] != candidate_run["repetition"]
            ):
                raise RuntimeError(f"paired benchmark cache samples differ for {name!r}")
            objective_delta = (
                None
                if baseline_run["objective"] is None or candidate_run["objective"] is None
                else candidate_run["objective"] - baseline_run["objective"]
            )
            power_delta = _maximum_absolute_difference(
                baseline_run["power_schedule_w"], candidate_run["power_schedule_w"]
            )
            soc_delta = _maximum_absolute_difference(
                baseline_run["soc_schedule_fraction"],
                candidate_run["soc_schedule_fraction"],
            )
            if candidate_payload["profile_state"] == "absent" and (
                objective_delta is None
                or abs(objective_delta) > tolerance
                or power_delta > tolerance
                or soc_delta > tolerance
            ):
                raise RuntimeError(
                    f"absent-profile result differs from unchanged base for {name!r}"
                )
            run_comparisons.append(
                {
                    "repetition": candidate_run["repetition"],
                    "cache_state": candidate_run["cache_state"],
                    "objective_delta": objective_delta,
                    "maximum_power_schedule_delta_w": power_delta,
                    "maximum_soc_schedule_delta_fraction": soc_delta,
                }
            )
        comparisons.append(
            {
                "name": name,
                "profile_state": candidate_payload["profile_state"],
                "runs": run_comparisons,
            }
        )
    return {
        "environment_parity": True,
        "absent_profile_tolerance": tolerance,
        "payloads": comparisons,
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
    provenance = verify_repository_provenance(PROJECT_ROOT, corpus["base_commit"])

    warning_capture = _WarningCapture()
    logger = _logger(warning_capture)
    payload_reports = []
    try:
        with tempfile.TemporaryDirectory(
            prefix="emhass-soc-profile-benchmark-"
        ) as data_dir:
            benchmark_data_path = pathlib.Path(data_dir)
            shutil.copyfile(
                PROJECT_ROOT / "data" / "test_df_final.pkl",
                benchmark_data_path / "test_df_final.pkl",
            )
            emhass_conf = _emhass_conf(benchmark_data_path)
            with benchmark_solver_environment(corpus["solver"]["name"]):
                for payload in corpus["payloads"]:
                    payload_reports.append(
                        await _run_payload(
                            payload,
                            corpus,
                            repetitions,
                            logger,
                            warning_capture,
                            emhass_conf,
                        )
                    )
    finally:
        OptimizationCache.clear()
        logger.handlers.clear()

    pyproject_path = PROJECT_ROOT / "pyproject.toml"
    lock_path = PROJECT_ROOT / "uv.lock"
    tracked_lock = _git_required(PROJECT_ROOT, "ls-files", "uv.lock") == "uv.lock"
    actual_solver_names = sorted(
        {
            run["solver_name"]
            for payload_report in payload_reports
            for run in payload_report["runs"]
        }
    )
    return {
        "schema_version": corpus["schema_version"],
        "repetitions": repetitions,
        "benchmark_variant": "candidate",
        "retained_warning_envelope": {
            "boolean_selectors": BENCHMARK_MAX_SELECTORS,
            "added_linear_rows": BENCHMARK_MAX_ADDED_ROWS,
        },
        "repetition_note": (
            "The first repetition is a cold construction; all later repetitions "
            "reuse its cached Optimization object."
        ),
        "corpus_sha256": _sha256(corpus_path),
        "reproduction": {
            **provenance,
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
            "solver": {
                **copy.deepcopy(corpus["solver"]),
                "actual_names": actual_solver_names,
            },
            "offline_inputs": copy.deepcopy(OFFLINE_BENCHMARK_SECRETS),
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
        "--baseline-report",
        type=pathlib.Path,
        help="Unchanged-base JSON report to validate and include as a paired comparison.",
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
    if args.baseline_report:
        baseline = json.loads(args.baseline_report.read_text(encoding="utf-8"))
        report["paired_comparison"] = compare_paired_reports(baseline, report)
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(f"{rendered}\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
