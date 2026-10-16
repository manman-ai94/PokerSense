"""离线影子重放和分量账本: block 11 of the session package (``session_package.py``).

《一页纸打法 v3.3》第七节的分量账本: every session, the page (``plain``) and
the older advice (``old``) are both worked out again from the window's frame
log with this checkout's code, at every decision of yours, and where they
differ the lines are booked with a fold worth 0. It is calculated and kept,
never shown to the player.

* Replays: frame by frame on the recording's clock, as ``plain_live_report``
  does it: plain as the window runs it with the switch on; old with the
  range rule in place of the heads-up solve (no TexasSolver in the replay).
  A strategy's answer at a decision is its last one ready while your
  buttons showed. What the window did show is kept next to them
  (``shown``), and how often the replay of that same strategy says the same
  (``replay_matches_shown``: a replay that does not is not to be trusted).
* Actions are compared as fold, check, call or raise (a bet or an all-in is
  a raise; a call of nothing is a check). Two raises of different sizes
  agree.
* Only the first divergence of each hand is booked: after it the hand goes
  on along one line only. It falls in one of the page's three groups, or in
  ``other``:

  - ``c_old_allin``: old advises going all in (a raise of every chip behind)
    with at least ``DEEP_ALLIN_BB`` effective big blinds ("旧策略建议推 100 个
    大盲"); booked when you raised;
  - ``a_preflop_old_in``: before the flop, old calls or raises and plain
    folds ("翻前旧进 / 本页弃"); booked when you did not fold;
  - ``b_postflop_plain_fold``: after it, plain folds and old goes on ("翻后
    本页弃 / 旧继续"); booked when you did not fold;

  each as what you actually won or lost from that decision on less the fold
  line (0), and the same with the luck of the cards dealt after an all-in
  taken out (``luck_results``' ``runout_luck``). Where you took the fold, the
  other line was never played: counted, not booked. With the page as the
  window's default, a and b fill only from hands where you did not take
  its fold.
* ``loosened``: the two loosenings v3.3 makes on low evidence, to be
  withdrawn after 1000-1500 hands if the interval holds 0 and its top is
  under +4 big blinds a hand: late-position limps (table 1) and the small
  and big blinds' completes (case a), each with only the hands v3.3 adds to
  v3.2's list (``LOOSENED``). Every such spot where plain decided by that
  table row is listed, booked as above when you put chips in.
* "From that decision on" is the hand's result as the sheet counts it
  (``aa_session_report.chips``: from this hand's start to the next one's,
  each after its blinds and antes), plus what you had put in before the
  decision (the start's stack less yours at the decision), plus what the
  table has you post at the start of the next hand (blinds, antes,
  straddle or bomb post; 0 after a bust). A fold at the decision comes to 0
  by this count; ``fold_check`` counts the decisions you folded where it did
  not (a stack read wrong). A dealer's mushroom post is not in it.
* ``booked`` (every first divergence, both lines worth 0 when they fold and
  what you got when they are what you did) and ``by_shown`` (every
  divergence where the opponents still in showed their cards, both lines
  against those cards as ``aa_compare_advice.chips`` values them, a fold 0)
  are other reckonings, kept apart.

Big blinds are at the hand's own level; table points (积分), never money.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from poker_engine.desktop.aa_solver_input import (  # noqa: E402
    hand_facts, table_observation)
from poker_engine.scoreboard.plain_policy import hands as hand_set  # noqa: E402
from poker_engine.scoreboard.strength import hand_class  # noqa: E402
from tools.aa_compare_advice import chips, shown_spot  # noqa: E402
from tools.aa_session_report import plain as act  # noqa: E402
from tools.plain_live_report import replay_old, replay_plain  # noqa: E402

HERO = 4
NAMES = {"plain": "一页纸打法（plain）",
         "old": "旧策略（翻前 aa_preflop，翻后 range_multiway）"}
GROUPS = ("a_preflop_old_in", "b_postflop_plain_fold", "c_old_allin", "other")
DEEP_ALLIN_BB = 50          # "推 100 个大盲": an all-in at least this deep
FOLD_OFF_BB = 0.5           # a fold "from here" further from 0 than this: off
# The two loosenings of v3.3 (section 8), as v3.2 had the lists and as v3.3
# adds to them; only the hands v3.2 did not have count.
_V32_SPECULATIVE = ("22+ A2s+ K5s+ 54s-KQs 75s-J9s Q9s ATs+ KTs+ QTs+ JTs ATo+ KTo+ "
                    "QTo+ JTo A8o+")
_V32 = {"late_limp": _V32_SPECULATIVE + " Q8s J8s T8s 97s 86s 75s A2o+ K9o+ Q9o+",
        "bb_complete": _V32_SPECULATIVE + " 98s T8s+ J8s+ Q8s+ K8s+ A2o+ K9o+ Q9o+ "
                                          "J9o+ T9o",
        "sb_complete": _V32_SPECULATIVE + " A2o+ K9o+ Q9o+ JTo"}
_V33_ADDS = {"late_limp": "K2s+ Q6s+ J7s+ T7s+ 96s 64s 53s 43s K8o+ J9o+ T9o 98o",
             "bb_complete": "43s 53s 64s K7o+ Q8o+ J8o+ T8o+ 98o 97o 87o 76o",
             "sb_complete": "K2s+ Q6s+ J7s+ T7s+ 96s 85s 74s 64s 53s K8o+ J9o+ T9o "
                            "98o"}
LOOSENED = {name: hand_set(_V33_ADDS[name]) - hand_set(_V32[name])
            for name in _V33_ADDS}
LOOSE_RULES = {"late_limp": ("T1.limp", "T1.out"),
               "bb_complete": ("T1.a", "T1.a.fold"),
               "sb_complete": ("T1.a", "T1.a.fold")}
CONVENTION = (
    "分量账本（一页纸 v3.3 第七节）：本页和旧策略都用这版代码按录像离线重放；每手只记第一个"
    "分歧，按弃 = 0 记账：c 旧策略建议全下且有效筹码 ≥ 50 个大盲（你加注了才记）；a 翻前旧进、"
    "本页弃；b 翻后本页弃、旧继续（a、b 你没弃才记）；记的是你从这一步起实际的输赢减弃牌线 0"
    "（这一手按体检单算的成绩 + 这一步之前已经投进去的 + 下一手开局交的前注、盲注、抓头或暴击局"
    "的钱，爆掉了就是 0；庄位交的蘑菇不在里面），另给一版扣掉全下后发牌运气的。loosened 是 v3.3 "
    "两条放宽（晚位平跟、小盲大盲补齐，只算 v3.3 新加的牌）每一次，按同样的口径记你投了钱的那几次。"
    "旧策略重放时单挑转牌河牌用范围规则代替求解器。")


def strategy_of(report):
    """``plain`` for a report of the one-page rules, else ``old``."""
    if report.get("plain") is not None or \
            str(report.get("basis") or "").startswith("一页纸打法"):
        return "plain"
    return "old"


def _decimal(value):
    try:
        return None if value in (None, "") else Decimal(str(value))
    except InvalidOperation:
        return None


def replays(rows):
    """{strategy: [its report at each row]}: both strategies."""
    return {"plain": replay_plain(rows)[0], "old": replay_old(rows)}


def last_ready(reports):
    return next((report for report in reversed(reports)
                 if report and report.get("status") == "ready"), None)


def side(report, free, strategy=None):
    """fold, check, call or raise of a ready report (a call of nothing is a
    check), its size and the rule that gave it; None without one."""
    if report is None:
        return None
    first = (report.get("advice") or [{}])[0]
    action = act(first.get("action"))
    if action == "call" and free:
        action = "check"
    page = report.get("plain") or {}
    return {"strategy": strategy or strategy_of(report), "action": action,
            "to": first.get("to"), "chips": first.get("chips"),
            "rule": page.get("rule"), "kind": report.get("kind")}


def posts(rows, stakes):
    """What the table has you put in at the start of the hand of these rows
    (blinds, antes, straddle, bomb post), from its frames before anyone
    acted; None when that does not replay."""
    before = [row for row in rows
              if not ((row["fields"].get("actions_v1") or {}).get("actions"))]
    try:
        observation = table_observation(hand_facts(before or rows[:1], stakes), HERO)
    except Exception:                   # noqa: BLE001 - a hand that does not replay
        return None
    if observation is None:
        return None
    return _decimal(observation["contributions"].get(str(HERO)))


def from_here(decision, hand, after):
    """(big blinds you won or lost from the decision on, or None, why not)."""
    result = _decimal(hand.get("chips"))
    if result is None:
        return None, "这手没有成绩（录像停在这手、重新买入或这手被拆成两段）"
    start = _decimal(hand.get("start"))
    behind = _decimal(decision.get("your_stack"))
    big_blind = _decimal(hand.get("big_blind"))
    if start is None or behind is None or not big_blind:
        return None, "你的筹码或大盲没读到"
    if result == -start:                # busted: nothing to post next hand
        put = Decimal(0)
    else:
        put = after
        if put is None:
            return None, "下一手开局交的前注盲注算不出"
    return round(float((result + start - behind + put) / big_blind), 2), None


def worth(action, you, here):
    """A line's worth in big blinds, fold = 0: 0 when it folds, what you got
    when it is what you did, else None (never played)."""
    if action == "fold":
        return 0.0
    if you is not None and action == you and here is not None:
        return here
    return None


def shove(item, decision):
    """Whether old's answer goes all in at least ``DEEP_ALLIN_BB`` deep."""
    put, behind = _decimal(item.get("chips")), _decimal(decision.get("your_stack"))
    deep = decision.get("effective_bb")
    return (item["action"] == "raise" and put is not None and behind is not None
            and put >= behind and deep is not None and deep >= DEEP_ALLIN_BB)


