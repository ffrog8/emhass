# MPC accuracy verification and release handoff — issue 21

**Status: local implementation verification complete; release blocked by R1.** This is the local implementation and verification record, not a release approval. Both 280-request arms and their six offline reference pairs completed; the candidate meets the 80% conservative latency criterion, and natural `production-1165` rejection/recovery passed independent readback. The final-source full suite exited 1 with three reproduced baseline weather failures. Configured lint and scoped post-suite formatting checks passed, and challenge/fault scenarios passed their independent checks. Version/image creation and deployment are separate work.

## Implementation contract

The MPC model stores each battery's energy once per forecast step and reuses that state across its constraints. Positive `energy_change` depletes energy:

```text
energy[0] = initial_energy - energy_change[0]
energy[t] - energy[t-1] = -energy_change[t]
```

Each battery keeps its own state, efficiencies, limits, SOC-dependent power profile and final target. The normal MPC path still solves the full horizon once; it does not run an online reference or repair solve. The legacy single-battery cumulative expression remains compatible, with its original constraints checked against the values actually returned. No new bounds were added to the shared state.

For HiGHS MPC, the effective `mip_rel_gap` is `min(configured lp_solver_mip_rel_gap, 0.001)` on cold and cached primary solves. A configured zero remains zero; saved and per-request values can tighten but cannot loosen the 0.1% ceiling. `mip_feasibility_tolerance=1e-8` and `mip_abs_gap=1e-6` are set before each primary solve. HiGHS may stop on **either** the relative or absolute gap rule. The relative gap compares the configured whole-plan objective with the native bound; it is not a guarantee about one action or the electricity bill. Other optimisation modes retain their existing defaults. The generic non-HiGHS acceptance policy has a fault-injected test; commercial solver runtimes were not installed or exercised here.

Only a fresh, original-model `Optimal` MPC result that passes the native and returned-value checks can become a new plan. The returned-value audit keeps the `1e-7` original-constraint threshold. A stale native result, numerical rejection, or successful relaxed fallback returns no accepted MPC plan and clears solver-start provenance. The last valid CSV, saved entities and structured plan remain available for inspection, while `last_run` records the rejected request. Saved optimiser CSVs and planner entities receive per-artifact publication blocks; a later optimisation clears only the CSV and entity records it actually refreshes. Independently saved machine-learning forecasts remain publishable. Preparation failures retain their existing handling.

## Provenance and recorded checks

Implementation base: `a2daf69a4788973289435e39b4be472d03a32893`. The earlier local prototype checkpoint is `905d2d90effc3d497616bf69cb77ab1d9c8094c8` at `/home/coder/git/emhass-multi-batt/.tmp/mpc-accuracy-latency-prototype`; its 280-request result (264/280 strict usable under two seconds, against 228/280 original) is **prototype evidence**, not final implementation acceptance.

Final executed code/test snapshot: self-contained verification commit `965d5d5c8c82f30e8f6938f48326a010fce68d40`. The [262-file frozen source manifest](../.tmp/issue21/verification/full-suite-final-01/source-manifest.json) records SHA-256 for every executed file. After that suite, only one blank line was added to `tests/test_grid_export_threshold.py`; its parsed Python AST is identical to the executed snapshot. The current principal code and test files are:

| File | SHA-256 |
| --- | --- |
| `src/emhass/optimization.py` | `86a539a70f008129fb431307e5b8765c26898e5549513a4d54e44f322d2d822e` |
| `src/emhass/command_line.py` | `0e70dfaf9e252d3e2a6d0a0927be9a8596e7350ef0cf0533eced1f01d593840c` |
| `src/emhass/retrieve_hass.py` | `b8fbf323d74025145aead6e4b2410728a20cae362cd59e191e3ee7996146904a` |
| `tests/test_command_line_utils.py` | `756c0b161734714a4b18a60edfec6ee75329418a67cf5e6df9bc78a5f91ec957` |
| `tests/test_grid_export_threshold.py` | `436b51ea62ed0b33551308d7bd331aa986a9d86f03bff77b91a96693d6be71e8` (executed snapshot: `2ffd9aa257bc613e2f5c656e3f855ed7bb6ebaf53410b23b01ffd07edee2b147`) |
| `tests/test_mpc_publication_safeguards.py` | `0611a99ab1323d59f7620289a4704c6dea3705d312a6d6062238f952aa8c9fbf` |
| `tests/test_optimization.py` | `81ba11fa776152144fb8b6aa8f06173581f5bad3951fbabec49365760eb201b8` |

