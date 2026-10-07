"""Prepare timestamp-aligned partial HiGHS starts for rolling MPC.

The owner supplies explicit variable time axes and records dates only after an
accepted PRIMARY MPC solve. Compiled CVXPY data is retained. No constraints,
objectives, solver options, or global classes are changed here.
HiGHS undefined user-solution values: https://github.com/ERGO-Code/HiGHS/releases/tag/v1.8.0
"""

import cvxpy as cp
import highspy
import numpy as np
import pandas as pd


def prepare_start(problem, previous_dates, current_dates, time_axes):
    """Replace only this problem's cached primal start with later integer hints.

    time_axes maps original CVXPY variable IDs to their owned timestep axes.
    Unknown variables receive no suggestion; dimensions alone are not a mapping.
    Invalid/stale cache information discards solver start data, not compilation.
    """
    cached = problem._solver_cache.get("HIGHS")
    if cached is None:
        return {"reason": "cold", "hint_count": 0}

    def discard(reason):
        problem._solver_cache.pop("HIGHS", None)
        return {"reason": reason, "hint_count": 0}

    if previous_dates is None:
        return discard("missing_previous_dates")
    old_dates = pd.DatetimeIndex(previous_dates)
    dates = pd.DatetimeIndex(current_dates)
    if (
        old_dates.tz is None
        or dates.tz is None
        or not old_dates.is_unique
        or not dates.is_unique
        or not old_dates.is_monotonic_increasing
        or not dates.is_monotonic_increasing
        or len(dates) == 0
        or len(old_dates) == 0
        or dates[0] < old_dates[0]
    ):
        return discard("invalid_timestamps")
    old_solver, old_data, old_result = cached
    if old_result.get("model_status") != "kOptimal":
        return discard("previous_solve_not_optimal")
    data = problem.get_problem_data(cp.HIGHS)[0]
    param = data["param_prob"]
    if param is not old_data.get("param_prob"):
        return discard("canonical_model_changed")
    source = np.asarray(old_result["solution"].col_value, dtype=float)
    if source.shape != (len(data["c"]),):
        return discard("column_count_changed")
    dense = np.full(source.size, highspy.kHighsUndefined)
    integers = set(data.get("bool_vars_idx", [])) | set(data.get("int_vars_idx", []))
    old_positions = old_dates.get_indexer(dates)
    count = 0
    for variable in param.variables:
        axis = time_axes.get(variable.id)
        if axis is None:
            continue
        if (
            not 0 <= axis < len(variable.shape)
            or variable.shape[axis] != len(dates)
            or len(old_dates) != len(dates)
        ):
            return discard("invalid_time_axis")
        offset = param.var_id_to_col[variable.id]
        columns = np.arange(offset, offset + variable.size).reshape(variable.shape, order="F")
        columns = np.moveaxis(columns, axis, 0).reshape(len(dates), -1)
        for t in range(1, len(dates)):
            old_t = old_positions[t]
            if old_t < 0:
                continue
            for col, old_col in zip(columns[t], columns[old_t]):
                if int(col) not in integers:
                    continue
                value = source[old_col]
                if not np.isfinite(value) or abs(value - round(value)) > 1e-6:
                    return discard("invalid_integer_hint")
                dense[col] = round(value)
                count += 1
    if count == 0:
        return discard("no_matching_integer_hints")
    partial = highspy.HighsSolution()
    partial.col_value = dense
    partial.value_valid = True
    partial.dual_valid = False
    problem._solver_cache["HIGHS"] = (old_solver, old_data, dict(old_result, solution=partial))
    return {"reason": "partial_timestamp_aligned", "hint_count": count}