def group_of(decision, old, plain):
    if shove(old, decision):
        return "c_old_allin"
    if decision.get("street") == "preflop":
        if plain["action"] == "fold" and old["action"] in ("call", "raise"):
            return "a_preflop_old_in"
    elif plain["action"] == "fold" and old["action"] != "fold":
        return "b_postflop_plain_fold"
    return "other"


def entered(group, you):
    if you is None:
        return None
    if group == "c_old_allin":
        return you == "raise"
    return you != "fold"


def loosened(decision, plain):
    """Which v3.3 loosening this decision is a spot of, or None."""
    cards = (decision.get("hero") or "").split()
    if plain is None or decision.get("street") != "preflop" or len(cards) != 2:
        return None
    try:
        name = hand_class(cards)
    except (IndexError, ValueError):
        return None
    seat = decision.get("seat_name")
    spot = ("late_limp" if decision.get("position") == "late" else
            "bb_complete" if seat == "BB" else "sb_complete" if seat == "SB" else None)
    if spot is None or plain.get("rule") not in LOOSE_RULES[spot]:
        return None
    return spot if name in LOOSENED[spot] else None


def luck_out(here, hand):
    """``here`` with the luck of the cards dealt after an all-in taken out (0
    in a hand without one), or None when that luck was not worked out."""
    runout = (hand.get("luck") or {}).get("runout")
    if here is None or runout is None:
        return None
    return round(here - runout, 2)


