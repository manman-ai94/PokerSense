"""Whether the range read for an opponent still held the hand he showed."""

import json
from pathlib import Path

import pytest

from poker_engine.scoreboard import ranges
from poker_engine.scoreboard.bots import _rng, make_policy
from poker_engine.scoreboard.exclusion import (compare, exclusion_trace, measured_seats,
                                               outcome, reading_model, showdown_traces,
                                               summarize)
from poker_engine.scoreboard.opponents import NoisyBot
from poker_engine.scoreboard.population import PopulationBot
from poker_engine.scoreboard.replay import with_hole
from poker_engine.scoreboard.runner import POOLS, run_scoreboard
from poker_engine.scoreboard.solver_bot import MODEL_SALT
from poker_engine.solver.texassolver import combo_key
from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2

RULES = Path(__file__).resolve().parents[2] / "configs/game/aa-scoreboard-rules-v2.json"


def rules():
    return AARuleProfileV2.from_dict(json.loads(RULES.read_text(encoding="utf-8")))


def first_raise(observation):
    return next(action["id"] for action in observation["legal_actions"]
                if action["kind"] == "raise_to")


def aces(board):
    """Two aces the board leaves, in the order the reading names them."""
    left = [card for card in ("Ah", "As", "Ad", "Ac") if card not in board][:2]
    return [combo_key(left)[:2], combo_key(left)[2:]]


def play(seed, villain_acts, hero_acts=lambda observation: "check_call"):
    """A hand where the first seat to act opens, the next one is the villain
    and everyone else folds before the flop; returns (arena, hero, villain)."""
    arena = AAFullHandArena(rules()).reset(seed)
    hero = arena.actor
    arena.step(first_raise(arena.observe(hero)))
    villain = arena.actor
    while not arena.terminal:
        seat = arena.actor
        observation = arena.observe(seat)
        if seat == villain:
            arena.step(villain_acts(observation))
        elif seat == hero:
            arena.step(hero_acts(observation))
        else:
            arena.step("fold")
    return arena, hero, villain


def test_aces_that_call_first_and_raise_later_are_thrown_out_at_the_call():
    def villain(observation):
        # Flat the open; after the flop raise the first bet, else check.
        if observation["street"] == "flop" and float(observation["to_call"] or 0):
            return first_raise(observation)
        return "check_call"

    def hero(observation):
        if observation["street"] == "flop" and not float(observation["to_call"] or 0):
            return first_raise(observation)
        return "check_call"

    arena, hero_seat, seat = play(3, villain, hero)
    observation = arena.observe(hero_seat)
    assert observation["terminal"] and seat not in observation["folded"]
    cards = aces(observation["board"])
    trace = exclusion_trace(observation, seat, cards, PopulationBot(adjusted=True))
    words = [(step["street"], step["action"]) for step in trace["steps"]]
    assert words[0] == ("preflop", "call")
    assert ("flop", "raise") in words
    # The model 3-bets aces: the flat call throws them out, for good.
    assert [step["excluded"] for step in trace["steps"]] == [True] * len(words)
    assert trace["steps"][0]["weight"] == 0 and trace["steps"][0]["hands"] > 0
    excluded, narrowed, first = outcome(trace)
    assert excluded and narrowed and (first["street"], first["action"]) == (
        "preflop", "call")
    summary = summarize([trace])
    assert summary["all"] == {"hands": 1, "excluded": 1, "rate": 1.0,
                              "ci95": summary["all"]["ci95"]}
    assert summary["river"]["hands"] == 1 and summary["narrowed"]["excluded"] == 1
    assert {street: part["rate"] for street, part in summary["by_street"].items()} == {
        "preflop": 1.0, "flop": 1.0, "turn": 1.0, "river": 1.0}
    assert summary["first"] == {"preflop call": 1}


def test_a_hand_played_as_the_model_plays_it_stays_in():
    model = PopulationBot(adjusted=True)
    # The deal's board, so that the villain's aces are not on it.
    probe = AAFullHandArena(rules()).reset(3)
    while not probe.terminal:
        probe.step("check_call")
    board = probe.observe(0)["board"]
    held = aces(board)

    def villain(observation):
        mine = with_hole(observation, held)
        return model.decide(mine, _rng(MODEL_SALT, mine))

    arena, hero, seat = play(3, villain)
    observation = arena.observe(hero)
    assert observation["board"] == board and seat not in observation["folded"]
    trace = exclusion_trace(observation, seat, held, model)
    assert trace["steps"] and trace["steps"][0]["action"] == "raise"     # a 3-bet
    assert all(step["weight"] == 1.0 and not step["excluded"]
               for step in trace["steps"])
    assert summarize([trace])["all"]["excluded"] == 0


