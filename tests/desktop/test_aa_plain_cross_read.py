"""两处读数对上才算读到（``aa_plain_advice``）：你的筹码往前带（``carried_stack``）、
要跟的金额按两处读数对上（``HandState.derived_price``）。

对不上、只有一处、或者不是这手开局以来该有的数，都还是没读到（铁律 5 照旧）：每个
测试都核对拿出来的数和画面上真的一样，没有拿出错数的情况。牌局是 ``Screen`` 合成的
画面：8 人桌，1/2/4(2)。
"""

from decimal import Decimal
from itertools import product

import pytest

from poker_engine.desktop import aa_plain_advice as live
from poker_engine.desktop.aa_plain_advice import AAPlainAdvice
from tests.desktop.test_aa_plain_live import Clock, HERO, Screen, ready

CARRIED = "你的筹码按上一手读数往前带"
DERIVED = "要跟的金额按两处读数对上"
SEATS = 8


def blinds(dealer):
    return [(dealer + step) % SEATS for step in (1, 2, 3)]


def deal_at(screen, dealer, ante=2, hero_ante=True):
    """开局：前注闪一下，再上小盲、大盲、抓头。``hero_ante``：False 是你的前注上一手
    结束前就扣过了。"""
    screen.show(2)
    for seat in screen.stacks:
        if seat != HERO or hero_ante:
            screen.stacks[seat] -= ante
        screen.wagers[seat] = ante
    screen.pot = ante * screen.seats
    screen.show(2)
    screen.wagers = dict.fromkeys(screen.wagers)
    for seat, chips in zip(blinds(dealer), (1, 2, 4)):
        screen.put(seat, chips, frames=0)
    return screen.show(3)


def first_hand(advice, dealer=7, fold=True, fold_frames=3, after=(), hidden=False,
               leak=0):
    """上一手：3 号加注，你弃牌（``fold``），别人接着打。``after``：弃牌以后你的筹码
    再读到的数（一个数一帧）；``hidden``：弃牌以后你的筹码一直读不到；``leak``：这手
    最后几帧你的筹码已经扣了下一手的前注。"""
    screen = Screen(advice, dealer=dealer, hero=("Qs", "Qh"), hand="hand_1")
    deal_at(screen, dealer)
    screen.put(3, 12)
    if hidden:
        screen.hidden.add(HERO)
    if fold:
        screen.fold(HERO, frames=fold_frames)
    else:
        screen.put(HERO, 12)
    if after:
        screen.hidden.discard(HERO)
    real = screen.stacks[HERO]
    for value in after:
        screen.stacks[HERO] = value
        screen.show(1)
    screen.stacks[HERO] = real
    if hidden:
        screen.hidden.add(HERO)
    screen.put(5, 12)
    screen.show(12)
    if leak:
        screen.hidden.discard(HERO)
        screen.stacks[HERO] -= leak
        screen.show(3)
    return screen


def next_hand(advice, first, dealer=1, raw=(), hero_ante=True):
    """这一手：你的筹码一帧都没读到（``raw``：这手读到过的几个数，一个数一帧）。"""
    screen = Screen(advice, dealer=dealer, hero=("Ac", "Kd"), hand="hand_2")
    screen.stacks = dict(first.stacks)
    screen.hidden.add(HERO)
    deal_at(screen, dealer, hero_ante=hero_ante)
    real = screen.stacks[HERO]
    for value in raw:
        screen.hidden.discard(HERO)
        screen.stacks[HERO] = value
        screen.show(1)
        screen.hidden.add(HERO)
    screen.stacks[HERO] = real
    return screen


def observation(screen):
    return live.table_observation(screen.advice.state, screen.fields,
                                  screen.advice.stakes())


def carried(screen, call):
    controls = {"visible": True, "button": "call", "call_amount": str(call)}
    return live.carried_stack(screen.advice.state, screen.advice.stakes(), controls,
                              Decimal(call))


# -- 你的筹码往前带 -----------------------------------------------------------------

