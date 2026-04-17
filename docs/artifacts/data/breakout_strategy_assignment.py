from __future__ import annotations

import json
import math
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import shinybroker as sb


# -----------------------------
# User-facing strategy settings
# -----------------------------
INITIAL_CAPITAL = 100000.0
RISK_FREE_RATE = 0.02

TRAINING_DAYS = 252
TESTING_DAYS = 63
ATR_WINDOW = 14
POSITION_NOTIONAL = 100000.0

BREAKOUT_LOOKBACKS = [10, 20, 55]
STOP_LOSS_ATR_MULTIPLES = [1.5, 2.0]
PROFIT_TARGET_ATR_MULTIPLES = [2.0, 3.0]
MAX_HOLD_DAYS_CHOICES = [10, 15]

ASSET_UNIVERSE = ["SPY", "QQQ", "IWM", "XLE", "GLD", "TLT"]
DATA_START = "2022-01-01"

IBKR_HOST = "127.0.0.1"
IBKR_PORT = 7497
IBKR_CLIENT_ID = 733
IBKR_TIMEOUT = 5


BASE_DIR = Path("/Users/jinxin/Desktop/Fintech 533")
SITE_DIR = Path("/Users/jinxin/Desktop/my-website")

ARTIFACTS_DIR = SITE_DIR / "artifacts"
DATA_DIR = ARTIFACTS_DIR / "data"
TABLE_DIR = ARTIFACTS_DIR / "tables"
PLOT_DIR = ARTIFACTS_DIR / "plots"


@dataclass(frozen=True)
class StrategyParams:
    breakout_lookback: int
    atr_window: int
    stop_loss_atr_multiple: float
    profit_target_atr_multiple: float
    max_hold_days: int


def ensure_directories() -> None:
    for directory in [DATA_DIR, TABLE_DIR, PLOT_DIR]:
        directory.mkdir(parents=True, exist_ok=True)


def build_contract(symbol: str) -> sb.Contract:
    return sb.Contract(
        {
            "symbol": symbol,
            "secType": "STK",
            "exchange": "SMART",
            "currency": "USD",
        }
    )


def fetch_history_shinybroker(symbol: str, start_date: str) -> pd.DataFrame | None:
    contract = build_contract(symbol)
    try:
        response = sb.fetch_historical_data(
            contract=contract,
            durationStr="5 Y",
            barSizeSetting="1 day",
            whatToShow="Trades",
            useRTH=True,
            host=IBKR_HOST,
            port=IBKR_PORT,
            client_id=IBKR_CLIENT_ID,
            timeout=IBKR_TIMEOUT,
        )
    except Exception:
        return None

    if not isinstance(response, dict) or "hst_dta" not in response:
        return None

    data = response["hst_dta"].copy()
    if data.empty:
        return None

    data["date"] = pd.to_datetime(data["timestamp"])
    data = data.rename(
        columns={
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume",
        }
    )
    data = data[["date", "open", "high", "low", "close", "volume"]]
    data = data[data["date"] >= pd.Timestamp(start_date)].reset_index(drop=True)
    data["source"] = "shinybroker"
    return data


def fetch_history_yahoo(symbol: str, start_date: str) -> pd.DataFrame:
    period1 = int(pd.Timestamp(start_date).timestamp())
    period2 = int(pd.Timestamp.today().normalize().timestamp())
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{symbol}?period1={period1}&period2={period2}&interval=1d&includePrePost=false&events=div,splits"
    )
    response = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()

    payload = response.json()["chart"]["result"][0]
    timestamps = payload["timestamp"]
    quote = payload["indicators"]["quote"][0]
    data = pd.DataFrame(
        {
            "date": pd.to_datetime(timestamps, unit="s"),
            "open": quote["open"],
            "high": quote["high"],
            "low": quote["low"],
            "close": quote["close"],
            "volume": quote["volume"],
        }
    ).dropna()
    data = data[data["date"] >= pd.Timestamp(start_date)].reset_index(drop=True)
    data["source"] = "yahoo_fallback"
    return data


