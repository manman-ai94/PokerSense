"""一页纸打法（plain）的实时通路（``aa_plain_advice``）：不重放，从每帧的画面字段和
按手锁存的状态直接算；就绪条件、一个决策只算一次、缺项默认（补充一、补充二）。

牌局都是合成的画面：8 人桌庄位 7（0 小盲、1 大盲、2 抓头），1/2/4(2)，每人 200。
``Screen`` 一帧一帧地放：先闪一下前注，再上盲注，然后各座位下注、弃牌、发公共牌，
轮到你（座位 4）时按钮出现。
"""

from copy import deepcopy

import pytest

from poker_engine.desktop import aa_plain_advice as live
from poker_engine.desktop.aa_plain_advice import AAPlainAdvice, HandState
from poker_engine.desktop.aa_session import frame_summary
from poker_engine.desktop.aa_solver_advice import AASolverAdvice
from poker_engine.scoreboard import plain_policy
from tests.scoreboard.test_plain_policy import spot

HERO = 4


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class Screen:
    """一手牌的画面，一帧一帧送进 ``advice``；筹码、底池跟着下注变。"""

    def __init__(self, advice, clock=None, seats=8, dealer=7, hero=("Qs", "Qh"),
                 stack=200, hand="hand_1", badges=True):
        self.advice, self.clock, self.frame, self.out = advice, clock, 0, []
        self.seats, self.badges = seats, badges
        self.hidden = set()                 # 筹码读不到的座位
        self.stacks = dict.fromkeys(range(seats), stack)
        self.wagers = dict.fromkeys(range(seats))
        self.pot = 0
        self.preflop_pot = None             # 翻前屏幕上显示的底池（None：显示真的）
        self.fields = {
            "street": "preflop", "hero": list(hero), "board": [None] * 5, "pot": "0",
            "dealer": dealer, "actor": None,
            "participants": {str(seat): "active" for seat in range(seats)},
            "stacks": {}, "street_wagers": {}, "mushroom_pool": None,
            "hero_controls": {"visible": False, "button": None, "call_amount": None},
            "actions_v1": {"hand_id": hand, "complete": True, "start": "pot_went_down",
                           "dealer": dealer, "actions": []}}

    def show(self, frames=3, **changes):
        self.fields.update(changes)
        self.fields["stacks"] = {str(seat): None if seat in self.hidden else str(chips)
                                 for seat, chips in self.stacks.items()}
        self.fields["street_wagers"] = {str(seat): None if chips is None else str(chips)
                                        for seat, chips in self.wagers.items()}
        self.fields["pot"] = str(self.pot)
        if self.preflop_pot is not None and self.fields["street"] == "preflop":
            self.fields["pot"] = self.preflop_pot or None
        for _ in range(frames):
            fields = deepcopy(self.fields)
            self.out.append(self.advice.observe_fields(fields, self.frame))
            self.frame += 1
            if self.clock is not None:
                self.clock.now += 0.1
        return self.out[-1]

    def deal(self, ante=2, blinds=(1, 2, 4)):
        self.show(2)
        for seat in self.stacks:
            self.stacks[seat] -= ante
            self.wagers[seat] = ante
        self.pot = ante * self.seats
        self.show(2)                                    # 前注闪一下
        self.wagers = dict.fromkeys(self.wagers)
        for seat, chips in zip((0, 1, 2), blinds):
            self.put(seat, chips, frames=0)
        return self.show(3)

    def put(self, seat, to, frames=3, badge=None):
        """``seat`` 这条街一共下到 ``to``。"""
        before = self.wagers.get(seat) or 0
        self.stacks[seat] -= to - before
        self.pot += to - before
        self.wagers[seat] = to
        if badge and self.badges:
            self._badge(seat, badge, to - before)
        return self.show(frames) if frames else None

    def fold(self, seat, frames=3):
        self.fields["participants"] = {**self.fields["participants"],
                                       str(seat): "folded"}
        if self.badges:
            self._badge(seat, "fold", 0)
        return self.show(frames)

    def _badge(self, seat, kind, chips):
        actions = self.fields["actions_v1"]["actions"]
        actions.append([self.frame, self.fields["street"], seat, kind,
                        str(chips) if kind != "fold" else "0", "pot_rise"])

    def street(self, name, *cards):
        board = [card for card in self.fields["board"] if card] + list(cards)
        self.wagers = dict.fromkeys(self.wagers)
        return self.show(3, street=name, board=board + [None] * (5 - len(board)))

    def turn(self, call=None, frames=4, button=None):
        """轮到你：按钮出现（``call``：要跟的金额；None 是让牌）。"""
        button = button or ("check" if call is None else "call")
        controls = {"visible": True, "button": button,
                    "call_amount": None if call is None else str(call)}
        return self.show(frames, hero_controls=controls)

    def acted(self, frames=2):
        return self.show(frames, hero_controls={"visible": False, "button": None,
                                                "call_amount": None})


