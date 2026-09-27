# PokerSense

The current increment is **AA engineering preview 0.2.0.dev1**. Windows packaging
now uses the dedicated AA entry; `launch/aa/START-AA.cmd` opens its local offline UI.
It adds ten-second turn deadline primitives, stale-result rejection, a killable
preloaded shadow policy process, and a 6/7/8-player full-hand simulation, bounded
MCCFR trainer and paired evaluator. **Live action advice remains disabled:** there
is no validated production turn-time source or qualified policy asset. Physical
end-to-end latency and empirical strategy strength remain unverified. Capture and
model APIs are off by default; private recognition models remain external.
See the [implementation and acceptance checklist](docs/AA-TEN-SECOND-IMPLEMENTATION.zh-CN.md),
including the corrected attribution of this increment's short training probe.
The original 378 failures were adapter binding errors, not measured coverage
misses. An actual rerun after repairing the salt contract separately confirmed
unknown information sets; see the [correction](docs/AA-EVALUATION-CORRECTION-V1.zh-CN.md).
The [bounded study command](docs/AA-SELF-PLAY-STUDY.zh-CN.md) freezes and executes
all nine player-count/seed configurations, retaining failures without automatic
tuning, best-seed selection, paid calls, or live promotion.

## AA eight-seat development monitor

Critical board, participation, ALL-IN and river-first-actor candidates now carry
source and temporal evidence. Snapshot prefill rejects missing, stale or conflicting
critical evidence; older raw-only records or cached projections without causal
evidence retain their candidates but may require
manual input. The current native card crop must also support a temporal board
candidate. These checks do not establish visual accuracy or real-hand acceptance.
See the [five-field verification contract](docs/AA-CRITICAL-PERCEPTION-VERIFICATION.zh-CN.md).
Perception-only validation explicitly disables the river analysis sidecar.

The [TARGET-S confirmation contract](docs/AA-REAL-HAND-CONFIRMATION-V1.zh-CN.md)
uses a separate evidence-bound confirmation history. Legacy confirmation records
are not automatically upgraded. Confirmed facts and current receipts do not imply
PHH readiness, strategy eligibility, independent vision acceptance or profitability.

[V5 offline review and conditional river bounds](docs/AA-STRATEGY-ENTRY-V5.zh-CN.md) adds saved-frame candidate inputs and a plain form that calculates and preserves conservative payoff bounds without an API key. Unknown fees do not produce a net-payoff guarantee. Opening/commitment continuity and call-price observations improve; a strong full-street policy and profitability remain unvalidated.

Saved frames can seed a source-labelled manual river-analysis draft; missing ranges, fees and commitments remain unfilled. This does not emit live advice. The observation page polls every 250ms; end-to-end capture/display latency remains to be measured.

The [focused observation and vision review desk](docs/AA-REVIEW-DESK-AND-VISION-API.zh-CN.md) separates observation, saved reviews and settings. Mark a frame without stopping observation, retain human correction history, and explicitly submit that saved image and its fields to DeepSeek for candidate review. The API key stays in server memory and must be re-entered after restart. Daily request caps apply; AI output never automatically trains models or enables live strategy.

An explicitly authorized live round can also sample at most once per 30 seconds, with at most 20 attempts, sending those images and fields to DeepSeek. The finite sampler stops after source/session changes or observation stops. Timed receipts remain separate from human confirmation; rounds do not renew automatically.

