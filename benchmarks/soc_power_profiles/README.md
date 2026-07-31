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
Use the clean candidate checkout's harness for both runs. For the baseline
process, execute that harness in the clean `4def37f8` project environment and
point `--project-root` at that unchanged source checkout:

```bash
uv sync --extra test
python /path/to/candidate/scripts/benchmark_soc_power_profiles.py \
  --corpus /path/to/candidate/benchmarks/soc_power_profiles/payloads.json \
  --project-root /path/to/unchanged-4def37f8 \
  --execution-order baseline \
  --repetitions 5 \
  --output /tmp/emhass-soc-profile-unchanged-base.json

python scripts/benchmark_soc_power_profiles.py \
  --execution-order candidate \
  --repetitions 5 \
  --baseline-report /tmp/emhass-soc-profile-unchanged-base.json \
  --output /tmp/emhass-soc-profile-candidate.json
```

Use the same corpus, repetition count, solver settings, Docker host, declared
container image, and process settings for both runs. Separate containers are
allowed and are reported rather than described as one container. The first
repetition performs cold construction, and the next four reuse the resulting
cached `Optimization` and CVXPY `Problem`. Retain both raw JSON files with the
corpus and source revisions.

The output records:

- separate harness and tested-source commits, branches, ancestry and
  cleanliness, plus the corpus and `pyproject.toml` hashes;
- every imported EMHASS production module's tested-source-relative path and
  SHA-256, after rejecting any ambient module outside the explicit tested root;
- UTC process order/timestamps, container identity, declared image/runtime,
  nonempty CPU identity/fingerprint, and all resolved package versions;
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

`cvxpy_compilation` is CVXPY's own `Problem.compilation_time` for the final
solve attempt. `final_solver` is `solver_stats.solve_time`.
`solve_wrapper_overhead` is the instrumented solve-call wall time minus those
two measurements. It is not labelled canonicalisation. If relaxed fallback
runs, the residual is `null` because the solve-call timer spans multiple
attempts while CVXPY's compilation and solver fields describe only the final
problem.

Cold means a newly constructed EMHASS `Optimization` and CVXPY `Problem`.
Warm means those objects are reused. CVXPY still records each warm solve's
compilation or cached reduction lookup in `Problem.compilation_time`; warm does
not mean that field must be zero.

The runner uses `get_data_from_file=True`, disables result publishing, and
redirects normal last-run/plan files into a temporary directory. It reads no
production credentials, contacts no Home Assistant endpoint, and grants no
control authority. Fixed loopback/empty/UTC/zero location inputs replace all
ambient Home Assistant credentials and location variables. The configured
solver temporarily overrides ambient `LP_SOLVER` and is restored after the run.

The shared harness omits `candidate_profiles` only for the baseline execution,
while importing and executing EMHASS from the clean `4def37f8` project root.
The report records the harness commit separately from tested source commit
`4def37f8`. The candidate process imports the candidate tested source and
applies the profiles. `--baseline-report` rejects common-input, execution-order,
host-characteristic, process-setting, package, or absent-profile result
mismatches. It also reads every reported production module from the declared
tested commit in the local Git object database and rejects a missing commit,
missing path, or content hash mismatch.

Every normal optimization request logs `T*K` Boolean selectors and
`T*(2*K+R)` added linear rows before cache selection. This includes cache hits
and explicit scalar-only replacements, which report 0 selectors and 0 rows.
Requests above the
retained 1,152-selector or 2,592-row boundary remain accepted and emit one
advisory warning. Solver timeout starts only when solving after problem
construction; this warning is not a request-size, memory, or service-safety
control. The benchmark and warning do not authorize real control use.

## Retained paired result

The raw 30 July 2026 reports are retained in
`results/2026-07-30/unchanged-base.json` and
`results/2026-07-30/candidate.json`. Both use corpus SHA-256
`55b6a370af365f5b78d49be75cd8f7a3a5bb4e3306a0dd402b43c6e80487eaa1`,
Python 3.12.12, CVXPY 1.7.5, highspy 1.15.1, one HiGHS thread, a 30-second
solver limit, and a 0.01 relative MIP gap on the same eight-CPU x86_64
Docker host. The reports identify two separate containers using the same
declared image and process settings. The comparator confirmed identical
resolved packages, hardware fingerprint, and stable environment metadata.