All native checks used image `emhass-mb-soc:1.2.1`, immutable ID `sha256:f8b9f433a248e234087543b8f6ec8ec1c76fae460937617b7d417849516df962`, Python 3.12.14, CVXPY 1.7.5 and HiGHS/highspy 1.15.1, with two CPUs, 4 GiB and no extra swap. Exact Docker commands, source and input manifests, logs and JUnit output are retained under `/home/coder/git/emhass-ticket-21/.tmp/issue21/verification/`; the [verification index](../.tmp/issue21/verification/INDEX.md) and [runner handoff](../.tmp/issue21/verification/RUNNER_HANDOFF.md) are the evidence map. These are local, task-owned files, not a published GitHub commit.

Focused Docker evidence on earlier frozen source snapshots passed seven public MPC cases, six publication cases, the public infeasibility case, eight stale-result/solver-exception cases and 51 multi-battery cases. The red/green receipts in the index show cold/cached native option readback, stale-status rejection and recovery, returned-value checks, retained-artifact publication and relaxed-fallback rejection. These runs do not replace the final-source suite.

The three-request paired [smoke](../.tmp/issue21/verification/replay-smoke-01/command-plan.json) and [independent readback](../.tmp/issue21/replay/smoke-independent-readback.json) used identical frozen inputs. Both arms accepted 3/3 with strict original-graph audit passing. Configuration-plus-complete-request durations were 9.778044, 0.562492 and 0.559077 s for baseline, against 1.104990, 0.206196 and 0.206616 s for candidate. Native readback was `(relative gap, absolute gap, MIP feasibility) = (0.05, 1e-6, 1e-6)` for baseline and `(0.001, 1e-6, 1e-8)` for candidate. This establishes the adapter path only; three requests cannot establish the 80% population criterion.

The final paired plan freezes the same corpus inputs for sequential baseline and candidate arms, with each arm's own source manifest. Its [completed baseline analysis](../.tmp/issue21/verification/replay-full-02/baseline-analysis.json) and [timed results](../.tmp/issue21/verification/replay-full-02/out/baseline/timed-results.json) show exit 0, 280/280 attempts completed, 280 production pipeline acceptances, and 279 strict original-graph passes. One baseline result, `production-0181`, failed the independent strict graph audit with a maximum residual of `2.825e-7`; it is excluded from conservative usability even though production accepted it. Using `elapsed_config_and_request_s`, which includes configuration, input preparation, production persistence and the timed native/control gate, **233/280 (83.2143%)** were usable under two seconds. The 20 compiled-cold requests yielded 0 fast plans; the 260 compiled-reuse requests yielded 233 fast plans, with 259 strict usable. Across all attempts, p95 was 6.539661 s, p99 21.317405 s and maximum 27.627943 s (NumPy linear-interpolation percentiles). This baseline arm alone did not establish a candidate improvement; the completed paired result is reported below.

