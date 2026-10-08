"""Additional live hand-boundary evidence without modifying the frozen reader."""

from collections import deque
from copy import deepcopy
from decimal import Decimal
import json
from types import SimpleNamespace

import cv2
import numpy as np

from tools.aa8_dealer_v2 import AA8DealerReader
from tools.aa8_participation import dice
from tools.aa8_state_adapter_v2 import AA8StateAdapterV2, amount, posting_comparison
from tools.aa8_strategy_state_v2 import AA8HandLedgerCandidate
from tools.aa8_live_wagers_v2 import CausalWagersV2
from tools.aa_seat_candidate import avatar_patch, plus_mask

from .aa_hero_controls import AAHeroControls
from .aa_mushroom import AAMushroomPool


def stack_vector(stacks):
    return tuple(amount((stacks or {}).get(str(seat))) for seat in range(8))


class LiveFrameEvidence:
    def __init__(self, bank, profile, empty_reference):
        self.controls = AAHeroControls(bank)
        self.mushroom = AAMushroomPool()
        self.dealer = AA8DealerReader()
        self.profile = profile
        self.empty_reference = empty_reference
        self.empty_runs = {}
        self.last_frame = None

    def __call__(self, image, row):
        self.controls(image, row)
        self.mushroom(image, row)
        row["live_dealer_candidate"] = self.dealer.read(image)["dealer_seat"]
        modes = row.get("special_modes") or {}
        clear = (row.get("scene_supported") is True
                 and not modes.get("block_state_updates")
                 and modes.get("insurance") != "VISIBLE")
        frame = row["frame"]
        if not clear or self.last_frame is not None and frame != self.last_frame + 1:
            self.empty_runs.clear()
        self.last_frame = frame
        confirmed = []
        for seat in self.profile["slots"]:
            slot = seat["slot"]
            if slot == 4 or not clear:
                continue
            patch = avatar_patch(image, seat["avatar"])
            plus = (plus_mask(patch) > 0).astype(np.uint8)
            # Align the same positive plus template, never infer empty from no cards.
            score = max(dice(cv2.warpAffine(plus, np.float32([
                [1, 0, dx], [0, 1, dy]]), (24, 24)) > 0, self.empty_reference)
                        for dx in (-2, -1, 0, 1, 2) for dy in (-2, -1, 0, 1, 2))
            hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
            green = ((hsv[:, :, 0] >= 35) & (hsv[:, :, 0] <= 95)
                     & (hsv[:, :, 1] >= 80) & (hsv[:, :, 2] >= 30))
            cue = row.get("participation", {}).get("slots", {}).get(str(slot), {})
            no_money_or_action = (
                (row.get("stacks", {}).get(str(slot)) or {}).get("value") is None
                and (row.get("street_wagers") or {}).get(str(slot)) is None
                and (row.get("glyphs") or {}).get(str(slot)) is None
                and cue.get("current") != "DEALT_IN_CANDIDATE")
            positive = (score >= .90 and float(green.mean()) > .80
                        and no_money_or_action)
            self.empty_runs[slot] = self.empty_runs.get(slot, 0) + 1 if positive else 0
            if self.empty_runs[slot] >= 2:
                confirmed.append(slot)
                # Positive empty evidence stays separate from old roster history.
                row["participation"]["slots"][str(slot)] = {
                    "current": "EMPTY_CANDIDATE", "history": "UNKNOWN",
                    "conflict": False, "in_this_hand": None,
                    "source": "aligned_positive_plus_v1"}
        row["empty_seats_v1"] = confirmed
        return row


