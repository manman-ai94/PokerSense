"""Six fixed legal trajectories preserve a known native V2 recall limitation.

KsJs and KsTs have distinct observed preflop classes, then collide on the
rainbow flop and fixed turn below. The fixed river separates them again. These
passing regressions describe lost private-class recall, not strategy/EV harm.
Only one suit permutation and one alternate hidden completion are exercised;
the earlier diagnostic's 96-trajectory experiment is not rerun or imported.
"""

from collections import Counter
from copy import deepcopy

import pytest

pytest.importorskip("pokerkit")

from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena  # noqa: E402
from poker_engine.strategy.aa_policy_encoding_v2 import encode_decision_v2  # noqa: E402
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2  # noqa: E402


_SUITS = "cdhs"
_CARDS = tuple(rank + suit for rank in "23456789TJQKA" for suit in _SUITS)
_HEROES = {"KJs": ("Ks", "Js"), "KTs": ("Ks", "Ts")}
_BOARD = ("2c", "4d", "8h", "5c", "Th")
_STREETS = ("preflop", "flop", "turn", "river")
_SNAPSHOT_STEPS = dict(zip(_STREETS, (4, 6, 12, 18)))
_CURSORS = dict(zip(_STREETS, (12, 16, 18, 20)))
_ACTORS = (2, 3, 4, 5, 0, 1, *range(6), *range(6), 0)
_COMPLETIONS = {
    "original": (("Ac", "Ad"), ("Qc", "Qd"), ("9c", "9d"),
                 ("7c", "7d"), ("6c", "6d")),
    "hidden": (("Ah", "As"), ("Qh", "Qs"), ("9h", "9s"),
               ("7h", "7s"), ("6h", "6s")),
}
_SUIT_MAP = dict(zip(_SUITS, "dhsc"))
_FROZEN_COST = Counter({
    "rules_build": 1, "arena_init": 6, "arena_reset": 6,
    "arena_observe": 114, "arena_legal": 114, "arena_step": 108,
    "engine_deal_inspect": 24, "encoder": 24,
})


def _call(counter, label, function, *args, **kwargs):
    # Count these explicit fixture boundary calls, including failed attempts.
    counter[label] += 1
    return function(*args, **kwargs)


def _mapped(card, suit_map):
    return card[0] + suit_map[card[1]]


def _deck(hero, completion, suit_map):
    prefix = [*hero, *(card for hole in _COMPLETIONS[completion] for card in hole),
              "3h", *_BOARD[:3], "3c", _BOARD[3], "3d", _BOARD[4]]
    assert len(prefix) == len(set(prefix)) == 20
    remainder = [card for card in _CARDS if card not in prefix]
    if completion == "hidden":
        remainder.reverse()
    deck = [_mapped(card, suit_map) for card in prefix + remainder]
    assert len(deck) == len(set(deck)) == 52
    assert set(deck) == set(_CARDS)
    return deck


def _expected_history(count):
    history = []
    for index, actor in enumerate(_ACTORS[:count]):
        street = "preflop" if index < 6 else "flop" if index < 12 else "turn"
        paid = "1" if actor == 0 else "0" if actor == 1 else "2"
        history.append({
            "index": index, "actor": actor, "street": street,
            "id": "check_call", "kind": "check_call", "raise_to": None,
            "paid": paid if index < 6 else "0",
        })
    return history


def _engine_deal(arena):
    # Inspect PokerKit's actual deal independently of arena.observe/_holes.
    return {
        "holes": [[repr(card) for card in hole]
                  for hole in arena._state.hole_cards],
        "board": [repr(card) for row in arena._state.board_cards for card in row],
        "cursor": arena._deck_cursor,
        "remaining": [repr(card) for card in arena._deck[arena._deck_cursor:]],
        "check_call_legal": arena._state.can_check_or_call(),
    }


def _trajectory(rules, hero, completion, suit_map, counter):
    deck = _deck(hero, completion, suit_map)
    arena = _call(counter, "arena_init", AAFullHandArena, rules,
                  occupied_seats=range(6), dealer_seat=5)
    _call(counter, "arena_reset", arena.reset, 0, deck=deck)
    assert tuple(arena._seats) == tuple(range(6))
    views = {}
    for index, actor in enumerate(_ACTORS):
        street = ("preflop" if index < 6 else "flop" if index < 12
                  else "turn" if index < 18 else "river")
        assert not arena.terminal
        assert (arena.street, arena.actor) == (street, actor)
        observation = _call(counter, "arena_observe", arena.observe, actor)
        menu = [action.to_dict() for action in
                _call(counter, "arena_legal", arena.legal_actions)]
        assert observation["public_history"] == _expected_history(index)
        assert observation["legal_actions"] == menu
        assert "check_call" in {action["id"] for action in menu}
        if index == _SNAPSHOT_STEPS[street]:
            assert observation["actor"] == observation["observing_seat"] == 0
            board = [] if street == "preflop" else deck[13:16]
            board_history = [] if not board else [{"street": "flop", "cards": board}]
            if street in ("turn", "river"):
                board = board + deck[17:18]
                board_history.append({"street": "turn", "cards": deck[17:18]})
            if street == "river":
                board = board + deck[19:20]
                board_history.append({"street": "river", "cards": deck[19:20]})
            assert observation["own_hole"] == deck[:2]
            assert observation["board"] == board
            assert observation["board_history"] == board_history
            deal = _call(counter, "engine_deal_inspect", _engine_deal, arena)
            assert deal["holes"] == [deck[i:i + 2] for i in range(0, 12, 2)]
            assert deal["holes"][0] == observation["own_hole"]
            assert deal["board"] == observation["board"]
            assert deal["cursor"] == _CURSORS[street]
            assert deal["remaining"] == deck[_CURSORS[street]:]
            assert deal["check_call_legal"]
            views[street] = {
                "observation": observation, "deal": deal,
                "encoded": _call(counter, "encoder", encode_decision_v2, observation),
            }
        if index == 18:
            break
        # Production step verifies checking/calling through PokerKit before mutation.
        _call(counter, "arena_step", arena.step, "check_call")
    assert tuple(views) == _STREETS
    return views


