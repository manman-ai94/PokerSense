"""Why the default advice (classic) says what it says: one sentence, three
numbers and where the answer flips (第三期 B ③, 2026-10-16).

Every number comes from the old strategy's own working at that decision:

- the opponents' range: before the flop the range ``aa_preflop`` reads for
  the last raiser (else the first caller), as a share of all hands; after it
  each opponent's range as ``range_multiway`` reads it (``opponent_ranges``),
  as the share of the hands he could hold that it keeps, each at its weight;
- your equity: before the flop your hand against that range (the heads-up
  equity table ``aa_preflop`` prices with); after it your share of the pot
  against every range (``range_equity``);
- the equity you need: facing a bet the price (what a call costs of what it
  can win, ``side_pots.price``, before the flop ``to_call / (pot + to_call)``);
  after the flop with nothing to call the bet line, the share a bet needs.

Where it flips: after the flop the shares where the rule's action changes
(its cuts), and facing a bet the most you could face to call and still call
(the bet you face grown or shrunk and the pot with it; the ranges as they
are). Before the flop facing a raise the same chips, from ``aa_preflop``'s
value of a call; otherwise how much the best option wins over the next.
Only shows advice; never acts for you.
"""

from __future__ import annotations

import re

from poker_engine.scoreboard.preflop_policy import Table, multiway
from poker_engine.scoreboard.side_pots import price

SEARCH_STEPS = 18       # halvings in the search for the chips where a call flips
WORDS = {"fold": "弃", "check": "过牌", "call": "跟注", "raise": "加注"}


def pct(value):
    return "不到 1%" if 0 < value < 0.005 else f"{value * 100:.0f}%"


def about(share):
    """" 约 36% " or " 不到 1% " of a range's share of hands."""
    return "不到 1%" if share < 0.005 else f"约 {share * 100:.0f}%"


def spaced(text):
    """A space between Chinese and a number, either way round."""
    text = re.sub(r"([\u4e00-\u9fff])([+−\d])", r"\1 \2", text)
    return re.sub(r"(\d%?)([\u4e00-\u9fff])", r"\1 \2", text)


def amount(value):
    value = float(value)
    return f"{value:.0f}" if abs(value - round(value)) < 0.05 else f"{value:.1f}"


def _me(observation):
    return str(observation["observing_seat"])


def all_in(observation, to):
    me = _me(observation)
    total = float(observation["bets"][me]) + float(observation["stacks"][me])
    return float(to) >= total - 0.5


def act_words(row, observation):
    """"弃", "过牌", "跟注 12", "下注 30", "加注到 60", "全下"."""
    action = row["action"]
    if action in ("fold", "check"):
        return WORDS[action]
    if action == "call":
        return f"跟注 {amount(observation['to_call'])}"
    if all_in(observation, row["to"]):
        return "全下"
    if action == "bet":
        mine = float(observation["bets"][_me(observation)])
        return f"下注 {amount(float(row['to']) - mine)}"
    return f"加注到 {amount(row['to'])}"


def last_raiser(observation):
    """The opponent who made the last bet or raise on this street, or None."""
    me = observation["observing_seat"]
    for row in reversed(observation["public_history"]):
        if row["street"] != observation["street"]:
            continue
        if row["kind"] == "raise_to" and row["actor"] != me:
            return row["actor"]
    return None


def facing(observation, chips, raiser):
    """``observation`` with ``chips`` to call: the raiser's bet, stack and
    chips in and the pot moved by the same chips as the price."""
    seat = str(raiser)
    delta = chips - float(observation["to_call"] or 0)

    def moved(values, sign=1):
        return {**values, seat: float(values[seat]) + sign * delta}

    found = {**observation, "to_call": chips,
             "pot": float(observation["pot"]) + delta,
             "bets": moved(observation["bets"]),
             "stacks": moved(observation["stacks"], -1)}
    if observation.get("contributions"):
        found["contributions"] = moved(observation["contributions"])
    return found


