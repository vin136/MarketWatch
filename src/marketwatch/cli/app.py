from __future__ import annotations

from datetime import datetime, date
from pathlib import Path
from typing import Optional
import csv
import uuid
import shutil

import typer

from marketwatch.core.events import Event
from marketwatch.core.state import build_snapshot
from marketwatch.core.analytics import (
    compute_whatsup,
    compute_invest_suggestions,
    filter_invest_rows_by_max_weight,
)
from marketwatch.storage.config import Config, SymbolConfig, save_config, load_config
from marketwatch.storage.ledger import append_events, read_events
from marketwatch.storage.paths import (
    get_base_dir,
    get_portfolio_dir,
    set_current_portfolio_dir,
)
from marketwatch.prices.yahoo import YahooPriceProvider


app = typer.Typer(help="MarketWatch CLI")


def _parse_date(date_str: str | None) -> datetime:
    if not date_str:
        return datetime.utcnow()
    try:
        d = date.fromisoformat(date_str)
    except ValueError as exc:
        msg = f"Invalid date format: {date_str!r}, expected YYYY-MM-DD"
        raise typer.BadParameter(msg) from exc
    return datetime(d.year, d.month, d.day)


@app.command()
def init(
    csv_file: Path = typer.Argument(..., exists=True, readable=True),
    name: str = typer.Option("main", help="Portfolio name."),
    directory: Optional[Path] = typer.Option(
        None,
        "--dir",
        help="Directory to store portfolio data (defaults to ~/.marketwatch/<name>).",
    ),
) -> None:
    """Initialize a new portfolio from a CSV file."""
    portfolio_dir = get_portfolio_dir(name=name, directory=directory)
    ledger_path = portfolio_dir / "ledger.jsonl"
    config_path = portfolio_dir / "config.json"

    events: list[Event] = []
    timestamp = datetime.utcnow()

    with csv_file.open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            symbol = (row.get("Symbol") or "").strip()
            if not symbol:
                continue
            quantity_str = (row.get("Quantity") or "").replace(",", "").strip()
            cost_str = (row.get("Cost Price") or "").replace(",", "").strip()
            if not quantity_str or not cost_str:
                continue
            quantity = float(quantity_str)
            cost_price = float(cost_str)
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
                event = Event(
                    id=str(uuid.uuid4()),
                    timestamp=timestamp,
                    type="init_position",
                    payload={
                        "symbol": symbol,
                        "quantity": quantity,
                        "cost_price": cost_price,
                    },
                )
                events.append(event)

    append_events(ledger_path, events)

    config = Config(name=name)
    save_config(config_path, config)

    set_current_portfolio_dir(portfolio_dir)
    typer.echo(f"Initialized portfolio '{name}' in {portfolio_dir}")
    typer.echo("This portfolio is now the current portfolio.")


@app.command()
def add(
    symbol: str = typer.Argument(..., help="Ticker symbol or 'cash'."),
    units: float = typer.Argument(..., help="Units to add (or cash amount)."),
    cost_basis: Optional[float] = typer.Argument(
        None,
        help="Cost basis per unit (ignored for cash).",
    ),
    portfolio: Optional[str] = typer.Option(
        None,
        "--portfolio",
        "-p",
        help="Portfolio name (defaults to current portfolio).",
    ),
    directory: Optional[Path] = typer.Option(
        None,
        "--dir",
        help="Portfolio directory (defaults to ~/.marketwatch/<portfolio>).",
    ),
    note: Optional[str] = typer.Option(None, "--note", help="Optional note."),
) -> None:
    """Add a position change or cash movement."""
    try:
        portfolio_dir = get_portfolio_dir(name=portfolio, directory=directory)
    except RuntimeError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1)
    ledger_path = portfolio_dir / "ledger.jsonl"

    timestamp = datetime.utcnow()

    events: list[Event] = []
    if symbol.lower() == "cash":
        event = Event(
            id=str(uuid.uuid4()),
            timestamp=timestamp,
            type="cash_movement",
            payload={"amount": units},
            note=note,
        )
        events.append(event)
    else:
        if cost_basis is None:
            raise typer.BadParameter("COST_BASIS is required for non-cash symbols.")
        event = Event(
            id=str(uuid.uuid4()),
            timestamp=timestamp,
            type="trade_add",
            payload={
                "symbol": symbol,
                "quantity_delta": units,
                "price": cost_basis,
            },
            note=note,
        )
        events.append(event)

    append_events(ledger_path, events)
    typer.echo(f"Recorded event(s) for portfolio '{portfolio}'.")


