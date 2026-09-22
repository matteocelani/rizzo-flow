"""Known-spot checks for the deterministic strategy layer. No model weights."""

import json
from pathlib import Path

import pytest

from jevbet.browser.casino import MockCasinoTable
from jevbet.cards import Card, ItalianCard
from jevbet.cli import main
from jevbet.games.holdem import filtered_raise_sizes
from jevbet.games.registry import build_request, load_game_state
from jevbet.play import run_play_loop
from jevbet.policy import RiskPolicy
from jevbet.strategy import hand_facts, recommend, recommend_blackjack, should_use_model
from jevbet.strategy.poker import pot_odds
from jevbet.strategy.select import compose_response
from rizzo_flow.schema import Request

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "games"


def _bj(player, dealer, legal, *, rules=None, bankroll=None, is_soft=False, bet=10):
    payload = {
        "game": "blackjack",
        "dealer_upcard": Card.parse(dealer).model_dump(),
        "hands": [
            {
                "cards": [Card.parse(card).model_dump() for card in player],
                "bet": bet,
                "is_soft": is_soft,
            }
        ],
        "legal_actions": legal,
        "bankroll": bankroll or {"cash": 400, "session_profit": 0},
        "rules": {"decks": 6, "dealer_hits_soft_17": True, "das": True, **(rules or {})},
    }
    return load_game_state(payload)


def _advice_bj(*args, policy=None, **kwargs):
    return recommend_blackjack(_bj(*args, **kwargs), policy)


def test_hand_value_recomputes_soft_and_pairs():
    soft = hand_facts([Card.parse("AS"), Card.parse("7D")], caller_soft=False)
    assert soft.total == 18 and soft.soft and soft.soft_disagrees
    hard = hand_facts([Card.parse("TH"), Card.parse("6D")], caller_soft=True)
    assert hard.total == 16 and not hard.soft and hard.soft_disagrees
    assert hand_facts([Card.parse("AS"), Card.parse("AD")]).pair == "A"
    assert hand_facts([Card.parse("KH"), Card.parse("QD")]).pair == "10"
    tens = hand_facts([Card.parse("AS"), Card.parse("AD"), Card.parse("9C")])
    assert tens.total == 21 and tens.soft and tens.pair is None


def test_italian_rank_aliases_and_scopa_pips():
    assert ItalianCard.parse("8-denari").rank == "Fante"
    assert ItalianCard.parse("8-denari").scopa_pips() == 8
    assert ItalianCard.parse("10-coppe").rank == "Re"
    assert ItalianCard.parse("10-coppe").scopa_pips() == 10
    assert ItalianCard.parse("7-denari").scopa_pips() == 7


def test_hard_16_vs_10_hits():
    advice = _advice_bj(["10H", "6D"], "KS", ["hit", "stand", "double"])
    assert advice.action == "hit"
    assert advice.confident
    assert "stand" not in {advice.action}


def test_hard_16_vs_10_surrenders_when_legal_else_hits():
    surrendered = _advice_bj(["10H", "6D"], "KS", ["hit", "stand", "surrender"])
    assert surrendered.action == "surrender"
    assert any(action == "hit" for action, _why in surrendered.alternatives)


def test_hard_12_vs_4_stands_and_12_vs_2_hits():
    assert _advice_bj(["10H", "2D"], "4S", ["hit", "stand"]).action == "stand"
    assert _advice_bj(["10H", "2D"], "2C", ["hit", "stand"]).action == "hit"


def test_soft_18_vs_9_hits_on_h17_chart():
    """BJA H17 (2024): A,7 vs 9 is a hit, including when the caller marked the hand hard."""
    advice = _advice_bj(["AS", "7D"], "9H", ["hit", "stand", "double"], is_soft=False)
    assert advice.action == "hit"
    assert "recomputed is_soft=True" in advice.reason
    # A hard 18 vs 9 would stand. The cards are soft, so the caller flag must not win.
    lied = _advice_bj(["10S", "8D"], "9H", ["hit", "stand"], is_soft=True)
    assert lied.action == "stand"
    assert "recomputed is_soft=False" in lied.reason


