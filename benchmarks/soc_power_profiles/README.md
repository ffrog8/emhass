# SOC power-profile benchmark

This benchmark compares the unchanged upstream optimizer with the exact
`battery_soc_power_profiles` implementation. It runs the credential-free
payloads in `payloads.json` through
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

The corpus contains absent profiles, representative two- and three-band
profiles, the three-battery mixed 48-interval shape (288 selectors and 816
rows), and a deliberately larger valid shape. The larger shape contains five
charge and five discharge bands for each of three batteries over 48 intervals:
1,152 selectors and 2,592 rows. It is the retained warning evidence boundary,
not a universal performance guarantee or a band-count limit.

Use the repository development environment described in `docs/develop.md`.
Run the harness-only benchmark commit against the unchanged optimizer with
`--unchanged-base`, then run the candidate checkout in the same environment:

```bash
uv sync --extra test
python scripts/benchmark_soc_power_profiles.py \
  --repetitions 5 \
  --unchanged-base \
  --output /tmp/emhass-soc-profile-unchanged-base.json

python scripts/benchmark_soc_power_profiles.py \
  --repetitions 5 \
  --baseline-report /tmp/emhass-soc-profile-unchanged-base.json \
  --output /tmp/emhass-soc-profile-candidate.json
```

Use the same corpus, repetition count, solver settings, machine, container, and
resolved environment for both runs. Each repetition performs one cold
construction followed by one solve that reuses the resulting cached
`Optimization` and CVXPY `Problem`. Five repetitions therefore produce five
cold and five warm samples per payload. Retain both raw JSON files with the
corpus and source revisions.

The output records:

- base and tested commits, branch, feature-only ancestry, corpus hash, and
  `pyproject.toml` hash;
- Python/platform details and all resolved package versions;
- the configured solver, timeout, relative MIP gap, and thread count;
- equal cold-construction and warm-cache sample populations;
- solver status, objective, battery power schedule, and SOC schedule;
- primary timeout/infeasible counts, final unsuccessful counts, and whether the
  relaxed fallback was used;
- actual solver names and generic CVXPY scalar-variable, Boolean-variable, and
  constraint-row counts;
- input setup, model construction, solver, result extraction, optimisation-mode,
  and end-to-end wall times;
- separate cold and warm minimum, median, p95, and maximum values for every
  timing field.
- profile direction presence, per-direction band counts, exact selector count,
  and exact added row count for every payload;
- paired environment checks and objective/power/SOC deltas, with absent-profile
  equality enforced at `1e-6`.

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

The unchanged-base run uses the current harness and corpus but ignores
`candidate_profiles`; the optimizer itself remains unchanged. This separates
measurement tooling from feature code while keeping payloads, sample ordering,
and environment identical. The candidate run applies those profiles, and
`--baseline-report` rejects environment or absent-profile result mismatches.

Normal EMHASS execution logs `T*K` Boolean selectors and `T*(2*K+R)` added
linear rows before constructing a supplied profile model. Requests above the
retained 1,152-selector or 2,592-row boundary remain accepted and emit one
advisory warning. Solver timeout starts only when solving after problem
construction; this warning is not a request-size, memory, or service-safety
control. The benchmark and warning do not authorize real control use.