The final-source [candidate timed results](../.tmp/issue21/verification/replay-full-02/out/candidate/timed-results.json) cover the same 280 attempts and report **265/280 (94.6429%)** accepted fresh, strictly audited plans under two seconds. Production accepted 279; the independent original-graph audit passed all 279; `production-1165` was the one correctly rejected numerical result, counted in the denominator. There were zero skipped requests. Of 20 compiled-cold requests, all were acceptable and 19 were fast. Of 260 compiled-reuse requests, 259 were acceptable and 246 were fast. The separate native-start diagnostic counted 21 cold starts and 259 timestamp-aligned starts because recovery after `production-1165` cleared its native start. Configuration-plus-complete-request p95 was 1.977467 s, p99 3.491559 s and maximum 6.718021 s across all attempts. The candidate exceeds the **80% latency criterion**, with 32 more fast usable plans than baseline on the same selected corpus; this does not by itself close suite or external release criteria. The [paired analysis](../.tmp/issue21/verification/replay-full-02/paired-analysis.json) confirms identical ordered inputs, exact arm source hashes and options, event-derived acceptance flags and completed references. Candidate process exit 1 is reconciled to its one correct `production-1165` rejection; it is not a missing request or an unexamined crash.

The ten longest configuration-plus-complete-request durations in each timed arm, in seconds, are retained in their result files:

| Rank | Baseline request / seconds | Candidate request / seconds |
| ---: | --- | --- |
| 1 | `production-1887` / 27.627943 | `production-0629` / 6.718021 |
| 2 | `production-0593` / 26.103995 | `production-0631` / 4.745895 |
| 3 | `production-0606` / 24.053725 | `production-0596` / 3.555895 |
| 4 | `production-1888` / 20.590029 | `production-0630` / 3.474457 |
| 5 | `production-1907` / 11.622824 | `production-0599` / 3.359342 |
| 6 | `production-0182` / 10.356445 | `production-0600` / 3.261223 |
| 7 | `production-0179` / 9.404673 | `production-0607` / 3.190072 |
| 8 | `production-1924` / 9.342215 | `production-0627` / 2.870794 |
| 9 | `production-0164` / 9.305910 | `production-0625` / 2.732775 |
| 10 | `production-1904` / 7.777607 | `production-0616` / 2.556594 |

The [paired analysis](../.tmp/issue21/verification/replay-full-02/paired-analysis.json) reports six successful offline unrestricted/fixed-action reference pairs per arm, each with a bounded first-action regret interval in configured objective units and no oracle inconsistency. Their exact recorded intervals and comparisons are:

| Selected request | Baseline interval | Candidate interval | Comparison |
| --- | --- | --- | --- |
| `production-0213` | `[0, 2.000000015820678e-7]` | `[0, 2e-7]` | overlap |
| `production-0632` | `[0.001333329613944687, 0.001335469047360296]` | `[0, 4.945364488723725e-6]` | candidate disjoint better |
| `production-0884` | `[0, 2.2111828036458127e-6]` | `[0, 1.5452285128219622e-6]` | overlap |
| `production-1207` | `[0, 7.414193779973431e-7]` | `[0, 5.390403259251329e-7]` | overlap |
| `production-1558` | `[0, 1.999999998889777e-7]` | `[0, 2.000000005551115e-7]` | overlap |
| `production-1934` | `[0, 2.0000000005551114e-7]` | `[0, 1.9999999977795539e-7]` | overlap |

The `production-0632` intervals show one disjoint candidate improvement; the other five overlap, with zero disjoint worsenings. The largest candidate upper bound is `4.945364488723725e-6` in configured objective units. No economic acceptance tolerance was selected. These numerical comparisons do not establish zero regret, a per-action solver-gap guarantee or realised electricity-bill savings.

