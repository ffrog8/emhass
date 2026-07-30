"""Behavior tests for the reproducible SOC power-profile benchmark runner."""

import asyncio
import json
from pathlib import Path

import pytest
from scripts.benchmark_soc_power_profiles import run_benchmarks, summarize_timings

CORPUS_PATH = (
    Path(__file__).parents[1] / "benchmarks" / "soc_power_profiles" / "payloads.json"
)
PROJECT_DATA_PATH = Path(__file__).parents[1] / "data"


def test_timing_summary_reports_minimum_median_p95_and_maximum():
    assert summarize_timings([1.0, 2.0, 3.0, 4.0]) == {
        "minimum_s": 1.0,
        "median_s": 2.5,
        "p95_s": pytest.approx(3.85),
        "maximum_s": 4.0,
    }


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


def test_runner_records_public_mode_results_for_one_and_multiple_batteries():
    report = asyncio.run(run_benchmarks(CORPUS_PATH, repetitions=2))

    assert not (PROJECT_DATA_PATH / "last_run.json").exists()
    assert not (PROJECT_DATA_PATH / "plan_latest.json").exists()
    assert report["reproduction"]["base_commit"] == (
        "aef76a4ba9286d5a12f1ca476e56076c70a74951"
    )
    assert report["reproduction"]["dependency_lock"]["tracked"] is False
    assert report["reproduction"]["pyproject_sha256"]
    assert report["reproduction"]["resolved_packages"]["cvxpy"]
    assert report["reproduction"]["solver"]["name"] == "HIGHS"
    assert report["repetitions"] == 2

    by_name = {payload["name"]: payload for payload in report["payloads"]}
    assert set(by_name) == {"one_battery", "two_batteries"}

    for payload in by_name.values():
        assert [run["cache_state"] for run in payload["runs"]] == ["cold", "warm"]
        assert payload["timing_summary"]["end_to_end_s"]["minimum_s"] >= 0
        assert payload["timing_summary"]["end_to_end_s"]["p95_s"] >= 0
        for run in payload["runs"]:
            assert run["solver_status"] in {"Optimal", "optimal"}
            assert isinstance(run["objective"], float)
            assert len(run["power_schedule_w"]["P_batt"]) == payload["prediction_horizon"]
            assert run["timings_s"]["model_construction"] >= 0
            assert run["timings_s"]["canonicalization_and_wrapper"] >= 0
            assert run["timings_s"]["solver"] >= 0
            assert run["timings_s"]["end_to_end"] >= 0

    one = by_name["one_battery"]["runs"][0]
    assert len(one["soc_schedule_fraction"]["SOC_opt"]) == 8

    two = by_name["two_batteries"]["runs"][0]
    assert set(two["power_schedule_w"]) >= {"P_batt", "P_batt_0", "P_batt_1"}
    assert set(two["soc_schedule_fraction"]) == {"SOC_opt_0", "SOC_opt_1"}
