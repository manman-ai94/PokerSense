# Frozen synthetic HU frequency entry

This research entry reads a pinned saved solution using the existing provider
and candidate contracts. It supports four fixed river decisions and eight
combo rows, with exact chips, ranges, actor, board, menu and path declarations.
It is also the source of shared combo/JSON/Decimal helpers used by the
[larger saved-path adapter](hu-saved-paths.md).

From a source checkout with the existing dependencies available:

```powershell
python tools/query_frozen_postflop.py --request docs/examples/frozen-postflop/root-oop-aa.json
```

The other synthetic example requests are `ip-after-check-ak.json`,
`oop-facing-bet-aa.json` and `ip-facing-bet-tt.json` in the same directory.
The CLI produces JSON and never starts a solver, native show or backend process.
It is independent of the desktop viewer and production registry.

The source engine is `ucsandman/postflop`, fixed at
`5fc7ee3d92b823b6c58e4f58cbee7d50d5e9e6de`; the bundled synthetic solution SHA256
is `17144742e1597990b74070d3652f47fad015a74a2c00e357a7cbe8f36c72314b`.
See [source notices and pins](../third_party/SOURCES.md).

Action EV is absent and confidence is zero. Aggregate profile EV/raw BR fields
are saved model metadata; they are not action EV or an empirical strategy score.
The asset does not declare a BB value, so BB metrics remain empty. Missing or
conflicting declarations, unknown paths and live mode refuse. No live, full-game,
empirical range or profitability claim follows from these model frequencies.