def load_asset_history(symbol: str, start_date: str = DATA_START) -> pd.DataFrame:
    data = fetch_history_shinybroker(symbol, start_date)
    if data is None or data.empty:
        data = fetch_history_yahoo(symbol, start_date)

    data = data.sort_values("date").reset_index(drop=True)
    data["symbol"] = symbol
    return data


def compute_atr(data: pd.DataFrame, window: int) -> pd.Series:
    prev_close = data["close"].shift(1)
    true_range = pd.concat(
        [
            data["high"] - data["low"],
            (data["high"] - prev_close).abs(),
            (data["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.rolling(window=window).mean()


def detect_breakouts(data: pd.DataFrame, breakout_lookback: int) -> pd.DataFrame:
    """
    Identify upside breakouts using a Donchian-style highest-high rule.

    A breakout is triggered when today's close is above the highest high from
    the prior `breakout_lookback` trading days. The rolling high is shifted by
    one day so the signal only uses information that would have been known at
    the close.
    """
    breakout_frame = data.copy()
    breakout_frame["rolling_high"] = (
        breakout_frame["high"].rolling(window=breakout_lookback).max().shift(1)
    )
    breakout_frame["breakout_signal"] = (
        breakout_frame["close"] > breakout_frame["rolling_high"]
    ) & breakout_frame["rolling_high"].notna()
    return breakout_frame


def annualized_sharpe(daily_returns: pd.Series, risk_free_rate: float) -> float:
    if daily_returns.empty:
        return 0.0
    excess_daily = daily_returns - risk_free_rate / 252.0
    std = excess_daily.std(ddof=1)
    if pd.isna(std) or std == 0:
        return 0.0
    return float(np.sqrt(252.0) * excess_daily.mean() / std)


def summarize_performance(ledger: pd.DataFrame, blotter: pd.DataFrame, risk_free_rate: float) -> dict[str, float]:
    daily_returns = ledger["daily_return"].fillna(0.0)
    if blotter.empty:
        trade_returns = pd.Series(dtype=float)
        wins = pd.DataFrame(columns=["pnl"])
        losses = pd.DataFrame(columns=["pnl"])
    else:
        trade_returns = blotter["return_pct"]
        wins = blotter[blotter["pnl"] > 0]
        losses = blotter[blotter["pnl"] < 0]

    equity_peak = ledger["portfolio_value"].cummax()
    drawdown = ledger["portfolio_value"] / equity_peak - 1.0

    metrics = {
        "total_return": float(ledger["portfolio_value"].iloc[-1] / ledger["portfolio_value"].iloc[0] - 1.0),
        "average_return_per_trade": float(trade_returns.mean()) if not trade_returns.empty else 0.0,
        "annualized_sharpe_ratio": annualized_sharpe(daily_returns, risk_free_rate),
        "max_drawdown": float(drawdown.min()) if not drawdown.empty else 0.0,
        "win_rate": float((blotter["pnl"] > 0).mean()) if not blotter.empty else 0.0,
        "profit_factor": float(wins["pnl"].sum() / abs(losses["pnl"].sum())) if not losses.empty else np.nan,
        "expectancy_dollars": float(blotter["pnl"].mean()) if not blotter.empty else 0.0,
        "number_of_trades": float(len(blotter)),
    }
    return metrics


def backtest_breakout_strategy(
    data: pd.DataFrame,
    params: StrategyParams,
    initial_capital: float = INITIAL_CAPITAL,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = detect_breakouts(data, params.breakout_lookback)
    frame["atr"] = compute_atr(frame, params.atr_window)
    frame = frame.dropna(subset=["atr", "rolling_high"]).reset_index(drop=True)

    cash = initial_capital
    shares = 0
    entry_price = None
    entry_date = None
    entry_atr = None
    entry_index = None
    stop_price = None
    target_price = None
    trade_id = 1

    blotter_rows: list[dict[str, Any]] = []
    ledger_rows: list[dict[str, Any]] = []

    pending_entry = False
    pending_exit_reason = None

    previous_portfolio_value = initial_capital

    for i, row in frame.iterrows():
        date = pd.Timestamp(row["date"])
        open_price = float(row["open"])
        close_price = float(row["close"])
        atr_value = float(row["atr"])

        if pending_exit_reason is not None and shares > 0:
            exit_price = open_price
            cash += shares * exit_price
            pnl = (exit_price - float(entry_price)) * shares
            return_pct = exit_price / float(entry_price) - 1.0
            blotter_rows.append(
                {
                    "trade_id": trade_id,
                    "symbol": str(row["symbol"]),
                    "direction": "Long",
                    "entry_timestamp": pd.Timestamp(entry_date),
                    "exit_timestamp": date,
                    "entry_price": float(entry_price),
                    "exit_price": exit_price,
                    "position_size": int(shares),
                    "outcome": pending_exit_reason,
                    "holding_days": int(i - int(entry_index)),
                    "atr_at_entry": float(entry_atr),
                    "stop_price": float(stop_price),
                    "profit_target": float(target_price),
                    "pnl": float(pnl),
                    "return_pct": float(return_pct),
                }
            )
            shares = 0
            entry_price = None
            entry_date = None
            entry_atr = None
            entry_index = None
            stop_price = None
            target_price = None
            trade_id += 1
            pending_exit_reason = None

        if pending_entry and shares == 0:
            new_shares = int(POSITION_NOTIONAL // open_price)
            if new_shares > 0:
                cash -= new_shares * open_price
                shares = new_shares
                entry_price = open_price
                entry_date = date
                entry_atr = atr_value
                entry_index = i
                stop_price = entry_price - params.stop_loss_atr_multiple * entry_atr
                target_price = entry_price + params.profit_target_atr_multiple * entry_atr
            pending_entry = False

        if shares == 0 and bool(row["breakout_signal"]):
            pending_entry = True
        elif shares > 0:
            holding_days = i - int(entry_index)
            close_below_stop = close_price <= float(stop_price)
            close_above_target = close_price >= float(target_price)
            timed_out = holding_days >= params.max_hold_days

            if close_below_stop:
                pending_exit_reason = "Stop-loss triggered"
            elif close_above_target:
                pending_exit_reason = "Successful"
            elif timed_out:
                pending_exit_reason = "Timed out"

        position_value = shares * close_price
        portfolio_value = cash + position_value
        daily_pnl = portfolio_value - previous_portfolio_value
        daily_return = daily_pnl / previous_portfolio_value if previous_portfolio_value else 0.0
        ledger_rows.append(
            {
                "date": date,
                "symbol": str(row["symbol"]),
                "cash": float(cash),
                "shares": int(shares),
                "close": close_price,
                "position_value": float(position_value),
                "portfolio_value": float(portfolio_value),
                "daily_pnl": float(daily_pnl),
                "daily_return": float(daily_return),
                "breakout_signal": bool(row["breakout_signal"]),
                "rolling_high": float(row["rolling_high"]),
                "atr": float(atr_value),
            }
        )
        previous_portfolio_value = portfolio_value

    if shares > 0:
        last_row = frame.iloc[-1]
        final_exit_price = float(last_row["close"])
        cash += shares * final_exit_price
        blotter_rows.append(
            {
                "trade_id": trade_id,
                "symbol": str(last_row["symbol"]),
                "direction": "Long",
                "entry_timestamp": pd.Timestamp(entry_date),
                "exit_timestamp": pd.Timestamp(last_row["date"]),
                "entry_price": float(entry_price),
                "exit_price": final_exit_price,
                "position_size": int(shares),
                "outcome": "Timed out",
                "holding_days": int(len(frame) - 1 - int(entry_index)),
                "atr_at_entry": float(entry_atr),
                "stop_price": float(stop_price),
                "profit_target": float(target_price),
                "pnl": float((final_exit_price - float(entry_price)) * shares),
                "return_pct": float(final_exit_price / float(entry_price) - 1.0),
            }
        )

    blotter = pd.DataFrame(blotter_rows)
    ledger = pd.DataFrame(ledger_rows)
    return blotter, ledger


def objective_score(metrics: dict[str, float], min_trades: int = 2) -> float:
    if metrics["number_of_trades"] < min_trades:
        return -1e9
    return metrics["annualized_sharpe_ratio"]


def optimize_parameters(train_data: pd.DataFrame) -> tuple[StrategyParams, dict[str, float]]:
    best_params = None
    best_metrics = None
    best_score = -1e18

    for breakout_lookback in BREAKOUT_LOOKBACKS:
        for stop_multiple in STOP_LOSS_ATR_MULTIPLES:
            for target_multiple in PROFIT_TARGET_ATR_MULTIPLES:
                for max_hold in MAX_HOLD_DAYS_CHOICES:
                    params = StrategyParams(
                        breakout_lookback=breakout_lookback,
                        atr_window=ATR_WINDOW,
                        stop_loss_atr_multiple=stop_multiple,
                        profit_target_atr_multiple=target_multiple,
                        max_hold_days=max_hold,
                    )
                    blotter, ledger = backtest_breakout_strategy(train_data, params)
                    if ledger.empty:
                        continue
                    metrics = summarize_performance(ledger, blotter, RISK_FREE_RATE)
                    score = objective_score(metrics)
                    if score > best_score:
                        best_score = score
                        best_params = params
                        best_metrics = metrics

    if best_params is None or best_metrics is None:
        raise RuntimeError("Unable to find valid breakout parameters on the training window.")

    return best_params, best_metrics


def walk_forward_backtest(data: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    windows: list[dict[str, Any]] = []
    blotters: list[pd.DataFrame] = []
    ledgers: list[pd.DataFrame] = []

    start_idx = TRAINING_DAYS
    while start_idx + TESTING_DAYS <= len(data):
        train_data = data.iloc[start_idx - TRAINING_DAYS:start_idx].reset_index(drop=True)
        test_data = data.iloc[start_idx:start_idx + TESTING_DAYS].reset_index(drop=True)

        best_params, train_metrics = optimize_parameters(train_data)
        test_blotter, test_ledger = backtest_breakout_strategy(test_data, best_params)
        if test_ledger.empty:
            start_idx += TESTING_DAYS
            continue

        test_metrics = summarize_performance(test_ledger, test_blotter, RISK_FREE_RATE)
        windows.append(
            {
                "train_start": str(train_data["date"].iloc[0].date()),
                "train_end": str(train_data["date"].iloc[-1].date()),
                "test_start": str(test_data["date"].iloc[0].date()),
                "test_end": str(test_data["date"].iloc[-1].date()),
                "best_breakout_lookback": best_params.breakout_lookback,
                "best_stop_loss_atr_multiple": best_params.stop_loss_atr_multiple,
                "best_profit_target_atr_multiple": best_params.profit_target_atr_multiple,
                "best_max_hold_days": best_params.max_hold_days,
                "train_sharpe": train_metrics["annualized_sharpe_ratio"],
                "test_sharpe": test_metrics["annualized_sharpe_ratio"],
                "test_total_return": test_metrics["total_return"],
                "test_trades": test_metrics["number_of_trades"],
            }
        )

        test_blotter = test_blotter.copy()
        test_blotter["window_test_start"] = test_data["date"].iloc[0]
        test_ledger = test_ledger.copy()
        test_ledger["window_test_start"] = test_data["date"].iloc[0]

        blotters.append(test_blotter)
        ledgers.append(test_ledger)
        start_idx += TESTING_DAYS

    all_blotter = pd.concat(blotters, ignore_index=True) if blotters else pd.DataFrame()
    all_ledger = pd.concat(ledgers, ignore_index=True) if ledgers else pd.DataFrame()
    all_windows = pd.DataFrame(windows)
    if not all_blotter.empty:
        all_blotter = all_blotter.reset_index(drop=True)
        all_blotter["trade_id"] = np.arange(1, len(all_blotter) + 1)
        all_blotter["holding_days"] = all_blotter["holding_days"].astype(int)
    return all_blotter, all_ledger, all_windows


def stitch_ledger(ledger: pd.DataFrame) -> pd.DataFrame:
    if ledger.empty:
        return ledger
    stitched = ledger.sort_values("date").reset_index(drop=True).copy()
    capital = INITIAL_CAPITAL
    portfolio_values = []
    cash_values = []
    prev_value = INITIAL_CAPITAL

    for _, row in stitched.iterrows():
        gross_return = float(row["portfolio_value"] / INITIAL_CAPITAL - 1.0)
        current_value = capital * (1.0 + gross_return)
        portfolio_values.append(current_value)
        cash_values.append(current_value - float(row["position_value"]))
        prev_value = current_value

    stitched["portfolio_value"] = portfolio_values
    stitched["cash"] = cash_values
    stitched["daily_pnl"] = stitched["portfolio_value"].diff().fillna(0.0)
    stitched["daily_return"] = stitched["portfolio_value"].pct_change().fillna(0.0)
    return stitched


def rank_assets() -> pd.DataFrame:
    rows = []
    for symbol in ASSET_UNIVERSE:
        history = load_asset_history(symbol)
        blotter, ledger, windows = walk_forward_backtest(history)
        if ledger.empty:
            continue
        stitched = stitch_ledger(ledger)
        metrics = summarize_performance(stitched, blotter, RISK_FREE_RATE)
        rows.append(
            {
                "symbol": symbol,
                "data_source": str(history["source"].iloc[-1]),
                "observations": int(len(history)),
                "trades": int(metrics["number_of_trades"]),
                "average_return_per_trade": float(metrics["average_return_per_trade"]),
                "annualized_sharpe_ratio": float(metrics["annualized_sharpe_ratio"]),
                "total_return": float(metrics["total_return"]),
                "max_drawdown": float(metrics["max_drawdown"]),
                "windows": int(len(windows)),
            }
        )
    ranking = pd.DataFrame(rows).sort_values(
        ["annualized_sharpe_ratio", "total_return", "trades"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    return ranking


def dataframe_to_scroll_html(df: pd.DataFrame, title: str) -> str:
    table_html = df.to_html(index=False, classes="table table-striped table-sm", border=0)
    return f"""
<div class="artifact-card">
  <h3>{title}</h3>
  <div style="max-height: 420px; overflow-y: auto; border: 1px solid #d9d9d9; padding: 0.5rem;">
    {table_html}
  </div>
</div>
"""


def save_plotly_html(fig: go.Figure, path: Path) -> None:
    fig.write_html(str(path), include_plotlyjs="cdn", full_html=True)


def export_artifacts(
    selected_symbol: str,
    history: pd.DataFrame,
    blotter: pd.DataFrame,
    ledger: pd.DataFrame,
    windows: pd.DataFrame,
    ranking: pd.DataFrame,
    metrics: dict[str, float],
    params_summary: dict[str, Any],
) -> None:
    ensure_directories()

    blotter_path = BASE_DIR / "breakout_blotter.csv"
    ledger_path = BASE_DIR / "breakout_ledger.csv"
    windows_path = BASE_DIR / "breakout_walkforward_windows.csv"

    blotter.to_csv(blotter_path, index=False)
    ledger.to_csv(ledger_path, index=False)
    windows.to_csv(windows_path, index=False)

    blotter.to_csv(DATA_DIR / "breakout_blotter.csv", index=False)
    ledger.to_csv(DATA_DIR / "breakout_ledger.csv", index=False)
    windows.to_csv(DATA_DIR / "breakout_walkforward_windows.csv", index=False)
    ranking.to_csv(DATA_DIR / "asset_screening_results.csv", index=False)
    if (BASE_DIR / "breakout_strategy_assignment.py").exists():
        shutil.copy2(BASE_DIR / "breakout_strategy_assignment.py", DATA_DIR / "breakout_strategy_assignment.py")
    if (BASE_DIR / "Breakout_Strategy_Assignment.ipynb").exists():
        shutil.copy2(BASE_DIR / "Breakout_Strategy_Assignment.ipynb", DATA_DIR / "Breakout_Strategy_Assignment.ipynb")

    metrics_df = pd.DataFrame(
        [
            {"metric": "Selected asset", "value": selected_symbol, "explanation": "Asset chosen after walk-forward screening across the ETF universe."},
            {"metric": "Average return per trade", "value": f"{metrics['average_return_per_trade']:.4%}", "explanation": "Mean percentage return across all completed trades."},
            {"metric": "Annualized Sharpe ratio", "value": f"{metrics['annualized_sharpe_ratio']:.3f}", "explanation": "Risk-adjusted return using a 2.0% annual risk-free rate assumption."},
            {"metric": "Max drawdown", "value": f"{metrics['max_drawdown']:.4%}", "explanation": "Largest peak-to-trough drop in the out-of-sample equity curve."},
            {"metric": "Win rate", "value": f"{metrics['win_rate']:.2%}", "explanation": "Fraction of trades that ended with positive PnL."},
            {"metric": "Profit factor", "value": f"{metrics['profit_factor']:.3f}" if not pd.isna(metrics['profit_factor']) else "N/A", "explanation": "Gross profits divided by gross losses."},
            {"metric": "Expectancy (USD)", "value": f"${metrics['expectancy_dollars']:,.2f}", "explanation": "Average dollar PnL per trade."},
            {"metric": "Number of trades", "value": f"{int(metrics['number_of_trades'])}", "explanation": "Completed out-of-sample trades in the stitched walk-forward test."},
        ]
    )

    metrics_df.to_csv(DATA_DIR / "breakout_metrics.csv", index=False)

    with open(DATA_DIR / "selected_asset_and_params.json", "w", encoding="utf-8") as handle:
        json.dump({"selected_asset": selected_symbol, **params_summary}, handle, indent=2)

    blotter_table = blotter.copy()
    if not blotter_table.empty:
        blotter_table["entry_timestamp"] = pd.to_datetime(blotter_table["entry_timestamp"]).dt.strftime("%Y-%m-%d")
        blotter_table["exit_timestamp"] = pd.to_datetime(blotter_table["exit_timestamp"]).dt.strftime("%Y-%m-%d")
        blotter_table["entry_price"] = blotter_table["entry_price"].map(lambda x: f"{x:.2f}")
        blotter_table["exit_price"] = blotter_table["exit_price"].map(lambda x: f"{x:.2f}")
        blotter_table["return_pct"] = blotter_table["return_pct"].map(lambda x: f"{x:.2%}")
        blotter_table["pnl"] = blotter_table["pnl"].map(lambda x: f"${x:,.2f}")

    ledger_table = ledger.copy().tail(120)
    if not ledger_table.empty:
        ledger_table["date"] = pd.to_datetime(ledger_table["date"]).dt.strftime("%Y-%m-%d")
        for column in ["cash", "close", "position_value", "portfolio_value", "daily_pnl", "daily_return"]:
            if column in ledger_table.columns:
                if column == "daily_return":
                    ledger_table[column] = ledger_table[column].map(lambda x: f"{x:.3%}")
                else:
                    ledger_table[column] = ledger_table[column].map(lambda x: f"{x:,.2f}")

    outcome_counts = (
        blotter["outcome"].value_counts().rename_axis("outcome").reset_index(name="count")
        if not blotter.empty
        else pd.DataFrame({"outcome": [], "count": []})
    )

    (TABLE_DIR / "trade_blotter_table.html").write_text(
        dataframe_to_scroll_html(blotter_table, "Trade Blotter"),
        encoding="utf-8",
    )
    (TABLE_DIR / "ledger_table.html").write_text(
        dataframe_to_scroll_html(ledger_table, "Daily Ledger (recent rows)"),
        encoding="utf-8",
    )
    (TABLE_DIR / "metrics_table.html").write_text(
        dataframe_to_scroll_html(metrics_df, "Performance Metrics"),
        encoding="utf-8",
    )
    (TABLE_DIR / "asset_screening_table.html").write_text(
        dataframe_to_scroll_html(ranking, "Asset Screening Results"),
        encoding="utf-8",
    )

    outcome_fig = px.bar(
        outcome_counts,
        x="outcome",
        y="count",
        title="Trade Outcome Counts",
        color="outcome",
        color_discrete_sequence=["#2a9d8f", "#e9c46a", "#e76f51"],
    )
    outcome_fig.update_layout(showlegend=False)
    save_plotly_html(outcome_fig, PLOT_DIR / "trade_outcomes.html")

    equity_fig = go.Figure()
    equity_fig.add_trace(go.Scatter(x=ledger["date"], y=ledger["portfolio_value"], mode="lines", name="Portfolio Value"))
    equity_fig.update_layout(title="Walk-Forward Equity Curve", xaxis_title="Date", yaxis_title="Portfolio Value")
    save_plotly_html(equity_fig, PLOT_DIR / "equity_curve.html")

    drawdown = ledger["portfolio_value"] / ledger["portfolio_value"].cummax() - 1.0
    drawdown_fig = go.Figure()
    drawdown_fig.add_trace(go.Scatter(x=ledger["date"], y=drawdown, fill="tozeroy", mode="lines", name="Drawdown"))
    drawdown_fig.update_layout(title="Drawdown", xaxis_title="Date", yaxis_title="Drawdown")
    save_plotly_html(drawdown_fig, PLOT_DIR / "drawdown.html")

    history_plot = detect_breakouts(history, params_summary["breakout_lookback"])
    breakout_points = history_plot[history_plot["breakout_signal"]]
    breakout_fig = go.Figure()
    breakout_fig.add_trace(go.Scatter(x=history_plot["date"], y=history_plot["close"], mode="lines", name="Close"))
    breakout_fig.add_trace(go.Scatter(x=history_plot["date"], y=history_plot["rolling_high"], mode="lines", name="Rolling High"))
    breakout_fig.add_trace(
        go.Scatter(
            x=breakout_points["date"],
            y=breakout_points["close"],
            mode="markers",
            marker=dict(size=7, color="#e76f51"),
            name="Breakout signal",
        )
    )
    breakout_fig.update_layout(title=f"{selected_symbol} Breakout Signals", xaxis_title="Date", yaxis_title="Price")
    save_plotly_html(breakout_fig, PLOT_DIR / "breakout_signals.html")


def build_summary_text(
    selected_symbol: str,
    ranking: pd.DataFrame,
    metrics: dict[str, float],
    params_summary: dict[str, Any],
    data_source: str,
) -> dict[str, str]:
    top_assets = ", ".join(ranking["symbol"].head(3).tolist())
    return {
        "strategy_logic": (
            f"This breakout strategy buys {selected_symbol} when the closing price finishes above the highest high "
            f"from the prior {params_summary['breakout_lookback']} trading days. Trades are entered at the next day's open, "
            f"risk is capped with a stop-loss set {params_summary['stop_loss_atr_multiple']:.1f} ATR below the entry price, "
            f"profits are taken at {params_summary['profit_target_atr_multiple']:.1f} ATR above the entry price, and any position "
            f"still open after {params_summary['max_hold_days']} trading days is closed with a market order at the next open."
        ),
        "asset_selection": (
            f"I screened the ETF universe {', '.join(ASSET_UNIVERSE)} using a rolling walk-forward test with one year of training "
            f"followed by one quarter of out-of-sample testing. {selected_symbol} was selected because it delivered the strongest "
            f"out-of-sample Sharpe ratio in the screen. The top three assets by walk-forward Sharpe were {top_assets}. "
            f"The historical data loader tries ShinyBroker first; when no local IBKR/TWS session is running, it falls back to a public Yahoo chart endpoint."
        ),
        "breakout_definition": (
            f"A breakout occurs when today's close is greater than the highest high from the previous "
            f"{params_summary['breakout_lookback']} sessions. The implementation uses a shifted rolling maximum to avoid look-ahead bias. "
            f"ATR uses a {params_summary['atr_window']}-day window. The stop-loss threshold is entry price minus "
            f"{params_summary['stop_loss_atr_multiple']:.1f} ATR, the profit target is entry price plus "
            f"{params_summary['profit_target_atr_multiple']:.1f} ATR, and the timeout rule closes any remaining position after "
            f"{params_summary['max_hold_days']} trading days."
        ),
        "results_summary": (
            f"The stitched out-of-sample backtest on {selected_symbol} produced {int(metrics['number_of_trades'])} trades with an "
            f"average return per trade of {metrics['average_return_per_trade']:.2%}, an annualized Sharpe ratio of "
            f"{metrics['annualized_sharpe_ratio']:.2f}, and a maximum drawdown of {metrics['max_drawdown']:.2%}. "
            f"All metrics assume a {RISK_FREE_RATE:.1%} annual risk-free rate."
        ),
        "data_source": data_source,
    }


def main() -> None:
    ensure_directories()
    ranking = rank_assets()
    if ranking.empty:
        raise RuntimeError("No asset produced a valid walk-forward backtest.")

    selected_symbol = str(ranking.iloc[0]["symbol"])
    history = load_asset_history(selected_symbol)
    blotter, ledger, windows = walk_forward_backtest(history)
    ledger = stitch_ledger(ledger)
    metrics = summarize_performance(ledger, blotter, RISK_FREE_RATE)

    if windows.empty:
        raise RuntimeError("Walk-forward windows were empty for the selected asset.")

    latest_window = windows.iloc[-1].to_dict()
    params_summary = {
        "breakout_lookback": int(latest_window["best_breakout_lookback"]),
        "atr_window": ATR_WINDOW,
        "stop_loss_atr_multiple": float(latest_window["best_stop_loss_atr_multiple"]),
        "profit_target_atr_multiple": float(latest_window["best_profit_target_atr_multiple"]),
        "max_hold_days": int(latest_window["best_max_hold_days"]),
    }

    export_artifacts(
        selected_symbol=selected_symbol,
        history=history,
        blotter=blotter,
        ledger=ledger,
        windows=windows,
        ranking=ranking,
        metrics=metrics,
        params_summary=params_summary,
    )

    summary_payload = build_summary_text(
        selected_symbol=selected_symbol,
        ranking=ranking,
        metrics=metrics,
        params_summary=params_summary,
        data_source=str(history["source"].iloc[-1]),
    )
    with open(DATA_DIR / "website_summary.json", "w", encoding="utf-8") as handle:
        json.dump(summary_payload, handle, indent=2)

    print("Selected asset:", selected_symbol)
    print("Data source:", history["source"].iloc[-1])
    print("Trades:", len(blotter))
    print("Sharpe:", metrics["annualized_sharpe_ratio"])


if __name__ == "__main__":
    main()