def test_soft_19_vs_6_doubles_vs_7_stands_on_h17_chart():
    """H17 soft 19 column: double vs 6 (Ds), stand vs 7. Typo was U on the 7 column."""
    vs6 = _advice_bj(["AS", "8D"], "6C", ["hit", "stand", "double"])
    assert vs6.action == "double"
    no_double = _advice_bj(["AS", "8D"], "6C", ["hit", "stand"])
    assert no_double.action == "stand"
    assert _advice_bj(["AS", "8D"], "7H", ["hit", "stand", "double"]).action == "stand"
    s17 = _advice_bj(
        ["AS", "8D"],
        "6C",
        ["hit", "stand", "double"],
        rules={"dealer_hits_soft_17": False},
    )
    assert s17.action == "stand"
    assert "S17" in s17.reason


def test_eleven_vs_6_doubles_else_hits():
    assert _advice_bj(["5H", "6D"], "6C", ["hit", "stand", "double"]).action == "double"
    fallback = _advice_bj(["5H", "6D"], "6C", ["hit", "stand"])
    assert fallback.action == "hit"


def test_split_eights_vs_10_and_aces_vs_6():
    eights = _advice_bj(["8H", "8D"], "KS", ["hit", "stand", "split"])
    assert eights.action == "split"
    no_split = _advice_bj(["8H", "8D"], "KS", ["hit", "stand"])
    assert no_split.action == "hit"
    assert _advice_bj(["AS", "AD"], "6C", ["hit", "stand", "split"]).action == "split"
    assert _advice_bj(["AS", "AD"], "6C", ["hit", "stand"]).action == "hit"


def test_stop_loss_does_not_recommend_a_costly_action():
    advice = _advice_bj(
        ["10H", "6D"],
        "KS",
        ["hit", "stand", "double", "split"],
        bankroll={"cash": 200, "session_profit": -80, "stop_loss": 50},
        policy=RiskPolicy(),
    )
    assert advice.action == "stand"
    assert advice.action not in {"hit", "double", "split"}
    assert advice.confident


def test_empty_post_policy_set_fail_closes_to_pass_not_a_costly_action():
    """H-L8: when stop-loss empties the free set, never resurrect legal_actions[0]."""
    from jevbet.choices import HOLD_POLICY
    from jevbet.games.registry import build_request

    costly_only = {
        "game": "blackjack",
        "dealer_upcard": Card.parse("KS").model_dump(),
        "hands": [
            {
                "cards": [Card.parse("10H").model_dump(), Card.parse("6D").model_dump()],
                "bet": 10,
                "is_soft": False,
            }
        ],
        "legal_actions": ["hit", "double", "split"],
        "bankroll": {"cash": 200, "session_profit": -80, "stop_loss": 50},
        "rules": {"decks": 6, "dealer_hits_soft_17": True, "das": True},
    }
    policy = RiskPolicy()
    request = build_request(costly_only, policy=policy)
    ids = [option.id for option in request.questions["action"].options]
    assert ids == ["pass", HOLD_POLICY]
    assert "hit" not in ids and "double" not in ids and "split" not in ids
    advice = recommend(load_game_state(costly_only), policy)
    assert advice.action == "pass"
    assert advice.action not in {"hit", "double", "split", "surrender"}
    assert advice.confident

    # Surrender is costly under stop-loss (M1); alone it still fails closed to pass.
    surrender_only = dict(costly_only)
    surrender_only["legal_actions"] = ["surrender", "hit"]
    request = build_request(surrender_only, policy=policy)
    assert [option.id for option in request.questions["action"].options] == [
        "pass",
        HOLD_POLICY,
    ]
    assert recommend(load_game_state(surrender_only), policy).action == "pass"

    holdem = {
        "game": "holdem",
        "street": "preflop",
        "hole_cards": [Card.parse("AH").model_dump(), Card.parse("KH").model_dump()],
        "community": [],
        "pot": 60,
        "to_call": 40,
        "stack": 400,
        "position": "BTN",
        "num_players": 6,
        "legal_actions": ["call", "raise"],
        "min_raise": 40,
        "raise_suggestions": [40, 80],
        "bankroll": {"cash": 400, "session_profit": -80, "stop_loss": 50},
    }
    request = build_request(holdem, policy=policy)
    ids = [option.id for option in request.questions["action"].options]
    assert ids == ["pass", HOLD_POLICY]
    assert "raise_amount" not in request.questions
    advice = recommend(load_game_state(holdem), policy)
    assert advice.action == "pass"
    assert advice.action not in {"call", "raise"}


