"""A visible, bounded river study fed by current candidates, never a live policy."""

from decimal import Decimal

from poker_engine.strategy.river_bounds_v1 import river_payoff_bounds


def current_river_study(row):
    result = {"status": "BLOCKED", "reasons": [],
              "source_frame": row.get("source_frame"),
              "observation_sequence": row.get("frame"), "strategy_eligible": False,
              "advice_emitted": False, "result": None}
    controls = row.get("hero_controls_v1") or {}
    cards = row.get("cards") or {}
    modes = row.get("special_modes") or {}
    if (row.get("scene_supported") is not True or modes.get("block_state_updates")
            or modes.get("insurance") == "VISIBLE"):
        result["reasons"].append("画面遮挡或特殊界面，暂不计算")
    if row.get("board_count") != 5 or any(
            value is None for value in cards.get("board_slots", [None] * 5)):
        result["reasons"].append("等待完整河牌")
    if row.get("current_actor") != 4 or controls.get("price_confirmed") is not True:
        result["reasons"].append("等待Hero行动及稳定的跟注按钮金额")
    elif controls.get("button") == "check":
        result["reasons"].append("当前可以让牌，不需要跟注")
    stacks, wagers = row.get("stacks") or {}, row.get("street_wagers") or {}
    participants = (row.get("participation") or {}).get("slots") or {}
    empty = row.get("empty_seats_v1") or []
    opponents = []
    for seat in range(8):
        if seat == 4 or seat in empty:
            continue
        cue = participants.get(str(seat), {})
        if not cue.get("conflict") and cue.get("current") == "FOLDED_CANDIDATE":
            continue
        stack = (stacks.get(str(seat)) or {}).get("value")
        wager = wagers.get(str(seat))
        try:
            all_in = (stack is not None and Decimal(stack) == 0
                      and wager is not None and Decimal(wager) > 0)
        except Exception:
            all_in = False
        if all_in:
            opponents.append(seat)
        else:
            result["reasons"].append(f"座位{seat}的争池/全下状态尚不明确")
    if not opponents:
        result["reasons"].append("当前没有已明确的全下对手")
    pot = (row.get("pot") or {}).get("value")
    call = controls.get("call_amount")
    hero_stack = (stacks.get("4") or {}).get("value")
    try:
        if (pot is None or call is None or Decimal(pot) <= 0
                or Decimal(pot) < Decimal(call)):
            result["reasons"].append("显示底池未知或与跟注金额不一致")
        if call is None or hero_stack is None or Decimal(call) >= Decimal(hero_stack):
            result["reasons"].append("跟注金额未知或跟注后全下，需单独处理底池资格")
    except Exception:
        result["reasons"].append("Hero筹码或跟注金额无效")
    if result["reasons"]:
        return result
    try:
        bound = river_payoff_bounds(cards.get("hero"), cards.get("board_slots"),
                                    pot, call, len(opponents))
    except (ValueError, TypeError, ArithmeticError):
        return {**result, "reasons": ["牌面或金额仍缺少完整有效输入"]}
    return {**result, "status": "CONDITIONAL_STUDY", "opponent_seats": opponents,
            "call_amount": call, "pot_before": pot, "result": bound,
            "eligibility_condition_verified": False,
            "notice": "按当前候选值计算；须核对全额争池资格、无后续行动及费用。不是胜率预测。"}
