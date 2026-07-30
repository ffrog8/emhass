# SOC power-profile benchmark

This benchmark captures the unchanged upstream model before
`battery_soc_power_profiles` is implemented. It runs the credential-free
one-battery and two-battery payloads in `payloads.json` through
`set_input_data_dict` and `naive_mpc_optim`, the same configuration/runtime
input and optimisation-mode seam used by ordinary requests.

The recorded upstream fixed point is
`aef76a4ba9286d5a12f1ca476e56076c70a74951`. The feature branch must start at
that commit. Verify the branch point and inspect every feature-only commit with:

```bash
git merge-base upstream/master HEAD
git log --oneline aef76a4ba9286d5a12f1ca476e56076c70a74951..HEAD
```

## Run

Use the repository development environment described in `docs/develop.md`:

```bash
uv sync --extra test
python scripts/benchmark_soc_power_profiles.py \
  --repetitions 5 \
  --output /tmp/emhass-soc-profile-baseline.json
```

Run the unchanged base and later selector branch with the same corpus,
repetition count, solver settings, machine, and resolved environment. Keep each
JSON output so schedules, objectives, statuses, and timings can be compared.

The output records:

- base and tested commits, branch, feature-only ancestry, corpus hash, and
  `pyproject.toml` hash;
- Python/platform details and all resolved package versions;
- the configured solver, timeout, relative MIP gap, and thread count;
- cold first execution and warm-cache repetitions;
- solver status, objective, battery power schedule, and SOC schedule;
- primary timeout/infeasible counts, final unsuccessful counts, and whether the
  relaxed fallback was used;
- actual solver names and generic CVXPY scalar-variable, Boolean-variable, and
  constraint-row counts;
- input setup, model construction, solver, result extraction, optimisation-mode,
  and end-to-end wall times;
- separate cold and warm minimum, median, p95, and maximum values for every
  timing field.

At this upstream fixed point, the repository ignores and does not track
`uv.lock`. The report therefore marks the dependency lock as unavailable and
records the project file hash plus resolved versions. This is a reproducibility
limitation: retain the first report and execute the paired comparison in the
same environment.

`canonicalization_and_wrapper` is the instrumented CVXPY solve-call wall time
minus `solver_stats.solve_time`. Current EMHASS instrumentation cannot separate
CVXPY canonicalisation from its remaining wrapper overhead, so the report names
that combined value explicitly. If relaxed fallback runs, this derived field is
`null` because the solve-call timer contains both primary and fallback work
while `solver_stats.solve_time` describes only the final problem.

The runner uses `get_data_from_file=True`, disables result publishing, and
redirects normal last-run/plan files into a temporary directory. It reads no
production credentials, contacts no Home Assistant endpoint, and grants no
control authority. Fixed loopback/empty/UTC/zero location inputs replace all
ambient Home Assistant credentials and location variables. The configured
solver temporarily overrides ambient `LP_SOLVER` and is restored after the run.

The unchanged base has no SOC-profile selectors, so it cannot report a
feature-specific selector count. Generic Boolean-variable and constraint-row
counts provide the model-size baseline; the later exact-selector implementation
must add its feature-specific selector/row accounting when those structures
exist.