The ordinary candidate replay naturally reproduced the historical `production-1165` numerical fault without an injected solve or extra online work. The [independent 20-check readback on all 280 timed rows](../.tmp/issue21/supplemental-review/natural-1165-final-timed-readback.json) matched its 6,099-row/2,306-column canonical model (`441f86061e35766f20cdaa2b913526ec121fe460332649eb87dbe4d8a6030878`), MPS and raw native vectors byte-for-byte to the retained historical witness. It checked all 49 archived recovered-leaf arrays and the 14 historical Boolean-recovery deltas. Raw original-graph residual was `4.348797481778322e-11`, but the actual returned values reached `3.5151098909977444e-7` against the unchanged `1e-7` threshold. With native MPC options `(relative gap 0.001, absolute gap 1e-6, MIP feasibility 1e-8)`, `production-1164` returned an accepted plan, `production-1165` returned only `Failure` with `last_run.status=error` and no CSV/control export, and `production-1166` obtained a fresh accepted `Optimal` solve after native cache/start provenance cleared. The previous CSV and structured plan remained byte-identical across the rejection. The natural three-request subset had two accepted, one correct numerical rejection, zero skipped; its available conservative durations were 1.038137, 1.006102 and 0.745108 s. The prepared historical injection shim was not executed. This readback does not establish a physical release of forced commands.

The separate final-source [20-request challenge replay](../.tmp/issue21/supplemental-review/out/challenge/results.json) exited 0 with 20 accepted, 20 strict graph passes, zero failures/skips and all six declared offline reference intervals bounded. Its [nine-check acceptance readback](../.tmp/issue21/supplemental-review/out/challenge/acceptance-readback.json) confirmed the disputed first aggregate action within `1e-6 W`: PV `3994 W`, load `2803 W`, battery `-1191 W`, grid `0 W`, curtailment `0 W`. Grid charging at negative prices occurred at all five declared later slots, 1–5. This cohort had **16/20** accepted fresh plans under two seconds; configuration-plus-request p95 was 5.292568 s, p99 6.088127 s and maximum 6.287017 s. Its slower cases are reported separately and are not folded into the representative 280 denominator. The ten longest available conservative durations, in descending order, were `retry-0-0` 6.287017 s, `retry-0-1` 5.240229 s, `retry-1-0` 2.746336 s, `incident-1` 2.019411 s, `retry-2-0` 1.687712 s, `retry-2-2` 1.680147 s, `retry-1-1` 1.597755 s, `retry-0-2` 1.551106 s, `retry-2-1` 1.501808 s and `retry-1-2` 1.485339 s.

Two separate fault triplets exercised plan retention and fresh recovery. The [warm-primary fault](../.tmp/issue21/supplemental-review/out/fault-warm/reconciled-acceptance.json) and [all-solves fault](../.tmp/issue21/supplemental-review/out/fault-all-solves/reconciled-acceptance.json) each completed three attempts: two accepted, one correct middle rejection, zero skips, with 14/14 scenario checks passed. Their process exits were 1 and 2 respectively, reconciled to the deliberate rejected solve paths. The rejected result had only `optim_status=Failure`, no control or diagnostic plan export, durable `last_run=error`, and byte-identical prior CSV/plan; the next request recovered a fresh `Optimal` result after cache/start provenance cleared. The warm-primary case also confirmed that a successful distinct relaxed fallback did not become a fresh MPC plan. Available configuration-plus-request durations were 0.905586, 0.748174 and 0.674795 s for the warm-primary triplet, and 1.126890, 0.789772 and 0.065572 s for all-solves. The [independent supplemental readback](../.tmp/issue21/supplemental-review/supplemental-independent-readback.json) passed **45/45 checks** (17 challenge, 14 per fault), verifying source/receipt hashes, raw first-action CSV cells, reference-interval arithmetic and artifact/recovery sequence. These cohorts remain outside the representative 280 denominator and do not prove physical command release.

The first canonical `pytest tests/ --durations=10 --durations-min=0 --junitxml=/out/result.xml` run exited 1: **1,456 total; 1,335 passed, 89 failed, 0 skipped, 32 xfailed**, in 375.85 s. Its [receipt](../.tmp/issue21/verification/full-suite-preflight-01/out/full/command.json) and [output](../.tmp/issue21/verification/full-suite-preflight-01/out/full/console.stdout) retain the actual failures. Of the 89, 62 followed the test container's 1 GiB `/tmp` exhaustion, 15 lacked writable `/work/.tmp`, two hit Git `safe.directory`, three were weather/cache failures under network-none, and seven were then-current behavior assertions. Corrected Git and scratch environment probes passed before the final-source run.