class LiveStateAdapter(AA8StateAdapterV2):
    def __init__(self):
        super().__init__()
        self.dealer_value = None
        self.dealer_pending = None
        self.dealer_run = 0
        self.cleared = deque(maxlen=12)
        self.pending_opening = None
        self.opening_updates = []

    @staticmethod
    def _stacks_equal(left, right):
        # OCR diagnostic scores may change even when accepted numeric values agree.
        return stack_vector(left) == stack_vector(right)

    def _posting(self, row, baselines=None):
        if not self.history:
            return None
        previous = self.history[-1]
        if (previous["frame"] != row["frame"] - 1 or previous.get("board_count") != 0
                or not self._stacks_equal(previous.get("stacks"), row.get("stacks"))
                or amount(previous.get("pot")) != amount(row.get("pot"))):
            return None
        choices = {}
        baselines = self.cleared if baselines is None else baselines
        for before, repeated in zip(baselines, list(baselines)[1:]):
            if repeated["frame"] != before["frame"] + 1 or not self._stacks_equal(
                    before.get("stacks"), repeated.get("stacks")):
                continue
            posting = posting_comparison(repeated, row)
            if posting and not posting["credits"] and sum(
                    (Decimal(v) for v in posting["debits"].values()), Decimal(0)) == (
                    amount(row.get("pot"))):
                choices[json.dumps(posting, sort_keys=True)] = posting
        return next(iter(choices.values())) if len(choices) == 1 else None

    def _anchored_opening(self):
        """True when this hand already holds a ledger-qualifying opening event.

        Mirrors ``AA8HandLedgerCandidate._reset`` exactly (one event for this
        epoch, status ``MULTI_POST_DEAL_CANDIDATE``, at least three debits) so
        that protecting the epoch here protects precisely the ledger that would
        otherwise resolve, and nothing broader.
        """
        events = [event for event in self.epoch_events
                  if event.get("epoch") == self.epoch]
        if self.epoch is None or len(events) != 1:
            return False
        posting = events[0].get("posting_comparison") or {}
        debits = posting.get("debits")
        return (events[0].get("status") == "MULTI_POST_DEAL_CANDIDATE"
                and isinstance(debits, dict) and len(debits) >= 3
                and not any(action.get("epoch") == self.epoch
                            for action in self.actions))

    def observe(self, row):
        frame = row["frame"]
        modes = row.get("special_modes") or {}
        blocked = (row.get("scene_supported") is not True
                   or modes.get("block_state_updates")
                   or modes.get("insurance") == "VISIBLE")
        gap = self.last is not None and frame != self.last + 1
        if blocked or gap:
            self.dealer_value = self.dealer_pending = None
            self.dealer_run = 0
            self.cleared.clear()
            self.pending_opening = None
        detected = row.get("live_dealer_candidate")
        if type(detected) is int and 0 <= detected < 8 and not blocked:
            self.dealer_run = (self.dealer_run + 1
                               if detected == self.dealer_pending else 1)
            self.dealer_pending = detected
        else:
            self.dealer_run = 0
            self.dealer_pending = None
        late_posting = None
        pending = self.pending_opening
        if pending:
            if (frame > pending["expires"] or self.epoch != pending["epoch"]
                    or row.get("board_count") != 0 or self.pending
                    or row.get("glyph_transitions")
                    or len(self.actions) != pending["action_count"]):
                self.pending_opening = None
            else:
                late_posting = self._posting(row, pending["baselines"])
        new_hand = invalidated = False
        if self.dealer_run >= 2:
            if self.dealer_value is None:
                self.dealer_value = detected
            elif self.dealer_value != detected and row.get("board_count") != 0:
                # A newly observed dealer midstreet means the opening was missed.
                # Reset hand attribution, retain cash/event audit, and do not
                # mistake later settlement clearing for a new dealer movement.
                self.dealer_value = detected
                self.cleared.clear()
                self.pending_opening = None
                self.epoch = self.pending_hand = None
                self.deal_streak = 0
                self.history.clear()
                self.participants, self.pending = {}, []
                self.cash, self.pot_changes = [], []
                self.used_cash.clear()
                self.street = self.board = self.geometry_run = None
                self.current_board_supported = False
                self.timeline = type(self.timeline)(slot_count=8, hero_slot=4,
                                                    pair_window=self.window)
                invalidated = True
            elif self.dealer_value != detected and row.get("board_count") == 0:
                if self._anchored_opening():
                    # This hand already holds a qualified opening, so the
                    # preflop cannot have ended: a dealer-seat reading change on
                    # an empty board, at an unchanged zero pot, with no observed
                    # action for this epoch is a reading change, not a new hand.
                    # Re-anchoring here replaced the epoch 14 frames after the
                    # opening resolved and made the ledger re-taint itself
                    # (source frames 1264 -> 1278 of the development recording).
                    # The deferred case -- a reading change after this epoch has
                    # already recorded actions -- stays out of scope: it is not
                    # proven, and a real preflop-to-preflop hand change needs
                    # settlement evidence this guard deliberately does not claim.
                    self.dealer_value = detected
                else:
                    baselines = deepcopy(list(self.cleared))
                    posting = self._posting(row)
                    self.history.clear()
                    self.pending_hand = None
                    self._new_epoch(frame, frame - 1,
                                    "MULTI_POST_DEAL_CANDIDATE" if posting
                                    else "DEALER_ADVANCE_CONTEXT_CANDIDATE", posting)
                    self.dealer_value = detected
                    self.cleared.clear()
                    new_hand = True
                    self.pending_opening = None if posting or row.get(
                        "glyph_transitions") else {
                            "epoch": self.epoch, "first_frame": frame - 1,
                            "expires": frame + 4, "baselines": baselines,
                            "action_count": len(self.actions)}
        if new_hand or invalidated:
            row = deepcopy(row)
            row["participation"] = {"slots": {str(s): {
                "current": "UNKNOWN", "conflict": False} for s in range(8)}}
            row["glyph_transitions"] = [
                e for e in row.get("glyph_transitions", [])
                if e.get("frame", -1) >= frame - 1]
            row["continuous_context"] = None
        result = super().observe(row)
        if (late_posting and self.pending_opening is pending
                and self.epoch == pending["epoch"] and not self.pending
                and len(self.actions) == pending["action_count"]):
            covered = [d for d in self.cash if (
                d.get("confirmed_frame", frame + 1) <= frame
                and d.get("first_frame", -1) >= pending["first_frame"]
                and str(d["seat"]) in late_posting["debits"]
                and amount(d.get("amount")) is not None
                and amount(d.get("amount")) == amount(
                    late_posting["debits"].get(str(d["seat"]))))]
            self.opening_updates.append({
                "epoch": self.epoch, "frame": frame,
                "first_frame": pending["first_frame"],
                "status": "MULTI_POST_DEAL_CANDIDATE",
                "posting_comparison": late_posting, "authoritative_boundary": False,
                "source": "stable_late_opening_reconciliation",
                "no_intervening_action": True,
                "covered_cash_keys": [[d["seat"], d["first_frame"]] for d in covered]})
            for debit in covered:
                self.used_cash.add((debit["seat"], debit["first_frame"]))
            self.pending_opening = None
        if not blocked and row.get("board_count") == 0 and amount(row.get("pot")) == 0:
            self.cleared.append(deepcopy({k: row.get(k) for k in (
                "frame", "stacks", "participation", "board_count", "pot")}))
        result["live_boundary_reset"] = new_hand
        result["live_boundary_invalidated"] = invalidated
        result["boundary_method"] = "stable_dealer_advance_with_empty_board_candidate"
        result["opening_reconciliation"] = deepcopy(self.opening_updates[-1]) if (
            self.opening_updates and self.opening_updates[-1]["epoch"] == self.epoch
        ) else None
        return result