def ready(screen, *args, **kwargs):
    report = screen.turn(*args, **kwargs)
    assert report["status"] == "ready", report
    return report


def same(report, observation):
    """实时窗口的建议和记分牌牌桌上同一步的建议一样（动作、尺寸、定生死的那一条）。"""
    expected = plain_policy.decide(observation).row()
    page = report["plain"]
    assert (page["action"], page["rule"], page["hits"]) == (
        expected["action"], expected["rule"], expected["hits"])
    assert page.get("to") == expected.get("to")


# -- 和记分牌牌桌上一样 ------------------------------------------------------------

@pytest.mark.parametrize("shown", ["0", ""])
def test_the_preflop_pot_comes_from_the_table_not_the_screen(shown):
    # AA 翻前屏幕上的底池是 0（注还摆在各人面前）；读不到也一样：按前注 × 人数 + 盲注
    # + 抓头 + 各座已投入的算，尺寸和记分牌一样（主人 2026-10-17：hand_3663 等）。
    screen = Screen(AAPlainAdvice(clock=Clock()), clock=None, hero=("Qs", "Qh"))
    screen.preflop_pot = shown
    screen.deal()
    screen.put(3, 12, badge="raise")
    report = ready(screen, call=12)
    assert report["pot"] == "35"                    # 16 + 1 + 2 + 4 + 12
    same(report, spot({4: "QsQh"}, "", "3r12"))
    assert report["plain"]["action"] == "raise" and float(report["plain"]["to"]) > 30


def test_preflop_facing_an_open_is_the_same_page_as_the_scoreboard():
    screen = Screen(AAPlainAdvice(clock=Clock()), clock=None, hero=("Qs", "Qh"))
    screen.deal()
    screen.put(3, 12, badge="raise")
    report = ready(screen, call=12)
    assert report["kind"] == "plain" and report["street"] == "preflop"
    same(report, spot({4: "QsQh"}, "", "3r12"))
    assert report["inferred_actions"] == 0 and report["acts_on_client"] is False
    assert report["plain"]["tag"].startswith("就绪 ")


def test_heads_up_flop_facing_a_bet_is_the_same_page_as_the_scoreboard():
    screen = Screen(AAPlainAdvice(), hero=("Qs", "Qh"))
    screen.deal()
    screen.fold(3)
    report = ready(screen, call=4)
    screen.put(HERO, 12)
    screen.acted()
    for seat in (5, 6, 7, 0, 1):
        screen.fold(seat)
    screen.put(2, 12)
    screen.street("flop", "Ah", "Kd", "7c")
    screen.put(2, 20)
    report = ready(screen, call=20)
    assert report["street"] == "flop"
    same(report, spot({4: "QsQh"}, "AhKd7c", "3f 4r12 5f 6f 7f 0f 1f 2c 2r20"))
    assert report["plain"]["range"] and report["plain"]["need"] is not None


def test_a_three_way_turn_is_the_same_page_as_the_scoreboard():
    screen = Screen(AAPlainAdvice(), hero=("Js", "Th"))
    screen.deal()
    screen.put(3, 4)
    ready(screen, call=4)
    screen.put(HERO, 4)
    screen.acted()
    for seat in (5, 6, 7, 0, 1):
        screen.fold(seat)
    screen.street("flop", "Jd", "8c", "2h")
    ready(screen)                                       # 抓头、早位先过牌
    screen.acted()
    screen.street("turn", "5s")
    screen.put(2, 10)
    screen.put(3, 10)
    report = ready(screen, call=10)
    same(report, spot({4: "JsTh"}, "Jd8c2h5s",
                      "3c 4c 5f 6f 7f 0f 1f 2c 2c 3c 4c 2r10 3c"))


# -- 就绪条件：没满足就不算 ---------------------------------------------------------

def opened(clock=None, **options):
    screen = Screen(AAPlainAdvice(clock=clock or Clock()), **options)
    screen.deal()
    screen.put(3, 12)
    return screen