def test_h17_s17_and_das_deviations():
    # H17 doubles 11 vs ace; S17 hits. Soft 18 vs 2 doubles on H17 and stands on S17.
    assert _advice_bj(["9H", "2D"], "AS", ["hit", "stand", "double"]).action == "double"
    s17 = _advice_bj(
        ["9H", "2D"],
        "AS",
        ["hit", "stand", "double"],
        rules={"dealer_hits_soft_17": False},
    )
    assert s17.action == "hit"
    assert "S17" in s17.reason
    assert _advice_bj(["AS", "7D"], "2C", ["hit", "stand", "double"]).action == "double"
    assert (
        _advice_bj(
            ["AS", "7D"],
            "2C",
            ["hit", "stand", "double"],
            rules={"dealer_stands_soft_17": True, "dealer_hits_soft_17": False},
        ).action
        == "stand"
    )
    assert _advice_bj(["2H", "2D"], "2C", ["hit", "stand", "split"]).action == "split"
    nodas = _advice_bj(["2H", "2D"], "2C", ["hit", "stand", "split"], rules={"das": False})
    assert nodas.action == "hit"
    assert "no DAS" in nodas.reason
    # 6:5 does not change the cell, and it is named so nobody treats the chart as +EV.
    paid = _advice_bj(["10H", "6D"], "KS", ["hit", "stand"], rules={"blackjack_payout": "6:5"})
    assert paid.action == "hit"
    assert "6:5" in paid.reason


def test_insurance_is_never_taken():
    advice = _advice_bj(["KH", "QD"], "AS", ["stand", "insurance"])
    assert advice.action == "stand"
    assert "insurance declined" in advice.reason


def test_pot_odds_and_holdem_clear_spots():
    assert pot_odds(60, 20) == pytest.approx(0.25)
    assert pot_odds(10, 0) == 0.0
    trash = load_game_state(
        {
            "game": "holdem",
            "street": "preflop",
            "hole_cards": [Card.parse("7C").model_dump(), Card.parse("2D").model_dump()],
            "community": [],
            "pot": 60,
            "to_call": 40,
            "stack": 400,
            "position": "UTG",
            "num_players": 6,
            "legal_actions": ["fold", "call", "raise"],
            "min_raise": 40,
            "raise_suggestions": [40, 80],
            "bankroll": {"cash": 400, "session_profit": 0},
        }
    )
    folded = recommend(trash)
    assert folded.action == "fold"
    assert folded.confident
    assert "trash" in folded.reason

    nuts = load_game_state(
        {
            "game": "holdem",
            "street": "river",
            "hole_cards": [Card.parse("AH").model_dump(), Card.parse("KH").model_dump()],
            "community": [Card.parse(c).model_dump() for c in ("QH", "JH", "10H", "2C", "3D")],
            "pot": 100,
            "to_call": 2,
            "stack": 900,
            "position": "BTN",
            "num_players": 2,
            "legal_actions": ["fold", "call", "raise"],
            "min_raise": 4,
            "raise_suggestions": [10, 40, 80],
            "bankroll": {"cash": 1000, "session_profit": 0},
        }
    )
    policy = RiskPolicy(max_bet_fraction=0.2)
    pushed = recommend(nuts, policy)
    assert pushed.action == "raise"
    assert pushed.action != "fold"
    sizes = filtered_raise_sizes(nuts, policy, ["fold", "call", "raise"])
    assert pushed.size in sizes

    call_only = load_game_state(
        {
            **nuts.model_dump(),
            "legal_actions": ["fold", "call"],
        }
    )
    assert recommend(call_only, policy).action == "call"