def test_your_stack_unread_all_hand_is_the_last_hand_s_less_this_hand_s_posts():
    # 上一手你弃牌以后读到 198；这手你抓头（4），前注 2，筹码一帧都没读到
    advice = AAPlainAdvice(clock=Clock())
    second = next_hand(advice, first_hand(advice), dealer=1)
    second.put(5, 12)
    report = ready(second, call=8)
    found, defaults, missing = observation(second)
    assert found["stacks"]["4"] == "192" == str(second.stacks[HERO])
    assert "hero_stack" in defaults and not missing
    assert CARRIED in report["plain"]["defaults"]


@pytest.mark.parametrize("dealer, post", [(1, 4), (2, 2), (3, 1), (7, 0), (6, 0)])
def test_the_carried_stack_takes_off_your_own_blind_only(dealer, post):
    advice = AAPlainAdvice(clock=Clock())
    second = next_hand(advice, first_hand(advice), dealer=dealer)
    second.put(5, 12)
    second.show(3)
    assert carried(second, 12 - post) == 198 - 2 - post == second.stacks[HERO]


def test_a_reading_this_hand_that_fits_the_hand_so_far_does_not_stop_it():
    advice = AAPlainAdvice(clock=Clock())
    second = next_hand(advice, first_hand(advice), dealer=1, raw=(198, 196))
    second.put(5, 12)
    report = ready(second, call=8)
    assert observation(second)[0]["stacks"]["4"] == "192"
    assert CARRIED in report["plain"]["defaults"]


def test_a_steady_reading_this_hand_is_used_and_nothing_is_carried():
    advice = AAPlainAdvice(clock=Clock())
    second = next_hand(advice, first_hand(advice), dealer=1)
    second.hidden.discard(HERO)
    second.put(5, 12)
    report = ready(second, call=8)
    found, defaults, _ = observation(second)
    assert found["stacks"]["4"] == "192" and "hero_stack" not in defaults
    assert CARRIED not in report["plain"]["defaults"]


UNREAD = {
    # 上一手你一直在局里（赢了输了筹码都会变）
    "in_the_pot": dict(first=dict(fold=False)),
    # 弃牌以后读到两个数（读错一帧，或者补了筹码）
    "two_readings": dict(first=dict(after=(198, 150, 198))),
    # 弃牌以后只读到一帧
    "one_reading": dict(first=dict(fold_frames=2, hidden=False, after=()),
                        hide_after_fold=True),
    # 弃牌以后一直读不到，只在最后几帧读到（那时可能已经扣了下一手的前注）
    "only_at_the_end": dict(first=dict(hidden=True, leak=2), hero_ante=False),
    # 上一手最后几帧读到的和弃牌时读到的不一样（下一手的前注提前扣了）
    "ante_taken_early": dict(first=dict(leak=2), hero_ante=False),
    # 上一手你是庄位（要交蘑菇），或者这一手你是庄位
    "dealer_before": dict(first=dict(dealer=HERO)),
    "dealer_now": dict(dealer=HERO),
    # 这手读到过一个对不上的数
    "odd_reading": dict(raw=(150,)),
}


@pytest.mark.parametrize("case", sorted(UNREAD))
def test_a_stack_that_is_not_cross_checked_stays_unread(case):
    options = UNREAD[case]
    advice = AAPlainAdvice(clock=Clock())
    first_options = dict(options.get("first", {}))
    if options.get("hide_after_fold"):
        first = Screen(advice, hero=("Qs", "Qh"), hand="hand_1")
        deal_at(first, 7)
        first.put(3, 12)
        first.fold(HERO, frames=2)                      # 弃牌读稳的那一帧读到一次
        first.hidden.add(HERO)
        first.put(5, 12)
        first.show(12)
    else:
        first = first_hand(advice, **first_options)
    dealer = options.get("dealer", 1)
    second = next_hand(advice, first, dealer=dealer, raw=options.get("raw", ()),
                       hero_ante=options.get("hero_ante", True))
    opener = next(seat for seat in range(5, 13) if seat % SEATS not in
                  blinds(dealer) + [dealer, HERO]) % SEATS
    second.put(opener, 12)
    post = dict(zip(blinds(dealer), (1, 2, 4))).get(HERO, 0)
    report = second.turn(call=12 - post)
    assert report["status"] == "reading" and "stack" in report["missing"], report
    assert carried(second, 12 - post) is None


