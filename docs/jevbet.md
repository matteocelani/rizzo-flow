# Jevbet

**Jevbet** is a thin domain layer on top of [Rizzo Flow](../README.md) for **card and
betting games**. It turns a structured table state into a typed
`POST /v1/decisions` request, optionally constrains bets with a bankroll policy, and
maps the chosen action back onto a browser table driver.

It does **not** retrain or fine-tune Spark weights. Specialization is schemas, question
packs, examples, prompts inside builders, and (later) optional calibration fixtures.

## Architecture

```
game state JSON  ──►  jevbet builders (+ RiskPolicy)
                         │
                         ▼
                 rizzo_flow.schema.Request
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
   --schema-only   rizzo Engine    HTTP /v1/decisions
          │         (llama/MLX)     (rizzo serve)
          ▼              ▼              ▼
     printed req      answers        answers
                         │
                         ▼
              TableDriver.act(choice)
```

| Piece | Role |
| --- | --- |
| `jevbet.games.*` | Pydantic states + builders per game |
| `jevbet.policy.RiskPolicy` | Max bet fraction, stop-loss; filters options **before** the model |
| `jevbet.browser.TableDriver` | `read_state` / `legal_actions` / `act` |
| `MockTableDriver` | Local HTML fixtures (CI-safe) |
| `ChromeTableDriver` | Playwright Chromium skeleton + selector map (site adapters plug in here) |

Built-in games: `blackjack`, `holdem`, `italian_poker`, `tre_sette`, `scopa`, `roulette`.
Register more with `jevbet.register_game(name, StateCls, builder)`.

## Quickstart (Mac / Metal)

Jevbet rides on the same Rizzo install. On a MacBook:

```bash
uv sync --extra test --locked
uv run rizzo download          # llama.cpp Metal runtime + Spark 4B Q8_0
uv run rizzo serve             # http://127.0.0.1:8017

# Print a typed Rizzo request from a blackjack fixture (no model needed):
uv run jevbet decide examples/games/blackjack.json --schema-only

# Stub decision without weights:
uv run jevbet decide examples/games/blackjack.json --fake

# Against a live local server:
uv run jevbet decide examples/games/blackjack.json --url http://127.0.0.1:8017

# One mock-table step (HTML fixture, no network):
uv run jevbet demo --game blackjack
uv run jevbet demo --game holdem
```

Optional Chromium driver:

```bash
uv sync --extra browser --locked
uv run playwright install chromium
```

`ChromeTableDriver` takes a **configurable** `base_url` and `SelectorMap`. There are no
hard-coded casino URLs. Live site adapters are pluggable subclasses: implement
`read_state()` for that site’s DOM, keep credentials out of the repo, and respect the
site’s terms of service.

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

No `RIZZO_REAL`, no 4B download. Browser tests use `MockTableDriver` only.

## What’s next

- Site-specific Playwright adapters (selectors + stake inputs)
- Mac integration tests with Metal + a headed mock page
- Optional calibration fixtures for betting domains
- More games via `register_game`

## IT / EN

**IT.** Jevbet specializza Rizzo Flow per giochi di carte e scommesse: stato tipizzato →
richiesta `/v1/decisions` → azione sul tavolo. Niente fine-tune dei pesi Spark in questa
fase. I driver dei casinò reali sono adattatori opzionali; i test usano tavoli HTML mock.

**EN.** Jevbet specializes Rizzo Flow for card/betting games: typed state →
`/v1/decisions` request → table action. No Spark fine-tuning in this phase. Real-site
drivers are optional adapters; tests use mock HTML tables.