def test_holdem_raise_size_stays_inside_policy():
    state = load_game_state(
        {
            "game": "holdem",
            "street": "river",
            "hole_cards": [Card.parse("AH").model_dump(), Card.parse("KH").model_dump()],
            "community": [Card.parse(c).model_dump() for c in ("QH", "JH", "10H", "2C", "3D")],
            "pot": 100,
            "to_call": 2,
            "stack": 100,
            "position": "BTN",
            "num_players": 2,
            "legal_actions": ["fold", "call", "raise"],
            "min_raise": 80,
            "raise_suggestions": [80, 100],
            "bankroll": {"cash": 100, "session_profit": 0},
        }
    )
    policy = RiskPolicy(max_bet_fraction=0.05, min_bet=1)
    advice = recommend(state, policy)
    assert advice.action == "call"
    assert advice.action != "raise"
    assert filtered_raise_sizes(state, policy, ["fold", "call", "raise"]) == []


def test_roulette_passes_and_ignores_history():
    base = json.loads((EXAMPLES / "roulette.json").read_text(encoding="utf-8"))
    reds = dict(base)
    reds["last_results"] = [1, 3, 5, 7, 9]
    blacks = dict(base)
    blacks["last_results"] = [2, 4, 6, 8, 10]
    policy = RiskPolicy(min_bet=base["min_bet"])
    left = recommend(load_game_state(reds), policy)
    right = recommend(load_game_state(blacks), policy)
    assert left.action == "pass"
    assert right.action == "pass"
    assert "2.70%" in left.reason or "1/37" in left.reason

    forced = dict(base)
    forced["legal_bet_types"] = ["straight_up", "red"]
    forced["last_results"] = [2, 4, 6, 8, 10]
    chased = recommend(load_game_state(forced), policy)
    assert chased.action == "red"
    assert chased.action != "straight_up"
    other = dict(forced)
    other["last_results"] = [1, 3, 5, 7, 9]
    assert recommend(load_game_state(other), policy).action == "red"


def _scopa(plays, *, bankroll=None):
    hand = []
    seen = set()
    for play in plays:
        label = f"{play['hand_card']['rank']}-{play['hand_card']['suit']}"
        if label not in seen:
            hand.append(play["hand_card"])
            seen.add(label)
    return load_game_state(
        {
            "game": "scopa",
            "hand": hand,
            "table": [],
            "legal_plays": plays,
            "bankroll": bankroll or {"cash": 0, "currency": "EUR"},
        }
    )


def _play(rank, suit, captured=(), scopa=False):
    return {
        "hand_card": {"rank": rank, "suit": suit},
        "table_cards": [{"rank": r, "suit": s} for r, s in captured],
        "is_scopa": scopa,
    }


def test_scopa_prefers_scopa_then_count_then_sevens_then_low_trail():
    policy = RiskPolicy(min_bet=0)
    scopa = recommend(
        _scopa(
            [
                _play("2", "spade", [("5", "bastoni")], scopa=True),
                _play("7", "denari", [("3", "coppe"), ("4", "bastoni"), ("Re", "spade")]),
            ]
        ),
        policy,
    )
    assert scopa.action == "p0"
    assert "scopa" in scopa.reason

    more = recommend(
        _scopa(
            [
                _play("5", "coppe", [("2", "bastoni"), ("3", "spade")]),
                _play("7", "denari", [("7", "bastoni")]),
            ]
        ),
        policy,
    )
    assert more.action == "p0"

    sevens = recommend(
        _scopa(
            [
                _play("4", "coppe", [("4", "bastoni")]),
                _play("6", "spade", [("7", "denari")]),
            ]
        ),
        policy,
    )
    assert sevens.action == "p1"

    denari = recommend(
        _scopa(
            [
                _play("3", "coppe", [("3", "spade")]),
                _play("2", "denari", [("2", "bastoni")]),
            ]
        ),
        policy,
    )
    assert denari.action == "p1"

    trail = recommend(
        _scopa([_play("Re", "coppe"), _play("2", "spade")]),
        policy,
    )
    assert trail.action == "p1"
    assert "lowest" in trail.reason

    stopped = recommend(
        _scopa([_play("7", "denari", [("3", "coppe")], scopa=True)], bankroll={"cash": 0}),
        RiskPolicy(),
    )
    assert stopped.action == "pass"


