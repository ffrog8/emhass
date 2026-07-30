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
Run the issue #2 runner at unchanged optimizer checkout `4def37f8` against this
same expanded corpus, then run the candidate checkout in the same environment:

```bash
uv sync --extra test
python scripts/benchmark_soc_power_profiles.py \
  --corpus /path/to/candidate/benchmarks/soc_power_profiles/payloads.json \
  --repetitions 5 \
  --output /tmp/emhass-soc-profile-unchanged-base.json

python scripts/benchmark_soc_power_profiles.py \
  --repetitions 5 \
  --baseline-report /tmp/emhass-soc-profile-unchanged-base.json \
  --output /tmp/emhass-soc-profile-candidate.json
```

Use the same corpus, repetition count, solver settings, machine, container, and
resolved environment for both runs. The first repetition performs cold
construction, and the next four reuse the resulting cached `Optimization` and
CVXPY `Problem`. Retain both raw JSON files with the corpus and source
revisions.

The output records:

- base and tested commits, branch, feature-only ancestry, corpus hash, and
  `pyproject.toml` hash;
- Python/platform details and all resolved package versions;
- the configured solver, timeout, relative MIP gap, and thread count;
- cold construction and warm-cache repetitions reported separately;
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

The unchanged runner at `4def37f8` does not know the corpus's optional
`candidate_profiles` member, so it uses the common scalar configuration and
runtime while retaining an unmodified optimizer. Its report records tested
commit `4def37f8`. The candidate runner applies those profiles, and
`--baseline-report` rejects environment or absent-profile result mismatches.

Normal EMHASS execution logs `T*K` Boolean selectors and `T*(2*K+R)` added
linear rows before constructing a supplied profile model. Requests above the
retained 1,152-selector or 2,592-row boundary remain accepted and emit one
advisory warning. Solver timeout starts only when solving after problem
construction; this warning is not a request-size, memory, or service-safety
control. The benchmark and warning do not authorize real control use.

## Retained paired result

The raw 30 July 2026 reports are retained in
`results/2026-07-30/unchanged-base.json` and
`results/2026-07-30/candidate.json`. Both use corpus SHA-256
`8433341de57b66ecb630325d4549c1adb6a3989e58b9247bcb00a0fd704447d6`,
Python 3.12.12, CVXPY 1.7.5, highspy 1.15.1, one HiGHS thread, a 30-second
solver limit, and a 0.01 relative MIP gap on the same eight-CPU x86_64
container host. The comparator confirmed identical resolved packages and
environment metadata.

The unchanged optimizer was commit `4def37f8`; the candidate was
`d6d9f91f`. Each row has one cold sample and four warm samples. Candidate
end-to-end seconds were:

| Scenario | Selectors / rows | Cold | Warm min | Warm median | Warm p95 | Warm max |
|---|---:|---:|---:|---:|---:|---:|
| One battery, no profile | 0 / 0 | 0.181 | 0.030 | 0.034 | 0.042 | 0.043 |
| Two batteries, no profile | 0 / 0 | 0.131 | 0.030 | 0.034 | 0.037 | 0.038 |
| Two-band charge/discharge | 16 / 48 | 0.172 | 0.040 | 0.042 | 0.044 | 0.044 |
| Three-band charge/discharge | 32 / 80 | 0.150 | 0.034 | 0.042 | 0.050 | 0.051 |
| Three-battery mixed, 48 intervals | 288 / 816 | 2.384 | 0.150 | 0.157 | 0.162 | 0.163 |
| Deliberately large, 48 intervals | 1,152 / 2,592 | 14.618 | 0.358 | 0.368 | 0.408 | 0.414 |

The paired end-to-end impact against the scalar optimizer was:

| Scenario | Base cold | Candidate cold | Cold delta | Base warm median | Candidate warm median | Warm delta / ratio |
|---|---:|---:|---:|---:|---:|---:|
| One battery, no profile | 0.085 | 0.181 | +0.096 | 0.026 | 0.034 | +0.007 / 1.28x |
| Two batteries, no profile | 0.110 | 0.131 | +0.021 | 0.028 | 0.034 | +0.006 / 1.21x |
| Two-band charge/discharge | 0.123 | 0.172 | +0.049 | 0.025 | 0.042 | +0.017 / 1.66x |
| Three-band charge/discharge | 0.067 | 0.150 | +0.083 | 0.028 | 0.042 | +0.015 / 1.53x |
| Three-battery mixed, 48 intervals | 0.570 | 2.384 | +1.814 | 0.093 | 0.157 | +0.064 / 1.69x |
| Deliberately large, 48 intervals | 0.566 | 14.618 | +14.051 | 0.094 | 0.368 | +0.274 / 3.94x |

The profile rows compare the exact selector model with the same scalar payload
on the unchanged optimizer, so the timing delta measures the added formulation
and its changed solve. The absent-profile rows prove result equivalence, but
their small timing differences show the residual process and measurement noise
in this sample; they are not evidence of a mathematical model change.

For the mixed case, cold model construction, canonicalisation/wrapper, and
solver times were 0.009, 0.140, and 2.210 seconds; their warm medians were
0.001, 0.006, and 0.128 seconds. For the deliberately large case, the same
values were 0.014, 0.289, and 14.291 seconds cold and 0.001, 0.009, and 0.333
seconds warm. The raw reports retain minimum, median, p95, and maximum for
every timing field.

All 60 solves were successful: zero timeouts, infeasible solves, unsuccessful
final statuses, or relaxed fallbacks. For both absent-profile scenarios, all
five paired runs had exactly zero objective, battery-power schedule, and SOC
schedule difference at the configured `1e-6` comparison tolerance.

These results show that the representative 288-selector model is within a
30-minute planning cycle on this host, including cold construction. They do
not authorize real control: one cold sample cannot establish a cold-start tail,
the deliberately large case took 14.6 seconds cold, and a different payload,
solver, host, or profile may behave differently. Shadow validation remains
required before control use.
