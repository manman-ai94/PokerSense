"""Build the digit bank for the AA mushroom pool badge from recordings.

    PYTHONPATH=src:. .venv/bin/python tools/build_aa_mushroom_bank.py \\
        --recording <PokerSense_private/aa-mac-recordings/录像目录> [...] \\
        [--crops <badges.bgr> ...] [--post 6] [--out <目录>] [--sheet]

Each recording is sampled at 2 frames a second (``--crops``: the same 130x60
crops, phone x 0-130 and y 90-150, as raw BGR, e.g. from ffmpeg
``crop=130:60:711:90,fps=2 -f rawvideo -pix_fmt bgr24``). The badge is read
with the stacks' digit bank first. Its values are labelled from the table's
rule rather than by hand: from one hand to the next the pool grows by the
post (``--post``, 6 at 1/2/4) or starts again at one post when the small
blind took it, so

- a value read on at least two frames running is kept when it follows the
  value read before it, or the value read after it follows it (the same, plus
  the post, or one post);
- a frame with the icon showing but no value read (two digits touching, a
  low score) between two kept values ``a`` and ``b`` takes its best guess when
  that is ``a`` or ``a`` plus the post and ``b`` follows it.

Each labelled badge gives one sample per digit (split as the live reader
splits them); at most ``--per-digit`` samples per digit are kept, spread over
the recordings, and added to the stacks' bank so every digit has samples.
The bank, a report and (``--sheet``) a picture of every digit's samples for
review go to ``--out`` (default: ``aa_mushroom_bank_v1`` in the private data
folder). Never commit the bank: it is cut from recordings.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from poker_engine.data_paths import private_root
from poker_engine.desktop.aa_mushroom import (
    BANK, DIGITS, ICON, MARGIN, glyph_patches, read_digits)
from poker_engine.perceptual.vision.gray_amount_recognizer import (
    GrayAmountRecognizer, gray_glyphs)

CROP = (0, 90, 130, 60)             # x, y, width, height of a crop on the table
SEED_BANK = "aa8_reviewed_money_bank_v2_wager58/bank.npz"
RATE = 2.0                          # samples a second
COLUMNS = (711, 1209)               # the phone in a 1920x1080 capture


def from_crop(crop, rect):
    x, y, w, h = rect
    return crop[y - CROP[1]:y - CROP[1] + h, x - CROP[0]:x - CROP[0] + w]


def crops_from_file(path):
    width, height = CROP[2], CROP[3]
    return np.fromfile(path, np.uint8).reshape(-1, height, width, 3)


def crops_from_recording(folder):
    """2 crops a second from a recording folder's segments, in order."""
    crops = []
    for segment in sorted(Path(folder).glob("segment_*.mp4")):
        video = cv2.VideoCapture(str(segment))
        fps = video.get(cv2.CAP_PROP_FPS) or 30.0
        step, index, due = fps / RATE, 0, 0.0
        while True:
            ok, frame = video.read()
            if not ok:
                break
            if index >= due:
                phone = frame[:, COLUMNS[0]:COLUMNS[1]]
                x, y, w, h = CROP
                crops.append(phone[y:y + h, x:x + w].copy())
                due += step
            index += 1
        video.release()
    return np.array(crops)


def icon_visible(crop):
    hsv = cv2.cvtColor(from_crop(crop, ICON), cv2.COLOR_BGR2HSV)
    red = (((hsv[..., 0] <= 8) | (hsv[..., 0] >= 170))
           & (hsv[..., 1] >= 120) & (hsv[..., 2] >= 120))
    return float(red.mean()) >= 0.08


def runs(reads):
    """[(start, end, value)] of frames with the icon; value None if unread."""
    out = []
    for index, (shown, value, _) in enumerate(reads):
        if not shown:
            continue
        if out and out[-1][1] == index and out[-1][2] == value:
            out[-1][1] = index + 1
        else:
            out.append([index, index + 1, value])
    return [tuple(run) for run in out]


