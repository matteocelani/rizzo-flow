# Jevbet

**Jevbet** is a thin domain layer on top of [Rizzo Flow](../README.md) for **card and
betting games**. It turns a structured table state into a typed
`POST /v1/decisions` request, optionally constrains bets with a bankroll policy, and
maps the chosen action back onto a browser table driver.

It does **not** retrain or fine-tune Spark weights. The default decision is a
deterministic **strategy engine**. Spark is an optional advisor (`--llm` /
`--url`), still filtered by `RiskPolicy`. Specialization is charts, heuristics,
schemas, and prompts inside builders — not a fine-tune.

## Architecture

```
game state JSON  ──►  RiskPolicy (legal actions / sizes)
                         │
                         ▼
               jevbet.strategy.recommend
                         │
            confident action still legal?
              │                      │
              │ yes                  │ no, or --llm / model_override
              ▼                      ▼
        strategy action      optional Rizzo advisor
              │               (Engine, --url, or --fake)
              └──────────┬───────────┘
                         ▼
              TableDriver.act(choice)
```

`jevbet decide` and `jevbet play` are strategy-first. A confident strategy action
that is still legal after `RiskPolicy` is what gets applied. The model is not
loaded unless you pass `--llm` or `--model-override` (and, for `play`, `--fake`
or `--url` — play never downloads the 4B weights). `--url` or `--fake` without
those flags still asks the model for a probability report, but the report does
not replace a confident strategy action. `--strategy-only` skips the model
entirely. `state.rules.model_override: true` is the same switch when a model
response is actually present.

| Piece | Role |
| --- | --- |
| `jevbet.strategy` | Deterministic action, reason, confidence, fallbacks |
| `jevbet.games.*` | Pydantic states + builders per game |
| `jevbet.policy.RiskPolicy` | Max bet fraction, stop-loss; filters options **before** strategy and the model |
| `jevbet.choices` | Fail-closed padding when only one legal action remains |
| `jevbet.browser.TableDriver` | `read_state` / `legal_actions` / `act` |
| `MockTableDriver` | Static HTML fixtures (CI-safe, no browser) |
| `MockCasinoTable` | In-process blackjack / holdem used by `jevbet play` |
| `ChromeTableDriver` | Playwright Chromium. `read_state` understands the **local mock** DOM only |
| `jevbet.browser.adapters` | `AdapterConfig` + `MockCasinoAdapter`. Real sites are your subclass |

Built-in games: `blackjack`, `holdem`, `italian_poker`, `tre_sette`, `scopa`, `roulette`.
Register more with `jevbet.register_game(name, StateCls, builder)`.

## Fail-closed choices

Rizzo `choice` questions need at least two options. `RiskPolicy` can leave a single
legal action (stop-loss drops hit/double/call/raise). Builders **do not** pad a second
real move — that would put a filtered action back in front of the model.

They append the sentinel option id `hold_policy` (not a table action; Rizzo option ids
must start with a letter or digit, so it is not `__hold_policy__`). `jevbet.choices.resolve_choice`
maps that sentinel, an unknown id, or abstention back to the sole legal action.
`_stub_response` only ever picks ids in the post-policy set, never the sentinel and never
a filtered action.

Roulette stop-loss does **not** keep the first bet type. The only offered action is
`pass` (plus `hold_policy` when that is the sole option), and no stake question is
asked. Scopa and tre sette do the same with a no-play `pass` when `should_stop` is
true. Blackjack, Hold'em, and poker italiano do the same when the filter removes
**every** legal action (stop-loss with only hit/double/call/raise, or Hold'em left
with only `all_in` while all-in is forbidden). They offer `pass` plus `hold_policy`.
They do not fall back to `legal_actions[0]` of the unfiltered set. Their default policy uses `min_bet=0`, so a fixture with `cash: 0` (not a
betting game) still asks for a card; an explicit policy, stop-loss, or take-profit
does not.

`ChromeTableDriver.read_state` reads the local mock casino (`data-*` attributes in
`src/jevbet/browser/fixtures/`). Any other game raises `NotImplementedError` — subclass
it for a site you control. `base_url` must match `allowed_url_prefixes`, which default
to `http://127.0.0.1`, `http://localhost`, and the `https` variants of those hosts.
Navigation uses a 30s timeout. If `start()` fails, the browser process is closed.

## Quickstart (Mac / Metal)