def test_measuring_leaves_the_shared_reading_cache_as_it_was():
    arena, hero, seat = play(3, lambda observation: "check_call")
    observation = arena.observe(hero)
    model = PopulationBot(adjusted=True)
    before = dict(ranges._KEPT)
    trace = exclusion_trace(observation, seat, aces(observation["board"]), model)
    assert ranges._KEPT == before
    # The same reading as the advice's, action by action.
    final = ranges.opponent_ranges(observation, model, cache={})[seat]
    key = combo_key(aces(observation["board"]))
    expected = round(final.get(key, 0.0) / max(final.values()), 6)
    assert trace["steps"][-1]["weight"] == expected


def test_the_observer_and_folded_seats_and_impossible_cards_are_refused():
    arena, hero, seat = play(3, lambda observation: "check_call")
    observation = arena.observe(hero)
    model = PopulationBot(adjusted=True)
    with pytest.raises(ValueError):
        exclusion_trace(observation, hero, ["Ah", "As"], model)
    folded = observation["folded"][0]
    with pytest.raises(ValueError):
        exclusion_trace(observation, folded, ["Ah", "As"], model)
    with pytest.raises(ValueError):
        exclusion_trace(observation, seat, [observation["board"][0], "2c"], model)


def step(street, action, excluded, ends=False, hands=100):
    return {"index": 0, "street": street, "action": action, "weight": 0.0 if excluded
            else 1.0, "hands": hands, "excluded": excluded, "ends_hand": ends}


def trace(street, steps, you_in=True):
    return {"seat": 1, "cards": ["Ah", "As"], "street": street, "combos": 1081,
            "you_in": you_in, "steps": steps}


def test_rates_by_kind_of_hand_by_street_and_before_the_end():
    traces = [
        trace("river", [step("preflop", "raise", False), step("flop", "call", False),
                        step("river", "call", True, ends=True)]),
        trace("turn", [step("preflop", "call", False), step("turn", "check", True)],
              you_in=False),
        trace("flop", [step("preflop", "raise", False, hands=1081)]),   # never cut
    ]
    whole = summarize(traces)
    assert (whole["all"]["excluded"], whole["all"]["hands"]) == (2, 3)
    assert (whole["narrowed"]["excluded"], whole["narrowed"]["hands"]) == (2, 2)
    assert (whole["river"]["excluded"], whole["river"]["hands"]) == (1, 1)
    assert (whole["you_in"]["excluded"], whole["you_in"]["hands"]) == (1, 2)
    by_street = {street: (part["excluded"], part["hands"])
                 for street, part in whole["by_street"].items()}
    assert by_street == {"preflop": (0, 3), "flop": (0, 3), "turn": (1, 2),
                         "river": (1, 1)}
    assert whole["first"] == {"river call": 1, "turn check": 1}
    # The last call at the showdown left out: the first hand stays in.
    end = summarize(traces, before_end=True)
    assert (end["all"]["excluded"], end["river"]["excluded"]) == (1, 0)
    assert end["first"] == {"turn check": 1}


def test_two_readings_of_the_same_hands_are_compared_hand_by_hand():
    out = trace("flop", [step("flop", "call", True)])
    kept = trace("flop", [step("flop", "call", False)])
    result = compare([out, out, kept], [kept, out, kept])
    assert (result["kept_now"], result["excluded_now"]) == (1, 0)
    assert (result["before"]["all"]["rate"], result["after"]["all"]["rate"]) == (
        0.667, 0.333)
    assert result["change"]["all"] == -0.334
    with pytest.raises(ValueError):
        compare([out], [])


def test_each_deal_measures_its_own_seats():
    seats = tuple(range(8))
    assert measured_seats(3, seats, 1) == {3}
    assert measured_seats(7, seats, 2) == {7, 0}
    assert measured_seats(5, seats, 20) == set(seats)


def test_a_strategy_reads_with_its_own_model_and_reads():
    model, sees = reading_model(make_policy("range_multiway@hu=1+aa_preflop"))
    assert model.adjusted and sees
    model, sees = reading_model(make_policy("noreads+range_multiway+aa_preflop"))
    assert model.adjusted and not sees
    model, sees = reading_model(make_policy("rfi_table"))
    assert not model.adjusted and sees


def test_every_opponent_still_in_at_the_end_is_measured():
    arena, hero, seat = play(3, lambda observation: "check_call")
    traces = showdown_traces(arena, hero, PopulationBot(adjusted=True))
    assert [found["seat"] for found in traces] == [seat]
    assert traces[0]["cards"] == arena.observe(seat)["own_hole"]
    # Everyone folded to one seat: nobody showed.
    arena = AAFullHandArena(rules()).reset(4)
    while not arena.terminal:
        arena.step("fold")
    assert showdown_traces(arena, 0, PopulationBot()) == []