def label_runs(reads, post):
    """The frames given a value by the pool's rule: [(start, end, value)]."""
    known = [run for run in runs(reads) if run[2] is not None and run[1] - run[0] >= 2]

    def follows(before, value):
        return value in (before, before + post, post)

    labelled = []
    for i, run in enumerate(known):
        value = int(run[2])
        before = int(known[i - 1][2]) if i else None
        after = int(known[i + 1][2]) if i + 1 < len(known) else None
        if (before is not None and follows(before, value)
                or after is not None and follows(value, after)):
            labelled.append((run[0], run[1], value))
    # Unread frames between two kept values: their best guess, when it is the
    # value before or one post more and the value after follows it.
    for (_, end, a), (start, _, b) in zip(list(labelled), labelled[1:]):
        for index in range(end, start):
            shown, value, raw = reads[index]
            if not shown or value is not None or not (raw or "").isdigit():
                continue
            guess = int(raw)
            if guess in (a, a + post) and follows(guess, b):
                labelled.append((index, index + 1, guess))
    return sorted(labelled)


def samples(crops, labelled):
    """(feature, digit, frame) for every digit of every labelled frame."""
    out = []
    for start, end, value in labelled:
        text = str(value)
        for index in range(start, end):
            patches = glyph_patches(from_crop(crops[index], DIGITS))
            if len(patches) != len(text):
                continue
            for patch, digit in zip(patches, text):
                glyphs, reason = gray_glyphs(patch)
                if reason is None and len(glyphs) == 1:
                    out.append((glyphs[0][0], digit, index))
    return out


def spread(rows, limit):
    """At most ``limit`` rows, evenly over the list."""
    if len(rows) <= limit:
        return rows
    picks = np.linspace(0, len(rows) - 1, limit).round().astype(int)
    return [rows[i] for i in picks]


def sheet(features, labels, path):
    lines = []
    for digit in "0123456789":
        tiles = [features[i] for i in range(len(labels)) if labels[i] == digit][:40]
        row = np.zeros((28, 28 * 40), np.float32)
        for i, tile in enumerate(tiles):
            row[:, i * 28:(i + 1) * 28] = tile
        lines.append(row)
    image = (np.vstack(lines) * 255).astype(np.uint8)
    cv2.imwrite(str(path), cv2.resize(image, None, fx=2, fy=2,
                                      interpolation=cv2.INTER_NEAREST))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--recording", type=Path, action="append", default=[])
    parser.add_argument("--crops", type=Path, action="append", default=[])
    parser.add_argument("--post", type=int, default=6)
    parser.add_argument("--per-digit", type=int, default=80)
    parser.add_argument("--seed-bank", type=Path, default=private_root() / SEED_BANK)
    parser.add_argument("--out", type=Path, default=(private_root() / BANK).parent)
    parser.add_argument("--sheet", action="store_true")
    args = parser.parse_args(argv)
    with np.load(args.seed_bank, allow_pickle=False) as data:
        seed_features, seed_labels = data["features"], data["labels"]
    seed = GrayAmountRecognizer(seed_features, seed_labels, margin=MARGIN, augment=True)
    sources = ([(str(path), crops_from_recording(path)) for path in args.recording]
               + [(str(path), crops_from_file(path)) for path in args.crops])
    report, found = {"post": args.post, "sources": []}, {}
    for name, crops in sources:
        reads = []
        for crop in crops:
            shown = icon_visible(crop)
            read = read_digits(seed, from_crop(crop, DIGITS)) if shown else None
            reads.append((shown, read and read.value, read and read.raw_text))
        labelled = label_runs(reads, args.post)
        rows = samples(crops, labelled)
        for row in rows:
            found.setdefault(row[1], []).append(row)
        report["sources"].append({
            "source": name, "frames": len(crops),
            "icon_frames": sum(shown for shown, _, _ in reads),
            "labelled_frames": sum(end - start for start, end, _ in labelled),
            "values": sorted({value for _, _, value in labelled}),
            "samples": len(rows)})
    kept = {digit: spread(rows, args.per_digit)
            for digit, rows in sorted(found.items())}
    features = np.concatenate([seed_features] + [
        np.array([row[0] for row in rows], np.float32) for rows in kept.values()])
    labels = np.concatenate([seed_labels] + [
        np.array([row[1] for row in rows]) for rows in kept.values()])
    report["mushroom_samples"] = {digit: len(rows) for digit, rows in kept.items()}
    report["seed_samples"] = len(seed_labels)
    args.out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.out / "bank.npz", features=features, labels=labels)
    (args.out / "report.json").write_text(json.dumps(report, indent=1),
                                          encoding="utf-8")
    if args.sheet:
        mushroom = len(seed_labels)
        sheet(features[mushroom:], labels[mushroom:], args.out / "digits.png")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