def by_shown(rows, indexes, hand_id, old, plain, big_blind):
    """Both lines against the cards the opponents still in showed, or None."""
    try:
        spot = shown_spot(rows, indexes, hand_id)
    except Exception:                   # noqa: BLE001 - a hand that does not replay
        return None
    big_blind = _decimal(big_blind)
    if spot is None or not big_blind:
        return None
    observation, share, _ = spot
    values = []
    for item in (old, plain):
        try:
            value = chips({"action": item["action"], "to": item["to"]},
                          observation, share)
        except (InvalidOperation, KeyError, TypeError, ValueError):
            value = None
        values.append(None if value is None
                      else round(value / float(big_blind), 2))
    one, two = values
    return {"old_bb": one, "plain_bb": two,
            "diff_bb": None if one is None or two is None else round(two - one, 2)}


def block(rows, hands, *, code=None, page_version=None):
    """The shadow block. ``hands``: one dict a hand in the log's order, with
    ``hand_id``, ``rows``, ``turns`` (each a list of (row, report) pairs as the
    log has them), ``decisions`` (the package's rows for those turns),
    ``stakes``, ``chips`` (the sheet's result), ``start`` (the sheet's
    starting stack) and ``luck`` (``runout``, ``allin``)."""
    position = {id(row): index for index, row in enumerate(rows)}
    replayed = replays(rows) if any(hand["turns"] for hand in hands) else {}
    items = []
    for number, hand in enumerate(hands):
        later = hands[number + 1] if number + 1 < len(hands) else None
        after = None if later is None else posts(later["rows"], later["stakes"])
        hand = {**hand, "big_blind": hand["stakes"].get("big_blind")}
        booked = False
        for turn, decision in zip(hand["turns"], hand["decisions"]):
            items.append(decision_item(rows, position, replayed, hand, after, turn,
                                       decision, first=not booked))
            booked = booked or items[-1]["first_divergence"]
    return {"summary": summary(items, code, page_version), "decisions": items}