def test_after_you_have_acted_this_hand_the_stack_is_not_carried():
    advice = AAPlainAdvice(clock=Clock())
    second = next_hand(advice, first_hand(advice), dealer=7)     # 你不在盲位
    second.put(3, 4)
    ready(second, call=4)
    second.put(HERO, 4)                                 # 你平跟了
    second.acted()
    second.put(5, 16)
    report = second.turn(call=12)
    assert report["status"] == "reading" and "stack" in report["missing"]


def test_a_limp_whose_chips_were_not_read_still_stops_the_carry():
    # 你平跟了 4，面前的筹码没读到：往前带的 196 就错了（真的是 192），所以动过就不带
    advice = AAPlainAdvice(clock=Clock())
    second = next_hand(advice, first_hand(advice), dealer=7)
    second.put(3, 4)
    ready(second, call=4)
    second.put(HERO, 4, frames=0)
    second.wagers[HERO] = None
    second.acted()
    second.put(5, 16)
    report = second.turn(call=12)
    assert report["status"] == "reading" and "stack" in report["missing"]
    assert second.stacks[HERO] == 192


def test_chips_you_put_in_without_a_button_seen_stop_the_carry():
    # 按钮一次没看到（比如预选了跟注），你面前已经有 12：不带
    advice = AAPlainAdvice(clock=Clock())
    second = next_hand(advice, first_hand(advice), dealer=7)
    second.put(3, 12)
    second.put(HERO, 12)
    second.put(5, 36)
    report = second.turn(call=24)
    assert report["status"] == "reading" and "stack" in report["missing"]


def test_after_the_flop_without_a_preflop_button_the_stack_is_not_carried():
    # 你抓头，翻前一次按钮都没看到（没人加注），翻牌有人下注：只在翻前带
    advice = AAPlainAdvice(clock=Clock())
    second = next_hand(advice, first_hand(advice), dealer=1)
    for seat in (5, 6, 7, 0, 1, 2, 3):
        if seat in (2, 3):
            second.put(seat, 4)
        else:
            second.fold(seat)
    second.street("flop", "Ah", "Kd", "7c")
    second.put(2, 10)
    report = second.turn(call=10)
    assert report["status"] == "reading" and "stack" in report["missing"]


@pytest.mark.parametrize("controls", [
    {"visible": True, "button": "all_in", "call_amount": None},     # 全下按钮
    {"visible": True, "button": "call", "call_amount": "200"},      # 要跟的不比它少
])
def test_a_button_that_does_not_fit_the_carried_stack_leaves_it_unread(controls):
    advice = AAPlainAdvice(clock=Clock())
    second = next_hand(advice, first_hand(advice), dealer=1)
    second.put(5, 204)
    report = second.show(4, hero_controls=controls)
    assert report["status"] == "reading" and "stack" in report["missing"]


def test_after_the_flop_the_stack_is_not_carried():
    advice = AAPlainAdvice(clock=Clock())
    second = next_hand(advice, first_hand(advice), dealer=1)
    for seat in (5, 6, 7, 0, 1, 2, 3):
        if seat in (2, 3):
            second.put(seat, 4)
        else:
            second.fold(seat)
    second.turn(frames=3)
    second.acted()
    second.street("flop", "Ah", "Kd", "7c")
    second.put(2, 10)
    report = second.turn(call=10)
    assert report["status"] == "reading" and "stack" in report["missing"]


