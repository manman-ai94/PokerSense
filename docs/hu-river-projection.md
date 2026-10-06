# Declared multiway-origin river model frequencies

This opt-in research entry projects a complete declared six/eight-dealt context
onto one of the existing saved HU river assets. It reuses `RootAssetProvider`,
`DecisionContext`, `StrategyCandidate`, `StrategyRouter`, `calculate_side_pots`,
the declared-history accounting helper and the saved-policy range tracker.
It creates no solver, provider framework, production registration or real-input
evidence. The original HU query body and path replay remain unchanged.

## Entry and preserved state

```python
bridge = saved_provider.for_multiway_river(
    original_river_start,
    action_order=(4, 1),  # Explicit original OOP, IP seats.
    origin="DECLARED_SYNTHETIC",  # Or DECLARED_MANUAL.
)
declared_conditioned_ranges = bridge.river_ranges(saved_path)
frequencies = StrategyRouter((bridge,)).route(original_current_context)
advice = bridge.projected_advice(original_current_context)
```

The caller supplies both original contexts and their explicit declarations.
There is no current-state-to-start inference or missing-evidence repair.
The bound copy retains the original immutable river start; the source provider
and input contexts remain untouched. The internal PokerKit model uses role
seats 0/1 only to replay the existing saved tree. Returned candidate identity
belongs to the original hand/request/version. Evidence binds original context
and start SHA256, original dealt count, OOP/IP seat order and the saved asset.

Original capacity, dealt count, all occupied seats, identities, folded statuses,
stacks and contributions are retained. Folded money contributes to the pot.
Unknown folded cards never become blockers or invented ranges. The explicit
full postflop seat order must include the complete roster, end at its declared
dealer and filter to the supplied OOP/IP order. A position label alone never
selects OOP/IP.

## Narrow admission contract

Only the two pinned river assets in [the saved-path catalogue](hu-saved-paths.md)
are accepted: river-a starts with pot 20 and two remaining stacks 80;
river-b starts with pot 24 and stacks 72. Their fixed boards, full root combo
weights, chip quantum 1, blinds 1/2, no ante and no rake must match exactly.
The complete original roster must contain six or eight dealt players.

At the explicit river-start marker, exactly two players must remain ACTIVE
with positive stacks and zero river commitments. All others must have folded
before river. `calculate_side_pots` must reproduce exactly one positive pot
eligible to that pair, with no unmatched return. Three contenders, including
one all-in even if only two can act, and multiple pots refuse. Subsequent
catalogued all-in actions retain their contender status and are supported.

Both surviving ranges must be complete explicit distributions with source
`DECLARED_SYNTHETIC/river-start-range` or `DECLARED_MANUAL/river-start-range`.
Their combo weights must equal the selected saved asset's OOP/IP priors.
Sources/versions stay in the original namespace; `river_ranges(path)` appends
the saved-policy asset/path namespace for conditioned distributions. It uses
the existing Bayesian action updater. Inferred, partial, mismatched or missing
ranges refuse. Declared source labels and confidence do not authenticate
real-world evidence.

Required provenance fields are seats, board, Hero, pots, native legal actions,
ranges, action history, river start and action order. Each must be explicitly
VALID from CONFIG or MANUAL according to the selected declaration origin.
Every provided `observed_at` must be no later than `request.requested_at` at
binding and query. Absent optional times remain absent and do not authenticate
the declaration.
Simulation, complete declared public history and unknown folded-card
information must also be explicit. No real or vision origin is admitted.

The original public prefix must begin with a complete hand-start roster and
initial-stack ledger, include ordered preflop/flop/turn/river stages and end at
the precise river-start marker. Its versions are consecutive, identities and
source agree, times increase and no event is after the request. The reused
helper validates declared payments, folded/all-in participation and reopening;
this does not certify historical actor order, room authenticity or visual
timing. Known opponent/dead/future card payloads refuse.

Each current context must retain that exact prefix and append precisely the
saved-path events in original seats. Original contributions plus river payments,
pot eligibility, actor, stacks, effective stack, complete native legal menu and
conditioned ranges must agree with PokerKit replay. CALL is additional chips;
BET/RAISE are total-street chips. A facing bet never becomes a new ROOT.
Missing namespaces, tree-external paths, terminal/chance crossings and altered
histories refuse. Native legal intervals and the saved abstraction menu remain
separate; absent native actions receive no fabricated saved frequency.

## Qualification and limits

Queries return `HIT_APPROXIMATE` / `HEURISTIC`, confidence and match score zero,
saved model action options, source evidence and empty action EV. The declared
model ignores folded-card bunching and assumes independent surviving ranges;
it uses a restricted saved betting abstraction. It is not full multiway GTO
and makes no empirical strategy-quality claim.

`projected_advice` passes the existing FAIL hard gate
`research_river_projection_execution` to `build_advice`. Fresh requests ABSTAIN
and older requests retain STALE; neither exposes actionable advice. The result
also declares `strategy_eligible:false`, `live_eligible:false`,
`action_executable:false` and `advice_ready:false`. Model frequency lookup and
execution qualification are distinct. This entry never overrides existing
confidence, evidence, legal-action or freshness checks for display.

Shared `build_advice(context, route)` also applies the existing
`frequency_only_not_execution` candidate restriction at its built-in
`strategy_source` FAIL gate, with reason `declared_model_frequency_only`.
Caller PASS gates or math reports cannot elevate a restricted candidate;
ordinary qualified sources retain their existing confidence behavior.

## Verification scope

The portable delivery has 75 projection tests, including all 28 decisions,
start/current refusal cases, both declared origins, generic Advice admission
and provided/absent provenance time boundaries. The source qualification fix
13ba129 was independently accepted with 121 PASS / 0 FAIL, including its
original seven failure witnesses and twelve normal nodes; the author 733
was excluded from that independent denominator. See the separate
[delivery stage](HU-SAVED-DELIVERY-STAGE.zh-CN.md) for this baseline's
integration, lint and collection scope. Prior failed receipts remain outside
the public tree, unchanged; they are not relabeled as current passing tests.