def _tressette(*, trick, legal, trump="denari", lead="coppe"):
    hand = list(legal)
    return load_game_state(
        {
            "game": "tre_sette",
            "hand": hand,
            "trump_suit": trump,
            "lead_suit": lead if trick else None,
            "trick": trick,
            "legal_cards": legal,
            "bankroll": {"cash": 0, "currency": "EUR"},
        }
    )


def test_tre_sette_wins_with_the_lowest_card_then_trump_then_dump():
    policy = RiskPolicy(min_bet=0)
    win = recommend(
        _tressette(
            trick=[{"rank": "Re", "suit": "coppe"}],
            legal=[
                {"rank": "7", "suit": "coppe"},
                {"rank": "3", "suit": "coppe"},
                {"rank": "2", "suit": "denari"},
            ],
        ),
        policy,
    )
    assert win.action == "c1_3_coppe"

    trump = recommend(
        _tressette(
            trick=[{"rank": "1", "suit": "coppe"}],
            legal=[
                {"rank": "7", "suit": "coppe"},
                {"rank": "4", "suit": "coppe"},
                {"rank": "Fante", "suit": "denari"},
            ],
        ),
        policy,
    )
    assert trump.action == "c2_Fante_denari"

    dump = recommend(
        _tressette(
            trick=[{"rank": "1", "suit": "coppe"}],
            legal=[{"rank": "7", "suit": "coppe"}, {"rank": "4", "suit": "coppe"}],
        ),
        policy,
    )
    assert dump.action == "c1_4_coppe"

    lead = recommend(
        _tressette(
            trick=[],
            legal=[
                {"rank": "1", "suit": "denari"},
                {"rank": "4", "suit": "coppe"},
                {"rank": "Re", "suit": "spade"},
            ],
            lead=None,
        ),
        policy,
    )
    assert lead.action == "c1_4_coppe"


def test_italian_poker_folds_trash_and_does_not_fold_a_monster():
    trash = load_game_state(
        {
            "game": "italian_poker",
            "street": "preflop",
            "hole_cards": [
                {"rank": "2", "suit": "coppe"},
                {"rank": "4", "suit": "bastoni"},
            ],
            "community": [],
            "pot": 20,
            "to_call": 40,
            "stack": 200,
            "position": "UTG",
            "num_players": 4,
            "legal_actions": ["fold", "call", "raise"],
            "min_raise": 40,
            "bankroll": {"cash": 250, "session_profit": 0},
        }
    )
    assert recommend(trash).action == "fold"

    premium = load_game_state(
        {
            "game": "italian_poker",
            "street": "preflop",
            "hole_cards": [
                {"rank": "1", "suit": "denari"},
                {"rank": "1", "suit": "coppe"},
            ],
            "community": [],
            "pot": 10,
            "to_call": 2,
            "stack": 200,
            "position": "dealer",
            "num_players": 4,
            "legal_actions": ["fold", "call", "raise"],
            "min_raise": 10,
            "bankroll": {"cash": 1000, "session_profit": 0},
        }
    )
    assert recommend(premium, RiskPolicy(max_bet_fraction=0.2)).action == "raise"

    trips = load_game_state(
        {
            "game": "italian_poker",
            "street": "flop",
            "hole_cards": [
                {"rank": "1", "suit": "denari"},
                {"rank": "Re", "suit": "denari"},
            ],
            "community": [
                {"rank": "1", "suit": "coppe"},
                {"rank": "1", "suit": "spade"},
                {"rank": "3", "suit": "bastoni"},
            ],
            "pot": 40,
            "to_call": 2,
            "stack": 200,
            "position": "dealer",
            "num_players": 4,
            "legal_actions": ["fold", "call", "raise"],
            "min_raise": 4,
            "bankroll": {"cash": 1000, "session_profit": 0},
        }
    )
    action = recommend(trips, RiskPolicy(max_bet_fraction=0.2)).action
    assert action in {"raise", "call"}
    assert action != "fold"