def test_a_carried_stack_is_never_a_wrong_number():
    # 各种上一手（弃没弃、弃牌以后读到几次、读错、前注提前扣）和这一手（位置、读到过
    # 的数）：拿出来的要么是 None，要么和画面上真的一样
    firsts = [dict(), dict(fold=False), dict(after=(198, 150, 198)),
              dict(hidden=True, leak=2), dict(leak=2), dict(dealer=HERO),
              dict(dealer=2)]
    raws = [(), (198,), (196,), (150,), (198, 196, 150)]
    used = 0
    for first_options, dealer, raw in product(firsts, (1, 2, 3, 4, 6), raws):
        advice = AAPlainAdvice(clock=Clock())
        first = first_hand(advice, **first_options)
        second = next_hand(advice, first, dealer=dealer, raw=raw,
                           hero_ante=not first_options.get("leak"))
        opener = next(seat for seat in range(5, 13) if seat % SEATS not in
                      blinds(dealer) + [dealer, HERO]) % SEATS
        second.put(opener, 12)
        post = dict(zip(blinds(dealer), (1, 2, 4))).get(HERO, 0)
        second.turn(call=12 - post)
        found = carried(second, 12 - post)
        if found is not None:
            used += 1
            assert found == second.stacks[HERO], (first_options, dealer, raw, found)
            assert observation(second)[0]["stacks"]["4"] == str(second.stacks[HERO])
    assert used >= 10                                   # 也真的用上了


# -- 要跟的金额按两处读数对上 -------------------------------------------------------

def to_flop(advice, clock=None, callers=(2,)):
    """翻前 3 号加到 12，``callers`` 和你跟，其余弃；翻牌 A♥K♦7♣，底池读稳。"""
    screen = Screen(advice, clock=clock, hero=("Ac", "Js"))
    screen.deal()
    screen.put(3, 12)
    ready(screen, call=12)
    screen.put(HERO, 12)
    screen.acted()
    for seat in (5, 6, 7, 0, 1, 2):
        if seat in callers:
            screen.put(seat, 12)
        else:
            screen.fold(seat)
    screen.street("flop", "Ah", "Kd", "7c")
    return screen


def bet_unread(screen, seat, to):
    """``seat`` 下注到 ``to``，面前的筹码读不到（底池照样涨）。"""
    screen.put(seat, to, frames=0)
    screen.wagers[seat] = None
    return screen.show(3)


def button(raw=None, call=None):
    return {"visible": True, "button": "call", "call_amount": call,
            "raw_call_amount": raw}


def test_a_doubtful_button_amount_equal_to_the_pot_rise_is_the_price():
    # 对手翻牌下注，面前的筹码没读到，按钮金额没读稳
    screen = to_flop(AAPlainAdvice(clock=Clock()))
    bet_unread(screen, 3, 46)
    report = screen.show(4, hero_controls=button(raw="46"))
    assert report["status"] == "ready" and report["price"] == "46", report
    assert DERIVED in report["plain"]["defaults"]
    assert report["plain"]["rule"] != "S1"


def test_a_doubtful_button_amount_equal_to_the_chips_in_front_is_the_price():
    screen = to_flop(AAPlainAdvice(clock=Clock()))
    screen.put(3, 30)
    report = screen.show(4, hero_controls=button(raw="30"))
    assert report["status"] == "ready" and report["price"] == "30"


@pytest.mark.parametrize("raw", ["40", "460", "4", "046", "4b", None])
def test_a_doubtful_button_amount_that_nothing_confirms_stays_unread(raw):
    screen = to_flop(AAPlainAdvice(clock=Clock()))
    bet_unread(screen, 3, 46)
    report = screen.show(4, hero_controls=button(raw=raw))
    assert report["status"] == "reading" and report["missing"][0] == "price"


def test_two_bets_in_the_pot_rise_do_not_confirm_one_price():
    # 3 号下 20、2 号跟 20（都没读到）：底池涨了 40，按钮读出 20 也对不上，不猜
    screen = to_flop(AAPlainAdvice(clock=Clock()), callers=(2,))
    bet_unread(screen, 2, 20)
    bet_unread(screen, 3, 20)
    report = screen.show(4, hero_controls=button(raw="20"))
    assert report["status"] == "reading" and report["missing"][0] == "price"


