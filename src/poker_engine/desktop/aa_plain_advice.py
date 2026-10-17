"""一页纸打法（plain）的实时通路：不重放、不开后台线程，每帧直接从画面字段算。

旧路（``AASolverAdvice`` 的 classic）每个决策先把这手牌重放到模拟牌桌上
（``aa_solver_input``），再分翻前模型、求解器、范围规则三条路在后台算，0.6 秒没
结果先给粗略建议；谁先出谁先显示，后面的盖掉前面的（补充二：主人 593 个决策里
85 次先粗略再换、22 次改口、9% 到最后只有粗略的；杜 26%）。plain 只有一条路
（补充一、补充二，2026-10-16）：

- **按手锁存的状态** ``HandState``（hand_state_v1），每帧喂一次：庄位（按桌上的
  盲注校正，``blind_dealer``）、本桌级别（``aa_stakes``）、各街各座位读到的最高注额
  （连续两帧一样才算）和它们涨的先后、每个座位最近一次读到的筹码、开局底池、翻牌
  开始时的底池、暴击、蘑菇池、你的手牌和公共牌各读出过几种。
- **动作从注额推**，不靠动作徽章：一个座位这条街的注额涨到比当时最高的还高是加注
  （翻后没人下过是下注），涨到一样是跟注；翻前停在抓头上是平跟。同一个座位连着涨
  两次、中间没别人动，是一个动作读了两下。弃牌看座位状态。注额一次没读到的，用动作
  历史里读到的那一下补；你要跟的金额比推出来的最高注多，就是有人加注没读到：补一个
  加到那么多的加注（这条街读到注额最高的对手，否则动作历史里这条街最后加注的人，
  否则在你前面最近说话的还在局对手）。
- **缺项默认**（补充二第四节、v3.2 一·定义）：对手筹码没读到，用他上一次的读数减之后
  投入的，还是没有就不算他（有效筹码按最深的已读对手）；蘑菇池没读到按 0；暴击按“翻前
  没人动、开局底池能被人数整除”认；庄位按这手开局锁定，读不到按盲注和抓头的位置推
  （只读到其中一个也行）；翻牌开始时的底池按手锁存。真正缺了没法算的只有四样：你的手牌、
  要跟的金额、底池（翻后）、你的筹码（还有庄位）。翻前的底池不读屏幕（AA 翻前显示
  0，注还摆在各人面前），按结构算：前注 × 人数 + 小盲 + 大盲 + 抓头 + 各座已投入的。
- **就绪条件**：按钮出现、要跟的金额连续 3 帧一样、两张手牌连续两帧读成一样、公共牌
  张数和街道对得上、还在局的对手连续 2 帧一样、底池（翻后）和你的筹码读到了；这手的手牌或
  公共牌读出过两种就不就绪（``card_conflict``，宁可铁律 5 也不按其中一种算）。就绪前
  显示“读画面中”；等了 2 秒还没就绪，按铁律 5（弃，能过牌就过牌）并写明缺什么。翻前
  轮到盲位且没人加注时铁律 5 不适用（v3.2）：读到了牌就照表，牌没读到就过牌或补齐。
- **一个决策只算一次**：决策 = （这手牌，街道，要跟的金额）。算完就显示，同一个决策里
  画面再变也不重算、不换；要跟的金额变了（有人加注）才是新决策，旧建议在旁边留 2 秒。

算一次不到 0.1 秒（胜率是固定范围的蒙特卡洛），在读帧的线程里直接算。只显示建议，
不替你点。
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation
import json
import time

from poker_engine.scoreboard import plain_policy

from .aa_action_history import COMPACT_FIELDS
from .aa_solver_input import blind_dealer
from .aa_stakes import RULES_PATH, detect_stakes, settle_stakes, stakes_report

HERO = 4                        # 你的座位：下面正中
STREETS = ("preflop", "flop", "turn", "river")
BOARD_CARDS = {"preflop": 0, "flop": 3, "turn": 4, "river": 5}
IN_HAND = frozenset({"active", "folded", "all_in"})
LIVE = frozenset({"active", "all_in"})
STEADY = 2                      # 注额、筹码、底池、牌：连续两帧读成一样才算
PRICE_FRAMES = 3                # 要跟的金额连续 3 帧一样
SEATS_FRAMES = 2                # 还在局的对手连续 2 帧一样
READY_SECONDS = 2.0             # 轮到你 2 秒还没就绪：铁律 5
READY_FRAMES = 20               # 没有时钟可看时按帧数（约 10 帧一秒）
SIDE_BY_SIDE = 2.0              # 要跟的金额变了：旧建议在旁边留 2 秒
OPENING_FRAMES = 300            # 认级别、庄位用的开局帧，最多留这么多
EPSILON = 1e-9
BASIS = "一页纸打法 v3.3b（plain）：只按这一页的规则；只显示建议，不替你点"

# 就绪条件没满足时缺的是什么（窗口上写“缺 X”）。
MISSING = {"price": "要跟的金额", "price_not_steady": "要跟的金额没稳",
           "hero_cards": "你的手牌", "card_conflict": "牌读出过两种",
           "board": "公共牌", "opponents": "在局对手没稳", "pot": "底池",
           "stack": "你的筹码", "dealer": "庄位", "seat": "你的座位",
           "actions": "这手的动作对不上"}
# 盲位没人加注时表里的规则（铁律 5 不适用，画面没读稳也照表）。
BLIND_RULES = frozenset({"T1.a", "T1.a.fold", "T1.b", "T1.c", "T1.straddle", "T1.str",
                         "T1.iso2", "M.iso"})
# 按默认补上的缺项（窗口上的小标签）。
DEFAULTS = {"opponent_stack": "缺对手筹码→按最深已读",
            "carried_stack": "对手筹码按上次读数往前带",
            "mushroom": "蘑菇池没读到→按 0",
            "inferred": "有动作没读到→按注额补上",
            "flop_pot": "翻牌底池按手锁存"}


def _amount(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return amount if amount.is_finite() and amount >= 0 else None


def _money(value):
    value = Decimal(str(value))
    return format(value.normalize(), "f") if value else "0"


def price(controls, stack=None):
    """你的按钮说的价格（要跟的金额）：让牌 0，跟注是跟注额，All in 是跟注额（没读到
    就是你的筹码）；没有就是 None。"""
    if not controls.get("visible"):
        return None
    button = controls.get("button")
    if button == "check":
        return Decimal(0)
    amount = _amount(controls.get("call_amount"))
    if button == "call":
        return amount
    if button == "all_in":
        return amount if amount is not None else stack
    return None


class _Steady:
    """一个读数连续几帧一样才算：``read`` 返回算数的值（还没稳是 None）。"""

    def __init__(self, frames=STEADY):
        self.frames, self.last, self.count = frames, object(), 0

    def read(self, value):
        self.count = self.count + 1 if value == self.last else 1
        self.last = value
        return value if self.count >= self.frames else None


class HandState:
    """hand_state_v1：一手牌里按手锁存的事实（见模块说明），每帧 ``observe`` 一次。

    ``last``：上一手结束时的手牌和公共牌。新一手开头几帧可能还显示着它们，读成一样
    的不算，直到读到别的（或读到空）。"""

    def __init__(self, hand_id, last=None):
        last = last or {}
        self.hand_id = hand_id
        self.frames = 0
        self.opening, self.opened = [], False
        self.states, self.previous_live, self.live_frames = {}, None, 0
        self.seen_live, self.folds = set(), []
        self._fold_reads = {}
        self.dealers = []
        self.street, self.carry = None, {}
        self._wager_reads, self.events, self.wagers = {}, [], {}
        self._stack_reads, self.stacks = {}, {}
        self._pot = _Steady()
        self.pot = self.opening_pot = self.flop_pot = None
        self._stale_hero = last.get("hero")
        self._stale_board = last.get("board")
        self._hero = _Steady()
        self.hero, self.hero_seen = None, set()
        self._board = [_Steady() for _ in range(5)]
        self.board, self.board_seen = [None] * 5, [set() for _ in range(5)]
        self.mushroom = None
        self.prices = []                # 按钮出现的帧上的价格，最近几帧
        self.acted = {}                 # 街 -> 你的按钮上次消失的帧（你在这条街动过）
        self.preflop_turn = False
        self._visible = False
        self.history = {}               # 动作历史（徽章）：最后一帧读到的

    # -- 每帧 -------------------------------------------------------------------

    def observe(self, fields, frame):
        self.frames += 1
        self.history = fields.get("actions_v1") or self.history
        street = fields.get("street")
        if street in STREETS and street != self.street:
            later = (self.street is not None
                     and STREETS.index(street) > STREETS.index(self.street))
            if later:
                # 上一条街的筹码还在桌上：读成一样的不算，直到这个座位读到别的。
                self.carry = {seat: value for (on, seat), value in self.wagers.items()
                              if on == self.street}
            self.street = street
        self._seats(fields, frame)
        self._wager_frame(fields, frame)
        self._stack_frame(fields, frame)
        self._pot_frame(fields)
        self._cards(fields)
        pool = _amount(fields.get("mushroom_pool"))
        if pool is not None:
            self.mushroom = pool
        controls = fields.get("hero_controls") or {}
        if controls.get("visible"):
            self.preflop_turn |= self.street == "preflop"
            self.prices.append(price(controls, self.stack_read(HERO)))
            del self.prices[:-PRICE_FRAMES]
        else:
            if self._visible:
                self.acted[self.street] = frame
            self.prices = []
        self._visible = bool(controls.get("visible"))
        if not self.opened:
            self.opening.append(fields)
            del self.opening[:-OPENING_FRAMES]
            self.opened = bool(self.history.get("actions"))

    def _seats(self, fields, frame):
        states = {int(seat): state for seat, state in
                  (fields.get("participants") or {}).items() if state is not None}
        self.states = states
        live = tuple(sorted(seat for seat, state in states.items()
                            if state in LIVE and seat != HERO))
        self.live_frames = self.live_frames + 1 if live == self.previous_live else 1
        self.previous_live = live
        for seat, state in states.items():
            if state in LIVE:
                self.seen_live.add(seat)
            steady = self._fold_reads.setdefault(seat, _Steady())
            if (steady.read(state) == "folded" and seat in self.seen_live
                    and seat not in {fold[2] for fold in self.folds}):
                self.folds.append((frame, self.street, seat))
        if fields.get("dealer") is not None:
            self.dealers.append(int(fields["dealer"]))
            del self.dealers[:-20]

    def _wager_frame(self, fields, frame):
        reads = {int(seat): _amount(value)
                 for seat, value in (fields.get("street_wagers") or {}).items()}
        values = [value for value in reads.values() if value]
        # 开局的前注：每个座位前面一样多的筹码闪一下（暴击局是每人投的那一份），不是动作。
        flash = (self.street == "preflop" and len(values) >= 3 and len(set(values)) == 1
                 and not any(on == "preflop" for _, on, *_ in self.events))
        for seat, value in reads.items():
            steady = self._wager_reads.setdefault(seat, _Steady()).read(value)
            if value is None:
                self.carry.pop(seat, None)
                continue
            if steady is None or flash or self.street not in STREETS:
                continue
            if seat in self.carry:
                if self.carry[seat] == steady:
                    continue
                del self.carry[seat]
            key = (self.street, seat)
            if steady > self.wagers.get(key, Decimal(0)):
                self.wagers[key] = steady
                self.events.append((frame, self.street, seat, steady))

    def _stack_frame(self, fields, frame):
        for seat, value in (fields.get("stacks") or {}).items():
            steady = self._stack_reads.setdefault(int(seat), _Steady()).read(
                _amount(value))
            if steady is not None:
                self.stacks[int(seat)] = (steady, frame)

    def _pot_frame(self, fields):
        steady = self._pot.read(_amount(fields.get("pot")))
        if steady is None:
            return
        self.pot = steady
        if self.opening_pot is None and steady > 0:
            self.opening_pot = steady
        flop_bets = any(on == "flop" for _, on, *_ in self.events)
        if (self.flop_pot is None and self.street == "flop" and not flop_bets
                and len(self._board_cards()) == 3):
            self.flop_pot = steady

    def _cards(self, fields):
        hero = tuple(sorted(card for card in fields.get("hero") or () if card))
        if self._stale_hero is not None and (
                not hero or (len(hero) == 2 and hero != tuple(self._stale_hero))):
            self._stale_hero = None
        steady = self._hero.read(hero if len(hero) == 2 else None)
        if steady is not None and self._stale_hero is None:
            self.hero = steady
            self.hero_seen.add(steady)
        board = list(fields.get("board") or ()) + [None] * 5
        if self._stale_board is not None:
            old = list(self._stale_board) + [None] * 5
            read = [(card, old[at]) for at, card in enumerate(board[:5]) if card]
            if read and all(card == was for card, was in read):
                return                      # 上一手的公共牌还在
            self._stale_board = None
        for at in range(5):
            steady = self._board[at].read(board[at])
            if steady is not None:
                self.board[at] = steady
                self.board_seen[at].add(steady)
            elif board[at] is None and self._board[at].count >= STEADY:
                self.board[at] = None

    # -- 读出来的事实 -----------------------------------------------------------

    def _board_cards(self):
        cards = []
        for card in self.board:
            if card is None:
                break
            cards.append(card)
        return cards

    def card_conflict(self):
        """这手的手牌或公共牌读出过两种。"""
        return len(self.hero_seen) > 1 or any(len(seen) > 1 for seen in self.board_seen)

    def stack_read(self, seat):
        found = self.stacks.get(seat)
        return None if found is None else found[0]

    def seats(self):
        """这手发了牌的座位：现在的状态是在局、弃牌或全下的，加上这手投过钱的、
        弃过牌的（弃了牌就离座的人也是这手发了牌的）。"""
        seats = {seat for seat, state in self.states.items() if state in IN_HAND}
        seats |= {seat for _, _, seat, _ in self.events}
        seats |= {seat for _, _, seat in self.folds}
        return sorted(seats)

    def stakes(self, earlier=None):
        """这手的级别（``aa_stakes``）：开局帧上的盲注和前注，没有就按前面几手的。"""
        found = detect_stakes(self.opening, self.seats(), self.opening_pot)
        return settle_stakes(found, earlier)

    def bomb(self):
        """暴击局每人投的那一份，或 None：翻前没人动（没读到翻前动作，你也没在翻前
        轮到过），已经翻牌了，开局底池能被人数整除（补充一第五节第 3 条）。"""
        seats = self.seats()
        if (self.street in (None, "preflop") or self.preflop_turn or not seats
                or self.opening_pot is None or any(
                    action[1] == "preflop" for action in self._history_actions())):
            return None
        post = self.opening_pot / len(seats)
        return post if post == post.to_integral_value() and post > 0 else None

    def dealer(self, stakes, bomb=None):
        """庄位：桌上的盲注说的（``blind_dealer``）；暴击局没有盲注，是第一个被读到要
        说话的座位前面那个；再没有是这手读到最多的庄位；庄位读不到，按只读到的一个
        盲注或抓头推（``posted_dealer``，v3.2 一·定义）。"""
        seats = self.seats()
        found = None if bomb else blind_dealer(self.opening, seats, stakes)
        if found is None and bomb is not None:
            first = _first_actor(self.opening)
            if first in seats:
                found = seats[seats.index(first) - 1]
        if found is None and self.dealers:
            found = Counter(self.dealers).most_common(1)[0][0]
        if found is None and bomb is None:
            found = posted_dealer(self.opening, seats, stakes)
        return found if found in seats else None

    def _history_actions(self):
        return [tuple(item) for item in self.history.get("actions") or ()]


def posted_dealer(fields, seats, stakes):
    """庄位读不到、小盲大盲也没一起读到时，按开局帧上只读到的一个盲注推：小盲的前一位、
    大盲的前两位、抓头的前三位（这手发了牌的座位里数）。每人一样多的那一下是前注，不算；
    推出来两种的不算（None）。"""
    back = {Decimal(str(stakes["small_blind"])): 1,
            Decimal(str(stakes["big_blind"])): 2}
    if len(seats) >= 4:
        back[Decimal(str(stakes["straddle_amount"]))] = 3
    found = set()
    for f in fields:
        wagers = {int(seat): _amount(value)
                  for seat, value in (f.get("street_wagers") or {}).items()}
        wagers = {seat: value for seat, value in wagers.items() if value}
        if len(wagers) >= 3 and len(set(wagers.values())) == 1:
            continue
        for amount, steps in back.items():
            at = [seat for seat, value in wagers.items() if value == amount]
            if len(at) == 1 and at[0] in seats:
                found.add(seats[(seats.index(at[0]) - steps) % len(seats)])
    return found.pop() if len(found) == 1 else None


def blind_unraised(state, stakes, now):
    """你在小盲、大盲或抓头，翻前没人加注（价格不超过补齐到抓头）：铁律 5 不适用。"""
    if now is None or state.bomb() is not None:
        return False
    seats = state.seats()
    dealer = state.dealer(stakes)
    if dealer is None or HERO not in seats or len(seats) < 3:
        return False
    ring = _clockwise(seats, dealer)
    posts = [Decimal(str(stakes["small_blind"])), Decimal(str(stakes["big_blind"]))]
    if len(ring) >= 4:
        posts.append(Decimal(str(stakes["straddle_amount"])))
    at = ring.index(HERO)
    return 1 <= at <= len(posts) and posts[at - 1] + now <= posts[-1]


def _first_actor(fields):
    """第一个连续两帧被读到要说话的座位，或 None。"""
    last = None
    for f in fields:
        actor = f.get("actor")
        if actor is None:
            continue
        if actor == last:
            return int(actor)
        last = actor
    return None


# -- 从按手锁存的状态拼出 plain_policy 要的观察 ---------------------------------------

def _clockwise(seats, dealer):
    at = seats.index(dealer)
    return seats[at:] + seats[:at]


def _order(seats, dealer, street, straddle):
    """这条街说话的顺序：翻后小盲先说；翻前抓头后面的人先说（没有抓头是大盲后面）。"""
    ring = _clockwise(seats, dealer)
    first = 1 if street != "preflop" else (4 if straddle else 3)
    first %= len(ring)
    return ring[first:] + ring[:first]


def _rules(stakes, players):
    raw = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    raw.update({key: _money(stakes[key]) for key in
                ("small_blind", "big_blind", "straddle_amount", "ante")})
    return {**raw, "table_size": players}


def _history_extra(history, events, seats):
    """动作历史（徽章）里读到、注额没读到的跟注、加注：（帧, 街, 座位, None, 投入）。"""
    extra = []
    have = {(street, seat) for _, street, seat, _ in events}
    for item in history.get("actions") or ():
        action = dict(zip(COMPACT_FIELDS, item))
        chips = _amount(action.get("amount"))
        seat = action.get("slot")
        if (action.get("kind") in ("call", "raise", "all_in") and chips
                and seat in seats and (action["street"], seat) not in have):
            extra.append((action["frame"], action["street"], seat, None, chips))
    return extra


class _Builder:
    """一手牌的动作行（``public_history``），从注额推出来（见模块说明）。"""

    def __init__(self, seats, posts, all_in=()):
        self.rows, self.bets, self.top = [], {}, Decimal(0)
        self.increment = Decimal(0)
        self.seats, self.posts, self.all_in = seats, posts, set(all_in)
        self.inferred = 0

    def street(self, street, big_blind):
        self.bets = {seat: Decimal(0) for seat in self.seats}
        if street == "preflop":
            self.bets.update(self.posts)
        self.top = max(self.bets.values(), default=Decimal(0))
        self.increment = self.top if street == "preflop" and self.top else big_blind
        self.on = street

    def fold(self, frame, seat):
        self.rows.append({"frame": frame, "actor": seat, "street": self.on,
                          "id": "fold", "kind": "fold", "raise_to": None, "paid": "0"})

    def put(self, frame, seat, to, inferred=False):
        """``seat`` 这条街一共下到 ``to``。"""
        mine = self.bets.get(seat, Decimal(0))
        if to <= mine or (to + Decimal(EPSILON) < self.top and seat not in self.all_in):
            # 没涨，或者比当时最高注少又不是全下：读错了一下（比如开局前注闪一下）。
            return
        self.inferred += inferred
        last = self.rows[-1] if self.rows else None
        if (last is not None and last["actor"] == seat and last["street"] == self.on
                and last["kind"] != "fold"):
            # 同一个座位连着涨、中间没别人动：是一个动作读了两下。
            self.rows.pop()
            mine = mine - Decimal(last["paid"])
            if last["kind"] == "raise_to":
                self.top = max(self._top_without(seat), mine)
        paid = to - mine
        if to > self.top + Decimal(EPSILON):
            self.increment = max(self.increment, to - self.top)
            self.top = to
            row = {"id": "raise_to:" + _money(to), "kind": "raise_to",
                   "raise_to": _money(to)}
        else:
            row = {"id": "check_call", "kind": "check_call", "raise_to": None}
        self.bets[seat] = to
        self.rows.append({"frame": frame, "actor": seat, "street": self.on, **row,
                          "paid": _money(paid)})

    def _top_without(self, seat):
        return max((value for other, value in self.bets.items() if other != seat),
                   default=Decimal(0))


def table_observation(state, fields, stakes):
    """(观察, 按默认补上的, 缺的)：plain_policy.decide 要的观察（和记分牌牌桌上的
    ``AAFullHandArena.observe`` 一个样），从按手锁存的状态和这一帧拼出来；缺了没法算的
    时候观察是 None。"""
    defaults, missing = [], []
    street = fields.get("street")
    seats = state.seats()
    controls = fields.get("hero_controls") or {}
    stack = state.stack_read(HERO)
    to_call = price(controls, stack)
    pot = state.pot if state.pot is not None else _amount(fields.get("pot"))
    if HERO not in seats:
        missing.append("seat")
    if to_call is None:
        missing.append("price")
    if pot is None and street != "preflop":       # 翻前底池按结构算，不读屏幕
        missing.append("pot")
    if stack is None:
        missing.append("stack")
    if state.hero is None:
        missing.append("hero_cards")
    bomb = state.bomb()
    dealer = state.dealer(stakes, bomb) if seats else None
    if dealer is None:
        missing.append("dealer")
    if missing:
        return None, defaults, missing
    big_blind = Decimal(stakes["big_blind"])
    ring = _clockwise(seats, dealer)
    straddler = ring[3] if len(ring) >= 4 and bomb is None else None
    posts = {}
    if bomb is None and len(ring) >= 3:
        posts = {ring[1]: Decimal(stakes["small_blind"]), ring[2]: big_blind}
        if straddler is not None:
            posts[straddler] = Decimal(stakes["straddle_amount"])
    builder = _Builder(seats, posts, [seat for seat, now in state.states.items()
                                      if now == "all_in"])
    events = [event + (None,) for event in state.events]
    events += _history_extra(state.history, state.events, set(seats))
    folds = {seat: (frame, on) for frame, on, seat in state.folds}
    for action in state._history_actions():
        item = dict(zip(COMPACT_FIELDS, action))
        if item.get("kind") == "fold" and item.get("slot") in seats:
            folds.setdefault(item["slot"], (item["frame"], item["street"]))
    folded = {seat for seat, now in state.states.items() if now == "folded"}
    folded |= set(folds)
    folded &= set(seats)
    folded.discard(HERO)
    streets = STREETS[1:] if bomb is not None else STREETS
    upto = streets[:streets.index(street) + 1] if street in streets else ()
    if not upto:
        return None, defaults, ["board"]
    final = {}
    for on in upto:
        builder.street(on, big_blind)
        moves = sorted([(frame, 1, seat, value, chips) for frame, at, seat, value, chips
                        in events if at == on]
                       + [(frame, 0, seat, None, None) for seat, (frame, at)
                          in folds.items() if at == on], key=lambda item: item[:2])
        for frame, kind, seat, value, chips in moves:
            if kind == 0:
                builder.fold(frame, seat)
            elif value is not None:
                builder.put(frame, seat, value)
            else:
                builder.put(frame, seat, builder.bets.get(seat, Decimal(0)) + chips)
        if on != street:
            final[on] = dict(builder.bets)
    _fit_price(builder, state, street, to_call, controls, dealer, seats, folded,
               straddler is not None)
    if builder.inferred:
        defaults.append("inferred")
    ante = Decimal(0) if bomb is not None else Decimal(stakes["ante"])
    contributions = {}
    for seat in seats:
        put = (bomb if bomb is not None else ante) + builder.bets.get(seat, Decimal(0))
        put += sum(bets.get(seat, Decimal(0)) for bets in final.values())
        contributions[seat] = put
    if street == "preflop":
        # AA 翻前屏幕上的底池是 0（注还摆在各人面前）：按结构算，前注 × 人数 + 小盲
        # + 大盲 + 抓头 + 各座这条街已投入的，都在 contributions 里（主人 2026-10-17）。
        pot = sum(contributions.values(), Decimal(0))
    stacks = _stacks(state, seats, builder.rows, folded, defaults)
    stacks[HERO] = stack
    my_bet = builder.bets.get(HERO, Decimal(0))
    top = builder.top
    pool = state.mushroom
    if pool is None and len(seats) >= plain_policy.MUSHROOM_PLAYERS and ring[1] == HERO:
        defaults.append("mushroom")
    if state.flop_pot is not None and street != "preflop":
        defaults.append("flop_pot")
    observation = {
        "observing_seat": HERO, "occupied_seats": seats, "dealer_seat": dealer,
        "straddler_seat": straddler,
        "bomb_pot": None if bomb is None else _money(bomb),
        "street": street, "own_hole": list(state.hero),
        "board": state._board_cards()[:BOARD_CARDS[street]],
        "folded": sorted(folded), "pot": _money(pot), "to_call": _money(to_call),
        "bets": {str(seat): _money(builder.bets.get(seat, Decimal(0)))
                 for seat in seats},
        "stacks": {str(seat): _money(chips) for seat, chips in stacks.items()},
        "contributions": {str(seat): _money(chips)
                          for seat, chips in contributions.items()},
        "betting": {"can_raise": stack > to_call,
                    "min_raise_to": _money(min(top + max(builder.increment, big_blind),
                                               my_bet + stack)),
                    "max_raise_to": _money(my_bet + stack)},
        "rules": _rules(stakes, len(seats)), "big_blind": _money(big_blind),
        "table_size": len(seats),
        "public_history": [{key: value for key, value in row.items() if key != "frame"}
                           for row in builder.rows],
        "mushroom_pool": None if pool is None else _money(pool),
        "flop_pot": None if state.flop_pot is None or street == "preflop"
        else _money(state.flop_pot),
        "inferred_actions": builder.inferred}
    return observation, sorted(set(defaults), key=list(DEFAULTS).index), missing


def _fit_price(builder, state, street, to_call, controls, dealer, seats, folded,
               straddle):
    """让这条街的注额和你的按钮对上（价格是承重的，读对 99%）：

    - 推出来的最高注比你的注额加要跟的金额少：有人加注没读到，补上；
    - 多：你在这条街先前动过（按钮出现又消失过），是你那一下没读到，补在后来的
      加注前面；不然是谁的注额读多了，按价格把最后那个加注改小。"""
    my_bet = builder.bets.get(HERO, Decimal(0))
    want = my_bet + to_call
    if builder.top + Decimal(EPSILON) < want:
        who = _raiser(builder, state, street, dealer, seats, folded, straddle)
        if who is not None:
            builder.put(None, who, want, inferred=True)
        return
    if builder.top <= want + Decimal(EPSILON) or controls.get("button") == "all_in":
        return
    if street in state.acted:
        _insert_mine(builder, street, builder.top - to_call)
        return
    last = next((row for row in reversed(builder.rows)
                 if row["street"] == street and row["kind"] == "raise_to"), None)
    if last is not None:
        was = Decimal(last["raise_to"])
        last["raise_to"], last["id"] = _money(want), "raise_to:" + _money(want)
        last["paid"] = _money(Decimal(last["paid"]) - (was - want))
        builder.bets[last["actor"]] = want
        builder.top = want
        builder.inferred += 1


def _insert_mine(builder, street, mine):
    """你这条街先前那一下（没读到）：放在别人最后一个加注前面。"""
    rows = builder.rows
    at = max((index for index, row in enumerate(rows)
              if row["street"] == street and row["actor"] != HERO
              and row["kind"] == "raise_to"), default=len(rows))
    before = Decimal(0) if street != "preflop" else builder.posts.get(HERO, Decimal(0))
    top = max([builder.posts.get(seat, Decimal(0)) for seat in builder.posts]
              if street == "preflop" else [Decimal(0)])
    for row in rows[:at]:
        if row["street"] != street:
            continue
        if row["kind"] == "raise_to":
            top = max(top, Decimal(row["raise_to"]))
        if row["actor"] == HERO:
            before += Decimal(row["paid"])
    if mine <= before:
        return
    if mine > top:
        kind = {"id": "raise_to:" + _money(mine), "kind": "raise_to",
                "raise_to": _money(mine)}
    else:
        kind = {"id": "check_call", "kind": "check_call", "raise_to": None}
    rows.insert(at, {"frame": None, "actor": HERO, "street": street, **kind,
                     "paid": _money(mine - before)})
    builder.bets[HERO] = max(builder.bets.get(HERO, Decimal(0)), mine)
    builder.inferred += 1


def _raiser(builder, state, street, dealer, seats, folded, straddle):
    """补上的加注是谁的：这条街读到注额最高的还在局对手；否则动作历史里这条街最后
    加注的；否则在你前面最近说话的还在局对手。"""
    live = [seat for seat in seats if seat not in folded and seat != HERO]
    if not live:
        return None
    read = {seat: builder.bets.get(seat, Decimal(0)) for seat in live}
    best = max(read.values())
    if best > 0:
        def last(seat):
            return max((at for at, row in enumerate(builder.rows)
                        if row["actor"] == seat), default=-1)
        return max((seat for seat in live if read[seat] == best), key=last)
    for action in reversed(state._history_actions()):
        item = dict(zip(COMPACT_FIELDS, action))
        if (item.get("street") == street and item.get("kind") in ("raise", "all_in")
                and item.get("slot") in live):
            return item["slot"]
    order = _order(seats, dealer, street, straddle)
    before = order[:order.index(HERO)] if HERO in order else order
    return next((seat for seat in reversed(before) if seat in live), live[0])


def _stacks(state, seats, rows, folded, defaults):
    """{座位: 现在剩的筹码}：全下的是 0；读到过的减掉读到以后他投入的（往前带）；
    还是没有的不放进来（不算他）。"""
    stacks = {}
    for seat in seats:
        if seat == HERO:
            continue
        if state.states.get(seat) == "all_in":
            stacks[seat] = Decimal(0)
            continue
        found = state.stacks.get(seat)
        if found is None:
            if seat not in folded:
                defaults.append("opponent_stack")
            continue
        value, frame = found
        since = sum(Decimal(row["paid"]) for row in rows
                    if row["actor"] == seat and row["frame"] is not None
                    and row["frame"] > frame)
        if since and seat not in folded:
            defaults.append("carried_stack")
        stacks[seat] = max(Decimal(0), value - since)
    return stacks


# -- 每帧的建议 ------------------------------------------------------------------

def advice_row(advice, observation):
    """一条 plain 建议的样子（和求解器的建议行一样，窗口和打分都认）。"""
    if advice.action not in ("bet", "raise") or advice.to is None:
        return {"action": advice.action, "frequency": 1.0}
    mine = Decimal(observation["bets"][str(observation["observing_seat"])])
    to = Decimal(str(advice.to)).quantize(Decimal(1))
    return {"action": advice.action, "frequency": 1.0, "chips": _money(to - mine),
            "to": _money(to)}


class AAPlainAdvice:
    """每帧的 plain 建议：一个按手锁存的状态，一个决策只算一次，在读帧的线程里算。"""

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self.reset()

    def reset(self):
        self.state, self._hand_id = None, None
        self._stakes = None             # 前面几手认下的级别
        self._last = None               # 上一手结束时的手牌和公共牌
        self._decisions = {}            # (街, 价格) -> 建议
        self._wait = None               # (街, 开始的帧, 开始的时间)
        self._shown = None              # (上一个决策的建议, 到什么时候)

    def __call__(self, payload, frame):
        from .aa_session import frame_summary
        return self.observe_fields(frame_summary(payload), frame)

    def stakes(self):
        if self.state is None:
            return settle_stakes(None, self._stakes)
        return self.state.stakes(self._stakes)

    def settled(self):
        """这手的 id 和它的决策：{(当时读到的动作数, 街, 价格): 建议}（打分用）。"""
        return self._hand_id, {
            (report["decision"], report["street"], report["price"]): report
            for report in self._decisions.values()}

    def observe_fields(self, fields, frame):
        history = fields.get("actions_v1")
        if not history:
            return self._report("idle", "no_hand")
        if history["hand_id"] != self._hand_id:
            self._new_hand(history["hand_id"])
        state = self.state
        state.observe(fields, frame)
        controls = fields.get("hero_controls") or {}
        if not controls.get("visible"):
            self._wait = None
            return self._report("idle", "not_your_turn")
        street = fields.get("street")
        if street not in STREETS:
            return self._report("idle", "street_not_covered", street=street)
        now = price(controls, state.stack_read(HERO))
        done = self._decisions.get((street, now))
        if done is not None:
            # 等待从价格第一次变成新的那一帧算起，不从一闪而过的误读算起。
            self._wait = None
            return self._with_previous(done)
        if self._wait is None or self._wait[0] != street:
            self._wait = (street, frame, self._clock())
        missing = self._not_ready(state, fields, street, now)
        _, first, since = self._wait
        waited = self._clock() - since
        late = frame - first >= READY_FRAMES or waited >= READY_SECONDS
        if missing and not late:
            return self._report("reading", missing[0], street=street, kind="plain",
                                waited=round(waited, 1), missing=missing,
                                missing_words=[MISSING[key] for key in missing])
        started = time.perf_counter()
        report = self._decide(state, fields, street, now, missing, waited, history)
        report["seconds"] = round(time.perf_counter() - started, 3)
        if now is not None:
            previous = [item for key, item in self._decisions.items()
                        if key[0] == street]
            self._decisions[(street, now)] = report
            if previous:
                self._shown = (previous[-1], self._clock() + SIDE_BY_SIDE, frame)
        self._wait = None
        return self._with_previous(report)

    def _new_hand(self, hand_id):
        if self.state is not None:
            stakes = self.state.stakes(self._stakes)
            if stakes["source"] == "table":
                self._stakes = stakes
            self._last = {"hero": self.state.hero,
                          "board": list(self.state.board)}
        self.state, self._hand_id = HandState(hand_id, self._last), hand_id
        self._decisions, self._wait, self._shown = {}, None, None

    def _not_ready(self, state, fields, street, now):
        """就绪条件（补充二第二节）没满足的：空的就是就绪了。"""
        missing = []
        if now is None:
            missing.append("price")
        elif len(state.prices) < PRICE_FRAMES or len(set(state.prices)) != 1:
            missing.append("price_not_steady")
        if state.card_conflict():
            missing.append("card_conflict")
        if state.hero is None:
            missing.append("hero_cards")
        need = BOARD_CARDS[street]
        board = [card for card in fields.get("board") or () if card]
        if len(state._board_cards()) < need or len(board) != need:
            missing.append("board")
        if state.live_frames < SEATS_FRAMES:
            missing.append("opponents")
        if state.pot is None and street != "preflop":   # 翻前底池按结构算
            missing.append("pot")
        if state.stack_read(HERO) is None:
            missing.append("stack")
        return missing

    def _decide(self, state, fields, street, now, missing, waited, history):
        stakes = self.stakes()
        observation, defaults = None, []
        if not missing:
            observation, defaults, missing = table_observation(state, fields, stakes)
        if observation is None:
            if street == "preflop" and blind_unraised(state, stakes, now):
                return self._blind(state, fields, street, now, missing, waited, history,
                                   stakes)
            return self._iron5(fields, street, now, missing, waited, history, stakes)
        try:
            advice = plain_policy.decide(observation)
        except Exception:                   # 拼出来的这手自相矛盾：不猜，铁律 5
            return self._iron5(fields, street, now, ["actions"], waited, history,
                               stakes)
        return self._ready(observation, advice, defaults, fields, street, now, waited,
                           history, stakes, tag=f"就绪 {waited:.1f}s")

    def _ready(self, observation, advice, defaults, fields, street, now, waited,
               history, stakes, tag, missing=()):
        controls = fields.get("hero_controls") or {}
        row = advice.row()
        row.update(tag=tag, waited=round(waited, 1),
                   defaults=[DEFAULTS[key] for key in defaults])
        if missing:
            row.update(unread=missing[0], missing=list(missing))
        table = plain_policy.Table(observation)
        facing = Decimal(observation["bets"][str(HERO)]) + now
        return self._report(
            "ready", None, street=street, kind="plain", plain=row,
            advice=[advice_row(advice, observation)], pot=observation["pot"],
            to_call=observation["to_call"], price=_money(now),
            decision=len(history.get("actions") or ()),
            mushroom_pool=(_money(table.mushroom * table.big_blind)
                           if table.mushroom else None),
            inferred_actions=observation["inferred_actions"],
            bomb_pot=observation["bomb_pot"], stakes_used=stakes_report(stakes),
            button=controls.get("button"), facing=_money(facing) if now else None)

    def _blind(self, state, fields, street, now, missing, waited, history, stakes):
        """翻前轮到盲位、没人加注，画面 2 秒没读稳：铁律 5 不适用（v3.2）。读到了牌就照表
        （没稳的按读到的算），牌没读到或读出过两种就过牌或补齐。"""
        words = "、".join(MISSING[key] for key in missing)
        if state.hero is not None and not state.card_conflict():
            observation, defaults, _ = table_observation(state, fields, stakes)
            advice = None
            if observation is not None:
                try:
                    advice = plain_policy.decide(observation)
                except Exception:
                    advice = None
            if advice is not None and advice.rule in BLIND_RULES:
                return self._ready(observation, advice, defaults, fields, street, now,
                                   waited, history, stakes, tag=f"盲位按表：缺{words}",
                                   missing=missing)
        controls = fields.get("hero_controls") or {}
        action = "check" if now == 0 else "call"
        advice = plain_policy.unread(action, f"画面没读稳：缺{words}", rule="I5.blind")
        row = {**advice.row(), "unread": missing[0], "missing": list(missing),
               "tag": f"盲位没人加注：{'过牌' if action == 'check' else '补齐'}"
                      f"（缺{MISSING[missing[0]]}）",
               "defaults": [], "waited": round(waited, 1)}
        return self._report(
            "ready", None, street=street, kind="plain", plain=row,
            advice=[{"action": action, "frequency": 1.0}], to_call=_money(now),
            price=_money(now), decision=len(history.get("actions") or ()),
            stakes_used=stakes_report(stakes), button=controls.get("button"))

    def _iron5(self, fields, street, now, missing, waited, history, stakes):
        """缺了没法算：铁律 5（弃，能过牌就过牌），写明缺什么。"""
        controls = fields.get("hero_controls") or {}
        action = "check" if controls.get("button") == "check" else "fold"
        words = "、".join(MISSING[key] for key in missing)
        advice = plain_policy.unread(action, f"画面没读稳：缺{words}")
        row = {**advice.row(), "unread": missing[0], "missing": list(missing),
               "tag": f"铁律 5：缺{MISSING[missing[0]]}", "defaults": [],
               "waited": round(waited, 1)}
        return self._report(
            "ready", None, street=street, kind="plain", plain=row,
            advice=[{"action": action, "frequency": 1.0}],
            to_call=("0" if action == "check"
                     else None if now is None else _money(now)),
            price=None if now is None else _money(now),
            decision=len(history.get("actions") or ()),
            stakes_used=stakes_report(stakes), button=controls.get("button"))

    def _with_previous(self, report):
        """价格变了以后 2 秒内，把上一个决策的建议也带上（窗口并排显示）。"""
        if self._shown is None:
            return report
        previous, until, _ = self._shown
        if self._clock() >= until or previous is report:
            self._shown = None if self._clock() >= until else self._shown
            return report
        return {**report, "previous": {
            "advice": previous.get("advice"), "to_call": previous.get("to_call"),
            "price": previous.get("price"),
            "rule": (previous.get("plain") or {}).get("rule")}}

    def _report(self, status, reason, **extra):
        return {"schema_version": 1, "status": status, "reason": reason,
                "hand_id": self._hand_id, "basis": BASIS, **extra,
                "stakes": stakes_report(self.stakes()),
                "advice_emitted": status == "ready", "acts_on_client": False}


__all__ = ["AAPlainAdvice", "BASIS", "BLIND_RULES", "DEFAULTS", "HandState",
           "MISSING", "advice_row", "blind_unraised", "posted_dealer", "price",
           "table_observation"]