def decision_item(rows, position, replayed, hand, after, turn, decision, *, first):
    free = decision.get("button") == "check" or _decimal(decision.get("to_call")) == 0
    indexes = [position[id(row)] for row, _ in turn]
    shown = side(last_ready([report for _, report in turn]), free)
    old = side(last_ready([replayed["old"][i] for i in indexes]), free, "old")
    plain = side(last_ready([replayed["plain"][i] for i in indexes]), free, "plain")
    you = decision.get("you_did")
    if you == "call" and free:
        you = "check"
    here, why = from_here(decision, hand, after)
    again = {"old": old, "plain": plain}.get((shown or {}).get("strategy"))
    item = {"hand_id": hand["hand_id"], "street": decision.get("street"),
            "video_seconds": decision.get("video_seconds"),
            "position": decision.get("position"),
            "seat_name": decision.get("seat_name"),
            "shown": shown, "old": old, "plain": plain,
            "replay_matches_shown": (None if shown is None or again is None
                                     else again["action"] == shown["action"]),
            "you_did": you, "from_here_bb": here, "from_here_missing": why,
            "agree": None if old is None or plain is None
            else old["action"] == plain["action"],
            "first_divergence": False, "group": None, "entered": None,
            "in_minus_fold_bb": None, "in_minus_fold_luck_out_bb": None,
            "booked": None, "by_shown": None, "loosened": loosened(decision, plain)}
    if item["loosened"]:
        item["entered"] = None if you is None else you in ("call", "raise")
        if item["entered"]:
            item["in_minus_fold_bb"] = here
            item["in_minus_fold_luck_out_bb"] = luck_out(here, hand)
    if item["agree"] is not False:
        return item
    item["by_shown"] = by_shown(rows, indexes, hand["hand_id"], old, plain,
                                hand["big_blind"])
    if not first:
        return item
    group = group_of(decision, old, plain)
    went = entered(group, you)
    item.update(first_divergence=True, group=group)
    if not item["loosened"]:
        item["entered"] = went
        if went and group != "other":
            item["in_minus_fold_bb"] = here
            item["in_minus_fold_luck_out_bb"] = luck_out(here, hand)
    one, two = worth(old["action"], you, here), worth(plain["action"], you, here)
    item["booked"] = {"old_bb": one, "plain_bb": two,
                      "diff_bb": None if one is None or two is None
                      else round(two - one, 2)}
    return item


def _tally(items):
    went = [item for item in items if item["entered"]]
    values = [item["in_minus_fold_bb"] for item in went
              if item["in_minus_fold_bb"] is not None]
    lucky = [item["in_minus_fold_luck_out_bb"] for item in went
             if item["in_minus_fold_luck_out_bb"] is not None]
    return {"n": len(items), "entered": len(went), "booked": len(values),
            "in_minus_fold_bb": round(sum(values), 2),
            "in_minus_fold_luck_out_bb": round(sum(lucky), 2),
            "luck_out_booked": len(lucky)}


def summary(items, code, page_version):
    compared = [item for item in items if item["agree"] is not None]
    diverged = [item for item in compared if not item["agree"]]
    first = [item for item in diverged if item["first_divergence"]]
    groups = {name: _tally([item for item in first if item["group"] == name])
              for name in GROUPS}
    for name in GROUPS:
        groups[name]["you_folded"] = sum(item["entered"] is False for item in first
                                         if item["group"] == name)
    loose = {name: {**_tally([item for item in items if item["loosened"] == name]),
                    "plain_enters": sum(item["plain"]["action"] != "fold"
                                        for item in items
                                        if item["loosened"] == name)}
             for name in LOOSENED}
    booked = [item["booked"]["diff_bb"] for item in first
              if item["booked"]["diff_bb"] is not None]
    shown = [item["by_shown"]["diff_bb"] for item in diverged
             if item["by_shown"] and item["by_shown"]["diff_bb"] is not None]
    folds = [item["from_here_bb"] for item in items
             if item["you_did"] == "fold" and item["from_here_bb"] is not None]
    checks = [item["replay_matches_shown"] for item in items
              if item["replay_matches_shown"] is not None]
    return {
        "names": NAMES, "replay_code": code, "page_version": page_version,
        "old_without_solver": True, "deep_allin_bb": DEEP_ALLIN_BB,
        "shown_by": dict(Counter(item["shown"]["strategy"] for item in items
                                 if item["shown"])),
        "replay_matches_shown": {"n": len(checks), "same": sum(checks)},
        "decisions": len(items), "compared": len(compared),
        "old_without_advice": sum(item["old"] is None for item in items),
        "plain_without_advice": sum(item["plain"] is None for item in items),
        "agree": len(compared) - len(diverged), "diverged": len(diverged),
        "pairs": dict(Counter(f"{item['old']['action']}→{item['plain']['action']}"
                              for item in diverged).most_common()),
        "first_divergences": len(first), "groups": groups, "loosened": loose,
        "booked": {"n": len(booked), "plain_minus_old_bb": round(sum(booked), 2)},
        "by_shown": {"n": len(shown), "plain_minus_old_bb": round(sum(shown), 2)},
        "fold_check": {"n": len(folds),
                       "off": sum(abs(value) > FOLD_OFF_BB for value in folds)},
        "convention": CONVENTION}


__all__ = ["CONVENTION", "DEEP_ALLIN_BB", "GROUPS", "LOOSENED", "NAMES", "block",
           "from_here", "group_of", "loosened", "posts", "strategy_of", "worth"]
