"""Jevbet CLI: ``jevbet decide`` and ``jevbet demo``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rizzo_flow.schema import Request

from .choices import HOLD_POLICY, fail_close_answers, legal_ids
from .games.registry import build_request, list_games
from .policy import RiskPolicy


def write_json(value, destination: str | None):
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if destination:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as stream:
            stream.write(text)
    else:
        print(text, end="")


def _policy_from_args(args) -> RiskPolicy:
    return RiskPolicy(
        max_bet_fraction=args.max_bet_fraction,
        max_bet_absolute=args.max_bet_absolute,
        min_bet=args.min_bet,
        forbid_all_in=not args.allow_all_in,
    )


def _stub_response(request: Request) -> dict:
    """Deterministic no-weight response for demos and --fake.

    Among real (post-policy) options, prefers the second when several exist.
    Never selects the ``hold_policy`` sentinel or any id outside that set.
    """
    answers = {}
    for qid, question in request.questions.items():
        if question.type == "choice":
            real = legal_ids(list(question.options))
            if not real:
                raise ValueError(f"Question {qid!r} has no post-policy legal option")
            choice = real[1] if len(real) > 1 else real[0]
            if choice == HOLD_POLICY:
                raise ValueError("stub selected the fail-closed sentinel")
            probs = {o.id: (1.0 if o.id == choice else 0.0) for o in question.options}
            answers[qid] = {
                "type": "choice",
                "status": "ok",
                "choice": choice,
                "probabilities": probs,
                "option_logits": {
                    o.id: (10.0 if o.id == choice else 0.0) for o in question.options
                },
                "legend": {o.id: o.description for o in question.options},
                "uncertainty": {
                    "top_probability": 1.0,
                    "entropy_nats": 0.0,
                    "concentration": 1.0,
                    "unavailable_probability": 0.0,
                },
                "probability_status": "uncalibrated_conditional_option_scores",
                "temperature": 1.0,
                "prompt_sha256": "jevbet-stub",
                "input_tokens": 1,
            }
        elif question.type == "numeric":
            mid = question.anchors[len(question.anchors) // 2]
            n = len(question.anchors)
            answers[qid] = {
                "type": "numeric",
                "status": "ok",
                "value": mid.value,
                "probabilities": {str(a.value): 1.0 / n for a in question.anchors},
                "option_logits": {str(a.value): 0.0 for a in question.anchors},
                "legend": {str(a.value): a.description for a in question.anchors},
                "uncertainty": {
                    "top_probability": 1.0 / n,
                    "entropy_nats": 0.0,
                    "concentration": 1.0 / n,
                    "unavailable_probability": 0.0,
                },
                "probability_status": "uncalibrated_conditional_option_scores",
                "temperature": 1.0,
                "prompt_sha256": "jevbet-stub",
                "input_tokens": 1,
                "unit": question.unit,
                "statistics_given_available": None,
                "support": [question.anchors[0].value, question.anchors[-1].value],
            }
        else:
            raise NotImplementedError(f"stub does not cover question type {question.type}")
    return {
        "model": {"fingerprint": "jevbet-stub"},
        "mode": request.mode,
        "answers": answers,
        "calibration": None,
        "timing": {"generated_tokens": 0, "total_seconds": 0.0},
    }


def _post_decision(url: str, request: Request, timeout: float) -> dict:
    import urllib.error
    import urllib.request

    data = json.dumps(request.model_dump()).encode("utf-8")
    req = urllib.request.Request(
        url.rstrip("/") + "/v1/decisions",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to reach Rizzo at {url}: {exc}") from exc


def cmd_decide(args) -> int:
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    policy = _policy_from_args(args)
    request = Request.model_validate(
        build_request(payload, game=args.game, policy=policy).model_dump()
    )
    body = request.model_dump()
    if args.schema_only:
        write_json(body, args.output)
        return 0
    if args.url:
        try:
            response = _post_decision(args.url, request, args.timeout)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        _publish(request, response, args.output)
        return 0
    if args.fake:
        _publish(request, _stub_response(request), args.output)
        return 0

    from rizzo_flow.engine import Engine
    from rizzo_flow.loader import load_backend

    backend = load_backend(
        args.backend,
        size=args.size,
        model=args.model,
        quant=args.quant,
        bits=args.bits,
        device=args.device,
        ctx=args.ctx,
        batch_size=args.batch_size,
        threads=args.threads,
    )
    _publish(request, Engine(backend, ctx=args.ctx).decide(request), args.output)
    return 0


def _publish(request: Request, response: dict, destination: str | None) -> None:
    """Map a sentinel (or abstention on a forced action) back to the legal id."""
    answers = response.get("answers")
    if isinstance(answers, dict):
        fail_close_answers(request.questions, answers)
    write_json(response, destination)


def cmd_demo(args) -> int:
    from .browser.mock import MockTableDriver

    fixture = args.fixture or ("blackjack.html" if args.game == "blackjack" else "holdem.html")
    driver = MockTableDriver.from_fixture(fixture)
    state = driver.read_state()
    policy = _policy_from_args(args)
    request = Request.model_validate(build_request(state, policy=policy).model_dump())
    print("=== observed state ===")
    write_json(state, None)
    print("=== rizzo request ===")
    write_json(request.model_dump(), None)
    if args.schema_only:
        return 0
    response = _stub_response(request)
    fail_close_answers(request.questions, response["answers"])
    print("=== decision (stub) ===")
    write_json(response, None)
    action_answer = (
        response["answers"].get("action")
        or response["answers"].get("card")
        or response["answers"].get("play")
        or response["answers"].get("bet_type")
        or next(iter(response["answers"].values()))
    )
    chosen = action_answer.get("choice")
    amount = None
    for key in ("raise_amount", "bet_amount"):
        if key in response["answers"] and response["answers"][key].get("value") is not None:
            amount = response["answers"][key]["value"]
    if chosen and chosen in driver.legal_actions():
        driver.act(chosen, amount=amount)
        print(f"=== applied on mock table: {chosen} amount={amount} ===")
    else:
        print(f"=== model chose {chosen!r}; not applied (not in legal mock actions) ===")
    return 0


def cmd_play(args) -> int:
    """Mock casino: read → decide → act, for ``--rounds`` decisions."""
    from .browser.adapters import MockCasinoAdapter
    from .play import run_play_loop

    if args.rounds < 1 or args.rounds > 100:
        print("rounds must be between 1 and 100", file=sys.stderr)
        return 2
    if not args.schema_only and not args.fake and not args.url:
        print(
            "pass --fake, --url, or --schema-only "
            "(jevbet play does not download or load the 4B weights)",
            file=sys.stderr,
        )
        return 2
    policy = _policy_from_args(args)
    adapter = MockCasinoAdapter(
        args.game,
        browser=args.browser,
        seed=args.seed,
        cash=args.bankroll,
        stop_loss=args.stop_loss,
        port=args.port,
        headless=not args.headed,
    )
    try:
        driver = adapter.open()
        if args.schema_only:
            outcome = run_play_loop(
                driver,
                game=args.game,
                rounds=args.rounds,
                policy=policy,
                decide=None,
                schema_only=True,
            )
            write_json(outcome["request"], args.output)
            return 0

        def decide(request: Request) -> dict:
            if args.fake:
                return _stub_response(request)
            return _post_decision(args.url, request, args.timeout)

        outcome = run_play_loop(
            driver,
            game=args.game,
            rounds=args.rounds,
            policy=policy,
            decide=decide,
            schema_only=False,
        )
    except (RuntimeError, ImportError, ValueError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        adapter.close()
    outcome["adapter"] = "mock-casino"
    outcome["driver"] = "playwright" if args.browser else "in-process"
    for row in outcome["hands"]:
        print(
            f"round {row['round']}: choice={row['choice']} applied={row['applied']} "
            f"amount={row['amount']} cash={row['bankroll_cash']} "
            f"profit={row['session_profit']} spot={row['spot']}",
            file=sys.stderr,
        )
    if outcome["stopped"]:
        print(f"stopped: {outcome['stop_reason']}", file=sys.stderr)
    summary = {
        "adapter": outcome["adapter"],
        "driver": outcome["driver"],
        "game": outcome["game"],
        "rounds_requested": outcome["rounds_requested"],
        "stopped": outcome["stopped"],
        "stop_reason": outcome["stop_reason"],
        "hands": outcome["hands"],
    }
    write_json(summary, args.output)
    return 0


def cmd_games(_args) -> int:
    write_json(list_games(), None)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Jevbet — card/betting decisions on top of Rizzo Flow"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--max-bet-fraction", type=float, default=0.05)
    shared.add_argument("--max-bet-absolute", type=float, default=None)
    shared.add_argument("--min-bet", type=float, default=1.0)
    shared.add_argument("--allow-all-in", action="store_true")

    decide = commands.add_parser(
        "decide", parents=[shared], help="Game state JSON → Rizzo request/decision"
    )
    decide.add_argument("input", type=Path)
    decide.add_argument("--game", help="Override game id when the JSON omits it")
    decide.add_argument("--output")
    decide.add_argument(
        "--schema-only",
        action="store_true",
        help="Print the /v1/decisions request only (no model load)",
    )
    decide.add_argument("--url", help="POST to a running Rizzo server (e.g. http://127.0.0.1:8017)")
    decide.add_argument("--timeout", type=float, default=120.0)
    decide.add_argument("--fake", action="store_true", help="Stub decision without loading weights")
    decide.add_argument("--size", default="4b")
    decide.add_argument("--backend", default="llama")
    decide.add_argument("--model", type=Path)
    decide.add_argument("--quant")
    decide.add_argument("--bits", type=int, choices=(4, 8))
    decide.add_argument("--device", default="auto")
    decide.add_argument("--threads", type=int)
    decide.add_argument("--batch-size", type=int, default=4)
    decide.add_argument("--ctx", type=int, default=8192)

    demo = commands.add_parser("demo", parents=[shared], help="One step on a local mock HTML table")
    demo.add_argument("--game", default="blackjack", choices=("blackjack", "holdem"))
    demo.add_argument("--fixture", help="HTML fixture under jevbet/browser/fixtures/")
    demo.add_argument("--schema-only", action="store_true")

    commands.add_parser("games", help="List built-in games")

    play = commands.add_parser(
        "play",
        parents=[shared],
        help="Play the local mock casino (in-process, or Chromium with --browser)",
    )
    play.add_argument("--adapter", required=True, choices=("mock-casino",))
    play.add_argument("--game", required=True, choices=("blackjack", "holdem"))
    play.add_argument("--rounds", type=int, default=1)
    play.add_argument("--fake", action="store_true", help="Stub decision without loading weights")
    play.add_argument(
        "--schema-only",
        action="store_true",
        help="Print one /v1/decisions request and do not act",
    )
    play.add_argument("--url", help="POST each decision to a running Rizzo server")
    play.add_argument("--timeout", type=float, default=120.0)
    play.add_argument("--output")
    play.add_argument(
        "--browser",
        action="store_true",
        help="Serve the HTML mock and drive it with Playwright Chromium",
    )
    play.add_argument("--headed", action="store_true", help="Show the Chromium window")
    play.add_argument("--port", type=int, default=0, help="Loopback port (0 picks a free port)")
    play.add_argument("--seed", type=int, default=7)
    play.add_argument("--bankroll", type=float, default=500.0)
    play.add_argument(
        "--stop-loss",
        type=float,
        default=None,
        help="Stop the session when profit falls to -stop-loss (stored on the bankroll)",
    )

    args = parser.parse_args(argv)
    if args.command == "decide":
        return cmd_decide(args)
    if args.command == "demo":
        return cmd_demo(args)
    if args.command == "play":
        return cmd_play(args)
    if args.command == "games":
        return cmd_games(args)
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
