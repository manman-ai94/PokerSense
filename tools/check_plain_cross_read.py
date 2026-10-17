"""两处读数对上才算读到（往前带的你的筹码、按两处读数对上的价格）在实录上的核对。

    PYTHONPATH=src:. .venv/bin/python tools/check_plain_cross_read.py \\
        --frames <录像>/frames.jsonl [...] --out <汇总.json>

Each window log (``frames.jsonl``, or the same gzipped) is replayed with this
checkout's plain path (``aa_plain_advice``, on the recording's clock, as
``tools/plain_live_report.py`` does), twice: with the two cross-checked
readings off (as before them) and on. On every frame with your buttons up:

* **stack**: where a carried stack can be worked out even though your stack
  was read (``carried_stack(shadow=True)``), it is compared with that read:
  every disagreement is a carried stack that would have been wrong;
* **price**: where a price from two readings can be worked out even though
  the button's amount was read (``derived_price(shadow=True)``), it is
  compared with the button's: every disagreement would have been a wrong
  price. Logs written before ``raw_call_amount`` was logged have no doubtful
  digits, so only the chips-and-pot-rise check is seen on them;
* **decisions**: iron rule 5 for want of a reading, off against on, by what
  was missing; and decisions whose advice changed;
* **tails** (``--tails``): the stack check again with other numbers of a
  hand's last frames left out of the carried reading (``aa_plain_advice.TAIL``),
  to see whether fewer would carry more stacks without a disagreement. The
  gate is on the window's own ``TAIL``.

Only totals are written: no hand, no card, no amount of a hand.
"""

from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal
import gzip
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from poker_engine.desktop import aa_plain_advice as live  # noqa: E402

HERO = live.HERO


def load(path):
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        return [row for row in (json.loads(line) for line in handle if line.strip())
                if row.get("fields")]


def log_name(path):
    path = Path(path)
    if path.name in ("frames.jsonl", "frames.jsonl.gz"):
        return path.parent.name
    return path.name.split(".")[0]


class _Off:
    """The two cross-checked readings switched off (the window before them)."""

    def __enter__(self):
        self.saved = live.carried_stack, live.HandState.derived_price
        live.carried_stack = lambda *args, **kwargs: None
        live.HandState.derived_price = lambda self, controls, shadow=False: None

    def __exit__(self, *exc):
        live.carried_stack, live.HandState.derived_price = self.saved


def decisions(rows):
    """{(hand, street, price, decision): plain row} as the replay gives them."""
    now = [0.0]
    advice = live.AAPlainAdvice(clock=lambda: now[0])
    found = {}
    for row in rows:
        now[0] = row.get("pts_seconds") or now[0]
        report = advice.observe_fields(row["fields"], row["processed"])
        if report.get("status") == "ready" and report.get("kind") == "plain":
            key = (advice._hand_id, report.get("street"), report.get("price"),
                   report.get("decision"))
            found.setdefault(key, report["plain"])
    return found


def shadow(rows, tail=None):
    """Carried stacks and derived prices against what was read, frame by frame
    (``tail``: a hand's last frames left out of the carried reading)."""
    saved = live.TAIL
    live.TAIL = saved if tail is None else tail
    try:
        return _shadow(rows)
    finally:
        live.TAIL = saved


