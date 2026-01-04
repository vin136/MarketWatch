## MarketWatch

MarketWatch is a **Python‑native CLI + Streamlit UI** to track a **single USD portfolio** across brokers and help with **analysis and capital allocation**.

All state changes (cash flows, trades, config edits, corrections) are written to an **append‑only JSONL event log**; both the CLI and UI operate on the same log so you always have a clear audit trail.

---

### Features

- **Single USD portfolio**
  - Positions + cash, tracked across brokers.
  - Event‑sourced ledger (`ledger.jsonl`) as the source of truth.
- **CLI and UI**
  - `mw ui` launches a Streamlit dashboard (Status, What's Up, Invest, Log, Config).
  - CLI commands for scripting and quick edits (`mw add`, `mw trade`, `mw config`, etc.).
- **Price data and baselines**
  - Yahoo Finance–backed `PriceProvider` with on‑disk CSV caching per symbol.
  - Portfolio series vs baselines: `SPY`, `QQQ`, and a fixed‑deposit synthetic portfolio.
- **Analytics**
  - “What’s Up” view: recent moves, 21‑day averages, quantiles.
  - “Invest” view: simple simulation of volatility impact when deploying new cash.
- **Targets and max weights**
  - Per‑symbol `buy_target`, `sell_target`, `intrinsic_value`, `max_weight`.
  - Global defaults for FD rate, default max weight, and analytics lookbacks.

---

### Installation (development)

Clone the repo and install in editable mode:

```bash
git clone https://github.com/your-org/marketwatch.git
cd marketwatch

# Option 1: conda (recommended for this project)
conda env create -f environment.yml
conda activate marketwatch-dev

# Option 2: plain Python
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

The `marketwatch-dev` conda environment is set up to include `pytest`, `streamlit`, `typer`, and `yfinance`.

---

### Recommended workflow

- **1. Start with the UI**
  - Launch: `mw ui`
  - If no portfolio exists, the UI (or `mw init`) will create one under `~/.marketwatch/<name>/`.
  - Use the **Status** page to:
    - Initialize or re‑initialize from CSV or manual table.
    - Add cash and position trades.
    - Maintain watchlist tickers and edit targets/max weights.
- **2. Use CLI for scripting / batch work**
  - `mw init` – initialize from a CSV (Symbol, Quantity, Cost Price).
  - `mw add` – add cash or position trades.
  - `mw trade` – record generic trades (options/swing PnL applied to cash).
  - `mw config set-target` – edit targets and max weights from the shell.
  - `mw status`, `mw whatsup`, `mw invest` – text summaries equivalent to the UI analytics.

Both UI and CLI write the same types of events into `ledger.jsonl`, so you can mix them freely.

---

### Key CLI commands (summary)

- `mw ui`  
  Launch the Streamlit dashboard for the current (or named) portfolio.

- `mw init PATH_TO_CSV [--name NAME] [--dir PATH]`  
  Initialize a portfolio from a CSV file. A row with `Symbol = CASH` is treated as cash balance (not a position).

- `mw add SYMBOL UNITS COST_BASIS [--portfolio NAME] [--dir PATH]`  
  Add a position trade. Use `mw add cash AMOUNT` for deposits/withdrawals.

- `mw trade CASH_NEEDED DURATION PNL [--note ...] [--date ...]`  
  Record generic trades whose realized PnL should hit cash on a specific date.

- `mw config set-target SYMBOL [--buy ...] [--sell ...] [--intrinsic ...] [--max-weight ...]`  
  Maintain per‑symbol config (targets, intrinsic value, max weight).

- `mw status`  
  Show a minimal CLI summary (positions + cash) for the current portfolio.

- `mw whatsup [--lookback-days N]`  
  Show recent moves and extremeness for portfolio + market symbols.

- `mw invest AMOUNT [--lookback-years Y]`  
  Suggest tickers based on approximate volatility impact of deploying new cash, respecting configured max weights.

- `mw reset [--yes]`  
  Wipe `ledger.jsonl`, `config.json`, and `price_cache/` for a portfolio so you can start over.

---

### Running tests

With the development environment active:

```bash
pytest
```

This runs unit tests for events/ledger, paths/reset, snapshot/status, analytics, timeline/baselines (including split handling), and provider behavior.  
One Yahoo‑specific provider test is skipped automatically if `yfinance` is not installed.