def test_the_price_must_hold_three_frames():
    screen = opened()
    first = screen.turn(call=12, frames=2)
    assert (first["status"], first["reason"]) == ("reading", "price_not_steady")
    assert first["missing"] == ["price_not_steady"] and "advice" not in first
    assert screen.turn(call=12, frames=1)["status"] == "ready"


def test_your_cards_must_be_read():
    screen = opened(hero=(None, "Qh"))
    report = screen.turn(call=12)
    assert (report["status"], report["reason"]) == ("reading", "hero_cards")


def test_the_board_must_match_the_street():
    screen = opened()
    screen.show(street="flop", board=["Ah", "Kd", None, None, None])
    assert screen.turn(call=12)["missing"] == ["board"]


def test_the_opponents_still_in_must_hold_two_frames():
    advice = AAPlainAdvice(clock=Clock())
    screen = Screen(advice)
    screen.deal()
    screen.put(3, 12, frames=3)
    controls = {"visible": True, "button": "call", "call_amount": "12"}
    for state in ("active", "folded", "active", "folded"):     # 5 号一会儿在一会儿弃
        screen.fields["participants"]["5"] = state
        report = screen.show(1, hero_controls=controls)
    assert report["status"] == "reading" and "opponents" in report["missing"]


def test_cards_read_two_ways_in_a_hand_are_never_ready():
    clock = Clock()
    screen = opened(clock)
    screen.show(3, hero=["Qs", "Qd"])                   # 手牌读成了两种
    report = screen.turn(call=12, frames=10)
    assert report["status"] == "reading" and "card_conflict" in report["missing"]


def test_two_seconds_not_ready_is_iron_law_5_with_what_is_missing():
    clock = Clock()
    screen = opened(clock, hero=("Qs", None))
    screen.clock = clock
    report = screen.turn(call=12, frames=25)
    assert report["status"] == "ready" and report["kind"] == "plain"
    assert report["advice"] == [{"action": "fold", "frequency": 1.0}]
    page = report["plain"]
    assert page["rule"] == "S1" and page["missing"] == ["hero_cards"]
    assert page["tag"] == "铁律 5：缺你的手牌"
    assert page["reason"] == "画面没读稳：缺你的手牌；第 1 步·看不清 → 铁律 5——弃。"
    assert 2.0 <= page["waited"] < 2.2


def test_iron_law_5_checks_when_it_can():
    clock = Clock()
    screen = Screen(AAPlainAdvice(clock=clock), clock=clock, hero=(None, None))
    screen.deal()
    screen.put(3, 4)
    for seat in (5, 6, 7, 0, 1):
        screen.fold(seat)
    screen.street("flop", "Ah", "Kd", "7c")
    report = screen.turn(frames=25)
    assert report["advice"] == [{"action": "check", "frequency": 1.0}]
    assert report["to_call"] == "0"


def blind_hand(clock, hero=("Qs", "Qh"), opener=("call", 4)):
    """庄位 2：3 小盲、4（你）大盲、5 抓头；6 平跟（或加注），其余弃到你。"""
    screen = Screen(AAPlainAdvice(clock=clock), clock=clock, dealer=2, hero=hero)
    screen.deal(blinds=())
    for seat, chips in ((3, 1), (4, 2), (5, 4)):
        screen.put(seat, chips, frames=0)
    screen.show(3)
    kind, chips = opener
    screen.put(6, chips, badge=kind)
    for seat in (7, 0, 1, 2, 3):
        screen.fold(seat)
    return screen


def test_a_blind_nobody_raised_is_not_iron_law_5_without_your_cards():
    # v3.2：翻前轮到盲位且没人加注时铁律 5 不适用（过牌或补齐）；牌没读到就补齐
    clock = Clock()
    screen = blind_hand(clock, hero=("Qs", None))
    report = screen.turn(call=2, frames=25)
    assert report["status"] == "ready"
    assert report["advice"] == [{"action": "call", "frequency": 1.0}]
    page = report["plain"]
    assert page["rule"] == "I5.blind" and page["missing"] == ["hero_cards"]
    assert page["tag"] == "盲位没人加注：补齐（缺你的手牌）"


