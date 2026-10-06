# Saved HU same-street frequency queries

`research.hu_root.adapter.RootAssetProvider` reads existing saved solutions and
returns the existing `ProviderResult`, `StrategyCandidate`, and `ActionOption`
contracts. It reuses PokerKit 0.7.5 for synthetic native state replay and the
existing Bayesian range tracker for saved-policy conditioning. Querying does
not run a solver, a native `show` command, or another backend process.

The catalogue is bound to `ucsandman/postflop` revision
`5fc7ee3d92b823b6c58e4f58cbee7d50d5e9e6de` and three saved solution digests:

| Asset | SHA256 | Catalogued decisions |
| --- | --- | --- |
| river-a | `32781f1f0e28bb2e842c135dd31db19e894b1198776f2ba1fe798d2d85e46bd7` | 14, including ROOT |
| river-b | `67d3c28c6bca7e93132c2be02fad79bdf64f1e783e3d557d9892da1a1d6607ed` | 14, including ROOT |
| turn-c | `1a0a56f658cfe8285df30897bb5fb2dfdb98bd4f405db0813751838cacf662ed` | ROOT and IP after CHECK |

This adds 27 non-ROOT decision paths to the three previously validated OOP
ROOTs. The saved files omit edges and per-node boards/combo axes. The finite
catalogue follows the pinned native source's node ordering and validates the
saved menus and axes. Other turn nodes and every chance/runout crossing are
outside this contract.

## Request and action amounts

Call `provider.query(context)` with an existing `DecisionContext`. The caller
must explicitly select simulation and the model. `context_for_path` creates an
owned synthetic fixture for checks; it does not reconstruct private real hands.

The exact street start, current board, actor, seats, statuses, contributions,
pot eligibility, stacks, effective stack, rules, complete native menu, history,
and conditioned ranges must agree with replay of the declared catalogue path.
Each history event retains actor, street, total-street amount, source, and request
identity. A conflicting history or an uncatalogued action returns no candidate.

For river-a, with original street-start pot 20 and stacks 80/80:

| Path | Saved node / actor | Current pot | Street bets | Current stacks | CALL additional |
| --- | --- | --- | --- | --- | --- |
| `BET:10` | 21 / IP | 30 | 10/0 | 70/80 | 10 |
| `CHECK,BET:10,RAISE:50` | 6 / IP | 80 | 50/10 | 30/70 | 40 |

`BET:n` and `RAISE:n` mean total-street chips. `ALLIN` maps to the original
street stack as a total-street BET or RAISE. CALL is an additional amount in the
native legal menu and the separate model menu. The existing `ActionOption`
leaves CALL `amount` empty. It never converts a facing-bet state into a fresh
ROOT using the current pot.

The complete native legal menu and the saved abstraction menu remain separate.
For example, node 6's abstraction has FOLD/CALL after its model raise cap, while
the native menu can still permit another raise. No frequency is invented for a
native action absent from the saved abstraction.

The original entry requires two dealt, nonfolded pot contenders. Table capacity
6 or 8 can accompany two dealt seats. Six/eight dealt histories are unsupported
by that entry. The separate opt-in [declared river projection](hu-river-projection.md)
preserves complete original rosters and exposes approximate model frequencies
only under its narrower river-start, pot, range and execution-gate contract.
An all-in seat retains pot eligibility. Three contenders with one all-in remain
outside this HU asset even when only two seats can act.

## Frequencies and verification

Saved action-major f32 rows are checked and normalized within the declared
`1e-6` mass tolerance. Path candidates use 30 decimal places, assigning the tiny
remaining mass to the largest branch, so grouped action probabilities satisfy
the existing exact candidate contract. Policy range likelihoods keep their
original precision. ROOT conversion is unchanged. Action EV stays empty and
confidence stays zero; these synthetic model frequencies do not certify
empirical ranges, equilibrium quality, or live eligibility.

The portable delivery reruns the 27 original path tests, 24 ROOT regressions,
and 3 ordinary Decimal routing tests with repository-contained assets.
Prior original 0/27 failure evidence and the separate 1072-row sweep are
preserved as predecessor evidence; neither is added to the current denominator.
See [the delivery stage](HU-SAVED-DELIVERY-STAGE.zh-CN.md) for integration,
projection and independent-review status. Full repository execution, full turn
BR, chance crossings and real range/live qualification remain separate.