The shared benchmark harness was commit `1ac3b380`. The unchanged optimizer
under test was commit `4def37f8`; the candidate optimizer was `1ac3b380`.
The reports verify that the baseline optimizer module came from the baseline
source root with SHA-256 `1668ff6a...6d05fb`, while the candidate optimizer
module came from the candidate source root with SHA-256
`ce5336b5...f379a6`.
Each row has one cold sample and four warm samples. Candidate end-to-end
seconds were:

| Scenario | Selectors / rows | Cold | Warm min | Warm median | Warm p95 | Warm max |
|---|---:|---:|---:|---:|---:|---:|
| One battery, no profile | 0 / 0 | 0.137 | 0.024 | 0.026 | 0.028 | 0.028 |
| Two batteries, no profile | 0 / 0 | 0.097 | 0.026 | 0.028 | 0.029 | 0.029 |
| Two-band charge/discharge | 16 / 48 | 0.076 | 0.026 | 0.026 | 0.026 | 0.027 |
| Three-band charge/discharge | 32 / 80 | 0.128 | 0.027 | 0.027 | 0.027 | 0.027 |
| Three-battery mixed, 48 intervals | 288 / 816 | 2.282 | 0.152 | 0.158 | 0.192 | 0.198 |
| Deliberately large, 48 intervals | 1,152 / 2,592 | 14.698 | 0.341 | 0.356 | 0.368 | 0.369 |

The paired end-to-end impact against the scalar optimizer was:

| Scenario | Base cold | Candidate cold | Cold delta | Base warm median | Candidate warm median | Warm delta / ratio |
|---|---:|---:|---:|---:|---:|---:|
| One battery, no profile | 0.088 | 0.137 | +0.049 | 0.028 | 0.026 | -0.002 / 0.92x |
| Two batteries, no profile | 0.096 | 0.097 | +0.001 | 0.028 | 0.028 | +0.001 / 1.02x |
| Two-band charge/discharge | 0.069 | 0.076 | +0.006 | 0.025 | 0.026 | +0.001 / 1.05x |
| Three-band charge/discharge | 0.070 | 0.128 | +0.058 | 0.025 | 0.027 | +0.002 / 1.07x |
| Three-battery mixed, 48 intervals | 0.581 | 2.282 | +1.701 | 0.092 | 0.158 | +0.066 / 1.72x |
| Deliberately large, 48 intervals | 0.560 | 14.698 | +14.138 | 0.090 | 0.356 | +0.266 / 3.94x |

The profile rows compare the exact selector model with the same scalar payload
on the unchanged optimizer, so the timing delta measures the added formulation
and its changed solve. The absent-profile rows prove result equivalence, but
their small timing differences show the residual process and measurement noise
in this sample; they are not evidence of a mathematical model change.

For the mixed case, cold model construction, CVXPY compilation, solver, and
wrapper-overhead times were 0.008, 0.173, 2.074, and 0.004 seconds; their warm
medians were 0.001, 0.001, 0.128, and 0.005 seconds. For the deliberately
large case, the same values were 0.017, 0.231, 14.414, and 0.009 seconds cold
and 0.001, 0.001, 0.325, and 0.007 seconds warm. The raw reports retain
minimum, median, p95, and maximum for every timing field and scenario.

All 60 solves were successful: zero timeouts, infeasible solves, unsuccessful
final statuses, or relaxed fallbacks. For both absent-profile scenarios, all
five paired runs had exactly zero objective, battery-power schedule, and SOC
schedule difference at the configured `1e-6` comparison tolerance.

These results show that the representative 288-selector model is within a
30-minute planning cycle on this host, including the measured cold
construction. They do not authorize real control: each scenario has only one
cold observation, so cold minimum, median, p95, and maximum are the same value
and cannot establish a cold-start distribution or tail. The deliberately large
case took 14.7 seconds cold, and a different payload, solver, host, or profile
may behave differently. Shadow validation remains required before control use.
