"""Exercise partial solver starts against real CVXPY and HiGHS models."""

import cvxpy as cp
import highspy
import numpy as np
import pandas as pd
import pytest

from emhass.mpc_start import prepare_start


@pytest.mark.parametrize(
    "case",
    [
        "omit_first_and_continuous",
        "shift_timestamp",
        "missing_metadata",
        "failed_previous_solve",
        "invalid_time_axis",
        "unknown_variables",
        "duplicate_timestamps",
        "backwards_time",
        "cold_model",
        "changed_inputs_feasible",
    ],
)
def test_partial_start_contract(case):
    modes = cp.Variable((2, 3), boolean=True)
    continuous = cp.Variable(3)
    bound = cp.Parameter(3, value=[2, 2, 2])
    problem = cp.Problem(
        cp.Minimize(cp.sum(continuous) - 10 * cp.sum(modes)),
        [continuous >= cp.sum(modes, axis=0), continuous >= 0, continuous <= bound],
    )
    dates = pd.date_range("2026-10-03T01:00:00Z", periods=3, freq="30min")
    if case != "cold_model":
        problem.solve(solver=cp.HIGHS, threads=1)
    compilation = problem._cache.param_prog
    previous = dates
    current = dates
    axes = {modes.id: 1, continuous.id: 0}
    if case == "missing_metadata":
        previous = None
    if case == "shift_timestamp":
        current = dates + pd.Timedelta(minutes=30)
    if case == "failed_previous_solve":
        solver, data, result = problem._solver_cache["HIGHS"]
        problem._solver_cache["HIGHS"] = (solver, data, dict(result, model_status="kTimeLimit"))
    if case == "invalid_time_axis":
        axes = {modes.id: 0}
    if case == "unknown_variables":
        axes = {}
    if case == "duplicate_timestamps":
        current = pd.DatetimeIndex([dates[0], dates[0], dates[2]])
    if case == "backwards_time":
        current = dates - pd.Timedelta(minutes=30)
    if case == "changed_inputs_feasible":
        bound.value = [0, 2, 2]

    result = prepare_start(problem, previous, current, axes)
    assert problem._cache.param_prog is compilation
    if case in ("omit_first_and_continuous", "shift_timestamp", "changed_inputs_feasible"):
        assert result["hint_count"] == (2 if case == "shift_timestamp" else 4)
        _, data, cached = problem._solver_cache["HIGHS"]
        columns = data["param_prob"].var_id_to_col
        hints = np.asarray(cached["solution"].col_value)
        assert np.all(hints[columns[modes.id] : columns[modes.id] + 2] == highspy.kHighsUndefined)
        assert np.all(
            hints[columns[continuous.id] : columns[continuous.id] + 3] == highspy.kHighsUndefined
        )
        problem.solve(solver=cp.HIGHS, warm_start=True, threads=1)
        assert problem.status == cp.OPTIMAL
        assert max(float(np.max(c.violation())) for c in problem.constraints) < 1e-7
        if case == "changed_inputs_feasible":
            assert np.allclose(modes.value[:, 0], 0)
    else:
        assert result["hint_count"] == 0
        assert "HIGHS" not in problem._solver_cache
