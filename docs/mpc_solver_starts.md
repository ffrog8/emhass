# Rolling MPC solver starts and failed solves

Rolling MPC retains the compiled optimisation model and gives HiGHS suggestions for later integer decisions from
the previous accepted primary solve. It leaves the first interval and every continuous variable unspecified, so the
current charging action can be selected using the current inputs rather than a complete old solution.

These suggestions do not change constraints, prices, forecasts, the objective, or the configured solver gap. They
do not guarantee maximum charging or an exact optimum. HiGHS may disregard a suggestion when current inputs make it
unsuitable. Day-ahead and perfect-forecast optimisation retain their existing solver-start behaviour.

## Ownership and invalidation

`Optimization.perform_naive_mpc_optim` enables the start preparation owned by `Optimization.perform_optimization`.
`mpc_start.prepare_start` maps explicitly registered chronological variable axes into CVXPY's canonical integer
columns. Later intervals are matched by timestamp; unknown variables and intervals without a matching previous
timestamp receive no suggestion. The first interval always receives no suggestion.

The owning optimiser records the problem identity and dates only after a primary solve returns normally with
`optimal` status. Missing metadata, an unsuccessful previous solve, changed canonical structure, invalid timestamps,
an incompatible axis, or invalid integer values discard the cached solver start while retaining compilation.
Fallback results never establish primary-start provenance. There is no new configuration parameter or disk state.

This implementation uses CVXPY's private solver cache and canonical variable mapping, plus HiGHS's undefined
solution values. Dependency upgrades must run the real-solver contract tests in `tests/test_mpc_start.py`, especially
first-interval exclusion, timestamp shifts, changed-input feasibility, and compilation retention.

## Solver exceptions

A cached CVXPY problem can retain its old status and values after `solve()` raises. EMHASS now accepts a result only
from a solve that returns normally during the current request. A primary exception triggers the existing fallback.
If fallback also raises, the result contains only `optim_status: Failure`; old power values are not returned as a
successful new schedule.

This does not erase an already published HA schedule or command equipment. Existing failed-run recording and
publication rejection apply to the failed new result. `tests/test_solver_exception_results.py` covers primary and
fallback exceptions, recovery, preservation of the last valid API plan, and refusal to publish a failed result.

## Accepted plan and publication

Only a current MPC result with an exact `Optimal` status and usable plan columns replaces the latest CSV, saved
planner entities and `/api/v1/plan` snapshot. A failed solve, rejected numerical result or relaxed fallback records
the failed run in `/api/v1/last-run` while retaining the last accepted plan for inspection. Retention does not make
that plan a fresh answer to the rejected request.

Later `publish-data` calls read the latest run verdict from `last_run.json` before reusing a saved CSV. A rejected
MPC run also marks existing optimiser CSVs and saved planner entities as blocked in `entities/metadata.json`; it
does not change their data values. This keeps old MPC artifacts blocked even if a later day-ahead run succeeds.
Saving a new CSV clears only that filename's block, and saving a new entity clears only that entity's block.
`continual_publish` applies the same entity check. Independently saved `mlforecaster` and `mlregressor` entities
can continue publishing.

The run-verdict check reads the file directly because each web worker has its own in-memory cache. If that verdict
or saved-artifact metadata cannot be read, saved plan publication stops. A disk failure that prevents the rejected
verdict or artifact flags from being written cannot be communicated reliably to another worker. The metadata
read-modify-write lock covers tasks in one worker; simultaneous updates from separate workers can race. Those
storage failures and concurrent writes remain operational limitations.

## Verification scope

Earlier solver-exception integration, before this MPC change, passed all seven solver-exception tests and ten
partial-start contract cases. Its full isolated suite reported 1,289 passed, 3 failed, 0 skipped and 32 expected failures. Its
three weather-test failures reproduce without the solver-exception fix: two tests depend on an unmocked Open-Meteo
request, and one mocks an outdated URL. They remain separate from these solver changes.

Full-suite durations are not controlled MPC response-time measurements. The regression suite does not establish a
universal maximum 0.25-second slowdown or validate live HA publication and physical equipment response.