The portrait source preview is larger and includes a scrollable live image dialog. Closing it keeps playback running. See the [manual first-hand review steps](docs/AA8-FIRST-HAND-REVIEW-20260915.zh-CN.md#人工复查操作); the dialog does not pause or save frames.

The [action/settlement interpretation layer](docs/AA8-ACTION-SEMANTICS-AND-SETTLEMENT.zh-CN.md) now separates bet/raise/call from all-in using pre-debit observations and keeps historical commitments out of the current cleared-pot difference. Original observations and unknown monetary attribution remain intact; this does not authorize live strategy.

The [current AA workflow](docs/AA-TABLE-VALIDATION-V2.zh-CN.md) adds manual per-table rules, continuous development replay, explicit local issue snapshots and isolated manual river analysis. [Portable private resource bundles](docs/AA-RUNTIME-BUNDLE.zh-CN.md) remove old checkout path dependencies. Conditional examples remain separate from live observations and are not evidence of strategy profitability.

A dedicated AA entry now provides explicit start/stop, device selection, registered development-frame replay, eight-seat candidate fields, preview and stale/error clearing. See [AA monitor setup and limitations](docs/AA-LIVE-MONITOR-V1.zh-CN.md). Source-based replay and browser controls were exercised; physical capture, complete legal state and reliable multiway strategy remain unverified. Private model references stay external to the public repository and executable.

[简体中文](README.zh-CN.md) | **English**

Current execution: [AA vision-first plan](PLAN-AA-vision-first.zh-CN.md), with
the [video-first WPK plan](PLAN-WPK-video-first.zh-CN.md) retained for regression.
Use the existing recordings for development before final hardware acceptance.
The [NLHE rulebook](docs/WPK-RULEBOOK.zh-CN.md) has independent executable examples.

Capture-card temporal protection has reached the local v9 candidate. Production
card acceptance stays disabled; offline diagnostics remain available. Historical
metrics do not validate the current pipeline. After a frame-source fault, the
local build discards temporary evidence and emits an unavailable, no-advice
snapshot before retrying, without deleting hand history. Controlled continuity
tests pass; real device/browser recovery still needs acceptance. See the
[continuity report](docs/WPK-V8-CONTINUITY-REVIEW.zh-CN.md).
Conflicting accepted current/fused card identities trigger abstention and a new
evidence window; see the [v9 tradeoffs](docs/WPK-V9-HANDOFF-REVIEW.zh-CN.md).
Pixel repetition is diagnostic only: still images do not prove a freeze, and
advancing host frame ids do not prove that the source is current.

PokerSense is a real-time Texas Hold'em training companion. Current local work
targets **AA Poker on a phone through a capture card: eight physical slots and
6–8 dealt players**. WPK remains a regression platform. The local build counts
active opponents for uniform-random showdown
equity and provides editable blinds, antes, rake/cap and straddle settings.
Dynamic capture-card recognition and postflop strategy are not yet accepted;
a working simulation or saved configuration is not proof of strategy coverage
or profitability. See [local WPK progress](docs/wpk-progress-2026-09-08.md).
The native app accepts only a physical phone capture card. LDPlayer/ADB is not
a selectable product source because both AA Poker and WePoker restrict emulator
logins. Historical ADB code and evidence remain for offline regression only.

PokerSense is not an autoplay bot. It never clicks, types, places bets, or
controls a poker client. The human remains the only executor. The intended
environment is a private table with friends, coaching, and deliberate practice.

## Historical ADB evidence (not selectable)

The table below records prior **portrait LDPlayer** calibration evidence. It is
kept to explain historical tests and must not be used as a deployment option or
as capture-card acceptance evidence.

| Feature | Availability |
|---|---|
| Windows LDPlayer capture over ADB | Historical regression only; the product CLI rejects `--source adb` |
| WePoker Android 1440×2560 portrait hero cards | Calibrated |
| WePoker Android board cards and street | Calibrated; deal/flip transitions fail closed |
| WePoker Android pot | Calibrated for the global total-pot banner; labels and overlays abstain |
| WePoker Android visual-slot stacks | Calibrated across eight fixed seat slots; empty/covered slots abstain |
| WePoker Android seat occupancy and positions | Calibrated across eight slots; a versioned Android mapping derives canonical seats and positions |
| WePoker Android Dealer marker | Calibrated as a visual slot and mapped only through the versioned Android seat contract |
| Equity calculation | Available for the recognized visible cards against a random range |
| English and Simplified Chinese UI | Available; preference persists across restarts |
| Hero actor and completed visual-slot actions | Hero decision turn and fold/check/call/bet/raise/all-in are calibrated; opponent current-turn timers still abstain |
| Canonical action history and amounts | Completed action glyphs are deduplicated and mapped; amounts are accepted only when stack delta and pot evidence agree |
| Explainable advice, range tracking, and training feedback | Contracts and UI exist; live actions remain withheld without a qualified multiplayer strategy Provider |
| Automated play or client control | Never provided |

When a newly dealt pair of hero cards is confirmed in consecutive frames,
PokerSense starts a new hand automatically. A transient frame during a deal is
not used as a state update.

Android calibration now combines the original 66 deduplicated ADB frames with
234 full-resolution table frames and an 88-minute temporal recording. Each
field keeps independent evidence. Occupancy was reviewed in 272 stable slot
states, the Hero actor detector accepted 33 decision frames and abstained on
the other 201 frames, and Dealer/stack/action observations remain bound to the
versioned Android mapping. Private raw captures and the recording remain
outside Git and packages.

## Release status

The canonical repository has no accepted new Release. Historical v0.1.11 generic
installers do not represent the current AA product. The 0.2.0.dev1 Windows preview
uses the AA entry and requires the complete `PokerSense-AA` folder. Installer,
hardware, physical latency and strategy qualification are separate acceptance
steps; an offline EXE smoke check does not establish live readiness.

## Emulator source disabled

`--source adb` is rejected by both desktop entry points. The retained ADB
backend is an internal historical regression dependency and must not be wired
back into the user-facing source list. Current development uses existing offline
AA capture-card recordings; later hardware checks use a physical phone and UVC
capture card. This does not authorize live advice or client control.

## Passive AA capture intake

The AA intake tool records video only from the declared physical phone and UVC
capture card after a one-time human authorization. Recognition, strategy,
Advice, automated input, networking, audio, emulators, and ADB are fixed off.
Missing or expired authorization, nonce reuse, an existing output directory, or
any enabled forbidden capability is rejected before FFmpeg starts. Every new
recording enters a private quarantine as 60-second segments with a hash receipt;
a successful recording is still not calibration or strategy evidence. See the
[passive AA capture intake V1 contract](docs/AA-PASSIVE-CAPTURE-INTAKE-V1.zh-CN.md).

## Privacy

Normal desktop recognition processes capture-card frames in memory and discards
them without keeping screenshots, video, or frame history. Only an explicitly
authorized passive AA intake session writes raw video-only segments under
`G:/PokerSense_private`. Those segments, screen names, and private identity maps
must not enter GitHub, pull requests, or packages. Private calibration captures
remain excluded as well; only small redacted regression fixtures belong in Git.

The interface language is persisted separately from editable table rules:

- macOS: `~/Library/Application Support/PokerSense/settings.json`
- Windows: `%APPDATA%\\PokerSense\\settings.json`

The file contains one of `auto`, `en`, or `zh`. `auto` follows the system
language. Table rules are stored in `table-rules.json` in the same directory;
changing language does not overwrite them. Diagnostic video tools read only the
explicit local archive supplied by the operator.

## Development

Python 3.11–3.13 is supported.

```bash
# Install development dependencies
pip install -e ".[dev,desktop,perceptual]"

# Run checks
make test
make lint

# Start the desktop app
make run-desktop

# Start the local server only
make run-desktop-server

# Build a local application bundle
pip install -e ".[dev,desktop,packaging]"
make package
```

The desktop composition lives in `src/poker_engine/desktop/`; the live update
loop is in `src/poker_engine/realtime/`; platform-specific calibration is under
`configs/`.

## Recognition and calibration

PokerSense uses OpenCV template matching and a per-platform layout map. The
WePoker Android hero-card geometry and confidence are measured on real ADB frames;
details and source calibration data are in:

- [`configs/platform/wepoker_android__ldplayer_portrait_1440x2560.json`](configs/platform/wepoker_android__ldplayer_portrait_1440x2560.json)
- [`configs/vision/wepoker_android/calibration.json`](configs/vision/wepoker_android/calibration.json)
- [`docs/vision-engine.md`](docs/vision-engine.md)

Fields without their own calibration are reported as unavailable rather than
guessed.

## Target architecture

![PokerSense v0.3 target architecture](docs/realtime-training-assistant.drawio.svg)

The SVG embeds its draw.io source and can be opened directly in draw.io. The
first result comes from a deterministic local Fast Path. Close decisions and
cache misses may start an asynchronous local resolver, but stale results are
discarded. Critical state uncertainty produces `ABSTAIN`, not a guess.

```text
Authorized table → Capture → Vision → Temporal Consensus → Confidence Gate
  → State/Event Engine v2 → DecisionContext
  → Range + Equity + Strategy Router → Decision Fusion → Advice → Live Coach UI
  → Human action → Hand Memory → Debrief / drills → better priors
```

The canonical design, latency budget, algorithms, contracts, and milestone
exit criteria are in [`architecture.md`](architecture.md).

## Project structure

| Area | Location |
|---|---|
| Domain types and state transitions | `src/poker_engine/core/`, `src/poker_engine/state_engine/` |
| Capture and vision | `src/poker_engine/perceptual/` |
| Equity and real-time pipeline | `src/poker_engine/equity/`, `src/poker_engine/realtime/` |
| Desktop application | `src/poker_engine/desktop/`, `ui/` |
| Tests | `tests/` |
| Platform calibration | `configs/` |

For detailed subsystem notes, see [`docs/`](docs/).

## Roadmap

1. **M1 — trustworthy Android table state:** calibrate board, pot, stacks, seats, dealer, actor,
   and actions; add temporal consensus, betting legality, hand boundaries, and
   chip conservation.
2. **M2 — explainable baseline advice:** add `DecisionContext`, Bayesian combo
   ranges, preflop DB, range equity, action EV, and a measured p95 ≤300 ms Fast
   Path.
3. **M3 — presolved library and training loop:** canonical solution bundles,
   EV-loss debriefs, leak classification, and drills using the live interfaces.
4. **M4 — robust opponent adjustment:** shrink small samples toward population
   priors and bound exploit adjustments with KL regularization.
5. **M5 — asynchronous local resolution:** start with river subgames, enforce
   compute budgets, and discard stale results.

Detailed deliverables and exit criteria are in
[`architecture.md` §9](architecture.md#9-最优实施路线).
# Offline AA observation viewer

Run `python -m tools.aa_replay_viewer --observations <pinned-log-path>` from the repository,
then open `http://127.0.0.1:8766`. This separate read-only viewer accepts only the pinned
0–1800 observation replay. It starts no capture or strategy. Missing features and
unrecorded confidence/rejection details remain explicit. See the
[viewer guide](docs/AA-REPLAY-VIEWER-V1.zh-CN.md).
