"""Fail-closed choice options for Rizzo's ≥2-option constraint.

Rizzo ``choice`` questions need at least two options. When ``RiskPolicy`` leaves
a single legal action, builders must not invent a second *game* action (that
would undo the filter). They append ``hold_policy`` instead — a sentinel that
is not a table move. Choosing it, or abstaining, maps back to the sole legal id.

Option ids must match ``^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$``, so the sentinel
cannot start with underscores.
"""

from __future__ import annotations

from rizzo_flow.schema import Option

# Not a game action. Documented in docs/jevbet.md.
HOLD_POLICY = "hold_policy"


def no_play_options(detail: str) -> list[Option]:
    """Safe stop path: one ``pass`` action, then the fail-closed sentinel.

    ``pass`` is not a card and not a stake. Builders use it when
    ``RiskPolicy.should_stop`` is true so a costly or forced play is not the
    only letter in front of the model.
    """
    return pad_singleton(
        [
            Option(
                id="pass",
                description=(
                    "Pass. Do not play a card and do not stake chips. "
                    f"Session policy stopped this decision ({detail})."
                ),
            )
        ]
    )


def pad_singleton(options: list[Option]) -> list[Option]:
    """Return ``options`` unchanged when ≥2; otherwise append the sentinel."""
    if len(options) >= 2:
        return options
    if len(options) != 1:
        raise ValueError("At least one legal option is required")
    sole = options[0]
    if sole.id == HOLD_POLICY:
        raise ValueError(f"Legal action id collides with sentinel {HOLD_POLICY!r}")
    return [
        sole,
        Option(
            id=HOLD_POLICY,
            description=(
                f"Sentinel, not a table action. The only legal action is {sole.id}. "
                "Selecting this letter is mapped back to that action."
            ),
        ),
    ]


def legal_ids(options: list[Option]) -> list[str]:
    return [option.id for option in options if option.id != HOLD_POLICY]


def resolve_choice(choice: str | None, legal: list[str]) -> str | None:
    """Map a model letter to a post-policy action.

    A sentinel, an unknown id, or abstention collapses to the sole legal action.
    With several legal actions, an id outside that set is dropped (returns None)
    rather than applied.
    """
    if choice in legal and choice != HOLD_POLICY:
        return choice
    if len(legal) == 1:
        return legal[0]
    return None


def fail_close_answers(request_questions: dict, answers: dict) -> dict:
    """Rewrite choice answers so the published id is always post-policy legal."""
    for qid, question in request_questions.items():
        if getattr(question, "type", None) != "choice":
            continue
        answer = answers.get(qid)
        if not isinstance(answer, dict):
            continue
        legal = legal_ids(list(question.options))
        resolved = resolve_choice(answer.get("choice"), legal)
        answer["choice"] = resolved
        if resolved is None:
            answer["status"] = "uncertain"
    return answers
