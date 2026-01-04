## MarketWatch – Command Line Guide

MarketWatch (`mw`) is a CLI + Streamlit UI tool to track a **single USD portfolio** across brokers and help with **analysis and capital allocation**.

It stores all changes in an **append‑only JSONL event log**, and can be controlled via both **CLI commands** and a **Streamlit UI**. The event log is always the source of truth.

---

### Installation (development)

- From a cloned repo:

```bash
conda env create -f environment.yml
conda activate marketwatch-dev
pip install -e ".[dev]"
```

This sets up the `mw` entrypoint and the `marketwatch-dev` environment used for testing.

---

### Concepts

- **Portfolio**: a initialized USD portfolio tracked by MarketWatch.
- **Event log (ledger)**: `ledger.jsonl` (append‑only); every state change is an event.
- **Config**: `config.json`; stores settings, targets, max weights, etc.
- **UI**: Streamlit app showing dashboard, analysis, and interactive tools.

---

### File Layout (per portfolio)

- **Portfolio directory** (created by `mw init` or lazily by `mw ui`), for example:
  - `ledger.jsonl` – JSON Lines event log.
  - `config.json` – configuration and metadata.
  - `price_cache/` – cached EOD prices, splits, dividends, etc.

MarketWatch tracks a **single current portfolio** at a time:

- `mw init` (or first `mw ui`) sets the current portfolio.
- Commands like `mw add` and `mw trade` default to operating on the **current portfolio**.
- You can override this with `--portfolio` or `--dir` if needed.

---

### Command Overview

- **Initialization & data**
  - `mw init` – initialize from an existing CSV.
  - `mw add` – add positions or cash.
  - `mw trade` – log a generic trade or short‑term activity; realized PnL affects cash and thus portfolio performance.
  - `mw config` – set targets, intrinsic values, max weights, notes.
  - `mw edit` – adjust/correct existing data (via new events).

- **Status & analysis**
  - `mw status` – minimal CLI status view (positions + cash).
  - `mw whatsup` – see recent moves and extremeness (quantiles).
  - `mw invest` – run simulations to see which tickers help reduce volatility.
  - `mw ui` – open the full dashboard (Streamlit).

---

### Recommended usage

- **Start with `mw ui`**:
  - Use Status to initialize from CSV or manual table, add trades and cash, and edit targets and max weights.
  - Use What's Up and Invest for day‑to‑day monitoring and allocation decisions.
- **Use CLI commands for scripting and batch operations**:
  - `mw init`, `mw add`, `mw trade`, `mw config`, `mw status`, `mw whatsup`, `mw invest`, `mw reset`.

---

### `mw init` – Initialize Portfolio

**Usage:**

```bash
mw init PATH_TO_CSV [--name NAME] [--dir PATH]
```

- **CSV schema (required columns):**
  - `Symbol` – e.g. `AAPL`, `SPY`, `QQQ`.
  - `Quantity` – current shares/units.
  - `Cost Price` – cost basis per unit.

**Behavior:**

- Creates a **new portfolio directory** (default: `~/.marketwatch/NAME/`).
- Ingests the CSV and writes `init_position` events to `ledger.jsonl`.
- Creates a default `config.json` with:
  - Base currency `USD`.
  - Default baselines: `SPY` and `QQQ`.
  - Default fixed deposit rate (e.g. 5% annual, weekly compounding).
- Marks this portfolio as the **current portfolio**; subsequent commands default to it.

**Example:**

```bash
mw init /path/to/my_positions.csv --name "main"
```

CSV example:

```csv
Symbol,Quantity,Cost Price
AAPL,50,150
QQQ,20,350
CASH,10000,1
```

---

### `mw add` – Add Positions or Cash

#### Add / Update a position

**Usage:**

```bash
mw add SYMBOL UNITS COST_BASIS [--note "text"] [--portfolio NAME] [--dir PATH]
```

- `SYMBOL`: ticker symbol, e.g. `AAPL`.
- `UNITS`: positive to buy, negative to sell.
- `COST_BASIS`: price per unit for this transaction.
- `--portfolio` / `--dir`: optionally target a specific portfolio; if omitted, uses the **current portfolio**.

**Behavior:**

- Appends a `trade_add` event to `ledger.jsonl` for the chosen portfolio.
- Portfolio positions and cost basis are derived from the full event history.

**Examples:**

```bash
# Buy 10 shares of AAPL at $180.50
mw add AAPL 10 180.5

# Sell 5 shares of TSLA at $250 on a specific date
mw add TSLA -5 250 --date 2025-12-01 --note "trimmed position"
```

#### Cash movement

**Usage:**

```bash
mw add cash AMOUNT [--note "text"] [--portfolio NAME] [--dir PATH]
```

- `AMOUNT > 0`: deposit cash.
- `AMOUNT < 0`: withdraw cash.
- If `--portfolio` / `--dir` are omitted, operates on the **current portfolio**.

**Example:**

```bash
# Deposit $500
mw add cash 500

# Withdraw $200
mw add cash -200 --note "moving money out"
```

---

### `mw trade` – Log Generic Trade / Activity

**Usage:**

```bash
mw trade CASH_NEEDED DURATION PNL [--note "text"] [--date YYYY-MM-DD] [--portfolio NAME] [--dir PATH]
```

- `CASH_NEEDED`: peak cash used for the strategy (e.g. 10000).
- `DURATION`: duration of the trade, typically in days (e.g. `7` or `30`).
- `PNL`: profit/loss in USD.
- `--portfolio` / `--dir`: optionally target a specific portfolio; if omitted, uses the current portfolio.

**Behavior:**