The ten longest available test durations in that full run were:

| Seconds | Test |
| ---: | --- |
| 68.80 | `test_perform_naive_mpc_optim_complex_case_with_inactive_loads` |
| 46.70 | `test_perform_naive_mpc_optim_complex_case` |
| 10.18 | `test_multi_block_battery_mode_lock_site_avoids_forced_cross_block_mixing` |
| 10.12 | `test_multi_block_battery_mode_lock_site_three_blocks_24_steps_performance_smoke` |
| 8.36 | `test_runner_rejects_dependency_lock_metadata_lookup_failure` |
| 5.99 | `test_main_regressor_model_fit` |
| 4.10 | `test_battery_first_priority_dayahead_feasible_with_soc_target` |
| 3.26 | `test_rest_changed_then_reused_and_fresh_efficiencies_are_request_scoped[charge-efficiency_site0]` |
| 3.25 | `test_battery_first_priority_stays_bounded_with_negative_price` |
| 3.12 | `test_get_forecasts_with_lists_special_case` |

The final-source [canonical suite analysis](../.tmp/issue21/verification/full-suite-final-01/analysis.json), [receipt](../.tmp/issue21/verification/full-suite-final-01/out/full/command.json) and [JUnit](../.tmp/issue21/verification/full-suite-final-01/out/full/result.xml) record **1,457 total; 1,422 passed, 3 failed, 0 ordinary skips, 32 xfailed**, with command exit 1 in 280.67 s. The only failures were `test_thermal_config_runtime_overrides`, `test_get_forecasts_with_lists_special_case` and `test_get_weather_forecast_openmeteo_method_mock`: all call the unchanged Open-Meteo/cache path under network-none. The [same three nodes failed on unmodified base source](../.tmp/issue21/verification/weather-baseline-01/env-probes/weather3/command.json); this diagnoses baseline/environment behavior, but the canonical command did **not** pass. All changed regression nodes selected in the analysis passed, including the two relocated complex physics cases (46.10 and 3.63 s calls). The final source and Git snapshot remained unchanged during the run.

The final suite's ten longest available phase durations were:

| Seconds | Phase | Test |
| ---: | --- | --- |
| 46.10 | call | `test_perform_optimization_complex_configured_gap_and_relaxed_physics` |
| 7.96 | call | `test_multi_block_battery_mode_lock_site_avoids_forced_cross_block_mixing` |
| 7.67 | call | `test_runner_rejects_dependency_lock_metadata_lookup_failure` |
| 7.66 | call | `test_multi_block_battery_mode_lock_site_three_blocks_24_steps_performance_smoke` |
| 5.28 | call | `test_main_regressor_model_fit` |
| 4.12 | call | `test_battery_first_priority_dayahead_feasible_with_soc_target` |
| 3.63 | call | `test_perform_optimization_complex_inactive_loads_configured_gap` |
| 3.22 | call | `test_rest_changed_then_reused_and_fresh_efficiencies_are_request_scoped[discharge-efficiency_site0]` |
| 3.17 | call | `test_get_forecasts_with_lists_special_case` |
| 3.10 | call | `test_get_weather_forecast_openmeteo_method_mock` |