def test_a_blind_nobody_raised_follows_the_table_when_the_cards_are_read():
    clock = Clock()
    screen = blind_hand(clock)
    controls = {"visible": True, "button": "call", "call_amount": "2"}
    for state in ("active", "folded") * 13:                 # 7 号一会儿在一会儿弃
        screen.fields["participants"]["7"] = state
        report = screen.show(1, hero_controls=controls)
    assert report["status"] == "ready"
    page = report["plain"]
    assert page["rule"] == "T1.b" and page["missing"] == ["opponents"]
    assert page["tag"] == "盲位按表：缺在局对手没稳"
    assert report["advice"][0]["action"] == "raise"


def test_a_blind_facing_a_raise_is_still_iron_law_5():
    clock = Clock()
    screen = blind_hand(clock, hero=("Qs", None), opener=("raise", 12))
    report = screen.turn(call=10, frames=25)
    assert report["advice"] == [{"action": "fold", "frequency": 1.0}]
    assert report["plain"]["rule"] == "S1"


# -- 一个决策只算一次 ---------------------------------------------------------------

def test_a_decision_is_worked_out_once_and_kept(monkeypatch):
    screen = opened()
    first = ready(screen, call=12)
    calls = []
    monkeypatch.setattr(plain_policy, "decide",
                        lambda *args, **kwargs: calls.append(args) or None)
    screen.fields["actions_v1"]["actions"].append([screen.frame, "preflop", 5, "call",
                                                   "12", "pot_rise"])
    later = screen.turn(call=12, frames=5)                # 又读到一个动作：不是新决策
    assert later == first and not calls


def test_a_new_price_is_a_new_decision_with_the_old_one_beside_it():
    clock = Clock()
    screen = opened(clock)
    screen.clock = clock
    first = ready(screen, call=12)
    screen.put(5, 36)                                     # 5 号再加注到 36
    second = ready(screen, call=36)
    assert second is not first and second["price"] == "36"
    assert second["previous"]["price"] == "12"
    assert second["previous"]["advice"] == first["advice"]
    clock.now += 2.5
    assert "previous" not in screen.turn(call=36, frames=1)


# -- 缺项默认 -----------------------------------------------------------------------

def test_actions_come_from_the_bets_without_any_badge():
    screen = Screen(AAPlainAdvice(), badges=False)
    screen.deal()
    screen.put(3, 4)                                      # 平跟
    screen.put(HERO, 4)
    screen.acted()
    screen.put(5, 16)                                     # 5 号加注到 16
    screen.put(6, 16)
    for seat in (7, 0, 1, 2):
        screen.fold(seat)
    report = ready(screen, call=12)
    same(report, spot({4: "QsQh"}, "", "3c 4c 5r16 6c 7f 0f 1f 2f"))
    assert report["inferred_actions"] == 0


def test_a_player_who_folds_and_leaves_was_still_dealt_in():
    """10/09 实录：3 号弃牌后座位变空，他那一下弃牌还在动作里，这手照样是 8 个人
    （以前这样会算出错，那一步没有建议）。"""
    screen = Screen(AAPlainAdvice(), badges=False)
    screen.deal()
    screen.fold(3)
    screen.show(3, participants={**screen.fields["participants"], "3": "empty"})
    report = ready(screen, call=4)
    same(report, spot({4: "QsQh"}, "", "3f"))
    assert report["plain"]["rule"] == "T1.raise"


def test_hand_actions_that_contradict_themselves_are_iron_law_5(monkeypatch):
    def broken(observation):
        raise KeyError(2)
    monkeypatch.setattr(plain_policy, "decide", broken)
    screen = opened()
    report = ready(screen, call=12)
    assert report["advice"] == [{"action": "fold", "frequency": 1.0}]
    assert report["plain"]["tag"] == "铁律 5：缺这手的动作对不上"


def test_a_raise_nobody_read_is_filled_in_from_your_price():
    screen = Screen(AAPlainAdvice(), badges=False)
    screen.deal()
    screen.put(3, 12, frames=0)
    screen.wagers[3] = None                               # 3 号的注额一直没读到
    screen.show(3)
    report = ready(screen, call=12)
    same(report, spot({4: "QsQh"}, "", "3r12"))
    assert report["inferred_actions"] == 1
    assert "有动作没读到→按注额补上" in report["plain"]["defaults"]


