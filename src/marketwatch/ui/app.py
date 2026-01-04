from __future__ import annotations

from pathlib import Path
from typing import Iterable
from datetime import datetime, date as _date
import csv
import io
import math
import shutil
import uuid

import streamlit as st

from marketwatch.core.analytics import (
    compute_invest_suggestions,
    compute_whatsup,
    filter_invest_rows_by_max_weight,
)
from marketwatch.core.timeline import build_daily_series
from marketwatch.core.events import Event
from marketwatch.core.state import build_snapshot
from marketwatch.prices.yahoo import YahooPriceProvider
from marketwatch.storage.config import Config, load_config, save_config
from marketwatch.storage.ledger import read_events, append_events


def _portfolio_dir_from_arg() -> Path | None:
    import sys

    if len(sys.argv) >= 2:
        return Path(sys.argv[1]).expanduser()
    return None


def _load_snapshot_and_config(portfolio_dir: Path):
    ledger_path = portfolio_dir / "ledger.jsonl"
    events = list(read_events(ledger_path))
    snapshot = build_snapshot(events)
    config = load_config(portfolio_dir / "config.json")
    return snapshot, config


def _reinitialize_portfolio(
    portfolio_dir: Path,
    positions: list[dict[str, object]],
    as_of: _date,
) -> None:
    ledger_path = portfolio_dir / "ledger.jsonl"
    config_path = portfolio_dir / "config.json"
    cache_dir = portfolio_dir / "price_cache"

    if ledger_path.exists():
        ledger_path.unlink()
    if config_path.exists():
        config_path.unlink()
    if cache_dir.exists() and cache_dir.is_dir():
        shutil.rmtree(cache_dir)

    events: list[Event] = []
    timestamp = datetime(as_of.year, as_of.month, as_of.day)
    for row in positions:
        symbol = str(row.get("Symbol") or "").strip()
        if not symbol:
            continue
        try:
            quantity = float(row.get("Quantity"))  # type: ignore[arg-type]
            cost_price = float(row.get("Cost Price"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if math.isnan(quantity) or math.isnan(cost_price):
            continue
        if quantity == 0.0 or cost_price <= 0.0:
            continue
        if symbol.upper() == "CASH":
            amount = quantity * cost_price
            events.append(
                Event(
                    id=str(uuid.uuid4()),
                    timestamp=timestamp,
                    type="cash_movement",
                    payload={"amount": amount},
                )
            )
        else:
            events.append(
                Event(
                    id=str(uuid.uuid4()),
                    timestamp=timestamp,
                    type="init_position",
                    payload={
                        "symbol": symbol,
                        "quantity": quantity,
                        "cost_price": cost_price,
                    },
                )
            )

    if events:
        append_events(ledger_path, events)

    config = Config(name=portfolio_dir.name)
    save_config(config_path, config)


def _status_page(portfolio_dir: Path) -> None:
    snapshot, config = _load_snapshot_and_config(portfolio_dir)
    provider = YahooPriceProvider(cache_dir=portfolio_dir / "price_cache")
    st.header("Status")
    st.write(f"Portfolio directory: `{portfolio_dir}`")

    st.subheader("Positions and watchlist")
    if not snapshot.positions and (config is None or not config.symbols):
        st.info("No positions or watchlist tickers yet.")
    else:
        # Compute approximate current prices and weights for held positions.
        last_prices: dict[str, float] = {}
        default_max_weight_pct: float | None = (
            config.default_max_weight * 100.0 if config is not None else None
        )
        total_value = snapshot.cash
        today = _date.today()
        start_price_window = _date(today.year, today.month, max(1, today.day - 10))
        for symbol, pos in snapshot.positions.items():
            if symbol.upper() == "CASH":
                continue
            ohlc = provider.get_ohlc(symbol, start_price_window, today)
            if not ohlc:
                continue
            last_close = ohlc[-1].close
            last_prices[symbol] = last_close
            total_value += pos.quantity * last_close

        rows: list[dict[str, object]] = []
        # Held positions.
        for symbol, pos in sorted(snapshot.positions.items()):
            if symbol.upper() == "CASH":
                continue
            cfg = config.symbols.get(symbol) if config is not None else None
            max_weight_pct: float | None
            if cfg is not None and cfg.max_weight is not None:
                max_weight_pct = cfg.max_weight * 100.0
            else:
                max_weight_pct = default_max_weight_pct
            price = last_prices.get(symbol)
            value = pos.quantity * price if price is not None else None
            weight_pct = (
                (value / total_value) * 100.0 if value is not None and total_value > 0 else None
            )
            rows.append(
                {
                    "Type": "Position",
                    "Symbol": symbol,
                    "Quantity": pos.quantity,
                    "Cost Basis": pos.cost_basis,
                    "Capital": value,
                    "Weight (%)": weight_pct,
                    "Buy Target": getattr(cfg, "buy_target", None),
                    "Sell Target": getattr(cfg, "sell_target", None),
                    "Intrinsic": getattr(cfg, "intrinsic_value", None),
                    "Max Weight": max_weight_pct,
                }
            )

        # Watchlist: symbols in config that are not currently held.
        watchlist_symbols: list[str] = []
        if config is not None:
            watchlist_symbols = sorted(
                sym for sym in config.symbols.keys() if sym not in snapshot.positions
            )
        for symbol in watchlist_symbols:
            cfg = config.symbols[symbol]
            if cfg.max_weight is not None:
                max_weight_pct = cfg.max_weight * 100.0
            else:
                max_weight_pct = default_max_weight_pct
            rows.append(
                {
                    "Type": "Watchlist",
                    "Symbol": symbol,
                    "Quantity": 0.0,
                    "Cost Basis": None,
                    "Capital": None,
                    "Weight (%)": None,
                    "Buy Target": cfg.buy_target,
                    "Sell Target": cfg.sell_target,
                    "Intrinsic": cfg.intrinsic_value,
                    "Max Weight": max_weight_pct,
                }
            )

        display_rows = [
            {
                "Type": row["Type"],
                "Symbol": row["Symbol"],
                "Quantity": row["Quantity"],
                "Cost Basis": row["Cost Basis"],
                "Capital": row["Capital"],
                "Weight (%)": row["Weight (%)"],
            }
            for row in rows
        ]

        st.dataframe(
            display_rows,
            hide_index=True,
            column_config={
                "Type": st.column_config.TextColumn(
                    "Type",
                    help="Whether this row is a held position or just a watchlist entry.",
                ),
                "Capital": st.column_config.NumberColumn(
                    "Capital",
                    help="Approximate market value invested in this ticker in USD.",
                ),
                "Weight (%)": st.column_config.NumberColumn(
                    "Weight (%)",
                    help="Approximate current portfolio weight for this position (including cash in denominator).",
                ),
            },
        )

        st.caption(
            "To add a pure watchlist ticker, either configure it in 'Edit targets and weights' "
            "with Quantity = 0, or use the form below."
        )

        st.subheader("Add watchlist ticker")
        with st.form("add_watchlist_form"):
            wl_symbol = st.text_input("Watchlist symbol").strip().upper()
            wl_note = st.text_input("Note (optional)", value="")
            submitted_wl = st.form_submit_button("Add to watchlist")

            if submitted_wl:
                if not wl_symbol:
                    st.error("Symbol is required.")
                else:
                    if config is None:
                        config = Config(name=portfolio_dir.name)
                    sym_cfg = config.symbols.get(wl_symbol)
                    if sym_cfg is None:
                        from marketwatch.storage.config import SymbolConfig

                        sym_cfg = SymbolConfig()
                        config.symbols[wl_symbol] = sym_cfg
                        # Apply global default max weight for new symbols.
                        sym_cfg.max_weight = config.default_max_weight
                    if wl_note:
                        sym_cfg.note = wl_note

                    save_config(portfolio_dir / "config.json", config)
                    event = Event(
                        id=str(uuid.uuid4()),
                        timestamp=datetime.utcnow(),
                        type="config_change",
                        payload={
                            "symbol": wl_symbol,
                            "buy_target": sym_cfg.buy_target,
                            "sell_target": sym_cfg.sell_target,
                            "intrinsic_value": sym_cfg.intrinsic_value,
                            "max_weight": sym_cfg.max_weight,
                        },
                        note=sym_cfg.note,
                    )
                    append_events(portfolio_dir / "ledger.jsonl", [event])
                    st.success(f"Added {wl_symbol} to watchlist.")
                    st.rerun()

        st.subheader("Edit targets and weights")

        original_rows = [
            {
                "Symbol": row["Symbol"],
                "Buy Target": row["Buy Target"],
                "Sell Target": row["Sell Target"],
                "Intrinsic": row["Intrinsic"],
                "Max Weight": row["Max Weight"],
            }
            for row in rows
            if row["Type"] in ("Position", "Watchlist")
        ]

        st.caption(
            "Hints: Buy/Sell/Intrinsic are prices in USD. "
            "Max Weight is entered as a percentage between 0 and 100 (e.g. 10 = 10%)."
        )

        edited = st.data_editor(
            original_rows,
            num_rows="fixed",
            hide_index=True,
            disabled=["Symbol"],
            key="config_editor",
            column_config={
                "Buy Target": st.column_config.NumberColumn(
                    "Buy Target",
                    help="Desired buy price in USD.",
                ),
                "Sell Target": st.column_config.NumberColumn(
                    "Sell Target",
                    help="Price in USD where you plan to trim or exit.",
                ),
                "Intrinsic": st.column_config.NumberColumn(
                    "Intrinsic",
                    help="Your estimate of fair value in USD.",
                ),
                "Max Weight": st.column_config.NumberColumn(
                    "Max Weight (%)",
                    help="Position limit as a percentage of portfolio (0–100). 10 means 10%.",
                    min_value=0.0,
                    max_value=100.0,
                ),
            },
        )

        def _to_optional_float(value: object) -> float | None:
            if value is None:
                return None
            if isinstance(value, (int, float)):
                if isinstance(value, float) and math.isnan(value):
                    return None
                return float(value)
            text = str(value).strip()
            if not text:
                return None
            try:
                parsed = float(text)
            except ValueError:
                return None
            return parsed

        if st.button("Save config changes"):
            # Streamlit may return a list of dicts or a DataFrame-like object.
            if isinstance(edited, list):
                edited_rows = edited
            else:
                # Assume pandas.DataFrame-like
                edited_rows = edited.to_dict(orient="records")  # type: ignore[no-untyped-call]

            changed = False
            if config is None:
                from marketwatch.storage.config import Config

                config = Config(name="default")

            for row in edited_rows:
                symbol = str(row["Symbol"])
                buy_target = _to_optional_float(row.get("Buy Target"))
                sell_target = _to_optional_float(row.get("Sell Target"))
                intrinsic_value = _to_optional_float(row.get("Intrinsic"))
                max_weight_pct = _to_optional_float(row.get("Max Weight"))
                max_weight = (
                    max_weight_pct / 100.0 if max_weight_pct is not None else None
                )

                sym_cfg = config.symbols.get(symbol)
                if sym_cfg is None:
                    from marketwatch.storage.config import SymbolConfig

                    sym_cfg = SymbolConfig()
                    config.symbols[symbol] = sym_cfg

                if (
                    sym_cfg.buy_target == buy_target
                    and sym_cfg.sell_target == sell_target
                    and sym_cfg.intrinsic_value == intrinsic_value
                    and sym_cfg.max_weight == max_weight
                ):
                    continue

                sym_cfg.buy_target = buy_target
                sym_cfg.sell_target = sell_target
                sym_cfg.intrinsic_value = intrinsic_value
                sym_cfg.max_weight = max_weight
                changed = True

                event = Event(
                    id=str(uuid.uuid4()),
                    timestamp=datetime.utcnow(),
                    type="config_change",
                    payload={
                        "symbol": symbol,
                        "buy_target": sym_cfg.buy_target,
                        "sell_target": sym_cfg.sell_target,
                        "intrinsic_value": sym_cfg.intrinsic_value,
                        "max_weight": sym_cfg.max_weight,
                    },
                    note=sym_cfg.note,
                )
                append_events(portfolio_dir / "ledger.jsonl", [event])

            if changed:
                save_config(portfolio_dir / "config.json", config)
                st.success("Configuration updated.")
                st.rerun()
            else:
                st.info("No changes to save.")

    st.subheader("Cash")
    st.metric("Cash balance", f"{snapshot.cash:,.2f} USD")

    st.subheader("Add cash or trade")
    col_add, col_generic = st.columns(2)

    # Left: mw add semantics (positions or cash).
    with col_add:
        st.markdown("**Add position or cash (`mw add`)**")
        with st.form("add_position_or_cash_form"):
            add_mode = st.radio(
                "Type",
                ["Position (ticker)", "Cash"],
                horizontal=True,
                key="add_mode",
            )
            add_date = st.date_input(
                "Date",
                value=_date.today(),
                key="add_date",
            )

            symbol = ""
            units = 0.0
            price = 0.0
            cash_amount = 0.0

            if add_mode == "Position (ticker)":
                symbol = st.text_input(
                    "Symbol",
                    key="add_symbol_position",
                ).strip().upper()
                units = st.number_input(
                    "Units (positive buy, negative sell)",
                    value=0.0,
                    help="Positive for buys, negative for sells.",
                    key="add_units_position",
                )
                price = st.number_input(
                    "Trade price per unit",
                    value=0.0,
                    help="Execution price per unit for this trade.",
                    key="add_price_position",
                )
            else:
                st.text_input(
                    "Symbol",
                    value="CASH",
                    disabled=True,
                    key="add_symbol_cash",
                )
                st.number_input(
                    "Trade price per unit",
                    value=1.0,
                    disabled=True,
                    help="Convention: CASH is priced at 1.0; enter only the amount.",
                    key="add_price_cash",
                )
                cash_amount = st.number_input(
                    "Amount (positive deposit, negative withdrawal)",
                    value=0.0,
                )

            add_note = st.text_input("Note", value="")
            submitted_add = st.form_submit_button("Add")

            if submitted_add:
                ts = datetime(
                    add_date.year,
                    add_date.month,
                    add_date.day,
                )
                if add_mode == "Position (ticker)":
                    if not symbol or units == 0.0 or price <= 0.0:
                        st.error("Symbol, non-zero units and positive price are required.")
                    else:
                        event = Event(
                            id=str(uuid.uuid4()),
                            timestamp=ts,
                            type="trade_add",
                            payload={
                                "symbol": symbol,
                                "quantity_delta": float(units),
                                "price": float(price),
                            },
                            note=add_note or None,
                        )
                        append_events(portfolio_dir / "ledger.jsonl", [event])
                        st.success("Position trade recorded.")
                        st.rerun()
                else:
                    if cash_amount == 0.0:
                        st.error("Non-zero amount required for cash movement.")
                    else:
                        event = Event(
                            id=str(uuid.uuid4()),
                            timestamp=ts,
                            type="cash_movement",
                            payload={"amount": float(cash_amount)},
                            note=add_note or None,
                        )
                        append_events(portfolio_dir / "ledger.jsonl", [event])
                        st.success("Cash movement recorded.")
                        st.rerun()

        st.caption(
            "CLI equivalents:\n"
            "- Position: `mw add SYMBOL UNITS COST_BASIS [--note ...]`\n"
            "- Cash: `mw add cash AMOUNT [--note ...]`\n"
            "The UI also lets you pick an explicit date for the event; the CLI "
            "version uses 'now' when no date is specified."
        )

    # Right: mw trade semantics (generic trades).
    with col_generic:
        st.markdown("**Add generic trade (`mw trade`)**")
        with st.form("add_generic_trade_form"):
            trade_date = st.date_input(
                "Close date",
                value=_date.today(),
                key="generic_trade_date",
            )
            cash_needed = st.number_input(
                "Cash needed (peak capital locked)",
                value=0.0,
                help="Approximate peak capital tied up in this trade or strategy.",
            )
            duration_days = st.number_input(
                "Duration (days)",
                min_value=0,
                step=1,
                value=0,
                help=(
                    "Number of days capital was tied up before this close date. "
                    "Used as metadata; PnL still hits cash on the close date."
                ),
            )
            pnl = st.number_input(
                "Realized PnL (USD at close date)",
                value=0.0,
            )

            trade_note = st.text_input("Note", value="")
            submitted_trade = st.form_submit_button("Add generic trade")

            if submitted_trade:
                ts = datetime(
                    trade_date.year,
                    trade_date.month,
                    trade_date.day,
                )
                if cash_needed <= 0.0 and pnl == 0.0:
                    st.error(
                        "Provide a positive cash_needed or non-zero PnL for generic trade."
                    )
                else:
                    duration_str = (
                        str(int(duration_days))
                        if isinstance(duration_days, (int, float)) and duration_days > 0
                        else ""
                    )
                    event = Event(
                        id=str(uuid.uuid4()),
                        timestamp=ts,
                        type="generic_trade",
                        payload={
                            "cash_needed": float(cash_needed),
                            "duration": duration_str,
                            "pnl": float(pnl),
                        },
                        note=trade_note or None,
                    )
                    append_events(portfolio_dir / "ledger.jsonl", [event])
                    st.success("Generic trade recorded.")
                    st.rerun()

        st.caption(
            "CLI equivalent:\n"
            "`mw trade CASH_NEEDED DURATION PNL [--note ...] [--date YYYY-MM-DD]`\n"
            "Here `CASH_NEEDED` is peak capital locked, `DURATION` is usually a "
            "number of days, and `--date` is the close date on which PnL hits cash."
        )

    st.subheader("Re-initialize portfolio")
    st.warning(
        "Re-initializing will delete all existing events and config for this "
        "portfolio and replace them with new initial positions."
    )
    init_date = st.date_input(
        "Initial state date (used as timestamp for positions)",
        value=_date.today(),
        key="init_date",
    )
    tab_csv, tab_manual = st.tabs(["From CSV", "Manual table"])

    with tab_csv:
        uploaded = st.file_uploader(
            "Initial positions CSV (columns: Symbol, Quantity, Cost Price)",
            type=["csv"],
            key="init_csv_file",
        )
        if st.button("Reinitialize from CSV"):
            if uploaded is None:
                st.error("Please upload a CSV file.")
            else:
                try:
                    text = uploaded.getvalue().decode("utf-8")
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Could not read uploaded file: {exc}")
                else:
                    reader = csv.DictReader(io.StringIO(text))
                    rows: list[dict[str, object]] = []
                    for row in reader:
                        rows.append(
                            {
                                "Symbol": row.get("Symbol", ""),
                                "Quantity": row.get("Quantity", ""),
                                "Cost Price": row.get("Cost Price", ""),
                            }
                        )
                    if not rows:
                        st.error("CSV did not contain any rows.")
                    else:
                        _reinitialize_portfolio(portfolio_dir, rows, as_of=init_date)
                        st.success("Portfolio re-initialized from CSV.")
                        st.rerun()

    with tab_manual:
        st.caption(
            "Enter one or more starting positions. Leave Symbol blank to ignore a row."
        )
        initial_rows = [
            {"Symbol": "", "Quantity": 0.0, "Cost Price": 0.0},
        ]
        table = st.data_editor(
            initial_rows,
            num_rows="dynamic",
            hide_index=True,
            key="init_manual_table",
        )
        if st.button("Reinitialize from table"):
            if hasattr(table, "to_dict"):
                rows = table.to_dict(orient="records")  # type: ignore[no-untyped-call]
            else:
                rows = table  # type: ignore[assignment]
            _reinitialize_portfolio(portfolio_dir, rows, as_of=init_date)  # type: ignore[arg-type]
            st.success("Portfolio re-initialized from manual table.")
            st.rerun()

    st.subheader("History vs baselines")
    bundle = build_daily_series(
        read_events(portfolio_dir / "ledger.jsonl"),
        provider=provider,
        fd_rate=config.fd_rate if config is not None else 0.05,
    )
    if bundle is None or not bundle.dates:
        st.info("Not enough data to build a history yet.")
        return

    chart_data = {
        "Date": bundle.dates,
        "Portfolio": bundle.portfolio,
        "SPY baseline": bundle.baseline_spy,
        "QQQ baseline": bundle.baseline_qqq,
        "Fixed deposit": bundle.baseline_fd,
    }
    st.line_chart(chart_data, x="Date")

    def _daily_returns(series: list[float]) -> list[float]:
        returns: list[float] = []
        for prev, curr in zip(series, series[1:]):
            if prev <= 0.0:
                continue
            returns.append(curr / prev - 1.0)
        return returns

    from statistics import pstdev

    port_rets = _daily_returns(bundle.portfolio)
    spy_rets = _daily_returns(bundle.baseline_spy)
    qqq_rets = _daily_returns(bundle.baseline_qqq)
    fd_rets = _daily_returns(bundle.baseline_fd)

    rows_summary = []
    for name, series, rets in [
        ("Portfolio", bundle.portfolio, port_rets),
        ("SPY baseline", bundle.baseline_spy, spy_rets),
        ("QQQ baseline", bundle.baseline_qqq, qqq_rets),
        ("Fixed deposit", bundle.baseline_fd, fd_rets),
    ]:
        if not series:
            continue
        start_val = series[0]
        end_val = series[-1]
        vol = pstdev(rets) if len(rets) > 1 else 0.0
        rows_summary.append(
            {
                "Series": name,
                "Start value": start_val,
                "End value": end_val,
                "Total return %": (end_val / start_val - 1.0) * 100.0
                if start_val > 0.0
                else 0.0,
                "Daily volatility %": vol * 100.0,
            }
        )

    st.subheader("Summary vs baselines")
    st.dataframe(rows_summary, hide_index=True)


def _whatsup_page(portfolio_dir: Path) -> None:
    snapshot, config = _load_snapshot_and_config(portfolio_dir)
    st.header("What's Up")
    st.caption(
        "Shows how extreme the latest daily move is relative to recent history, "
        "for both portfolio tickers and a small market dashboard."
    )
    default_lookback = (
        getattr(config, "whatsup_lookback_days", 252) if config is not None else 252
    )
    lookback_days = st.sidebar.number_input(
        "Lookback days", min_value=30, max_value=2000, value=default_lookback
    )
    provider = YahooPriceProvider(cache_dir=portfolio_dir / "price_cache")
    market_symbols = ["SPY", "QQQ", "GLD", "SLV", "XLF", "XLE"]
    rows = compute_whatsup(
        snapshot=snapshot,
        symbols_extra=market_symbols,
        provider=provider,
        lookback_days=lookback_days,
    )
    if not rows:
        st.info("No sufficient price data.")
        return

    portfolio_symbols = set(snapshot.positions.keys())
    if config is not None:
        portfolio_symbols.update(config.symbols.keys())

    portfolio_rows: list[dict[str, object]] = []
    market_rows: list[dict[str, object]] = []
    for row in rows:
        row_dict = {
            "Symbol": row.symbol,
            "Last 1d %": row.last_return * 100.0,
            "Avg 21d %": row.avg_21d_return * 100.0,
            "Quantile": row.quantile,
            "Extremeness": row.extremeness,
        }
        if row.symbol in portfolio_symbols:
            portfolio_rows.append(row_dict)
        else:
            market_rows.append(row_dict)

    st.subheader("Portfolio tickers")
    if portfolio_rows:
        st.dataframe(portfolio_rows, hide_index=True)
    else:
        st.info("No portfolio tickers with sufficient history yet.")

    st.subheader("Market dashboard")
    st.dataframe(market_rows, hide_index=True)


def _invest_page(portfolio_dir: Path) -> None:
    snapshot, config = _load_snapshot_and_config(portfolio_dir)
    st.header("Invest")
    st.caption(
        "Simulates the impact of deploying new cash into each ticker, approximating "
        "how much it would change your portfolio's volatility based on historical data."
    )
    amount = st.sidebar.number_input("Amount to deploy (USD)", min_value=0.0, value=1000.0)
    default_lookback_years = (
        getattr(config, "invest_lookback_years", 5) if config is not None else 5
    )
    lookback_years = st.sidebar.number_input(
        "Lookback years", min_value=1, max_value=20, value=default_lookback_years
    )
    universe_choice = st.sidebar.radio(
        "Universe",
        ["Positions only", "Positions + watchlist"],
        index=1,
    )

    if amount <= 0.0:
        st.info("Enter an amount greater than zero.")
        return

    # Optionally extend universe with watchlist tickers at zero quantity.
    snapshot_for_invest = snapshot
    if universe_choice == "Positions + watchlist" and config is not None:
        from marketwatch.core.state import Position, PortfolioSnapshot

        positions_ext = dict(snapshot.positions)
        for sym in config.symbols.keys():
            if sym not in positions_ext:
                positions_ext[sym] = Position(symbol=sym, quantity=0.0, total_cost=0.0)
        snapshot_for_invest = PortfolioSnapshot(positions=positions_ext, cash=snapshot.cash)

    provider = YahooPriceProvider(cache_dir=portfolio_dir / "price_cache")
    rows = compute_invest_suggestions(
        snapshot=snapshot_for_invest,
        provider=provider,
        amount=amount,
        lookback_years=int(lookback_years),
    )
    if config is not None:
        max_weights: dict[str, float] = {
            sym: cfg.max_weight
            for sym, cfg in config.symbols.items()
            if cfg.max_weight is not None
        }
        rows = filter_invest_rows_by_max_weight(
            rows=rows,
            snapshot=snapshot_for_invest,
            provider=provider,
            amount=amount,
            max_weights=max_weights,
            default_max_weight=config.default_max_weight,
        )
    if not rows:
        st.info("Not enough data to compute suggestions.")
        return

    table_rows = []
    for row in rows:
        cfg = config.symbols.get(row.symbol) if config is not None else None
        max_weight_pct: float | None
        if cfg is not None and cfg.max_weight is not None:
            max_weight_pct = cfg.max_weight * 100.0
        elif config is not None:
            max_weight_pct = config.default_max_weight * 100.0
        else:
            max_weight_pct = None
        table_rows.append(
            {
                "Symbol": row.symbol,
                "Avg daily %": row.avg_daily_return * 100.0,
                "Symbol vol %": row.volatility * 100.0,
                "Combined vol %": row.combined_volatility * 100.0,
                "Vol change %": row.vol_change * 100.0,
                "Buy Target": getattr(cfg, "buy_target", None),
                "Intrinsic": getattr(cfg, "intrinsic_value", None),
                "Max Weight (%)": max_weight_pct,
            }
        )
    st.dataframe(
        table_rows,
        hide_index=True,
        column_config={
            "Vol change %": st.column_config.NumberColumn(
                "Vol change %",
                help="Approximate change to portfolio daily volatility if you deploy this amount into the ticker (negative is good).",
            )
        },
    )


def _log_page(portfolio_dir: Path) -> None:
    st.header("Event Log")
    ledger_path = portfolio_dir / "ledger.jsonl"
    events = list(read_events(ledger_path))
    rows = []
    for ev in events[-200:]:
        rows.append(
            {
                "id": ev.id,
                "timestamp": ev.timestamp.isoformat(),
                "type": ev.type,
                "payload": ev.payload,
                "note": ev.note,
            }
        )
    st.dataframe(rows, hide_index=True)


def _config_page(portfolio_dir: Path) -> None:
    st.header("Config")
    snapshot, config = _load_snapshot_and_config(portfolio_dir)
    if config is None:
        st.info("No config found.")
        return

    # Backwards compatibility for configs created before global fields existed.
    if not hasattr(config, "default_max_weight"):
        config.default_max_weight = 0.05
    if not hasattr(config, "whatsup_lookback_days"):
        config.whatsup_lookback_days = 252
    if not hasattr(config, "invest_lookback_years"):
        config.invest_lookback_years = 5

    st.subheader("Global settings")
    with st.form("global_config_form"):
        fd_rate = st.number_input(
            "Fixed deposit annual rate (fraction, e.g. 0.05 for 5%)",
            min_value=0.0,
            max_value=1.0,
            value=float(getattr(config, "fd_rate", 0.05)),
        )
        default_max_weight_pct = st.number_input(
            "Default max weight (%)",
            min_value=0.0,
            max_value=100.0,
            value=float(getattr(config, "default_max_weight", 0.05) * 100.0),
            help="Used as the initial max weight for new symbols.",
        )
        whatsup_days = st.number_input(
            "What's Up: default lookback days",
            min_value=30,
            max_value=2000,
            value=int(getattr(config, "whatsup_lookback_days", 252)),
        )
        invest_years = st.number_input(
            "Invest: default lookback years",
            min_value=1,
            max_value=20,
            value=int(getattr(config, "invest_lookback_years", 5)),
        )
        submitted_global = st.form_submit_button("Save global config")

    if submitted_global:
        config.fd_rate = float(fd_rate)
        config.default_max_weight = float(default_max_weight_pct) / 100.0
        config.whatsup_lookback_days = int(whatsup_days)
        config.invest_lookback_years = int(invest_years)
        save_config(portfolio_dir / "config.json", config)
        event = Event(
            id=str(uuid.uuid4()),
            timestamp=datetime.utcnow(),
            type="config_change",
            payload={
                "symbol": "",
                "fd_rate": config.fd_rate,
                "default_max_weight": config.default_max_weight,
                "whatsup_lookback_days": config.whatsup_lookback_days,
                "invest_lookback_years": config.invest_lookback_years,
            },
            note="Updated global config via UI.",
        )
        append_events(portfolio_dir / "ledger.jsonl", [event])
        st.success("Global configuration updated.")
        st.rerun()

    st.subheader("Per-symbol config")
    st.caption(
        "Union of configured symbols and current positions. "
        "Watchlist entries are those with zero quantity."
    )

    symbols_all: set[str] = set(snapshot.positions.keys())
    symbols_all.update(config.symbols.keys())

    rows = []
    for symbol in sorted(symbols_all):
        cfg = config.symbols.get(symbol)
        max_weight_pct: float | None
        note: str | None
        buy_target = None
        sell_target = None
        intrinsic = None
        if cfg is not None:
            buy_target = cfg.buy_target
            sell_target = cfg.sell_target
            intrinsic = cfg.intrinsic_value
            max_weight_pct = cfg.max_weight * 100.0 if cfg.max_weight is not None else None
            note = cfg.note
        else:
            max_weight_pct = None
            note = None
        qty = snapshot.positions.get(symbol).quantity if symbol in snapshot.positions else 0.0
        rows.append(
            {
                "Symbol": symbol,
                "Quantity": qty,
                "Buy Target": buy_target,
                "Sell Target": sell_target,
                "Intrinsic": intrinsic,
                "Max Weight (%)": max_weight_pct,
                "Note": note,
            }
        )

    st.dataframe(rows, hide_index=True)


def main(portfolio_dir: str | Path | None = None) -> None:
    st.set_page_config(page_title="MarketWatch", layout="wide")
    portfolio_path: Path | None = (
        Path(portfolio_dir) if portfolio_dir is not None else _portfolio_dir_from_arg()
    )
    if portfolio_path is None:
        st.error("Portfolio directory must be provided as an argument.")
        return

    st.sidebar.title("MarketWatch")
    page = st.sidebar.radio(
        "Page",
        ["Status", "What's Up", "Invest", "Log", "Config"],
    )

    if page == "Status":
        _status_page(portfolio_path)
    elif page == "What's Up":
        _whatsup_page(portfolio_path)
    elif page == "Invest":
        _invest_page(portfolio_path)
    elif page == "Log":
        _log_page(portfolio_path)
    elif page == "Config":
        _config_page(portfolio_path)


if __name__ == "__main__":
    main()