def call_limit(observation, raiser, calls):
    """(the most you could face to call and still call, whether that is all
    the chips there are) by halving: ``calls(observation)`` says whether the
    call is still made. None without a raiser to move."""
    if raiser is None:
        return None
    me = _me(observation)
    to_call = float(observation["to_call"] or 0)
    high = min(float(observation["stacks"][me]),
               to_call + float(observation["stacks"][str(raiser)]))
    if high <= to_call + 0.5:           # all in already: the price cannot grow
        return None
    if calls(facing(observation, high, raiser)):
        return high, True
    low = 0.0
    for _ in range(SEARCH_STEPS):
        middle = (low + high) / 2
        if calls(facing(observation, middle, raiser)):
            low = middle
        else:
            high = middle
    return low, False


def range_share(weights, dead):
    """The share of the hands an opponent could hold (two cards neither yours
    nor the board's) that his range keeps, each at its weight; a hand the
    range left out has no weight there."""
    left = 52 - len(set(dead))
    kept = sum(weight for key, weight in weights.items()
               if key[:2] not in dead and key[2:] not in dead)
    return kept / (left * (left - 1) / 2)


# -- after the flop -----------------------------------------------------------------

def postflop_range(observation, ranges):
    dead = set(observation["own_hole"]) | set(observation["board"])
    shares = {seat: range_share(weights, dead) for seat, weights in ranges.items()}
    if len(shares) == 1:
        (share,) = shares.values()
        return f"对手范围{about(share)}的牌", shares
    raiser = last_raiser(observation)
    if raiser in shares:
        others = [pct(share) for seat, share in shares.items() if seat != raiser]
        return (f"下注的那位范围{about(shares[raiser])}的牌，另 {len(others)} 人约"
                + "、".join(others)), shares
    return (f"{len(shares)} 个对手，范围约" + "、".join(pct(share) for share in shares.values())
            + "的牌"), shares


def postflop_why(observation, ranges, value, line, row, guard=None):
    """{"reason", "range", "range_shares", "equity", "need", "need_for", "flip"}
    for ``range_multiway``'s answer ``row`` (``multiway_row``) at your share
    ``value``; ``line``: its cuts; ``guard``: the big-pot guard's report when
    it changed the answer."""
    words, shares = postflop_range(observation, ranges)
    to_call = float(observation["to_call"] or 0)
    if to_call > 0:
        need, need_for = line["call"], "call"
        how = (f"你能赢 {pct(value)}，跟注要 {pct(need)}"
               + (f"，加注线 {pct(line['raise'])}" if row["action"] == "raise" else ""))
    else:
        need, need_for = line["bet"], "bet"
        how = f"你能赢 {pct(value)}，下注要 {pct(need)}"
    rule = {"fold": "不够价格就弃", "call": "够价格就跟", "raise": "过加注线就加注",
            "check": "不到下注线就过牌", "bet": "过下注线就下注"}[row["action"]]
    if guard is not None:
        rule = (f"护栏：只有一对或更小、底池已有 {amount(guard['pot_big_blinds'])} 个大盲，"
                + ("不加注" if to_call > 0 else "河牌不下注" if guard["street"] == "river"
                   else "最多下半个底池"))
    reason = f"{words}；{how}；{rule}——{act_words(row, observation)}。"
    return {"reason": spaced(reason), "range": spaced(words),
            "range_shares": {str(seat): round(share, 3)
                             for seat, share in shares.items()},
            "equity": round(value, 3), "need": round(need, 3), "need_for": need_for,
            "flip": spaced(postflop_flip(observation, value, line, row, guard))}


def postflop_flip(observation, value, line, row, guard=None):
    action = row["action"]
    facing_bet = float(observation["to_call"] or 0) > 0
    margin = line["call"] - price(observation) if facing_bet else 0.0
    if action in ("fold", "call"):
        found = call_limit(observation, last_raiser(observation),
                           lambda moved: value >= price(moved) + margin)
        if action == "fold":
            if found is not None and found[0] >= 1:
                return f"要跟的不到 {amount(found[0])} 就跟"
            return f"胜率到 {pct(line['call'])} 就跟"
        if found is None:
            first = f"胜率低于 {pct(line['call'])} 就弃"
        else:
            first = ("他再加到全下你也够跟" if found[1]
                     else f"要跟的超过 {amount(found[0])} 就弃")
        return first + ("；大底池只有一对不加注（护栏）" if guard is not None
                        else f"；胜率到 {pct(line['raise'])} 就加注")
    if action == "raise":
        return f"胜率低于 {pct(line['raise'])} 就只跟"
    if action == "check":
        if guard is not None:
            return "河牌只有一对不下注（护栏）"
        return f"胜率到 {pct(line['bet'])} 就下注"
    return f"胜率低于 {pct(line['bet'])} 就过牌"


