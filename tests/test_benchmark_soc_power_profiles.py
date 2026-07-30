"""Behavior tests for the reproducible SOC power-profile benchmark runner."""

import asyncio
import copy
import hashlib
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from scripts.benchmark_soc_power_profiles import (
    benchmark_solver_environment,
    build_benchmark_params,
    build_run_record,
    compare_paired_reports,
    primary_solve_outcome,
    run_benchmarks,
    summarize_runs,
    summarize_timings,
    verify_cache_transition,
    verify_repository_provenance,
)

from emhass.soc_power_profiles import model_size_increase

CORPUS_PATH = (
    Path(__file__).parents[1] / "benchmarks" / "soc_power_profiles" / "payloads.json"
)
RETAINED_RESULT_PATH = (
    Path(__file__).parents[1]
    / "benchmarks"
    / "soc_power_profiles"
    / "results"
    / "2026-07-30"
)
PROJECT_DATA_PATH = Path(__file__).parents[1] / "data"
RESULT_PATHS = [
    PROJECT_DATA_PATH / "last_run.json",
    PROJECT_DATA_PATH / "plan_latest.json",
]


def _git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _repository(tmp_path: Path) -> tuple[Path, str]:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "-q")
    (repository / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(repository, "add", "tracked.txt")
    _git(
        repository,
        "-c",
        "user.name=Benchmark Test",
        "-c",
        "user.email=benchmark@example.invalid",
        "commit",
        "-q",
        "-m",
        "base",
    )
    return repository, _git(repository, "rev-parse", "HEAD")


def test_timing_summary_reports_minimum_median_p95_and_maximum():
    assert summarize_timings([1.0, 2.0, 3.0, 4.0]) == {
        "minimum_s": 1.0,
        "median_s": 2.5,
        "p95_s": pytest.approx(3.85),
        "maximum_s": 4.0,
    }


def test_run_summary_keeps_cold_and_warm_populations_separate():
    runs = [
        {
            "cache_state": "cold",
            "primary_solver_status": "optimal",
            "solver_status": "Optimal",
            "relaxed_fallback_used": False,
            "objective": 12.0,
            "timings_s": {"end_to_end": 10.0},
        },
        {
            "cache_state": "warm",
            "primary_solver_status": "optimal",
            "solver_status": "Optimal",
            "relaxed_fallback_used": False,
            "objective": 12.0,
            "timings_s": {"end_to_end": 2.0},
        },
        {
            "cache_state": "warm",
            "primary_solver_status": "optimal",
            "solver_status": "Optimal",
            "relaxed_fallback_used": False,
            "objective": 12.0,
            "timings_s": {"end_to_end": 4.0},
        },
    ]

    summary = summarize_runs(runs)

    assert set(summary["timing_summary"]) == {"cold", "warm"}
    assert summary["timing_summary"]["cold"]["end_to_end_s"]["median_s"] == 10.0
    assert summary["timing_summary"]["warm"]["end_to_end_s"]["median_s"] == 3.0
    assert summary["absent_profile_objective"] == 12.0


def test_cache_labels_require_observed_object_reuse():
    cold_optimization = object()

    assert verify_cache_transition(
        repetition=0,
        had_cached_instance=False,
        cold_optimization=None,
        current_optimization=cold_optimization,
    ) == ("cold", False, cold_optimization)
    assert verify_cache_transition(
        repetition=1,
        had_cached_instance=True,
        cold_optimization=cold_optimization,
        current_optimization=cold_optimization,
    ) == ("warm", True, cold_optimization)

    with pytest.raises(RuntimeError, match="did not reuse"):
        verify_cache_transition(
            repetition=1,
            had_cached_instance=True,
            cold_optimization=cold_optimization,
            current_optimization=object(),
        )


def test_unsuccessful_solve_remains_reportable_with_counts():
    problem = SimpleNamespace(
        value=None,
        status="infeasible",
        solver_stats=SimpleNamespace(solve_time=None, solver_name="HIGHS"),
        size_metrics=SimpleNamespace(
            num_scalar_variables=4,
            num_scalar_eq_constr=2,
            num_scalar_leq_constr=3,
        ),
        variables=lambda: [],
    )
    optimization = SimpleNamespace(optim_status="Infeasible", prob=problem)
    result = pd.DataFrame({"P_batt": [float("nan")], "SOC_opt": [float("nan")]})

    run = build_run_record(
        repetition=1,
        cache_state="cold",
        cache_reused=False,
        result=result,
        optimization=optimization,
        stage_times={
            "optim_solve.build": 0.1,
            "optim_solve.solve": 0.2,
            "optim_solve.extract": 0.1,
            "optim_solve": 0.4,
        },
        setup_seconds=0.1,
        end_to_end_seconds=0.5,
        primary_solver_status="infeasible",
        relaxed_fallback_used=False,
    )
    summary = summarize_runs([run])

    assert run["objective"] is None
    assert run["power_schedule_w"]["P_batt"] == [None]
    assert run["solver_name"] == "HIGHS"
    assert run["problem_size"]["constraint_rows"] == 5
    assert summary["primary_infeasible_count"] == 1
    assert summary["primary_timeout_count"] == 0
    assert summary["final_unsuccessful_count"] == 1
    assert summary["relaxed_fallback_count"] == 0


def test_unsuccessful_solve_without_solver_stats_remains_reportable():
    problem = SimpleNamespace(
        value=None,
        status=None,
        solver_stats=None,
        size_metrics=SimpleNamespace(
            num_scalar_variables=4,
            num_scalar_eq_constr=2,
            num_scalar_leq_constr=3,
        ),
        variables=lambda: [],
    )
    optimization = SimpleNamespace(optim_status="error", prob=problem)
    result = pd.DataFrame({"P_batt": [float("nan")], "SOC_opt": [float("nan")]})

    run = build_run_record(
        repetition=1,
        cache_state="cold",
        cache_reused=False,
        result=result,
        optimization=optimization,
        stage_times={"optim_solve.solve": 0.2},
        setup_seconds=0.1,
        end_to_end_seconds=0.3,
        primary_solver_status="error",
        relaxed_fallback_used=False,
    )

    assert run["solver_name"] == "unknown"
    assert run["timings_s"]["final_solver"] == 0.0
    assert run["problem_size"]["constraint_rows"] == 5


def test_primary_failure_is_preserved_when_relaxed_fallback_succeeds():
    primary_status, relaxed = primary_solve_outcome(
        [
            "Optimization failed with status: 'user_limit'. "
            "Retrying with relaxed constraints (Continuous LP)..."
        ],
        final_status="Optimal (Relaxed)",
    )

    assert primary_status == "user_limit"
    assert relaxed is True


def test_provenance_requires_clean_descendant_of_recorded_base(tmp_path):
    repository, base_commit = _repository(tmp_path)

    provenance = verify_repository_provenance(repository, base_commit)
    assert provenance["tested_commit"] == base_commit
    assert provenance["merge_base"] == base_commit
    assert provenance["worktree_clean"] is True
    assert provenance["commits_since_base"] == []

    (repository / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="clean worktree"):
        verify_repository_provenance(repository, base_commit)

    _git(repository, "checkout", "-q", "--", "tracked.txt")
    unrelated_commit = _git(
        repository,
        "-c",
        "user.name=Benchmark Test",
        "-c",
        "user.email=benchmark@example.invalid",
        "commit-tree",
        "4b825dc642cb6eb9a060e54bf8d69288fbee4904",
        "-m",
        "unrelated",
    )
    with pytest.raises(RuntimeError, match="merge-base"):
        verify_repository_provenance(repository, unrelated_commit)


def test_benchmark_params_ignore_ambient_credentials_and_location(monkeypatch):
    ambient = {
        "EMHASS_URL": "https://production.example.invalid",
        "SUPERVISOR_TOKEN": "production-token",
        "TIME_ZONE": "Australia/Adelaide",
        "LAT": "-34.9",
        "LON": "138.6",
        "ALT": "50",
    }
    for name, value in ambient.items():
        monkeypatch.setenv(name, value)
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    payload = corpus["payloads"][0]

    params = asyncio.run(
        build_benchmark_params(
            payload["configuration"], corpus["solver"], payload["runtime"]
        )
    )

    retrieve = params["retrieve_hass_conf"]
    assert retrieve["hass_url"] == "http://127.0.0.1/"
    assert retrieve["long_lived_token"] == ""
    assert retrieve["time_zone"] == "UTC"
    assert retrieve["Latitude"] == 0.0
    assert retrieve["Longitude"] == 0.0
    assert retrieve["Altitude"] == 0.0


def test_benchmark_solver_selection_overrides_and_restores_ambient_value(monkeypatch):
    monkeypatch.setenv("LP_SOLVER", "GUROBI")

    with benchmark_solver_environment("HIGHS"):
        assert os.environ["LP_SOLVER"] == "HIGHS"

    assert os.environ["LP_SOLVER"] == "GUROBI"


def test_runner_rejects_non_positive_repetition_count():
    with pytest.raises(ValueError, match="at least one"):
        asyncio.run(run_benchmarks(CORPUS_PATH, repetitions=0))


def test_payload_corpus_contains_no_control_or_credential_fields():
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    serialized_keys = {
        str(key).lower()
        for payload in corpus["payloads"]
        for section in ("configuration", "runtime")
        for key in payload[section]
    }
    assert serialized_keys.isdisjoint(
        {"hass_url", "long_lived_token", "mqtt", "control_endpoint"}
    )


def test_runner_rejects_dependency_lock_metadata_lookup_failure(monkeypatch):
    actual_run = subprocess.run

    def fail_lock_metadata_lookup(command, *args, **kwargs):
        if command[-2:] == ["ls-files", "uv.lock"]:
            return subprocess.CompletedProcess(
                command,
                returncode=128,
                stdout="",
                stderr="simulated lock metadata failure",
            )
        return actual_run(command, *args, **kwargs)

    monkeypatch.setattr(
        "scripts.benchmark_soc_power_profiles.verify_repository_provenance",
        lambda repository, base_commit: {
            "base_commit": base_commit,
            "tested_commit": "f" * 40,
            "merge_base": base_commit,
            "worktree_clean": True,
            "branch": "test-benchmark",
            "commits_since_base": [],
        },
    )
    monkeypatch.setattr(
        "scripts.benchmark_soc_power_profiles.subprocess.run",
        fail_lock_metadata_lookup,
    )

    with pytest.raises(RuntimeError, match="simulated lock metadata failure"):
        asyncio.run(run_benchmarks(CORPUS_PATH, repetitions=1))


def test_runner_records_public_mode_results_for_one_and_multiple_batteries(
    monkeypatch, tmp_path
):
    before_result_files = {
        path: path.read_bytes() if path.exists() else None for path in RESULT_PATHS
    }
    monkeypatch.setattr(
        "scripts.benchmark_soc_power_profiles.verify_repository_provenance",
        lambda repository, base_commit: {
            "base_commit": base_commit,
            "tested_commit": "f" * 40,
            "merge_base": base_commit,
            "worktree_clean": True,
            "branch": "test-benchmark",
            "commits_since_base": [],
        },
    )
    monkeypatch.setenv("LP_SOLVER", "GUROBI")
    monkeypatch.setenv("EMHASS_URL", "https://production.example.invalid")
    monkeypatch.setenv("SUPERVISOR_TOKEN", "production-token")
    monkeypatch.setenv("TIME_ZONE", "Australia/Adelaide")
    monkeypatch.setenv("LAT", "-34.9")
    monkeypatch.setenv("LON", "138.6")
    monkeypatch.setenv("ALT", "50")

    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    corpus["payloads"] = corpus["payloads"][:3]
    small_corpus = tmp_path / "payloads.json"
    small_corpus.write_text(json.dumps(corpus), encoding="utf-8")

    report = asyncio.run(run_benchmarks(small_corpus, repetitions=2))

    after_result_files = {
        path: path.read_bytes() if path.exists() else None for path in RESULT_PATHS
    }
    assert after_result_files == before_result_files
    assert os.environ["LP_SOLVER"] == "GUROBI"
    tested_source = report["reproduction"]["tested_source_provenance"]
    harness = report["reproduction"]["harness_provenance"]
    assert tested_source["base_commit"] == (
        "aef76a4ba9286d5a12f1ca476e56076c70a74951"
    )
    assert tested_source["merge_base"] == tested_source["base_commit"]
    assert tested_source["tested_commit"]
    assert harness["tested_commit"] == tested_source["tested_commit"]
    assert tested_source["worktree_clean"] is True
    assert harness["worktree_clean"] is True
    assert report["reproduction"]["dependency_lock"]["tracked"] is False
    assert report["reproduction"]["pyproject_sha256"]
    assert report["reproduction"]["resolved_packages"]["cvxpy"]
    assert report["reproduction"]["solver"]["name"] == "HIGHS"
    assert report["reproduction"]["solver"]["actual_names"] == ["HIGHS"]
    environment = report["reproduction"]["environment"]
    assert environment["cpu_model"]
    assert environment["hardware_fingerprint_sha256"]
    assert environment["declared_container_image"]
    assert environment["container_id"]
    assert report["reproduction"]["offline_inputs"]["hass_url"] == "http://127.0.0.1/"
    assert report["reproduction"]["offline_inputs"]["long_lived_token"] == ""
    assert report["reproduction"]["offline_inputs"]["time_zone"] == "UTC"
    assert report["repetitions"] == 2
    assert report["benchmark_variant"] == "candidate"
    assert report["schema_version"] == 2
    assert report["execution"]["order"] == "candidate"
    assert datetime.fromisoformat(report["execution"]["completed_at_utc"]) >= (
        datetime.fromisoformat(report["execution"]["started_at_utc"])
    )
    assert report["retained_warning_envelope"] == {
        "boolean_selectors": 1152,
        "added_linear_rows": 2592,
    }

    by_name = {payload["name"]: payload for payload in report["payloads"]}
    assert set(by_name) == {
        "one_battery",
        "two_batteries",
        "one_battery_two_band",
    }

    for payload in by_name.values():
        assert [run["cache_state"] for run in payload["runs"]] == ["cold", "warm"]
        assert [run["cache_reused"] for run in payload["runs"]] == [False, True]
        assert set(payload["timing_summary"]) == {"cold", "warm"}
        assert payload["timing_summary"]["cold"]["end_to_end_s"]["minimum_s"] >= 0
        assert payload["timing_summary"]["warm"]["end_to_end_s"]["p95_s"] >= 0
        assert payload["primary_timeout_count"] == 0
        assert payload["primary_infeasible_count"] == 0
        assert payload["final_unsuccessful_count"] == 0
        assert payload["relaxed_fallback_count"] == 0
        assert isinstance(payload["absent_profile_objective"], float)
        for run in payload["runs"]:
            assert run["solver_status"] in {"Optimal", "optimal"}
            assert run["primary_solver_status"] in {"Optimal", "optimal"}
            assert run["solver_name"] == "HIGHS"
            assert isinstance(run["objective"], float)
            assert len(run["power_schedule_w"]["P_batt"]) == payload["prediction_horizon"]
            assert run["problem_size"]["scalar_variables"] > 0
            assert run["problem_size"]["constraint_rows"] > 0
            assert run["timings_s"]["model_construction"] >= 0
            assert run["timings_s"]["canonicalization_and_wrapper"] >= 0
            assert run["timings_s"]["final_solver"] >= 0
            assert run["timings_s"]["end_to_end"] >= 0

    one = by_name["one_battery"]["runs"][0]
    assert len(one["soc_schedule_fraction"]["SOC_opt"]) == 8
    assert by_name["one_battery"]["profile_model_size"]["battery_count"] == 1
    assert by_name["one_battery"]["profile_model_size"]["direction_presence"] == [
        {"charge": False, "discharge": False}
    ]

    two = by_name["two_batteries"]["runs"][0]
    assert set(two["power_schedule_w"]) >= {"P_batt", "P_batt_0", "P_batt_1"}
    assert set(two["soc_schedule_fraction"]) == {"SOC_opt_0", "SOC_opt_1"}
    assert by_name["two_batteries"]["profile_model_size"]["battery_count"] == 2
    assert by_name["two_batteries"]["profile_model_size"]["band_counts"] == [
        {"charge": 0, "discharge": 0},
        {"charge": 0, "discharge": 0},
    ]

    configured = by_name["one_battery_two_band"]
    assert configured["profile_state"] == "configured"
    assert configured["profile_model_size"]["battery_count"] == 1
    assert configured["profile_model_size"]["direction_presence"] == [
        {"charge": True, "discharge": True}
    ]
    assert configured["profile_model_size"]["band_counts"] == [
        {"charge": 2, "discharge": 2}
    ]
    assert configured["profile_model_size"]["boolean_selectors"] == 16
    assert configured["profile_model_size"]["added_linear_rows"] == 48


def test_corpus_covers_required_profile_shapes_and_warning_envelope():
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    payloads = {payload["name"]: payload for payload in corpus["payloads"]}

    assert {"one_battery", "two_batteries"} <= payloads.keys()
    assert payloads["one_battery"].get("candidate_profiles") is None
    assert payloads["two_batteries"].get("candidate_profiles") is None
    assert len(
        payloads["one_battery_two_band"]["candidate_profiles"][0]["charge"][
            "power_max"
        ]
    ) == 2
    assert len(
        payloads["one_battery_three_band"]["candidate_profiles"][0]["charge"][
            "power_max"
        ]
    ) == 3

    full_size = model_size_increase(
        payloads["three_battery_mixed_48"]["candidate_profiles"], 48
    )
    assert full_size["boolean_selectors"] == 288
    assert full_size["added_linear_rows"] == 816

    envelope_payloads = [
        payload for payload in corpus["payloads"] if payload.get("benchmark_envelope")
    ]
    assert len(envelope_payloads) == 1
    envelope_size = model_size_increase(
        envelope_payloads[0]["candidate_profiles"],
        envelope_payloads[0]["runtime"]["prediction_horizon"],
    )
    assert envelope_size["boolean_selectors"] == 1152
    assert envelope_size["added_linear_rows"] == 2592


def test_paired_report_comparison_requires_absent_profile_equivalence():
    run = {
        "repetition": 1,
        "cache_state": "cold",
        "objective": 1.0,
        "power_schedule_w": {"P_batt": [1.0]},
        "soc_schedule_fraction": {"SOC_opt": [0.5]},
    }
    common_environment = {
        "python": "test",
        "platform": "test",
        "machine": "test",
        "cpu_count": 1,
        "cpu_model": "test CPU",
        "hardware_fingerprint_sha256": "same",
        "containerized": True,
        "container_id": "baseline-container",
        "declared_container_image": "test-image",
        "declared_runtime": "test-runtime",
        "process_settings": {"processes": 1},
    }
    common_reproduction = {
        "solver": {"name": "HIGHS"},
        "offline_inputs": {"hass_url": "http://127.0.0.1/"},
        "environment": common_environment,
        "resolved_packages": {"cvxpy": "test"},
    }
    baseline = {
        "corpus_sha256": "same",
        "repetitions": 1,
        "reproduction": common_reproduction,
        "execution": {
            "order": "baseline",
            "started_at_utc": "2026-07-30T00:00:00+00:00",
            "completed_at_utc": "2026-07-30T00:01:00+00:00",
        },
        "payloads": [{"name": "absent", "runs": [run]}],
    }
    candidate_reproduction = copy.deepcopy(common_reproduction)
    candidate_reproduction["environment"]["container_id"] = "candidate-container"
    candidate = {
        "corpus_sha256": "same",
        "repetitions": 1,
        "reproduction": candidate_reproduction,
        "execution": {
            "order": "candidate",
            "started_at_utc": "2026-07-30T00:02:00+00:00",
            "completed_at_utc": "2026-07-30T00:03:00+00:00",
        },
        "payloads": [
            {
                "name": "absent",
                "profile_state": "absent",
                "runs": [dict(run)],
            }
        ],
    }

    comparison = compare_paired_reports(baseline, candidate)
    assert comparison["environment_parity"] is True
    assert comparison["separate_containers"] is True
    assert comparison["payloads"][0]["runs"][0]["objective_delta"] == 0

    candidate["payloads"][0]["runs"][0]["power_schedule_w"] = {"P_batt": [2.0]}
    with pytest.raises(RuntimeError, match="absent-profile result differs"):
        compare_paired_reports(baseline, candidate)


def test_paired_report_comparison_rejects_payload_reordering():
    environment = {
        "python": "test",
        "platform": "test",
        "machine": "test",
        "cpu_count": 1,
        "cpu_model": "test CPU",
        "hardware_fingerprint_sha256": "same",
        "containerized": True,
        "container_id": "container",
        "declared_container_image": "test-image",
        "declared_runtime": "test-runtime",
        "process_settings": {"processes": 1},
    }
    reproduction = {
        "solver": {"name": "HIGHS"},
        "offline_inputs": {},
        "environment": environment,
        "resolved_packages": {},
    }
    run = {
        "repetition": 1,
        "cache_state": "cold",
        "objective": 0.0,
        "power_schedule_w": {},
        "soc_schedule_fraction": {},
    }
    baseline = {
        "corpus_sha256": "same",
        "repetitions": 1,
        "reproduction": copy.deepcopy(reproduction),
        "execution": {
            "order": "baseline",
            "started_at_utc": "2026-07-30T00:00:00+00:00",
            "completed_at_utc": "2026-07-30T00:01:00+00:00",
        },
        "payloads": [
            {"name": "first", "runs": [run]},
            {"name": "second", "runs": [run]},
        ],
    }
    candidate = copy.deepcopy(baseline)
    candidate["execution"] = {
        "order": "candidate",
        "started_at_utc": "2026-07-30T00:02:00+00:00",
        "completed_at_utc": "2026-07-30T00:03:00+00:00",
    }
    candidate["payloads"] = list(reversed(candidate["payloads"]))
    for payload in candidate["payloads"]:
        payload["profile_state"] = "absent"

    with pytest.raises(RuntimeError, match="names or order differ"):
        compare_paired_reports(baseline, candidate)


def test_retained_paired_result_has_provenance_and_exact_model_deltas():
    baseline = json.loads(
        (RETAINED_RESULT_PATH / "unchanged-base.json").read_text(encoding="utf-8")
    )
    candidate = json.loads(
        (RETAINED_RESULT_PATH / "candidate.json").read_text(encoding="utf-8")
    )

    current_corpus_hash = hashlib.sha256(CORPUS_PATH.read_bytes()).hexdigest()
    assert baseline["corpus_sha256"] == current_corpus_hash
    assert candidate["corpus_sha256"] == current_corpus_hash
    assert baseline["schema_version"] == 2
    assert candidate["schema_version"] == 2
    assert baseline["reproduction"]["tested_source_provenance"]["tested_commit"] == (
        "4def37f83c7ef4cde6900abb0fd68f402fbd1072"
    )
    expected_harness_commit = "a5ad22f3cf13e3a08f3d501298b68c8539a912e4"
    assert (
        baseline["reproduction"]["harness_provenance"]["tested_commit"]
        == expected_harness_commit
    )
    assert (
        candidate["reproduction"]["harness_provenance"]["tested_commit"]
        == expected_harness_commit
    )
    assert (
        candidate["reproduction"]["tested_source_provenance"]["tested_commit"]
        == expected_harness_commit
    )
    independent_comparison = compare_paired_reports(baseline, candidate)
    assert independent_comparison["environment_parity"] is True
    assert independent_comparison["separate_containers"] is True
    assert independent_comparison["baseline_completed_before_candidate_started"] is True

    required_shape_fields = {
        "horizon",
        "battery_count",
        "direction_presence",
        "band_counts",
        "boolean_selectors",
        "added_linear_rows",
    }
    for report in (baseline, candidate):
        for payload in report["payloads"]:
            assert required_shape_fields <= payload["scenario_profile_shape"].keys()
            assert required_shape_fields <= payload["profile_model_size"].keys()

        absent_payloads = {payload["name"]: payload for payload in report["payloads"]}
        assert absent_payloads["one_battery"]["profile_model_size"][
            "battery_count"
        ] == 1
        assert absent_payloads["one_battery"]["profile_model_size"][
            "direction_presence"
        ] == [{"charge": False, "discharge": False}]
        assert absent_payloads["one_battery"]["profile_model_size"]["band_counts"] == [
            {"charge": 0, "discharge": 0}
        ]
        assert absent_payloads["two_batteries"]["profile_model_size"][
            "battery_count"
        ] == 2
        assert absent_payloads["two_batteries"]["profile_model_size"][
            "direction_presence"
        ] == [
            {"charge": False, "discharge": False},
            {"charge": False, "discharge": False},
        ]
        assert absent_payloads["two_batteries"]["profile_model_size"][
            "band_counts"
        ] == [
            {"charge": 0, "discharge": 0},
            {"charge": 0, "discharge": 0},
        ]

    baseline_payloads = {payload["name"]: payload for payload in baseline["payloads"]}
    for payload in candidate["payloads"]:
        assert payload["scenario_profile_shape"]["horizon"] == payload[
            "prediction_horizon"
        ]
        assert payload["scenario_profile_shape"]["battery_count"] == len(
            payload["scenario_profile_shape"]["band_counts"]
        )
        baseline_run = baseline_payloads[payload["name"]]["runs"][0]
        candidate_run = payload["runs"][0]
        assert (
            candidate_run["problem_size"]["boolean_variables"]
            - baseline_run["problem_size"]["boolean_variables"]
            == payload["profile_model_size"]["boolean_selectors"]
        )
        assert (
            candidate_run["problem_size"]["constraint_rows"]
            - baseline_run["problem_size"]["constraint_rows"]
            == payload["profile_model_size"]["added_linear_rows"]
        )
        assert payload["primary_timeout_count"] == 0
        assert payload["primary_infeasible_count"] == 0
        assert payload["final_unsuccessful_count"] == 0
        assert payload["relaxed_fallback_count"] == 0