def test_model_does_not_override_a_confident_chart_unless_asked():
    state = _bj(["10H", "6D"], "KS", ["hit", "stand", "double"])
    advice = recommend_blackjack(state)
    assert advice.action == "hit" and advice.confident
    request = build_request(state.model_dump())
    from jevbet.cli import _stub_response

    stub = _stub_response(Request.model_validate(request.model_dump()))
    assert stub["answers"]["action"]["choice"] == "stand"
    assert not should_use_model(advice, "strategy", model_available=True, rules={})
    kept = compose_response(request, advice, stub, source="strategy")
    assert kept["answers"]["action"]["choice"] == "hit"
    assert kept["strategy"]["source"] == "strategy"
    assert kept["strategy"]["model_choice"] == "stand"

    assert should_use_model(advice, "llm", model_available=True, rules={})
    overridden = compose_response(request, advice, stub, source="model")
    assert overridden["answers"]["action"]["choice"] == "stand"
    assert overridden["strategy"]["action"] == "hit"

    flagged = _bj(["10H", "6D"], "KS", ["hit", "stand", "double"], rules={"model_override": True})
    flagged_advice = recommend_blackjack(flagged)
    assert should_use_model(
        flagged_advice, "strategy", model_available=True, rules=dict(flagged.rules)
    )
    assert not should_use_model(
        flagged_advice, "strategy_only", model_available=True, rules={"model_override": True}
    )


def test_play_loop_uses_strategy_by_default():
    table = MockCasinoTable("blackjack", seed=7, cash=500)
    outcome = run_play_loop(
        table,
        game="blackjack",
        rounds=3,
        policy=RiskPolicy(),
        decide=None,
        advisor="strategy",
    )
    # Seed 7, S17. Decisions are per action, including insurance declines when
    # the dealer shows an ace: 18 vs 10 stands, 14 vs 7 hits, then decline
    # insurance vs ace before the hard-11 play.
    assert [row["choice"] for row in outcome["hands"]] == ["stand", "hit", "decline"]
    assert [row["spot"] for row in outcome["hands"][:2]] == ["810 vs K", "59 vs 7"]
    assert outcome["hands"][2]["choice"] == "decline"
    assert all(row["decision_source"] == "strategy" and row["applied"] for row in outcome["hands"])

    def explode(_request):
        raise AssertionError("strategy-only must not call the model")

    quiet = MockCasinoTable("blackjack", seed=7, cash=500)
    outcome = run_play_loop(
        quiet,
        game="blackjack",
        rounds=1,
        policy=RiskPolicy(),
        decide=explode,
        advisor="strategy_only",
    )
    assert outcome["hands"][0]["choice"] == "stand"


def test_cli_decide_is_strategy_first(tmp_path, capsys):
    spot = {
        "game": "blackjack",
        "dealer_upcard": {"rank": "10", "suit": "S"},
        "hands": [
            {
                "cards": [{"rank": "10", "suit": "H"}, {"rank": "6", "suit": "D"}],
                "bet": 10,
                "is_soft": False,
            }
        ],
        "legal_actions": ["hit", "stand", "double"],
        "bankroll": {"cash": 400, "session_profit": 0},
        "rules": {"decks": 6, "dealer_hits_soft_17": True, "das": True},
    }
    path = tmp_path / "sixteen.json"
    path.write_text(json.dumps(spot), encoding="utf-8")
    out = tmp_path / "decision.json"
    assert main(["decide", str(path), "--output", str(out)]) == 0
    err = capsys.readouterr().err
    assert "strategy: hit" in err
    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["answers"]["action"]["choice"] == "hit"
    assert body["strategy"]["source"] == "strategy"
    assert body["model"]["fingerprint"] == "jevbet-strategy"

    forced = tmp_path / "llm.json"
    assert main(["decide", str(path), "--llm", "--fake", "--output", str(forced)]) == 0
    llm = json.loads(forced.read_text(encoding="utf-8"))
    assert llm["answers"]["action"]["choice"] == "stand"
    assert llm["strategy"]["action"] == "hit"
    assert llm["strategy"]["source"] == "model"
    assert main(["decide", str(path), "--strategy-only", "--llm"]) == 2