def test_your_own_missed_raise_is_put_before_the_reraise():
    screen = Screen(AAPlainAdvice(), badges=False, hero=("Ah", "Kh"))
    screen.deal()
    screen.fold(3)
    ready(screen, call=4)
    screen.put(HERO, 12)
    screen.wagers[HERO] = None                            # 你的加注没读到
    screen.acted()
    screen.put(5, 36)
    for seat in (6, 7, 0, 1, 2):
        screen.fold(seat)
    report = ready(screen, call=24)
    same(report, spot({4: "AhKh"}, "", "3f 4r12 5r36 6f 7f 0f 1f 2f"))


def test_an_opponent_stack_not_read_is_carried_or_left_out():
    screen = Screen(AAPlainAdvice())
    screen.deal()
    screen.hidden.add(3)                                  # 3 号加注以后筹码读不到了
    screen.put(3, 12)
    for seat in (5, 6, 7, 0, 1, 2):
        screen.fold(seat)
    report = ready(screen, call=12)
    observation, defaults, _ = live.table_observation(
        screen.advice.state, screen.fields, screen.advice.stakes())
    assert observation["stacks"]["3"] == "186"           # 上次读到的 198 减之后投入的 12
    assert defaults == ["carried_stack"]
    assert "对手筹码按上次读数往前带" in report["plain"]["defaults"]
    never = Screen(AAPlainAdvice())
    never.hidden.add(3)                                   # 一直没读到
    never.deal()
    never.put(3, 12)
    report = ready(never, call=12)
    assert "缺对手筹码→按最深已读" in report["plain"]["defaults"]
    observation, _, _ = live.table_observation(never.advice.state, never.fields,
                                               never.advice.stakes())
    assert "3" not in observation["stacks"]


def test_the_mushroom_pool_not_read_counts_as_none():
    screen = Screen(AAPlainAdvice(), dealer=3, hero=("Ah", "9c"))     # 你是小盲
    screen.show(2)
    report = None
    for seat in range(8):
        screen.stacks[seat] -= 2
        screen.wagers[seat] = 2
    screen.pot = 16
    screen.show(2)
    screen.wagers = dict.fromkeys(screen.wagers)
    for seat, chips in zip((4, 5, 6), (1, 2, 4)):
        screen.put(seat, chips, frames=0)
    screen.show(3)
    for seat in (7, 0, 1, 2, 3):
        screen.fold(seat)
    report = ready(screen, call=3)
    assert "蘑菇池没读到→按 0" in report["plain"]["defaults"]
    assert report["mushroom_pool"] is None


def test_a_bomb_pot_is_no_preflop_action_and_a_pot_the_players_share():
    # 2/4/8(4) 桌，每人投 20（不是 7 个大盲）：按“翻前没人动、开局底池能被人数整除”认。
    screen = Screen(AAPlainAdvice(), hero=("9h", "8h"))
    screen.show(2)
    for seat in range(8):
        screen.stacks[seat] -= 20
        screen.wagers[seat] = 20
    screen.pot = 160
    screen.show(3)
    screen.wagers = dict.fromkeys(screen.wagers)
    screen.street("flop", "7h", "6c", "2d")
    report = ready(screen)
    assert report["bomb_pot"] == "20"
    observation, _, _ = live.table_observation(screen.advice.state, screen.fields,
                                               screen.advice.stakes())
    assert observation["straddler_seat"] is None and observation["public_history"] == []


def test_the_dealer_is_the_one_the_blinds_show():
    screen = Screen(AAPlainAdvice(), dealer=5)            # 按钮还显示上一手的庄位
    screen.deal()
    screen.put(3, 12)
    ready(screen, call=12)
    assert screen.advice.state.dealer(screen.advice.stakes()) == 7


def test_an_unread_dealer_comes_from_the_one_blind_that_was_read():
    stakes = {"small_blind": "1", "big_blind": "2", "straddle_amount": "4"}
    seats = list(range(8))
    flash = {"street_wagers": {str(seat): "2" for seat in seats}}      # 前注闪一下
    assert live.posted_dealer([flash, {"street_wagers": {"2": "4"}}], seats,
                              stakes) == 7
    assert live.posted_dealer([{"street_wagers": {"1": "2"}}], seats, stakes) == 7
    assert live.posted_dealer([{"street_wagers": {"0": "1"}}], seats, stakes) == 7
    two = [{"street_wagers": {"0": "1"}}, {"street_wagers": {"5": "4"}}]
    assert live.posted_dealer(two, seats, stakes) is None
    assert live.posted_dealer([flash], seats, stakes) is None
    screen = Screen(AAPlainAdvice(), dealer=None)        # 庄位按钮一直没读到
    screen.deal(blinds=())
    screen.stacks[0] -= 1
    screen.stacks[1] -= 2
    screen.pot += 3
    screen.put(2, 4)                                     # 只读到抓头的筹码
    screen.put(3, 12, badge="raise")
    report = ready(screen, call=12)
    assert screen.advice.state.dealer(screen.advice.stakes()) == 7
    assert report["plain"]["rule"] != "S1"


