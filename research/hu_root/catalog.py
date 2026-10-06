"""Finite decision catalogue for three existing SHA-bound native assets.

Reuse frozen_postflop._DECISIONS' catalogue approach, not a tree builder.
At pin 5fc7ee3, tree.rs:486-551 reserves the parent, then recursively builds
Check, Fold/Call and sizing children in that order. The 39-node river assets
have the following fourteen decisions. Their complete saved node/action order
matches this explicit catalogue. Turn only binds ROOT and its first Check
child (node 1); its file omits edges and per-node boards/combo axes, so other
turn paths and all chance crossings are deliberately absent.
"""
from decimal import Decimal


ASSETS = {
    "32781f1f0e28bb2e842c135dd31db19e894b1198776f2ba1fe798d2d85e46bd7":
        ("river-a", 39, 14),
    "67d3c28c6bca7e93132c2be02fad79bdf64f1e783e3d557d9892da1a1d6607ed":
        ("river-b", 39, 14),
    "1a0a56f658cfe8285df30897bb5fb2dfdb98bd4f405db0813751838cacf662ed":
        ("turn-c", 8247, 2990),
}
CATALOG_VERSION = "saved-same-street-catalog-v1"


def line(path):
    return "hu-root:" + (",".join(path) or "ROOT")


def chip_text(value):
    return format(Decimal(value).normalize(), "f")


def decisions(asset_sha, config):
    """Literal known decisions: path -> (node, actor, street bets)."""
    if asset_sha not in ASSETS:
        return {}
    pot = Decimal(str(config["starting_pot"]))
    stack = Decimal(str(config["effective_stack"]))
    half = pot / 2
    b50, b100 = "BET:" + chip_text(half), "BET:" + chip_text(pot)
    raise_, check, allin = "RAISE:" + chip_text(5 * half), "CHECK", "ALLIN"
    root = {(): (0, 0, (0, 0)), (check,): (1, 1, (0, 0))}
    if ASSETS[asset_sha][0] == "turn-c":
        return root
    return {
        **root,
        (check, b50): (3, 0, (0, half)),
        (check, b50, raise_): (6, 1, (5 * half, half)),
        (check, b50, allin): (9, 1, (stack, half)),
        (check, b100): (12, 0, (0, pot)),
        (check, b100, allin): (15, 1, (stack, pot)),
        (check, allin): (18, 0, (0, stack)),
        (b50,): (21, 1, (half, 0)),
        (b50, raise_): (24, 0, (half, 5 * half)),
        (b50, allin): (27, 0, (half, stack)),
        (b100,): (30, 1, (pot, 0)),
        (b100, allin): (33, 0, (pot, stack)),
        (allin,): (36, 1, (stack, 0)),
    }
