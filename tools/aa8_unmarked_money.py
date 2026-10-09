"""Development-only source-trained OCR and conditional unmarked call check."""

import argparse
from dataclasses import asdict
from decimal import Decimal
import json
from pathlib import Path

import cv2
import numpy as np

from poker_engine.perceptual.vision.gray_amount_recognizer import (
    GrayAmountRecognizer, gray_glyphs,
)
from tools.aa_amount_candidate import stack_patch
from tools.aa_pot_candidate import (
    colon_candidates, colon_x, pot_mask, prefix_score, region,
)
from tools.aa8_action_transfer import inventory, load, sha


def pot_patch(image, prefix=None, threshold=.90):
    """The pot's digits after the "底池:" label, found by matching ``prefix``
    (a reviewed rasterization of the label) at ``threshold`` or better."""
    patch = region(image)
    binary = pot_mask(patch)
    colon = colon_x(binary)
    if prefix is not None:
        matches = [x for x in colon_candidates(binary) if x >= 34 and
                   prefix_score(binary[:, x - 34:x + 2], prefix) >= threshold]
        colon = matches[0] if len(matches) == 1 else None
    if colon is None:
        return None
    ys, xs = np.where(binary[:, colon + 3:] > 0)
    if not len(xs):
        return None
    left, right = int(xs.min()) + colon + 3, int(xs.max()) + colon + 4
    top, bottom = int(ys.min()), int(ys.max()) + 1
    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    return np.pad(gray[top:bottom, left:right], 2, constant_values=int(gray.min()))


def infer_call(before, after, context):
    """Requires reviewed actor/street wager context; never infer from a pot alone."""
    unknown = {"action": None, "status": "UNKNOWN", "strategy_eligible": False}
    if not context.get("reviewed_single_action_interval"):
        return unknown
    try:
        def money(value):
            if not isinstance(value, str):
                raise ValueError("unknown amount")
            number = Decimal(value)
            if not number.is_finite() or number < 0:
                raise ValueError("invalid amount")
            return number
        a, b = ({s: money(v) for s, v in r["stacks"].items()}
                for r in (before, after))
        slot = str(context["actor"])
        if set(a) != set(b) or slot not in a:
            return unknown
        if [s for s in a if a[s] != b[s]] != [slot]:
            return unknown
        debit = a[slot] - b[slot]
        owed = money(context["street_price"]) - money(context["actor_street_wager"])
        if (debit <= 0 or owed <= 0 or debit != min(a[slot], owed)
                or money(after["pot"]) - money(before["pot"]) != debit):
            return unknown
    except (ValueError, KeyError, ArithmeticError):
        return unknown
    return {"action": "call", "all_in": b[slot] == 0, "debit": str(debit),
            "status": "CONSISTENT_WITH_REVIEWED_CONTEXT", "strategy_eligible": False,
            "visual_action_glyph_inferred": False, "context_automated": False}


def run(source, target, cash_path, profile_path, output):
    cash = json.loads(cash_path.read_text())
    profile = json.loads(profile_path.read_text())
    source_rows = inventory(source, cash["audit_sha256"])
    target_rows = inventory(target, cash["audit_sha256"])
    features, labels, provenance = [], [], []
    reference = load(source, source_rows[1500])
    binary = pot_mask(region(reference))
    colon = colon_x(binary)
    if colon is None or colon < 34:
        raise ValueError("reviewed pot prefix missing")
    prefix = binary[:, colon - 34:colon + 2]
    for checkpoint in cash["monetary_checkpoints"]:
        frame = checkpoint["frame"]
        image = load(source, source_rows[frame])
        patches = [(f"stack_{s}", v, stack_patch(image, profile["slots"][int(s)][
            "stack"])) for s, v in checkpoint["balances"].items()]
        patches.append(("pot", checkpoint["pot"], pot_patch(image, prefix)))
        for field, value, patch in patches:
            glyphs, reason = gray_glyphs(patch)
            if reason or len(glyphs) != len(value):
                continue
            for digit, (feature, _) in zip(value, glyphs):
                labels.append(digit)
                features.append(feature)
            provenance.append({"frame": frame, "field": field, "value": value,
                               "sha256": source_rows[frame]["sha256"]})
    bank = GrayAmountRecognizer(np.array(features), np.array(labels), augment=True)
    observations = []
    for frame in (4822, 4823, 4824, 4825):
        image = load(target, target_rows[frame])
        reads = {str(s): asdict(bank.diagnose(stack_patch(
            image, profile["slots"][s]["stack"]))) for s in range(8)}
        pot = asdict(bank.diagnose(pot_patch(image, prefix)))
        observations.append({"frame": frame, "stacks": {
            s: r["value"] for s, r in reads.items()}, "pot": pot["value"],
            "diagnostics": {"stacks": reads, "pot": pot}})
    context = {"actor": 0, "street_price": "221", "actor_street_wager": "63",
               "reviewed_single_action_interval": True,
               "source": "manual full-frame review; not automatically recognized"}
    load(target, target_rows[4755])
    stable = all(observations[a][field] == observations[b][field]
                 for a, b in ((0, 1), (2, 3)) for field in ("stacks", "pot"))
    context["reviewed_single_action_interval"] = stable
    result = infer_call(observations[1], observations[2], context)
    output.mkdir(parents=True, exist_ok=False)
    np.savez_compressed(output / "bank.npz", features=np.array(features),
                        labels=np.array(labels))
    report = {"observations": observations, "context": context, "result": result,
              "training": provenance, "cash_review_sha256": sha(cash_path),
              "target_manifest_sha256": sha(target / "samples.json"),
              "stable_before_and_after": stable,
              "evidence": {str(f): target_rows[f]
                           for f in (4755, 4822, 4823, 4824, 4825)},
              "bank_sha256": sha(output / "bank.npz"),
              "independent_holdout": False, "full_visual_acceptance": False}
    (output / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({"observations": [{k: v for k, v in r.items() if k != (
        "diagnostics")} for r in observations], "result": result}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("source", "target", "cash", "profile", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    args = parser.parse_args()
    run(args.source, args.target, args.cash, args.profile, args.output)