@app.command()
def trade(
    cash_needed: float = typer.Argument(
        ...,
        help="Peak cash used for the trade or strategy.",
    ),
    duration: str = typer.Argument(
        ...,
        help="Duration string, for example '7d' or '30d'.",
    ),
    pnl: float = typer.Argument(
        ...,
        help="Realized profit or loss in USD.",
    ),
    date_str: Optional[str] = typer.Option(
        None,
        "--date",
        help="Date of trade close (YYYY-MM-DD). Defaults to today (UTC).",
    ),
    note: Optional[str] = typer.Option(
        None,
        "--note",
        help="Optional note.",
    ),
    portfolio: Optional[str] = typer.Option(
        None,
        "--portfolio",
        "-p",
        help="Portfolio name (defaults to current portfolio).",
    ),
    directory: Optional[Path] = typer.Option(
        None,
        "--dir",
        help="Portfolio directory (defaults to ~/.marketwatch/<portfolio> or current).",
    ),
) -> None:
    """Record a generic trade with realized PnL that affects cash."""
    try:
        portfolio_dir = get_portfolio_dir(name=portfolio, directory=directory)
    except RuntimeError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1)

    ledger_path = portfolio_dir / "ledger.jsonl"
    timestamp = _parse_date(date_str)

    event = Event(
        id=str(uuid.uuid4()),
        timestamp=timestamp,
        type="generic_trade",
        payload={
            "cash_needed": cash_needed,
            "duration": duration,
            "pnl": pnl,
        },
        note=note,
    )
    append_events(ledger_path, [event])
    typer.echo("Recorded generic trade event.")


config_app = typer.Typer(help="Configuration commands.")
app.add_typer(config_app, name="config")


@config_app.command("set-target")
def config_set_target(
    symbol: str = typer.Argument(..., help="Ticker symbol to configure."),
    buy: Optional[float] = typer.Option(
        None,
        "--buy",
        help="Buy target price.",
    ),
    sell: Optional[float] = typer.Option(
        None,
        "--sell",
        help="Sell/trim target price.",
    ),
    intrinsic: Optional[float] = typer.Option(
        None,
        "--intrinsic",
        help="Intrinsic value estimate.",
    ),
    max_weight: Optional[float] = typer.Option(
        None,
        "--max-weight",
        help="Maximum portfolio weight (e.g. 0.10 for 10%%).",
    ),
    note: Optional[str] = typer.Option(
        None,
        "--note",
        help="Optional note for this symbol.",
    ),
    portfolio: Optional[str] = typer.Option(
        None,
        "--portfolio",
        "-p",
        help="Portfolio name (defaults to current portfolio).",
    ),
    directory: Optional[Path] = typer.Option(
        None,
        "--dir",
        help="Portfolio directory (defaults to ~/.marketwatch/<portfolio> or current).",
    ),
) -> None:
    """Update per-symbol configuration such as targets and max weight."""
    try:
        portfolio_dir = get_portfolio_dir(name=portfolio, directory=directory)
    except RuntimeError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1)

    config_path = portfolio_dir / "config.json"
    ledger_path = portfolio_dir / "ledger.jsonl"

    config = load_config(config_path)
    if config is None:
        config = Config(name=portfolio or "main")

    sym_cfg = config.symbols.get(symbol)
    if sym_cfg is None:
        sym_cfg = SymbolConfig()
        config.symbols[symbol] = sym_cfg

    if buy is not None:
        sym_cfg.buy_target = buy
    if sell is not None:
        sym_cfg.sell_target = sell
    if intrinsic is not None:
        sym_cfg.intrinsic_value = intrinsic
    if max_weight is not None:
        sym_cfg.max_weight = max_weight
    if note is not None:
        sym_cfg.note = note

    save_config(config_path, config)

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
    append_events(ledger_path, [event])
    typer.echo(f"Updated configuration for {symbol}.")


@app.command()
def status(
    no_ui: bool = typer.Option(
        True,
        "--no-ui/--ui",
        help="Show CLI summary only (UI not yet implemented).",
    ),
    portfolio: Optional[str] = typer.Option(
        None,
        "--portfolio",
        "-p",
        help="Portfolio name (defaults to current portfolio).",
    ),
    directory: Optional[Path] = typer.Option(
        None,
        "--dir",
        help="Portfolio directory (defaults to ~/.marketwatch/<portfolio> or current).",
    ),
) -> None:
    """Show a minimal status view with positions and cash."""
    try:
        portfolio_dir = get_portfolio_dir(name=portfolio, directory=directory)
    except RuntimeError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1)

    ledger_path = portfolio_dir / "ledger.jsonl"
    events = list(read_events(ledger_path))  # type: ignore[name-defined]
    snapshot = build_snapshot(events)

    typer.echo("Positions:")
    if not snapshot.positions:
        typer.echo("  (none)")
    else:
        typer.echo("  Symbol    Quantity    Cost Basis")
        for symbol in sorted(snapshot.positions):
            position = snapshot.positions[symbol]
            cost_basis = position.cost_basis
            cost_str = f"{cost_basis:.4f}" if cost_basis is not None else "-"
            typer.echo(
                f"  {symbol:<8} {position.quantity:>9.4f}    {cost_str:>10}"
            )

    typer.echo("")
    typer.echo(f"Cash: {snapshot.cash:.2f}")