def test_the_flop_pot_is_kept_from_the_flop_s_first_frames():
    screen = Screen(AAPlainAdvice())
    screen.deal()
    screen.put(3, 4)
    ready(screen, call=4)
    screen.put(HERO, 4)
    screen.acted()
    for seat in (5, 6, 7, 0, 1):
        screen.fold(seat)
    screen.street("flop", "Jd", "8c", "2h")
    screen.put(2, 10)
    report = ready(screen, call=10)
    assert screen.advice.state.flop_pot == 31
    assert "翻牌底池按手锁存" in report["plain"]["defaults"]


def test_last_hand_s_cards_still_showing_are_not_read_as_this_hand_s():
    advice = AAPlainAdvice()
    first = Screen(advice, hero=("Qs", "Qh"))
    first.deal()
    first.put(3, 12)
    ready(first, call=12)
    second = Screen(advice, hero=("Qs", "Qh"), hand="hand_2")
    second.fields["hero"] = ["Qs", "Qh"]                  # 新一手开头还显示着上一手的牌
    second.deal()
    second.show(3, hero=["7c", "2d"])
    second.put(3, 12)
    report = ready(second, call=12)
    assert advice.state.hero == ("2d", "7c") and not advice.state.card_conflict()
    assert report["plain"]["hand"] == "72o"


# -- 窗口、日志和打分 ---------------------------------------------------------------

def test_the_window_switch_sends_every_frame_to_the_live_page():
    advice = AASolverAdvice(strategy="plain")
    screen = Screen(advice)
    screen.deal()
    screen.put(3, 12)
    report = ready(screen, call=12)
    assert report["kind"] == "plain"
    hand, decisions = advice.settled()
    assert hand == "hand_1" and list(decisions.values()) == [report]
    assert advice.stakes()["source"] == "table"
    logged = frame_summary({"solver_advice_v1": report})["solver_advice"]
    assert logged["plain"] == report["plain"] and logged["price"] == "12"
    advice.set_strategy("classic")
    assert advice.settled() == (None, {})


def test_hand_state_is_kept_per_hand():
    state = HandState("hand_9")
    assert state.seats() == [] and state.bomb() is None and not state.card_conflict()


@pytest.mark.parametrize("button,amount,stack,expected", [
    ("check", None, None, 0), ("call", "12", None, 12), ("all_in", None, "150", 150),
    ("all_in", "80", "150", 80), ("call", None, None, None)])
def test_the_price_on_your_button(button, amount, stack, expected):
    controls = {"visible": True, "button": button, "call_amount": amount}
    found = live.price(controls, None if stack is None else live._amount(stack))
    assert found == (None if expected is None else live._amount(expected))


def test_your_action_is_graded_against_the_page():
    from poker_engine.desktop.aa_grading import AAGrades

    advice = AASolverAdvice(strategy="plain")
    grades = AAGrades(advice)

    class Both:
        def observe_fields(self, fields, frame):
            report = advice.observe_fields(fields, frame)
            grades.observe_fields(fields, frame)
            return report

    screen = Screen(Both(), hero=("7c", "2d"))
    screen.deal()
    screen.put(3, 12, badge="raise")
    report = ready(screen, call=12)
    assert report["advice"] == [{"action": "fold", "frequency": 1.0}]
    screen.acted(frames=0)
    screen.put(HERO, 12, badge="call")                    # 你跟了：没照一页纸
    graded = grades.report()
    assert graded["decisions"] == 1 and graded["advised"] == 1
    assert graded["last"]["action"]["kind"] == "call"
    assert graded["last"]["grade"] != "best"


def test_a_price_misread_for_a_frame_does_not_start_the_two_seconds():
    clock = Clock()
    screen = opened(clock)
    screen.clock = clock
    ready(screen, call=12)
    screen.turn(call=72, frames=1)                        # 一帧读错
    screen.turn(call=12, frames=30)                       # 3 秒过去
    screen.put(5, 36, frames=0)
    report = screen.turn(call=36, frames=1)               # 真的加注了：从现在开始等
    assert report["status"] == "reading"