def _shadow(rows):
    now = [0.0]
    advice = live.AAPlainAdvice(clock=lambda: now[0])
    counts = Counter()
    stack_diffs, price_diffs = Counter(), Counter()
    stack_hands, rescued_hands = {}, set()
    for row in rows:
        now[0] = row.get("pts_seconds") or now[0]
        fields = row["fields"]
        advice.observe_fields(fields, row["processed"])
        state = advice.state
        controls = fields.get("hero_controls") or {}
        if state is None or not controls.get("visible"):
            continue
        counts["turn_frames"] += 1
        stakes = advice.stakes()
        read = state.stack_read(HERO)
        sure = live.price(controls, read)
        to_call = state.price(controls)
        if read is None:
            counts["stack_unread_frames"] += 1
            if live.carried_stack(state, stakes, controls, to_call) is not None:
                counts["stack_carried_frames"] += 1
                rescued_hands.add(advice._hand_id)
        else:
            carried = live.carried_stack(state, stakes, controls, to_call, shadow=True)
            if carried is not None:
                same = carried == read
                counts["stack_check_frames"] += 1
                counts["stack_agree_frames" if same else "stack_disagree_frames"] += 1
                stack_hands.setdefault(advice._hand_id, set()).add(same)
                if not same:
                    stack_diffs[str(carried - read)] += 1
        if sure is None:
            if controls.get("button") == "call":
                counts["price_unread_call_frames"] += 1
                if state.derived is not None:
                    counts["price_derived_frames"] += 1
        else:
            derived = state.derived_price(controls, shadow=True)
            if derived is not None:
                same = derived == sure
                counts["price_check_frames"] += 1
                counts["price_agree_frames" if same else "price_disagree_frames"] += 1
                if not same:
                    price_diffs[str(derived - Decimal(sure))] += 1
    counts["stack_check_hands"] = len(stack_hands)
    counts["stack_disagree_hands"] = sum(1 for seen in stack_hands.values()
                                         if False in seen)
    counts["stack_carried_hands"] = len(rescued_hands)
    return counts, stack_diffs, price_diffs


def iron5(found):
    return Counter(row.get("unread") for row in found.values() if row.get("unread"))


def log_report(rows, tails=()):
    with _Off():
        before = decisions(rows)
    after = decisions(rows)
    counts, stack_diffs, price_diffs = shadow(rows)
    changed = Counter()
    for key, row in after.items():
        old = before.get(key)
        if old is None:
            changed["new_decision"] += 1
        elif (old.get("action"), old.get("rule"), old.get("to")) != (
                row.get("action"), row.get("rule"), row.get("to")):
            was, now = old.get("unread") or "read", row.get("unread") or "read"
            changed[f"{was}->{now}"] += 1
    return {"decisions_off": len(before), "decisions_on": len(after),
            "iron5_off": dict(iron5(before)), "iron5_on": dict(iron5(after)),
            "changed": dict(changed), "counts": dict(counts),
            "stack_differences": dict(stack_diffs),
            "price_differences": dict(price_diffs),
            "tails": {str(tail): _tail(shadow(rows, tail)[0]) for tail in tails}}


def _tail(counts):
    return {key: counts[key] for key in ("stack_carried_frames", "stack_carried_hands",
                                         "stack_check_frames", "stack_disagree_frames")}


def summarize(reports):
    total = {"decisions_off": 0, "decisions_on": 0}
    sums = {key: Counter() for key in ("iron5_off", "iron5_on", "changed", "counts",
                                       "stack_differences", "price_differences")}
    tails = {}
    for report in reports.values():
        for tail, counts in report["tails"].items():
            tails.setdefault(tail, Counter()).update(counts)
        total["decisions_off"] += report["decisions_off"]
        total["decisions_on"] += report["decisions_on"]
        for key, counter in sums.items():
            counter.update(report[key])
    total.update({key: dict(counter) for key, counter in sums.items()})
    total["tails"] = {tail: dict(counts) for tail, counts in tails.items()}
    counts = sums["counts"]
    total["gate"] = {
        "stack_disagree_frames": counts["stack_disagree_frames"],
        "price_disagree_frames": counts["price_disagree_frames"],
        "pass": not counts["stack_disagree_frames"]
        and not counts["price_disagree_frames"]}
    return total


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--frames", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--tails", default="",
                        help="其他要比的 TAIL，逗号分开，如 0,3,5")
    args = parser.parse_args(argv)
    tails = [int(tail) for tail in args.tails.split(",") if tail.strip()]
    reports = {}
    for path in args.frames:
        reports[log_name(path)] = log_report(load(path), tails)
        print(log_name(path), json.dumps(reports[log_name(path)]["counts"]),
              file=sys.stderr)
    result = {"logs": reports, "total": summarize(reports)}
    text = json.dumps(result, ensure_ascii=False, indent=1)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(json.dumps(result["total"], ensure_ascii=False))
    return 0 if result["total"]["gate"]["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