@app.command()
def whatsup(
    lookback_days: int = typer.Option(
        252,
        "--lookback-days",
        help="Number of calendar days of history to consider.",
    ),
    portfolio: Optional[str] = typer.Option(
        None,
        "--portfolio",
        "-p",
        help="Portfolio name (defaults to current portfolio).",
    ),
    directory: Optional[Path] = typer.Option(
        None,
        "--dir",
        help="Portfolio directory (defaults to ~/.marketwatch/<portfolio> or current).",
    ),
) -> None:
    """Show recent moves and extremeness for portfolio and market tickers."""
    try:
        portfolio_dir = get_portfolio_dir(name=portfolio, directory=directory)
    except RuntimeError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1)

    ledger_path = portfolio_dir / "ledger.jsonl"
    events = list(read_events(ledger_path))
    snapshot = build_snapshot(events)

    provider = YahooPriceProvider(cache_dir=portfolio_dir / "price_cache")
    market_symbols = ["SPY", "QQQ", "GLD", "SLV", "XLF", "XLE"]
    rows = compute_whatsup(
        snapshot=snapshot,
        symbols_extra=market_symbols,
        provider=provider,
        lookback_days=lookback_days,
    )

    if not rows:
        typer.echo("No sufficient price data to compute metrics.")
        raise typer.Exit(code=0)

    typer.echo(
        "Symbol    Last 1d %   Avg 21d %   Quantile   Extremeness"
    )
    for row in rows:
        last_pct = row.last_return * 100.0
        avg_pct = row.avg_21d_return * 100.0
        q = row.quantile if row.quantile is not None else float("nan")
        e = row.extremeness if row.extremeness is not None else float("nan")
        typer.echo(
            f"{row.symbol:<8} {last_pct:>9.2f} {avg_pct:>10.2f} "
            f"{q:>9.3f} {e:>11.3f}"
        )


@app.command()
def invest(
    amount: float = typer.Argument(
        ...,
        help="Cash amount you plan to deploy.",
    ),
    lookback_years: int = typer.Option(
        5,
        "--lookback-years",
        help="Historical lookback in years.",
    ),
    portfolio: Optional[str] = typer.Option(
        None,
        "--portfolio",
        "-p",
        help="Portfolio name (defaults to current portfolio).",
    ),
    directory: Optional[Path] = typer.Option(
        None,
        "--dir",
        help="Portfolio directory (defaults to ~/.marketwatch/<portfolio> or current).",
    ),
) -> None:
    """Suggest tickers based on approximate volatility impact of deploying new cash."""
    try:
        portfolio_dir = get_portfolio_dir(name=portfolio, directory=directory)
    except RuntimeError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1)

    ledger_path = portfolio_dir / "ledger.jsonl"
    events = list(read_events(ledger_path))
    snapshot = build_snapshot(events)

    provider = YahooPriceProvider(cache_dir=portfolio_dir / "price_cache")
    rows = compute_invest_suggestions(
        snapshot=snapshot,
        provider=provider,
        amount=amount,
        lookback_years=lookback_years,
    )

    # Respect configured max weights where possible.
    config_path = portfolio_dir / "config.json"
    config = load_config(config_path)
    if config is not None:
        max_weights: dict[str, float] = {
            sym: cfg.max_weight
            for sym, cfg in config.symbols.items()
            if cfg.max_weight is not None
        }
        rows = filter_invest_rows_by_max_weight(
            rows=rows,
            snapshot=snapshot,
            provider=provider,
            amount=amount,
            max_weights=max_weights,
            default_max_weight=config.default_max_weight,
        )

    if not rows:
        typer.echo(
            "Not enough data to compute invest suggestions (or all candidates "
            "would breach their max weights)."
        )
        raise typer.Exit(code=0)

    typer.echo(
        "Symbol    Avg daily %   Vol %     Combined vol %   Vol change %"
    )
    for row in rows:
        avg_pct = row.avg_daily_return * 100.0
        vol_pct = row.volatility * 100.0
        comb_pct = row.combined_volatility * 100.0
        delta_pct = row.vol_change * 100.0
        typer.echo(
            f"{row.symbol:<8} {avg_pct:>11.3f} {vol_pct:>8.3f} "
            f"{comb_pct:>15.3f} {delta_pct:>12.3f}"
        )


