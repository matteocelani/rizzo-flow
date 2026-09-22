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
| `jevbet.choices` | Fail-closed padding when only one legal action remains |
| `jevbet.browser.TableDriver` | `read_state` / `legal_actions` / `act` |
| `MockTableDriver` | Static HTML fixtures (CI-safe, no browser) |
| `MockCasinoTable` | In-process blackjack / holdem used by `jevbet play --fake` |
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
true. Their default policy uses `min_bet=0`, so a fixture with `cash: 0` (not a
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

# Print a typed Rizzo request from a blackjack fixture (no model needed):
uv run jevbet decide examples/games/blackjack.json --schema-only

# Stub decision without weights:
uv run jevbet decide examples/games/blackjack.json --fake

# Against a live local server:
uv run jevbet decide examples/games/blackjack.json --url http://127.0.0.1:8017

# One mock-table step (static HTML fixture, no network):
uv run jevbet demo --game blackjack
uv run jevbet demo --game holdem

# Full decide → act loop on the in-process mock (no 4B download, no Playwright):
uv run jevbet play --adapter mock-casino --game blackjack --rounds 3 --fake
uv run jevbet play --adapter mock-casino --game holdem --rounds 3 --fake

# Print one request from the live table and do not act:
uv run jevbet play --adapter mock-casino --game blackjack --schema-only
```

Playwright, only if you want Chromium to click the HTML mock:

```bash
uv sync --extra browser --locked
uv run playwright install chromium
uv run jevbet play --adapter mock-casino --game blackjack --rounds 3 --fake --browser
```

`--browser` serves `src/jevbet/browser/fixtures/` on `127.0.0.1` and drives it with
headless Chromium (`--headed` shows the window). `--stop-loss 50` stops the session
when profit reaches −50. `--url http://127.0.0.1:8017` posts each decision to a
running `rizzo serve` instead of `--fake`. `play` never downloads or loads the 4B
weights; point it at a server you already started.

## Mock first

The shipped table is a **local casino mock**: blackjack (hit / stand / double / split,
bankroll) and one Texas Hold'em street (fold / check / call / raise, amount input).
It is not a real casino, it does not log in anywhere, and it has no credentials.

`examples/mock-casino/adapter.example.json` is the config shape. The default URL
allowlist is loopback. `load_adapter_config` rejects keys such as `password`,
`token`, and `cookie`.

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

**IT.** Jevbet specializza Rizzo Flow per giochi di carte e scommesse: stato tipizzato →
richiesta `/v1/decisions` → azione sul tavolo. Niente fine-tune dei pesi Spark in questa
fase. I driver dei casinò reali sono adattatori opzionali; i test usano tavoli HTML mock.

**EN.** Jevbet specializes Rizzo Flow for card/betting games: typed state →
`/v1/decisions` request → table action. No Spark fine-tuning in this phase. Real-site
drivers are optional adapters; tests use mock HTML tables.