The two long, no-battery complex public MPC cases reached time limits and rejected relaxed results on that source, with 46.70 s and 68.80 s test calls. Matched [diagnostics](../.tmp/issue21/verification/complex-paired-05/analysis.json) now establish an availability change on the **same inputs**, without attributing it to the shared-energy formulation: the 288-step input bundle SHA-256 was `19702a9cf5251b916d386d29d840587014b3ee946fad5158d59dc291def004a0` in both arms. Baseline primary timed out at its configured 0.01 gap and the old public test accepted the relaxed fallback; candidate primary timed out at the 0.001 ceiling and rejected the relaxed fallback. For the 96-step first call, the matched bundle was `95b6bc3cac8a321ed8bd173626095c20aa21ee6c2861d452def1370e744d984e`: baseline primary solved at configured 0.2 gap (native gaps 0.01110 and 0.03519 across its two calls), while candidate's 0.001 primary timed out and rejected its relaxed fallback. The candidate's second 96-step call was not exercised because the first assertion stopped that test. These are real difficult-cohort failures; they remain separate from the representative 280-request target.

To retain the existing 288/96-step deferrable-load and thermal **physics** checks with their configured gap and relaxed fallback, only those two test methods now call the generic `perform_optimization` interface with the exact same horizon, frame, forecasts, prices and deferrable arguments. All their physics assertions remain. Their renamed nodes are `test_perform_optimization_complex_configured_gap_and_relaxed_physics` and `test_perform_optimization_complex_inactive_loads_configured_gap`; both passed in the final-source suite. Separate public MPC tests continue to require strict rejection and fresh recovery. Moving these test seams does not make the timed-out public MPC attempts accepted plans or close the availability finding.

The configured repository-wide [Ruff lint check](../.tmp/issue21/verification/full-suite-final-01/static/ruff-check/command.json) passed with exit 0. The repository-wide formatter exited 1 on six files; [clean-base comparison](../.tmp/issue21/verification/full-suite-final-01/static/formatter-baseline-comparison.json) traced five files to inherited formatting differences (`optimization.py`, `utils.py`, `test_command_line_utils.py`, `test_dst_forecast.py`, `test_forecast_validity_contract.py`). Its only new hunk was the missing blank line in `test_grid_export_threshold.py`. That one line was added, and [scoped lint](../.tmp/issue21/verification/final-whitespace-02/check/command.json) and [scoped format](../.tmp/issue21/verification/final-whitespace-02/format/command.json) both passed with exit 0 on the current file; stdlib AST comparison with the tested file passed. The inherited five formatter differences remain; no configured type checker exists. The [preliminary Spec review](../.tmp/issue21/review/spec.md) found a legacy N=1 original-constraint gap; the reviewed correction and public red/green test resolved that finding.

## Acceptance checklist