Jevbet rides on the same Rizzo install. On a MacBook:

```bash
uv sync --extra test --locked
uv run rizzo download          # llama.cpp Metal runtime + Spark 4B Q8_0
uv run rizzo serve             # http://127.0.0.1:8017

# Strategy decision, no model and no download (action + reason on stderr, JSON on stdout):
uv run jevbet decide examples/games/blackjack.json

# Print the typed Rizzo request only:
uv run jevbet decide examples/games/blackjack.json --schema-only

# Let a stub or a live server choose instead of the chart:
uv run jevbet decide examples/games/blackjack.json --llm --fake
uv run jevbet decide examples/games/blackjack.json --llm --url http://127.0.0.1:8017

# One mock-table step (static HTML fixture, no network):
uv run jevbet demo --game blackjack
uv run jevbet demo --game holdem

# Decide → act on the in-process mock. Strategy is the default (no 4B download):
uv run jevbet play --adapter mock-casino --game blackjack --rounds 3
uv run jevbet play --adapter mock-casino --game holdem --rounds 3

# Same loop, but the stub picks the action (still inside the policy filter):
uv run jevbet play --adapter mock-casino --game blackjack --rounds 3 --llm --fake

# Print one request from the live table and do not act:
uv run jevbet play --adapter mock-casino --game blackjack --schema-only
```

Playwright, only if you want Chromium to click the HTML mock:

```bash
uv sync --extra browser --locked
uv run playwright install chromium
uv run jevbet play --adapter mock-casino --game blackjack --rounds 3 --browser
```

`--browser` serves `src/jevbet/browser/fixtures/` on `127.0.0.1` and drives it with
headless Chromium (`--headed` shows the window). `--stop-loss 50` stops the session
when profit reaches −50. `--url http://127.0.0.1:8017` posts each decision to a
running `rizzo serve` (a report, unless you also pass `--llm`). `play` never
downloads or loads the 4B weights.

## What the strategy actually knows

Honest split. Nothing here is a claim of profit, and none of it is Spark.

| Game | What you get | What you do not get |
| --- | --- | --- |
| Blackjack | Multi-deck **basic strategy**. Default chart is 4–8 decks, dealer hits soft 17, double after split, late surrender when that button is legal (Blackjack Apprenticeship H17 chart, 2024). Soft 18 vs 9 is a **hit** on that chart. | Card counting, composition-dependent indices, single-deck or double-deck cell changes (the multi-deck chart is still used, and the reason says so), European no-hole-card, early surrender. A 6:5 blackjack payout does **not** change the cells and it does eat the edge the chart was built to protect. Insurance is never taken. |
| Blackjack rules | `dealer_hits_soft_17` / `dealer_stands_soft_17`, `das`, `surrender`, `decks`, `blackjack_payout`. S17 flips six cells: 11 vs A hits; soft 18 vs 2 stands; soft 19 vs 6 stands; 15 vs A and 17 vs A do not surrender; 8s vs A split instead of surrender. No DAS: 2s and 3s vs 2–3 hit, 4s vs 5–6 hit, 6s vs 2 hit. Stop-loss treats hit, double, split, insurance, and surrender as costly. When that empties the free set, builders and strategy offer `pass` + `hold_policy` — never `legal_actions[0]`. | If the chart says surrender or double or split and that action is not legal after policy, the next chart action is used (surrender → hit, double → hit or stand, split → the hard/soft total). |
| Hold'em | Pot odds `to_call / (pot + to_call)`. Preflop bucket: premium / strong / speculative / trash. Postflop flags from the cards only: pair, overcards, flush or straight draw, and whether the holding is the nuts on this board. Raise size is one of the sizes `RiskPolicy` already kept. | Not GTO. No ranges, no opponent model, no equity solver. Draw “equity” is a fixed approximation (about 35% for a flopped flush draw, and so on), not a simulation. Clear spots are confident (trash facing a bet folds; the nuts does not fold). Marginal pairs are not. |
| Poker italiano | The same heuristic on 40-card ranks. Asso is high. Straights use those numbers, so asso does not connect to Re. | Not a solved Italian-deck game. |
| Scopa | Among `legal_plays`: a scopa, else more cards captured, else more sevens (sette bello breaks the next tie), else more denari, else trail the lowest pip (Fante 8, Cavallo 9, Re 10). | Not a search of the remaining deck. No opponent model. |
| Tre sette | `legal_cards` already encode must-follow. Win the trick with the cheapest card that beats the current winner (a small lead-suit card before a trump). If nothing wins, dump the lowest card and keep trump. Lead the lowest card. Order: Asso, 3, Re, Cavallo, Fante, then 7…2. | Not partnership signalling. Not a point-count endgame. |
| Roulette | **Impossible to beat** with a selection rule. European house edge is 1/37 ≈ 2.70%. American (0 and 00) is 2/38 ≈ 5.26%. Even-money bets have that same edge; they are only less volatile. `last_results` are ignored. Default action is `pass`. If pass is not legal, the minimum even-money bet (red, black, even, odd, low, high — fixed order, not “whatever just hit”). | No positive-EV bet exists. Chasing a colour because it just repeated is not a strategy this code will emit. |