- Designed for trades that do not map neatly to a simple position (e.g. options, short‑term swings).
- On the **close date** (CLI `--date`, UI “Close date”), `PNL` is applied to your cash balance:
  - `PNL > 0` → realized gain, cash up.
  - `PNL < 0` → realized loss, cash down.
- This **does affect portfolio performance and volatility** since net liq changes on that date.
- `CASH_NEEDED` and `DURATION` are kept as metadata for risk/efficiency analytics:
  - Conceptually, a trade with duration `D` days is treated as if capital equal to `CASH_NEEDED`
    was tied up from `(close date - D)` to `close date`, but only the PnL hit on the close date
    is applied to cash.

**Example:**

```bash
mw trade 10000 7d 250 --note "short swing in NVDA options"
```

---

### `mw config` – Targets, Intrinsic Value, Max Weight

**Usage:**

```bash
mw config set-target SYMBOL [--buy PRICE] [--sell PRICE] \
  [--intrinsic PRICE] [--max-weight FRACTION] [--note "text"]
```

- `--buy`: buy target price.
- `--sell`: sell/trim target price.
- `--intrinsic`: your estimate of intrinsic value.
- `--max-weight`: max weight as fraction of portfolio (e.g. `0.10` for 10%).

**Example:**

```bash
mw config set-target AAPL --buy 150 --sell 220 --intrinsic 210 \
  --max-weight 0.12 --note "long-term core position"
```

Config changes can be done both via CLI and the Streamlit UI. Internally, changes are recorded as events.

---

### `mw edit` – Corrections / Edits

Edits are modeled as **new events** that correct previous state; the event log remains append‑only.

**Usage (CLI):**

```bash
# Open a TUI/editor to adjust last N events
mw edit [--last N]

# Or correct a specific event by id
mw edit --id EVENT_ID
```

The UI will also expose editing:

- Select an event (e.g. a mistaken `mw add`).
- Adjust fields (quantity, date, note, etc.).
- A correction event is written to `ledger.jsonl`.

From user perspective this behaves like editing; internally we keep a full audit trail.

---

### `mw status` – Portfolio Status & Baselines

**Usage:**

```bash
mw status [--as-of YYYY-MM-DD] [--no-ui] [--portfolio NAME] [--dir PATH]
```

**Behavior:**

- v1 implementation focuses on a **minimal CLI summary**:
  - Reads the event log and reconstructs:
    - Open positions (symbol, quantity, average cost basis).
    - Cash balance.
  - `--portfolio` / `--dir` select a portfolio; if omitted, uses current portfolio.
- UI and baselines (SPY/QQQ/fixed deposit) will be layered on top of this core reconstruction later.

**Outputs:**

- With `--no-ui` (default for now):
  - Prints a simple CLI summary:
    - Positions table (symbol, quantity, cost basis).
    - Cash balance.
- UI mode will be introduced once the Streamlit dashboard is wired.

**Examples:**

```bash
mw status
mw status --as-of 2025-12-31 --no-ui
```

---

### `mw whatsup` – Recent Moves & Extremeness

**Usage:**

```bash
mw whatsup [--lookback-days N] [--no-ui]
```

Defaults: `--lookback-days 252`.

**Behavior:**

- For all **portfolio tickers** and a fixed set of **broad market tickers**:
  - For example `QQQ`, `SPY`, a gold ETF, a silver ETF, sector ETFs.
- For each symbol:
  - 1‑day return (last trading day).
  - Average daily return over past 21 trading days.
  - Quantile of today’s move based on historical daily returns over lookback.

**Output:**

- Sorted by **extremeness** (how far quantile is from the middle).
- In UI:
  - A sortable table with columns: symbol, 1‑day return, 21‑day avg, quantile, etc.
- In CLI:
  - Printed table in descending order of extremeness.

**Examples:**

```bash
mw whatsup
mw whatsup --lookback-days 504 --no-ui
```

---

### `mw invest` – Simulated Allocation Help

**Usage:**

```bash
mw invest AMOUNT [--lookback-years Y] [--horizon "Xm"] [--no-ui]
```

Defaults:

- `--lookback-years 5`
- `--horizon "3m"` (3 months).

**Behavior:**

- Universe = existing portfolio tickers + watchlist (tickers with buy targets only).
- For each candidate ticker:
  - Simulate, over a rolling window across history:
    - Start with your historical portfolio (reconstructed from ledger).
    - At many past dates, add a hypothetical purchase of `AMOUNT` in that ticker (respecting `max_weight`).
    - Track look‑forward volatility (or reduction in volatility) over the next horizon.
  - Aggregate results into an average volatility impact.

**Output:**

- In UI:
  - A table of candidates, sorted by **average volatility reduction** (or lowest resulting volatility).
  - Columns: symbol, average volatility change, times tested, current price, distance to buy target, etc.
  - Controls to tweak `lookback-years`, `horizon`, and filters.
- In CLI (`--no-ui`):
  - Top N tickers with summary metrics.

**Examples:**

```bash
mw invest 1000
mw invest 5000 --lookback-years 8 --horizon "6m" --no-ui
```

---

### `mw ui` – Full Dashboard

**Usage:**

```bash
mw ui
```

- Launches the full Streamlit UI:
  - Status page (portfolio vs baselines).
  - What’s Up page (recent moves, quantiles).
  - Invest simulation page.
  - Event log page (view and edit via correction events).
  - Config page (targets, intrinsic values, max weights, fixed deposit rate, etc.).

Any UI change that affects state (for example editing a note, adding a trade, changing a target) writes an appropriate event to the ledger, same as if done through CLI.