class LiveHandLedger(AA8HandLedgerCandidate):
    def _reset(self, epoch, adapter):
        updates = [item for item in adapter.opening_updates if item["epoch"] == epoch]
        if updates:
            # Original context events stay immutable; use the separately audited
            # stable reconciliation, never replace an existing known/tainted ledger.
            super()._reset(epoch, SimpleNamespace(epoch_events=[updates[-1]]))
            if self.opening is not None:
                self.opening["reconciliation"] = deepcopy(updates[-1])
        else:
            super()._reset(epoch, adapter)

    def observe(self, row, adapter):
        epoch = (row.get("observed_state_v2") or {}).get("observed_epoch")
        updates = [item for item in adapter.opening_updates if item["epoch"] == epoch]
        if (self.totals is None and not self.tainted and updates
                and self.epoch == epoch and not adapter.pending
                and not any(a.get("epoch") == epoch for a in adapter.actions)):
            self._reset(epoch, adapter)
        return super().observe(row, adapter)


class LiveCausalWagers(CausalWagersV2):
    """Expose a qualified late opening without deleting original audit events."""
    def observe(self, row, adapter, partition):
        updates = [item for item in adapter.opening_updates
                   if item["epoch"] == adapter.epoch and item["frame"] <= row["frame"]]
        if not updates:
            return super().observe(row, adapter, partition)
        qualified = updates[-1]
        covered = {tuple(key) for key in qualified["covered_cash_keys"]}
        view = SimpleNamespace(
            last=adapter.last, snapshot=adapter.snapshot, street=adapter.street,
            credits=adapter.credits,
            epoch_events=[event for event in adapter.epoch_events
                          if event["epoch"] != qualified["epoch"]] + [qualified],
            actions=adapter.actions, pending=adapter.pending,
            cash=[debit for debit in adapter.cash
                  if (debit["seat"], debit["first_frame"]) not in covered])
        result = super().observe(row, view, partition)
        result["opening_reconciliation_frame"] = qualified["frame"]
        return result