@pytest.fixture(scope="module")
def recall_corpus():
    counter = Counter()
    rules = _call(counter, "rules_build", AARuleProfileV2.from_dict, {
        "schema_version": 2, "table_size": 6, "small_blind": "1", "big_blind": "2",
        "ante": "0", "ante_mode": "none", "straddle_mode": "none",
        "straddle_amount": "0", "rake_percent": "0", "rake_cap_bb": "0",
        "rake_application": "all_pots", "rake_rounding": "exact",
        "rake_distribution": "proportional_all_pots", "minimum_chip": "1",
        "verification_status": "simulation", "source": "synthetic-recall-regression",
    })
    identity = dict(zip(_SUITS, _SUITS))
    variants = (("original", "original", identity),
                ("suit", "original", _SUIT_MAP), ("hidden", "hidden", identity))
    corpus = {
        (variant, name): _trajectory(rules, hero, completion, suit_map, counter)
        for variant, completion, suit_map in variants
        for name, hero in _HEROES.items()
    }
    assert len(corpus) == 6
    assert counter == _FROZEN_COST
    return corpus, counter


def _public(observation):
    return {key: value for key, value in observation.items() if key != "own_hole"}


def _record_cost_once(counter, record_property):
    cost = 0 if getattr(counter, "_cost_recorded", False) else sum(counter.values())
    record_property("synthetic_nodes", cost)
    counter._cost_recorded = True  # Metadata, outside the counted operation keys.


def test_known_native_recall_limit_collides_on_flop_and_turn(
        recall_corpus, record_property):
    corpus, counter = recall_corpus
    _record_cost_once(counter, record_property)
    record_property("synthetic_trajectories", len(corpus))
    record_property("synthetic_steps", counter["arena_step"])
    record_property("synthetic_encodes", counter["encoder"])
    record_property("known_limitation", "native_v2_loses_preflop_private_class_recall")
    for variant in ("original", "suit", "hidden"):
        left, right = corpus[(variant, "KJs")], corpus[(variant, "KTs")]
        assert [views["preflop"]["encoded"]["features"]["cards"]["preflop_class"]
                for views in (left, right)] == ["KJsuited", "KTsuited"]
        for street in _STREETS:
            a, b = left[street], right[street]
            assert _public(a["observation"]) == _public(b["observation"])
            assert a["encoded"]["exact_key"] != b["encoded"]["exact_key"]
            # Passing known-limit assertions: no xfail or strategic-equivalence claim.
            collision = street in ("flop", "turn")
            assert (a["encoded"]["abstract_key"]
                    == b["encoded"]["abstract_key"]) is collision
            assert (a["encoded"]["features"] == b["encoded"]["features"]) is collision
            assert "lossy" in a["encoded"]["abstraction_disclosure"]
            assert "not proven strategic equivalence" in (
                a["encoded"]["abstraction_disclosure"])
        # Th restores a concrete distinction: only KT now pairs the public ten.
        assert left["river"]["encoded"]["features"]["cards"]["made_category"] == 0
        assert right["river"]["encoded"]["features"]["cards"]["made_category"] == 1


def test_one_global_suit_permutation_preserves_complete_encoding(
        recall_corpus, record_property):
    corpus, counter = recall_corpus
    _record_cost_once(counter, record_property)
    for hero in _HEROES:
        for street in _STREETS:
            original = corpus[("original", hero)][street]
            mapped = corpus[("suit", hero)][street]
            observation = deepcopy(original["observation"])
            for field in ("own_hole", "board"):
                observation[field] = [_mapped(card, _SUIT_MAP)
                                      for card in observation[field]]
            for row in observation["board_history"]:
                row["cards"] = [_mapped(card, _SUIT_MAP) for card in row["cards"]]
            assert observation == mapped["observation"]
            assert original["encoded"] == mapped["encoded"]
            assert mapped["deal"]["holes"] == [
                [_mapped(card, _SUIT_MAP) for card in hole]
                for hole in original["deal"]["holes"]]
            assert mapped["deal"]["remaining"] == [
                _mapped(card, _SUIT_MAP) for card in original["deal"]["remaining"]]


def test_different_actual_hidden_completion_does_not_leak(
        recall_corpus, record_property):
    corpus, counter = recall_corpus
    _record_cost_once(counter, record_property)
    for hero in _HEROES:
        for street in _STREETS:
            original = corpus[("original", hero)][street]
            hidden = corpus[("hidden", hero)][street]
            assert original["deal"]["holes"][1:] != hidden["deal"]["holes"][1:]
            assert original["deal"]["remaining"] != hidden["deal"]["remaining"]
            assert original["observation"] == hidden["observation"]
            assert original["encoded"] == hidden["encoded"]