# -- before the flop ----------------------------------------------------------------

def preflop_why(observation, policy, options):
    """{"reason", "range", "equity", "need", "need_for", "flip"} for
    ``aa_preflop``'s ``options`` (most valuable first, as the report has them)."""
    table = Table(observation, policy.params, policy.adjusted)
    raisers = [seat for seat, kind in table.history
               if kind == "r" and seat in table.live]
    callers = [seat for seat, kind in table.history
               if kind == "c" and seat in table.live]
    main = raisers[-1] if raisers else callers[0] if callers else None
    to_call = float(observation["to_call"] or 0)
    equity = need = None
    entered = list(dict.fromkeys(raisers + callers))
    if main is not None:
        hands = table.band(main)
        # Your share against everyone in, as aa_preflop prices it (``multiway``).
        equity = multiway([table.equity(table.band(seat)) for seat in entered])
        kind = "加注" if main in raisers else "平跟"
        words = (f"{kind}的那位范围{about(hands.mass())}的牌"
                 + (f"，另 {len(entered) - 1} 人入池" if len(entered) > 1 else ""))
        if to_call > 0:
            need = to_call / (float(observation["pot"]) + to_call)
    else:
        words = f"前面没人入池，后面还有 {len(table.behind())} 人"
    mine = [f"你 {table.hand}"]
    if equity is not None:
        mine.append(("对他" if len(entered) == 1 else f"对入池的 {len(entered)} 人")
                    + f"胜率 {pct(equity)}")
    if need is not None:
        mine.append(f"跟注要 {pct(need)}")
    reason = (f"{words}；{'，'.join(mine)}；按 AA 真人的打法算每个选择值多少"
              f"（后面的人怎么应对、翻后拿回多少都算上），{_values(options)}"
              f"——{_option_words(options[0])}。")
    return {"reason": spaced(reason), "range": spaced(words),
            "equity": None if equity is None else round(equity, 3),
            "need": None if need is None else round(need, 3),
            "need_for": "call" if need is not None else None,
            "flip": spaced(preflop_flip(observation, policy, options,
                                        raisers[-1] if raisers else None))}


def _option_words(option):
    if option["action"] == "raise":
        return f"加注到 {option['to']}"
    if option["action"] == "call":
        return f"跟注 {option['chips_in']}"
    return WORDS.get(option["action"], option["action"])


def _big_blinds(value):
    return f"{'+' if value > 0.05 else '−' if value < -0.05 else ''}{abs(value):.1f} 大盲"


def _values(options):
    """"加注到 19 值最多（+9.4 大盲）", or with a fold or check best what the
    others lose."""
    best, rest = options[0], options[1:]
    if best["action"] in ("fold", "check") and rest:
        others = [f"{_option_words(option)} {_big_blinds(option['big_blinds'])}"
                  for option in rest]
        return f"其余都不如{WORDS[best['action']]}：" + "、".join(others)
    return f"{_option_words(best)} 值最多（{_big_blinds(best['big_blinds'])}）"


def preflop_flip(observation, policy, options, raiser):
    best = options[0]
    second = options[1] if len(options) > 1 else None
    if float(observation["to_call"] or 0) > 0 and best["action"] in ("fold", "call"):
        found = call_limit(observation, raiser, lambda moved: Table(
            moved, policy.params, policy.adjusted).call_value() > 0)
        if found is not None:
            if best["action"] == "call":
                return ("他再加到全下你也跟" if found[1]
                        else f"他加得更大、要你跟超过 {amount(found[0])} 就弃")
            if found[0] >= 1:
                return f"他加得小一点、要你跟不到 {amount(found[0])} 就跟"
            return "他加得再小也不跟"
    if second is None:
        return "只有这一个选择"
    gap = best["big_blinds"] - second["big_blinds"]
    text = f"{_option_words(best)}比{_option_words(second)}多赢 {gap:.1f} 大盲"
    if gap < 0.5:
        text += "，两个差不多"
    if best["action"] == "raise":
        text += "；有人再加注就按新的价格和他的范围重算"
    return text


__all__ = ["act_words", "call_limit", "facing", "postflop_why", "preflop_why",
           "range_share"]