`recommend_blackjack` recomputes hard and soft totals from the cards. A caller
`is_soft` flag that disagrees is reported in the reason and ignored. The action
is always one of the post-policy legal ids, never `hold_policy`. Stop-loss still
removes hit, double, split, call, and raise before this choice is made.

## Mock first

The shipped table is a **local casino mock**: blackjack (hit / stand / double / split,
bankroll) and one Texas Hold'em street (fold / check / call / raise, amount input).
It is not a real casino, it does not log in anywhere, and it has no credentials.

`examples/mock-casino/adapter.example.json` is the config shape. The default URL
allowlist is loopback. `load_adapter_config` walks every nested object and list
and rejects credential-shaped keys (`password`, `secret`, `api_key`, `token`,
`cookie`, `authorization`, and the same names in any casing, including
`selectors.extra.password`).

### Adding a site adapter later

Do this only for a site whose terms allow it, with a session you already own.

1. Copy `examples/mock-casino/adapter.example.json` to a path you do not commit if
   it contains anything environment-specific. JSON needs no extra dependency. YAML
   is read only when PyYAML is installed; otherwise convert to JSON.
2. Set `base_url` and widen `allowed_url_prefixes` to that origin **explicitly**.
   The default stays localhost. There is no built-in casino URL.
3. Fill `selectors` from the page's DOM (table root, action buttons, stake input).
   Do not put usernames, passwords, cookies, or tokens in the file.
4. If the page does not use the mock `data-game` / `data-action` / `data-cards`
   attributes, subclass `ChromeTableDriver` and override `read_state`. Keep `act`
   matching `data-action` by equality — never paste a model string into a CSS
   selector. Map `hold_policy` back to the single legal action before you click;
   `jevbet play` already does that.
5. Wire your subclass the way `MockCasinoAdapter` wires `ChromeTableDriver`, and
   keep using `RiskPolicy` so a stopped session cannot be offered a filtered bet.

## Examples

JSON fixtures live in `examples/games/` (`blackjack.json`, `holdem.json`, …). Each one
carries a valid `legal_actions` / `legal_plays` / `legal_bet_types` set so builders never
invent illegal moves.

## Tests

```bash
uv sync --extra test --locked
uv run ruff check src tests scripts
uv run pytest -q
```

No `RIZZO_REAL`, no 4B download, no Playwright. `MockTableDriver`, `MockCasinoTable`,
and the play-loop tests cover the decide → act path. `@pytest.mark.browser` starts the
loopback mock and Chromium; it skips when Playwright or the browser binary is missing.

```bash
uv run pytest -q -m browser
```

## What’s next

- Your own site adapter (selectors + a `read_state` subclass), if the site allows it
- Mac Metal numbers for `rizzo serve` behind `jevbet play --url`
- Optional calibration fixtures for betting domains
- More games via `register_game`

## IT / EN

**IT.** Jevbet decide prima con una strategia deterministica (blackjack: basic strategy
multi-mazzo; gli altri giochi: euristiche dichiarate, non GTO). Spark è un consulente
opzionale (`--llm`), non sovrascrive una mossa sicura della strategia. La roulette ha
valore atteso negativo: l'azione predefinita è `pass`. Niente fine-tune dei pesi.

**EN.** Jevbet decides with a deterministic strategy first (blackjack: multi-deck basic
strategy; other games: stated heuristics, not GTO). Spark is an optional advisor
(`--llm`) and does not override a confident strategy action. Roulette has negative
expected value: the default action is `pass`. No weight fine-tune.