| Required outcome | Status | Evidence needed to close it |
| --- | --- | --- |
| Shared per-battery energy formulation, current native options and original returned-value safeguards | passed | Final-source suite passed the changed optimizer regressions, including N=1 and cold/cached paths; 280-request candidate replay confirms actual HiGHS options, strict original-graph acceptance and the natural returned-value rejection/recovery. |
| Existing physical limits, profiles, forecast alignment, prices, output names/units and disputed first action | passed | Final-source regressions and 20-request challenge passed, including the corrected incident aggregate action, five negative-price charging slots, changing-input/retry cases and strict output checks. The slower challenge cohort remains separately disclosed. |
| At least 80% of **all 280 attempted requests** return an accepted fresh plan under two seconds | passed | Both arms completed 280/280: candidate 265 conservative fast usable (94.6429%), against baseline 233 (83.2143%), using the same corpus and configuration-plus-request timer. Paired analysis reconciles candidate exit 1 to its one correct numerical rejection. |
| Offline first-action economic references | passed | Six predeclared pairs per arm completed at positions 50, 90, 130, 180, 230 and 280 with bounded intervals and no oracle inconsistency: one disjoint candidate improvement, five overlaps, zero disjoint worsenings. No economic acceptance tolerance or bill-savings claim follows. |
| `production-1165` returned-graph rejection and fresh recovery at `1e-7` | passed | Natural candidate sequence and independent 20-check readback matched the historical model and raw vectors, rejected the returned residual `3.5151098909977444e-7`, preserved last valid artifacts and accepted `production-1166` on a fresh native solve. Physical command release remains R1. |
| Rejected-plan, saved-artifact and fallback behavior | passed | Public MPC/publication regressions passed in the final suite; both supplemental three-request fault sequences passed 14/14 checks each, with correct middle rejection, retained artifacts and fresh recovery. Independent supplemental readback passed 45/45 overall. |
| Canonical full suite, configured checks and final independent reviews | passed | The required final-source suite ran 1,457 cases and was diagnosed: 1,422 passed, 3 baseline-weather failures, 0 ordinary skips, 32 xfailed, **command exit 1**. Those same three failures reproduced on unmodified base source; no changed regression failed. Repository-wide Ruff lint exited 0; formatter exited 1 on five inherited differences after the one new hunk was fixed and scoped check passed. Independent Standards found zero defects, Spec replay readback passed 608/608, and supplemental readback passed 45/45. This is a completed verification workflow, **not** a claim that every test or format check passed. |
| No-acceptable-plan handoff documented | passed | See [R1](#r1-control-owner-release-blocker); its external implementation and physical proof remain a release blocker. |

## Standards

The independent [final Standards review](../.tmp/issue21/review/final-standards.md) found **zero documented-standard violations** and **zero actionable code smells** in the frozen `965d5d5c` code/test snapshot. It checked the shared-energy and acceptance paths, publication metadata, changed fallback tests and docs against the repository's documented rules. With no Standards findings, there is no within-axis severity ranking. This was read-only review; the reviewer did not run tests, lint, Docker or native solves.

## Spec

The independent [final Spec code review](../.tmp/issue21/review/final-spec.md) found **zero new code or scope defects** in the same frozen snapshot. It confirmed separate battery states, original-constraint checks, rejected-result provenance and retained-artifact blocks. There is no code-defect severity ranking within this axis. At review time it identified **three incomplete evidence groups**, not implementation findings: (1) representative paired performance, including the real matched difficult-cohort availability loss; (2) offline economics and historical returned-value reproduction; (3) final-source suite, checks and evidence readback. The follow-up [independent runtime readback](../.tmp/issue21/review/candidate-runtime-spec.json) passed **608 checks with zero discrepancies** against paired replay hashes, all ordered inputs, numeric acceptance events, six reference comparisons and natural `production-1165` artifacts. The separate [supplemental readback](../.tmp/issue21/supplemental-review/supplemental-independent-readback.json) passed **45/45** across challenge and fault scenarios. Neither reviewer reran native solves. The representative replay, economics, historical returned-value, final-source suite and supplemental evidence are now supplied; the suite's three baseline weather failures and five inherited formatter differences remain recorded as failed command outcomes. The matched difficult-cohort availability loss remains documented separately and is not treated as repaired by the representative result.

## R1: control-owner release blocker

Before any deployment that uses forced battery commands, the existing external control owner must demonstrate how it detects a rejected or missing plan, stops renewing stale commands, and decides the safe release action. Verify the equipment's **actual physical state** after that action. Compare `/api/v1/last-run` action/status with `/api/v1/plan` `generated_at`; a retained older CSV or plan does not prove a fresh accepted request and does not release a force. This is an external release blocker, not a new Home Assistant/device-control policy in EMHASS. No control-owner change or physical readback has been exercised here.

The release handoff must retain the tested image ID, Python/CVXPY/HiGHS versions, effective MPC options, exact source/input hashes and completed replay/suite receipts. Rollback requires the previous known-good image and configuration plus the control owner's verified command handoff; do not treat restoring an old CSV as device rollback. Version/image creation, deployment, running-image/settings readback and an initial production watch require separate authorization and later evidence. A quiet observation window cannot substitute for the failed-request and physical-release checks.

Known storage limits: a disk failure can prevent a rejected verdict or artifact block from reaching another worker; metadata read-modify-write locking covers one process and simultaneous writes in separate workers can race. Those cases are not claimed as verified cross-worker protection. Preparation errors and uninstalled commercial solvers are outside the exercised new acceptance path.