@app.command()
def reset(
    portfolio: Optional[str] = typer.Option(
        None,
        "--portfolio",
        "-p",
        help="Portfolio name to reset (defaults to current portfolio).",
    ),
    directory: Optional[Path] = typer.Option(
        None,
        "--dir",
        help="Portfolio directory (defaults to ~/.marketwatch/<portfolio> or current).",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Confirm reset without interactive prompt.",
    ),
) -> None:
    """Delete ledger/config for a portfolio so it can be re-initialized."""
    try:
        portfolio_dir = get_portfolio_dir(name=portfolio, directory=directory)
    except RuntimeError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1)

    if not yes:
        confirm = typer.confirm(
            f"Reset portfolio at {portfolio_dir}? This deletes ledger/config.",
            default=False,
        )
        if not confirm:
            raise typer.Exit(code=0)

    ledger_path = portfolio_dir / "ledger.jsonl"
    config_path = portfolio_dir / "config.json"
    cache_dir = portfolio_dir / "price_cache"

    if ledger_path.exists():
        ledger_path.unlink()
    if config_path.exists():
        config_path.unlink()
    if cache_dir.exists() and cache_dir.is_dir():
        shutil.rmtree(cache_dir)

    typer.echo(f"Reset portfolio data in {portfolio_dir}. You can run 'mw init' again.")


@app.command()
def ui(
    portfolio: Optional[str] = typer.Option(
        None,
        "--portfolio",
        "-p",
        help="Portfolio name (defaults to current portfolio).",
    ),
    directory: Optional[Path] = typer.Option(
        None,
        "--dir",
        help="Portfolio directory (defaults to ~/.marketwatch/<portfolio> or current).",
    ),
) -> None:
    """Launch the Streamlit UI for the current portfolio."""
    try:
        portfolio_dir = get_portfolio_dir(name=portfolio, directory=directory)
    except RuntimeError:
        base_dir = get_base_dir()
        # If user passed a portfolio name, honor it; otherwise default to "main".
        name = portfolio or "main"
        portfolio_dir = base_dir / name
        portfolio_dir.mkdir(parents=True, exist_ok=True)
        config_path = portfolio_dir / "config.json"
        if not config_path.exists():
            cfg = Config(name=name)
            save_config(config_path, cfg)
        set_current_portfolio_dir(portfolio_dir)
        typer.echo(
            f"No current portfolio was set. Created/selected '{name}' at {portfolio_dir}."
        )

    import subprocess
    import sys
    from pathlib import Path as _Path
    import marketwatch.ui.app as ui_app  # type: ignore[import-not-found]

    script_path = _Path(ui_app.__file__).resolve()
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(script_path),
        "--",
        str(portfolio_dir),
    ]
    typer.echo("Launching Streamlit UI...")
    subprocess.run(cmd, check=False)


@app.command()
def edit(
    last: int = typer.Option(
        5,
        "--last",
        help="Consider the last N events for editing.",
    ),
    portfolio: Optional[str] = typer.Option(
        None,
        "--portfolio",
        "-p",
        help="Portfolio name (defaults to current portfolio).",
    ),
    directory: Optional[Path] = typer.Option(
        None,
        "--dir",
        help="Portfolio directory (defaults to ~/.marketwatch/<portfolio> or current).",
    ),
) -> None:
    """Interactively invalidate one of the last events."""
    try:
        portfolio_dir = get_portfolio_dir(name=portfolio, directory=directory)
    except RuntimeError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1)

    ledger_path = portfolio_dir / "ledger.jsonl"
    events = list(read_events(ledger_path))
    if not events:
        typer.echo("No events to edit.")
        raise typer.Exit(code=0)

    tail = events[-last:] if last > 0 else events
    typer.echo("Recent events:")
    for idx, event in enumerate(tail):
        typer.echo(
            f"[{idx}] {event.id} {event.timestamp.isoformat()} "
            f"{event.type} {event.payload}"
        )

    choice = typer.prompt(
        "Enter index of event to invalidate (or blank to cancel)",
        default="",
    )
    if not choice.strip():
        typer.echo("Edit cancelled.")
        raise typer.Exit(code=0)

    try:
        index = int(choice)
    except ValueError:
        typer.echo("Invalid index.")
        raise typer.Exit(code=1)

    if index < 0 or index >= len(tail):
        typer.echo("Index out of range.")
        raise typer.Exit(code=1)

    target = tail[index]
    correction = Event(
        id=str(uuid.uuid4()),
        timestamp=datetime.utcnow(),
        type="correction",
        payload={
            "target_event_id": target.id,
            "correction_type": "invalidate",
            "new_payload": None,
        },
    )
    append_events(ledger_path, [correction])
    typer.echo(f"Invalidated event {target.id}.")


if __name__ == "__main__":
    app()