def postflop(arena_seed=3):
    """A flop observation of the seat to act, with and without a bet to call."""
    arena = AAFullHandArena(rules()).reset(arena_seed)
    while arena.street == "preflop":
        arena.step("check_call")
    checked_to = arena.observe(arena.actor)
    arena.step(first_raise(checked_to))
    return checked_to, arena.observe(arena.actor)


class Fixed:
    def __init__(self, action):
        self.action = action

    def for_game(self, salt):
        return lambda observation: self.action(observation)

    def decide(self, observation, rng):
        return self.action(observation)


def test_noisy_players_slow_play_stab_and_call_instead_of_folding():
    checked_to, facing = postflop()
    bet = Fixed(first_raise)
    assert NoisyBot(bet, slow=1).for_game("s")(checked_to) == "check_call"
    assert NoisyBot(bet, slow=0).for_game("s")(checked_to) == first_raise(checked_to)
    fold = Fixed(lambda observation: "fold")
    assert NoisyBot(fold, sticky=1).for_game("s")(facing) == "check_call"
    assert NoisyBot(fold, sticky=0).for_game("s")(facing) == "fold"
    check = Fixed(lambda observation: "check_call")
    assert NoisyBot(check, stab=1).for_game("s")(checked_to).startswith("raise_to:")
    assert NoisyBot(check, stab=1).for_game("s")(facing) == "check_call"
    # Before the flop it plays exactly as its base.
    arena = AAFullHandArena(rules()).reset(3)
    preflop = arena.observe(arena.actor)
    assert NoisyBot(fold, slow=1, sticky=1, stab=1).for_game("s")(preflop) == "fold"


def test_noisy_players_by_name_and_without_noise_play_as_their_base():
    bot = make_policy("noisy@slow=0.5:sticky=0:stab=0.2+aa_real")
    assert (bot.slow, bot.sticky, bot.stab, bot.base.name) == (0.5, 0.0, 0.2, "aa_real")
    default = make_policy("noisy+aa_real")
    assert (default.slow, default.stab, default.sticky) == (0.35, 0.10, 0.25)
    with pytest.raises(ValueError):
        make_policy("noisy@slowly=1+aa_real")
    quiet = make_policy("noisy@slow=0:stab=0:sticky=0+aa_real").for_game("g")
    base = make_policy("aa_real").for_game("g")
    arena = AAFullHandArena(rules())
    for seed in range(3):
        arena.reset(seed)
        while not arena.terminal:
            observation = arena.observe(arena.actor)
            action = base(observation)
            assert quiet(observation) == action
            arena.step(action)


def test_the_existing_pools_are_unchanged_and_noisy_is_added():
    assert POOLS["noisy"] == ("noisy+aa_real",)
    assert {name: pool for name, pool in POOLS.items()
            if name not in ("noisy", "aa_cal")} == {
        "population": ("population",), "aa": ("aa_population",),
        "aa_real": ("aa_real",), "styles": ("tag", "lag", "rock", "station"),
        "reg": ("reg",), "maniac": ("maniac",), "nit": ("nit",),
        "tough": ("reg", "maniac", "nit", "aa_population"),
        "mirror": ("range_multiway+aa_preflop",), "solver": ("solver_turn+reg",)}


def test_measuring_on_the_scoreboard_does_not_change_its_results():
    from poker_engine.scoreboard.mushroom import Mushroom
    kwargs = {"deals": 3, "base_seed": 2, "pool": POOLS["noisy"], "reads": 100,
              "mushroom": Mushroom(3), "workers": 1}
    names = ["range_multiway@hu=1+aa_preflop", "aa_preflop"]
    plain = run_scoreboard(rules(), names, **kwargs)
    measured = run_scoreboard(rules(), names, exclusion=2, **kwargs)
    for key in ("strategies", "per_deal", "versus_reference", "pairwise",
                "decision_counts"):
        if key == "strategies":
            for name in names:
                found = dict(measured[key][name])
                report = found.pop("range_exclusion")
                assert found == plain[key][name]
                assert report["whole_hand"]["all"]["hands"] == len(report["hands"])
        else:
            assert measured[key] == plain[key]
    assert "exclusion" not in plain and measured["exclusion"]["seats_per_deal"] == 2
    hands = measured["strategies"][names[0]]["range_exclusion"]["hands"]
    assert hands and {item["hero"] for item in hands} <= set(range(8))
