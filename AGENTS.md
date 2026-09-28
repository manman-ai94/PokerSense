# AGENTS.md

Project operating notes for contributors and coding agents. Read this before
changing desktop capture, recognition, packaging, or project documentation.

## Working agreement

1. Inspect the working tree and this file before changing code. Preserve any
   unrelated local changes.
2. Verify every code change in proportion to its risk. A user-facing desktop
   change requires focused tests; a release also requires a local package
   check before GitHub packaging.
3. At the end of every material task, update this file's **Current state** or
   **Progress log**. Record the outcome, affected version/commit when relevant,
   verification performed, and any remaining limitation. Do not add routine
   narration or duplicate git history.
4. Keep documentation aligned with the product:
   - Update `README.md` and `README.zh-CN.md` when installation, supported
     behavior, privacy, or user-visible limitations change.
   - Update the relevant file in `docs/` when a contract, architecture, or
     subsystem behavior changes.
   - Update release/version files together: `pyproject.toml`,
     `src/poker_engine/__init__.py`, `packaging/pokersense.spec`, and
     `packaging/pokersense.iss`.
5. Remove a Markdown document only after confirming it is obsolete or fully
   duplicated, checking references with `rg`, and moving any still-useful
   information into its replacement. An unlinked design document is not, by
   itself, evidence that it is disposable.
6. Use `docs/PR-WORKFLOW.zh-CN.md` for authorized development. The canonical
   remote is the public `xiaoyangpeng1994-create/PokerSense`; treat
   `windgeek/PokerSense` and `x-poker` as read-only references. Use scoped
   `codex/` branches, Draft PRs and independent review. Merging, tags, releases,
   real capture and live play still require explicit user authorization.

## Current state
- **2026-09-28 PREFLOP SUPPORT AUDIT COMPLETE: engineering PASS, support incomplete.**
  Source4ca7bc0,manifest6f72bbdd; V2/MCCFR/nine assets unchanged. One supervised
  batch107.621s completed63shards/10647slots/31941asset rows:2833HIT,3042NA,
  23204UNVISITED,1990zero-regret-only,872nonzero-regret-only;0errors/notrun.
  28899constructible rows9.80%HIT; after within-asset key dedup2229/27378=8.14%.
  Fixed limp-then-minraise response prefix9126constructible rows allUNVISITED;
  not a claim about every second decision. Original95o/8visit witness confirmed.
  Regret membership is not learning/average export; old traverser roles UNKNOWN.
  Independent raw result audit PASS;27input artifact hashes unchanged, old
  primary retained. Fixed default physical geometry/169classes/3prefixes only,
  not full-hand acceptance, natural frequency, profitability or live readiness.
  FakeHIT/observation/NA/metadata/failed-nonuniform attacks rejected;30newtests,
  84encoder/policy/MCCFR regressions and full lint pass. No fitting, capture,
  paid API, package or live change. Next only: sampling coverage and correct
  average weighting on enumerable small games before changing collection.
  Results/commands:docs/AA-PREFLOP-SUPPORT-AUDIT-20260928.zh-CN.md.
- **2026-09-28 LOCAL FULL-HAND CLOSEOUT: NO_GO, budget complete / samples PARTIAL.**
  Experiment source2dfe5a5, DraftPR41 over PR40; manifest27f20f7c. Both fixed
  Mapika models fail public-only decision checks (0.8b6/9,2b3/9); 2b folds all
  three private royal-flush cases. Two capped batches2382.376/2387.223s finished:
  480/540shards,3297complete+3blocked+480NOT_RUN=3780plannedpairs; timely1901.
  Exactly one attempt per shard, no third batch. Three failures are batch-edge
  remainder timeouts/terminated worker, not full10s neural timeouts. Smallmodel
  completes1890/1890 but has1turn/0river decisions and substantial deterioration
  against min_raise at7/8players. Large8p240-pair check_call group completes238;
  its remaining480pairs unexecuted. Incomplete groups retain nullEV/CI.
  Independent raw audit/recomputed18group intervals PASS;32recorded branches
  replayed with60observation matches,6597terminal fee/conservation checks PASS.
  Local first-decision p95 416.051/647.165ms,not capture-to-display.73focused
  tests/full lint pass; experiment sourceCI36333561924 PASS. No realrules,
  capture/training/paidcalls/live promotion/package/merge. Earlier0.8b timing
  priority is superseded by this quality NO_GO. Next recommendation only:
  poker-specific abstraction/average-policy coverage research, not started.
  Results/commands:docs/AA-LOCAL-FULLHAND-20260928.zh-CN.md.
- **2026-09-27 LOCAL CANDIDATE SCREEN:** isolated branch codex/aa-local-policy-screen
  from15d5895; source9663038, screen-v3 manifest770b2551. Pinned Mapika0.8b/2b-v10
  safetensors/licenses and separate Windows CUDA runtime; no desktop dependency
  changes. Added synthetic-only exact-state/public-input external option adapter
  and frozen48-query, preloaded-process screen with complete failures, no truncation,
  actual loaded identity, high-resolution deadlines and no live registration.
  Independent review repaired incomplete source/runtime binding and blocking IPC;
  actual v1 wrongly rejected upstream empty temperature map (48NOT_RUN), preserved.
  v2 returned48legal with coarse-clock timing; v3 sameinputs/scores/actions afterQPC
  repair:0.8b24/24<=300ms,p95=210.051ms;2b22/24,p95=300.999ms. Longriverprobe
  209.425/298.132ms. Prior slower v2 and two timeouts preserved; uncontrolled load
  means no speedup claim.125focusedtests/full lint pass. Queries are not full-hand
  model play, not quality/profit/end-to-end acceptance. Real rules still unsaved;
  choose0.8b only as next offline evaluation priority, not promotion. No third
  candidate/training/paid API/cloud/capture/reservedmedia/package/merge/release.
  Details:docs/AA-LOCAL-CANDIDATE-SCREEN-20260927.zh-CN.md.
- **2026-09-27 AA MANUAL TABLE SETTINGS:** observation header now exposes saved
  settings and edit entry; empty tables open the existing form automatically.
  Basic/advanced fields, explicit percent/BB units, optional usual stack range,
  save/cancel/reset and bounded request recovery added. New range is metadata
  only: no actual stacks, rule fingerprint, readiness or live promotion changes.
  Legacy files load without rewrite; omitted legacyPOST metadata is preserved
  under revision lock, explicitnull clears. Save/reset retain stop+invalidate.
  Focused57pytest pass (including actual HTTP/hand-receipt lifecycle),10new UI
  scenarios+39analysis+8TTL checks pass, scoped lint/diff clean. Independent
  review reproduced oldrule identity, concurrentrevision refusal and no-rewrite
  migration. Browser synthetic form/save/error/cancel/summary exercised; no
  capture/private media/paid calls or new package. Follow setup contract in
  docs/AA-TABLE-VALIDATION-V2.zh-CN.md. Old dirty primary/frozen studies retained.
- **2026-09-27 POLICY READINESS V2 CLOSEOUT:** source40a42f5, manifest0b5750b5.
  All99jobs complete:18train/18zero-update controls/54eval/9query. Training
  1024.844s, evaluation258.156s under2400s supervised batch budgets. Independent
  checkpoint/export recomputation confirms nineV2 85-97sweeps and41-56repeat
  nonuniform infosets; all18controls two sweeps,zero regret,uniform. Numerical
  recovery fixed and actual3.11/3.12 counterexamples pass; CI36310254293 green.
  Gate3 NO_GO: V2 345/5670 complete(4.44-8.89% percase), V1 350/5670. All11340
  pairs retained,10645UNKNOWN failures,EV null;3150queries complete,105preflop
  hits,0/630 each postflopstreet,315expected out-of-scope refusals. Declared
  malicious-input27/27 rejected,not universal leakage proof. Independent1620
  shard audit agrees. V2misses4630unvisited+695regret-only/noaverage; no observed
  exact/abstract collision in measured prefixes,not proof of global equivalence.
  Actualnineassets passed shadow process load/repeat/legal/deadline probes using
  already-seen preflop inputs; no physical latency/live/strength acceptance.
  Stop this experiment; only next recommendation is finite preflop support-set
  average-policy coverage study,not started. All old assets and dirty primary
  preserved. Full result/commands:docs/AA-POLICY-READINESS-RESULTS-20260927.zh-CN.md.
- **2026-09-27 POLICY READINESS V2, PRE-FIT FREEZE:** added explicit V2 suit/path
  encoding, versioned research assets, shared shadow loader, committed-visit
  learning diagnostics and bounded 18-case V1/V2 study with no-update controls.
  Full denominators freeze11340pairs and3150 separate query opportunities.
  Stage1 passed before fitting. First1024.86s training batch showed variation,
  but Python3.11 CI exposed sorted-JSON continuation rounding drift; all149
  files preserved and no new evaluation/query seed consumed in that batch.
  Canonical action-order normalization repair independently reproduced on
  Python3.11/3.12; exact checkpoint/JSON equality retained, no tolerance change.
  Fresh source-bound matrix required; same algorithm, seeds, budgets and gates.
  See docs/AA-POLICY-READINESS-V2.zh-CN.md and numerical reproducibility note.
  No strength/live qualification, capture, paid calls, packaging or release.
- **2026-09-27 FROZEN-POLICY EVALUATION CORRECTION (STAGE 1):** original
  PR37 b796cce's 48/378 failures were independent_policy_salt_required during
  binding, not measured coverage misses. Unified canonical 64-hex-string salts
  and added actual artifact-loader/evaluator integration on 6/7/8 players.
  Declared controls 42/42 complete with identical traces, settlements and
  returns to direct check/call. Actual rerun of nine old assets now binds,
  then records378 UNKNOWN_INFORMATION_SET at each first Hero decision; all
  denominator rows retained, affected EV null. Original57JSON hashes unchanged.
  All592 exported entries uniform after one sweep; no learned-strength claim.
  Added explicit failure phase/actor and observed-prefix street diagnostics;
  unseen suffix counts remain unknown. Independent review reproduced controls,
  old/new failures and negative paths. No expanded training before this gate,
  no live/capture/paid calls or packaging changes. See
  docs/AA-EVALUATION-CORRECTION-V1.zh-CN.md; older performance attribution below
  is historical and superseded by this correction, not rewritten raw evidence.
- **2026-09-27 TEN-SECOND AA ENGINEERING PREVIEW:** isolated from exact
  `af67b4bb3ba56da2d4fdb70e0731583afc7aaf40` on
  `codex/aa-ten-second-foundation`, version `0.2.0.dev1`. Added monotonic
  turn deadlines, source-age rejection, independent UI TTL and killable
  preloaded shadow policy execution; actual AA HTTP remains observation-only
  because verified physical turn timing and qualified live policy are absent.
  Windows entry/package now AA; frozen EXE offline self-check, 13 endpoints,
  actual spawn analysis and capture refusal passed, browser layout inspected.
  Added PokerKit 0.7.5 full-hand 6/7/8 simulation, paired seat/deal evaluation,
  SIMPLE external-sampling MCCFR, scope-bound transactional checkpoints,
  research-only frozen policy and explicit synthetic recorded-Jev adapter.
  Independent review repaired checkpoint scope, nested private-label forwarding
  and partial-commit faults; original probes independently reverified.
  Full local 4701 passed/2 skipped (471.96s), full lint/diff passed; existing
  30-case baseline digest unchanged. Nine bounded 3s training probes retained:
  two completed ten sweeps, seven budget-exhausted. Eight-player coverage probe
  48/48 BLOCKED, zero paired EV: no strategy promotion. Physical p95/p99,
  real hands, strong strategy and installer installation NOT accepted; local
  Inno compiler absent. No capture, paid inference/cloud, merge/tag/release.
  Old dirty primary and rejected experiments preserved. Start with
  docs/AA-TEN-SECOND-IMPLEMENTATION.zh-CN.md; do not call this live readiness.
  Follow-up adds one-command frozen nine-case study orchestration, with 15
  focused tests and independent seed-domain counterexample review. Actual
  one-sweep smoke retains all 9 cases and 378/378 blocked paired opportunities;
  no EV/strategy promotion. Draft PR #37; initial head 5ce06ca CI36301773529
  passed Windows/macOS/hygiene, build36301786735 produced AA Windows installer
  and legacy macOS artifacts with release skipped. Later study-only changes
  require their own latest-head checks; these runs are not relabeled.
  Actual isolated install/EXE/uninstall on the first CI artifact passed
  functionally and restored test registration, but /NOICONS was ignored.
  Added AllowNoIcons=yes plus regression assertion; preserve the failed
  installer audit and require rebuilt-artifact verification (tracked on PR37).
- **2026-09-23 INDEPENDENT PR #34 EVALUATION GATE:** independently audited
  original head `4f59d723f20fab760b50c0f2de1ec88a5b9b1b8f` against exact main
  `d98084aba96eac6ff3bc0cf07dad99b00e36ff31`. Recompiled all six V1 books from
  that base: byte-identical artifact `3b9983b46c054a40499286467164c68e2e1ea7039df0a5c2470859ebd702eab4`;
  deterministic 30-world result remains `c1a725f3f95a76261fb041af200e45bae02b6836202b36ec56578f0afd680aae`
  on Python 3.11/3.12. Two P1s prevented approval of the original head:
  per-world candidate reoptimization was accepted (9 positive/0 negative),
  and a self-rehashed different policy could be relabeled BASELINE_V1.
  Scoped repairs pin canonical V1 bytes, require one candidate book per public
  group across all worlds, replay changed-book reports from supplied books
  using the frozen kernel, and reject metric/identity/partial-result drift.
  Original baseline/results/oracle artifacts and all production source stay
  unchanged. Original-head full suite 4587 passed/2 skipped with pinned
  PokerKit; repaired evaluation/reference 46 passed, math/reference 128 passed,
  full lint and hygiene passed. Independent repair probes: 25 negatives
  rejected plus fixed-book/budget positive controls; separate 12-probe review
  passed. Independent terminal reference: committed artifact byte-identical,
  400 additional synthetic cases MATCH, 16 injected errors detected.
  STRATEGY_EVALUATION_READY and BASELINE_V1_FROZEN apply only to exposed
  synthetic conditional worlds, not independent action-tree or empirical
  strategy acceptance. Exact integrated head and post-main CI are recorded in
  Issue #27. Jev remains non-authoritative; no strategy optimization started.
  Next mission remains OPPONENT_RIVER_RANGE_POSTERIOR_CALIBRATION;
  REAL_HAND_ACCEPTANCE_PENDING=YES and empirical NOT_ASSESSED remain.
- **2026-09-23 STRATEGY EVALUATION FOUNDATION V1 (DRAFT):** on a clean
  `d98084aba96eac6ff3bc0cf07dad99b00e36ff31` base in isolated
  `codex/strategy-evaluation-foundation`, frozen six AA manual threeway-river
  public-history policy books before changing strategy behavior. Source/input/
  protocol hashes and 30 synthetic conditional-world results are committed as
  BASELINE V1; 30/30 complete, 12 cases below at least one simple policy, six
  capacity/scope probes BLOCKED. PokerKit 0.7.5 plus independent settlement
  math passed 11 focused oracle tests, including mismatch and refusal probes;
  this does not validate ranges or
  action-tree EV independently. A paired-report comparator retains candidate
  failures in its denominator. Jev: conditional shadow-test candidate only,
  no paid call; next target is opponent river-range posterior calibration, not
  started. See docs/STRATEGY-EVALUATION-FOUNDATION-V1.zh-CN.md. Independent
  review caught and verified fixes for result-tamper acceptance and artifact
  overwrite. Local full pytest exited 0 (existing httpx deprecation warning),
  20 focused evaluation/oracle tests passed with PokerKit 0.7.5, full flake8,
  diff and staged filename hygiene passed. No strategy/perception behavior,
  real media, capture, real-hand
  acceptance or profitability claim changed; REAL_HAND_ACCEPTANCE_PENDING=YES
  and empirical strategy NOT_ASSESSED remain.
- **2026-09-22 SEQUENTIAL PR #32 -> #33 INTEGRATION:** PR32 merged as
  a578d330879e542a56bd8c2c85ccdbfdd27f77bf after independent review and scoped
  repairs. Its main CI 35633329108 and desktop build 35633329102 succeeded;
  release skipped without a tag. PR33 was then retargeted to that exact main
  and synchronized with a merge commit; product/test files are unchanged from
  the reviewed 0bb9cdb tree (local full 4508 passed/22 skipped). Original PR33
  0d76342 was blocked by a demonstrated cache P0; the repaired causal module
  remains 0724dcfe29bfec884959308655803cfb5ee82bca317ab38583f4348cfe18494a.
  Final-head rechecks, merge identities and both post-main CI results are
  recorded in Issue #27. Branches/history are retained. No historical media,
  training, real gold/freeze, product strategy or real-hand acceptance work;
  REAL_HAND_ACCEPTANCE_PENDING=YES and NOT_ASSESSED=YES remain.
- **2026-09-22 PR #33 CACHED CAUSAL SEMANTICS REPAIR:** independent review of
  0d76342 proved cached first-actor and board-CONFLICT conclusions could bypass
  production consumers even though scorer replay rejected them. Repaired the
  shared production check to reconstruct the entire projection from a separate,
  digest-bound raw evidence sidecar: at most four board progression/first-conflict
  witnesses and 256 contiguous transition rows, with source/epoch/order/current-end
  validation. Old caches without evidence abstain. Long stable TURN histories can
  start a fresh transition window without erasing earlier board contradictions.
  Merged board/transition witness chronology also enforces the same source-frame
  offset and bounded source-time continuity. Final focused 126 passed; manual/UI
  compatibility 39 passed. Independent original 45/45 and expanded 65/65 probes
  passed on source 0724dcfe29bfec884959308655803cfb5ee82bca317ab38583f4348cfe18494a.
  Full lint/diff passed. Original 0d76342 must not serve as the merge head.
  Final-base integration and post-merge CI are tracked in Issue #27. No media,
  training, gold/freeze, product solver run or real-hand confirmation;
  REAL_HAND_ACCEPTANCE_PENDING / NOT_ASSESSED remain.
- **2026-09-22 CRITICAL PERCEPTION BOUNDARY:** runtime now uses versioned
  native-current board rejection and terminal-participation guards while frozen
  readers remain unchanged. Five source-bound candidate fields, a causal river
  transition window, shared snapshot/evaluation checks and a candidate-only
  TARGET-S screen prevent stale or contradictory automatic prefill. Perception
  validation disables the river study sidecar explicitly. The scoped scorer
  pins declared source rows/artifacts, replays candidate projection, requires
  nonzero polarity coverage and safe first-actor abstention; it cannot award
  real-hand, independent-vision or strategy acceptance. Final focused 89 passed;
  independent actual adapter+wager+boundary probes 10/10 passed after fixing
  initialization latency and an omitted cache dependency. Full lint/diff passed;
  full integration and exact-head CI results are recorded on the PR. Existing
  28 exposed hands remain CLASS X; single-frame diagnostics matched 26/28 boards
  and exposed a preprocessing-sensitive false card, not a temporal accuracy
  result. Sparse existing images cannot establish continuous first-actor truth.
  No new capture, training, real confirmation or product strategy run occurred.
  REAL_HAND_ACCEPTANCE_PENDING / NOT_ASSESSED remain; new source validation and
  owner signoff are required before phase completion.
- **2026-09-22 INDEPENDENT INTEGRATION REVIEW, PR #32:** fresh reviewers verified
  the requested 25168a8 baseline with 90 evidence/recovery and 168 domain probes;
  no scoped acceptance P0 remained. A non-P0 Unicode audit-text persistence issue
  was reproduced and fixed using physical JSONL line splitting only, preserving
  canonical seals. Final focused 151 passed; independent rerun 90/90 plus 4/4
  Unicode and 10/10 physical-line/revision checks passed. No media, real-hand
  confirmation, training, gold/freeze or product strategy work. Integration and
  post-merge CI are tracked in Issue #27; real acceptance and strategy assessment
  remain pending.
- **2026-09-22 TARGET-S CONFIRMATION V2 (PR #32):** repaired the six acceptance
  blocker groups from Issue #27 comment 5762748242. Source-bound stable windows,
  explicit opening/river interval seals, complete semantic recovery validation,
  evidence/revision-bound current receipts, full seat partitions, no-ALL_IN scope
  and lossless monetary identity/assertions now fail closed. Independent review
  additionally tightened clockwise order and malformed UTF-8 recovery. V1 stores
  remain untouched and cannot inherit V2 acceptance. Final focused 147 passed;
  the full run preceding the last two narrow fixes was 4392 passed/22 skipped,
  final independent probes passed 15/15 (root) and 36/36 (separate reviewer).
  Full lint and
  diff checks passed; exact-head CI is reported on the PR. All test receipts are
  synthetic. No real confirmation, capture, product strategy run, PHH bridge or
  training permission was created; REAL_HAND_ACCEPTANCE_PENDING and NOT_ASSESSED
  remain. This is a factual contract, not an executable solver adapter.
- **2026-09-16 GITHUB-001 (Issue #25) STANDARD GIT SYNC:** Added tools/git_sync.py, a thin
  verified wrapper around standard git/gh. Root cause of the observed push hang: the
  user-level config installs a Git Credential Manager helper, and `-c credential.helper=X`
  only APPENDS, so GCM still ran first and blocked. The wrapper resets the helper list
  (`-c credential.helper=`) before adding `!gh auth git-credential`, sets
  GIT_TERMINAL_PROMPT=0 / GCM_INTERACTIVE=never, runs every command under an external
  timer that kills only its own child tree, writes a 20s progress trail, drains pipes on
  reader threads, and refuses to report success without local HEAD == remote ref == PR
  head SHA. It never force-pushes, resets, rebases or cleans. Focused offline tests live
  in tests/tools/test_git_sync.py.
- **2026-09-17 USABLE-001 P1 CI REGRESSION FIXED - DIRECTED OPTIONAL-DEPENDENCY SKIP, NO ASSERTION WEAKENED (Issue #27, PR #28):** the P1 round pushed `0b7c40a` and CI run `35230485037` FAILED on BOTH matrix jobs at the `pytest` step (macos 7m22s, windows 9m36s; `review-hygiene` green; `flake8` never ran, because the step order is pytest then flake8). Root cause read off the failing log rather than guessed: `ModuleNotFoundError: No module named 'pokerkit'` - CI installs `-e ".[dev,perceptual,desktop]"` and NOT the optional `solver-tools` extra, so **PokerKit is genuinely absent on CI**, while the local runtime has 0.7.5, which is exactly why the P1 tests passed locally and failed there. **15 of the 24 P1 tests were red and 9 passed**, and those 9 are the substance: a gate refusal happens BEFORE the library is consulted (`shadow_export` computes `missing_required` and returns `NOT_EXPORTABLE` above the `_pokerkit()` call), so CI had already confirmed the fail-closed property on a machine with no PokerKit at all. The fix is therefore a DIRECTED skip, not a module-level one: a `needs_poker_kit` marker (`importlib.util.find_spec("pokerkit") is not None`, degrading to "unavailable" on `ImportError`/`ValueError`) is attached to the 15 tests that actually drive PokerKit, while the 10 gate/refusal/field-map/reverse-adapter tests keep running everywhere. A blanket module-level `pytest.importorskip` - the shape the other five optional-dependency modules in this repository use - would have made all 24 skip and left CI unable to tell a fail-closed gate from a missing dependency. A new test, `test_a_missing_field_refuses_before_the_library_is_consulted`, pins that ORDERING as the precondition the CI-visible tests rest on. Which tests to mark was MEASURED, not read off the source: a throwaway runner that swaps the path finder for one refusing to locate `pokerkit` makes `import` and `importlib.util.find_spec` behave exactly as on a machine that never installed it, and it reported **15 failed / 9 passed** before the fix and **15 skipped / 10 passed / 0 failed** after; with PokerKit present the module is **25 passed** (24 plus the new ordering test) and `flake8` is clean. The whole repository was then run under that same harness, i.e. under CI's real dependency set: **4099 passed, 21 skipped, 0 failed, exit 0** in 405.99s **(deliberately read from a `-v -rs` run: `addopts` already carries `-q`, so a second `-q` makes it `-qq` and the tally line disappears; counting the progress-bar characters instead undercounted the skips by 2, and the printed tally is the authority)**. Every number reconciles against the PokerKit-present run, which is **4158 passed + 1 skipped = 4159**: exactly **59** tests stop passing without the extra - the **15** newly marked P1 tests, **1** in `tests/tools/test_nlhe_rulebook.py`, **2** in `tests/tools/test_wpk_hand_trace.py` (all function-level `importorskip`) and the whole of `tests/state_engine/test_reviewed_replay.py` (**29**) and `tests/state_engine/test_reviewed_completion.py` (**12**), which gate with a MODULE-LEVEL `pytest.importorskip("pokerkit")`, so those modules never enter collection at all and contribute ONE skip entry each instead of their 41 outcomes. Skips therefore go **1 -> 21** for exactly the same reason (the pre-existing `Quartz` skip, the 15 P1 tests, the 3 function-level pokerkit skips and the 2 module-level entries), and both identities check out: `4158 - 59 = 4099` and `1 + 15 + 3 + 2 = 21`. `ci.yml` was deliberately NOT changed to install `solver-tools`: that is a repository-wide CI policy change which would also pull in `phevaluator` and alter other skip outcomes, so it is put to the user as a decision instead. No assertion was relaxed, no required field defaulted, and no threshold, ROI, solver, `_posting` anchor, `expires`, all-in terminal or early-fold change; nothing merged or released; `REAL_HAND_ACCEPTANCE_PENDING` and `NOT_ASSESSED` unchanged.
- **2026-09-17 USABLE-001 P0.1 ORDINARY-TERMINAL FAIL-CLOSED GUARDS (G1 STABILITY LATCH, G2 ACTION COUNT) - NOTHING RELAXED (Issue #27, PR #28):** authorized by `P0_1_TERMINAL_GUARDS_THEN_P1_SHADOW_ORACLE` (`issuecomment-5714727922`) as exactly the two guards the P0 round had reported and NOT patched. G1: a single self-contradictory frame (a flicker claiming a complete river inside a hand that never reaches one) must not be able to establish a sticky river fact, so `AAObservationSemantics` keeps a `river_streak` of consecutive AGREEING observations (`full_river AND pending_actions == 0`) and latches `river_frame` only on the SECOND; the latched frame is the FIRST frame of the run (`row["frame"] - (river_streak - 1)`), so the guard costs latency without re-stamping the recorded instant. The run is broken by a blocked row, by `epoch is None` and by `closed`, and the epoch-change and `reset()` paths still clear it; after latching, the pre-existing sticky semantics are UNCHANGED. G2: `pending_actions == 0` is required ONLY while first latching, never afterwards, so a later teardown or action-count wobble cannot revoke an already-established historical fact. Deliberately NOT a frame-count threshold tuned to this recording's 67/149/168 frames, and nothing was relaxed to preserve "5 hands close" - if the guard had cost a close that would have been reported per hand instead. Failing tests first: 3 of the 5 new cases ran RED against the pre-fix head (**3 failed / 18 passed**), the other 2 being anti-over-fix guards green on both sides by design; green now `tests/desktop/test_aa_ordinary_river_terminal.py` **21 passed** and the three-file desktop run **52 passed**. Real replay (0..27287, every frame through one temporal chain, no seek, no sparse sampling, 23m20s, `retrieve_fail / read_fail = 0 / 0`): full-river epochs **6**, latched-river epochs **5**, `ordinary_river_pending` **5**, `ORDINARY_RIVER_CLOSED` **5**, `closed NOT exactly once: none`; first blocker per epoch is **5** `CONFIRMED_ORDINARY_RIVER_CLOSED`, 14 `no_complete_river_observed`, 5 `no_real_hand_board`, 1 `suspended_bucket_has_no_epoch_name_so_c3_can_never_fire`. Latch detail: river frames are IDENTICAL to P0 (9512 / 12325 / 15033 / 18170 / 25674), each latches on the SECOND frame (9513 / 12326 / 15034 / 18171 / 25675), the latched VALUE is the first frame every time, and exactly **1** complete-river frame was seen before latching with `nonzero_pending = 0` in all five hands - so G1 costs one frame of latency and G2 costs nothing and no hand was lost; `observed_deal_14593` still closes at **f15198** (river 15033, latch 15034, 50 pending rows, settlement seat 4 `+134` 131 -> 265 confirmed 15148; Hero `4s 3s`, board `3c 7s 3h Tc 6c`). An independent post-hoc auditor (`p01_audit.py`, locating each payload by the epoch INSIDE it) re-derived the audit from the JSON artifact and reports **`PROBLEMS: none`** over 10 checks x 5 hands - needed because the IN-RUN audit printed 5 false "problems" by reading the closing epoch's record when a terminal actually rides on the SUCCESSOR's first row; the printed payloads carry `river_complete_frame = 9512 / 12325 / 15033 / 18170 / 25674` matching the latched values exactly. One un-attributed fact is recorded, not explained away: the anonymous `None` bucket has **119** complete-river frames (longest unlatched run 117, 5126 blocked frames) and never latches - a broken streak is plausible but UNVERIFIED, and it could never confirm anyway because it has no epoch name so C3 can never fire. No all-in terminal, vision threshold, ROI, solver, opening ledger, `_posting` anchor, `expires` or early-fold change; nothing merged or released; `REAL_HAND_ACCEPTANCE_PENDING` and `NOT_ASSESSED` unchanged.
- **2026-09-17 USABLE-001 P1 PHH + POKERKIT SHADOW ORACLE, FIRST ROUND - BYPASS/DIFFERENTIAL ONLY, NO RULE CODE DELETED (Issue #27, PR #28):** authorized by the same comment as P0.1, and the existing PokerSense rule code was NOT deleted while the production state machine was NOT replaced. PokerKit **0.7.5 was already installed** in the project runtime and `pyproject.toml`'s `solver-tools` extra already pins `pokerkit==0.7.5`, so P1 added no dependency. New files, not wired into the pipeline: `src/poker_engine/desktop/aa_phh_shadow.py` (**614 lines**; `SHADOW_SCHEMA = "aa-phh-shadow-v1"`, `VARIANT = "NT"`, `POKERKIT_NT_REQUIRED`, `PHH_REQUIRED`, `SEATS_FIELD`, and a `FIELD_MAP` tuple that is the single source of truth for the doc), `tests/desktop/test_aa_phh_shadow.py` (**24 tests at the time, 25 after the CI fix above, flake8 clean**) and `docs/research/pokersense-phh-pokerkit-shadow-oracle.zh-CN.md` (the required "PokerSense evidence -> PHH -> PokerKit State" field-mapping document, sections 1-8, which also records the payoffs-vs-`ChipsPulling` finding, the corrected side-pot arithmetic and the four-scenario refusal table). Contract: only CONFIRMED facts are ever handed to PokerKit, every UNKNOWN field carries an explicit `unconfirmed_because` reason, and `shadow_export(facts)` returns one of `NOT_EXPORTABLE` / `POKERKIT_UNAVAILABLE` / `POKERKIT_REJECTED` / `EXPORTED` - a `NOT_EXPORTABLE` or `POKERKIT_UNAVAILABLE` refusal NEVER contains a `phh` key (only `POKERKIT_REJECTED` carries the document, and there every required field WAS confirmed), so no refusal can hand a downstream consumer a hand history built from unconfirmed evidence, and no unknown field can be silently read by PokerKit as 0 / False / loser. `optional_explicit_utg` is deliberately judged UNMAPPABLE because it is a per-hand observation rather than a declaration. **The fail-closed gate is real and the proof is layered:** the real closed hand `observed_deal_14593` exported under four escalating scenarios - A (real situation, no table rules) -> **6** missing (`seat_order`, `min_bet`, `blinds_or_straddles`, `antes`, `starting_stacks`, `actions`); B (+ complete declared table rules) -> **3** missing; C (+ confirmed positional order and opening stacks) -> **only `actions`**; D (+ one action carrying the pipeline's best status, `PRICE_DERIVED_CANDIDATE`) -> still only `actions` with reason "1 of 1 action interpretations are not confirmed". All four refuse and none writes `phh`. The `actions` gate is STRUCTURAL rather than a data gap: `aa_semantics.py` assigns `interpretation_status` at only three sites (`"UNKNOWN"`, `"VISIBLE_LABEL_CANDIDATE"`, `"PRICE_DERIVED_CANDIDATE"`) and **never `"CONFIRMED"`**, so under the current pipeline no real hand can ever be exported - this is the round's headline finding and it was deliberately NOT worked around by inventing a status. **The most valuable measurement of the round is semantic:** PokerSense's `unallocated_positive_cash` is a settlement-time BALANCE DELTA (the counterpart of PokerKit's `ChipsPulling.amount`), NOT PokerKit's net `payoffs` - measured `payoffs = [-50, -300, 350]` against `ChipsPulling(player_index=2, amount=650)` - and the two coincide only when the credited seat contributed nothing to the pot, so a differential written against `payoffs` silently misreports every split pot; `_pulled_by_seat()` was added and the net payoffs are retained in the report as `poker_kit_net_payoffs` instead of being the comparison basis. Three capabilities were added after the first pass because the checkpoint asked for them explicitly: the PHH now carries the physical seats in the optional `seats` header (`seats = ['4','7','1']`, measured to round-trip verbatim while `dumps(loads(dumps)) == dumps` still holds), a computed `side_pot_split` differential item verified on a VALID main-900/side-600 short-stack hand and on a call-full-then-fold hand where a seat paid 300 but is eligible for none of it (so "paid in" is distinguished from "eligible", with fold status read from the `Folding` operations because `State.statuses` cannot tell a fold from a showdown kill), and the reverse adapter `shadow_ingest` plus `shadow_round_trip` where nothing the reverse direction produces is ever `CONFIRMED` (reconstructed actions carry `PHH_ROUND_TRIP`, so feeding them back into `shadow_export` REFUSES - otherwise the reverse would launder unconfirmed facts past the gate) and the round trip is asserted per field (`variant` / `antes` / `blinds_or_straddles` / `min_bet` / `starting_stacks` / `actions` / `seats` all MATCH; `ROUND_TRIP_NOT_RUN` when the forward export refuses rather than faking a result). **Two bugs of my own were caught and fixed rather than quietly deleted, both now pinned by regression tests:** the first `side_pot_split` version divided the pot by its eligible count to recover the level, which is not what a level is, and reported `MISMATCH` on the simplest single-pot hand (650/2 = 325, which nobody had paid); and the export constructed the `HandHistory` OUTSIDE the guard, so an illegal action list raised a traceback instead of the named `POKERKIT_REJECTED` refusal the action-legality item exists to produce. Also established: PHH round-trip identity holds (`dumps(loads(dumps)) == dumps`), replay must be driven by iterating `hh.state_actions` (a generator of `(State, action)`; `create_state()` returns only the INITIAL state, the final state being the last yielded one), `HandHistory.__init__` is keyword-only even though `HandHistory.loads` is not, `State.pots` is ZEROED once the chips are pushed so a side-pot split must be sampled mid-replay at the last state with a non-zero total (reading it off the finished state makes the check a tautology), and PokerKit's own `HandHistory.required_field_names["NT"]` is asserted against `POKERKIT_NT_REQUIRED` in a test so the gate cannot drift from the installed library - that assertion also pins that `seat_order` is OUR precondition and NOT a PHH field, a nomenclature error the first doc version made and has fixed. Solver expansion, Deep CFR and GTO strategy work were NOT started.
- **2026-09-17 USABLE-001 P0 FIRST REAL ORDINARY-RIVER HAND CLOSE - BOUNDED `river_frame` FIX, NOTHING RELAXED (Issue #27, PR #28):** authorized by `P0_FIRST_REAL_HAND_CLOSE` (`issuecomment-5713265121`) as a bounded code-gap repair and it supersedes the previous round's "REPORTED, NOT APPLIED". Failing tests first: the new sticky-river cases against head `f4b0298` gave **2 failed / 14 passed** (two further cases are anti-over-fix guards green on both sides). The fix in `src/poker_engine/desktop/aa_semantics.py` is exactly one combination wide: within an epoch, `not closed AND not full_river AND river_frame already set` used to CLEAR `river_frame` and now KEEPS it; clearing happens only on an epoch change, on `reset()` (source change or frame discontinuity, which still discards every cross-frame fact) and while `closed` (the all-in showdown explains the ending by itself) holds. **The previous round's root cause was mis-attributed and is withdrawn:** `payout_credit_not_visible` (reported for 3 of 5 hands) was a measurement artefact - the old probe counted credits only on frames whose board was still complete - and on a frame-by-frame re-measurement **all five** full-river hands have an own-epoch payout credit confirmed AFTER their last complete-board frame (8622 seat 3 +33 @9680; 11609 seat 5 +172 @12398; 14593 seat 4 +134 @15148; 17323 seat 4 +239 @18323; 24560 seat 1 +123 @25825). One root cause, five isomorphic manifestations, so one fix covers all five. Measured on the full continuous 0..27287 replay (every frame read through one temporal chain, no seeking, no sparse sampling): `ORDINARY_RIVER_CLOSED` **0 -> 5**, one per full-river hand, each EXACTLY ONCE (`closed NOT exactly once: none`; `terminal_rows` is 1 for exactly 5 of the 25 epochs and 0 for the other 20, so no epoch ever emitted a second confirmation event), each on the first observed frame of the successor epoch, none on an epoch without a full river, none without a payout, and the whole run reproduced IDENTICALLY by a second independent end-to-end replay. The target hand `observed_deal_14593` closes at **f15198** (river 15033; pending f15148-15197, 50 rows; then a direct switch to `observed_deal_15197` with no `None` in between); Hero `4s 3s`, board `3c 7s 3h Tc 6c`. All five carry `ledger_status: HAND_COMMITMENTS_UNKNOWN` with `canonical_verified / card_showdown_verified / rake_verified / strategy_eligible` all `False`, so this terminal claims no GTO strength and is not a checkable complete hand record. `pending_actions == 0` is still NOT a C1 condition - recorded as a documented deviation rather than silently added. **One new false positive found by an adversarial differential harness (same file, only the river block reverted) and deliberately NOT patched:** a single self-contradictory frame (`street_candidate == "river"` with five valid distinct cards) inside an epoch whose hand never reaches a river, followed by a cleared board, a `confirmed_frame` balance increase and a new epoch, now emits `ORDINARY_RIVER_CLOSED` with `river_complete_frame = 0`. Patching it would require an `ordinary_river`-exists guard that NARROWS the authorized semantics, so it is reported with the guard proposal for a decision instead; the failure mode is bounded to misclassification because C2 still demands that money moved, and it is unreachable on this recording where the minimum `complete_frames` across the five real hands is **67**. Verified: `tests/desktop/test_aa_ordinary_river_terminal.py` **16 passed**, `tests/desktop` **445 passed**, full suite **4128 passed / 1 skipped**, `flake8 src tests tools` clean. An independent auditor (fresh context, its own script, told not to use this round's analysis tooling) recomputed the raw JSON and CONFIRMED that each of the five hands really reached a complete river, really has a payout confirmed strictly after that river, that no river-less epoch closed, and every frame number claimed for `observed_deal_14593`; it also flagged a measurement caveat now recorded in the report (the adapter's `first_frame`/`confirmed_frame` are stable-read bookkeeping that can lag the raw balance change by a few frames - pre-existing behaviour, and both instants still fall after the river frame). No visual threshold, ROI, solver, `_posting` anchor, `expires` or seat-count change and no early-street fold-out terminal; `REAL_HAND_ACCEPTANCE_PENDING` and `NOT_ASSESSED` are unchanged.
- **2026-09-17 USABLE-001 ORDINARY TERMINAL REAL-REPLAY VERIFICATION AND LIFECYCLE CONTRACT (Issue #27, PR #28) - VERIFICATION ONLY, NO EARLY-STREET TERMINAL:** the reviewer accepted the desktop `DESKTOP_EPOCH_GUARD` as `FIX_ACCEPTED_WITH_SCOPE`, kept `>= 3 seats` unchanged, and asked for exactly two things: prove or disprove real footage hits for `ORDINARY_RIVER_CLOSED` on the authorized `aa-live-20260917-0430` recording with a continuous sequential replay, and pin the `ordinary_terminal` lifecycle before any consumer exists. (1) **Replay result: 0 confirmed hits, and the first blockers are located.** The whole recording was replayed continuously (every frame grabbed in ascending order, never seeked, never sparse) from frame 0 to 27,287: 25 epochs (counting the suspended `None` bucket), **6 reaching a full river** (`None`, `observed_deal_8622`, `observed_deal_11609`, `observed_deal_14593`, `observed_deal_17323`, `observed_deal_24560`), **1 producing `ordinary_river_pending`**, and **0 producing `ORDINARY_RIVER_CLOSED`**. Attribution per hand AS PUBLISHED THEN (subsequently withdrawn): three of the five named hands were recorded as never having a credit of their OWN epoch confirmed strictly after their river frame, so C2 was said to fail for them (`payout_credit_not_visible`); `observed_deal_8622` additionally had non-zero `pending_actions`; and the suspended `None` bucket has no epoch at all so C3 can never confirm it by design. **The `payout_credit_not_visible` half of that attribution is WRONG** - it was an artefact of counting credits only on frames whose board was still complete - and the P0 entry above carries the corrected five-hand measurement plus the single real root cause. Crucially the credit channel is NOT silent - 26,980 frames carry `unallocated_positive_cash` for 218,310 entries - but those are mostly opening/refund credits (`new_post_comparison` and `stable_visual_balance_increase`), so "this epoch has credits" is not the same as "a post-river payout", and the strict `confirmed_frame > river_frame` count is what the diagnosis reports. (2) **The second blocker is a defect in this round's own implementation, located to the frame.** `observed_deal_14593` DID satisfy C1 and C2 on real data: the river completed at frame 15033 and frames 15173-15185 carried a live pending record for 38 rows (`settle=1, seats=5, pending_actions=0`). Then **frames 15186-15197 lost the complete-river reading** (`complete=False`), which reset `river_frame` and withdrew the pending record, and only at **frame 15198** did the epoch switch to `observed_deal_15197` - a direct A-to-B transition with no `None` in between. So C3 found nothing left to confirm. The cause is that `river_frame` is cleared the moment the five board cards flicker during the end-of-hand animation, even though "this hand reached a river" is an already-established fact about the hand. Minimal fix (reported then but NOT applied in that round because the authorization was verification plus one lifecycle guard; APPLIED in the P0 round above): clear `river_frame` only on an epoch change, keep suppressing via `closed` at the eligibility level, and note the residual risk that a pending record would ride on an epoch if the adapter stalls - bounded by the fact that C3 requires the pending epoch to equal the epoch that just ended and epoch names are unique. (3) **`ordinary_terminal` lifecycle pinned as a contract, with tests.** It is now a ONE-SHOT CONFIRMATION EVENT emitted only on the confirming observation and cleared immediately afterwards (clearing happens in `observe` after `_phase` returns, so it covers every return path including the blocked and lost-epoch early exits), while the persisted history is a separate, explicitly named `last_ordinary_terminal` snapshot carrying its own `epoch` plus a per-row `belongs_to_current_epoch` flag so a stale terminal can never be mistaken for the current hand's. Four new tests cover the one-shot emission, no leak across the second/third/fourth epoch, absence before any confirmation, and that the event does not survive a blocked row. No downstream consumer exists yet, which is exactly why the contract was pinned now. Verified: full suite **4124 passed / 1 skipped / 414.33s** (previous baseline 4120/1, so +4 lifecycle tests), the five touched desktop files **86 passed**, `flake8 src tests tools` clean. No threshold, no ROI, no solver, no `_posting` anchor or `expires` change, no early-street terminal started, and **nothing was relaxed to make a hit appear**. `REAL_HAND_ACCEPTANCE_PENDING` and `NOT_ASSESSED` unchanged; the ordinary river terminal was recorded as `CODE_TESTS_PASS / REAL_REPLAY_NOT_YET_PROVEN` as of this round, and the P0 round above moved the real-replay half to PROVEN (5 hands) while keeping `REAL_HAND_ACCEPTANCE_PENDING`, since a closed terminal is not yet a checkable complete hand record.
- **2026-09-17 USABLE-001 DESKTOP OPENING BOUNDARY FIX AND ORDINARY RIVER CLOSE (Issue #27, PR #28) - KERNEL, SOLVER AND EVERY SEAT THRESHOLD UNTOUCHED:** the reviewer asked for three things and this round does exactly those. (1) **A real desktop-layer defect is fixed with a regression.** `aa_live_context.LiveStateAdapter`'s dealer-advance branch required only `dealer_run >= 2`, a changed `dealer_value` and `board_count == 0`, so a dealer-seat reading change (a reading wobble in this recording) re-anchored the hand and replaced the epoch even when this hand already held a ledger-qualifying opening. On the frozen development recording that discarded a ledger which had just resolved: source frame 1264 produced `observed_deal_1263` with `MULTI_POST_DEAL_CANDIDATE` and seven debits, and frame 1278 created `observed_deal_1277` with `DEALER_ADVANCE_CONTEXT_CANDIDATE`, sending `hand_ledger_v2` back to `HAND_COMMITMENTS_UNKNOWN` with `opening_post_vector_incomplete`; the plain `AA8StateAdapterV2` chain that the historical successful runs used kept the same ledger resolved for 67 consecutive frames. New `LiveStateAdapter._anchored_opening()` mirrors `AA8HandLedgerCandidate._reset`'s qualification exactly (one event for this epoch, status `MULTI_POST_DEAL_CANDIDATE`, at least three debits, no action observed yet) and, when it holds, only tracks the new dealer reading instead of re-anchoring; the deferred case (a reading change after this epoch has recorded an action) is explicitly out of scope and says so in the code. Evidence: `tests/desktop/test_aa_live_opening_boundary.py` plus the fixture `tests/fixtures/aa_reference_hands/opening_rows_1260_1290_v1.json`, which holds the **pre-adapter** rows for source frames 1260-1290 (1260-1262 from `aa8_first_hand_entry_dense_v2`, 1263+ from `aa8_first_hand_full_v1`) so CI needs no private `G:` pool; it cross-checks against the already-reviewed `eight_session_boundary_v1.json` (`initial_posting_slots [0,1,2,3,4,5,7]`, empty slot 6, hero `200 -> 196`). Run against the previous head `064894b` in a separate read-only worktree the two new files gave **8 failed / 2 passed** and now give **10 passed**; the two that were already green are the anti-over-fix guards (fixture sanity, and "an unanchored dealer advance must still re-anchor"). End to end on the real pool frames the desktop chain's epoch list went from "1264 MULTI_POST + 1278 DEALER_ADVANCE" to "**only 1264 MULTI_POST**", matching the plain-adapter history. (2) **The table's forced-bet structure was checked and the `>= 3 seats` threshold was deliberately NOT changed.** Three separate hands each open the pot at exactly **17** (frames 8647, 9814, 11130), and the committed `configs/game/aa-shadow-rules-v2.json` declares `small_blind 1 / big_blind 2 / ante 2 per dealt player / mandatory UTG straddle 4`; with the five dealt seats this recording consistently shows (empty seats 0, 2, 6) that is `5 x 2 + 1 + 2 + 4 = 17`, matching every hand. So the table has **five** simultaneous debits and `>= 3` is satisfiable in principle - it stays as it is. What actually blocks this recording is that **no seat's recognised stack ever decreases** in any of the three opening windows (`pot` moves while the stacks do not) and `causal_street_wagers_v2.status` is `WAGERS_UNKNOWN` with `street_price: null` and null glyphs, so the stack-difference method `posting_comparison` is structurally blind here regardless of the seat count. The arithmetic agreement is graded as an **inference**, not a confirmation: the rules file itself is marked `verification_status: "simulation"` and its own source note says it is "not verified live room accounting". (3) **A new, strictly bounded terminal type `ORDINARY_RIVER_CLOSED` was added in parallel to the all-in terminal, which is untouched.** C1 needs a complete river (`street_candidate == "river"`, five valid distinct board cards, `pending_actions == 0`) and `closed` false, and records `river_complete_frame`; C2 needs POSITIVE settlement evidence, a same-epoch `unallocated_positive_cash` balance increase confirmed strictly after the river - a zero pot alone never settles anything and an unread pot never blocks; C3 is the only confirmer, a NEW non-empty epoch observed strictly after `river_complete_frame` (which is the epoch event frame, because `_new_epoch` stamps the frame it runs in), and a lost epoch (`None`, the unsupported-scene or overlay case) NEVER confirms. Participating seats come from this epoch's own `participants`, never from `ledger.opening_evidence`, so the opening-ledger gap cannot silently disable the new path; `ledger_status` is copied into the evidence so a downstream consumer can require the ledger separately. The row states its own scope in `ordinary_terminal_semantics` (`ORDINARY_RIVER_CLOSED_ONLY; preflop/flop/turn fold-out endings are NOT covered`), and the record carries `canonical_verified`, `strategy_eligible`, `card_showdown_verified` and `rake_verified` all false and does not touch `terminal_observation_frame`. Seven counter-examples in `tests/desktop/test_aa_ordinary_river_terminal.py` cover confirmation only after the boundary, the explicit scope sentence, zero pot without a payout, a lost epoch after the river, a recording that ends right after the river, an all-in showdown never producing an ordinary close, a blocked overlay frame neither confirming nor reporting a pending close, and a preflop fold-out staying uncovered; all eight fail against `064894b` and pass now. Known limit stated rather than hidden: C2 needs a VISIBLE payout, and this recording's stacks did not move during the openings, so whether payouts are visible there is still unverified - if they are not, this terminal will simply stay PENDING on that recording instead of guessing. Preflop/flop/turn fold-out endings remain NOT implemented and are left for a separate round. Verified: full suite **4120 passed / 1 skipped / 407.27s** (previous baseline 4109/1, so +11 = 3 boundary plus 8 ordinary-terminal tests), `tests/desktop` + `tests/tools` **1726 passed**, `flake8 src tests tools` clean, previous-head counter-example `8 failed / 2 passed` versus `11 passed` now. NOTHING was relaxed: no threshold, no `UNKNOWN` downgrade, no ROI recalibration, no change to the `_posting` comparison anchor or its `expires`, no change to `closed`/`full_river`/`terminal`, no kernel, solver or capacity change, no front-end change, nothing merged or released. `REAL_HAND_ACCEPTANCE_PENDING` and `NOT_ASSESSED` are unchanged.
- **2026-09-17 USABLE-001 FIRST MANUAL OFFLINE TRIAL PREPARATION (Issue #27, PR #28) - NO FEATURE WORK:** U2 is frozen (`PASS_WITH_SCOPE`, review `pullrequestreview-5227367145`) and this round only prepares the first manual trial, so the kernel, the strategy path, the launcher and every computing limit are untouched. The standalone entry for commit `c993632` is `launch/u2-trial/START-TRIAL.cmd` (double-click) or `python launch/u2-trial/trial_launcher.py`, version `aa-trial-u2.0` with record implementation `aa-analysis-record-v1`; it prefers port 8791, reports a busy port instead of killing anything, opens the browser only after the service answers, and keeps its own `state/` directory so an existing installation's program, configuration and records are neither read nor overwritten. The main checkout `C:\Users\Administrator\WorkBuddy\扑克\PokerSense\` has no `launch/` directory at all, so nothing of the user's is replaced. Verified this round by really starting it: `--version` prints `aa-trial-u2.0 (aa-analysis-record-v1)`, `--self-check` reports `missing_resources: []` on the preferred port with `capture_enabled: false`, the ready file carries `base=http://127.0.0.1:8791/`, `GET /` answers 200 with all four panels and the `手工假设 · 非实时建议` tag, and `/api/status` answers 200 with `strategy_scope=AA8_OBSERVATION_ONLY_NO_ADVICE` and `table_rules.conditional_analysis_ready=false` (a fresh trial directory has no table rules yet, so saving them is the first step). The page carries NO on-screen version badge and none was added this round (that would be a feature change); the version is identified by the launcher banner, the panel set, each saved record's `implementation_version` and the trial state path. **No authorised real hand can be used for the trial**: re-reading the existing selection study (`docs/research/usable-001-u1-sample-selection.zh-CN.md`, which covered 10 decision points across 9 registered development hands, the two `observed_deal_17` observation sets and the 36 reviewed action labels) confirms no re-scan is needed - every registered hand has `HAND_COMMITMENTS_UNKNOWN` with `hand_commitments=null`, the river frames have at most TWO active participants where the kernel requires exactly three, and the 36 labels carry no hole cards, board, pot or commitments. That is why no "input pending human confirmation" could be produced: the parts that ARE known cannot form a computable hand and the missing parts cannot be filled without guessing, and no synthetic hand was relabelled as real. `docs/research/usable-001-first-trial-preparation.zh-CN.md` records the entry, the version identifiers, the simplest way to open it on the user's machine, the sample conclusion and the single consolidated list of what the user must confirm (the eleven no-guessing facts a real hand needs, the three things that may legitimately be stated as assumptions, and the one yes/no). The review's non-blocking note is fixed: `usable-001-u2-r2-...` §3.2 said the cap `8 < 6.5`, it is `8 > 6.5`, and that only means THIS pot does not reach the cap. No new private media was scanned, no capture device opened, no media replayed, no vision API called, no automation added, nothing merged or released, and no old sample material was re-searched.
- **2026-09-16 USABLE-001 U2-R2 (Issue #27, PR #28) RULE-SOURCE CONTROL HONOURED, WRONG-SHAPED RECORD ISOLATED - KERNEL UNCHANGED:** review `pullrequestreview-5226343574` accepted the whole U2-R1 rebuild (both recomputes really re-verify, compute and save new records with a parent link; request identity; content seal; three-process restart test) and refused final acceptance on two boundaries, which this entry fixes without redoing anything. (1) **The rule-source control now really switches the mode.** Loading a record's saved conditions puts the form into THAT record's rules scenario with the checkbox off; ticking "use this table's saved rules" used to call only the generic "input changed" path, which dropped the receipt but left the scenario alive - so the build request kept asking for `rules_source=document` with the OLD document rules while the control said otherwise, and re-verifying happily produced a receipt for a rule set the human had not chosen. The checkbox now has its OWN change handler (`handUseTableRulesFromControl`): ticking it leaves the scenario, clears the receipt, the built document and the accepted job, and says so - while KEEPING the hand, the opponent assumptions, the size grid and the recompute-parent link. `handVerify` also fails closed on the one state that must never be sent (a saved-rules scenario paired with the control saying "this table's rules"), the saved-conditions load lists the available switch in its gaps, and the panel feedback repeats it. Switching back to a record's saved conditions still goes through the explicit, verified path (reopen the record, press "recompute under saved conditions"). (2) **A wrong-shaped record no longer takes the list down.** `record.json` holding valid JSON that is not an object (`[]`, `null`, a bare string) made `recent` raise `AttributeError` straight out of the route: measured on the previous head, the list answered **HTTP 500 with a body that never finished**, the `null`/string cases and single `get`/`scenario` **timed out**, and all four healthy records disappeared from the list. The shape check is now the FIRST thing `_verify` does, `_present` reads its envelope fields only from a dict, the field-reading block turns the expected shape/type errors into that record's own named refusal, and `recent` isolates each file (parse + present) so a broken entry becomes its own `INVALID` row and the rest of the list is served normally - never an empty list, never a rewrite or a delete. Measured on the same probe script: the list now answers 200 with the bad row as `INVALID`/`display_permitted=false` beside four healthy records, `get`/`scenario` answer 400 with a named refusal, and the file stays byte-identical. (3) **A measured trap worth keeping:** `rake_cap_bb = 0` makes the cap `0 chips`, which removes the rake entirely - a table with `rake_percent=0.05, rake_cap_bb=0` produces EXACTLY the no-rake EVs (call 64.375 / raise80 108.90625), so a "recompute under current rules" check written against it proves nothing. The harness's current-rules table now uses `rake_cap_bb=2` (call 60.15625 / raise80 104.10625), and the switched recompute is also cross-checked against a DIRECT kernel call on its own canonical input. Verified: `tests/desktop/test_aa_analysis_records.py` went from **7 failed / 44 passed** against the previous head `d9212c8` in a separate read-only worktree to **51 passed / 0 failed**; the three-phase harness went from **9 named phase-1 failures** (six for the rule-source control, three for the wrong-shaped file) to green in all three phases, driving the real control through saved conditions -> switch to this table -> re-verify -> real kernel -> save a new record E whose effective rules equal the table's and whose numbers differ from the parent's, plus an in-flight switch that discards the stale answer, a wrong-shaped file exercised through the real list/get/scenario routes, and five records reopening unchanged after two real restarts with zero analytical requests. `flake8 src tests tools` is clean; the full suite is 4109 passed / 1 skipped (was 4092 / 1). Kernel, solver, capacity, launcher and CI config unchanged; no model change; nothing merged; `REAL_HAND_ACCEPTANCE_PENDING` and `NOT_ASSESSED` unchanged.
- **2026-09-16 USABLE-001 U2-R1 (Issue #27, PR #28) RECOMPUTE BOUND TO THE VERIFIED FLOW, REQUEST IDENTITY, SEALED RECORD CONTENT - KERNEL UNCHANGED:** review `pullrequestreview-5225415635` accepted the U2 save/reopen/launcher work as real but refused acceptance on three paths, and this entry supersedes the U2 entry below for exactly those three plus one readability item (its save ownership, idempotency, reopen and launcher statements still hold, except that a record now also carries a content seal and an explicit `source_kind`; "recompute under the saved conditions loads the frozen input and rules without touching the global table rules" and "recompute with current rules puts the saved facts back in the form and demands a fresh verify" are now TRUE end to end instead of merely intent). (1) **A: both recomputes go back through the accepted verify/invalidate flow.** `recordsRecompute` now voids FIRST - `recordVoid()` advances the record epoch, clears the detail and disables both recompute buttons, then `handResetForSource()` advances the hand token, drops the built document, the accepted job and the verified receipt, and clears the fields, the end-of-hand confirmation, the opponent assumptions and the rendered result through the existing 350 ms debounced cancel. It then loads the record's facts through the ONE shared fill entry (`handApplyFacts`, extracted out of `handApplyImportedFacts` so the two import paths cannot diverge on provenance or candidates), REPLACES its opponent model via a new `handApplyAssumptions` (ranges, response weights, size grid, aggression cap, fee scenario), and keeps the analysis-record id in its own field: `handSource.issue_id` carries only the ORIGINAL review id (or null) and `parent_analysis_record_id` carries the record, which the save writes into the new record's source. "Saved conditions" injects the record's rules as this scenario's rules and goes through the EXISTING document/table contract (`rules_source="document"` on `/api/hand-input/build` and `/api/analysis`), so a legitimate saved-rules scenario is not forbidden and the global table rules are never written back; "current rules" leaves the scenario unset and uses the table path. Neither auto-computes: the form says "待重新核对" and the human presses 核对输入, after which the real kernel runs and the result saves as a NEW record whose parent is the original. The previous behaviour - the form showing A while `handBuilt`/`handReceipt`/`acceptedAnalysisId` still belonged to B, A's cards mixed with B's ranges, the analysis-record id passed off as an observed-review id, and the saved-conditions branch establishing no saveable receipt at all - is exactly what the red run shows failing. (2) **B: every open/recompute/save answer is bound to the target it was issued for.** One epoch plus the requested record id plus the response's own record id plus the live selection are all checked, and a recompute additionally checks the form token captured after the void, so a clear, an edit or a rules change during the flight drops the answer instead of writing it over what the human now has. A failed open leaves no numbers and no enabled recompute button; a response naming another record is refused rather than painted; a save whose answer lands after the panel has moved on says so instead of reporting success for the current result, and refuses to report success for a non-displayable receipt. `recordsRefresh` now reads the selection at the moment the answer is APPLIED (it used to read it when the request was sent, so the automatic refresh after a save could switch the user to another record). (3) **C: the stored CONTENT is sealed and re-verified, not just the input.** Saving writes `content_seal {schema: "aa-analysis-record-content-v1", sha256:<digest of the whole record minus the seal>}` LAST, and every read path (`get`, `recent`, `scenario` and the idempotent `_find_existing`) runs the same verification. Named checks run BEFORE the seal so a failure says what actually moved: the folder id must equal the record id; `identity.source_issue_id`/`parent_analysis_record_id`/`job_id` must equal the source and job blocks; the input/facts/assumptions/rules digest chain and `job.verified_rules` must agree; `source_kind` must equal the type the source really implies; the root actions' `actor` must be the frozen Hero, a `bet/raise` size must be on the grid confirmed at verification (never rounded onto it), each `additional_cost` must equal that grid row's amount, and a `call`'s cost must equal the verified to-call; and the three blocks carrying the same derived numbers (support check, amount detail, capacity summary) must agree with each other, with the view's capacity and amounts REGENERATED from the verified support block. Because the identity digests are untouched by all of these edits, only the seal catches an `{exact, decimal}` pair rewritten together. A damaged record is INVALID on its own and does not disturb its neighbours; a file whose content was never sealed reports the new status `UNVERIFIED_FORMAT` instead of being silently promoted; nothing is ever repaired, rewritten or deleted, and the lookup refuses to hand back a matching-but-invalid file as "already saved". No new secret, no signing service, and reopening still never calls the solver. (4) **P2 readability:** `_view` returns an explicit `source_kind` (default `manual_hypothesis_unverified`; `linked_review_record`; `recomputed_from_analysis_record`) that replaced the old inference from the mere presence of an issue id, and the detail now shows the sample type in words and as the machine value, the original review link and the recompute parent, the ACTUAL rule values (not only a revision prefix) and the ACTUAL opponent ranges, response weights, size grid and fee scenario, in ordinary tables and a folding block. Verified: `tests/desktop/test_aa_analysis_records.py` went from **15 failed / 19 passed** against the previous head `3f56d4d0` in a separate read-only worktree to **34 passed / 0 failed**; the three-phase shipped-JS harness `tests/js/hand_records_flow_test.mjs` (real DOM stub, real HTTP, real kernel, three real server processes on one records directory) went from **15 named failures in phase 1** against that head to **run1 44/44 + run2 14/14 + run3 9/9**, exercising recompute-with-current-rules (A saved, B computed, A reopened, old receipt/built document/accepted job voided, A's facts AND assumptions loaded, re-verified, computed, saved as a new record C under the new table rules with `parent=A`) and recompute-under-saved-conditions in a NEW process with no receipt (A reopened, its frozen facts/assumptions ORIGINAL rules scenario loaded, global rules untouched, re-verified, computed, saved as a new record D that used A's rules rather than the current ones), then a third process reopening all four records field-for-field unchanged with zero analytical requests; plus out-of-order and forged record-id opens, a failed open, a clear and a selection change during a flight, a late list refresh, eight content rewrites and a legacy file refused on every read path with the file preserved. `flake8 src tests tools` is clean; the local full suite is reported in the progress log. `launch/` is untouched, `REAL_HAND_ACCEPTANCE_PENDING` and `NOT_ASSESSED` are unchanged, and no merge, no model change, no solver or capacity change was made.
- **2026-09-16 USABLE-001 U2 (Issue #27, PR #28) SAVE THIS ANALYSIS, REOPEN IT AFTER A RESTART, VERSIONED OFFLINE TRIAL - KERNEL UNCHANGED:** the checkpoint was "compute THIS input -> save -> close the program -> start it again -> reopen the same result", plus a trial entry that cannot overwrite an existing installation. New `src/poker_engine/desktop/aa_analysis_records.py` is a thin adapter over the existing analysis facade - `aa_study_records.py`'s fixed synthetic registry is untouched. One save freezes the facts (with provenance and original candidates), the assumptions, the effective rules and the verified revision, the canonical input, the report of the job that really finished, the input/facts/assumptions/rules identities, the job id, the implementation version, the save time and the optional source link. **The server owns the numbers**: the client may only name the job and the digest it verified, the report is read from the live facade, and RUNNING / ERROR / CANCELLED / TIMED_OUT / superseded jobs are refused; the canonical input is REBUILT through the same trusted path the build route uses (`aa_hand_input.build_document` with the job's own effective rules injected) so the frozen facts and the analysed document cannot drift apart. Saves are idempotent on `(job_id, input_sha256, source_issue_id)` while two different manual sources stay separate even with identical numbers. **Reopen is not recompute**: every read re-derives the whole view from the frozen values - schema, record kind, the four identity digests, input-to-job linkage, every `{exact, decimal}` pair with the decimal REGENERATED from the exact rational (an edited display is detected), and action-field consistency (`check/call/fold` must carry target 0, `bet/raise` must be positive, a `call`'s additional cost must equal the verified to-call, no duplicate root actions). A record whose rules revision or implementation version moved on is still readable as a HISTORICAL result under its original input/assumptions/implementation, clearly labelled, and the fixed-C rule that the source file must still exist at its original path is deliberately NOT copied; a record that fails a check is refused with `display_permitted: false`, `view: null`, and the file left exactly as it was. Reopen never calls the kernel and never writes the current table rules into a record; "recompute under the saved conditions" loads the frozen input and rules without touching the global table rules, while "recompute with current rules" puts the saved facts back in the form and demands a fresh verify. New `ui/aa-live/analysis_records.js` plus one section in the manual review entry adds save / list / open and shows the board and situation, the facts and assumptions with provenance, the rules scenario, each action's additional amount and conditional EV, capacity/blockers and the history labels, using only the existing design tokens and safe text nodes. `launch/u2-trial/` is a versioned, independent trial entry (`aa-trial-u2.0`, `START-TRIAL.cmd` + `trial_launcher.py` + a README) that reuses the local Python with no new dependency, prints its version and every unverified item, checks the required resources exist, waits for the service to answer before opening the browser, keeps its own git-ignored `state/` directory, and on a busy port reports it and picks an explicitly free one without ending any process or opening a capture device. Verified: 18 store regressions (server ownership, idempotency, every integrity refusal including a corrupt file that is preserved), 8 launcher regressions (a busy port leaves its occupant listening; a restart still lists a record placed in the state directory), 2 end-to-end tests, and a two-phase shipped-JS harness (`tests/js/hand_records_flow_test.mjs`) that computes and saves two different synthetic inputs, exercises the counter-examples, then - after the first server process is stopped and a NEW one starts on the same records directory - reopens both records with identical numbers and no analytical request at all. Full suite 4076 passed / 1 skipped, flake8 clean including `launch` locally (the CI lint target is UNCHANGED: the push token has no `workflow` scope, so a workflow edit is refused by the remote). No U2 scope creep: no algorithm/player-count/street/limit change, no new Git/MCP/automation, no new private media, no capture or vision API, no live advice, no merge, no overwriting the user's existing program. `REAL_HAND_ACCEPTANCE_PENDING` and `NOT_ASSESSED` are unchanged; every synthetic record is labelled `synthetic_input_labelled` and stays apart from real records.
- **2026-09-16 USABLE-001 U1-R3 (Issue #27, PR #28) RECEIPT BOUND TO THE TABLE-RULES VERSION, UNKNOWN CANDIDATES KEPT - KERNEL UNCHANGED:** review `pullrequestreview-5223174943` found that saving new table rules left `handBuilt`/`handExpectedInput` alive (`controls.js::saveRules` only cleared the analysis panel), that the hand receipt never recorded which rules revision it was built with, and that `handCompute` paired the OLD document with the CURRENT revision, so a hand verified against 0% rake could be computed against 3% - all three input hashes equal, because they all describe the old document. (1) **The receipt names its rules version.** `POST /api/hand-input/build` now returns `verified_rules = {rules_source, rules_revision, effective_rules_sha256}` and the form stores it on `handReceipt`; a build that comes back without a revision refuses to become a usable receipt. `handCompute` re-checks the receipt's revision against the page's current one, and the analysis request carries the VERIFIED revision (`analysisExpectedRulesRevision`) instead of whatever the page sees - since `start_analysis` already requires `body.rules_revision == current.revision`, a rule change made by another page is refused by the SERVER even before this page polls. `renderAnalysis` additionally requires the accepted revision, the report's `table_rules_revision` and the verified revision to agree. (2) **Every rules path voids.** `controls.js::saveRules` calls `handRulesChanged()` BEFORE its request (fail-closed for both save and reset), and `app.js::poll` calls `handRulesRevisionSeen()`, which compares the receipt's revision - or the revision an in-flight build used, via `handRulesInFlight` - against the page's; any difference voids the receipt and the result while KEEPING the typed hand so only a re-verify is needed. Two real defects surfaced while testing this: the first version of `handRulesChanged` only voided when a receipt already existed, so an in-flight build could restore "verified" (it now always goes through `handInvalidate`, which advances the token), and `handFillRows` dropped the retained candidate when a block was replaced (CSV or a human fill), which is the R3-B leak too. (3) **Unknown candidates survive.** `handApplyImportedFacts` retains every returned block's provenance/candidate BEFORE deciding whether a control can be filled, so `history` (unknown with a candidate) and `seats` (time basis failed, candidate kept) keep their evidence; `handFact` maps an empty control to `unknown + candidate` and a filled one to `human_confirmed + candidate`, so a candidate never becomes a confirmed fact. Verified: a new joint front/back harness `tests/js/hand_rules_flow_test.mjs` loads `app.js + controls.js + analysis.js + hand_input.js` in the page's own order against the real backend, so the same-page saves really run controls.js's submit handler and the real `POST /api/rules`, the external change is a plain POST the page has not polled, and the poll case drives the page's own `poll()`; it went from 24 passed / 12 failed against head `81b0f2a9` to 36/36, the import harness's new candidate cases went from 3 failing to 47/47, and the deterministic DOM regression gained three revision cases (39 now). Full suite 4048 passed / 1 skipped, flake8 clean. One fidelity fix in the stub: `.value` is now always coerced to a string and `element.id = x` registers the node, like a real document. No U2, no DIAG redo, no model change, no solver or capacity change, no merge; `REAL_HAND_ACCEPTANCE_PENDING` and `NOT_ASSESSED` are unchanged and were NOT replaced by synthetic records, which are used only for coding and counter-example evidence.
- **2026-09-16 USABLE-001 U1-R2 (Issue #27, PR #28) PROGRAMMATIC-FILL INVALIDATION, UNKNOWN/PROVENANCE, SNAPSHOT TIME BASIS, REAL IDENTITY CROSS-CHECK - KERNEL UNCHANGED:** review `pullrequestreview-5222526862` found that the import/batch-fill entry points bypassed the R1 invalidation, that an incomplete import inherited the previous hand's facts, and that the three input identities were never actually compared. (1) **Every replacement path voids first.** `handImportRecord` invalidates BEFORE it fetches, then binds the request's `handToken` and the rules revision at that moment and drops its own response if either moved, if `body.source.issue_id` is not the requested record, or if the fetch fails; `handCsvApply`, `handSourceChanged`, `handClear` and the verify start/failure paths all go through the one `handInvalidate` (bump the token, drop the receipt, clear the result and the debounced cancel). A batch fill never restores "verified", and the old receipt can no longer be computed. (2) **No inherited facts, no lost provenance.** Changing the source clears the previous fields, end-of-hand confirmation and opponent assumptions with a Chinese explanation; `handSource` records kind / issue_id / saved_at / preview_sha256 / source_frame / `revised_by_human` (in memory; U2 persistence is not started) and `handOrigin` keeps `{provenance, candidate}` per field, so an imported value stays `observed` with its original candidate until the human edits it, when it becomes `human_confirmed` and the candidate is retained. History became three-state - unknown, filled, or explicitly confirmed empty through a new `#hand-no-history` checkbox - and a blank seat id is refused in Chinese instead of `Number("")` turning it into seat 0. (3) **Snapshot time basis.** New `river_start_evidence()` in `aa_hand_input.py` refuses to treat the CURRENT stacks/commitments/participant states as river-start facts unless the payload proves it is a river-start frame: a non-empty `observed_epoch`, `street_candidate == "river"` with five distinct board cards, a clean `OBSERVED_HAND_COMMITMENTS_CANDIDATE` ledger for that same epoch with no taint, and reconciled `OBSERVED_STREET_WAGERS_CANDIDATE` street wagers that are all zero. Otherwise `seats` stays `unknown` with a specific Chinese gap and the ledger/wagers/stacks/participants are kept as the candidate. The R1 snapshot fixture used an invented ledger status and carried no start evidence, so its "positive" case was unsound; it now uses the real token and real evidence, and its missing-evidence variants are R2 negatives. (4) **The identity check is real now.** On a receipt for a form-initiated computation the panel requires a 64-hex `input_sha256` that EQUALS the digest the form verified before accepting the job, and `renderAnalysis` requires the accepted digest, the report's digest and (on the form path) the verified digest to be the same non-empty value - a missing report identity no longer skips the check - plus the same job, kind, source and rules revision. (5) P2: `_replay` now builds the kernel's own `RiverAction` and tests membership in `tree.legal(node)`, so 20 and 20.0 are the same amount; the row controls auto-generate and lock the kernel's zero for check/call/fold instead of asking a non-programmer for a sentinel, with an optional call-cost field reconciled against the replayed amount. Verified: the five touched test files were **15 failed / 34 passed (of 49)** against the previous head `5bed8cf` in a separate read-only worktree, and are **49 passed / 0 failed** now; the new `tests/js/hand_import_flow_test.mjs` (39 checks) went from 22 failing checks to 39/39 and really drives compute A -> import incomplete B -> refuse to reuse A -> fill and confirm B -> compute B, plus out-of-order imports, an edit or clear during an import, a failed import, CSV replacement, unknown vs confirmed-empty history, candidates and source, and mismatched/missing/foreign identities; the deterministic DOM regression gained three identity cases (37 now). Full suite 4047 passed / 1 skipped, flake8 clean. No U2, no DIAG redo, no model change, no solver/capacity change, no merge; `REAL_HAND_ACCEPTANCE_PENDING` is unchanged and was NOT replaced by synthetic records, which are used only for coding and counter-example evidence.
- **2026-09-16 USABLE-001 U1-R1 (Issue #27, PR #28) FORM IDENTITY BINDING, NO-GUESS IMPORT, LEGAL-HISTORY REPLAY, PER-ROW CONTROLS - KERNEL UNCHANGED:** review `pullrequestreview-5221916203` required four fixes and this entry supersedes the U1 entry below for those four points (its kernel, capacity, refusal and `REAL_HAND_ACCEPTANCE_PENDING` statements still hold). (1) **Identity binding:** the form's verified identity, the panel's expected identity and the report's identity are now ONE string, not three coexisting hashes. `aa_hand_input.facts_hashes()["input_sha256"]` and `AAConditionalAnalysis`'s `_json_bytes()` canonicalise with the same `json.dumps(sort_keys=True, separators=(",",":"), ensure_ascii=False)`, so the identity the human verified equals `report.input_sha256` byte for byte (asserted directly). `analysis.js` gained `analysisExpectedInput`; every input change funnels through ONE entry point `analysisInputChanged(reason)` that drops the identity, hides the result and cancels on a 350 ms debounce, and `analysis-start` re-verifies identity continuity, panel-content continuity and the form-to-scenario identity match BEFORE it posts, then stores both identities on `analysisBinding`; `renderAnalysis` re-checks them on every status poll, so an identity that moved invalidates the shown result. Two real defects were found only after the whole chain was driven end to end: a specific "result invalidated" message used to be overwritten by the generic cancel text, and an immediately-fired `POST /api/analysis/cancel` could land on a job the user had already started again - both fixed by the single debounced path plus `clearTimeout(cancelTimer)` in the start handler (the stale-cancel race is invisible to a click-counting test). (2) **Import never guesses:** `facts_from_snapshot` no longer derives the Hero seat from `current_actor`, no longer invents an action order from seat numbers, and no longer treats a live `observed_state_v2` participant state as the river-start state; each of those stays `unknown` with a concrete Chinese gap and an explicit rejected-candidate record. `blank_assumptions()["other_fees"]` starts `{"value": null, "provenance": "unknown"}` and fees are accepted only as `human_confirmed` or `assumed`, so unknown fees can never be read as zero. Duplicate combination rows and duplicate (seat, action) weight rows are refused with a merge instruction. (3) **Legal Hero history:** new `_document()` + `_replay()` rebuild the scenario and replay the declared public history through the kernel's OWN `_Tree`/`_Node` legal transitions - no second rule book - so an illegal action, a wrong actor order and a history that does not stop at an unfinished Hero decision each produce their own Chinese reason; the replay always runs even when a static check already failed, so a wrong order is reported as a wrong order rather than as a pot mismatch. (4) **Per-row controls:** the four free-text CSV textareas are gone; `#hand-rows-seats|history|ranges|weights` render one row per seat/action/combo with `#hand-add-*` buttons and a per-row delete, `#hand-fees` is a three-way choice, `#hand-import-record` brings in only the evidence-backed fields of the selected review record, and CSV survives only inside a `<details>` as a flat-row helper. A row the human has not touched is a placeholder and is never read as input, so seeding the empty form cannot fabricate a seat. Flat range rows are folded per seat for the kernel, and `check_support` now also reports the combo product, per-seat stack/hand-committed/street-wager/to-call and the kernel's full legal root actions with their additional chips. Verified: the three hand-input files went from 28 failed / 3 passed to 31 passed / 0 failed (the new tests were run against the previous HEAD in a separate worktree for a genuine red), the shipped-JavaScript form harness passes 25 checks and the new end-to-end harness `tests/js/analysis_flow_test.mjs` passes 26 checks by really feeding input → `/api/analysis` → a spawned worker → the real kernel → `/api/status`, then invalidating on an input change and on a late report for the abandoned input, then recomputing; full suite 4030 passed / 1 skipped, flake8 clean. Measured for two different hands at the same 4 legal joint combos, to_call 20, implied pot 130: Hero QsQd gives fold 0 / call 515/8 = 64.375 / raise 3485/32 = 108.90625 chips, Hero 2h3d gives fold 0 / call -20 / raise -2387/40 = -59.675 chips, with `strategy_eligible=false` and `advice_emitted=false` in both. No GTO, no whole-hand EV, no win rate and no live advice is claimed; strategy strength was not assessed and no DIAG stage was redone.
- **2026-09-16 USABLE-001 U1 (Issue #27) REAL-HAND INPUT ADAPTER AND PLAIN FORM, NO KERNEL CHANGE:** the offline desk can now take an ended hand typed in plain controls (cards, seats, public history, amounts, opponents' concrete combos with relative weights, response weights, bet sizes) instead of a hand-written JSON document. New `src/poker_engine/desktop/aa_hand_input.py` keeps observed FACTS separate from manual ASSUMPTIONS (each fact carries `observed` / `human_confirmed` / `unknown` plus the original candidate, and `unknown` is never filled), builds the exact 17-field scenario document the existing `analyze_threeway_river` entry point already accepts, and refuses anything the current kernel does not support in Chinese: more or fewer than three ACTIVE players at the river start, unequal active contributions (side pots), stacks that reach the all-in boundary, a displayed pot that does not reconcile with committed chips plus street history, a history bet/raise size outside the declared size grid (never rounded onto the grid), a history action with zero probability under the stated response weights, response weights with no mass on either node type, a combo product above 128 joint assignments (reported with the actual product), a missing opponent range or weight table, and any nonzero `other_fees`. `AAHandInput` never solves: it only pre-checks, and the same document then goes through the untouched `AAConditionalAnalysis` / `/api/analysis` chain, so results are computed for the current input and are bound to facts/assumptions/input hashes with `strategy_eligible=false` and `advice_emitted=false`. New routes: `GET /api/hand-input/template`, `GET /api/hand-input/facts/{issue_id}` (reads only a saved structured snapshot, `SAVED_STRUCTURED_SNAPSHOT_NO_MEDIA_NO_OCR`, never an image or OCR) and `POST /api/hand-input/build` (validates the saved table-rules revision when the form uses table rules). New `ui/aa-live/hand_input.js` plus one section in the analysis panel render with safe text nodes, invalidate the verified input on any change, show capacity (combo product, legal joint combos, highest bet, hero to-call, implied pot) and hand the document to the existing analysis entry. Verified: 14 backend regressions (including a hand-computed call EV of exactly 55 chips from two equal joint deals), a real-backend shipped-JavaScript interaction harness with 17 checks, a Chromium click-through that computed 0 / 64.375 / 83.03125 / 108.90625 chips from the typed input, full suite 4015 passed / 1 skipped, lint clean. Real-sample acceptance is `REAL_HAND_ACCEPTANCE_PENDING`: every registered development hand has `HAND_COMMITMENTS_UNKNOWN` and at most two active participants at the river, so no authorised real hand can satisfy the kernel's single-pot three-active precondition yet; the required user-supplied fields are listed in `docs/research/usable-001-u1-sample-selection.zh-CN.md`. Strategy strength was not assessed and the DIAG stage was not redone.
- **2026-09-16 STRATEGY-DIAG-D-R1 (Issue #23) REOPEN TRUST BOUNDARY AND INTERACTION FIXES, NO KERNEL CHANGE:** review `pullrequestreview-5220426669` accepted the D integration as present but not yet valid: a saved `record.json` was returned as `CURRENT` even after its display, binding or example identity was edited on disk, because only the source file hashes were compared and the stored view was trusted. `_verify()` now re-derives both the identity and the whole view from the verified source on every `get`/`recent`, so an edited record can never come back as a usable result: display-only edits, exact-value edits, path-contribution edits, changed `bound_record_id`/`source_type`/policy identity, an unregistered example, a non-false nested decision flag, a reshaped view or an unsupported file all yield `INVALID` with `view: null` and `display_permitted: false`; a replaced or unavailable source yields `HISTORICAL_UNVERIFIED` with the file preserved and no numbers. `_load` now also validates the nested identity shape (64-hex ids, exactly the two book hashes, non-empty world hashes, `bound_record_id: null`, `source_revision: 1`) and the synthetic origin of the table context. The study view gained an explicit experiment context (`table_context`): Hero cards, board, public history, pot and unit with its components, the to-call amount and BOTH frozen books' root actions, with raise-to separated from the additional chips amount - all derived from the pinned input and the validated report, never from an observed hand and never by re-planning a policy. The page now invalidates the current result on example change, record-selection change and panel close, invalidates BEFORE each new request, checks the response target identity in addition to the monotonic token, and refuses to render or to report success for a record that is not displayable. Verified: 15 new backend regressions plus 6 new shipped-JavaScript interaction checks were red before the fix (15 failed of 39; 32 passed / 2 failed of 34) and green after (39 passed; 34/34), full suite 3999 passed / 1 skipped, and two Chromium screenshots (context block; invalid-record notice with no numbers). Frozen protocol and C data untouched, no record file deleted.
- **2026-09-16 STRATEGY-DIAG-D (Issue #23) MINIMAL OFFLINE REVIEW INTEGRATION, NO KERNEL CHANGE:** the existing offline desk gained one controlled SYNTHETIC study view. New `src/poker_engine/desktop/aa_study_records.py` loads the frozen C report only through a fixed registry (example id to repository filename plus pinned sha256; the path strings inside the report are compared, never opened), recomputes every reported number as a Fraction (reach sums, contribution sums, per-policy deltas, cross-book path differences, per-factor readings, posterior sums, and the three shared baseline columns), and refuses baseline mismatch, BLOCKED worlds, unknown schemas, tampered contributions or probabilities, unreachable paths that carry a conditional EV, empty or non-hex policy identity, illegal declared paths and source hash mismatches. `policy_unchanged` now requires a full 64-hex identity, an identical before/after hash and a matching frozen-book ledger: two empty fields are not evidence. Records are independent sidecars under `records_dir/study-records/<record_id>/record.json` with `bound_record_id = null`, a `SYNTHETIC_STUDY_EXAMPLE` source type and no link into the observed-frame namespace. `aa_server.py` exposes five routes (`GET /api/study/examples`, `GET /api/study/examples/{id}/view`, `POST /api/study/records`, `GET /api/study/records`, `GET /api/study/records/{record_id}`) plus `/study.js`, all behind the existing same-origin and `X-AA-Live` middleware; the study flow touches neither the capture session nor any vision API (regression asserts the only session call is the application shutdown). The new `ui/aa-live/study.js` renders with `createElement`/`textContent` only, shows readable decimals with expandable exact fractions in chips, prints fixed number-derived sentences instead of generated prose, guards every paint with a monotonic token so a late response cannot overwrite the current record, and marks a record whose registered source was replaced as `SUPERSEDED_SOURCE` (historical) instead of a current result. Verified: 24 backend/API regressions, a real-backend plus shipped-JavaScript interaction harness (`tests/js/study_flow_dom_stub_test.mjs`, 26 checks: preview numbers and paths, save, list, identical reopen, late-response supersede, rejection paths, no innerHTML, study-only requests) and a real Chromium click-through with three layout screenshots. C wording corrections applied without touching the frozen protocol or its hash: an in-world negative delta still means the policy is worse than that baseline and cannot be undone by another world's sign flip; only extrapolation to a cross-world or real-opponent ranking is excluded; the protocol's "no ranking reversal" clause refers to global ranking, not to reporting the measured sign change of this specified comparison; and the protocol rationale's description of `TcTd` as an overpair was wrong (TT is not an overpair on a J-high board) - the file itself stays byte-identical.
- **2026-09-16 STRATEGY-DIAG-C (Issue #23) SINGLE-FACTOR OPPONENT-RANGE EXPERIMENT, KERNEL UNCHANGED:** One original failing stress scenario (`n6-facing_bet` / `reference_control`), one opponent-range parameter (the relative weight of seat 1's `JhJd` combo, the only combo in that range that beats Hero's QQ on that river), factors 0.5 / 1 / 2. The protocol `configs/strategy/examples/strategy-diag-c-range-protocol-v1.json` was committed BEFORE any perturbed world ran and declares the scenario, the single varied object, the factor list and the expected factor-1 baseline readings. Both policy books (`manual_reference`, `training_selected`) are compiled ONCE from the original planning scenario and reused in all three worlds with identical hashes before and after, so no world re-plans Hero; the driver is `tools/threeway_range_experiment.py` and it reuses `evaluate_policy_book(..., trace=True)` plus the path reconciliation instead of re-running the B-stage sample builder. Measured, exact: factor 1 reproduces the original reading `-30444/189457` chips (world and both book hashes match the production study), factor 0.5 gives `+353982/17719` and factor 2 gives `-5755044/284867`, so the SIGN of the selected-minus-manual-reference comparison reverses under this one range parameter at fixed policies; the manual reference stays exactly EV-equal to check/call in all three worlds while the selected book keeps the raise line, and its own history likelihood rises from `2834/39445` to `22781/225400` as that combo's weight grows. Every world and every reconciliation is exact (reach sums 1, contribution sums equal the policy EV, cross-book path differences sum to the reported delta with `distinct_books=true`; new `reconcile_path_ledgers` keeps the same-book entry point strict and requires an explicit opt-in for two frozen books in one world). No improvement, no optimal policy and no ranking claim is made: the outcome is a sensitivity result, and a negative or absent effect would have been equally valid. Committed artifacts: the protocol, the driver, the machine-readable result `configs/strategy/examples/strategy-diag-c-range-experiment-v1.json`, `docs/research/strategy-diag-c-range-experiment.zh-CN.md`, `tests/tools/test_threeway_range_experiment.py` plus two cross-book reconciliation regressions. Wording corrections from the B review are also applied: D is named "minimal integration of the existing offline review" (not a data-intake gap list) and `--check` is described as parsed-JSON content equality with timing fields excluded. D remains NOT_RUN.
- **2026-09-16 STRATEGY-DIAG-R1 STAGE B (Issue #23) TERMINAL-PATH DIAGNOSIS, KERNEL UNCHANGED:** `threeway_policy_evaluation_v1.py` gained an OPTIONAL path trace (`evaluate_policy_book(..., trace=True, trace_max_nodes=...)`); the solver, policy selection, baselines, settlement and risk boundaries are untouched and the trace is off by default. A second, independent traversal enumerates every terminal public path of frozen_policy / check_fold / check_call exactly once (Hero nodes expand over all legal actions with the policy action carrying the full mass, so the enumerated path set is identical for the three policies), and reports per path: public history, exact reach probability, conditional terminal EV (None exactly when the path is unreachable) and the weighted contribution. `PolicyPathLedger` recomputes every sum from its paths and requires the contribution sum to equal the independently computed policy EV and the fallback reach to equal the metric fallback probability, so no partially reconciled ledger can be constructed; `compare_policy_paths` subtracts two policies on the union of the same paths and requires the summed differences to equal the reported EV delta. `PolicyEvaluation.path_ledgers` is the ONLY difference between trace on and trace off. Budget exhaustion returns BLOCKED (`trace_node_budget_exceeded` / `invalid_explicit_trace_budget`) with no partial ledger. New `tools/threeway_path_diagnostics.py` (offline, exact rational strings, refuses to overwrite, `--check` against the committed sample) plus the synthetic world `configs/strategy/examples/threeway-path-diagnostics-v1.json` and its committed machine-readable output `...-sample-v1.json`: frozen_policy 19407/242 chips from 4 reachable paths, check_fold 0, check_call 497/8, deltas 19407/242 and 17491/968, every reach sum 1 and every reconciliation exact. Tests: a hand-computed 9-path/3-policy example, the trace-toggle identity, the no-optimizer guard, zero-probability and unreachable-path handling, union subtraction without ancestor double counting, ledger self-verification, and end-to-end sample regeneration. Claims: offline conditional EV of one declared synthetic world only - not an optimal-action proof, not bb/100, not profitability and not live advice; `strategy_eligible` and `advice_emitted` stay false. C (single-factor experiments) and D (minimal integration of the existing offline review, NOT a data-intake gap list) remain NOT_RUN at that checkpoint; C has since been executed in the entry above.
- **2026-09-16 STRATEGY-001-DIAG-V1 (Issue #23) CONCLUSION CORRECTION, NO KERNEL CHANGE:** Review 5217785775 (STRATEGY-001-R1) is correct: the production statistics path in tools/validate_threeway_models.py appends at most ONE record per (group, world) using an OR over three comparator columns, so the earlier claim that 9 of the 18 negatives were "double-counted" is wrong and has been withdrawn in docs/research. What remains true is only that the manual-reference column is numerically identical to check/call in the facing_bet worlds and to the selected policy in the unopened worlds - a readability/diagnostic observation that does NOT change the scenario failure count of 18. The earlier "main cause" and "over-calling" attributions are downgraded to untested hypotheses, and a clean run does NOT exclude an implementation defect: excluding one needs branch-level evidence, which stage B now supplies as a read-only path decomposition rather than as a repair. Added tests/tools/test_validate_threeway_models_counting.py covering the real production path: one negative comparator, two or three negative comparators in the same scenario, equal comparator columns, equal deltas across different (group, world) pairs, and an independent recomputation of the loss set from the report. Candidates, worlds, baselines, thresholds, the counting algorithm and the reported figure of 18 are all unchanged.
- **2026-09-16 STRATEGY-001 (Issue #23) OFFLINE RESEARCH, NO KERNEL CHANGE - SUPERSEDED, retained only for traceability:** Superseded by the CONCLUSION CORRECTION entry above for its attribution and counting claims. Its "dominant cause is category-B response/range misspecification" and "9 of the 18 negative comparisons double-count one comparison" statements are WITHDRAWN and must not be read as current guidance; component A was not excluded and no comparator was ever double-counted. The reproduction readings it reports (exit 0 / 30 world cases / 60 evaluations / fallback 0 / FAIL_STRESS_SCREEN / NO_EMPIRICAL_PROMOTION, and study_opponent_uncertainty.py exit 2 as a by-design signal at tools/study_opponent_uncertainty.py:95) remain valid. Original text: reproduced the three-way river stress screen on baseline dc72a41 with no code change. Delivered docs/research/strategy-001-{evidence,findings,results}.zh-CN.md and kept the strategy kernel, candidate set, worlds and metrics unchanged. Deliberately REPORT_AND_REPRO_ONLY: no counter, no fallback-world relaxation, no new robust module, no profitability or live claim. Its "next batch task 1 = comparator-degeneracy detection in the report layer" is also superseded: the approved order is now B (branch-level terminal-path diagnosis and exact EV reconciliation) then C then D.

- **2026-09-16 V5 OFFLINE STRATEGY ENTRY:** userendedplay;capturestopped,no
  subsequent device start. Reboot didnotlose saved20AI/600slog/90developmentsamples.
  Added unchanged-threshold Hero callprice,min-channel extraction,stable positive
  empty-plus withconflict guards;stable dealer/newhand andnumeric-stack comparison;
  independent late-opening receipts reachhandledger+causalwagers without deleting
  originalcash/events orclearing existingtaint/actions. Firstafter-singleframe P1
  fixed and independently reviewed. Saved6062actoris4;earlier actor7claimwas a
  timestamp alignment error and is withdrawn. River bound checkslegalholdings and
  card-disjoint tie upperbounds;manual saved-frame form/API persists assumptions,
  imagehash/result;no range guesses,feesunknown=>netNone,no livepolicy approval.
  Core3859pass/7skip/1warning,34JS;finalconflictguard45focusedpass.2060PNG replay
  baselinefieldsunchanged,21actions both;lastconflictguardlaterfocusedtested.
  Independentmath1024graphsPASS;EXE savedframe448/260=>grosslower94 PASS.
  V5 localhost8777 offlineonly,keyrestoredtomemory,calls_today20preserved. Browser
  visualQA unavailable. Actualrake/fulllegalstate/fullstreetstrongstrategy remain
  unaccepted. See docs/AA-STRATEGY-ENTRY-V5.zh-CN.md andprivate aa-strategy-entry-
  20260916-v1;no WorkBuddy dispatch,newpaidAIcall,merge/tag/release.

- **2026-09-16 LIVE FOLLOW-UP / STRATEGY DRAFT BRIDGE:** capture remainson8777
  UGREEN0/DSHOW. AuthorizedAIroundfinished20:17COMPLETE/3ERROR,no retry;43211
  reportedtokens,AI241match/71uncertain/10mismatch areNOTaccuracy. Poll800->250ms,
  remove duplicate validframe DOMreset;unknown/stale clearing retained. Saved
  snapshot->manualterminaldraft usesoriginal rules andseparateprovenance;
  unknown wagers/fees/ranges remainnull/empty,oldledger excluded,sameepoch/taint
  checked.32JS+26analysis/UI focused PASS. Userconfirmed2/4/8 ante4 storedprivate;
  fees/straddle subtype unknown,rules-save notused toavoid interruptingcapture.
  CORRECTION: saved6062 actoris4;earlier actor7 reportmixeddifferentframes.
  Added bounded600s/.5s readonlyGET settlementlogger,31tests/lintPASS;actualrun
  private settlement-followup-20260916. No video/newAIuploads,fee inference,
  gamecontrols,livepolicy approval orclaimstrongstrategycomplete. See reviewdeskdoc.

- **2026-09-15 AUTHORIZED LIVE AA CONNECTION / FINITE AI ROUND:** user explicitly
  requested capture during own live session,then approved real screenshots to
  DeepSeek atmost1/30s and20total. UGREEN25854/index0/DSHOW nowstreams;MSMF had
  2s noframe error. Firstsavedcapture141 Ks/3c visuallymatches;not accuracygate.
  Finite localAPI sampler pinsinstance/generation,stops onsource/stop/key/quota,
  rechecks markedframe provenance,no retry afteruncertainPOST. Separate round
  receipts identify timedautomation,never humangold. FirstrealAI COMPLETE2599
  tokens,match/uncertain are modelcandidates.4scheduler tests+27JS PASS;source
  selector now mirrors running options across tabs andremembers capture.
  CurrentV4 localhost8777,APIkeyonlyinmemory;primarycapturekept running.
  No client/game actions,automatic training,strategyadvice orprofit acceptance.
  See docs/AA-REVIEW-DESK-AND-VISION-API.zh-CN.md andprivate live-round-1 receipts.

- **2026-09-15 FOCUSED AA DESK / DEEPSEEK VISION REVIEW:** three views keep
  setup/diagnostics/manual strategy off observation screen. One-click mark keeps
  matched frozen image/fields while observation continues; human revisions and
  AI candidates remain separate,original observations unchanged. Fixed HTTPS
  DeepSeek endpoint,process-memory key,explicit per-image upload,UTC daily cap,
  one worker,no retry,30s publication timeout/late-result rejection;busy retained
  until underlying worker exits.16backend tests and26JS cases PASS,fullsuite PASS,
  focused lint/syntax PASS. PackagedEXE replay mark at1261/hash/stop/reopen PASS.
  Real API tested only on synthetic image:720candidate vs120visible detected,
  803tokens,COMPLETE;real table frames not uploaded. Browser visual QA blocked
  by bridge;independent code review andhardware/fullstate/strongstrategy pending.
  V4 private app atlocalhost8777;old8775 remains because process stop was denied
  by tool policy. No model training,automatic source edits or strategy promotion.
  See docs/AA-REVIEW-DESK-AND-VISION-API.zh-CN.md;private aa-review-desk-20260915-v1.

- **2026-09-15 AA PREVIEW READABILITY:** portrait preview now uses a wider
  responsive column and native aspect ratio; accessible scrollable live dialog
  opens without changing playback. Both views clear on invalidation/decode error;
  late preview replies remain rejected. 21 deterministic JS UI cases and 9
  focused desktop tests PASS (one dependency warning), JS syntax/diff checks PASS.
  Portable V3 static assets updated in place with source/bundle/HTTP byte checks;
  same server instance/generation continued replay. Browser visual QA unavailable
  because CUA bridge failed; no hardware or recognition/strategy changes.
  Private evidence: aa-preview-enlargement-20260915-v1. Manual review instructions
  in docs/AA8-FIRST-HAND-REVIEW-20260915.zh-CN.md; development status unchanged.

- **2026-09-15 AA ACTION SEMANTICS / SETTLEMENT CANDIDATES:** additive desktop
  interpreter uses bounded pre-debit same-source/epoch/street price+cash evidence;
  raw actions/ledger untouched,allin separated frombet/raise/call. First-hand
  2060frame rerun preservesalloldfields,21semantictypes matchreference;
  3023check retainsUNKNOWN confirmationstreet. Terminalriver/allin+latercredits
  +two clearedframes => waitingnextcandidate,currentledgerNone,historical629/6
  retained. No inference ofrake/mushroom13/6,no canonical/strategy promotion.
  28newfocused/full3786pass/7skip/1warning(52.58s),18JS checks. No model/template/
  threshold/hardware/holdout edits orruns. Evidence private aa-semantic-stage-
  20260915-v1/runtime-v1;see docs/AA8-ACTION-SEMANTICS-AND-SETTLEMENT.zh-CN.md.

- **2026-09-15 FIRST AA HAND REVIEW:** current3c50eb0/V3 rerun2060frames
  (3context+2057hand),21registered visible actions match seat/order/glyph/amount;
  83sourceframes visually reviewed(6full),prior references reused,not blindgold.
  4labels needbet/raise/call semantics;openingcash29-pot23=6 andsettlement
  529-paid516=13 remainunallocated. Settledpot0 vs historicalledger629 needs
  phase distinction;readable3195board rejected;UI raw/processed frame ambiguity.
  Dense onset/confirmation1740/1741,3168/3169,3171/3174 preserve1/1/3frame delays.
  About20min AI-assisted review,141.266s model;human labelingcostUNKNOWN.
  No runtime/model/threshold/media-source edits,device/holdout/strategy execution.
  See docs/AA8-FIRST-HAND-REVIEW-20260915.zh-CN.md;private aa-first-hand-review-20260915-v1.

- **2026-09-15 AA INTEGRATED TABLE VALIDATION V2:** continued with new account;
  packagedEXE now actually starts and runs model/development frames plus terminal
  andthreeway spawned analysis,overcoming prior blocked smoke. Added manualAA
  rules/nullunknowns/versioning,continuous manifest-bound multi-pool replay,
  same-frame user-triggered local issueJPEG+JSON,OS capture lock and10s separate
  analysis process. Manual input never becomes visual or live authority;old
  analysis invalidates on edits/rules/source changes. Reader resourceV3 bundle
  34files/24PNG/22,429,499bytes,baseline5frames unchanged,knownmuck suppressed
  andlightallin detected(developmenttemplateoverlap). Full3756pass/7skip/1warning;
  focus,packagedHTTP/browser/independentreview evidence retained privately.
  Realhardware unavailable,completelegalstate andstrongstrategy remain incomplete;
  source1260-1606dev autoepoch/dealer restored,unallocatedcash6 remains.
  Final3842frame two-hand runtime regression:3context/3839scored,38actions,
  sparse59/state45/38390historicalfieldchecks identical;107blocked retained,
  no readergapreset. Cashpositive94/516/559/192 remainunallocated. UI14case
  regression covers cross-tab staleEV;IPC-exit race fixed. Developmentonly.
  Finalfull3757pass/7skip/1warning(57.19s),lint0;earlier3756retained aspriorcheck.
  Final packaged browser identified neutral action target0 label ambiguity;
  call/fold no longer show raise-to0,15JS regressions pass.
  Server instance IDs prevent generation rollback after fast server restart
  from leaving UI stuck;focused session/JS regression added(16JS cases).
  No WPK development,device/control/holdout/thirdparty solver or training.
  See docs/AA-TABLE-VALIDATION-V2.zh-CN.md and private aa-live-integration-20260915-v2.

- **2026-09-15 ISOLATED MANUAL ANALYSIS FACADE:** AAConditionalAnalysis runs
  terminal/threeway manual JSON in one disposable multiprocessing spawn worker.
  Fixed input/binding/output budgets and4096terminal/128threeway assignments,
  20000threeway nodes;independent Timer terminates at deadline without polling.
  Cancel invalidates before termination;generation-bound result publication,
  copied input/binding/reports and no partial/error-result publication.23focused
  tests PASS including real examples,oversize/invalid/crashed child,forged live
  flags,compute caps,unpolled timeout and cancellation/restart. No capture,
  Provider,UI coupling or empirical promotion. Caller must cancel when saved
  rules/manual input/source generation changes;frozen entry must freeze_support.
  Evidence:aa-conditional-strategy-integration-20260915-v1/worker-pytest-final.log.

- **2026-09-15 CONDITIONAL MULTIWAY ANALYSIS INTEGRATION:** migrated 32 existing
  research files from the preserved primary worktree onto 6d76cfc:6 modules,
  5 CLIs,11 test files,6 manual/synthetic examples and4 historical reports.
  All46 existing transitive dependencies match the original source hashes;
  no task7 simulation assets or tracked identity patches imported.3 new target
  text files normalized to repository LF;originals unchanged.224 focused tests
  PASS after LF normalization,focused lint0;896 baseline files unchanged before
  this note. Terminal supports6-8dealt/Hero sole ACTIVE/2-7allin opponents on
  river;threeway supports6-8dealt but3ACTIVE at river start,finite actions and
  no allin/sidepot crossing. Fixed-policy/calibration/uncertainty failures remain
  regressions,not empirical approval. No live Provider/UI integration,hardware,
  media or external solver runs. Root evidence:
  G:/PokerSense_private/aa-conditional-strategy-integration-20260915-v1/.
  See docs/THREEWAY-MODEL-VALIDATION-V1.zh-CN.md and
  docs/OPPONENT-MODEL-V1.zh-CN.md;historical report counts remain historical.

- **2026-09-15 AA8 PORTABLE PRIVATE RESOURCES:** added minimal exporter and
  externally pinned validator;31boundfiles/21developmentPNGs/19,808,686bytes.
  Relativeprofile,source/context contiguous metadata retained;only reachable
  witnesses copied,no video/holdout/model changes. Reader requires trusted
  external manifestSHA for bundle profiles,checks path/role/reservation/hash
  closure before decode. Real constructor found missing card-head JSON sidecar,
  fixed and regression-covered;v1failed output retained,v2constructor+2template
  observations PASS with every JSON/PNG/NPZ access confined to bundle,pot43.
  44focused tests PASS,changed lint0,diff0. No hardware/accuracy/strategy
  acceptance;desktop CLI pin plumbing remains integration responsibility.
  See docs/AA-RUNTIME-BUNDLE.zh-CN.md and private
  G:/PokerSense_private/aa-resource-bundle-20260915-v1/.

- **2026-09-15 AA8 OBSERVATION TOOL V1:** added dedicated AA reader/session/
  source/server/UI and standalone PyInstaller entry. ExplicitStart/Stop,single
  session,latest capture slot,stale/error clearing,raw vs processed sequences,
  development role/path/hash validation. Real model deepcopy and PTS-string
  integration bugs fixed;STOP null-sequence UI and close-failure fixed.
  Full3440pass/7skip/1warning;post-PTS20focusedpass;release-propagation adds
  one focused regression(42newfocused total),lint0.
  Browser showed real development Hero5d6d/pot81/actor7 at1606 and stop-cleared.
  LocalAA EXEbuildPASS;packaged launch smoke BLOCKED by automatic approval,
  reason only blocked by policy. No device/video/holdout/control or strategy
  promotion. OptionalV3supplement not configured in current localprofile.
  See docs/AA-LIVE-MONITOR-V1.zh-CN.md and private aa-live-runtime-20260915-v1.

- **2026-09-15 AA-ONLY REPOSITORY MAP:** owner asks for full remote/local
  understanding before implementation;AA8/Hero4/6-8dealt is the sole current
  target and hardware is unavailable for testing. Verified main fb703e2,
  882remote/970primary-visible files and22worktrees;no product edits. AA readers
  remain tools/private compositions,not installed desktop runtime;canonical
  state and empirically strong multiway strategy are incomplete. Three read-only
  domain audits retained at G:/PokerSense_private/project-map-20260915-v1/.
  Optional GTOpen registration missing source_revision reproduced without
  network/device use;not fixed. No media/training/capture/commit/push/merge.

- **2026-09-15 AA FROZEN OBSERVATION VIEWER:** isolated localhost-only viewer
  for SHA7f86f4cd,1801frames(0–1800),nine visual slots. Shows source/time,values,
  unknowns,participation and resets;pot/presence/actor/full-actions/special modes
  explicitly unimplemented. Confidence and detailed rejection reasons absent
  from source are shown unrecorded,never fabricated. Browser verified hero
  Jc9h at152 and cleared at1261;no capture/recognizer/threshold/template/strategy
  changes. Five focused tests pass;full3399passed/7skipped/1warning,lint0,diff0.
  All1801frames verified29rows each and five explicit unimplemented fields;
  see docs/AA-REPLAY-VIEWER-V1.zh-CN.md.

- **2026-09-15 TC-20260915-03 historical baseline reconciliation.**
  The FIRST offline replay entry below is preserved verbatim as a historical
  baseline, not the current implementation status. PR #15 fixed the session-only
  slot 4 crop candidate (13415/13415 readable candidates) and added explicit
  manual-development context (12320/13415 epoch frames), not automatic hand
  detection or legal-state acceptance. PR #15 confirmed insurance in H02/H11
  and special-mode continuation in H09; conservative v3 ordinary selection is
  6 hands/8266 frames. PR #16 retained 82 reviewed actions, removed two muck/fold
  errors and added the missed H05 all-in candidate at8676 in development replay.
  Historical pot/actor/board counts and log hash remain baseline evidence, not
  rerun results. Full accuracy, recall, legal state and live eligibility remain
  unproven. Only document conflicts resolved; main implementations unchanged.
  See the dated correction in docs/AA-DEVELOPMENT-001-REPLAY.zh-CN.md.

- **2026-09-15 AA DEVELOPMENT 001 OFFLINE REPLAY: execution PASS; state
  closure incomplete.** User authorized PR #12 merge (main 3b2c8b9) and nine-hand
  replay. Exactly 13,415 selected frames processed with fresh CandidateStateV2
  per hand, existing training templates/models and overlay-aware GlyphTransitionsV2.
  Pot candidates 13,173; actor 9,675; postflop full-board 5,126/5,305; 100 glyph
  events, not verified actions. Slot 4 stack coverage 0; epoch and complete legal
  state both 0. No Advice/strategy eligibility. Identity and gate audit passed;
  model/config hashes unchanged and 200 implementation snapshots checked.
  Private evidence G:/PokerSense_private/aa-development-001-replay-v1/;
  observations 5ac0941bab6e9d8845a089fa0206d1df6c851af8ca75b9b7a6186159e236c167.
  No new capture or model training; coverage is not accuracy. Next: bottom-seat
  stack ROI/glyph review and spectator-state initialization investigation.
  See docs/AA-DEVELOPMENT-001-REPLAY.zh-CN.md.

- **2026-09-15 GLYPH SUPPLEMENT V3: development regression PASS.** Added
  explicit private fold/muck/light-All-in template competition;frozen reader
  unchanged.13415frames replayed,82reviewed actions retained,2muck-as-fold
  errors removed,H05slot0 all_in added at8676.Only new event within reviewed
  seven hands;full nine-hand100events not all independently reviewed. Templates
  from4565/11761/8680 overlap regression,not independent accuracy acceptance.
  Initial15action-loss experiment retained;fixed inconclusive supplement to
  preserve baseline.8focused/full3394passed/7skipped/1warning,lint0.No live
  integration/capture/Advice.Private aa-glyph-v3-development;see
  docs/AA-GLYPH-SUPPLEMENT-V3.zh-CN.md.Next:independent glyph confusion/recall audit.

- **2026-09-15 ACTION CANDIDATE REVIEW: PARTIAL, concrete defects identified.**
  Reviewed84events from prior7-hand selection via before/event/after frames;
  82visible glyph transitions,2false folds are showdown muck at11761/15313.
  Confirmed missed H05slot0 all-in visible8680/8710:308->0,display308,pot259->567;
  exact onset pending.24display-delta checks,not legal cash/conservation proof.
  H09 is the hand after lucky-bomb animation13600,previous ordinary classification
  wrong;conservative v3 excludes it,6hands/8266frames,old selections preserved.
  No complete opportunity census/recall or street-accuracy claim.Private review
  7b28fa56,manifest3e6b847a under G:/PokerSense_private/aa-action-review-001-v1/.
  See docs/AA-ACTION-REVIEW-001.zh-CN.md.Next:fix muck-vs-fold and missed all-in.

- **2026-09-15 OBSERVER VISUAL SPOT REVIEW: insurance true positives;
  ordinary selection corrected.** Frames3931/17114 show purchase countdown;
  followups3940/17130 explicitly show insurance mode. Keep fail-closed context
  clearing.7selected bottom-stack checkpoints match manual values;frame12000
  outside original selection is context only,not scored. Old nine-hand ordinary
  classification was overstated:H02/H11 contain insurance. New private selection
  v2 retains7hands/10068frames,existing targeted epoch available10068/10068 only
  in this post-hoc subset,not session accuracy/coverage acceptance. Old evidence
  preserved;no runtime changes. Report1d2418ea;selection61a7613b;private evidence
  G:/PokerSense_private/aa-observer-visual-check-v1/. Next:seven-hand action/state
  truth checks and separate insurance guard regressions;no strategy promotion.

- **2026-09-15 OBSERVER REPLAY TARGETED FIXES: development PASS, no live
  promotion.** Added session-specific layout candidate: slot 4 stack y914->912,
  old frozen layout and model unchanged. All13415 old failures clipped_or_border;
  current candidate coverage13415/13415,one manual frame2700 reads1107,not full
  accuracy acceptance. Added explicit offline manual-boundary context,not an
  automatic deal detector fix. Epoch12320/13415;1095 remain cleared after old
  insurance VISIBLE labels at3931/17114,requiring visual verification. Wrong
  source/interval/start rejected;overlay clears context without auto-reanchoring.
  Legal state/strategy remain false.7focused;full3386passed/7skipped/1warning,
  lint0,generator299. Private targeted output aa8e5ae7624d77bc006f4e45715295039315607d5ba3bde21f14f87977db614f.
  See docs/AA-OBSERVER-REPLAY-FIXES.zh-CN.md. No new capture or training.

- **2026-09-14 FIRST10MIN DEVELOPMENT MEDIA REVIEW + EXACT BOUNDARIES:
  source-specific PASS;9 ordinary development hands,not validation.** Owner
  authorized decode/review of session aa-live-observer-development-20260914-001
  and PR#11 merged as main4ab1cc3.Source receipt c09dd51e;10segments/
  3401350388bytes rehashed10/10.Full decode10/10 error0,1920x1080@30 MJPEG,
  noaudio;initial black0.000-0.867s and no later black;600one-fps frames all
  globally unique.Ten minute sheets show continuous AA POKER8-seat table,no
  lobby/other app/splash;498x1080 core geometry stable.Observer-only visual
  evidence remains consistent,not OS-input proof.Privacy P0:incoming-call overlay
  with direct phone number0.000-75.600s;value not copied into metadata/Git,whole
  interval excluded because it also obscures table top.Nicknames/avatars/stacks/
  possible table IDs remain private.5FPS board-count+dealer probe(no rank/name/
  amount/strategy recognition)plus12 dense +/-2s reviews yields1incomplete head,
  1incomplete tail,11inter-boundary complete temporal candidates;1privacy-
  occluded and1lucky-bomb special excluded,leaving9ordinary unoccluded candidates,
  including2preflop-only candidates.30FPS signal review plus before/current/after
  frame sheets confirmed12first-visible multi-seat forced-posting frames;FFprobe
  bound all18003frames to real PTS.Exact boundaries B01..B12 are frames1322/
  2591/4379/5894/7342/9270/10654/11884/13639/15441/16202/17761 with PTS
  44.067..591.959.Source-specific registry63a605cc,index26d3a815.9ordinary
  hands/13415frames frozen development_only selection08a8f411;no validation,
  holdout,calibration or cross-session canonical claim.Private report7a30153d,
  privacy780e53c9,79-file manifest6ff0efe4 all rehashed.No other media/upload/
  recognition model/strategy/Advice/input/promotion.See
  docs/AA-LIVE-DEVELOPMENT-MEDIA-REVIEW-V1.zh-CN.md.Next:separately authorize
  offline recognition on only these9 development hands;rules/identity/opportunities/
  legal menus/second same-rule session remain blockers.

- **2026-09-15 MACOS LIVE-STREAM PACING TEST FLAKE: isolated test PASS;
  PR #13 merged as 07bddff; three CI checks passed.** PR#12 doc-only head a0428e6 passed review-hygiene and
  Windows but macOS failed twice at test_interval_is_a_minimum_period_not_a_fixed_sleep.
  The test used a real0.20s source delay against only0.30s minimum period;slow
  runner pipeline overhead legitimately consumed the remainder,so production
  requested no sleep while the test required one.This branch changes only the
  test period to2.0s and asserts the0.20s work is credited(sleep<=1.81s);a fixed
  2.0s sleep still fails.No production pacing/runtime behavior changed.Target
  test10/10 repeated pass;full3379passed/7skipped/1dependencywarning(28.70s),
  full lint0,generator299,private filename guard867/0,diff0.

- **2026-09-14 FIRST FINGERPRINT-BOUND 10MIN AA OBSERVER DEVELOPMENT CAPTURE:
  technical PASS;media/dataset review PENDING.** Owner signed dry-run003 after
  completion(signoff334a1f47)and explicitly authorized one600s passive capture.
  Session aa-live-observer-development-20260914-001 binds fingerprint769a404c,
  authorizationaf4496a2,plan20e83e33 and prior dry-run sources.It finalized
  CAPTURE_FINALIZED_UNREVIEWED:18003frames,out_time600.058264s,10segments,
  finalPTS600.025s,maxgap0.001s,3401350388bytes,drop0,dup0,exit0,forcedfalse;
  full inspect0.Device824e5633 and FFmpeg57c56e36 match signed dry-run;no capture
  process or active lock remains.Private receipt
  c09dd51e737cfb57bd001f716e6d75e8c29d4fda9c840b70d04109c9bc96748d,
  metadata reportf8c4fa263c1c141c32d7350135b8e082b4051382544bf1de603804887fc2628b,
  manifest46b9e42da05bb0a56131a21360e1e27b2a05e30ad439d4a037d22325a356459c.
  No media decode/view,audio,recognition,strategy,Provider,equity,Advice,input,
  ADB/emulator/retry/promotion.Source remainsUNASSIGNED_QUARANTINE/BLOCKED;
  platform/privacy/rules/identity/hand-boundaries/opportunity census/legal menus/
  split/independent review remain missing.See
  docs/AA-LIVE-DEVELOPMENT-CAPTURE-001.zh-CN.md.Next:obtain session-specific
  decode/review authorization before any dataset intake or offline replay.

- **2026-09-14 FINGERPRINT-BOUND OBSERVER DRY-RUN003: technical PASS;
  post-capture human signoff PENDING.** Operator declared phone model,Android,
  AA version and capture-card firmware not queryable and adapter model not
  required;sentinel values are explicit operator unknowns,not observed facts.
  Manifest fingerprint769a404c384d1105b2399c09750d194adf1d457824e8af606ee7d6fb993b7567.
  New10s passive session recorded301frames,out_time10.066656s,segmentPTS10.033s,
  drop0,dup0,exit0,forcedfalse;full receipt inspect0.Final receipt
  1259774ebc42c77204f506bfafb8515223c9ac24e3e7da328f5bb331806efdeb.
  Device824e5633 and FFmpeg57c56e36 match prior observations;lock-fix validated
  on real hardware because no active lock remained.No session003 media decode/
  view,recognition,strategy,Advice,input or automatic promotion.Signoff request
  ba51b2e5ff7d884ba56ed4a52178bcb8194c84c1fb90d0e4092032c541ce8d1d,
  manifestb025c59de7512ea6d3cc645e10f373efe4ea781a62b0da65464327beab8e645d.
  Owner previously authorized progression,but protocol requires a concrete
  post-capture human statement before HARDWARE_DRY_RUN_SIGNED_OFF and a separate
  600s development authorization.No development capture started.

- **2026-09-14 AA OBSERVER DRY-RUN002 MEDIA REVIEW: visual/technical PASS;
  privacy restricted,hardware signoff BLOCKED.** Explicit authorization covered
  only session002 offline platform/image/privacy review.Source segment hash
  371af049dacaa5daf9be249b8e782713fc11f547fa348e33276b43c6e5d25f68
  matches immutable receipt c6d5d08b442964c10ab8001392aaf86f2d12a3789ddac3100cdd94dd12fe9cd3.
  Full30.033s MJPEG decode exit0/error0;1920x1080@30,noaudio,blackdetect0;
  30one-fps samples all unique.Six full-resolution samples show continuous AA
  POKER8-seat table,no black/splash/corruption.Core crop[711,0,1209,1080]
  exactly matches existing498x1080 normalization4634d6f2 and AA8 candidate layout
  6e8a53ee.No Hero hole cards or operator fold/call/raise controls are visible;
  evidence is consistent with declared observer-only but cannot prove OS input
  absence.Window is only partial turn-to-river,not a complete hand boundary.
  Nicknames,avatars,stacks/bets,possible room/table identifiers,status bar,network
  latency,rules and live state are visible;private offline review only,public/Git
  media blocked and masking+pseudonyms required.Current receipt fingerprint is
  null and immutable,so signoff remains impossible.Private report
  f41d7207c531dd1100d691dde8393be381e719145bf269f81ef99382bd5a2dd9,
  hardware candidate70a9a19a6ddd61d6d187e7efc3ce5386bbabe0f9cd977aac65157687dfe63219,
  manifestdb5b63b7ce4f0eb92e61a9903e8923a3110d1a390b76d6d01bf3394d85aaedb0;
  15/15files rehashed.No other recording read/media uploaded/model/strategy/
  Advice/ADB/input.No automatic promotion.See
  docs/AA-LIVE-DRYRUN-MEDIA-REVIEW-V1.zh-CN.md.Next:get exact phone/Android/AA/
  adapter/firmware declarations,then request a new fingerprint-bound short dry run.

- **2026-09-14 AA OBSERVER DRY RUN 002 + DEVICE-LOCK FIX: engineering PASS;
  media review/calibration remain BLOCKED; owner PR review pending.** User
  explicitly authorized one new30s passive session while spectating AA;no
  participation or extension.Session aa-live-observer-dryrun-20260914-002
  recorded one MJPEG-copy MKV segment:901frames,out_time30.066637s,
  segmentPTS30.033s,172206698bytes,drop0,dup0,exit0,forcedterminationfalse.
  Prior10s frame-density failure did not recur.Final status
  CAPTURE_FINALIZED_UNREVIEWED;receipt
  c6d5d08b442964c10ab8001392aaf86f2d12a3789ddac3100cdd94dd12fe9cd3,
  plan0a6e148e36bebe1a47767841ff5433cb2b55b95b8b9803fe5e9ee5fe16765fd6,
  authorization19fad24d7bf3bc7ae6b7e3c3722ff1681ec969a50a1bc0592b2a2434c027d6cc;
  full receipt inspect exit0.Source remainsUNASSIGNED_QUARANTINE/BLOCKED;
  hardware fingerprint null and all visual/privacy/rules/identity/hand-boundary/
  opportunity/legal-menu/session-split/independent-review gates remain open.No
  decode,screenshot,media-content read,audio,recognition,strategy,Provider,equity,
  Advice,input control,network orADB.Both finalized sessions left device locks.
  Stale locks were manually investigated,exact bytes preserved under
  G:/PokerSense_private/
  aa_capture_lock_investigation_20260914_001/ and _002/,then cleared;no session
  evidence deleted.Root cause reproduced:the lock identity included size but was
  captured at0bytes before PID/session content was written,so final comparison
  always differed.Current branch from main b7b2483 moves the identity snapshot
  after lock write+fsync;normal success and handled recorder failure remove only
  the unchanged owned lock,while an externally changed lock remains for manual
  investigation.59focused tests;full3379passed/7skipped/1dependencywarning
  (26.51s),full lint0,generator299,private filename guard865/0,diff0.V1 freeze
  manifest f3b55436 unchanged and patch paths overlap0freeze entries.No further
  hardware/media/decode/capture/strategy action.Next:owner reviews/merges the
  scoped PR,then separately authorizes media review before hardware signoff.

- **2026-09-14 CONNECTED UGREEN COMPOSITE-DEVICE READ-ONLY PREFLIGHT: PASS;
  video stream/dry run still NOT AUTHORIZED.** PR#7 merged as main
  0d24d32db6fb1887e36258b306ff1912a4339155.User connected phone/capture card;
  metadata-only inspection found two same-name PnP interfaces:MI00 usbvideo
  Camera and MI02 usbaudio MEDIA.Original Name-only unique check safely rejected
  but made valid video unusable.Fix now enumerates one DirectShow(video)
  alternative first,then selects exactly one Name=UGREEN25854+Service=usbvideo
  CIM entity,requires MI00/Camera-or-Image/OK,one signed driver with exact
  DeviceID,version/provider/INF/class GUID,and normalized full DShow PnP identity
  equal to the CIM ID.Popen still uses the exact alternative and `-an`;audio
  sibling is excluded.PnP tail is `pnp_instance_suffix`,never physical serial;
  capture_card_serial may remain null.Hardware fingerprint includes full video
  interface metadata plus prior phone/app/UVC/layout fields.6 adversarial
  service/class/driver/MI/suffix/DShow mismatches reject.Real read-only probe PASS:
  selected interface canonical SHA
  824e5633a9578e4a93724be01ecabb63139b347f6c616637cdbf7206e280d079;
  FFmpeg9.0.1 real target SHA
  57c56e369d5b4873b4d93fc1a1d833cb7cd8bc9325c14b05c34ce60b22842d8a,
  size222229504;G free~222GiB.
  Private evidence G:/PokerSense_private/aa_capture_hardware_preflight_20260914_v1/
  observation ffce26a2fb7a942a86e2791c8ffb1cabd21622f5cd39fded4846368117271d1a,
  report0f376854d10a5494400ddbf4a88e1ec02a297318a9f20f52df505bde1ead0a4a,
  manifestde8d2f29774b1e43cb71d276796ed64c03d10567bbe9c316be4c3245ee47705e;
  independent hash/canonical recomputation0differences.62focused;full3371passed/
  7skipped/1dependencywarning(29.46s),lint0,generator299,diff0.Independent code/
  evidence/scope reviews P0/P1=0.No video= input,stream open,frame/media read/write,
  capture authorization/nonce,model/strategy/advice.This proves device enumeration
  only.Next:fill private phone/app/adapter/UVC/layout declaration and obtain exact
  per-session phrase before one10s observer-only hardware dry run.

- **2026-09-14 AA PASSIVE REAL-CAPTURE INTAKE V1: engineering PASS; real
  hardware dry run PENDING one-time user authorization.** PR#6 merged as
  main8e14f754342f9245feb6e0e1cc289075e272b420;new isolated branch adds a
  stdlib-only formal capture CLI and NOT-DATA authorization template.No desktop/
  recognition/state/strategy/provider/equity/advice/ADB/network/input-control
  imports or source/replay/device/codec/extra-arg switches.One authorization
  expires<=24h,binds one aa-live-* session,private root,5-30s hardware dry run
  or60-1800s development capture,fixed20GiB/25GiB disk caps,privacy,field-level
  UNKNOWN/operator-declared rules and pseudonymous identity;11forbidden
  capabilities must befalse.Nonce is single-use;formal device lock blocks
  concurrency;all JSON/status writes flush+fsync.New recorder uses a prehashed
  absolute FFmpeg,shell=false,60s MKV stream-copy segments,noaudio,and rehashes
  the binary after stop.Windows CIM requires oneOK UGREEN25854+one signed driver;
  the same FFmpeg enumerates one DirectShow alternative containing matching
  instance VID/PID+serial,and Popen uses that name.Manifest fingerprint also
  covers phone/app/adapter/card/firmware/serial/instance/driver/UVC/layout/
  normalization;development requires same hardware,observed-device and FFmpeg
  hashes as dry run plus distinct session/group.Dry authorization,plan,
  finalization and human signoff files+SHAs are all required and the original
  dry session bytes are rehashed before plan and record.Capture frames must
  match segment/out-time and30fps within max3frames/10%;duration,wall clock,
  drop/dup/progress/stop/exit/file set/hashes are bounded.Success maxes at
  CAPTURE_FINALIZED_UNREVIEWED;all sources stayUNASSIGNED_QUARANTINE/BLOCKED,
  all offline/calibration/model/strategy/advice/control gates false.Failed
  receipts retain files,require a whitelisted real failure blocker and visible
  fact<->blocker equality;malformed progress writes attempt-failure instead.
  Full inspect rebuilds ledger/metadata/segments/command/FFmpeg evidence.55
  focused;full3370passed/7skipped/1dependencywarning(27.15s),lint0,generator299,
  private filenames865/0,diff0,V1freeze280/280,old private hashes9/9.Three
  independent adversarial reviews P0/P1/P2=0.
  Existing frozen recorders remain byte-unchanged;operator can bypass formal
  tooling at OS level,so project accepts only intake-closed sessions.No real
  CIM/PnP/FFmpeg/device/media/decode/capture/model/strategy run.See
  docs/AA-PASSIVE-CAPTURE-INTAKE-V1.zh-CN.md.Next:after explicit per-session
  phrase,collect private hardware inventory and run one bounded dry run;then
  human privacy/source signoff before any development session.

- **2026-09-14 AA8 ARTIFACT VERIFIER + ACTOR EPISODE CENSUS V1: engineering
  PASS; real calibration/live use BLOCKED.** Added conservative actor-cue episode
  census,closed nine-role JSON/JSONL bundle builder and read-only verifier on
  main c9f32115881583b0493e57c632601a1ad76506fa. Two complete hands cover3313
  gameplay frames:2472known actor/841UNKNOWN(813supported+28unsupported),14UNKNOWN
  spans,32episodes.30reviewed MATCH actions bind28 one-to-one within12frames;
  4unmatched episodes retained and A10/A33 remain unbound.26bindings have exact
  street;2cross-street episodes are explicitly EPISODE_STREET_AMBIGUOUS;explicit
  street conflicts remain unbound and do not consume an episode. Verifier rejects
  path/NFC/case/symlink/reparse/hardlink/TOCTOU/non-UTF8/duplicate-key/schema and
  bool-as-int attacks;requires external manifest SHA,9/9 role closure,and rebuilds
  the entire readiness wrapper+audit+episode census from the same hashed snapshots
  for exact equality.All promotion fields remain required false/null.Status only
  VERIFIED_CURRENT_BLOCKED_METADATA_SNAPSHOTS with6blockers(raw media absent,
  source BLOCKED,identity/rules/legal menus/independent coverage missing).Episode
  v6 SHA1bb9cfda2a12ed49fb167ffdf8f243c7a7b6e20644fb0fce875979e1a2cfd9b8;
  bundle v4 manifest2b5ad31b77bad1cb5bf08e175eaa7c27d9aa515307699fa566cee201bcc1df5c;
  verification v4 76e813b7ad0c11e8547ab02f4a993f32f657e0bc1b6a88d0ac264d4b934c6e84.
  42focused;full3320passed/7skipped/1dependencywarning(27.25s),lint0,generator299,
  private filenames861/0,diff0,V1freeze280/280,old private hashes9/9.Three final
  independent code/evidence/scope reviews PASS after readiness source-rebuild and
  exact-int fixes. Earlier episode/bundle/verification versions retained. No media/
  protected segment/device/model fit/strategy/advice/live/merge/tag/release. See
  docs/AA8-ARTIFACT-AND-ACTOR-EPISODES-V1.zh-CN.md.Next:human-review the34 union
  candidates plus detector misses,and add stable identity,real rules,complete legal
  menus and a second same-rule session before any offline calibration.

- **2026-09-14 AA8 COMPLETE DECISION OPPORTUNITY AUDIT V1: engineering PASS;
  real dataset/calibration BLOCKED.** Added model-independent all-table decision
  ledger/auditor+CLI,NOT-DATA template,complete synthetic contract and current
  AA8 JSON/JSONL readiness builder. Exact schema binds platform,AARuleProfileV2
  recomputed fingerprint,raw recording/audit/manifest hashes,whole-session split,
  stable player vs physical seat,all hands/censored edges,ordered ledger/details,
  predecision frame+PTS,complete legal ranges,exact Fraction,mode/review status.
  Rebuilds forced pot,street/hand commitments,current bet,stack,actor/pending order,
  fold eligibility,allin state and aggression reopen;hand must reach one-player/
  allin terminal or closed river round. Ordinary JSON can only reach DECLARED_
  COMPLETE_NEEDS_ARTIFACT_VERIFICATION,never calibration eligibility;fit/range/
  strategy/advice/live always off. Current late-AA queue:36reviewed/30MATCH/6false,
  25opponent/5Hero;preflop7/flop19/turn2/river2;30candidate UNKNOWN rows,legal
  menus0,eligible0,BLOCKED with26blockers. No second confirmed same-rule session:
  255.977s physical recording is lobby-only;old1377.97s source is unverified9seat/
  mixed rules. Final readiness e10be9812b7beb24cd8da4792166fbc94903493831192f2ddc799a2f474cec10;
  synthetic9391257b19e7c42e69047e5b98ee0c9c0abd17fbbd81fef983047b55aefb5a6d;
  templatecf7a902bdf91370fb5aadbb6af097288e2034ba985747f2ae1bc4ea073fe20fd.
  53focused;full3327passed/1skipped/2warnings,lint0,generator299,private filename
  854/0,diff0.Independent
  code/evidence/scope reviews PASS after five adversarial rounds. No media/protected
  segment/device/model fit/live strategy/tag/release. See
  docs/AA8-DECISION-OPPORTUNITIES-V1.zh-CN.md and private
  aa8_decision_opportunities_v1_20260914_v10/. PR#2/#3/#4 merged sequentially;
  canonical main135ba95908861e9e85847fc6c8eca5e5b24e2fcf before this branch.

- **2026-09-14 AA8 GLYPH DE-DUPLICATION V2: engineering/development
  regression PASS; real calibration still BLOCKED.** Preserved V1
  action_reader/action_transfer/visual_pipeline bytes and added versioned
  GlyphTransitionsV2+offline visual pipeline. Unsupported/special scenes suspend
  confirmed identity but cannot bridge unconfirmed streaks; rapid different
  glyphs stay suppressed through short clears,5stable clear rearms,and automatic
  non-authoritative hand candidates never reset epochs. Existing4661frame
  development replay(840.023-995.366s) yields42->36events,retains all30reviewed
  MATCH,removes exact6reviewed false,keeps6outside-hand events in order,and adds0.
  Strict regression binds old/new/review/registry hashes,4661frames,18unchanged
  inputs,explicit V1->V2 implementation replacement,policy and ordered event
  identities. Final report0c794250f6a222bc294dab1b4418cd6f3ad783e08f0c95e6cf8b613420735f65,
  observationsb3e206aadda8738454a1e620fc1c9360bbe149585ea4ff93f376d7ea763d8ff9,
  regressione3e1ca46b19082307193790327243690dba49cfeea0a83cc202bd0142aa551af.
  Independent code/evidence/scope reviews PASS after fixing two rounds of P1s.
  Focused63passed;full3274passed/1skipped/2warnings,lint0,generator299current,
  private filename0,diff0.Original C-root V1freeze280/280 and private hashes9/9;
  this PR overlaps0freeze entries (prior stacked baseline differences are not
  relabelled as freeze matches). One early reviewer accidentally SHA-read existing
  840s+ review PNG bytes without rendering;no video or300-820s access;final reviews
  were source/JSON only. No legal menus,independent accuracy,holdout/device/live
  strategy/advice/main merge/tag/release. See docs/AA8-GLYPH-DEDUPE-V2.zh-CN.md
  and G:/PokerSense_private/aa8_glyph_dedupe_regression_v2_20260914_v2/.

- **2026-09-14 AA8 ACTION TRUTH REVIEW V1: author development review COMPLETE;
  independent visual review pending,real calibration BLOCKED.** Reviewed all36
  complete-hand glyph candidates from physical capture-card development frames:
  30visible completed actions(25opponent/5Hero),6false;types check11/fold10/call6/
  bet2/allin1. A18 is post-call showdown muck misread fold. A28-32 are prior
  check/fold labels reappearing simultaneously after allin confirmation overlay,
  not new actions. Manual amounts use visible stack deltas and remain candidates.
  New strict review contract/tool retain all rows,bind source/order/hand/frame/
  slot/glyph/evidence hashes,require matched action/amount semantics and same-slot
  prior MATCH for stale duplicates;legal_actions must remain null.14new focused
  tests initially passed;code review found and fixed missing candidate-frame SHA
  binding and cross-hand stale references.16focused;full3253passed/1skipped/
  2warnings(27.67s),lint0,generator0,private filename0,diff0.Independent code
  review PASS.Independent blind visual review
  agrees36/36 classifications and all9nonzero amounts;A27 clearer frame28240 added.
  Output result-v4 sha264be3050dc1fd7834caaff8358dd1cd1938b00073503a8a21065eed52850e73.
  See docs/AA8-ACTION-TRUTH-REVIEW-V1.zh-CN.md. Stacked on Draft PR#2;no protected
  media/emulator/device/live advice/main merge/tag/release.

- **2026-09-14 AA8 PHYSICAL-CAPTURE OFFLINE SESSION EVIDENCE V1: development
  engineering in review; real opponent calibration still BLOCKED.** User
  confirmed AA/WPK emulator logins are restricted; product CLI/server now expose
  capture-card only and reject adb, while historical backend/evidence remain for
  offline regression. Used only new8seat physical-capture development segments
  0014-0016,840.023-995.366s,4661frames;segment0013 excluded whole because it
  crosses protected820s boundary. Source audit/sizes/mtimes/hashes unchanged.
  Existing pipeline:3781supported scenes,2968known-pot frames,42glyph candidates.
  Manual boundary review registers2temporally complete development hands
  25492-27473(next27474) and27474-29051(next29052),plus incomplete tail29052-29864.
  Complete hands contain36glyph candidates/30opponent;29 have same-slot actor cue
  within prior12frames. Legal menus/reviewed decision truth0,amounts unbound;
  first hand has unresolved special-bomb pot,one session cannot train/validate.
  All results strategy_eligible/advice false. New fail-closed registry verifier
  binds audit/split/segments/4661samples/pipeline/events/key frames and rejects
  emulator,protected overlap,hash/order/drop/boundary drift. Initial review found
  and fixed PTS/localframe,registry-next-boundary/evidence and SHA manifest path
  traversal/read-order gaps without changing old helper.28focused tests;
  full3237passed/1skipped/2warnings(28.08s),lint0,generator0,private filename0,
  diff0. Final independent rereview PASS;PR#2 CI and owner signoff tracked in PR. See
  docs/AA8-OFFLINE-SESSION-EVIDENCE-V1.zh-CN.md;private evidence under
  G:/PokerSense_private/aa8_offline_session_evidence_20260914_v1/.
  No LDPlayer/ADB/device/live capture/advice/tag/release/main push.

- **2026-09-14 PUBLIC CANONICAL REPOSITORY + PROTECTED PR WORKFLOW:** Created
  independent public `xiaoyangpeng1994-create/PokerSense` (not a fork), with local committed
  baseline eb4011172adec280c99cd442ca49e9083ce9ec8b on main. Local `origin`
  targets the canonical repository; `windgeek-base` retains the earliest public
  repository as reference. `x-poker` is a substantive 532-file/54-commit private
  historical snapshot and is retained. This PR adds the Chinese review template,
  workflow guide and CI hygiene checks. The migration also removes two baseline
  recorder lint violations and regenerates strategy fixtures against the
  repository's LF asset bytes for cross-platform determinism. Uncommitted later
  work remains preserved in the primary worktree and will migrate through
  dependency-scoped PRs. Local3216passed/1skipped/2dependencywarnings(25.42s),
  full lint0,generator check0,private filename guard827/0,diff-check clean.
  Independent review PASS; Draft PR #1 CI PASS,owner merge pending. Public main
  protection requires current PR+three checks+resolved conversations,includes
  admins,and forbids force-push/deletion;0 approvals avoids single-owner deadlock.
  No old repository merge,tag,release,media upload or live action.
- **LOCAL HANDOFF CHECKPOINT 2026-09-12:** current cross-model entry is
  handoff/2026-09-12/START-HERE.zh-CN.md; old HANDOFF-CODEX-GPT6.md marked
  historical. Pre-checkpoint audit:34modified tracked,371untracked/1,690,272B,
  no large/private media,nested git,reparse point or high-risk secret pattern.
  Full3216passed/1skipped/2dependencywarnings,lint0,43changed JSON parse0fail.
  Repository/private SHA manifests and read-only VERIFY.ps1 included. Expected
  local tag handoff-2026-09-12-aa-strategy-task6 must resolve to clean HEAD;
  no remote push. New agents run VERIFY.ps1 -Full before edits and start only
  NEXT-TASK strategy task7. AA is active;WPK regression. Do not use older
  historical chat claims over this package.
- **STRATEGY TASK6 RANGE ASSET/TRACKER COMPLETE, NO REAL RANGE DATA:** additive
  AAConcreteRangeAssetV2+strict schema pins rule/source/node dimensions and only
  sorted concrete combos; reversed holding duplicates, bad weights/likelihoods,
  missing exact nodes reject. Reuses blocker filter+Bayesian update. Per-hand
  AARangeShadowTrackerV2 logs all action events, requires>=.80 likelihood coverage;
  no-likelihood/unseeded/reordered/collision taints snapshot. Readiness requires
  exact pot-eligible opponent seats,no extras,current rule source versions and
  confidence>=.25. Equity now requires identical permitted tracker snapshot by
  default; untracked only explicit test disclosure. Existing MIT preflopR is not
  relabeled for ante/rake/straddle.23range+11equity/tool focused tests pass;
  full3216passed/1skipped/2warnings,lint0,V1freeze280files0changed. No realAA
  prior/likelihood,visual equity,Provider,Advice. See
  docs/AA8-RANGE-ASSET-TRACKER-TASK6.zh-CN.md.
- **STRATEGY TASK5 VERSIONED ASSET + EQUITY SHADOW COMPLETE, no real asset:**
  additive AAStrategyAssetBindingV2 pins asset/capability/rules/provider/player/
  street/source/license/status; test_only cannot shadow, mismatches reject.
  AA rake distribution now fingerprinted. Rule-aware equity reuses adaptive
  exact/MC+multi-pot shares; requires exact rules/context/opening/ranges, explicit
  simulation, computes gross/configured-net with proportional or main-first rake,
  never Advice. Synthetic6/7/8 exact river report has gross150,rake4,net146 only
  as engine wiring proof. WAL whitelist now records math/provider state but rejects
  preferred_action/unknown fields. Latest real v8 shadow20260910-v2:3839records,
  provider0/equity0/advice0, WAL8939b345308dea033edf39ba9e169657f073c605c2bbaad353a25a255e3e47bc,
  chain/receipt/current implementations match. No realAA range/strategy nodes,
  settings UI,holdout/device/live approval. Full3192passed/1skipped/2warnings,
  lint0,V1freeze280files0changed. See
  docs/AA8-ASSET-AND-EQUITY-SHADOW-TASK5.zh-CN.md.
- **STRATEGY TASK4 AA RULE V2 + PROVIDER GATE COMPLETE, no real strategy asset:**
  additive aa_rules_v2 encodes6-8 players,per-player ante,none/mandatory/explicit
  UTG straddle,exact blinds/rake/cap/application/rounding/minchip and fingerprints;
  old frozen contracts unchanged. Checked aa-shadow profile1/2/4(2),3%,2BB is
  explicit SIMULATION not live truth. Forced-bet plan derives positions,first actor,
  raise floor and reconciles all8 slots; real dev first7p differs seat4+2/seat7+6
  total+8 UNALLOCATED, second has missing seat6 and cannot reconcile. Rake unknown
  policy abstains. AARuleBoundShadowRouter requires live rules,exact fingerprint,
  exact opening/context and correct straddle raise floor; only preflop unopened,
  shadow candidate never Advice. FakeProvider is tests only; existing no-ante/rake
  RFI remains blocked.24focused tests pass;full3165passed/1skipped/2warnings,
  lint0,V1freeze280files0changed. No settings UI/real asset/equity/advice.
  See docs/AA8-RULES-AND-PROVIDER-GATE-TASK4.zh-CN.md.
- **STRATEGY TASK3 P0 CANDIDATES COMPLETE, NOT CANONICAL:** reused existing D
  detector with AA8 ROIs+2frame/epoch gate.15manual development dealerPNG checks
  match; full3839 dev_v6 stable dealer7=2043,0=1491,next1=38,unknown267;
  single moving5/6 rejected. Added per-epoch hand ledger from opening debits plus
  exactly-once action debits, never fee/rake attribution, and preflop action-line
  vocabulary. Base frames3732: ledger candidate3610/unknown122; all identified
  preflop1896/1896 have line candidate. Long differences6/2 and next-window-2
  remain UNALLOCATED; canonical/strategy flags false. V7 preserved21+17 actions,
  sparse59fields and2740/1099 wager coverage;9 dev checkpoints x5 fields=45/45.
  Current dev_v8 output ee6e6240876f62b1dd2a730b8efe6d93d5c6ce486e522c342546b7f32c1b3d20
  byte-identical tov7 after malformed-input guard. Shadow v8 WAL
  7c600afbcdda7540e86f19a25c4975e3ce6e63434223446c9e9b6d7523bbc40f.
  Full3141passed/1skipped/2warnings,lint0;V1freeze280files0changed. No
  holdout/device/provider/equity/advice. See
  docs/AA8-DEALER-LEDGER-ACTIONLINE-TASK3.zh-CN.md.
- **STRATEGY TASK2 SHADOW BACKEND COMPLETE OFFLINE, not live strategy:** added
  tamper-evident append-only ShadowWalWriter, bounded incremental follower,
  exact offline analyzer and AA8 source-hash runner. Final owned dev session
  aa8-dev-v5-shadow-20260909-v4 has3839records,3732ABSTAIN,107DEFERRED,0READY;
  no provider/equity/advice. WAL3906ea230e60ef30d3dd45d7e75266ff573f5154caf9d6a4c48d08f75b2c3242,
  chain/receipt/current implementation hashes verified. Gate p50.0151ms/
  p95.0211/p99.0296/max.1095 only,NOT E2E. Base optimization queue P0 action
  line/dealer/hand-ledger all3732,actor-visible-blocked2945; P1wager992,hero349,
  street278,stack118. Special107excluded from base tuning. No live capture/UI,
  auto-tuning or holdout read. Final3115passed/1skipped/2dependencywarnings,
  lint0; bounded follower reread3839/3839 without failure or partial line. See
  docs/AA8-SHADOW-LOG-BACKEND-TASK2.zh-CN.md.
- **STRATEGY TASK1 COMPLETE, overall strategy NOT complete:** added fail-closed
  aa8_shadow bridge for8physical/Hero4 and6-8dealt players, plus saved-log audit.
  It reuses PokerState/context/legal actions/sidepots/ranges/multiway equity/router,
  but requires ten explicit canonical authority flags and full conservation.
  Actual dev_v5 3839frames:3732ABSTAIN,107DEFERRED_SPECIAL,0structurallyready;
  no provider/equity/advice executed. Existing RFI heuristic is only unopened,
  ante0/rake0;7/8derived9max and notGTO. HU is not multiplayer; postflop/straddle
  assets remain missing.16new tests +155reused-core tests pass; full3099passed/
  1skipped/2dependencywarnings and lint0. No new holdout,capture,strategyUI or
  game action. See docs/AA8-STRATEGY-BRIDGE-TASK1.zh-CN.md.
- **LATEST scope-adjusted V2 dev_v5, still PARTIAL:**3839developmentframes,
  2740causalwagercandidate/1099UNKNOWN versusv3 2556/1283 (+184coverage,notaccuracy).
  38visibleactions21+17match,noextra/streetmismatch;sparse59fieldsallmatch.
  Fixed missingcenter and unknownROI mistaken permanent conflict; private ledger
  never published until fresh reconciliation. Newbank wager58 adds2reviewed2503
  glyphs,.90/.05unchanged,148oldchecks0regression. Sourcecenter nowlogged inV2.
  diagnostics aa8_unknown_audit_v5_logged:331actor-cuedUNKNOWN,107positive-special,
  cannot classify remainingunknown as normal/safe automatically. New BASE_VISUAL
  gate implemented separately; no realBASEPASS/freeze/holdout/device run yet.
  Newbank ece873a6c8eccc31ce6391d71abe6e33892027a7a221fa40c7bcfcc71c0eaf95.
  Final3083passed/1skipped/2dependencywarnings;full lint0 with existing recorder
  exclusion. Details docs/AA8-BASE-VISUAL-ITERATION-V5.zh-CN.md.
- **USER SCOPE UPDATE:** insurance/mushroom/bomb detailed rules and cash semantics
  deferred pending later evidence. Preserve templates, modal guards, unknown cash
  and source footage. Base ordinary-state and independent/hardware acceptance are
  still required; NOT a model freeze or release PASS. Scope profile/receipt added
  in base_visual_scope.json / aa8_base_scope.py, V2 visual_scope output. Unknown
  mode is not normal; no automatic frame exemptions or changes to full V1 gate.
  See docs/AA8-BASE-VISUAL-SCOPE.zh-CN.md.23focused tests passed; changed lint clean.
  Investigating ordinary-state gaps in existing1283UNKNOWN development frames.
- **LATEST V2 integrated_v3 / score_v3, PARTIAL:** 1260-1262 real development
  preroll plus3839scoredframes. Modal guard now drops ambiguous insurance-entry
  unmarked104: CURRENT38actions not39; visible21+17 matched,noextra/street errors.
  Sparse59fields match; causalwager2556candidate/1283UNKNOWN is NOT accuracy.
  Positivecash94/516/559/192 eachonce UNALLOCATED, no profit/rake/fee attribution.
  Main evidence docs/AA8-V2-INTEGRATED-STATUS.zh-CN.md. Do NOT burn fresh300-600
  holdout while known canonical-state/action gaps remain; V2 harness preparation
  only. No physical capture/reconnect verification or strategy launch performed.
  Final software check3045passed/1skipped/2dependencywarnings; full lint0
  (existingaa_record_session.pyexcluded); frozenV1 280files rehashed0changes.
- **ACTIVE V2 2026-09-09, NOT visual acceptance:** V1 independent sparse A/B
  review found stack/actor abstentions; 600-820s is now previously evaluated,
  never fresh V2 holdout. Reserve untouched300-600s with candidate_v2 split.
  V2 integrated center142-feature bank, coin-only smoothing, waiting cues,
  state adapter and causal wager ledger; latest development_v2 replay3839frames,
  39/39 actions with amounts, gold38visible+1unmarked104 matched, no extra or
  street mismatch; sparse59 fields match. Ledger2062candidate/1777UNKNOWN is
  coverage NOT accuracy. Keep original V1 files/freeze/results unchanged.
  Next: mode-boundary action reset and all-positive-cash UNALLOCATED ledger,
  explicit existing1260-1262preroll, rerun, freeze V2 then fresh whole-hand test.
  Full suite3012passed/1skipped/2warnings before these final pending fixes.
  No live capture or strategy started; physical chain test still needs user start.
- **ACTIVE 2026-09-09 comprehensive task, not finished:** latest integrated
  first_v5/second_v5 full3839frames complete. Manual sparse DEVELOPMENT gold
  comparison_v5 now actor11/11,hero12/12,board12/12,pot12/12,8-stackvectors12/12;
  this59field match is NOT independent or full temporal PASS. New s-component
  normalization+two-button Hero cue fixes2700/2850/3150; explicitwaiting_next2400
  template resolves current waiting-seatNA withouthistoryfill. Rootpipeline
  includes hand candidate, participation, card smoothing and spatial insurance
  +buyin overlay. Read hashes from reports, not old summary counts.
- **FROZEN candidate_v1** G:/PokerSense_private/aa8_candidate_freeze_v1/freeze.json
  SHA f3b55436de2ad21933b2561d921d72ba03aead23830b287dd9478bc68feaf696,
  280runtime/model/parameter/training files. DO NOT modify existing frozen source
  while independent boundary review runs. Isolated acceptance agent now doing
  holdout600-820 boundary-only sampling with checked --boundary-freeze; outputs
  explicitlyroleholdout, never relabeldevelopment. Root/tuningagents have NOT
  seen heldoutcard/actioncontent. Coarse44frames,census3potentialboundaries/2whole
  candidates pendingexactregistration. Only metadata shared back to root.
- New evaluation-only harness/dataset helper being authored AFTERbasefreeze but
  BEFOREprediction; mustrecord supplementaryhash/chronology, no backdating,
  no ASTexec, no inventorymonkeypatch/relabel. Existing frozenrecognizers/params
  unchanged. Isolated reviewer mustnotreadpredictions orsharevisualgoldwithtuning.
- Hardware validation still requires user's explicit newrecordingstart; async
  question requested phone+card ready inlobby/nonlive replay and phrase可以开始验收录制.
  NO recorder/device reopened orstrategy advice. Specialmodecash semantics,
  triggerpositiveevidence and independentacceptance stillNOTpassed.

- **IN PROGRESS 2026-09-09 comprehensive AA8 visual integration (user explicitly
  authorized parallel agents):** continuous-state, special-mode and independent
  acceptance workstreams implemented as new offline tools/tests/docs; root
  aa8_visual_pipeline integrates money,glyphs,actor/wagers,cards,participation,
  automatic candidate boundary and overlay guards. Not released or accepted.
- Completed full private aa8_integrated_first_v3/v4 (2057) and second_v3/v4(1782).
  Multi reviewed first-hand pot-prefix variants improve second knownpot994->1762;
  first knownpot2045. Coverage is NOT accuracy. Continuous4-frame inferred
  shortcall104 at4825 now uses AUTOMATIC actor/wager/cash evidence; remains
  CASH_SUPPORTED_SHORT_CALL_CANDIDATE, not legal-event truth.
- Automatic candidate newposts5051 confirmed5052, not potclear5036; manually
  bound secondhand3320-5050/1731frames registry aa8_second_hand_registry_v1.
  Source-slot1 refill192 remains unallocated, not profit. Full hand/cash state
  truth still incomplete. Root fixtures sparse12checkpointgold manually read
  without modelpredictions. V4 hero/board/pot12/12;actor8/11;stackvector6/12 due
  awaiting-seat6 NA unknown. Actor andWAITING_NEXT_HAND repairs being integrated.
- Cards opt-in gaussian_050 (uniform currentcrop, no threshold drop), unchanged
  existingWPKheads; development47card anchor reads47/47. Full sparsegoldhero12/12
  vs9/12 raw. Hash-pin aa8_card_preflight too. Not independent card calibration.
- Special3/5/7 insurancecountdowns and BUYIN_APPLICATION blockingoverlay positive
  samples discovered in late DEVELOPMENT820-995.366,36coarse frames;96coarse total.
  Added dense915-921/24frames: counter12->6 associated withnewposts,27cashdebit
  vs21pot leaves6 unallocated. No explicit critical-hit/mushroom trigger/payout
  semantics verified; do NOT guess fromcounter/rulelabels. Old failures retained.
- Acceptance/holdout freeze tools reject manual/UNKNOWN/overlap/missing evidence,
  includehero+boardidentities and contextualNA; no holdout600-820 read yet.
  No capture device, recorder, emulator or strategy started. Hardware end-to-end
  acceptance and full independent handgold still outstanding. Continue integration,
  do not equate these development candidates or software test counts with PASS.

- **2026-09-09 AA8 insurance false-raise + unmarked cash check:** aggressive now
  requires white 加注 text similarity>=0.80 as well as0.90 coloured badge. Source
  template remains1470/slot3. Full first2057 frames21/21,no extras; second1782
  frames17/17,no extras,投保6 no longer raises. Second hand is now DEVELOPMENT
  REGRESSION, not untouched generalization. Insurance semantics still unimplemented.
- New aa8_unmarked_money trains gray digits on first-hand reviewed checkpoints;
  auto target4822/23/24/25 stacks all eight read correctly, pot474->578,slot0
  104->0,others unchanged. V1 pot UNKNOWN retained; V2 prefix-disambiguation works;
  V3 confirms two stable frames each side. With MANUAL4755 actor0,price221,
  own-wager63 and reviewed single-action interval, conditional short-call104
  passes. Actor/context/window selection NOT automated, no invented All in glyph.
  Missing/invalid/multiple-change data abstains. No strategy eligibility.
- Private aa8_auto_actions_dev_v6,second_hand_transfer_v2/comparison_v2,
  aa8_unmarked_money_v1/v2/v3; docs/AA8-INSURANCE-GUARD-AND-UNMARKED-CALL.zh-CN.md.
  NEXT: automatic actor/street-wager context + continuous money/action integration;
  special modes and exact boundaries remain. No recording/device/holdout accessed.
  Verification: full2753 passed,1 skip,2 dependency warnings; changed-file lint clean;
  10 new tests. Real two-hand glyph reruns and four-frame cash OCR executed.

- **2026-09-09 AA8 frozen V5 transfer:** extracted ONLY new development window
  frames3320-5101 (1782); reused first-hand template masks/layout and0.90/2/5
  parameters unchanged, predictions do not read target labels. Source-disjoint,
  NOT independent holdout or blinded gold. Exact ending boundary still unregistered.
- Post-prediction review:17 visible glyph transitions all matched;1 false aggressive
  proposal4886 slot3 is orange insurance label 投保6 (full frame4890). Preserve
  failure; don't claim cross-hand PASS. Frame4823->4824 slot0 cash104->0,pot474->578
  jumps timer->revealed cards/insurance without visible All in glyph in4816-4831.
  This requires money/context action reconstruction, NOT invented glyph truth.
  Slot6 participates this hand despite waiting last hand; Hero-folded context kept.
- Tools aa8_action_transfer and7 input-guard tests; private aa8_second_hand_window_v1,
  transfer_v1/comparison_v1 and review sheets. See docs/AA8-CROSS-HAND-TRANSFER.zh-CN.md.
  NEXT: insurance-vs-raise rejection, unmarked monetary action reconstruction,
  exact boundary/cash registration. No reader tuning this turn, no holdout/live work.
  Verification: full2743 passed,1 skip,2 dependency warnings; changed-file lint clean.

- **2026-09-09 AA8 glyph V5 development hand closure:** all2057 existing frames
  processed;21/21 reference glyph events matched,0 missed,0 unmatched proposals.
  V4 matched21 but repeated slot1 all-in after3-frame dropout; V5 confirms2 frames,
  clears/rearms only after5 unknown frames. Per-frame UNKNOWN remains unchanged.
  Badge largest-component/bbox normalization and7x7 sigma1 smoothing; fold raw
  crop retained; all-in border-component removal plus additional frame3120/slot1
  template. Same0.90 floor, SAME DEVELOPMENT HAND template/parameter selection.
  This is NOT independent accuracy, legal actor or complete visual acceptance.
- Private aa8_auto_actions_dev_v4/v5 retained, diagnostic sheets v1/v2; updated
  docs/AA8-AUTO-ACTIONS-DEV.zh-CN.md. Full2736 passed,1 skip,2 warnings, changed-file
  lint clean;5 new tests. NEXT: freeze V5 templates/parameters for other development
  hands, compare predictions without injecting reference actions. No holdout,
  device, live advice or recording. Nine-slot combined-reader guard still intact.

- **2026-09-09 AA8 automatic glyph development baseline:** new offline
  aa8_action_reader processes all2057 existing owned frames with source hashes;
  five visible-label templates,2-frame transitions, one-to-one reference comparison.
  V1 matched11/21, missed10, no unmatched proposals; higher badge V threshold180
  V2 matched14/21, missed7, none extra, but regressed two slot5 calls fromV1.
  Preserve both failures. Templates/evaluation use SAME DEVELOPMENT HAND; these
  are NOT independent accuracy, legal actions, actor truth or visual acceptance.
- Remaining: slot5 preflop/flop calls,slot3 flop check,slots2/3 flop folds,
  slot5 turn check,slot1 river all-in. Do not relax thresholds just to pass.
  V3 same-parameter reproduction adds implementation/template-mask fingerprints.
  Private aa8_auto_actions_dev_v1/v2/v3, docs/AA8-AUTO-ACTIONS-DEV.zh-CN.md.
  Six new tests; full2731 passed,1 skip,2 dependency warnings. No device/recording,
  no holdout, no strategy; old nine-slot combined-reader guard retained.

- **2026-09-09 AA8 first-hand voluntary action reference:** reviewed existing
  development frames only; added21-action four-street reference and source-bound
  replay verifier. Turn1/4/5 explicit checks; river1 all-in214,4 short-call120,
  then5 fold (3166-3168,3170-3172 witnesses). Replayed pot623 and cash match;
  unmatched94 explains prior observed return; contested529, payout difference13
  still unallocated, NOT verified rake. Initial post/mushroom routing unresolved.
- Added private hash-checked AA8 action contact sheets, not model predictions.
  Blue Hero raise CONTROL is not an action; orange flop raise badge maps to bet;
  all-in Hero river maps to call. Frame windows are bounded observations, NOT
  exact first-visible timestamps or continuous actor truth. No recording started.
  See `docs/AA8-FIRST-HAND-ACTION-REVIEW.zh-CN.md`; NEXT: compare actual AA8
  automatic recognition against reference, then other development hands and
  independent acceptance. Full visual acceptance remains false. Verification:
  full2725 passed,1 platform skip,2 dependency warnings; changed-file flake8 clean;
  real private frame binding/replay passed.13 new action tests include wrong calls,
  waiting actors, omitted checks, future boards, false raises and reversed timing.

- **2026-09-09 AA8 first-hand cash review:** extracted all2057 owned frames
  to private aa8_first_hand_full_v1; ordered IDs and first/last PNG hashes match
  frozen registry. No calibration/holdout exposure or live capture.
- Reviewed8 monetary checkpoints,pots43/81/99/173/231/289/503/623; all seven-
  seat cash totals plus displayed pot plus hypothesized3BB*2=6 equal2162.
  Late waiting seat6 excluded. This supports observed consistency, not verified
  mushroom routing or ordinary-post decomposition.
- Source3180->3195 settlement: Hero0->516,opponent0->94,total credits610,
  pot623 difference13 unallocated; display components529+94=623. Starting to
  ending cash gap19 decomposes6+13 (algebraic identity, not independent proof).
  Hero200->516 matches+316 label; evaluator confirms5d6d beatsKh6h on5h6c6sTc3d.
  No rake policy, profitability or earlier-decision use of revealed cards claimed.
- Added source-bound verify_aa8_settlement and10 tests; full2712 passed,
  1 platform skip,2 dependency warnings; lint clean. Report
  `docs/AA8-FIRST-HAND-CASH-REVIEW.zh-CN.md`, private
  `aa8_first_hand_cash_checkpoints_v2`. Full action truth and automated visual
  extraction remain false. NEXT: exact checks/folds/order and complete reference
  action line, then AA8 automatic recognition comparison. Do not rerecord.

- **2026-09-09 AA8 first development hand registered:** development-only0-300s
  sampling (60 coarse points), entry/exit half-second refinement and36 dense
  boundary frames. No new recording or calibration/holdout tuning.
  First5d6d hand has exact visible-post ownership1263-3319 (2057 frames,
  PTS42.100-110.633), before-start1262 and next-post3320 bound to PNG hashes.
  Hero200->196 at first posts,516->514 at next posts; no fee/profit inference.
  Initial posting slots0/1/2/3/4/5/7;6 empty initially, waiting newcomer at end
  is NOT an opening opponent. Joining-hand post components remain unverified.
- Other candidates9dQd/2cTd/4cQd retain uncertain boundaries; explicit Hero fold
  images4351/5851 reviewed, top slot0 waiting at5851 must not be active by census.
  Registry repeat SHA97d8319d96506ad8681e6c7b3f13ff80cc0280f71c5e27da5081995f90cb5877.
  Boundary registration is not full state truth or independent acceptance.
  See `docs/AA8-FIRST-HAND-BOUNDARY.zh-CN.md`; private directories listed there.
  Full2702 passed/1 skip/2 warnings, lint clean. NEXT: full action/amount/settlement
  review of2057 owned frames, then AA8 recognition integration. Do not re-audit
  original source or repeat completed boundary extraction without a concrete need.

- **2026-09-09 AA8 recording baseline:** fully hashed/strictly decoded all17
  new segments,29865 frames exactly match recorder,5807664790B,995.366s.
  All frames1920x1080,monotonic PTS,no gaps>67ms; CSV/file list/start PTS match.
  This is integrity/timeline evidence, not black-frame/freshness/recognition proof.
  Private audit G:/PokerSense_private/aa_phone_audit_20260909_v1. Do not repeat
  hashing/full decode unnecessarily; reuse frozen hashes and frame_index.jsonl.
- Added separate8-seat candidate layout,top0/Hero4,using pre-recording reference
  SHA950c348258d2263defb4744605b2229121eb6d6eafc9c7857bf897a09769db2b.
  Old9-seat config retained. Combined legacy reader explicitly rejects8-seat
  input pending actual adaptation; don't describe draft geometry as recognition.
- Frozen AA8 split-plan candidate time ranges:development0-300,calibration
  300-600,holdout600-820,development820-end. Known preview60/840.023 in dev.
  Needs complete hand boundaries before assignment; no independent hand verified.
  No model tuning or recognition on new recording yet. See
  `docs/AA8-RECORDING-BASELINE-20260909.zh-CN.md`. Full2686 passed/1 skip/
  2 dependency warnings. No live recording restarted or strategy activated.
  NEXT: hand-boundary annotation/registration, then8-seat full-state development.

- **STOPPED 2026-09-09 03:27:06 Asia/Shanghai, user ended capture:** latest
  aa_phone_record_20260909_031030_54322c62 finalized via STOP/q, status stopped,
  user_stop,exit0; recorder40004/ffmpeg28356 no longer present.17 MKV files,
  5807664790 actual bytes, CSV end995.366s (~16m35s), FFmpeg reports29865 frames.
  Last segment starts960.005; its duration field995.366 is an absolute timeline
  end, not a995-second segment. Full decode/integrity hashing still pending.
  Files retained, no recognition/strategy was running. Do not restart recording
  without another explicit user start. Source is now available for offline work.

- **Historical start, now STOPPED: 2026-09-09 03:10:30 Asia/Shanghai:**
  G:/PokerSense_private/aa_phone_record_20260909_031030_54322c62.
  Recorder PID40004, ffmpeg28356, exec session38186 at launch. Verify current
  status/process identity before any stop. Graceful stop: create STOP in THIS
  session directory, not the earlier stopped test directory. User requested
  start and subsequent health check; no recognition/advice is running.
- Health check~03:11:56: status recording, video bytes increasing, second
  segment writing; first finalized segment60.000s/346730712B, MJPEG1920x1080
  30FPS. FFmpeg progress around68s reportsdup0/drop0 (not independent source
  freshness proof). Extracted frame from segment0001 shows full AA phone table,
  not black/logo. No second live device opened. No betting analysis performed.
  Limits remain1800s/about20GiB/20GiB free reserve. No auto-restart/scheduler.

- **STOPPED 2026-09-09 ~02:54:47 Asia/Shanghai:** user says they had not
  started playing and explicitly requests NO recording until they say start.
  Created STOP for aa_phone_test_20260909_0245; verified state=stopped,
  stop_reason=user_stop,exit_code=0 and recorder/ffmpeg PIDs no longer present.
  Five segments finalized, last CSV endpoint255.977s. Files retained, not
  deleted or treated as gameplay acceptance. Do not restart capture/recording
  automatically; wait for an explicit user start instruction.

- **Historical recording start, now STOPPED (see above), ~02:50:30:** user clarified this
  session is for video testing and later review, not consulting live advice.
  Started bounded phone-card video-only recording in
  G:/PokerSense_private/aa_phone_test_20260909_0245 (name is an identifier;
  actual timestamps are in status.json). Recorder PID16332, ffmpeg29796,
  exec session16892 at launch. Check status/process identity before acting.
  STOP safely by creating file STOP in THIS session folder; recorder sends q
  to its own ffmpeg and finalizes. Do not terminate unrelated capture processes.
  Limit1800s video, approximate20GiB bytes, stop below20GiB disk free,1s checks;
  wall-clock watchdog duration+20s and up to15s graceful finalization.
  No automation/scheduler created. Process runs until stop/limit/failure.
- Recording source UGREEN25854,1920x1080/30FPS MJPEG stream-copy, no audio,
  no new compression/cropping,60s MKV segments with CSV timestamps and progress.
  First completed segment verified60.000s /369567291B; screenshot from recorded
  file showed AA lobby. Later check2 files623846971B and recording status.
  No eight-seat recognizer or strategy running; do NOT claim synchronized
  recognition predictions exist. Preview/status checks are not whole-recording
  decode validation. Do not open a second live capture while recording.

- **2026-09-09 phone AA frame confirmed:** bounded single-frame capture now
  shows AA TABLE, not lobby, with complete portrait UI and black sidebars.
  Current visual layout has8 physical positions (one top,3 left,3 right,bottom),
  unlike prior AA nine-slot prototype's two top positions. Do not apply existing
  nine-slot geometry unchanged. User participation is UNKNOWN from this frame;
  lack of own hole cards/buttons is not proof of observing/folding.
  Source1920x1080/30FPS MJPEG; process exited, no strategy or game controls.
  Private frame G:/PokerSense_private/aa_lobby_check_ec201b0bfbb5482588083b60e55ebf13/aa_check.png.

- **2026-09-09 capture recheck after phone reconnect:** one bounded DirectShow
  frame after3s warmup now visibly shows the unlocked portrait phone home
  screen and AA Poker icon, centred with black side bars. UGREEN25854 stream
 1920x1080/30FPS MJPEG; capture process exited normally. Phone picture link
  is confirmed for this snapshot, NOT AA in-app recognition or long-run stability.
  Private frame G:/PokerSense_private/capture_recheck_b6903e50a7724f31960af0f3d2095c92/desktop_check.png.
  No ADB, gameplay, strategy or continuous recording. Next permitted basic
  check: user opens phone AA lobby; no need to enter a table for capture QA.

- **2026-09-09 phone capture connection check:** user reports platform confirmed
  phone+capture-card use allowed and emulator use disallowed; this is user-
  supplied policy information, not independent confirmation of RTA permission.
  Authorized bounded video-link check only, no strategy/gameplay/ADB actions.
  Windows/DirectShow enumerate UGREEN25854 OK; opened1920x1080/30FPS MJPEG.
  Two initial PNGs show black then UGREEN logo; an additional frame after5s
  warmup is black. Thus capture-device link works, usable phone/AA picture NOT
  confirmed. Capture process exited/released device. Private snapshots:
  G:/PokerSense_private/capture_check_20260909_1e41561e250e4e36bd9962289891fff1.
  Next: user unlock/keep phone screen on and verify video input/adapter/cable;
  test phone home screen before any gameplay. Do not call this a vision pass.

- **2026-09-09 platform warning supersedes emulator live-work plans:** user
  supplied AA dialog stating this table has a data-collection-software shield,
  claiming the user used such a plugin and prohibiting entry to this table
  category today; requests removal of third-party plugins and official client.
  This does NOT establish permanent account ban/deletion or identify a detector.
  Do not run further emulator capture/debug investigations or attempt repeated
  entry, concealment, fingerprint changes, component disabling or bypass.
  Keep current work offline; resolve applicable policy and restriction through
  official support before considering live integration. Prior ADB package/
  permission inspection and installed-APK copying occurred; causation is unknown.
  Firewall and filesystem privacy protections are not anti-ban measures.
- File-privacy batch immediately before warning: expanded .gitignore for
  media/APKs/credentials/databases/private dirs, preserving legitimate PNG assets
  and sanitized .env example filenames. Added read-only check_private_files tool;
  filename-only checks found0 flagged among446 current index /447 local history
  paths; no content/remote audit claimed.16 focused tests passed.
  Created new empty G:/PokerSense_private with protected ACL allowing current
  user, Administrators and SYSTEM only. No existing media moved or deleted.
  G:/PokerSense_archive retains broad inherited Users/Authenticated Users ACLs;
  not tightened pending explicit scope confirmation. No independent media backup
  created, no encryption or automatic cleanup, no old blocked-delete retry.

- **2026-09-09 AA/LD9 read-only package security audit:** exact connected
  emulator-5554; com.plusaa.amula1.9.1, target34 on guestAndroid9 reporting
  patch2019-07-05. Installer is Android package installer, publisher provenance
  not verified. Pulled only installed base APK temporarily for aapt manifest/
  FileProvider XML inspection; no private data, memory, traffic, root or bypass.
  Fine location granted; external-storage runtime denied despite AppOps allow.
  allowBackup=true but system backup disabled; usesCleartextTraffic=true does
  not prove actual cleartext sensitive traffic. Some components exported,
  providers checked not exported but sharing paths broad; no exploit claim.
  EmulatorCheckService declared: do not disable, spoof or infer exact ban rules.
  No app permissions/config/firewall/gameplay mutations. AA PID remained present.
  Report: `docs/AA-LD9-PACKAGE-SECURITY-AUDIT.zh-CN.md`.

- **2026-09-09 LD9 basic security follow-up:** added persistent inbound rules
  `PokerSense-LD9-ADB-Server-External-v1` (LD9 adb.exe TCP5037, nonloopback
  IPv4 plus2000::/3,fc00::/7,fe80::/10) and
  `PokerSense-LD9-VM-Debug-IPv6-v1` (existing VM program TCP5555/2222, same
  three IPv6 ranges). Original IPv4 VM rule unchanged. ActiveStore filters
  verified for all3;127.0.0.1 TCP5037/5555/2222 still connect; processes alive.
  Shared folders are dedicated nonlinked LD directories; inspected metadata
  only, not contents/subtrees. No8876/8877 listener observed at this check.
  No external-host ingress test, no game-login continuity claim, no clipboard/
  macro-state claim. No restart, client/device/identity change or anti-detection.
  Report and scoped rollback appended to
  `docs/LD9-BASIC-NETWORK-HARDENING.zh-CN.md`. Not a ban-prevention guarantee.

- **2026-09-09 user-authorized LD9 basic security:** inspected running LD9,
  verified1080x1920/DPI480/60FPS and rootMode=false without modifying VM config.
  VM process listened0.0.0.0:5555/2222; ADB server127.0.0.1:5037.
  Added one persistent Windows firewall rule
  `PokerSense-LD9-Block-External-Debug-TCP-v1`, scoped to
  `C:/Program Files/ldplayer9box/Ld9BoxHeadless.exe`, inbound TCP5555/2222,
  remote IPv4 ranges excluding127/8. ActiveStore filters verified; loopback
  TCP tests5037/5555/2222 succeed; processes still running. No remote-host
  ingress test, no IPv6-rule coverage, no macro-state verification claimed.
  No restart, AA login/account/gameplay/client modification, device spoofing,
  anti-detection or strategy activation. This is NOT a ban-prevention guarantee.
  Report/rollback: `docs/LD9-BASIC-NETWORK-HARDENING.zh-CN.md`.

- **2026-09-09 pot rejection repair v8:** centre coin uses source-template
  localization in combined reader; added reviewed1380 centre14 glyphs (bank52
  total), same.90/.05 gates. Wager numeric strip follows coin vertical bounds
  so grey preaction-button edge no longer clips Hero60. Title480 accepts a
  verified one-column blank separator after colon with background padding;
  no-separator still rejects. No arithmetic relabeling or holdout tuning.
- Same1801-frame replay: pot reconciliation4/11 ->7/11,4 still abstain at
  0(cold start),720(collection animation),1200(settlement evidence incomplete),
  1320(title0 vs14+2+4+8). Static title11/11; continuous title10/11 plus cold
  abstain. Cards36 correct/36 negative rejects, cash10 correct/1 abstain unchanged.
  Keep display-title truth separate from canonical pot truth in score reports.
- Full2656 passed/1 skip/2 warnings; lint clean. Evidence/report
  `docs/AA-POT-REJECTION-REPAIR-V8.zh-CN.md`. v8~85.76s with concurrent tests,
  not a performance calibration. NEXT: action/settlement evidence for remaining
  unreconciled amounts, full participation and special-mode automation, exact
  reserved-hand boundaries/independent acceptance. Four gates remain PARTIAL.

- **2026-09-09 requested all four gates / actual result still PARTIAL:** added
  separate centre-font bank (+13 reviewed glyphs from0/1050/8700/23640/32880,
  total50 including parent bank) with unchanged.90/.05 gates. Added nine-slot
  visible wager reader (coin side differs left/right; multiple coins reject;
  positive blank-green evidence only). Title need not equal centre: e.g.
  frame180 centre16 + visible2/4/8 == title30. Missing wagers stay unknown.
- Continuous1801 frames: pot correct1/11 v4 ->3/11 centre-font v5 ->4/11 v6/v6b,
  remaining7 abstain. Card slots36 correct/36 negatives and Hero cash10 correct/
  1 abstain unchanged. v6b~73.42s offline. These are development scores, not
  independent acceptance. No pass flags/production gates changed.
- Reserved boundary-only annotation saved48 samples, NO recognition/tuning on
  them. 2sJc interval2701-3599 continues into exposed3600;6h2d18001-18899 into
  exposed18900. Neither qualifies as a full reserved hand. Interval6301-7199
  has a possible complete2sQs hand (after6421 clearing, new backs6481, visible
  pair6901, still old hand7081 with approval overlay, next deal7141). Need exact
  post/settlement boundaries and census before registration; eligible count0.
  These frames must remain excluded from tuning, including newly reviewed images.
- Full2654 passed/1 platform skip/2 warnings, lint clean. Evidence/report:
  `docs/AA-WAGER-ACCOUNTING-V6.zh-CN.md`. NEXT: precise2sQs reserved boundaries
  (annotation only), complete pot/action/participation reconstruction and actual
  mushroom/insurance recognizers; no full-gate or strategy-ready claim.

- **2026-09-09 four-gate execution / dual-pot and Hero-turn v4:** added
  coin-prefixed centre amount observation, separate pot_title/pot_center and
  numeric agreement gate. Frame0 title30/centre16 and8700 title0/centre120 do
  not produce a merged pot;23640 centre90 and32880 centre329 still abstain.
  Equality is not canonical pot proof. This conservative gate regresses pot
  recall and must not be claimed as completed financial reconstruction.
- Hero-turn candidate requires three coloured active buttons plus current
  face cards, two sequential-frame confirmation and no current fold badge.
  Verified development positives1050/1110/29700, negatives0/8700/32820/40650;
  never infer observer from absent buttons. Legal actor/opponent turns remain open.
- Continuous1801-frame `combined_dual_pot_turn_v4`:~70.16s, unchanged card
  checkpoints36 correct/36 negative rejects, cash10 correct/1 abstain, strict
  pot1 correct/10 abstain.672 Hero candidate frames are NOT672 verified frames.
  All strategy flags closed. Full2650 passed/1 platform skip/2 warnings;
  see `docs/AA-DUAL-POT-TURN-V4.zh-CN.md`. NEXT: centre amount coverage and pot
  semantic reconstruction, full action/participation, mushroom/insurance,
  independent hand and stability acceptance. Four required gates remain partial.

- **2026-09-09 AA lucky-bomb title / posts v1:** new offline title detector
  scans1292 existing non-holdout samples, returns8640 and23610, both visually
  confirmed. Reference8640 is development;23580 glare phase not detected.
  No full-animation recall/false-positive rate or live wiring is claimed.
- Bound two contribution cases: BB4 six seats ->6*20=120 collected, new dealer6
  extra8; BB2 nine seats ->9*10=90, new dealer1 extra4. These extra debits match
  displayed mushroom2BB, not proven general rake. Second-case slot4 starting
  balance is obscured and stays unknown (do not invent200).
- Mushroom first case16->8 does NOT close as a simple deposit; prior winning
  frames8550/8580 still show16. Second56->60 matches extra4. Full mushroom
  routing remains unverified. At8700/23640 pot title0 lags collection120/90;
  keep these display sources separate in future canonical reconstruction.
- See `docs/AA-BOMB-POSTS-V1.zh-CN.md`, fixture `bomb_posts_v1.json`, private
  `bomb_title_v1` and `bomb_posts_pool_audit_v2`. Added4 tests; full2639 passed,
  1 platform skip,2 dependency warnings; lint clean. No strategy activation.
  NEXT: dense mushroom payout/reset/post window and dual-pot-display handling;
  continue full action/participation, independent hands and hardware gates.

- **2026-09-09 latest user correction: this AA recording has 种蘑菇, NOT 鱿鱼.**
  Current recorded-mode work is mushroom, critical-hit and insurance/settlement.
  Keep squid as separate future support, unverified; never alias mushroom to
  squid or keep mining this recording for an asserted squid instance.
  User requests inference/calculation from video, not waiting for rule screenshots.
  Record visible transactions and unallocated differences, not guessed fees.
- Pot candidate added: verified literal prefix + unique colon before gray OCR;
  source0/720 prefix variants, floor.90; static11 checkpoints10 correct/1
  clipped-digit abstain. AA branding-text backup to logo restores scene44/44
  development positives;2/2 non-table rejects. Not independent calibration.
- AA physical-seat candidate added (positive empty-plus or avatar+balance).
  Frame0 nine slots agree with8 occupied/1 empty;17100 and29700 each7 observed/
  2 unknown. Hero action-button replacement remains unknown. Never use physical
  occupancy as a dealt-in hand roster. Combined tool emits explicit semantics.
- Continuous1801-frame `combined_pot_brand_v2` / `combined_pot_seats_v3`:
  reviewed card slots36 correct/36 negative rejects, Hero cash10 correct/1
  cold-start abstain, pot9 correct/2 abstain. Hero presentation transitions now
  only152 Jc9h,1261 unknown,1433 Ac9c; prior4 spurious interruptions removed.
  Throughput v3~72.06s is offline, not hardware latency. Full fields still open.
- Read-only source-bound1s mode mining saved1292 frames (reserved intervals
  excluded),46 raw anchors match. `mode_diversity_v1` selects80 representatives;
  this is visual mining, NOT mode labels. Includes private identity/chat pages:
  never put raw images in repo/public artifacts. No source media changed.
- Located lucky-bomb animations8640/23580, insurance32820->32880->32910,
  mushroom hand-history34290 and No Signal40650. Insurance case has bound
  reviewed quote626/313/premium174/payout313/outs13, then 投保174, credits
  135+452+503=1090;1264-1090=174 and626-174=452. Window closes after premium,
  not a general rake formula. Independently enumerate40 possible rivers from
  cards visible by32880:13 outs exactly match listed outs; no actual river used.
  Display1.8*174=313.2 vs313 leaves0.2 rounding-policy uncertainty.
  Fixture `tests/fixtures/aa_reference_hands/insurance_32880_v1.json`, tool
  `verify_aa_insurance_case`, private `insurance_32880_audit_v1`. Manual visual
  labels plus automatic arithmetic, NOT end-to-end automatic insurance reading.
- Keep action_smooth_v2 as an experiment, default remains binary. On29700 still
 4/6 target accepts; on17100 accepts fold0/1/3, rejects fold5/6/7. Seats2/4/8
  show cards, not folds; don't label seat8 folded. Strategy remains closed.
  NEXT: full action/participation truth, mushroom/bomb contribution windows,
  insurance-region recognizers, complete reserved hands and long-run/hardware.
- Verification after this batch:2635 passed,1 platform skip,2 dependency
  warnings; full flake8 and git diff --check pass. No strategy/live activation.

- **2026-09-08 AA combined fields v1 (user requests all four gaps):** continue
  actual implementation, but all four acceptance gates remain PARTIAL. Never
  describe tests/static checkpoints as AA-ready or strategy-ready. See
  `docs/AA-COMBINED-FIELDS-V1.zh-CN.md` for exact unfinished items.
- AA own gray bank from reviewed frame0 plus previously bound1200/1320/1740
  Hero glyphs:29700 development stacks6/9 ->8/9 correct,1 abstain1054; no floor
  reduction (.90/.05). Fold/all-in text candidate only4/6 accepts on template
  frame29700,2 abstain; actor/full actions/seat census not completed.
- Dynamic-card first attempt regressed27 correct/9 abstain, failure retained.
  Nominal-first, image-only raised-top search fixes reviewed static72 slots:
  36 correct/36 negative rejects. Not independent acceptance.
- New AACombinedReader processes1801 genuine sequential frames, fuses cards
  with source lifecycle, per-slot ROI resets and current-frame amount/action
  consensus. Replay ~58.59s, repeat ~52.14s (not hardware latency). Saved
  observations are byte-identical SHA256
  7f86f4cd631dfae997b2fe7dc8ce42fda819f6b52d8b0127f56e6173e18161bc.
  Eleven reviewed points:27 correct card slots/9 abstain/36 negative rejects;
  Hero cash9 correct/2 abstain. Static success is NOT continuous success.
  Pot, seat_presence, current_actor, participation/full actions and special
  modes still incomplete; every output strategy_eligible=false.
- Reserved untouched-with-respect-to-tuning intervals2701-3599,6301-7199,
  18001-18899 in `configs/reproduction/aa_holdout_reservations_v1.json`.
  Training rejects these frames. No complete eligible hand has been verified;
  only full hands within one interval may qualify, not crossing exposed900-frame
  anchors. Do not sweep these intervals for development or tune on their output.
- Agent Reach/Exa search found generic/other-platform special-mode descriptions,
  not verified AA rules. Jina brand-domain read failed; web-reader unavailable.
  See `docs/AA-SPECIAL-MODES-EVIDENCE.zh-CN.md`. No invented mutual-exclusion,
  penalty, insurance or forced-post rules; no client login or media upload.
- Full2626 passed/1 platform skip/2 dependency warnings; full lint and diff checks
  clean. New research and candidate code remain local; heartbeat stays paused.
  NEXT: improve full fields/occupancy, continuous abstentions, mode cue mining,
  then reviewed complete reserved hands and hardware/long-run acceptance.

- **2026-09-08 AA geometry/card baseline v1:** independent nine-slot candidate
  (clockwise top-left0, Hero5), global card/pot/room-rule zones; NOT production.
  Scene probe43/44 table supports,2/2 non-table rejects;17100 logo obscured by
  collection chips abstains. Hero avatar is covered by action UI, so no census
  from that patch. Special-mode/participation fields remain UNKNOWN.
- Generalized VisualTimeline slot_count/hero_slot (default8/0 unchanged).
  Saved WPK399 observations replay to identical events and summary; original
  WPK labels/production heads hashes unchanged. AA timeline not yet integrated.
- AA bounded0-1800 extraction:121 samples/15-frame step, original pixel anchors
  0/900/1800 verified.11 displayed-card/cash/pot checkpoints frozen before model
  probing. Old-pair disappearance bracket1260-1320, new Ac9c visible1440; no
  exact hand boundary or complete-hand truth is claimed.
- Static WPK-head transfer on72 scored slots:33 correct,1 wrong,2 abstain,
  32 negative rejects,4 card-back false accepts. AA face-background/top-crop
  gate yields33 correct,3 abstain,36 negative rejects,0 wrong/false accepts on
  SAME development points. Preserved failure; no new model or lowered floors.
  Raised winning cards currently abstain; no dynamic-card tracking yet.
  See `docs/AA-GEOMETRY-CARD-BASELINE-V1.zh-CN.md`; private directories recorded
  there. NEXT: exact transition boundaries, moving-card/AA glyph coverage,
  nine-slot fields/participation, explicit special-mode evidence. No readiness.
- Verification: full2612 passed,1 Quartz skip,2 dependency deprecation warnings;
  full flake8 clean and git diff --check passes. No live pipeline activation.

- **2026-09-08 latest user priority: AA PRIMARY, WPK REGRESSION ONLY.**
  This supersedes older WPK-first / AA-phase-two sequencing below.
  Follow `PLAN-AA-vision-first.zh-CN.md`. Reuse existing AA FFV1 footage;
  independently measure nine physical slots, normalization and AA field art.
  Do not inherit WPK geometry/calibration or claim occupied == dealt players.
  Strategy and real-play activation remain deferred; heartbeat stays paused.
  AA source audit starts with immutable originals and separate derived evidence.
  Completion notification requires AA_VISION_READY_FOR_STRATEGY / needs_review,
  not sparse screenshot success. Existing WPK evidence must be preserved.
- AA user scope addition: both 暴击 and 鱿鱼游戏 require explicit visual
  coverage and later dedicated rule/strategy support. Distinguish room-enabled,
  hand-triggered and settlement evidence; unknown is not ordinary mode.
  Do not invent mechanics from names or equate a settings caption with a trigger.
- AA source audit v1 complete: original SHA256
  2638c3ea894fa6a342947b9c4a06b5d7746a6512360f4ef7d79a387fe89da82f;
  41339 sequential frames, header count matches, no nonincreasing OpenCV times.
  46 source-bound exploration samples and candidate498x1080 crops; no AA truth,
  training, independent acceptance or production calibration yet. Lobby10800
  and non-table40500 are negatives, not crop shifts. See
  `docs/AA-SOURCE-AUDIT-V1.zh-CN.md`. Source tests plus full suite passed;
  later exploration tests/focused lint passed. NEXT: hand/scene/mode truth and
  nine-slot geometry. Do not repeat completed source hashing/full decode.

- **2026-09-08 Td3h causal evidence timeline:**399 owned PNG frames now feed
  CombinedVisionCandidate then new `state_engine/visual_timeline.py`, without
  passing reviewed actions/roster/future money into inference. Two-frame evidence
  confirmation, bounded12-frame unique debit/badge pairing, persistent badge/fold
  deduplication, gap reset and nonopening-seat exclusion. It emits observational
  TimelineEvidence, NOT canonical StateEvents or a verified betting ledger.
- First11/14 ordinary actions improved to14/14 with unchanged truth after an
  opt-in±5% badge-size tolerance and a reviewed source001 check-badge variant;
  0.85/0.10 gates unchanged. Three old action groups have no new errors/lost
  correct accepts. Target remains development, not independent validation.
  Seat6 vacancy never becomes an invented fold; newcomer5 never gets a hand
  action; Hero is folded, observed roster0/1/2/4/6/7 correct. Cash146->240 is only
  net+94, not an inferred fee/refund decomposition. Repeated same-kind/new-debit
  ambiguity still needs betting context, and forced posts are not fully sealed.
- Added17 tests; full2581 passed/1 Quartz skip/2 dependency warnings, lint clean.
  Repeat report and observation JSONL are byte-identical; no extra independent
  samples are claimed from this reproduction.
  Report `docs/WPK-TD3H-VISUAL-TIMELINE.zh-CN.md`; private `td3h_timeline/final_v1`.
  All release/canonical reconstruction flags remain false; default production
  configuration/weights and original labels unchanged. Heartbeat stays paused.
  NEXT: reconcile visual evidence with forced-post/departure/collection/refund
  rules and broaden hand coverage. Do not mark full_action_truth_ready true yet.

- **2026-09-08 true-hand registry v1:** froze3 reviewed ownership intervals:
  six-player Td3h1197-1595 (current reconstruction development target), eight-
  player AcQh8376-8835, seven-player4sJd BOMB POT10872-11315 (regression).
  Adjacent before/after-post frames are boundary context, not scored/training
  frames. Full Td3h401 PNGs contain399 owned frames and2 sentinels; all owned
  file/pixel hashes checked. Hero dims1291, definite fold1293; retain post-fold
  play, departed seat6 and waiting newcomer5. Full action truth remains pending.
- Registry validates ownership overlap, duplicate ids, boundary anchors and
  known train/calibration/development exposure. All3 have known exposure; clean
  whole-model independent acceptance count remains0. Another Tc3d candidate
  also hits train lists. Existing hand_0100 spans beyond Td3h into next hand;
  never split solely by legacy names. Seven-player special mode is not ordinary
  seven-player acceptance. No classifier was scored during this registry work.
- Actual current code/config/model snapshots and hashes frozen under private
  `hand_registry/frozen_delivery`; report `docs/WPK-HAND-REGISTRY-V1.zh-CN.md`.
  Added15 tests; full2564 passed/1 Quartz skip/2 dependency warnings, lint clean.
  Original labels/weights unchanged; heartbeat remains paused. NEXT: label
  Td3h event/state truth then automatically reconstruct its399 owned frames,
  while independently tracing provenance/reserving genuinely eligible hands.

- **2026-09-08 immediate execution / gray banks and combined vision:** user
  rejected scheduling; heartbeat pokersense is PAUSED and must stay paused.
  Rebuilt session001-only source gray bank:60 proposals visually audited,51
  retained,9 rejected including mislabeled4/5 and Chinese two-pair text. Full
  source images confirm174 vs old173 and255 vs old266. Original labels unchanged.
  Stack bank NPZ rebuild byte-identical;51 real glyphs ->765 augmented vectors.
  Separate pot bank has33 reviewed source001 glyphs, with147/72 supplements.
- New normal-package GrayAmountRecognizer implements AmountRecognizer, with
  0.90 top score/0.05 class gap and explicit ambiguity/crop/punctuation rejection.
  Session002 checks: stacks33->62/63;12->23/23;10->22/22; later four-frame check
  19->29/31. Waiting200 now reads; layout13/13 visible numeric values correct.
  No measured false accepts. These overlapping/development checks are not full
  independent-hand acceptance; original legacy labels have demonstrated errors.
- Offline CombinedVisionCandidate routes cards, amounts, actions, layout and
  existing occupancy/dealer/actor/street through one VisionEngine. Dedicated
  pot bank fixes the original5 numeric points, including visible156 at8560.
  Source8360-8845:486 sequential frames; checkpoints hero12+board16 correct,
  28 absent card slots rejected, stacks62/63, pot5/5, actions34/35. 404 frames
  have8 numeric slot values, NOT404 fully ground-truth-verified states.
- Source1180-1240:61 frames; six occupied seats at actual1220 (not nominal1281)
  have6 correct stacks,2 empty rejects,18 pot,Td3h, correct occupancy/dealer2.
  Added positive green/ribbon scene support and full temporary-state clearing;
  all34 deduplicated legacy menu candidates reject (not new gold labels).
- Added23 tests; full2549 passed/1 Quartz skip/2 dependency warnings; lint clean.
  Production weights/labels unchanged; no strategy, real-play or default UI
  activation. All combined results remain release_eligible=false and calibration
  unverified; production action/card gates stay closed. Report:
  `docs/WPK-GRAY-BANK-COMBINED-VISION.zh-CN.md`; evidence `gray_amount/` and
  `combined_vision/aq_guarded`, `six_seats_guarded`. NEXT: independent calibration,
  participation eligibility, event/state reconstruction, UI and long-run gates.
  Visual subsystem remains PARTIAL; do not announce VISION_OFFLINE_READY.

- **2026-09-08 user priority lock:** finish the WPK visual subsystem first;
  strategy development is deferred, real play requires a separate decision.
  Use `docs/WPK-VISION-ACCEPTANCE.zh-CN.md` and `docs/WPK-VISION-WORKQUEUE.zh-CN.md`.
  Do not mistake offline-ready for independent real-play readiness. Continue
  actual video-first implementation, not repeated planning-only status turns.
  Next concrete item: source-audited grayscale digit templates/amount coverage.
  Completion requires the documented independent coverage, integration and
  offline long-run gates; then notify and stop at needs_review. Keep original
  data, dirty worktree changes, production safety gates and isolated runtime.
  User rejected scheduled work and requested immediate current-turn execution.
  Heartbeat `pokersense` was verified PAUSED; do not recreate/resume scheduling.
  Continue implementing in this conversation. Do not stop at a planning-only
  update or imply work will continue invisibly after the reply ends.

- **2026-09-08 Hero balance location v1:** offline positive capsule-edge selector
  chooses lower(y1056) or raised(y937) without reading numeric centre or missing
  action buttons. Both signals -> CONFLICT, neither -> UNKNOWN. Composition
  reads only the current selected crop through existing amount recognizer/gate;
  no stateful carry, participation inference, playable-cash claim or live wiring.
- Original13 visual checkpoints:13 layout correct, amounts6->7 correct. New82
  sequentially extracted frames in two intervals:10530-10580 and10860-10890.
  Manual crop review confirms upward move10542, downward10871. Dense82 rescore:
  65 layout correct/17 abstain/0 wrong;10874-10890 dims with BOMB POT animation.
  Do not treat sampled10900 recovery as its exact first recovery frame.
- Dense amount reads14->31 correct,51 abstain. All17 additional accepts are
  displayed0 from buy-in/approval states, NOT usable stack or equity evidence.
  Waiting200 still fails original digit gate.13+82 reviews overlap4 frames;
  183 unique source frames processed,91 unique visually scored frames. Dense
  labels were reviewed after first probe; this is development, not holdout.
- Added15 tests; full2526 passed/1 Quartz skip/2 dependency warnings, lint clean.
  Evidence `hero_layout/coarse_final`, `dense_final`; report
  `docs/WPK-HERO-BALANCE-LAYOUT.zh-CN.md`. Production assets/gates unchanged.
  Next: independently sourced gray digit templates and opponent all-in variants;
  keep geometry, visible digits, actual participation and usable cash separate.

- **2026-09-08 field features v2:** offline action masks now use3x3 sigma0.7
  smoothing; yellow all-in masks additionally use5x5 top-hat >20 to suppress
  broad glow. Same0.85/0.10 engineering gate, not a calibrated probability.
  No new action templates, source-seat remapping, production changes or events.
- AcQh action checkpoints improve20->34/35 correct,1 abstain,29 negative rejects.
  Prior followup improves4->7/7 with17 negative rejects. Three newly action-
  reviewed frames10700/11050/11250 improve2->10/11 with13 negative rejects;
  remaining11250/seat6 all-in stays out (~0.704). No false accepts in these
  measured slots. Development includes template sources; all later frames have
  prior card-development exposure, so not independent project holdout.
- Numeric binary-feature experiment was NOT adopted: first12/63 correct, then
  removing old template uniform letterbox improves21/63 but still below v1's33.
  Prior followup11/23 vs v1's12; new check7/22 vs v1's10. All other positives
  abstain, negatives reject. Keep v1 stack candidate; do not lower gates or
  conceal failed prototypes.10700 waiting Hero balance200 moves to y937, outside
  bottom y1056 ROI; source layout needs explicit recognition, not inferred cash.
- Added13 tests; full2511 passed/1 Quartz skip/2 dependency warnings, lint clean.
  Report `docs/WPK-FIELD-FEATURES-V2.zh-CN.md`; private evidence
  `field_candidates/features_v2_final` and `features_v2_transfer_final`.
  Next: independently sourced opponent all-in/font variants, grayscale digit
  template provenance and waiting/active layout selection. Production remains
  requires_revalidation=true and no full action timeline acceptance is claimed.

- **2026-09-08 offline field candidate v1:** added eight-slot two-zone action
  candidate (badge for bet/call/check/raise, avatar for fold/all_in). New masks
  are source-bound to AcQh8500/8700; 0.85 floor/0.10 gap are engineering choices,
  NOT production calibration. All code/geometry stays in offline tools/fixtures.
  Old production ACTION ROIs and gates are intentionally unchanged.
- AcQh96 cached samples/8 checkpoints: actions20 correct/15 abstain/29 negative
  rejections (including template-source frames, not holdout). Same recognizer/
  gates with tighter stack crops improve21->33 correct out of63;30 abstain,
  masked negative rejected. No prior accepted checkpoint stack regresses.
  Visual crop audit confirms old slots2/5 clip digit tops; slot7 includes a
  pill edge that collapses segmentation. Correct raw text below gate stays out.
- Frozen later10400/11000/11340 transfer check: actions4 correct/3 abstain/17
  negative rejections; stacks5->12 correct out of23,11 abstain/1 negative reject.
  No false accepts in measured points. These are prior card-development frames,
  NOT untouched project holdout. Placeholder0 at11340 slots4/6 is only visible
  text, not proof of usable stack/participation. No action events emitted.
- Added11 tests; full2498 passed/1 Quartz skip/2 dependency warnings, lint clean.
  Evidence `field_candidates/v1_final` and `followup_verified`; report
  `docs/WPK-FIELD-CANDIDATE-V1.zh-CN.md`. Production weights/gates unchanged.
  Remaining: dim fold glyph variants, opponent all-in effects, stack segmentation/
  template robustness and independent calibration; temporal event wiring stays
  blocked on measured field coverage, not on lack of more live recordings.

- **2026-09-08 observation-field baseline:** added a source-bound production
  VisionEngine probe with frozen source/config and screen-only truth.96 unique
  cached frames processed,8 visually reviewed checkpoints/136 field checks;
  no raw-video redecode, continuous event reconstruction or independent holdout
  claimed. Pot3 correct/2 abstain plus3 negative rejections; stacks21 correct/
  42 abstain plus1 masked rejection; actions35 abstain/29 negative rejections.
  No false accepts in those checkpoints, but coverage is not release-ready.
- Concrete gaps: ACTION ROI lacks slots6/7, templates lack fold/all_in, and
  action calibration is absent. Raw candidates never become accepted actions.
  Added15 tests; full2487 passed/1 Quartz skip/2 dependency warnings; lint clean.
  Repeated96-frame run produces byte-identical report. Production assets and
  requires_revalidation unchanged. Report `docs/WPK-OBSERVATION-FIELDS.zh-CN.md`;
  private evidence `observation_fields/aq_measured_v1`.
- Important evidence erratum: f8560 ribbon actually displays156, NOT218.
  The legacy raw_total_pot218 is the reviewed logical post-call target. Old
  fixtures/reports preserved; new screen truth separates it, checkpoint helper
  docs/new CLI metadata no longer imply simultaneous displayed-money parity.
  Prior5 checkpoint checks are logical, not5 direct screen agreements. Final
  346 gross/324 visible/22 unallocated settlement findings remain unchanged.
  Next: offline eight-slot action regions/fold+all-in templates and calibration,
  stack crop/segmentation diagnostics, then causal state-event integration.

- **2026-09-08 reviewed hand completion v1:** continued the same PokerKit betting
  session through single-board runout, showdown, gross awards and separate cash
  observations in `state_engine/reviewed_completion.py`. AcQh now has30 logical
  states (19 betting+11 completion); all serialize/deserialize unchanged.
  Project independent evaluator/side pots agree with PokerKit: Hero gross346.
- Sequential cash review8780-8845 confirms Hero324 first visible8793 in that
  interval, seat6 refund balance238 directly visible8833-8835, and all8 balances
  visible8835. Next-hand ante starts8836 and is rejected as this hand's fee.
  Net22 outflow remains unallocated; insurance notices are not transactions.
  These are visibility boundaries, NOT server transaction times or latency.
- 21 original+9 supplemental image references (27 unique frames) are bound by
  file/pixel hashes. Full2472 passed/1 Quartz skip/2 dependency warnings; lint
  clean. Twelve new tests include synthetic distinct main/side-pot winners and
  exact splits; unsupported odd chips/multi-board/external inflows fail closed.
  Original input, labels and production weights unchanged; requires_revalidation
  remains true. No Frozen Core enum or live event-store integration changed.
- Report: `docs/WPK-REVIEWED-HAND-COMPLETION.zh-CN.md`; private output
  `state_replay/completed_aq_v1`. Reviewed completion PASS; fee attribution,
  automatic OCR-to-state and strategy acceptance remain PARTIAL/unverified.
  Next: measured action/stack OCR integration and causal state comparison on
  existing videos; do not invent missing multi-action sequences. The earlier
  state-ledger entry below describes the preceding betting-only milestone.

- **2026-09-08 reviewed state ledger v1:** added offline
  `state_engine/reviewed_replay.py`: reviewed action line -> PokerKit legality ->
  immutable core PokerState snapshots.13 player actions pass existing project
  action reconstruction; forced posts/collections/refunds are separate ledger
  entries, NOT new Frozen Core event enums or automatic live event-store writes.
- Source-bound AcQh case:21 image references verified,5 money checkpoints checked,
  19 logical states roundtrip through core serialization. Raw last-call pot584
  is preserved before a distinct238 return yields346. Rules-derived refund
  balance is NOT the screen's exact credit time. Antes are hand, not street,
  commitments. Every betting state conserves initial chips2644.
- Prefix through action12 computes conditional64 call ->346 eligible pot,
  238 return, fee-free32/173 threshold without consuming later actions, opponent
  cards, river or settlement. Settlement remains PARTIAL: observed324 relative
  to logical refund balances,22 unallocated net difference; insurance12 is a
  notice, not an assumed debit. River/showdown/gross award are NOT replayed yet.
- 29 new tests cover inconsistent evidence, exact money, visibility/prefix safety,
  6/7/8-seat synthetic main60+side80/return40, and explicitly mapped UTG straddles.
  Unknown straddle position and other variants fail closed. Full2460 passed,
  1 Quartz skip,2 dependency warnings; lint clean. Report:
  `docs/WPK-REVIEWED-STATE-LEDGER.zh-CN.md`; private final output
  `state_replay/reviewed_aq_final`. OCR-to-state and strategy acceptance remain
  false. Next: runout/showdown/payout/cash-observation events, then measured
  action/stack OCR integration without inventing missing multi-action sequences.

- **2026-09-08 V9 identity consistency:** an accepted current-frame card that
  contradicts accepted fused history now causes abstention and reseeding from
  the current frame. Same heads/floors; no rank-specific mapping or retraining.
  Uncertain current reads do not invent a conflict; correlated model errors
  are still possible. Production acceptance remains closed.
- Controlled no-gap splices of reviewed crops: first12 cases, V8 outputs the old
  card on all144 post-switch observations; V9 has120 correct/24 abstain/0 wrong.
  Remaining26 cases (same development crop pool) have260 correct/52 abstain/0
  wrong. These are artificial swaps, not38 independent recorded hands.
- Normal111+8 checkpoint scores unchanged, but full traces differ. Pixel review
  of all12 changed-output frames confirms V8 errors at11148(Qc->Tc),14931(5s->Ts)
  and15451(As->Ks); V9 abstains on the first and corrects the other two. Across
  58 positive slots in these selected frames: V8 44 correct/3 wrong/11 abstain;
  V9 37 correct/0 wrong/21 abstain. Nine formerly correct reads temporarily
  abstain. This difference-directed audit is development evidence, not holdout.
- CaptureCardBackend now exposes passive PixelRepeatEvidence (counts/time/pixel
  changes), always source_freshness=UNKNOWN. It neither rejects legitimate
  static frames nor treats advancing host ids as proof of source freshness.
  No independent device/app heartbeat exists in this path; hardware freshness
  remains unresolved. Diagnostics are not yet wired to the UI.
- Full2431 passed/1 Quartz skip/2 dependency warnings, lint/diff clean. Evidence
  private corpus `handoffs/`; report `docs/WPK-V9-HANDOFF-REVIEW.zh-CN.md`.
  Next: complete hand/action/stack/main-side-pot state traces; source freshness
  requires independent signals and final hardware evidence, not more pixel
  threshold tuning. Original labels, media and production weights unchanged.

- **2026-09-08 V8 continuity protection:** VisionEngine now forwards optional
  frame/source/time/ROI lifecycle to fused recognition; recording wrappers also
  forward it. Frame gaps/duplicates, backwards or >budget timestamps, source/
  canvas/layout changes reset evidence; missing/moved ROIs reset only their group.
  A slot cannot accumulate twice in one frame or bridge missed invocations.
  `card_fused.max_frame_gap_seconds=1.0` is an engineering budget, not hardware
  calibration. Direct crop-only diagnostics do not prove lifecycle protection.
- Source exceptions invalidate visual/consensus temporary evidence and latest
  confidence/equity without erasing canonical history. Desktop retry loop clears
  cached advice and emits an unavailable snapshot before backoff after any prior
  frame; the notification reuses the last capture frame id, not a fabricated one.
- 6 fault-injection scenarios on reviewed source11340 pass V8; V7 baseline fails
  the fresh-evidence recovery requirement. This repeats one real image with
  injected metadata, NOT observed hardware outages. Normal1101+2551-frame replay
  traces are byte-identical to V7, with original111+8 visual checkpoint scores.
  Replay timestamps now use container PTS, never processing wall time; container
  time is not the phone wall clock or true capture latency.
- 24 new tests; full2420 passed/1 Quartz skip/2 dependency warnings, lint/diff
  checks pass. Evidence under private `interruptions/`, report
  `docs/WPK-V8-CONTINUITY-REVIEW.zh-CN.md`. Production remains closed and weights
  unchanged. Next: similar-card changes with no observable gap, source sessions/
  hidden stale device buffers, then complete action/stack/pot state reconstruction.
  Browser/network-loss and real capture-card reconnection acceptance remain open.

- **2026-09-08 V7 transition/freshness repair:** failed current rank/suit/colour
  extraction now clears fusion history; adapter respects failed ingest. Missing/
  empty/non-BGR crops abstain, changed crop shape starts a new window.6 regression
  tests fail on old code and pass after repair. This is a demonstrated code risk;
  the examined real window did NOT exhibit stale accepts before the repair.
- Source10400–11500:1101 continuous frames,111 visually reviewed checkpoints.
  V6 baseline andV7 traces are exactly equal: hero144 correct/6 abstain/0 wrong,
  board266 correct/11 abstain/0 wrong;72 empty/unreadable hero slots and278 board
  slots have no false accepts. All-frame accepted-without-current-glyph count0
  in both versions. V7 original-batch03 regression:2551 frames, original8 points,
  hero15 correct/1 abstain/0 wrong, board20 correct,20 empty board slots correct.
- Dense31-frame follow-up at11310–11340 confirms old cards clear on11316;
  partial new deal11328, full7s/2c accepted11332. Dense review rescores saved
  predictions, not a new independent holdout;4 points overlap main review.
  BOMB POT overlay observed10880/10890, rules still unknown, no rule invented.
- `RealtimePipeline.latest_analysis()` now returns the last per-frame presented
  snapshot, separate from cached computations.2 tests pin current UNKNOWN/guard
  results and recovery without corrupting equity cache. No production caller
  of this accessor was found; this fixes its contract, not a witnessed UI bug.
- Full regression2396 passed/1 Quartz skip/2 dependency warnings; Flake8 passes.
  See `docs/WPK-V7-TRANSITION-REVIEW.zh-CN.md` and private corpus `transitions/`.
  Production weights unchanged, v7 candidate requires revalidation and remains
  closed. Next: broader interruptions/ROI loss/similar-hand transitions, then
  actual action/stack/pot/participation state traces. Latest-snapshot fix has
  synthetic pipeline evidence, not full real-video state reconstruction.

- **2026-09-08 isolated V6 reproduction PASS:** new interpreter
  `C:/Users/Administrator/.codex/runtimes/pokersense-v6-clean-20260908/Scripts/python.exe`.
  Use it for subsequent WPK training/replay/tests with `PYTHONPATH=src`,
  `PYTHONUTF8=1`, `PYTHONNOUSERSITE=1`; do not add shared site-packages.
  One OpenCV distribution (contrib4.10.0.84), numpy2.3.5, Python3.13.14.
  Loaded cv2.pyd matches prior actual bytes and wheel RECORD. Shared WorkBuddy
  packages and application release pins are unchanged. Do not install default
  project extras here: this is a historical candidate reproduction environment.
- Regenerated2150 training inputs and weights are byte-identical to V6 baseline;
  original frozen-source batch03 replay has exactly identical checkpoint fields,
  scores and summary. This is environment reproduction, NOT additional holdout
  evidence. Production card acceptance remains closed.
- Fixed training inventory/development-freeze tools requiring the wrong OpenCV
  distribution metadata; clean contrib-only env now works. Runtime isolation
  and exact NPZ/replay comparison have10 new tests. Clean full regression:
  2388 passed/1 Quartz skip/2 dependency deprecation warnings; Flake8/diff checks
  pass. Initial failing clean test XML preserved alongside successful rerun.
- Reproduction locks in `configs/reproduction/`;37 wheel archives (120471495B)
  hash-verified and retained in private `reproduction/v6_clean_20260908/wheelhouse`.
  See `docs/WPK-V6-CLEAN-REPRODUCTION.zh-CN.md` and private `verification.json`.
  Next: empty/dealing/hand-transition temporal negatives, then full state-chain
  evidence. Hand-level independence, live hardware and strategy gates stay open.

- **2026-09-08 V6 reproducible rank candidate:** reviewed91 unique session_001
  rank crops (212 origins), approved86 across all13 ranks and rejected5 clipped/
  contaminated crops. Training uses only session_001; synthetic same-glyph
  fusion yields2150 inputs, not2150 real observations. New64-hidden rank MLP,
  seed7; repeated training produces identical arrays and NPZ hash
  `ba73c17601a37f53726cf78da5954e7818ded452a3362059559bef7449693d1a`.
  All10 suit arrays remain unchanged; production weights are NOT replaced.
- V6 batch02 original-floor continuous development test fixes both red6 errors
  (boards32/32) but misreads folded5c as6c. First FAIL is preserved. A declared
  .05 grid using batch02 only selects offline rank-floor0.50: saved-score
  calibration projects21 correct hero/1 abstain/0 wrong and32 correct board.
- Third batch, frozen BEFORE inference: continuous14500–16900 (2401 frames),
  8 visual checkpoints, hero15 correct/1 folded abstain/0 wrong, required6/6;
  board20 correct/0 wrong, required8/8; empty board slots20/20. PASS for this
  limited candidate batch only. Frame14500 continues the previous QhTc hand
  and is warmup only. Legacy suit training overlap and hand boundaries remain
  unverified; no empty-hero checkpoints in this new batch. Production stays
  `requires_revalidation=true`; this is not full-state/strategy acceptance.
- Artifacts: private corpus `training/rank_v6_source001_frozen`,
  `rank_v6_candidate_frozen`, `rank_v6_candidate_repeat`, and validation
  `v6_batch_02_development`, `v6_batch_03`; see
  `docs/WPK-V6-RANK-TRAINING.zh-CN.md`. Full regression2378 passed/1 Quartz skip,
  Flake8/diff checks pass. PokerKit unknown burn handling is now deterministic.
- Runtime audit found overlapping OpenCV distributions: actual cv2.pyd matches
  opencv-contrib-python4.10.0.84 RECORD, not installed opencv-python5.0.0.93
  metadata. Actual numpy2.3.5/OpenCV4.10 differs from project pins. Training
  runtime text is metadata inventory, NOT a clean install lock. Fingerprint
  retained under private `training/runtime-fingerprint.json`; shared Python
  environment unchanged. Next: isolated runtime reproduction, then broader
  negative/transition/full-hand evidence and state-chain work. Never claim
  86 crops or35 accepted card checkpoints prove production-level reliability.

- **2026-09-08 V5 contrast repair and rank audit:** integrated 5/95 percentile
  glyph contrast normalization before fixed-height centroid placement. Flat/
  low-contrast glyphs abstain; source arrays remain untouched. Batch-02 remains
  DEVELOPMENT: continuous frames10700–14100, 12 corrected visual checkpoints
  now have hero21 correct/1 abstain/0 wrong (required6/6); boards30 correct/
  2 wrong (required10/12). All30 absent slots stay absent. Overall FAIL;
  `requires_revalidation=true`, weights and decision floors unchanged.
- Rank-only diagnosis reproduces both red6->5 errors without temporal fusion.
  Their normalized features are identical. +/-1px width experiments flip
  multiple sixes between5/6 with high margins; do not deploy a width hack or
  a5->6 mapping. Existing private script trains suit heads only; exact rank
  training/export provenance was not found in the searched repo/archive
  scripts/logs. Old feature collection contains the now-fixed v3 fusion bugs.
- Tools: `replay_wpk_card_development` preserves parent results and snapshots
  source/config/tools before continuous replay; `diagnose_wpk_rank_features`
  writes private glyph-only evidence. Outputs live under private corpus
  `validation/v5_batch_02_development` and `v5_rank_diagnostics_aspect`.
  The former snapshot retains pre-report calibration metadata (v4 label),
  but contains the actual v5 normalizer; only descriptive metadata was updated
  afterward. Next: reproducible rank-feature dataset/trainer with reviewed
  hand-disjoint splits, then third-batch validation. Do not spend the remaining
  new batch on tuning known batch-02 errors. Full regression:2364 passed,
  1 Quartz/macOS skip; Flake8 and git diff --check pass. Original batch and
  new evidence manifests verify; parent corpus manifest refreshed.

- **2026-09-08 V4 batch-02 evaluation:** 12 visually frozen checkpoints were
  scored during continuous frames10700–14100 (3401 frames). First results
  are retained under the private corpus `validation/v4_batch_02`. One manual
  suit label was corrected from Kd to Kh with source-pixel evidence; saved
  predictions were rescored without rerunning/changing the model. Corrected
  V4: required live hero checkpoints6/6, but 3 wrong accepted dim hero cards
  and 2 wrong red-six board cards remain; complete boards10/12. Do not lift
  `requires_revalidation`. The same-recording batch was unused for selecting
  the prior fusion repair, but old-v3 training overlap is not ruled out.
- A separate static contrast-normalization experiment removes the three
  dim-hero wrong accepts (two correct, one abstain), but does not fix red6→5.
  No production algorithm/weights/thresholds changed in this evaluation turn.
  This batch is now development material; a new batch must validate a future
  change. Tools: `validate_wpk_card_batch`, `rescore_wpk_card_batch`, and
  `experiment_wpk_contrast`. Preserve the first-run files and model snapshot.

- **2026-09-08 first source-bound hand and fusion repair:** V2 now has a
  redacted AcQh all-in trace (`tests/fixtures/wpk_reference_hands/aq_allin_v1.json`).
  PokerKit independently reproduces 13 actions, contestable pot 346 and
  unmatched return 238. Project side-pot math agrees; post-reveal turn equity
  is 37/44. Insurance notice 12 and settlement difference 22 are observed;
  the remaining fee decomposition is not verified. Never use later revealed
  villain cards for the earlier decision.
- This hand exposed in-place Hanning mutation in `phaseCorrelate`, reversed
  registration direction and unbounded glyph storage. Fixed with input copies,
  inverse shifts and a 64-glyph window. Candidate-only replay on 421 reviewed
  frames accepts the correct AcQh on 414 and abstains on 7, with no wrong
  accepted hero; 8 board/hero checkpoints agree. This is a development case,
  not independent validation. `card_fused.requires_revalidation=true` now
  withholds production card candidates; historical v3 counts must not be
  reused as v4 acceptance. See `docs/WPK-INSURANCE-NOTES.zh-CN.md` and the
  private hand report under the video-first corpus.

- **2026-09-08 video-first execution:** follow `PLAN-WPK-video-first.zh-CN.md`
  for current sequencing: existing WPK recordings first, real capture-card
  acceptance last, AA later. V1 completed; V2 anchor/hand review started.
  Private artifacts are under `G:\PokerSense_archive\wpk_video_first_20260908`.
  Full session_002 sequential decode: 17063 frames, no PTS regression.
  All 257 old labeled images matched exact source pixels (242 unique,
  15 repeated); 64 nominal source indices were wrong. Old labels/hand IDs
  remain development hints, not accepted truth. 57 sparse anchors were
  visually reviewed by Codex and 66 candidate hand windows generated;
  neither interval completeness nor Golden eligibility is claimed.
- The user requested distilled poker-rule knowledge. Maintain
  `docs/WPK-RULEBOOK.zh-CN.md` alongside `tools/verify_nlhe_rulebook.py`.
  Its 12 PokerKit examples cover posts, straddle, short/full all-in reopening,
  side pots/uncalled return and rake. Passing the external oracle does not
  mean our production state/rule adapter has passed parity.

- **2026-09-08 local WPK scope supersedes the older ADB-first notes below:**
  phone + capture card, 6/7/8-player tables; AA is phase two. Work stays local.
  The user requests open-source-first components and editable table rules.
  WPK 2/4 and 3% rake are examples, not immutable constants. Ante, rake cap,
  straddle and special effects are user-configurable; bundled defaults are
  explicitly simulation assumptions. See `docs/wpk-progress-2026-09-08.md`.
- The local native desktop entry now defaults to capture-card and loads the
  measured 1920x1080 -> 498x1080 crop. The CLI retains explicit ADB support.
  Incomplete initial state yields a waiting frame; it does not invent players.
  Rule edits invalidate old Advice, with a rule revision carried to the UI.
- Live equity now counts ACTIVE/ALL_IN opponents, excludes folded/sitting-out
  seats, and requires a complete calibrated seat census and current cards.
  It remains **uniform-random showdown equity**, not inferred-range strategy,
  side-pot EV, or expected profit. Optional `phevaluator` is preferred when
  installed; an independently tested Python fallback remains available.
- Capture-card `board` and `action` calibration, low pot/stack recall,
  train/eval hand overlap, straddle production strategy, postflop providers,
  continuous ground-truth Replay and live hardware acceptance remain open.
  PokerKit has only been exercised as an independent ante/straddle oracle,
  not promoted to a live rules engine. Do not mark the project complete.

- Default branch: `main`.
- Current release: `v0.1.11` — [GitHub Release](https://github.com/windgeek/PokerSense/releases/tag/v0.1.11), source commit `f963181`.
- The `main` desktop path reads WePoker Android from a portrait LDPlayer
  instance over ADB, recognizes **hero and board cards**, derives the street,
  reads the total pot, eight-slot occupancy/stacks, the visual-slot Dealer
  marker, Hero's current decision turn, and completed visual-slot action
  labels, and displays visible-card equity against a random range. Published v0.1.11
  installers still contain the legacy H5 path; do not describe Android capture
  as released yet.
- A different hero-card pair must be visible for two consecutive frames before
  it starts a new hand. This prevents deal-animation reads from replacing the
  prior hand while allowing the companion window to refresh on every deal.
- All calibrated Android fields, including per-slot stack/action observations,
  require two consecutive matching production frames before state processing.
- Android occupancy, stack, Dealer, action, and Hero actor each have independent
  measured geometry and confidence evidence. A versioned eight-slot mapping
  promotes them to canonical seats/positions. Completed action glyphs are
  deduplicated and become canonical events only when actor stack delta and pot
  evidence are coherent. Opponent current-turn timers and complex missed-action/
  side-pot sequences remain unavailable without additional measured Replay.
- Capture frames are memory-only. The only persistent user setting is UI
  language (`auto`, `en`, or `zh`).

## Live-capture constraints

- Production input is `adb -s <serial> exec-out screencap -p` from LDPlayer,
  currently calibrated at 1440x2560 portrait. Host window coordinates, DPI,
  visibility, and occlusion are not part of the Android TableMap.
- Never choose among multiple ADB devices implicitly. `auto` is allowed only
  when exactly one authorized device exists; otherwise require
  `--device-serial` or `POKERSENSE_ADB_SERIAL`.
- Resolve ADB from `POKERSENSE_ADB_PATH` or PATH. Treat offline, unauthorized,
  timeout, corrupt PNG, and device disappearance as recoverable capture errors.
- Android and H5 never share ROIs or calibration evidence. They may share
  platform-neutral recognition algorithms and identical card-art templates.
- Real calibration screenshots and ZIPs are private inputs, ignored by Git,
  and never packaged. Retain only a small redacted labeled regression set.

## Local development and packaging

Python 3.11–3.13 is supported. On this machine Python 3.13 is used:

```bash
python3 -m venv .venv
./.venv/bin/pip install -e ".[dev,perceptual,desktop,packaging]"

./.venv/bin/python -m pytest -q
./.venv/bin/python -m flake8 src tests
./.venv/bin/pyinstaller packaging/pokersense.spec \
  --distpath dist --workpath build --noconfirm
```

For a macOS build, verify the bundle version and signature structure:

```bash
/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' \
  dist/PokerSense.app/Contents/Info.plist
codesign --verify --deep --strict --verbose=2 dist/PokerSense.app
```

The user validates GitHub release installers. Local verification should cover
tests, lint, package construction, bundle version, and code-signature
structure; do not represent a local build as a clean-user installation test.

## Documentation map

- `README.md` and `README.zh-CN.md`: product scope, installation, privacy,
  usage, and release-facing limitations.
- `docs/product-requirements.md`: product requirements, multi-scenario and
  multi-player capability matrix, input/output contracts, and staged
  acceptance criteria.
- `docs/strategy-requirements-matrix.md`: post-recognition strategy functions,
  required inputs, processing rules, output contracts, and router decisions.
- `docs/strategy-regression-test-matrix.md`: executable test suites, fixtures,
  coverage rules, performance budgets, CI tiers, and release gates.
- `docs/capture-replay.md`: hash-pinned raw-frame Replay registration,
  recognizer evidence binding, quality-report contract, and R6 eligibility.
- `docs/capture-card-calibration-guide.zh-CN.md`: AI-executable private-data
  calibration and acceptance specification for the candidate phone-to-PC USB
  capture-card path; its evidence remains separate from LDPlayer and H5. The
  hardware-independent tooling for it lives in
  `tools/capture_card_calibration/`
  (`python -m tools.capture_card_calibration.cli --help`); stages A and B
  still need real hardware and a human operator.
- `PLAN-capture-card-calibration.zh-CN.md`: the step-by-step development and
  work plan that turns the calibration guide's stages A-L into ordered,
  one-action-at-a-time tasks, splitting each into what the agent can build
  (code/config/tooling) and what needs real hardware or a human operator.
- `docs/recognition-ui-handoff.md`: practical handoff for the parallel WPK
  recognition and Live Coach UI work, including existing modules, owned gaps,
  frozen contracts, sequencing, and acceptance checklists.
- `docs/test-report-2026-08-23.md`: commit-bound development regression and
  target-hardware performance results, environmental blockers, requirement
  verdicts, and the remaining release evidence.
- `architecture.md`: overall design and data flow.
- `docs/`: subsystem contracts and architecture decisions. Keep these files
  concise and update the owning document rather than creating duplicate notes.
- `configs/vision/wepoker_android/` and `configs/platform/`: measured recognition
  calibration, not marketing claims. Update calibration evidence together with
  recognizer changes.
- `configs/strategy/`: versioned strategy/equity performance calibration. A
  policy-default change requires a fresh measured artifact and tool hash.

## Progress log

- **2026-09-17 — USABLE-001 P1 CI regression fixed (directed optional-dependency skip):**
  The P1 round pushed `0b7c40a` and CI run `35230485037` FAILED on BOTH matrix jobs at the `pytest`
  step (macos 7m22s, windows 9m36s; `review-hygiene` green; `flake8` never ran, because the step
  order is pytest then flake8). Root cause read off the failing log rather than guessed:
  `ModuleNotFoundError: No module named 'pokerkit'`. CI installs
  `-e ".[dev,perceptual,desktop]"` and NOT the optional `solver-tools` extra, so **PokerKit is
  genuinely absent on CI** -- while the local runtime has 0.7.5, which is exactly why the P1 tests
  passed locally and failed there. **15 of the 24 P1 tests were red and 9 passed**, and those 9 are
  the substance: a gate refusal happens BEFORE the library is consulted (`shadow_export` computes
  `missing_required` and returns `NOT_EXPORTABLE` above the `_pokerkit()` call), so CI had already
  confirmed the fail-closed property on a machine with no PokerKit at all.
  The fix is therefore a DIRECTED skip, not a module-level one: a `needs_poker_kit` marker
  (`importlib.util.find_spec("pokerkit") is not None`, degrading to "unavailable" on
  `ImportError`/`ValueError`) is attached to the 15 tests that actually drive PokerKit, while the 10
  gate / refusal / field-map / reverse-adapter tests keep running everywhere. A blanket module-level
  `pytest.importorskip` -- the shape the other five optional-dependency modules in this repository
  use -- would have made all 24 skip and left CI unable to tell a fail-closed gate from a missing
  dependency. A new test, `test_a_missing_field_refuses_before_the_library_is_consulted`, pins that
  ORDERING as the precondition the CI-visible tests rest on.
  Which tests to mark was MEASURED, not read off the source: a throwaway runner that swaps the path
  finder for one refusing to locate `pokerkit` makes `import` and `importlib.util.find_spec` behave
  exactly as on a machine that never installed it, and it reported **15 failed / 9 passed** before
  the fix and **15 skipped / 10 passed / 0 failed** after; with PokerKit present the module is
  **25 passed** (24 plus the new ordering test) and `flake8` is clean. The whole repository was then
  run under that same harness, i.e. under CI's real dependency set: **4099 passed,
  21 skipped, 0 failed, exit 0** in 405.99s (the tally is the authority: `addopts` already carries
  `-q`, so a second `-q` hides the summary, and counting progress-bar characters instead
  undercounted the skips by 2). Against the PokerKit-present run -- **4158 passed + 1 skipped =
  4159** -- exactly **59** tests stop passing without the extra, and every one is accounted for:
  the **15** newly marked P1 tests, **1** in `tests/tools/test_nlhe_rulebook.py` and **2** in
  `tests/tools/test_wpk_hand_trace.py` (all function-level `importorskip`), plus the whole of
  `tests/state_engine/test_reviewed_replay.py` (**29**) and
  `tests/state_engine/test_reviewed_completion.py` (**12**) which gate with a MODULE-LEVEL
  `pytest.importorskip("pokerkit")` and so never enter collection at all, contributing ONE skip
  entry each instead of their 41 outcomes. Skips go **1 -> 21** for the same reason (the
  pre-existing `Quartz` skip, the 15 P1 tests, the 3 function-level pokerkit skips and the 2
  module-level entries), and both identities check out: `4158 - 59 = 4099` and
  `1 + 15 + 3 + 2 = 21`. `ci.yml` was deliberately NOT changed to
  install `solver-tools`: that is a repository-wide CI policy change which would also pull in
  `phevaluator` and alter other skip outcomes, so it is put to the user as a decision instead. No
  assertion was relaxed, no required field defaulted, and no threshold, ROI, solver, `_posting`
  anchor, `expires`, all-in terminal or early-fold change; nothing merged or released;
  `REAL_HAND_ACCEPTANCE_PENDING` and `NOT_ASSESSED` unchanged.

- **2026-09-17 — USABLE-001 P0.1 ordinary-terminal fail-closed guards (G1 stability latch, G2 action count):**
  authorized by `P0_1_TERMINAL_GUARDS_THEN_P1_SHADOW_ORACLE` (`issuecomment-5714727922`) as exactly the
  two guards the P0 round had reported and deliberately NOT patched. **G1** - a single self-contradictory
  frame must not be able to establish a sticky river fact: `AAObservationSemantics` now keeps a
  `river_streak` of consecutive observations that AGREE (`full_river AND pending_actions == 0`) and
  latches `river_frame` only on the second of them. The latched frame is the FIRST frame of the run
  (`row["frame"] - (river_streak - 1)`), so the guard costs latency WITHOUT re-stamping the recorded
  instant. The run is broken by a blocked row, by `epoch is None`, and by `closed`, and the epoch-change
  and `reset()` paths still clear it. After latching, the pre-existing sticky semantics are UNCHANGED
  (`full_river=False` frames still must not revoke it). **G2** - `pending_actions == 0` is now required
  ONLY while first latching, never afterwards, so a later teardown or action-count variation cannot
  revoke an already-established historical fact. Deliberately NOT implemented as a frame-count threshold
  tuned to this recording's 67/149/168 frames. Failing tests first: 3 of the 5 new cases ran RED against
  the pre-fix head (`3 failed / 18 passed`); the other 2 are anti-over-fix guards that are green on both
  sides by design. Green now: `tests/desktop/test_aa_ordinary_river_terminal.py` **21 passed**, and the
  combined `test_aa_ordinary_river_terminal.py + test_aa_live_opening_boundary.py + test_aa_semantics.py`
  run **52 passed**. **Real replay (0..27287, every frame through one temporal chain, no seeking, no
  sparse sampling, 23m20s, `retrieve_fail / read_fail = 0 / 0`):** full-river epochs **6**, latched-river
  epochs **5**, `ordinary_river_pending` **5**, `ORDINARY_RIVER_CLOSED` **5**, `closed NOT exactly once:
  none`. First blocker per epoch: **5** `CONFIRMED_ORDINARY_RIVER_CLOSED`, 14 `no_complete_river_observed`,
  5 `no_real_hand_board`, 1 `suspended_bucket_has_no_epoch_name_so_c3_can_never_fire`. Latch detail: the
  river frames are IDENTICAL to P0 (9512 / 12325 / 15033 / 18170 / 25674), each latches on the SECOND
  frame (9513 / 12326 / 15034 / 18171 / 25675), the latched VALUE is the first frame in every case, and
  exactly **1** complete-river frame was seen before latching with `nonzero_pending = 0` in all five hands
  - so G1 costs exactly one frame of latency and G2 costs nothing, and **no hand was lost**. The target
  hand `observed_deal_14593` still closes at **f15198** (river 15033, latch 15034, 50 pending rows,
  settlement seat 4 `+134` from 131 -> 265 confirmed 15148), Hero `4s 3s`, board `3c 7s 3h Tc 6c`.
  A separate post-hoc auditor (`p01_audit.py`, locating each payload by the epoch INSIDE it) re-derived
  the audit from the JSON artifact and reports **`PROBLEMS: none`** across 10 checks x 5 hands. That step
  was necessary because the in-run audit printed 5 false "problems" - a terminal rides on the SUCCESSOR's
  first row, not on the closing epoch's record, and the in-run code read the wrong one; the printed
  payloads themselves carry `river_complete_frame = 9512 / 12325 / 15033 / 18170 / 25674`, matching the
  latched values exactly. One un-attributed fact is recorded rather than explained away: the anonymous
  `None` bucket has **119** complete-river frames (longest unlatched run 117, 5126 blocked frames) and
  never latches - a broken streak is a plausible but UNVERIFIED explanation, and it can never confirm
  anyway because it has no epoch name, so C3 can never fire. No all-in terminal, vision threshold, ROI,
  solver, opening ledger, `_posting`, `expires` or early-fold change; nothing merged or released
  (`REAL_HAND_ACCEPTANCE_PENDING` / `NOT_ASSESSED` unchanged).
- **2026-09-17 — USABLE-001 P1 PHH + PokerKit SHADOW ORACLE (first round: bypass/differential only):**
  authorized by the same comment, first round only, and **no existing PokerSense rule code was deleted
  and the production state machine was NOT replaced**. PokerKit **0.7.5 is already installed in the
  project runtime**, and `pyproject.toml`'s `solver-tools` extra already pins `pokerkit==0.7.5`, so P1
  needed no new dependency. New files, not wired into the pipeline:
  `src/poker_engine/desktop/aa_phh_shadow.py` (`SHADOW_SCHEMA = "aa-phh-shadow-v1"`, `VARIANT = "NT"`,
  `POKERKIT_NT_REQUIRED`, `PHH_REQUIRED`, `SEATS_FIELD`, and a `FIELD_MAP` tuple that is the single
  source of truth for the doc), `tests/desktop/test_aa_phh_shadow.py` (**24 tests at the time, 25 after the CI fix
  recorded above, flake8 clean**) and `docs/research/pokersense-phh-pokerkit-shadow-oracle.zh-CN.md` (the required
  "PokerSense evidence -> PHH -> PokerKit State" field-mapping document, sections 1-8). The contract:
  only CONFIRMED facts are ever fed to PokerKit, every UNKNOWN field grows an explicit
  `unconfirmed_because` reason, and `shadow_export(facts)` returns one of `NOT_EXPORTABLE` /
  `POKERKIT_UNAVAILABLE` / `POKERKIT_REJECTED` / `EXPORTED` - a `NOT_EXPORTABLE` or
  `POKERKIT_UNAVAILABLE` refusal NEVER contains a `phh` key (only `POKERKIT_REJECTED` carries the
  document, and there every required field WAS confirmed), so a refusal can never hand a downstream
  consumer a hand history built from unconfirmed evidence. `optional_explicit_utg` is deliberately
  judged UNMAPPABLE because it is a per-hand observation, not a declaration. **The fail-closed gate is
  real and the proof is layered**: the real closed hand `observed_deal_14593` was exported under four
  scenarios - A (real situation, no table rules) -> **6** missing (`seat_order`, `min_bet`,
  `blinds_or_straddles`, `antes`, `starting_stacks`, `actions`); B (+ complete declared table rules) ->
  **3** missing; C (+ confirmed positional order and opening stacks) -> **only `actions`**; D (+ one
  action carrying the pipeline's best status, `PRICE_DERIVED_CANDIDATE`) -> still only `actions`, reason
  "1 of 1 action interpretations are not confirmed". All four refuse and none emits `phh`. The `actions`
  gate is STRUCTURAL, not a data gap: `aa_semantics.py` assigns `interpretation_status` at only three
  sites (`"UNKNOWN"`, `"VISIBLE_LABEL_CANDIDATE"`, `"PRICE_DERIVED_CANDIDATE"`) and **never
  `"CONFIRMED"`**, so under the current pipeline no real hand can ever be exported - that is this
  round's headline finding, and it was NOT worked around by inventing a status. Three further
  capabilities were added after the first pass because the checkpoint asked for them explicitly:
  (1) **the PHH now carries the physical seats** in the optional `seats` header (`seats = ['4','7','1']`,
  measured to round-trip verbatim while `dumps(loads(dumps)) == dumps` still holds) - without it a PHH is
  only positionally indexed and the reverse direction could never restore `seat_order`;
  (2) **a computed `side_pot_split` differential item**, verified on a VALID main-900/side-600 short-stack
  hand (`p3` raises to 300, `p1` re-raises to 600, `p2` calls all-in for 300, `p3` calls) and on a
  call-full-then-fold hand where a seat paid 300 but is eligible for none of it - so "paid in" is
  distinguished from "eligible", with fold status read from the `Folding` operations because
  `State.statuses` cannot tell a fold from a showdown kill; and
  (3) **the reverse adapter `shadow_ingest` plus `shadow_round_trip`**, where nothing the reverse
  direction produces is ever `CONFIRMED` (reconstructed actions carry `PHH_ROUND_TRIP`, so feeding them
  back into `shadow_export` REFUSES - otherwise the reverse would launder unconfirmed facts past the
  gate), and the round trip is asserted per field (`variant` / `antes` / `blinds_or_straddles` /
  `min_bet` / `starting_stacks` / `actions` / `seats` all MATCH; `ROUND_TRIP_NOT_RUN` when the forward
  export refuses rather than faking a result). **Two bugs of my own were caught and fixed rather than
  quietly deleted, both now pinned by regression tests:** the first `side_pot_split` version divided the
  pot by its eligible count to recover the level, which is not what a level is, and reported `MISMATCH`
  on the simplest single-pot hand (650/2 = 325, which nobody had paid) - the level has to be derived by
  slicing the contributions at each distinct positive amount; and the differential's first version
  compared the payout against `final.payoffs` instead of `ChipsPulling`, which is the round's most
  valuable engineering conclusion: PokerSense's `unallocated_positive_cash` is a settlement-time BALANCE
  DELTA (the counterpart of `ChipsPulling.amount`), NOT the net payoff - measured `payoffs = [-50, -300,
  350]` against `ChipsPulling(player_index=2, amount=650)` - and the two coincide only when the credited
  seat contributed nothing to the pot, so a differential written against `payoffs` silently misreports
  every split pot. Also established: PHH round-trip identity holds; replay must be driven by iterating
  `hh.state_actions` (a generator of `(State, action)`; `create_state()` returns only the INITIAL state);
  `HandHistory.__init__` is keyword-only even though `HandHistory.loads` is not; `State.pots` is ZEROED
  once the chips are pushed, so a side-pot split has to be sampled mid-replay at the last state with a
  non-zero total (reading it off the finished state turns the check into a tautology); and PokerKit's own
  `HandHistory.required_field_names["NT"]` is asserted against `POKERKIT_NT_REQUIRED` in a test, so the
  gate cannot drift from the installed library - the assertion also pins that `seat_order` is OUR
  precondition and **not** a PHH field, a nomenclature error the first doc version made and has fixed.
  Solver expansion, Deep CFR and GTO strategy work were NOT started.
- **2026-09-17 — USABLE-001 P0 first real ordinary-river hand close (bounded `river_frame` fix):**
  authorized by `P0_FIRST_REAL_HAND_CLOSE` (`issuecomment-5713265121`) as a bounded code-gap fix,
  explicitly NOT a rule relaxation. Failing tests first: the new sticky-river cases ran against
  head `f4b0298` in a separate read-only worktree and gave **2 failed / 14 passed** (two further
  cases are anti-over-fix guards that must be green on both sides). Fix, in
  `src/poker_engine/desktop/aa_semantics.py` only, is one combination wide - within an epoch,
  `not closed AND not full_river AND river_frame already set` used to CLEAR `river_frame`; it now
  KEEPS it. `river_frame` is cleared only on an epoch change, on `reset()` (source change or frame
  discontinuity, which still discards every cross-frame fact) and when `closed` (the all-in
  showdown, which explains the ending by itself) holds. The root cause was mis-attributed in the
  previous round: the earlier `payout_credit_not_visible` finding (3 of 5 hands) was a MEASUREMENT
  ARTEFACT - the old probe counted credits only on frames whose board was still complete, and in
  **all five** full-river hands the own-epoch payout credit is confirmed AFTER the last
  complete-board frame (8622 seat 3 +33 @9680; 11609 seat 5 +172 @12398; 14593 seat 4 +134 @15148;
  17323 seat 4 +239 @18323; 24560 seat 1 +123 @25825). So there was ONE root cause with five
  isomorphic manifestations, and the fix covers all five at once. Measured on the full continuous
  0..27287 replay (every frame read, no seeking, no sparse sampling): `ORDINARY_RIVER_CLOSED`
  **0 -> 5**, one per full-river hand, each on the first frame of the successor epoch, each
  EXACTLY ONCE (`{8622:1, 11609:1, 14593:1, 17323:1, 24560:1}`), none on an epoch with no full
  river, none without a payout. The target hand `observed_deal_14593` closes at **f15198**
  (river 15033, pending f15148-15197 = 50 rows, then the epoch switches to `observed_deal_15197`
  with no `None` in between); Hero `4s 3s`, board `3c 7s 3h Tc 6c`. All five carry
  `ledger_status: HAND_COMMITMENTS_UNKNOWN` with `canonical_verified / card_showdown_verified /
  rake_verified / strategy_eligible` all `False` - this terminal claims no GTO strength and is not
  a checkable complete hand record. `pending_actions == 0` is still NOT a C1 condition (recorded
  as a documented deviation, not silently added). An adversarial differential harness (same file
  with only the river block reverted) found ONE false positive the fix newly introduces: a single
  self-contradictory frame (`street_candidate == "river"` plus five valid distinct cards) inside an
  epoch whose hand never reaches a river, followed by a cleared board, a `confirmed_frame` balance
  increase and a new epoch, now emits `ORDINARY_RIVER_CLOSED` with `river_complete_frame = 0`.
  It is NOT patched: the authorization is bounded to "clear only on epoch change / `reset()`", and
  adding an `ordinary_river`-exists guard would narrow that semantics. Reported with the guard
  proposal instead. Residual risk is bounded - C2 still requires money to have moved, so the
  failure mode is misclassification, never a premature close - and it is unreachable on this
  recording, where the minimum `complete_frames` across the five real hands is **67**. Verified:
  `tests/desktop/test_aa_ordinary_river_terminal.py` **16 passed**, `tests/desktop` **445 passed**,
  full suite and `flake8 src tests tools` clean. No visual threshold, no ROI, no solver, no
  `_posting` anchor, no `expires`, no seat-count change, no early-street fold-out terminal.
  `REAL_HAND_ACCEPTANCE_PENDING` and `NOT_ASSESSED` unchanged.
- **2026-09-17 — USABLE-001 ordinary-terminal real-replay verification and lifecycle contract:**
  verification-only round: no new feature, no early-street fold-out terminal. A continuous
  sequential replay of the authorized recording (frame 0..27287, every frame grabbed in order,
  no seeking, no sparse frames) gave 25 epochs, **6** reaching a full river, **1** producing
  `ordinary_river_pending`, and **0** producing `ORDINARY_RIVER_CLOSED`. Attribution per hand (as
  published that round): three of five named hands had no own-epoch credit confirmed strictly after
  their river frame (`payout_credit_not_visible`), one also had non-zero `pending_actions`, and the
  suspended `None` bucket has no epoch so it can never confirm. **The `payout_credit_not_visible`
  attribution is WITHDRAWN** by the next round's frame-by-frame re-measurement: it was an artefact
  of counting credits only on frames whose board was still complete, and all five hands really do
  have a post-river own-epoch payout credit (see the P0 entry above, which also carried the fix
  this entry had to defer). Blocker located to the frame and still correct: `observed_deal_14593`
  DID satisfy C1+C2 (river at f15033, live pending across f15148-15185, 38 rows) but
  **f15186-15197 lost the complete-river reading**, resetting `river_frame` and withdrawing the
  pending record, and the epoch only switched at **f15198** (a direct A-to-B transition, no `None`
  in between), so C3 had nothing left. The minimal fix (clear `river_frame` only on an epoch
  change) was reported here but NOT applied, because this round's authorization was verification
  plus one lifecycle guard; it was applied in the following P0 round. The lifecycle contract was
  pinned instead:
  `ordinary_terminal` is now a one-shot confirmation event (cleared in `observe` after `_phase`
  returns, covering every return path) and the persisted history is the separately named
  `last_ordinary_terminal` snapshot with its own `epoch` and a `belongs_to_current_epoch` flag.
  Four new tests: one-shot emission, no leak across the 2nd/3rd/4th epoch, absent before any
  confirmation, and not surviving a blocked row. Verified: full suite **4124 passed /
  1 skipped / 414.33s**, five touched desktop files 86 passed, flake8 clean. No threshold, ROI,
  solver, anchor, `expires` or seat-count change; nothing relaxed to chase a hit.
- **2026-09-17 — USABLE-001 desktop opening-boundary fix and `ORDINARY_RIVER_CLOSED`:**
  scoped by the reviewer to three items: fix the explicit desktop duplicate-epoch defect and
  regress it on the historical 1260-1330 data; confirm this table's forced-bet rule without
  touching `>= 3 seats`; implement the ordinary terminal as `ORDINARY_RIVER_CLOSED` only.
  Failing tests came first. `tests/desktop/test_aa_live_opening_boundary.py` (with the frozen
  pre-adapter row fixture `opening_rows_1260_1290_v1.json`) and
  `tests/desktop/test_aa_ordinary_river_terminal.py` were run against the previous head
  `064894b` in a separate read-only worktree: **8 failed / 2 passed**, the two green ones being
  deliberate anti-over-fix guards. Fix one: `LiveStateAdapter._anchored_opening()` mirrors
  `AA8HandLedgerCandidate._reset`'s qualification and stops the dealer-advance branch from
  replacing an epoch whose hand already holds a ledger-qualifying opening - the defect that
  sent a just-resolved ledger back to `HAND_COMMITMENTS_UNKNOWN` at source frame 1278. Fix two
  (added in parallel, all-in terminal untouched): `AAObservationSemantics._phase` now reports
  `ordinary_terminal` / `ordinary_river_pending`, confirmed only by a new non-empty epoch
  observed after a complete, settled river, with `ordinary_terminal_semantics` stating that
  preflop/flop/turn fold-out endings are not covered. `docs/research/usable-001-opening-boundary-and-ordinary-river-close.zh-CN.md`
  records the mechanism, the forced-bet arithmetic (`5 x 2 + 1 + 2 + 4 = 17` matching all three
  observed openings, so `>= 3` stays), the counter-examples and the known limit that a visible
  payout is required. Verified: `tests/desktop` + `tests/tools` **1726 passed**, flake8 clean,
  and the real-pool replay now yields a single `MULTI_POST_DEAL_CANDIDATE` epoch. No kernel,
  solver, capacity, threshold, ROI, anchor or `expires` change; nothing merged.
- **2026-09-16 — USABLE-001 U2-R2 rule-source control and wrong-shaped record isolation:**
  review `pullrequestreview-5226343574` kept the whole U2-R1 rebuild and refused final
  acceptance on two boundaries. Failing tests came first: the new store cases and the three-phase
  `tests/js/hand_records_flow_test.mjs` were run against the previous head `d9212c8` in a separate
  read-only worktree, producing 7 named server failures and 9 named phase-1 failures (a standalone
  probe script also captured the old failure mode: the list answered HTTP 500 with an unterminated
  body, the `null`/string cases and single `get`/`scenario` timed out, and the healthy records
  disappeared). Fixed: `ui/aa-live/hand_input.js` gives the rule-source control its own change
  handler that really leaves a saved-rules scenario (keeping hand, assumptions, size grid and
  parent link) plus a fail-closed guard when the control and the scenario disagree;
  `ui/aa-live/analysis_records.js` points at that switch in its feedback;
  `src/poker_engine/desktop/aa_analysis_records.py` checks the record's shape before reading any
  field, keeps `_present` safe for a non-object, turns expected shape errors into that record's own
  named refusal, and isolates each file inside `recent`. A measured trap is recorded: `rake_cap_bb=0`
  removes the rake entirely, so the harness's current-rules table now uses `rake_cap_bb=2` and the
  switched recompute is cross-checked against a direct kernel call. Docs: new
  `docs/research/usable-001-u2-r2-rules-source-and-record-isolation.zh-CN.md`. Verified:
  `tests/desktop/test_aa_analysis_records.py` 51 passed (was 7 failed / 44 passed on the old head),
  the three-phase harness green in all phases, `flake8 src tests tools` clean, full suite 4109
  passed / 1 skipped (was 4092 / 1). No kernel, solver, capacity, launcher, model or CI-config
  change; no merge.
- **2026-09-16 — USABLE-001 U2-R1 recompute binding, request identity, sealed record content:**
  review `pullrequestreview-5225415635` refused U2 acceptance on three paths while keeping the
  U1 acceptance and the U2 save/reopen/launcher work. Fixed exactly those three plus a
  readability item, with failing tests first: the new `tests/desktop/test_aa_analysis_records.py`
  cases and the rewritten three-phase `tests/js/hand_records_flow_test.mjs` were run against the
  previous head `3f56d4d0` in a separate read-only worktree, where they produced 15 named server
  failures and 15 named phase-1 failures (not a crash), then went green here. Changes:
  `ui/aa-live/analysis_records.js` (void-before-request, epoch + requested/response record id +
  live selection + form-token binding, selection preserved at refresh apply time, save bound to
  the analysis it was issued for, sample type / rule values / opponent assumptions rendered),
  `ui/aa-live/hand_input.js` (shared `handApplyFacts`, new `handApplyAssumptions`, `handScenario`
  for a saved-rules scenario, `handLoadRecordScenario`, `analysis_record_id` /
  `parent_analysis_record_id` in the source), `src/poker_engine/desktop/aa_analysis_records.py`
  (content seal with an explicit schema, named cross-checks for folder-vs-record id, source/job/
  rules linkage, root-action actor/size/cost against the verified grid, derived pot/amount/
  capacity regenerated from the verified block, a single verification used by get/list/scenario/
  idempotent lookup, `UNVERIFIED_FORMAT` for unsealed files, explicit and validated `source_kind`),
  and `docs/research/usable-001-u2-r1-recompute-binding.zh-CN.md`, which supersedes the two
  recompute and `rubric` statements of `docs/research/usable-001-u2-save-reopen.zh-CN.md`.
  No kernel, solver, capacity, launcher, model or CI-config change; no merge.
- **2026-09-03 — capture-card branch review hardening:** reviewed the eight
  commits on `feat/capture-card-toolchain` before integration. Fixed a source/
  profile isolation defect so `source="capture-card"` automatically selects
  the independent capture-card platform and can never run against the
  calibrated LDPlayer profile; the reverse ADB/profile mismatch is also
  rejected. Profiles explicitly marked `uncalibrated` now fail with a clear
  `LiveCaptureError` before recognizers or templates are constructed. Tightened
  normalization config parsing so strings, floats, booleans, and negative crop
  coordinates cannot be silently coerced into geometry. Aligned the calibration
  README/manifest with the already-landed partial geometry and recorded the
  owner-approved session/head-count exceptions in the owning guide and plan.
  Added focused regression tests. The full suite passed 2,121 tests with 3 platform skips;
  repository-wide Flake8 and diff checks passed. Capture-card recognition
  remains intentionally unreleased and fail-closed pending the recorded stage-G
  gaps and the rest of stages H-L.

- **2026-09-04 — fused card pipeline WIRED end-to-end into live.py:** the
  fused recognizer is no longer only a landed artifact — it now replaces the
  legacy single-frame matcher at load time for the capture-card platform.
  `load_calibration` builds a `FusedCardRecognizerAdapter` (per-slot temporal
  fusion behind the stateless `CardRecognizer` protocol) whenever
  `card_heads.npz` + the `card_fused` calibration are present, and
  `load_measured_calibrations` promotes `card_fused` to the platform's `card`
  measurement (floor=suit_floor=0.3, Wilson confidence 0.985). The stateful
  recognizer requires a fixed canvas, so the hero dynamic-coordinate fallback
  (a WePoker-H5 "browser toolbar shifted the ROI" affordance) is disabled for
  the fused platform — otherwise the same slot's buffer would receive two
  different crops per frame and reset itself. Verified on the private
  corpus through the real `vision.process` path: fused hero cards read
  **7/7 correct across the 7 hands with >=3 gated frames, 0 wrong** (the rest
  abstain on under-sampled fusion, as designed). `fused_card_adapter.py` +
  engine/live wiring + 2 adapter tests (1666 passed, flake8 clean).

- **2026-09-04 — FULL card recognition UNBLOCKED in software (no hardware
  change); locked splits 100%:** the "suits physically unresolvable at
  53x78" verdict is reversed. Root causes were in OUR pipeline, not the
  pixels: (1) the HSV-hue colour router is undefined for black ink (hue
  noise lands in the red range) — replaced with a BGR (R-B) ink test,
  perfectly bimodal on the corpus (black=0, red>=35) → colour family
  450/450; (2) the aspect-fit letterbox rescaled+repositioned every glyph
  independently, so temporal fusion blurred a club's three lobes into a
  spade shape — replaced with fixed-height size normalisation + ink-
  centroid anchoring + phase-correlation registration; (3) the board-strip
  street gate cannot tell two hands apart at PRE_FLOP (an empty board is
  identical), so the NEXT hand's hero glyphs bled into the fusion (an 8S
  averaged into a clear K ghost, faint-Q dilutions) — fixed with a
  per-slot card-region gate; (4) ~3% of card labels carried a wrong suit
  — a classifier-vs-label disagreement audit with crop-by-crop visual
  confirmation corrected 37 suit labels + 1 hero order swap (backups
  kept). On the fused grayscale glyphs: sklearn MLP heads (rank 13-class
  softmax 32-hidden; per-colour-family binary logistic 24-hidden;
  shift/scale/brightness augmentation) read the FULL card at
  **calibration 62/62, locked validation 116/116, zero false VALID**.
  Landed: `perceptual/vision/fused_card_recognizer.py` (numpy-only MLP
  forward, FusedSlotBuffer street+slot gating, fail-closed floors),
  `configs/vision/wepoker_android_capture_card/card_heads.npz`(+meta),
  `calibration.json` card_fused block (legacy single-frame path stays
  fail-closed at floor=1.0 by design), 15 tests. Method/evidence:
  `_stage_i_gray_fused.py` + `evidence/field_metrics.json`; label audit
  `_fix_suit_labels.py`. Next: online temporal fusion wiring into the
  live frame loop (end-to-end on the capture card).

- **2026-09-04 — stages J/K/L closed; card suits stay BLOCKED at full scale:**
  the fused stage-I pipeline ran end-to-end on the locked splits
  (`_stage_i_fused.py`, private log `_mining/stage_i_fused_run.log`):
  calibration 65 positives = 54 correct / 11 wrong, and **all 11 errors are
  same-colour suit confusions (D<->H, C<->S)** — four at margin 0.000 (S/C
  template scores identical) and the rest *confidently* wrong (margins up to
  0.88), so no threshold yields recall at zero false VALID; the fail-closed
  gate correctly abstains on everything (recall 0%). Rank alone is 96.9%
  and red/black family is ~100% when rank is right — the reliable delivery
  boundary. Exact suits are physically unresolvable at 53x78 on this
  canvas; unblocking them means a higher-resolution card region (e.g. a 4K
  UVC negotiate + a redone stage I), which is an owner decision. Until then
  hero_cards/board_cards remain UNKNOWN (fail-closed, as designed).
- **2026-09-04 — stage J (seat mapping) done:** new
  `tools/capture_card_calibration/seat_mapping.py` builds the platform's
  identity slot->seat contract (hero = seat 0, ascending slot = direction
  of play, evidenced by the dealer badge advancing 2->4->7->1->2->4 across
  session_002 hands) plus fail-closed reducers (`derive_canonical_dealer`:
  zero badges -> UNKNOWN, multiple -> CONFLICT; EMPTY+stack ->
  `SeatConsistencyError`). A latent occupancy bug was fixed in
  `seat_reader.read_slot`: an ambiguous band (dimmed "away" avatar, or the
  hero band whose white hand-type text false-fires the "+" cross detector)
  used to be read EMPTY — a wrong positive claim that mutates seat state.
  EMPTY now requires the positive cross signal and the hero slot never
  uses the avatar/cross path: re-measured on the private corpus, occupancy
  is **893 correct / 59 abstain / 0 wrong (100% precision, 93.8% recall)**
  and dealer stays **576/576**. Evidence: private
  `geometry/seat_mapping.draft.json` + `evidence/seat_mapping.json`;
  41 tests in `tests/tools/test_capture_card_seat_mapping.py`.
- **2026-09-04 — stage K (replay + performance) done:** replay draft for
  the real hand `session_002_hand_0117` (6-8 handed, owner direction) runs
  through `load_capture_replay` / `run_capture_replay` with label-derived
  expectations: **6 frames, 0 mismatches** — 3 EXACT (fold, street_change,
  fold), 2 INVALID (chip actions correctly fail closed with
  `actor_stack_missing_for_chip_action`), 1 NO_ACTION snapshot. Draft +
  report: private `replay/capture_card_hand_0117/` and
  `evidence/replay_report.json`; `release_eligible=false` recorded
  verbatim (not raw_frame stage; field calibrations not landed). Measured
  performance (recorded as-is, no release threshold implied): UVC decode
  30.1 fps / 0 drops over 300 frames (black stream — phone detached),
  normalization p50 0.4 ms / p95 0.61 ms, 8-slot seat recognition p50
  82.5 ms / p95 153.2 ms (fits the ~10 fps effective budget, exceeds a
  33 ms one); 30-min continuous run, hot-plug and multi-device selection
  are marked not-measured (no signal attached).
- **2026-09-04 — stage L (seat mapping landed):** the stage-J contract is
  now a production resource,
  `configs/platform/wepoker_android_capture_card__<layout_id>_seat_mapping.json`,
  loading through `live.load_platform_seat_mapping`; resource /
  serialization / builder-parity tests pin it (the landed file, the
  stage-J builder and both loaders must never diverge). Card-related
  vision configs intentionally stay uncalibrated skeletons (stage I
  blocked); docs updated. Remaining open items: owner decision on suits
  (4K recapture vs rank+colour delivery), then end-to-end live wiring.

- **2026-09-03 — owner focus: 6-8 handed table is the calibration primary
  direction.** The owner stated "90% 的牌局都是 6-8 人" and asked to focus there.
  An audit of the drop-clean dataset confirms it: head-count buckets are
  {1人: 6, 2人: 31, 6-8人: 64} with **zero 3-5 handed frames** — the owner plays
  6-8 handed and never plays a 3-5 handed table. Section 10's generic head-count
  requirement {2, 3-5, 6-8} was therefore **owner-authorized** to a focused
  {2, 6-8} (new `REQUIRED_HEADCOUNT_BUCKETS` in `coverage.py`, documented inline
  and recorded here — the same pattern as the `MIN_SESSIONS=2` waiver). This is
  a recorded owner decision, not a silent relaxation: a table type the owner
  never plays must not be collected purely to satisfy a generic table, since it
  would be out-of-distribution noise rather than evidence. The real remaining
  gaps (now that occupancy is `ok`) are within the 6-8 handed bucket: the
  `completed_action` / `current_actor` fields are entirely empty (0 samples),
  the TURN street has only 3 frames, and the negative samples (card-back,
  non-pot, occlusion, menu) are near-zero. The updated top-up checklist
  (`reports/label-topup-checklist.zh-CN.md` v3) prioritises these.

- **2026-09-03 — viewpoint evidence tool (`cli viewpoint`):** the owner anchored
  the LIVE discriminator on **the three action buttons** ("以三按钮为准"), and
  this tool surfaces that evidence for a human to confirm by eye. `viewpoint.py`
  is deliberately *not* an auto-classifier (guide rules 1-2 forbid reusing
  another platform's geometry, and the failure-closed philosophy forbids guessing
  which table a frame belongs to): it extracts the explainable signals — the
  revealed-hero-cards white fraction (`hero_signal`), the coloured three-button
  action-band fraction (`_action_signal`), and a caller-supplied `hero_occupied`
  — then returns a conservative `LIVE`/`SPECTATE`/`UNKNOWN` verdict with a
  confidence and a `ViewpointEvidence` breakdown. `hero_occupied` is *never*
  derived here (a second heuristic would break the fail-closed contract); it is
  supplied by the seat-reader pipeline / the labeller and only corroborates.
  `cli viewpoint` renders a self-contained HTML contact sheet in the private
  dataset's `reports/` (images inlined; never in Git) plus an optional `--json-out`
  machine-readable verdicts file. On the 101-frame drop-clean dataset it reports
  session_001 all-LIVE (the owner's real heads-up game) and session_002
  47 LIVE / 17 UNKNOWN (the UNKNOWN frames are mid-street frames where the
  buttons were not lit — exactly the frames the owner should eyeball).   18 new
  unit tests; flake8-clean project-wide.

- **2026-09-03 — stack-value transcription tool (`cli stack-worksheet` /
  `cli stack-apply`):** with occupancy now `ok`, the remaining blocker for a
  "stable positive" frame is an `OCCUPIED` seat whose `stack` is still
  `UNKNOWN` — which de-qualifies the whole frame and leaves calibration/
  validation splits empty. `stack_transcribe.py` turns every such target into a
  form the labeller fills by eye (a zoomed crop of that seat's stack pill plus
  the frame context), and applies only the values the labeller actually returns.
  It **renders, never writes**: `stack-worksheet` emits a self-contained HTML
  (images inlined, never in Git) + a `frame,slot_id,value` CSV template;
  `stack-apply` is the sole writer and keeps a timestamped backup of
  `frames.jsonl` first. Philosophy (guide rule): a blank/unknown/already-set
  cell is never auto-filled, `CONFLICT` is never transcribed (it needs a
  re-read, not a guess), and a non-empty value must validate as a non-negative
  int before promotion to `VALID`. Geometry comes from `seat_reader`'s
  `SLOT_LAYOUT_MULTI` / `SLOT_LAYOUT_S002` per session — it stays in normalized
  canvas space and is not reused from any other platform. `cli review-frames`
  gained a `--session` filter so the labeller can work the primary 6-8 handed
  bucket without a 100+-frame dump. 14 new unit tests; flake8-clean.

- **2026-09-03 — data-trust audit: dropped spectate-segment frames from
  session_001:** the owner flagged that the capture may have mixed in frames of
  a table he was *watching*, not playing, which would corrupt every hero-relative
  field (hero_cards, current_actor, completed_action). A frame-by-frame review of
  the private dataset confirmed it: session_001's first segment (t < 62300 ms,
  `session_001_hand_0000/0001`, 5 frames) was the 8-handed table of an opponent
  ("泰迪小白" et al.) that the owner was spectating, before he entered his own
  heads-up table. Note the room-label line `<不要不要不要01的牌局>` is a *room
  name*, NOT a spectate badge — the reliable LIVE indicator is the owner's own
  nickname + revealed hole cards + action buttons at the bottom. session_001's
  later segment (heads-up, owner = "鱼而已不要") and all of session_002 (8-handed,
  owner playing) are genuine live play. Per owner decision the 5 spectate frames
  were dropped from `labels/frames.jsonl` (106 -> 101; backup kept as
  `labels/frames.jsonl.pre_spectate_drop.bak`), and the coverage / top-up
  checklist was regenerated. `hero_cards` was already UNKNOWN on those frames
  (correct fail-closed), but their board_cards / street / pot / occupancy came
  from a table the owner was *not* playing, so dropping them matters.

- **2026-09-03 — label top-up review page (`cli review-frames`):** stage F
  label coverage is currently the bottleneck (105 of 106 frames carry at least
  one UNKNOWN field), and a terminal `coverage`/`splits` run reports *how many*
  samples are missing but never *which pixel to look at*. Added
  `tools/capture_card_calibration/review_frames.py`, which turns an audit
  report plus the label set into a per-frame labeller-facing HTML page: each
  card embeds the normalized PNG, the audit findings that point at that frame
  (if any), and a slot-by-slot read-out marking which fields are still
  UNKNOWN/CONFLICT. The output is self-contained (images inlined as base64) so
  it opens without the private data dir, and it lives under the private
  dataset's `reports/` — never Git. It never rewrites a label or invents a
  value, honouring the failure-closed philosophy. Wired it into `cli.py`
  (`review-frames --root/--out/--json-out/--limit/--rules/--include-images`)
  and unit-tested it with synthetic-only
  `tests/tools/test_capture_card_review_frames.py` (25 tests: field rendering,
  gap detection, slot views, per-frame issue indexing, HTML/JSON emission,
  escaping, self-containedness). Module stays import-safe without OpenCV. Ran
  it over the real 106-frame set (123 MB with embedded images, 380 KB in
  `--include-images` off mode); the per-frame gap distribution matches the
  top-up checklist exactly (board_cards 27 / hero_cards 6 / pot 1 frame-level;
  stack 461 / dealer 232 / completed_action+current_actor 848 slot-level).

- **2026-09-03 — stage-H splits run against the real label set is BLOCKED
  by stage-F coverage, not a tool defect:** ran `cli splits` (and `cli
  coverage`) over the private 106-frame label set. `splits` assigns frames by
  hand group and reports `train/validation have no stable positive frames`
  because 105 of 106 frames carry at least one known-but-UNKNOWN field: stack
  is UNKNOWN on 461 slot observations, dealer on 232, board_cards 27,
  hero_cards 6. Diagnosed against `_has_unknown_field`: even under a generous
  rule that lets an EMPTY slot keep an UNKNOWN stack, only 14 of 106 frames
  qualify as fully-valid, so the read is legitimately fail-closed — the 2-5
  and 6-8 seat frames and completed-action/temporal/anomaly samples still must
  be transcribed before a usable train/validation split exists. Coverage shows
  the exact gaps (completed_action 0, hero_actor 0, anomaly 0, board/pot/dealer
  negative samples short, head-count 3-5 never observed). A per-field top-up
  checklist was written to the private dataset
  (`reports/label-topup-checklist.zh-CN.md`), but no label or split value was
  invented and no coverage requirement was relaxed. This is a PARTIAL/BLOCKED
  honest state, not a claim that calibration is complete.

- **2026-09-04 — glyph-level temporal fusion UNBLOCKS card suits (prototype):**
  following the stage-I single-frame impasse, a fusion prototype content-
  matches each labelled frame to its cv2 position in the raw video (VFR index
  drift is real: ffmpeg index != sequential cv2 index, but board-strip
  signature matching lands exact, meandiff 0.0), gathers street-gated
  neighbour glyphs (signature gate, ~30-40 per card), and classifies the
  averaged glyph. The exact K♠ case that k-NN/medoid got wrong (C at
  best=1.000) reads correctly as S after fusion; all three prototype cases
  read right. Margins are still thin (~2.5% S-vs-C), so the production path
  is per-frame fusion + full split-discipline threshold calibration — that
  rerun is the next stage-I task. Card field remains UNCALIBRATED until the
  fused pipeline passes zero-false-VALID on the locked validation split.

- **2026-09-04 — stage H done; stage I card field honestly BLOCKED (for now):**
  stage H splits are written and validated (train 224 / calibration 63 /
  validation 80, hand-isolated, each with stable positives and hard negatives)
  after fixing a `_has_unknown_field` semantics bug in `splits.py` — it
  demanded a VALID stack on EMPTY slots, contradicting the dataset rule
  ("a seated player should carry a stack; an empty slot must not"), which
  made every 6-8-handed frame unusable as a positive. A duplicate-frame
  cleanup (scene-priority dedupe, 378 -> 367) preceded the split. Stage I
  for hero_cards+board_cards then ran the full evidence pipeline (train-only
  templates, calibration distributions, locked validation): single-frame
  glyph matching **cannot** separate S/C or D/H at 53x78 — medoid IoU gives
  no gap (wrong reads up to 0.994), k-NN k=5 collides at best=1.000, and
  hole-count topology finds zero holes on all 281 train glyphs (structure
  not preserved at this resolution). Zero-false-VALID therefore forces
  threshold>1.000 = 0% recall: card recognition stays UNCALIBRATED
  (fail-closed), and the recorded next method is street-gated glyph-level
  temporal fusion (supersampling), which already fixed rank 6->5 reads in
  the earlier pilot. Evidence lives in the private `evidence/field_metrics.json`.

- **2026-09-04 — stage G CLOSED (owner-waived final three):** after the VFR
  fix surfaced CHECK/BET, the remaining three sub-gaps (ALL_IN 0/6, hand_end
  0/10, reconnect 2/5) were presented to the owner with full evidence;
  he ruled them waived — all-in is a rare action to be hand-labelled when it
  occurs, this UI shows no distinct result panel, and the capture signal was
  stable throughout. Implemented as recorded waivers in `coverage.py`
  (`ACTION_WAIVERS` / `TEMPORAL_WAIVERS` / `RECONNECT_WAIVED`, generic guide
  minimums preserved; test updated to pin ALL_IN not being named).
  **Coverage: stage G minimum coverage = met (378 frames).** Next stages:
  H (train/validation splits), I (platform templates + thresholds — card
  suits need the street-gated fusion work), J (seat mapping), K (replay).

- **2026-09-04 — VFR time-base fix: footage is 48 min, CHECK/BET closed:**
  the two mkv containers claim 30 fps but the effective capture rate is ~10
  fps, so in-frame phone clocks are the ground truth: session_001 spans
  03:06-03:26 (20 min) and session_002 04:40-05:08 (28 min) — 48 minutes of
  real 6-8-handed play, not 16. Dataset timestamps stay on the container
  time base; event dedupe must convert (s001 x1200/11985, s002 x1680/17063).
  Re-deduping on real time split over-merged events (orange badges 25 -> 40)
  and, together with a blob-geometry badge/name discriminator, surfaced two
  classes previously declared absent: **让牌 = teal CHECK badge (11 verified
  events)** and 下注 BET (12 verified incl. the teal variant; text, not hue,
  separates BET from RAISE on orange badges). completed_action is now
  FOLD/CALL/RAISE/CHECK/BET-complete. Verified-absent after full-spectrum
  badge sweeps and per-frame text reads: ALL_IN (0 in 48 min), hand_end
  RESULT (4 showdown-reveal candidates, win-glow semantics unconfirmed),
  reconnect (2 black frames; signal was stable). Checklist v5 in the private
  dataset records the exact recording recipe needed to close the last three.

- **2026-09-04 — video-mined label top-up: stage-G gaps closed 8 -> 2:**
  mined both raw session videos (48 min wall-clock; see the VFR entry above)
  at 10 fps with a private
  scene miner, then promoted only visually-verified evidence into the private
  dataset (216 -> 355 labelled frames; every single frame eyeballed on a
  contact sheet, no auto-proposal landed unreviewed). Landed: 61 verified
  completed-action labels (CALL 18 / RAISE 21 / BET 4 / FOLD 18 across
  slots 0-7), 55 `current_actor=HERO` frames (blue "N 跟注" decision circle
  is the reliable hero-turn cue; the grey 让或弃/自动让牌 toggles are always
  on and are NOT a turn signal), 50 MENU + 2 SIGNAL_LOSS + 1 OVERLAY anomaly
  scenes, 30 deal-transition and 70 action-transition temporal groups.
  Coverage: hero_actor, anomaly_scenes, all field negatives, and temporal
  deal/action/street_change are now `ok`. Honest remaining gaps (nothing in
  the current footage can close them): CHECK 0/10 and ALL_IN 0/6 badges never
  rendered (raise-heavy low-stakes play), BET 4/10, hand_end RESULT screens
  not identified (golden burst is a win effect, semantics unconfirmed),
  reconnect groups 2/5 (signal was stable throughout). Action-badge vocabulary
  measured on this platform: CALL=blue, RAISE/BET=orange (text tells them
  apart), FOLD=dimmed avatar + white text, countdown=white "Ns"; 等待审核/
  等待中 is NOT an action. Private checklist regenerated as
  `reports/label-topup-checklist.zh-CN.md` v4.

- **2026-09-03 — capture-card 5-slot board geometry landed; card-template
  pilot (honest negative):** mined the two raw session videos (~16 min) with a
  private scene miner (board-strip blob counting, seat avatar dark/white text
  events, table-vs-anomaly gating), yielding 83 RIVER candidates whose 5 card
  boxes are stable to ±1 px across both sessions. Widened the platform
  `board_cards` ROI to the measured full 5-card strip (110,478)-(388,556) and
  landed `configs/vision/wepoker_android_capture_card/board_slot_layout.json`
  (5 measured slots, relative to the strip); evidence rows appended to the
  private `labels/roi_measurements.csv`. Card-recognition pilot against the
  owner's labelled frames: H5 (`wepoker`) corner-glyph templates FAIL
  verification at capture-card scale (70.5% hero / 90.5% board, black-suit
  S/C collapse with high raw scores — no abstain threshold can gate them), so
  `template_source: wepoker` must not be relied on for suits. Platform-derived
  medoid templates from labelled crops reach 89.6% hold-out with residual
  6/8 and S/C confusion; 10-frame temporal fusion within one street fixes
  rank 6/5 reads (measured) but needs street-boundary gating. Card
  calibration therefore stays UNCALIBRATED (fail-closed); next step is formal
  stage-I template/threshold work on street-gated fused crops. Mining also
  produced 621 action-event / 569 button / 52 anomaly / 24 transition
  candidates ready for owner-reviewed label top-up.

- **2026-09-03 — capture-card boundary measurement, seat reader, and
  two-session floor:** added `tools/capture_card_calibration/boundary.py`
  (stage C section-6 content-boundary drift measurement) and its
  `cli boundary` subcommand, measuring canvas geometry separately from content
  luminance so a leftover UVC letterbox border is caught even while the game
  draws a dark menu band; only stable table frames decide the verdict against
  the guide's 2-pixel tolerance. Added `tools/capture_card_calibration/seat_reader.py`
  (stage F seat pixel reader) reading per-visual-slot occupancy / stack /
  dealer from normalized frames via luminance/chroma thresholds, giving VALID or
  UNKNOWN per read and reusing no LDPlayer or H5 ROI. Recorded the
  owner-authorized waiver of the third capture session as an explicit
  annotation (`MIN_SESSIONS = 2` in `schema.py`, surfaced in `report.py`), with
  the deliberate, documented rationale. Resolved the capture-card identity
  placeholder by replacing the `card_replace_me` platform config / layout_id
  with the real ugreen UVC card and updating `hero_slot_layout.json` and the
  `land_capture_card_configs.py` default. Unit-tested via synthetic-only
  `tests/tools/test_capture_card_boundary.py`; capture-card tool modules and
  tests are flake8-clean and pass with `PYTHONPATH=src`. This still calibrates
  nothing on its own: validation of the seat reader's measured geometry and the
  remaining negative-sample / temporal / action / anomaly gaps below require
  real capture-card evidence.

- **2026-09-03 — capture-card calibration toolchain:** added
  `tools/capture_card_calibration/`, the hardware-independent half of the
  calibration guide. It provides: SHA-256/SHA256SUMS hashing (guide rule 8),
  a strict label/field schema that forces UNKNOWN (a field never carries a
  guessed value) and intercepts REPLACE_ME placeholders, deterministic
  `layout_id` construction (§6), the dataset delivery skeleton (§3) with
  `frames.jsonl` / `roi_measurements.csv` I/O, pixel-ROI -> normalized
  coordinate geometry that emits draft `table_map` + slot layouts, minimum
  coverage checks with an exact top-up list (§10), session+hand-isolated
  splits with leakage detection (§11), an acceptance report that defaults to
  PARTIAL/BLOCKED (§17), and a `cli.py` entrypoint. It also ships the
  stage A/B live-recording helpers (`probe` to read a device's negotiated
  UVC parameters, `record` to capture a session to `source/raw/*.mkv` while
  automatically logging disconnect / black-frame / reconnect signal events).
  Unit-tested (see `tests/tools/test_capture_card_*.py`). This does NOT
  calibrate anything — stages A (freeze hardware) and B (record 45–90 min of
  real hands) still require real hardware and a human operator.

- **2026-09-03 — capture-card realtime backend:** added the UVC capture
  backend `CaptureCardBackend` (`perceptual/capture/capture_card_backend.py`)
  implementing the `CaptureService` contract via OpenCV `VideoCapture`
  (MSMF/DirectShow, YUY2 fourcc, resolution/fps, disconnect + all-black
  signal-loss detection), plus stage-C frame normalization
  (`perceptual/capture/normalization.py`: fixed rotate -> mirror -> crop ->
  content-size validation, versioned). Both are unit-tested with a mocked
  VideoCapture. Added `configs/vision/wepoker_android_capture_card/` as an
  explicit `uncalibrated` platform scaffold. This is the realtime backend only:
  no capture-card recognition calibration exists, so the platform's fields must
  read UNKNOWN until `docs/capture-card-calibration-guide.zh-CN.md` stages A-K
  produce real capture-card evidence and stage L lands it. No end-to-end
  capture-card capability is claimed.

- **2026-09-02 — capture-card calibration handoff:** added a Chinese,
  AI-executable end-to-end specification for independently calibrating a real
  Android phone connected through a USB capture card. It freezes source and
  normalization metadata, visual-slot numbering, ROI/label contracts,
  field-by-field minimum coverage, hand/session-isolated splits, threshold and
  locked-validation rules, Replay/hash evidence, privacy constraints, failure
  conditions, and final deliverables. Linked it from the capture/mapping
  document. This is a calibration handoff only: no UVC capture backend or
  released capture-card capability is claimed.

- **2026-08-24 — Android calibration desktop packages:** committed the
  completed LDPlayer Android table calibration as `c3e9d59`, temporarily used
  public standard GitHub-hosted runners for Build Desktop App run `#47`, then
  restored the repository to private. The native Windows installer and macOS
  DMG both built successfully; the downloaded DMG checksum verified, and its
  bundled app passed strict code-signature, Gatekeeper Notarized Developer ID,
  and stapler validation. The Windows installer is structurally a valid PE32
  executable; live Windows LDPlayer installation and recognition remain
  tester-owned release evidence.

- **2026-08-24 — Android seat/actor/canonical-action closure:** added an
  independent eight-slot occupancy observation contract, serializer,
  confidence gate, temporal confirmation, and empty-plus recognizer. Thirty-
  four manually reviewed stable states produced 272/272 correct occupied or
  empty labels with no conflict. Added a versioned eight-slot Android mapping
  that derives canonical 2–8-player positions from Dealer and occupancy,
  promotes mapped stacks, and keeps unknown slots fail closed. A separately
  measured Hero-turn recognizer accepted all 33 reviewed blue-control frames
  and abstained on the other 201 private frames; it never guesses an opponent
  timer. Completed action glyphs now choose their own actor slot, persistently
  rendered glyphs are deduplicated, and an event is recorded only when stack
  delta and pot evidence reconstruct a legal chip amount. Canonical action
  history now reaches `LiveStrategySession`, whose dealt-player count follows
  active occupancy; without a qualified multiplayer Provider, Advice remains
  ABSTAIN. Updated the English/Chinese product, vision, architecture, and
  handoff documents. The full suite passed 1,806 tests with 3 platform skips
  (1,809 collected); repository-wide Flake8 and diff checks passed. The local
  v0.1.11 macOS bundle built successfully, passed strict code-signature
  verification, and contains one copy of each new mapping/template resource.
  Authorized privacy-reviewed raw Replay, live Windows LDPlayer/reconnect and
  Windows packaging remain external release evidence; opponent current actor
  and complex missed-action/side-pot sequences remain UNKNOWN until measured.

- **2026-08-24 — Android completed-action label calibration:** added eight
  Android-only action ROIs and privacy-safe binary glyph masks for Fold,
  Check, Call, Bet, Raise, and All-in. Forty-five timeline- and slot-spread
  labels were manually reviewed and all 45 matched the correct action/slot;
  600 labels cleared the measured 0.83 floor across all 234 frames with no
  ambiguous runner-up. The 48 strongest rejected candidates were Hero action
  controls, nicknames, avatars, cards, or overlays; their maximum score was
  0.762. Production now emits completed `slot_actions[]` through independent
  calibration, confidence gating, and two-frame temporal confirmation.
  Persistent Fold labels remain observations rather than duplicate events.
  The full suite passed 1,796 tests with 3 platform skips (1,799 collected);
  repository-wide Flake8 and diff checks passed. Seat occupancy, canonical
  mapping, actor, action amounts, raw Replay, live Windows LDPlayer, and
  packaging remain; strategy therefore still fails closed to ABSTAIN.

- **2026-08-24 — Android visual-slot stacks and Dealer calibration:** added
  eight Android-only stack ROIs with independent glyph templates/calibration,
  plus eight Dealer search windows whose output is explicitly a visual slot.
  Eighty timeline-spread stack crops (ten per slot) were manually reviewed and
  all decoded correctly; 68 empty/overlay/transition negatives abstained.
  Forty Dealer detections (five per slot) were reviewed and all mapped to the
  correct slot; across all 234 raw ADB frames, 216 produced exactly one valid
  Dealer slot and 18 hidden/transition states abstained. Added glyph-topology
  filtering after real stack crops exposed an 8-versus-3 correlation error.
  Focused production-profile tests passed; the full suite passed 1,795 tests
  with 3 platform skips, and repository-wide Flake8 and diff checks passed.
  Seat occupancy, canonical mapping, actor/action amounts, raw Replay, live Windows
  LDPlayer, and packaging remain.

- **2026-08-24 — Android board/street production calibration:** added an
  Android-only five-slot board ROI/layout for the 1440x2560 LDPlayer canvas
  and independently calibrated occupancy/street evidence from 27 manually
  reviewed stable raw-ADB states: 17 distinct postflop boards containing 64
  visible card identities plus 10 preflop empty-board states. All stable
  states read correctly; measured deal/flip transitions top out below the
  accepted occupancy floor and remain UNKNOWN/CONFLICT. The separate
  88-minute H.264 recording validated the same geometry after its 48-pixel
  toolbar crop but did not lower raw-ADB thresholds. Added a private video
  normalization/dedup manifest tool and synthetic production-profile tests.
  Also calibrated the fixed total-pot ROI and white-on-dark amount OCR: 22/22
  distinct manually transcribed values and all 53 labeled stable frames were
  correct, while 25 label/menu/overlay/transition negatives abstained. The
  full suite passed 1,793 tests with 3 platform skips; repository-wide Flake8
  and diff checks passed. Seat occupancy/canonical mapping, actor/actions,
  authorized raw-frame Replay, live Windows LDPlayer, and packaging remain.

- **2026-08-24 — 88-minute LDPlayer video intake:** audited a private
  1.9GB H.264 recording (88m35s, 30fps, 1440x2608) without adding it or
  extracted frames to Git. The extra 48 vertical pixels are a stable LDPlayer
  host toolbar; cropping `(0, 48, 1440, 2560)` restores the calibrated Android
  game canvas, so existing Android ROIs remain geometrically applicable.
  A full-decode one-minute sample produced 89 frames spanning changing seat
  occupancy, all streets, all-ins, showdowns/results, and ranking/profile
  overlays. The production hero recognizer returned 62 VALID, 27 UNKNOWN,
  and zero CONFLICT across 60 distinct accepted hands; visual review found
  the UNKNOWN cases concentrated in card backs, folded/dimmed cards, and
  overlays, with no confirmed false VALID in the sample. H.264 compression
  makes this strong temporal/negative/calibration evidence but not a basis
  for lowering thresholds without raw ADB PNG ground truth. No product code
  or calibration changed.

- **2026-08-23 — Android-first README:** clarified the English and Simplified
  Chinese user guides so LDPlayer Android/ADB is the only default live input:
  no H5 or Chrome window is required, the 1440×2560 portrait prerequisite is
  explicit, and single-device `auto` versus multi-device serial selection is
  documented. This remains a `main` capability until the next Windows
  installer is packaged and released.

- **2026-08-23 — application icon:** added a project-owned PokerSense icon
  (PNG source plus macOS `.icns` and Windows `.ico`) and made the PyInstaller
  spec select the native format for each platform. The local macOS bundle
  contains `PokerSense.icns` and passed `codesign --verify --deep --strict`.
  Windows package validation remains CI-owned.

- **2026-08-23 — strategy UI and cross-platform CI repair:** redesigned the
  desktop Strategy Advice panel around primary action, action frequencies,
  sizes, EV, source, safety reasons, and expandable evidence; non-READY
  output remains explicitly withheld. Added repository-wide LF checkout and
  UTF-8 CI defaults so strategy fixtures, documentation, UI contract tests,
  and benchmark hashes do not vary on Windows; fixed the merged verifier's
  lint issue. Full pytest, flake8 (including `tools`), and local browser
  rendering against a READY strategy fixture passed. The Windows GitHub run
  must still confirm the platform-specific repair.

- **2026-08-23 — multiplayer strategy merge:** merged
  `codex/multiplayer-strategy-system` into `main` after retaining the Android
  ADB capture path. The live stream now emits atomic `DesktopFrame` values and
  routes incomplete Android observations through the strategy safety gates,
  which fail closed to `ABSTAIN` until actor, stack, action, and a qualified
  provider are calibrated. Resolved capture/UI integration and documentation
  conflicts; full test suite, flake8, and staged diff checks passed. Live
  LDPlayer, real capture Replay, interactive UI, package, and clean-install
  evidence remain outstanding.

- **2026-08-23 — Android/LDPlayer production pivot:** replaced the default H5
  window path with explicit ADB device capture for portrait frames. Added
  fail-closed device selection, capture error/PNG validation, Android-specific
  hero calibration, and retained shared card-art templates without sharing ROI
  evidence. On 66 private deduplicated frames, all 58 visible hands read
  correctly and all eight negative scenes abstained. Full tests and flake8
  passed; live Windows LDPlayer and package verification remain pending.

- **2026-08-23 — Android dataset audit:** inspected 234 private LDPlayer
  captures without retaining them. The added temporal triplets cover deal
  transitions, folds, results, menus, multiplayer/showdown geometry, and
  negative scenes; missing ground truth deliberately leaves thresholds and
  calibration counts unchanged.

- **2026-08-23 — development regression and performance report:** recorded a
  commit-bound Python 3.13/M1 Pro report for the multiplayer strategy branch.
  The strategy suite passed 1,080 tests in 4.10s; the available full suite
  passed 1,766 with 3 Windows-only skips in 23.55s. The isolated Quartz file
  had 6 passes, 7 TCC-precondition failures, and one real-capture skip, which
  remains an environment blocker rather than being relabeled as passing.
  Five-repeat Adaptive Equity measurements reported p95 1,065.064ms/7.436
  outcomes-per-ms for exact HU, 1,373.229ms/7.282 trials-per-ms for HU MC,
  and 2,006.896ms/4.983 trials-per-ms for 3-way MC; the conservative 3/2
  operations-per-ms policy remains unchanged. Flake8, 298-fixture, JavaScript,
  and diff checks passed. Real WPK Replay, stable-state-to-render p95, UI
  interaction, soak, package, and clean-install evidence remain missing.

- **2026-08-23 — partner-facing recognition/UI handoff:** added a standalone
  implementation handoff for the parallel WPK recognition and Live Coach UI
  work. It inventories the strategy/state capabilities already present, gives
  prioritized recognition and UI work tables, defines the `RawObservation`,
  `PlatformSeatMapping`, and `DesktopFrame` boundaries, identifies strategy-
  owned gaps that the partner must not guess around, and supplies development,
  Replay, UI-sequence, and shared R6 acceptance checklists. Documentation link
  and diff checks passed; this changes no released behavior. Real WPK Replay
  and interactive UI acceptance remain outstanding.

- **2026-08-23 — recognition/UI integration handoff and branch packaging:**
  documented the production boundary between the multiplayer strategy/state
  work and the parallel WPK recognition/Live Coach UI work. The PRD now lists
  required per-field `RawObservation` inputs, ownership of the live 2-max and
  per-size-frequency gaps, Advice display rules, Replay evidence, and a shared
  R6 merge gate; architecture and regression documents link the same frozen
  boundaries. On Python 3.13, 1,766 tests passed and 3 skipped with the Quartz
  permission-dependent file excluded; all 7 tests in that file were collected
  but blocked by the current terminal's Screen Recording TCC gate before their
  mocked window cases. Full Flake8, 298-fixture regeneration check, JavaScript
  syntax, and diff checks passed. Real WPK raw-frame Replay and interactive UI
  acceptance remain required.

- **2026-08-23 — bounded local GTOpen Slow Provider:** added an optional
  loopback-only `GTOpenPreflopProvider` against the separately checked-out
  upstream service. It serializes GTOpen's single mutable preflop session,
  maps exact 2–9-player position/blind/ante/rake/equal-stack contexts and
  authoritative actor/kind/raise-to histories, enforces action-line parity,
  waits for a bounded model gap, then reads the Hero's exact 169-class slice
  while preserving every raise/all-in size. Unequal stacks, imprecise paths,
  illegal actions, transport errors, expiry, timeout, and poor convergence
  fail closed; timeout attempts to stop the upstream solve. Multiway output is
  always HEURISTIC and discloses product-equity/realization, non-unique
  equilibrium, unverified remote revision, and license limits. A real M1 Pro
  CPU-only E2E at upstream `4aee435` built 4,270 nodes/1,710 action nodes/
  5.771688 MB and returned AKo Fold/Call/2-2.5-3BB Raise/All-in frequencies at
  100 iterations with model gap 0.008207490846030292 BB. Twenty-one focused
  Adapter tests, all 1,080 strategy tests, and all 1,522 available non-OpenCV
  tests passed; the generated corpus is current at 298 fixtures and focused
  Ruff, byte compilation, JavaScript syntax, and diff checks passed. Missing
  upstream license, independent Golden parity, real WPK input mapping, and
  multiway postflop solving still block registration as a released Provider.

- **2026-08-23 — local GTOpen execution probe:** cloned upstream commit
  `4aee435bdeb155b25f0c8140e707a8342ce4356f` into the Git-ignored
  `.upstream/GTOpen/` research checkout, without copying source or generated
  strategy assets into PokerSense. The Apple M1 Pro CPU-only Release build
  succeeded and all 104 executed upstream Solver tests passed (one benchmark
  ignored). A real local API probe built a 3-player 20BB BTN/SB/BB tree with
  13 nodes/6 action nodes/0.016224 MB, converged by its first 25-iteration
  check to a reported total model gap of 0.0004571471 BB, and returned a root
  2x169 strategy array. This proves local executability and API shape only;
  missing upstream licensing, independent Golden parity, real WPK context
  mapping, deeper performance, and multiway-postflop limitations still block
  registration or release as a PokerSense Provider.

- **2026-08-23 — multiplayer Provider source re-audit:** rechecked current
  public solver candidates after the generic PRV-003 intake path was ready.
  GTOpen now exposes a promising 2–9-player Preflop Lab API with per-node
  169-class strategy arrays and per-player best-response gaps, but its root
  repository has no LICENSE file and the raw LICENSE URL returns 404. Its own
  documentation also limits multiway terminal values to an equity/product
  approximation and postflop solving to Heads-Up. It was therefore documented
  as a priority candidate only if a compatible license and independent Golden
  validation appear; no code or asset was copied and no capability was
  claimed. MIT DCFR-SOLVER remains 6-max-only and cannot satisfy the 3–9-player
  or multiway-postflop requirements. PRV-003~005 still require an externally
  licensed source or user-supplied licensed export.

- **2026-08-23 — integrity-checked raw-frame Capture Replay contract:**
  advanced the real-evidence side of `ST-002` with strict Replay v1 loading,
  execution, and a deterministic JSON-safe quality report. Artifact, platform
  config, per-field calibration, and every raw frame are SHA-256 pinned;
  references cannot escape an explicit asset root, and their JSON must restate
  matching platform/layout/field/sample metadata. Release eligibility requires
  real-capture stage, authorization, privacy review, production recognizer
  execution, frame/revision-bound field evidence, non-empty calibration for
  every used field, and exact per-frame status/version/event/reason parity.
  Stable-observation or Synthetic Replay can never satisfy R6. Thirty-two
  focused tests cover tampering, drift, missing evidence, strict schema,
  recognizer identity, and eligibility. All 1,059 strategy tests and all 1,498
  available non-OpenCV tests passed; fixture, JavaScript syntax, diff, and
  focused Ruff checks passed. No real WePoker stack/action/actor/dealer raw
  frames were added, so ST-002 and R6 remain partial rather than overstated.

- **2026-08-23 — explicit platform slot-to-seat candidate mapping:** advanced
  `ST-002` with an immutable, versioned `PlatformSeatMapping` and a
  fail-closed `PlatformMappedStateEngine`. Stable actor/action/stack/pot/dealer
  evidence now maps visual geometry to canonical seats, builds one-player
  candidate deltas, reuses the production action reconciler, and atomically
  persists only exact transitions. Missing/unmapped/conflicting slots,
  multi-player stack changes, mixed action/street/card frames, chip mismatch,
  low-confidence values, and forced postings expose no candidate or event.
  Thirty-eight focused tests include parameterized 2–9-player coverage, and
  23 executable `MOCK-PLATFORM-MAPPING-*` Synthetic Replay cases grew the
  corpus to 297. All 1,027 strategy tests and all 1,466 available non-OpenCV
  tests passed; fixture, JavaScript syntax, diff, and focused Ruff checks
  passed. `ST-002` remains partial because WePoker stack/action/actor/dealer
  ROI/slot calibration and authorized real capture Replay do not yet exist;
  the production live profile therefore remains fail-closed.

- **2026-08-22 — licensed strategy-asset intake contract:** partially advanced
  `PRV-003~005` with a read-only `JsonStrategyAssetProvider` for 3–9-player
  preflop and multiway/presolved postflop nodes. Registration verifies file
  SHA-256, schema, provider/source/license metadata, capability ID, and the
  full capability digest; lookup uses the canonical context digest and fails
  closed for missing or malformed nodes. Synthetic tests cover 3-player
  preflop, 3-way flop, 4-way turn, sizing/EV, Router→Advice, bad hash,
  capability mismatch, and damaged nodes. Six executable
  `MOCK-STRATEGY-ASSET-*` fixtures grew the corpus to 274. All 988 strategy
  tests and all 1,427 available non-OpenCV tests passed; fixture, JavaScript
  syntax, diff, and focused Ruff checks passed. Real licensed multiplayer and
  presolved assets plus Golden parity remain required before these Provider
  requirements can be completed or released.

- **2026-08-22 — ordered Fast-source fallback:** completed `RTR-005` with a
  capability-safe `TieredStrategyRouter` that queries Cache, Preflop DB,
  Presolved, then Model and stops after the first usable layer. Added a
  lookup-only cache Provider so a write-through DB/asset wrapper can populate
  the same canonical entry without hiding fallback behavior. Miss,
  not-applicable, and rejected results fall through; all-source failure keeps
  the lookup trail and never invents a candidate. Five executable
  `MOCK-FAST-FALLBACK-*` fixtures grew the corpus to 268. All 967 strategy
  tests and all 1,406 available non-OpenCV tests passed; fixture, JavaScript
  syntax, diff, and focused Ruff checks passed.

- **2026-08-22 — target-hardware adaptive Equity calibration:** completed
  `EQ-004` on the declared MacBookPro18,3 target (Apple M1 Pro 10-core, 32GB,
  Python 3.12.2). Five measured runs found exact p95 throughput of 7.186
  outcomes/ms and worst-case measured MC p95 throughput of 4.757 trials/ms;
  the versioned `adaptive-equity-v2-m1-pro` defaults now use conservative 3/2
  rates. The calibration JSON records environment, command, source revision,
  latencies, and benchmark-tool SHA-256; tests lock the hash, rates, 50% safety
  margin, and 300ms PARTIAL behavior. All 953 strategy tests and all 1,392
  available non-OpenCV tests passed; fixture, JavaScript syntax, diff, and
  focused Ruff checks passed.

- **2026-08-22 — auditable hard refusal gates:** completed `FUS-004` with
  structured PASS/FAIL/SKIPPED results for request freshness, confidence,
  decision context, strategy availability, and legal actions, plus uniquely
  named external gates for range, numerical, and future modules. A failed gate
  cannot coexist with READY Advice; failure reasons flow through Fusion,
  Orchestrator, serialization, desktop view, and UI, while stale conversion
  preserves the audit. Four executable `MOCK-HARD-GATE-*` fixtures grew the
  corpus to 263. All 950 strategy tests and all 1,389 available non-OpenCV
  tests passed; fixture, JavaScript syntax, diff, and focused Ruff checks
  passed.

- **2026-08-22 — transparent bounded strategy matching:** completed `RTR-004`
  with exact hero-position matching and explicit, bounded stack, pot, and
  last-aggressive-size interpolation. Every interpolated candidate now carries
  structured requested/matched/distance/maximum dimensions; candidates that
  omit dimensions or overstate a dimension/capability score fail closed. The
  local resolver protocol, strategy cache, exploit adjustment, Advice wire,
  and UI preserve those dimensions. Four executable `MOCK-ABSTRACTION-*`
  fixtures grew the corpus to 259. All 932 strategy tests and all 1,371
  available non-OpenCV tests passed; fixture, JavaScript syntax, diff, and
  focused Ruff checks passed.

- **2026-08-22 — atomic HandMemory transitions:** completed `MEM-001` by
  replacing Orchestrator's state-then-events writes with prevalidated atomic
  `record_transition`, and hand-boundary's event/complete/start sequence with
  atomic `replace_active_hand`. Invalid event identity/version, non-HAND_END
  boundaries, time errors, and existing successors leave states, events,
  histories, and active-hand identity unchanged. Added 8 direct rollback and
  commit tests plus 4 executable `MOCK-MEMORY-*` fixtures, growing the corpus
  to 255. All 916 strategy tests, all 1,355 available non-OpenCV tests, and
  all 75 memory/orchestrator/integration tests passed; fixture check and
  focused Ruff passed.

- **2026-08-22 — production live Advice binding:** connected the real desktop
  stream through `LiveStrategySession`, `StrategyOrchestrator`, and atomic
  `DesktopFrame` output. Advice is bound to hand/state/request plus the current
  perception-quality fingerprint; state changes, expiry, history changes, or
  same-state confidence degradation force a new request and prevent prior
  READY actions from leaking forward. The current WePoker capture remains
  fail-closed ABSTAIN because actor/stacks/actions are uncalibrated and no
  bundled HU strategy asset is claimed. Added 6 focused production-binding
  tests. All 912 strategy tests and all 1,344 available non-OpenCV tests
  passed; fixture check and focused Ruff passed.

- **2026-08-22 — deterministic hand-boundary orchestration:** completed
  `ST-004` with a fail-closed SAME_HAND/CONFIRMED/AMBIGUOUS detector. Hero-card
  changes and corroborated street/board/pot resets can start a new hand;
  dealer and stack resets count only through explicit slot-to-seat mappings.
  The realtime pipeline now closes the previous hand with a timestamped
  `HAND_END` before creating the successor, while weak/conflicting evidence
  cannot switch hands. Added 12 focused tests, including a no-OpenCV pipeline
  integration, and 6 executable `MOCK-HAND-BOUNDARY-*` cases, growing the
  corpus to 251. All 906 strategy tests and all 1,338 available non-OpenCV
  tests passed; fixture regeneration/check and focused Ruff passed. Real
  platform mapping and capture Replay remain under `ST-002`.

- **2026-08-22 — general temporal consensus:** completed ST-001's stable-
  observation orchestration with configurable consecutive-frame confirmation
  for all base recognition fields and visual slot stacks/actions. Changed
  candidates, UNKNOWN, missing slots, and frame-sequence gaps restart the run;
  CONFLICT remains explicit and pending values become UNKNOWN before the
  StateEngine. The realtime pipeline now uses this general gate, while the
  live profile requires two frames for every future calibrated field. Added
  14 focused tests including a no-OpenCV pipeline integration and 8 executable
  `MOCK-TEMPORAL-*` sequences, growing the corpus to 245. All 894 strategy
  tests and all 1,326 available non-OpenCV tests passed. ST-002 remains partial
  until explicit platform slot-to-seat/candidate-state mapping and real replay.

- **2026-08-22 — fail-closed Advice UI view contract:** added a JSON-safe
  desktop view model and Live Coach rendering for action frequencies, sizes,
  EV, source/version, match quality, confidence, assumptions, and evidence.
  Only READY exposes actions; PARTIAL, ABSTAIN, STALE, and send-time expiry
  hide them. Advice now retains per-field Vision/manual/config/derived/inferred
  provenance, and the UI shows match/source badges with manual input explicitly
  highlighted; older schema-v1 Advice remains readable. Added deterministic
  wire-contract tests and localized status labels, and lazy-loaded realtime
  capture/pipeline exports so serialization tests do not require optional
  OpenCV. An atomic `DesktopFrame` now carries analysis plus optional Advice;
  its WebSocket contract accepts same-state Fast→Slow refinement but converts
  expired or hand/state-mismatched results to STALE before JavaScript sees
  them. All 879 strategy tests and all 1,311 available non-OpenCV tests passed.
  UI-002/UI-003 are complete; UI-001 remains partial until the live capture
  path can construct a full DecisionContext and invoke StrategyOrchestrator.

- **2026-08-22 — complete HU preflop Blueprint parity:** completed PRV-002.
  Ante and action amounts now normalize by arbitrary big-blind units, while
  capability metadata preserves real stack/ante pairs instead of inventing a
  Cartesian product. Expanded the pinned upstream Golden from 4 to 180 direct
  lookups: every 169-class root hand plus 11 action/stack/ante nodes across
  three verified shards. This exposed and fixed Decimal regrouping drift via
  deterministic 1e-26 largest-remainder allocation. Focused Adapter/Router
  tests and direct generation/upstream parity checks passed. Full regression
  passed with all 865 strategy tests and all 1,297 available non-OpenCV tests;
  assets remain optional and upstream exploitability remains unreported.

- **2026-08-22 — canonical action-event reconstruction:** completed ST-005
  with a pure adjacent-state reconciler for fold/check/call/bet/raise/all-in.
  Events carry both additional and total-street amount semantics plus chip
  evidence. Hand/version/card/player/status/chip/current-bet conflicts fail
  closed; multi-meaning all-ins are AMBIGUOUS and emit no event until an
  observed label resolves them. Added 29 focused tests and 8 executable Mock
  transitions, growing the corpus to 237 cases. Live Observation-to-candidate
  state mapping remains under ST-002. All 682 strategy tests and all 1,114
  available non-OpenCV tests passed; fixture check and focused Ruff passed.

- **2026-08-22 — automatic input provenance collection:** completed CTX-002
  with deterministic Vision/manual/config/derived/inferred adapters, stable
  canonical value digests, one resolved provenance record per field, explicit
  same-value consensus, and fail-closed cross-source conflict handling. The
  collector now feeds DecisionContext quality aggregation directly. Added 23
  focused tests and 8 executable provenance fixtures, bringing the synthetic
  corpus to 229 cases. All 652 strategy tests and all 1,084 available
  non-OpenCV tests passed; fixture regeneration/check and focused Ruff passed.

- **2026-08-22 — fail-closed local resolver process adapter:** added a
  no-shell JSON stdin/stdout protocol bound to Provider/version and exact
  hand/state/request identity. Configured timeout and request deadline are
  combined; output size, process exit, malformed JSON, invalid strategy,
  no-strategy, non-convergence, and exploitability thresholds are explicit
  states. A real subprocess test double also proves Slow Path Advice upgrade.
  Added 20 process tests and one fixture; all 625 strategy tests and all 1,057
  available non-OpenCV tests passed. PRV-007 is complete.

- **2026-08-22 — conservative whole-hand debrief aggregation:** added
  `HandReview` to pair Advice and observed actions only by exact
  hand/state/request identity, order matched decisions by observation time,
  sum only known EV losses, report completeness and the largest leak, and
  count action/size deviations. Missing, orphan, duplicate, same-state retry,
  cross-hand, and missing-EV records are never guessed into place. Added 14
  whole-hand tests; all 605 strategy tests and all 1,037 available non-OpenCV
  tests passed. TRN-002 is functionally complete; real Replay remains a
  release-acceptance evidence requirement.

- **2026-08-22 — versioned preflop range-prior selection:** added a bounded
  `PreflopRfiRangePrior` that expands only the reviewed 6/9-handed, 100BB,
  first-in-raise asset into concrete combinations, removes known-card
  collisions, normalizes exactly, and preserves source/version evidence.
  Unsupported counts, BB, stacks, action lines, and fully blocked ranges return
  `NOT_APPLICABLE/UNKNOWN` with no random fallback. Added 41 tests and two
  trace fixtures; all 591 strategy tests and all 1,023 available non-OpenCV
  tests passed. RNG-001 is complete for capability-bounded lookup behavior.

- **2026-08-22 — structured Advice evidence-chain audit:** added deterministic
  input, canonical-state, per-seat range, and Provider references with a
  SHA-256 chain ID and named missing links. Incomplete evidence remains visible
  but caps READY confidence at 0.49 and adds an explicit assumption; complete
  and legacy schema-v1 Advice round-trip safely. Added 19 tests and a broken-
  chain fixture; all 550 strategy tests and all 982 available non-OpenCV tests
  passed. ADV-003 is complete at the in-memory/serialized contract layer.

- **2026-08-22 — KL-bounded opponent adjustment and Decision Fusion:** added
  sample/quality/weight/logit/KL gates around exponential Q-value tilting.
  Weak or incomplete profile evidence returns the identical baseline; applied
  results preserve zero support and per-size conditionals, disclose metadata,
  and are downgraded to `HEURISTIC`. `DecisionFusion` now keeps the Router's
  one baseline, applies at most one adjustment, and is used by Fast and Slow
  Orchestrator Advice. Added 38 focused tests and one trace fixture; all 531
  strategy tests and all 963 available non-OpenCV tests passed. FUS-002 and
  FUS-003 are complete.

- **2026-08-22 — audited 6/9-handed RFI heuristic provider:** added a
  versioned MIT-source asset importer and bundled only the explicit 6-handed
  and 9-handed unopened ranges from `bmorrow10/preflopR` commit `aed511d`.
  The Provider always reports `HEURISTIC`, discloses source/asset hashes and
  limitations, invents neither sizing nor EV, and rejects 3–5/7–8 player and
  BB fallbacks. Thirty-one focused tests cover all 13 explicit ranges × 169
  hand classes, corruption, boundaries, and Exact-over-Heuristic routing.
  All 493 strategy tests and all 925 available non-OpenCV tests passed; a
  local wheel contains the JSON asset and full MIT notice. `PRV-006` is
  complete for this bounded fallback; a true 3–9-player solver-derived
  Provider (`PRV-003`) remains open.

- **2026-08-22 — canonical strategy cache and Provider fast path:** added a
  thread-safe TTL/LRU cache keyed by canonical decision state plus Provider,
  asset, and strategy-engine versions. Cached entries are identity-free
  templates and are materialized against the current hand/state/request, so a
  prior request identity cannot leak. Added a cache-first Provider wrapper,
  context/action payload sensitivity, source/version/asset/engine misses,
  stale re-query, no caching of misses, exact action-option preservation, and
  concurrent lookup tests. Eighteen new tests, all 462 strategy tests, and all
  894 tests in the available non-OpenCV suite passed. RTR-008 is complete;
  RTR-005 remains partial pending real DB/presolved/model layers.

- **2026-08-22 — conservative Advice confidence aggregation:** added named
  quality components and a strict minimum aggregator for input, Provider,
  state-match, range, numerical, or caller-defined factors. Advice now exposes
  factor metadata; an explicitly required but missing factor yields confidence
  zero and ABSTAIN rather than being averaged away. Approximate match scores
  also cap final confidence. Ten new tests, all 444 strategy tests, and all 876
  tests in the available non-OpenCV suite passed. FUS-005 is complete at the
  contract and Advice integration level.

- **2026-08-22 — context quality and request factory:** added conservative
  required-field provenance aggregation that uses the minimum rather than an
  average and emits hard reason codes for missing, UNKNOWN, CONFLICT,
  LOW_CONFIDENCE, below-threshold, duplicate, and state-consistency inputs.
  Integrated the policy into State→DecisionContext and added a thread-safe,
  clock-injected RequestContext factory with aware deadlines, duplicate-ID
  retries, rollback, and concurrent uniqueness. Fifteen new tests, all 434
  strategy tests, and all 866 tests in the available non-OpenCV suite passed.
  CTX-003 and CTX-004 are complete; CTX-002 remains partial until real
  observation/manual/config sources are automatically collected.

- **2026-08-22 — exact EV primitives and completeness gates:** added exact
  Decimal immediate Call EV, explicit Fold/Call/Raise branch aggregation for
  aggressive actions, and UNKNOWN results whenever a positive-probability
  continuation lacks a net value. EV gap now requires every legal action EV;
  incomplete maps cannot leak a misleading best-vs-second gap into Advice.
  Sixteen new EV/Advice tests, all 419 strategy tests, and all 851 tests in the
  available non-OpenCV suite passed. EV-001 through EV-003 are complete at the
  deterministic calculation-contract level; real Provider/solver continuation
  values remain separate evidence requirements.

- **2026-08-22 — training and deterministic explanation contracts:** added
  exact actual-action→Advice identity binding, action and size deviation,
  evidence-preserving debriefs, and EV loss only when both preferred and actual
  counterfactual EVs are present. Added deterministic Chinese/English Advice
  explanations that render the existing Decimal values, source, match, and
  confidence without changing decisions. Eight focused tests, all 403 strategy
  tests, and all 835 tests in the available non-OpenCV suite passed. EXP-001
  and TRN-001 are complete at the domain-contract level; TRN-002 remains
  partial until full-hand Replay/aggregation and real counterfactual Golden
  evidence exist.

- **2026-08-22 — Fast/Slow strategy orchestration:** added immediate Fast
  Advice with optional asynchronous Slow submission, caller-owned threaded
  Provider adaptation, explicit handles, and PENDING/APPLIED/NO_UPDATE/
  DISCARDED/FAILED collection states. Slow results are fail-closed on
  hand/state/request drift, request or candidate expiry, provider identity or
  version mismatch, malformed results, exceptions, and non-improving strategy
  quality. Thirteen focused orchestration tests, all 395 strategy tests, and
  all 827 tests in the available non-OpenCV suite passed. RTR-006 and RTR-007
  are complete at the orchestration-contract level; a real local resolver,
  persistent strategy cache, WebSocket/UI update path, and target-hardware
  latency evidence remain future work.

- **2026-08-22 — real HU preflop Provider baseline:** added an optional
  integrity-checked Adapter for `amaster97/poker_solver` 1.11.0 at commit
  `f78f1b2`, with exact HU/preflop capability boundaries, concrete-card
  to 169-class mapping, authoritative StateEvent→`c/b/r/A` history tokens,
  source action aggregation, per-size `ActionOption` frequencies and legality,
  manifest/shard provenance, and contained NOT_APPLICABLE/NOT_FOUND/REJECTED
  outcomes. Added non-invented 100BB/no-ante Golden root results for AA/AKs/72o
  plus `b300/AA`, an
  explicit upstream parity verifier, Provider→Router→Advice E2E coverage, and
  license/quality research. Direct parity against the checked-out upstream
  assets, 24 focused Provider tests, all 382 strategy tests, and all 814 tests in the
  available non-OpenCV suite passed; strategy-scope Ruff, byte compilation,
  fixture regeneration, and documentation diff checks passed. PRV-002 remains
  partial: non-zero ante capability is not yet BB-normalized and broader action
  tree Golden coverage remains; no multi-player Provider, bundled asset,
  released UI path, or exploitability claim was added.

- **2026-08-22 — equity cache and adaptive-budget baseline:** added canonical
  SHA-256 equity queries over cards, normalized concrete ranges and versions,
  pots/eligibility, method, engine version, trials, and seed; a thread-safe
  bounded TTL/LRU cache with stale state, CI metadata, provenance, and identity
  checks; seeded weighted multiway Monte Carlo with standard error/95% CI; and
  deadline-derived exact/MC selection with COMPLETE/PARTIAL numerical status.
  Thirty-two focused cache/adaptive/multiway tests, all 358 strategy tests,
  and all 790 tests in the available non-OpenCV suite passed; lint, byte
  compilation, fixture regeneration, and documentation diff checks passed.
  EQ-006 is complete at the in-memory contract level. Large concrete ranges now
  bypass joint Cartesian materialization and use seeded independent range draws
  with whole-assignment collision rejection. Monte Carlo checks a monotonic wall
  deadline in bounded intervals and reports actual rather than planned trials.
  EQ-004 remains partial until exact/MC throughput budgets are calibrated on
  target hardware.

- **2026-08-22 — exact derived strategy metrics:** added Decimal pairwise SPR
  over main/side-pot totals, exact immediate pot odds with an explicit
  no-call-cost state, and action-size normalization in BB, pot fraction, and
  raise multiplier using separate additional and total-street amounts. Zero
  bases remain unknown (`None`) instead of being represented as zero. Seven
  focused tests, all 333 strategy tests, and all 765 tests in the available
  non-OpenCV suite passed; lint, byte compilation, fixture regeneration, and
  documentation diff checks passed. The metrics are deterministic domain
  functions and are not yet populated from real recognized stacks/actions.

- **2026-08-22 — exact multiway pot-share equity:** implemented bounded exact
  evaluation over weighted collision-free joint assignments and all legal board
  runouts. Results report Hero win/tie/loss, expected share, and expected chips
  separately for every main/side pot, respecting each pot's eligible seats, plus
  total-pot equity. Tests cover a three-way partial tie, side-pot ineligibility,
  weighted assignments, turn enumeration, missing holdings, card collisions,
  and budget refusal. Seven focused tests, all 324 strategy tests, and all 756
  tests in the available non-OpenCV suite passed; lint, byte compilation,
  fixture regeneration, and documentation diff checks passed. This is an exact
  small-scenario engine, not the adaptive/Monte Carlo budget, confidence
  interval, or cache.

- **2026-08-22 — deterministic range tracker core:** implemented concrete-combo
  parsing, Hero/board blocker filtering with exact renormalization, Bayesian
  action updates with likelihood coverage and missing-data confidence
  degradation, population-prior small-sample shrinkage, and bounded multi-player
  joint assignment enumeration that excludes known-card and cross-player
  collisions. Abstract labels such as `AKs` are intentionally rejected until a
  versioned range asset expands them. Eleven focused range tests, all 317
  strategy tests, and all 749 tests in the available non-OpenCV suite passed;
  lint, byte compilation, fixture regeneration, and documentation diff checks
  passed. No initial range asset/profile event integration or multiway equity
  consumer was added yet.

- **2026-08-22 — strategy state derivation implementation:** added explicit
  legal-action amount semantics (zero/additional/total-street), deterministic
  check/bet/fold/call/raise/short-all-in generation, exact main/side-pot
  allocation with folded-player exclusion, provisional open-betting tranches,
  and settled unmatched-chip returns, plus a
  request-bound PokerState→DecisionContext builder. The builder derives active
  seats, legal actions, pots, pairwise effective stacks, strategy player count,
  missing fields, and consistency hard failures. Synthetic all-in fixtures now
  execute against the implementation with exact pot amounts, eligible seats,
  and chip conservation. The 306 strategy tests, 362 focused compatibility
  tests, and all 738 tests in the available non-OpenCV suite passed; lint, byte
  compilation, fixture regeneration, and documentation diff checks passed.
  The full suite still cannot be collected in this environment because OpenCV
  is unavailable. Real perception does not yet supply calibrated board, pot,
  stacks, actor, or actions, and no real strategy Provider or UI path was added.

- **2026-08-22 — strategy contract/router/advice implementation:** implemented
  the first target-architecture strategy slice as a separate, additive package:
  immutable 2–9-player DecisionContext inputs, provenance/quality/range
  contracts, Provider capabilities and FakeProvider, exact/approximate routing,
  strict player-count and active-count filtering, candidate legality and sizing
  normalization, versioned READY/PARTIAL/ABSTAIN/STALE Advice, request/candidate
  expiry protection, and explicit strategy schema v1 serialization. Extended
  RequestContext additively with expiry/deadline while preserving legacy v1
  deserialization. All 72 preflop player-count/action-line fixtures and all 24
  postflop street/active-count fixtures execute through the new router. The 285
  strategy tests, 341 focused compatibility tests, and 717 available non-OpenCV
  regression tests passed; Ruff/compile checks passed. No real strategy Provider,
  automatic State→Context builder, UI integration, or released behavior changed.

- **2026-08-22 — strategy mock regression corpus:** added a deterministic,
  generated v1 strategy fixture corpus with 213 Synthetic/Benchmark cases, a
  JSON schema, manifest/hash, generator, and automated coverage checks. The
  corpus covers every documented requirement and test ID, 2–9-player preflop
  action families, 2–9-way postflop streets, quality gates, stack/pot/side-pot
  boundaries, malformed payloads, Provider/Router/Fast-Slow failures, all
  Advice states, equity anchors, audit/debrief flows, and benchmark workloads.
  The 143 focused dataset tests and the available 569-test non-OpenCV suite
  passed; Ruff, byte compilation, regeneration check, and documentation diff
  checks passed. The full suite could not be collected in the available
  environment because OpenCV is not installed. Synthetic data remains
  ineligible as real Provider Golden, real capture Replay, hardware performance,
  or clean-install evidence.

- **2026-08-22 — strategy requirements and regression baseline:** reorganized
  the target design into a product requirements document, a strategy
  requirements matrix, and a separate regression test matrix. Added stable
  requirement IDs, input-processing-output gates, 2–9-player scenario
  coverage, deterministic/Golden/Replay/benchmark fixture contracts, CI test
  tiers, change-impact regression sets, release gates, and end-to-end
  traceability. Documentation checks passed; the listed target tests remain to
  be implemented alongside their functions.

- **2026-08-22 — multi-player strategy specification correction:** clarified
  that 6-max is only the first multi-player strategy-asset priority, not the
  product boundary. The post-perception router and test matrix now require
  parameterized 3–9-player preflop coverage, separate 3-way and 4-way+
  postflop coverage, exact player-count capability matching, and explicit
  internal lookup states instead of an ambiguous `miss` result. Documentation
  validation passed; implementation remains future work.

- **2026-08-22 — post-perception strategy specification:** decomposed the v0.3
  strategy path into traceable function IDs, required input and Advice output
  matrices, Provider routing rules, canonical fixtures, unit/property/golden/
  integration/performance/fault tests, and staged acceptance gates. The spec
  distinguishes state facts, range inference, Equity, Strategy, approximations,
  and refusal behavior. Documentation only; no runtime behavior changed.
- **2026-08-22 — multi-scenario/multi-player requirements:** added the product
  requirements baseline for configurable 2–9 seat state, positions, stack and
  game configurations, preflop/postflop action lines, provider capability
  routing, multiway ranges/equity, Advice provenance, refusal rules, and staged
  delivery. Heads-up remains the first demonstrable provider, not a hard-coded
  system boundary. Documentation only; no runtime behavior changed.
- **2026-08-21 — v0.3 target architecture:** replaced the frozen v0.2.1
  plan with a staged architecture for authorized, self-hosted training. The
  design adds trusted temporal perception, State/Event Engine v2, Bayesian
  range tracking, Fast/Slow strategy routing, Decision Fusion, abstention,
  and a live-to-debrief training loop. English and Chinese product docs now
  distinguish current capabilities from the M1–M5 target. The embedded-source
  draw.io SVG passed XML validation, draw.io reopen/export, and visual review;
  the full test suite and flake8 passed. Documentation only; no runtime or
  release artifact changed.
- **2026-08-21 — external project research:** added
  `docs/research-dickreuter-poker.md` after reviewing `dickreuter/Poker`.
  The research records reusable ideas for table calibration, structured
  decision inputs, strategy parameterization, and hand analysis, while
  separating them from the repository's auto-play behavior, known Monte Carlo
  test limitations, fixed-layout assumptions, and GPL-3.0 integration duties.
- **2026-08-21 — v0.1.11:** a real Windows retest showed
  Chrome exposes the table as `WePoker-H5 - Google Chrome`, while the Windows
  backend still required an exact `WePoker-H5` title. Windows matching now
  normalizes titles, accepts generic host suffixes only at explicit separator
  boundaries, supports `window_index`, and honors the existing opt-in primary
  display fallback for the full-screen WePoker calibration. It does not bind
  behavior to a Chrome-specific suffix or use arbitrary substring matching.
  Focused and full local tests, flake8, local packaging checks, macOS/Windows
  CI, both installer builds, and GitHub release upload passed. Source commit
  `f963181`; clean-user Windows retest remains pending.
- **2026-08-21 — v0.1.10:** after v0.1.9 fixed startup,
  a real Windows run exposed the next blocker: the WebView host had already
  established a non-Per-Monitor process DPI mode. `MssBackend` now uses
  Windows mixed-mode DPI and establishes Per-Monitor V2 on every capture
  worker thread before reading physical-pixel coordinates. Focused and full
  local tests, flake8, the local package checks, macOS/Windows CI (including
  Win32-specific DPI tests), both installer builds, and GitHub release upload
  passed. Source commit `94bdc47`; clean-user Windows retest remains pending.
- **2026-08-21 — v0.1.9:** fixed the Windows packaged
  app's missing `mss` dependency, wait for the local uvicorn server before
  opening the webview, and convert capture initialization/runtime failures to
  recoverable UI errors instead of closing the WebSocket. Added focused
  regression tests and a Windows workflow dependency check. Full tests and
  flake8 passed locally and on macOS/Windows CI; the local macOS bundle passed
  version, resource, signature-structure, and HTTP startup checks; both GitHub
  installers built and were published. Source commit `91de955`.
- **2026-08-21 — Windows v0.1.8 startup diagnosis:** the release workflow
  installs `.[desktop,packaging]` but omits the `perceptual` extra that provides
  `mss`.  The frozen Windows app can therefore serve its UI, but opening `/ws`
  raises an uncaught `RuntimeError` while constructing `MssBackend`; the UI
  reports a disconnect and reconnects indefinitely.  The first-launch
  `ERR_CONNECTION_REFUSED` is a separate server-readiness race because the
  webview navigates immediately after starting the server thread.  Windows has
  no macOS-style Screen Recording permission prompt.  Diagnosis was verified
  by tracing the packaging, desktop startup, WebSocket, and capture code paths;
  no product code or release artifact was changed.
- **2026-08-20 — v0.1.8:** fixed stale hero cards across hands. After two
  matching frames show a different pair, the live pipeline closes the active
  capture hand and starts a fresh hand. Regression coverage added; full test
  suite, flake8, local macOS bundle validation, and GitHub macOS/Windows
  release builds passed. Commit `e827f62` is on `main`.
- **2026-08-20 — documentation maintenance:** rewrote English and Simplified
  Chinese READMEs as concise product documentation; audited Markdown files.
  Existing design documents remain in scope and were retained.

## Open work

1. Run the new ADB path against a live Windows LDPlayer instance, measure
   capture latency/reconnect behavior, and package it only after that passes.
2. Register a privacy-reviewed, authorized raw-frame Android Replay covering
   all-in/side-pot, missed multi-action sequences, hand transitions, overlays,
   opponent current-turn evidence, and genuine failures.
3. Keep opponent current actor and every other unmeasured Android field
   `UNKNOWN`; do not infer it from the completed-action glyph.
4. Improve CI coverage so ordinary feature-branch pushes and pull requests run
   the test suite, not only `main` and release tags.