def test_chips_in_front_and_pot_rise_alone_are_not_enough_on_the_flop():
    screen = to_flop(AAPlainAdvice(clock=Clock()))
    screen.put(3, 30)
    report = screen.show(4, hero_controls=button())
    assert report["status"] == "reading" and report["missing"][0] == "price"


def to_turn(advice, clock=None):
    screen = to_flop(advice, clock)
    screen.turn(frames=3)                                # 都过牌
    screen.acted()
    screen.street("turn", "2s")
    return screen


def test_on_the_turn_chips_in_front_and_pot_rise_agree_without_a_digit():
    screen = to_turn(AAPlainAdvice(clock=Clock()))
    screen.put(3, 30)
    report = screen.show(4, hero_controls=button())
    assert report["status"] == "ready" and report["price"] == "30", report
    assert DERIVED in report["plain"]["defaults"]


def test_on_the_turn_a_pot_that_moved_before_it_was_locked_confirms_nothing():
    # 转牌一来 3 号就下了注（筹码没读到，底池读稳时已经涨了）：这条街开始的底池和翻牌
    # 最后的对不上，后来的注额和底池涨的就不拿来对
    screen = to_flop(AAPlainAdvice(clock=Clock()))
    screen.turn(frames=3)
    screen.acted()
    screen.put(3, 30, frames=0)
    screen.wagers[3] = None
    screen.show(3, street="turn", board=["Ah", "Kd", "7c", "2s", None])
    screen.put(2, 60)
    report = screen.show(4, hero_controls=button())
    assert report["status"] == "reading" and report["missing"][0] == "price"


def test_your_own_chips_on_the_street_stop_the_pot_rise_check():
    screen = to_turn(AAPlainAdvice(clock=Clock()))
    screen.put(3, 10)
    ready(screen, call=10)
    screen.put(HERO, 30)                                # 你加到 30
    screen.acted()
    bet_unread(screen, 3, 90)
    report = screen.show(4, hero_controls=button(raw="60"))
    assert report["status"] == "reading" and report["missing"][0] == "price"


def test_with_your_own_chips_on_the_street_even_a_matching_digit_is_not_taken():
    # 你下了 30，3 号加到 90：要跟 60。按钮读成没把握的 90（和 3 号面前的一样）也不算
    screen = to_turn(AAPlainAdvice(clock=Clock()))
    screen.put(HERO, 30)
    screen.put(3, 90)
    controls = button(raw="90")
    screen.show(3, hero_controls=controls)
    assert screen.advice.state.derived_price(controls) is None


def test_a_derived_price_is_never_a_wrong_number():
    # 翻牌、转牌上各种下注（一个人下、下了又被加、两个人跟），筹码读到没读到、按钮读出
    # 真的数还是没读出：按两处读数对上拿出来的要么是 None，要么和真的一样
    plays = [((3, 30),), ((2, 20), (3, 60)), ((2, 20), (3, 20)), ((3, 46),),
             ((2, 10), (3, 30), (2, 30))]
    used = 0
    for street, play, shown, digits in product(("flop", "turn"), plays,
                                               ("all", "none", "last", "first"),
                                               (True, False)):
        start = to_flop if street == "flop" else to_turn
        screen = start(AAPlainAdvice(clock=Clock()))
        for at, (seat, to) in enumerate(play):
            visible = (shown == "all" or (shown == "last" and at == len(play) - 1)
                       or (shown == "first" and at == 0))
            if visible:
                screen.put(seat, to)
            else:
                bet_unread(screen, seat, to)
        truth = max(to for _, to in play)
        state = screen.advice.state
        controls = button(raw=str(truth) if digits else None)
        screen.show(3, hero_controls=controls)
        found = state.derived_price(controls)
        if found is not None:
            used += 1
            assert found == truth, (street, play, shown, digits, found)
    assert used >= 10
