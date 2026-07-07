import argparse
import csv
import html
import json
import math
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
OUT_DIR = ROOT / "reports" / "dual_ma"
CODEX_CONFIG = Path.home() / ".codex" / "config.toml"
PRICE_COLUMNS = ["open", "high", "low", "close", "pre_close"]


@dataclass
class Config:
    symbols: list[str]
    start_date: str | None
    end_date: str | None
    adjust: str
    refresh_data: bool
    lookback_days: int
    fast_window: int
    slow_window: int
    initial_cash: float
    buy_commission: float
    sell_commission: float
    stamp_tax: float
    buy_slippage: float
    sell_slippage: float
    enable_stop_loss: bool
    stop_loss_pct: float
    enable_drawdown_stop: bool
    max_drawdown_stop_pct: float


def parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    value = value.strip().lower()
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"Invalid boolean value: {value}")


def normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper()


def symbol_slug(symbol: str) -> str:
    return normalize_symbol(symbol).replace(".", "_")


def fmt_pct(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "--"
    return f"{value * 100:.2f}%"


def fmt_num(value: float | None, digits: int = 2) -> str:
    if value is None or not math.isfinite(value):
        return "--"
    return f"{value:,.{digits}f}"


def validate_config(cfg: Config) -> None:
    if not cfg.symbols:
        raise ValueError("symbols cannot be empty")
    if cfg.fast_window <= 0 or cfg.slow_window <= 0:
        raise ValueError("fast_window and slow_window must be positive")
    if cfg.fast_window >= cfg.slow_window:
        raise ValueError("fast_window must be less than slow_window")
    if cfg.start_date and cfg.end_date and cfg.start_date > cfg.end_date:
        raise ValueError("start_date must be <= end_date")
    if cfg.adjust not in {"none", "qfq", "hfq"}:
        raise ValueError("adjust must be one of: none, qfq, hfq")
    if cfg.lookback_days <= cfg.slow_window + 2:
        raise ValueError("lookback_days must be greater than slow_window + 2")
    for name in [
        "buy_commission",
        "sell_commission",
        "stamp_tax",
        "buy_slippage",
        "sell_slippage",
    ]:
        if getattr(cfg, name) < 0:
            raise ValueError(f"{name} cannot be negative")
    if cfg.enable_stop_loss and not (0 < cfg.stop_loss_pct < 1):
        raise ValueError("stop_loss_pct must be between 0 and 1")
    if cfg.enable_drawdown_stop and not (0 < cfg.max_drawdown_stop_pct < 1):
        raise ValueError("max_drawdown_stop_pct must be between 0 and 1")
    if cfg.initial_cash <= 0:
        raise ValueError("initial_cash must be positive")


def read_tushare_token() -> str:
    env_token = os.environ.get("TUSHARE_TOKEN")
    if env_token:
        return env_token.strip()
    if CODEX_CONFIG.exists():
        text = CODEX_CONFIG.read_text(encoding="utf-8", errors="ignore")
        match = re.search(r"https://api\.tushare\.pro/mcp/\?token=([^'\"\s]+)", text)
        if match:
            return match.group(1)
    raise RuntimeError("No Tushare token found. Set TUSHARE_TOKEN or configure Tushare MCP URL in Codex config.")


def tushare_query(api_name: str, token: str, params: dict, fields: list[str]) -> pd.DataFrame:
    payload = {
        "api_name": api_name,
        "token": token,
        "params": params,
        "fields": ",".join(fields),
    }
    req = urllib.request.Request(
        "https://api.tushare.pro",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Tushare request failed for {api_name}: {exc}") from exc
    if raw.get("code") != 0:
        raise RuntimeError(f"Tushare API error for {api_name} [{raw.get('code')}]: {raw.get('msg')}")
    data = raw.get("data") or {}
    rows = data.get("items") or []
    result_fields = data.get("fields") or fields
    return pd.DataFrame(rows, columns=result_fields)


def default_fetch_dates(cfg: Config) -> tuple[str, str]:
    end = cfg.end_date or date.today().strftime("%Y%m%d")
    start = cfg.start_date or (date.today() - timedelta(days=cfg.lookback_days)).strftime("%Y%m%d")
    return start, end


def adjusted_data_path(symbol: str, adjust: str) -> Path:
    return DATA_DIR / "stocks" / f"{symbol_slug(symbol)}_daily_{adjust}.csv"


def fetch_and_cache_adjusted_daily(symbol: str, cfg: Config) -> Path:
    ts_code = normalize_symbol(symbol)
    slug = symbol_slug(ts_code)
    start, end = default_fetch_dates(cfg)
    token = read_tushare_token()
    fields = [
        "ts_code",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "change",
        "pct_chg",
        "vol",
        "amount",
    ]
    daily = tushare_query(
        "daily",
        token,
        {"ts_code": ts_code, "start_date": start, "end_date": end},
        fields,
    )
    if daily.empty:
        raise RuntimeError(f"Tushare returned no daily rows for {ts_code} from {start} to {end}")
    daily["trade_date"] = daily["trade_date"].astype(str)
    for col in fields:
        if col not in {"ts_code", "trade_date"}:
            daily[col] = pd.to_numeric(daily[col], errors="coerce")

    if cfg.adjust != "none":
        factors = tushare_query(
            "adj_factor",
            token,
            {"ts_code": ts_code, "start_date": start, "end_date": end},
            ["ts_code", "trade_date", "adj_factor"],
        )
        if factors.empty:
            raise RuntimeError(f"Tushare returned no adj_factor rows for {ts_code} from {start} to {end}")
        factors["trade_date"] = factors["trade_date"].astype(str)
        factors["adj_factor"] = pd.to_numeric(factors["adj_factor"], errors="coerce")
        daily = daily.merge(factors[["trade_date", "adj_factor"]], on="trade_date", how="left")
        if daily["adj_factor"].isna().any():
            missing = int(daily["adj_factor"].isna().sum())
            raise RuntimeError(f"Missing adj_factor for {missing} rows of {ts_code}")
        daily = daily.sort_values("trade_date").reset_index(drop=True)
        base_factor = daily["adj_factor"].iloc[-1] if cfg.adjust == "qfq" else daily["adj_factor"].iloc[0]
        ratio = daily["adj_factor"] / base_factor
        for col in PRICE_COLUMNS:
            daily[col] = daily[col] * ratio
        daily["change"] = daily["close"] - daily["pre_close"]
        daily["pct_chg"] = daily["change"] / daily["pre_close"] * 100
    else:
        daily["adj_factor"] = 1.0
        daily = daily.sort_values("trade_date").reset_index(drop=True)
    daily["adjust"] = cfg.adjust

    out_dir = DATA_DIR / "stocks"
    out_dir.mkdir(parents=True, exist_ok=True)
    dated_path = out_dir / f"{slug}_daily_{cfg.adjust}_{daily['trade_date'].iloc[0]}_{daily['trade_date'].iloc[-1]}.csv"
    latest_path = adjusted_data_path(ts_code, cfg.adjust)
    daily.to_csv(dated_path, index=False, encoding="utf-8-sig", float_format="%.6f")
    daily.to_csv(latest_path, index=False, encoding="utf-8-sig", float_format="%.6f")
    return latest_path


def find_data_file(symbol: str, cfg: Config) -> Path:
    slug = symbol_slug(symbol)
    candidates = [
        adjusted_data_path(symbol, cfg.adjust),
        DATA_DIR / "stocks" / f"{slug}_daily_{cfg.adjust}_latest.csv",
    ]
    if cfg.adjust == "none" and normalize_symbol(symbol) == "603986.SH":
        candidates.extend(
            [
                DATA_DIR / "gigadevice" / "603986_SH_daily_latest.csv",
                DATA_DIR / "gigadevice" / "603986_SH_daily_20250704_20260703.csv",
            ]
        )
    candidates.extend(sorted(DATA_DIR.rglob(f"*{slug}*daily*{cfg.adjust}*.csv")))
    for path in candidates:
        if path.exists():
            return path
    if cfg.refresh_data or cfg.adjust != "none":
        return fetch_and_cache_adjusted_daily(symbol, cfg)
    raise FileNotFoundError(
        f"No local CSV found for {symbol}. Expected data/stocks/{slug}_daily_{cfg.adjust}.csv or a matching CSV under data/."
    )


def load_symbol_data(symbol: str, cfg: Config) -> pd.DataFrame:
    path = fetch_and_cache_adjusted_daily(symbol, cfg) if cfg.refresh_data else find_data_file(symbol, cfg)
    df = pd.read_csv(path)
    required = {"trade_date", "open", "close"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"{path} missing required columns: {', '.join(sorted(missing))}")
    df["trade_date"] = df["trade_date"].astype(str)
    df = df.sort_values("trade_date").reset_index(drop=True)
    if cfg.start_date:
        df = df[df["trade_date"] >= cfg.start_date]
    if cfg.end_date:
        df = df[df["trade_date"] <= cfg.end_date]
    df = df.reset_index(drop=True)
    if len(df) <= cfg.slow_window + 2:
        raise ValueError(
            f"Not enough rows after date filtering: {len(df)} rows, need more than slow_window + 2"
        )
    if not df["trade_date"].is_monotonic_increasing:
        raise ValueError("trade_date must be sorted ascending")
    if (df["open"] <= 0).any() or (df["close"] <= 0).any():
        raise ValueError("open and close must be positive")
    if "ts_code" not in df.columns:
        df["ts_code"] = normalize_symbol(symbol)
    return df


def max_drawdown(nav: pd.Series) -> float:
    peak = nav.cummax()
    dd = nav / peak - 1
    return float(dd.min())


def sharpe_ratio(nav: pd.Series) -> float | None:
    returns = nav.pct_change().dropna()
    if len(returns) < 2 or returns.std(ddof=1) == 0:
        return None
    return float(returns.mean() / returns.std(ddof=1) * math.sqrt(252))


def annual_return(nav: pd.Series) -> float | None:
    if len(nav) < 2:
        return None
    total = nav.iloc[-1] / nav.iloc[0] - 1
    years = len(nav) / 252
    if years <= 0:
        return None
    return float((1 + total) ** (1 / years) - 1)


def make_unexecuted_event(ts_code: str, row: pd.Series, event_type: str, trigger: float, threshold: float) -> dict:
    return {
        "ts_code": ts_code,
        "event_date": row["trade_date"],
        "event_type": event_type,
        "trigger_value": trigger,
        "threshold": threshold,
        "execution_date": "",
        "execution_price": "",
        "status": "not_executed_no_next_day",
    }


def trade_markers(trades: pd.DataFrame, y_lookup: dict[str, float]) -> list[dict]:
    if trades.empty:
        return []
    markers = []
    for _, trade in trades.iterrows():
        entry_date = str(trade["entry_date"])
        exit_date = str(trade["exit_date"])
        if entry_date in y_lookup:
            markers.append(
                {
                    "date": entry_date,
                    "value": y_lookup[entry_date],
                    "label": "BUY",
                    "color": "#d92d20",
                }
            )
        if exit_date in y_lookup:
            reason = str(trade["exit_reason"])
            color = "#dc6803" if reason in {"stop_loss", "max_drawdown_stop"} else "#039855"
            label = "RISK" if reason in {"stop_loss", "max_drawdown_stop"} else "SELL"
            markers.append({"date": exit_date, "value": y_lookup[exit_date], "label": label, "color": color})
    return markers


def run_backtest(symbol: str, cfg: Config) -> dict:
    ts_code = normalize_symbol(symbol)
    df = load_symbol_data(ts_code, cfg).copy()
    df["ma_fast"] = df["close"].rolling(cfg.fast_window).mean()
    df["ma_slow"] = df["close"].rolling(cfg.slow_window).mean()

    cash = cfg.initial_cash
    shares = 0.0
    entry = None
    entry_signal_date = ""
    entry_raw_open = None
    buy_fee = 0.0
    position = 0
    halted = False
    pending_order = None
    trades = []
    equity_rows = []
    risk_events = []
    trade_returns = []
    equity_peak = 1.0

    buy_hold_shares = cfg.initial_cash / float(df.iloc[0]["close"])

    for i, row in df.iterrows():
        date = row["trade_date"]
        open_price = float(row["open"])
        close_price = float(row["close"])

        if pending_order:
            if pending_order["action"] == "buy" and not halted and position == 0:
                exec_price = open_price * (1 + cfg.buy_slippage)
                shares = cash / (exec_price * (1 + cfg.buy_commission))
                gross = shares * exec_price
                buy_fee = gross * cfg.buy_commission
                cash -= gross + buy_fee
                if abs(cash) < 1e-6:
                    cash = 0.0
                position = 1
                entry = {
                    "date": date,
                    "price": exec_price,
                    "gross": gross,
                }
                entry_signal_date = pending_order["signal_date"]
                entry_raw_open = open_price
            elif pending_order["action"] == "sell" and position == 1:
                exec_price = open_price * (1 - cfg.sell_slippage)
                gross = shares * exec_price
                sell_fee = gross * cfg.sell_commission
                stamp_fee = gross * cfg.stamp_tax
                cash += gross - sell_fee - stamp_fee
                gross_return = exec_price / entry["price"] - 1
                net_return = cash / (entry["gross"] + buy_fee) - 1
                slippage_cost = shares * ((entry["price"] - entry_raw_open) + (open_price - exec_price))
                total_cost = buy_fee + sell_fee + stamp_fee + slippage_cost
                trades.append(
                    {
                        "ts_code": ts_code,
                        "entry_signal_date": entry_signal_date,
                        "entry_date": entry["date"],
                        "entry_price": entry["price"],
                        "exit_signal_date": pending_order["signal_date"],
                        "exit_date": date,
                        "exit_price": exec_price,
                        "exit_reason": pending_order["reason"],
                        "holding_days": len(df[(df["trade_date"] >= entry["date"]) & (df["trade_date"] <= date)]),
                        "gross_return": gross_return,
                        "net_return": net_return,
                        "total_cost": total_cost,
                    }
                )
                trade_returns.append(net_return)
                shares = 0.0
                position = 0
                entry = None
                entry_signal_date = ""
                entry_raw_open = None
                buy_fee = 0.0
            pending_order = None

        position_value = shares * close_price
        total_asset = cash + position_value
        strategy_nav = total_asset / cfg.initial_cash
        buy_hold_nav = buy_hold_shares * close_price / cfg.initial_cash
        equity_peak = max(equity_peak, strategy_nav)
        drawdown = strategy_nav / equity_peak - 1

        equity_rows.append(
            {
                "trade_date": date,
                "position": shares,
                "is_halted": halted,
                "cash": cash,
                "position_value": position_value,
                "total_asset": total_asset,
                "strategy_nav": strategy_nav,
                "buy_hold_nav": buy_hold_nav,
                "drawdown": drawdown,
                "ma_fast": row["ma_fast"],
                "ma_slow": row["ma_slow"],
                "close": close_price,
            }
        )

        if i == len(df) - 1:
            next_exists = False
        else:
            next_exists = True

        exit_reason = None
        trigger_value = None
        threshold = None
        if not halted and cfg.enable_drawdown_stop and drawdown <= -cfg.max_drawdown_stop_pct:
            exit_reason = "max_drawdown_stop"
            trigger_value = drawdown
            threshold = cfg.max_drawdown_stop_pct
            halted = True
        elif (
            position == 1
            and cfg.enable_stop_loss
            and entry is not None
            and close_price / entry["price"] - 1 <= -cfg.stop_loss_pct
        ):
            exit_reason = "stop_loss"
            trigger_value = close_price / entry["price"] - 1
            threshold = cfg.stop_loss_pct
        elif (
            position == 1
            and i > 0
            and pd.notna(df.loc[i - 1, "ma_fast"])
            and pd.notna(df.loc[i - 1, "ma_slow"])
            and pd.notna(row["ma_fast"])
            and pd.notna(row["ma_slow"])
            and df.loc[i - 1, "ma_fast"] >= df.loc[i - 1, "ma_slow"]
            and row["ma_fast"] < row["ma_slow"]
        ):
            exit_reason = "death_cross"

        if exit_reason:
            if exit_reason in {"stop_loss", "max_drawdown_stop"}:
                has_position_to_exit = position == 1
                execution_price = (
                    float(df.loc[i + 1, "open"]) * (1 - cfg.sell_slippage)
                    if next_exists and has_position_to_exit
                    else ""
                )
                event_status = (
                    "executed"
                    if next_exists and has_position_to_exit
                    else "halted_no_position"
                    if not has_position_to_exit
                    else "not_executed_no_next_day"
                )
                event = {
                    "ts_code": ts_code,
                    "event_date": date,
                    "event_type": exit_reason,
                    "trigger_value": trigger_value,
                    "threshold": threshold,
                    "execution_date": df.loc[i + 1, "trade_date"] if next_exists and has_position_to_exit else "",
                    "execution_price": execution_price,
                    "status": event_status,
                }
                risk_events.append(event)
            if next_exists:
                if position == 1:
                    pending_order = {"action": "sell", "signal_date": date, "reason": exit_reason}
            continue

        if (
            position == 0
            and not halted
            and i > 0
            and pd.notna(df.loc[i - 1, "ma_fast"])
            and pd.notna(df.loc[i - 1, "ma_slow"])
            and pd.notna(row["ma_fast"])
            and pd.notna(row["ma_slow"])
            and df.loc[i - 1, "ma_fast"] <= df.loc[i - 1, "ma_slow"]
            and row["ma_fast"] > row["ma_slow"]
        ):
            if next_exists:
                pending_order = {"action": "buy", "signal_date": date, "reason": "golden_cross"}

    # Close open position at final close for reporting consistency.
    if position == 1 and entry is not None:
        final = df.iloc[-1]
        exec_price = float(final["close"])
        gross = shares * exec_price
        sell_fee = gross * cfg.sell_commission
        stamp_fee = gross * cfg.stamp_tax
        final_cash = cash + gross - sell_fee - stamp_fee
        gross_return = exec_price / entry["price"] - 1
        net_return = final_cash / (entry["gross"] + buy_fee) - 1
        total_cost = buy_fee + sell_fee + stamp_fee + shares * (entry["price"] - entry_raw_open)
        trades.append(
            {
                "ts_code": ts_code,
                "entry_signal_date": entry_signal_date,
                "entry_date": entry["date"],
                "entry_price": entry["price"],
                "exit_signal_date": final["trade_date"],
                "exit_date": final["trade_date"],
                "exit_price": exec_price,
                "exit_reason": "end_of_backtest",
                "holding_days": len(df[df["trade_date"] >= entry["date"]]),
                "gross_return": gross_return,
                "net_return": net_return,
                "total_cost": total_cost,
            }
        )
        trade_returns.append(net_return)

    equity_df = pd.DataFrame(equity_rows)
    trades_df = pd.DataFrame(trades)
    risk_df = pd.DataFrame(risk_events)
    if trades_df.empty:
        trades_df = pd.DataFrame(
            columns=[
                "ts_code",
                "entry_signal_date",
                "entry_date",
                "entry_price",
                "exit_signal_date",
                "exit_date",
                "exit_price",
                "exit_reason",
                "holding_days",
                "gross_return",
                "net_return",
                "total_cost",
            ]
        )
    if risk_df.empty:
        risk_df = pd.DataFrame(
            columns=[
                "ts_code",
                "event_date",
                "event_type",
                "trigger_value",
                "threshold",
                "execution_date",
                "execution_price",
                "status",
            ]
        )

    nav = equity_df["strategy_nav"]
    buy_hold_nav = equity_df["buy_hold_nav"]
    wins = [r for r in trade_returns if r > 0]
    losses = [r for r in trade_returns if r <= 0]
    avg_win = float(np.mean(wins)) if wins else 0.0
    avg_loss = abs(float(np.mean(losses))) if losses else 0.0
    summary = {
        "ts_code": ts_code,
        "status": "ok",
        "adjust": cfg.adjust,
        "start_date": df.iloc[0]["trade_date"],
        "end_date": df.iloc[-1]["trade_date"],
        "strategy_return": float(nav.iloc[-1] - 1),
        "buy_hold_return": float(buy_hold_nav.iloc[-1] - 1),
        "excess_return": float(nav.iloc[-1] - buy_hold_nav.iloc[-1]),
        "annual_return": annual_return(nav),
        "max_drawdown": max_drawdown(nav),
        "sharpe": sharpe_ratio(nav),
        "win_rate": len(wins) / len(trade_returns) if trade_returns else 0.0,
        "trade_count": len(trades_df),
        "payoff": avg_win / avg_loss if avg_loss else None,
        "avg_holding_days": float(trades_df["holding_days"].mean()) if not trades_df.empty else 0.0,
        "stop_loss_count": int((trades_df["exit_reason"] == "stop_loss").sum()) if not trades_df.empty else 0,
        "drawdown_stop_triggered": bool((risk_df["event_type"] == "max_drawdown_stop").any()) if not risk_df.empty else False,
    }
    return {
        "symbol": ts_code,
        "data": df,
        "equity": equity_df,
        "trades": trades_df,
        "risk_events": risk_df,
        "summary": summary,
    }


def svg_line_chart(
    title: str,
    x_labels: list[str],
    series: list[dict],
    y_min=None,
    y_max=None,
    height=320,
    markers: list[dict] | None = None,
) -> str:
    width = 980
    left, right, top, bottom = 64, 24, 42, 38
    plot_w, plot_h = width - left - right, height - top - bottom
    vals = []
    for s in series:
        vals.extend([float(v) for v in s["values"] if pd.notna(v)])
    if markers:
        vals.extend([float(m["value"]) for m in markers if pd.notna(m.get("value"))])
    if not vals:
        vals = [0, 1]
    y_min = min(vals) if y_min is None else y_min
    y_max = max(vals) if y_max is None else y_max
    if y_min == y_max:
        y_min -= 1
        y_max += 1
    pad = (y_max - y_min) * 0.05
    y_min -= pad
    y_max += pad

    def x(i):
        return left + plot_w * i / max(1, len(x_labels) - 1)

    def y(v):
        return top + (y_max - float(v)) / (y_max - y_min) * plot_h

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#fff"/>',
        f'<text x="{left}" y="25" font-size="17" font-weight="700" fill="#182230">{html.escape(title)}</text>',
    ]
    for i in range(5):
        yy = top + plot_h * i / 4
        val = y_max - (y_max - y_min) * i / 4
        parts.append(f'<line x1="{left}" y1="{yy:.2f}" x2="{width-right}" y2="{yy:.2f}" stroke="#e4e7ec"/>')
        parts.append(f'<text x="8" y="{yy+4:.2f}" font-size="12" fill="#667085">{val:.2f}</text>')
    colors = ["#2563eb", "#d92d20", "#039855", "#7c3aed", "#f59e0b", "#475467"]
    legend_x = left
    for idx, s in enumerate(series):
        color = s.get("color", colors[idx % len(colors)])
        pts = []
        for i, v in enumerate(s["values"]):
            if pd.notna(v):
                pts.append(f"{x(i):.2f},{y(v):.2f}")
        parts.append(f'<polyline points="{" ".join(pts)}" fill="none" stroke="{color}" stroke-width="{s.get("width", 2)}"/>')
        parts.append(f'<circle cx="{legend_x}" cy="{height-13}" r="5" fill="{color}"/>')
        parts.append(f'<text x="{legend_x+9}" y="{height-9}" font-size="12" fill="#475467">{html.escape(s["name"])}</text>')
        legend_x += max(90, len(s["name"]) * 8 + 30)
    if markers:
        label_to_x = {label: i for i, label in enumerate(x_labels)}
        for marker in markers:
            if marker["date"] not in label_to_x:
                continue
            mx = x(label_to_x[marker["date"]])
            my = y(marker["value"])
            color = marker.get("color", "#dc6803")
            parts.append(f'<circle cx="{mx:.2f}" cy="{my:.2f}" r="6" fill="{color}" stroke="#fff" stroke-width="2"/>')
            parts.append(f'<text x="{mx+8:.2f}" y="{my-8:.2f}" font-size="12" fill="{color}" font-weight="700">{html.escape(marker["label"])}</text>')
    if x_labels:
        for idx in [0, len(x_labels) // 2, len(x_labels) - 1]:
            parts.append(f'<text x="{x(idx)-28:.2f}" y="{height-22}" font-size="11" fill="#667085">{x_labels[idx]}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def svg_scatter(title: str, rows: list[dict], height=320) -> str:
    width = 700
    left, right, top, bottom = 70, 28, 42, 48
    plot_w, plot_h = width - left - right, height - top - bottom
    xs = [r["max_drawdown"] for r in rows if r["status"] == "ok" and r["max_drawdown"] is not None]
    ys = [r["strategy_return"] for r in rows if r["status"] == "ok" and r["strategy_return"] is not None]
    if not xs or not ys:
        xs, ys = [-0.1, 0], [0, 0.1]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    if x_min == x_max:
        x_min -= 0.05
        x_max += 0.05
    if y_min == y_max:
        y_min -= 0.05
        y_max += 0.05

    def sx(v):
        return left + (v - x_min) / (x_max - x_min) * plot_w

    def sy(v):
        return top + (y_max - v) / (y_max - y_min) * plot_h

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#fff"/>',
        f'<text x="{left}" y="25" font-size="17" font-weight="700" fill="#182230">{html.escape(title)}</text>',
        f'<rect x="{left}" y="{top}" width="{plot_w}" height="{plot_h}" fill="none" stroke="#e4e7ec"/>',
    ]
    for r in rows:
        if r["status"] != "ok" or r["max_drawdown"] is None or r["strategy_return"] is None:
            continue
        x, y = sx(r["max_drawdown"]), sy(r["strategy_return"])
        parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="6" fill="#2563eb" opacity="0.85"/>')
        parts.append(f'<text x="{x+8:.2f}" y="{y+4:.2f}" font-size="12" fill="#475467">{html.escape(r["ts_code"])}</text>')
    parts.append(f'<text x="{left}" y="{height-14}" font-size="12" fill="#667085">横轴：最大回撤；纵轴：策略收益</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def write_csv(path: Path, df: pd.DataFrame) -> None:
    df.to_csv(path, index=False, encoding="utf-8-sig")


def write_single_report(result: dict, cfg: Config) -> None:
    symbol = result["symbol"]
    slug = symbol_slug(symbol)
    equity = result["equity"]
    trades = result["trades"]
    risk = result["risk_events"]
    summary = result["summary"]
    dates = equity["trade_date"].tolist()
    close_lookup = dict(zip(equity["trade_date"].astype(str), equity["close"].astype(float)))
    price_chart = svg_line_chart(
        f"{symbol} 价格与双均线",
        dates,
        [
            {"name": "收盘价", "values": equity["close"].tolist(), "color": "#182230"},
            {"name": f"MA{cfg.fast_window}", "values": equity["ma_fast"].tolist(), "color": "#f59e0b"},
            {"name": f"MA{cfg.slow_window}", "values": equity["ma_slow"].tolist(), "color": "#2563eb"},
        ],
        height=360,
        markers=trade_markers(trades, close_lookup),
    )
    nav_chart = svg_line_chart(
        f"{symbol} 策略净值 vs BUY入持有",
        dates,
        [
            {"name": "策略净值", "values": equity["strategy_nav"].tolist(), "color": "#2563eb"},
            {"name": "BUY入持有", "values": equity["buy_hold_nav"].tolist(), "color": "#98a2b3"},
        ],
        height=320,
    )
    dd_chart = svg_line_chart(
        f"{symbol} 回撤曲线",
        dates,
        [{"name": "策略回撤", "values": equity["drawdown"].tolist(), "color": "#d92d20"}],
        y_max=0,
        height=280,
    )
    trade_ret_values = trades["net_return"].tolist() if not trades.empty else [0]
    trade_chart = svg_line_chart(
        f"{symbol} 单笔交易净收益",
        [str(i + 1) for i in range(len(trade_ret_values))],
        [{"name": "单笔净收益", "values": trade_ret_values, "color": "#039855"}],
        height=260,
    )
    rows = [
        ("策略收益", fmt_pct(summary["strategy_return"])),
        ("BUY入持有收益", fmt_pct(summary["buy_hold_return"])),
        ("超额收益", fmt_pct(summary["excess_return"])),
        ("年化收益", fmt_pct(summary["annual_return"])),
        ("最大回撤", fmt_pct(summary["max_drawdown"])),
        ("夏普比率", fmt_num(summary["sharpe"], 3)),
        ("胜率", fmt_pct(summary["win_rate"])),
        ("交易次数", str(summary["trade_count"])),
        ("止损次数", str(summary["stop_loss_count"])),
        ("触发回撤停交易", "是" if summary["drawdown_stop_triggered"] else "否"),
    ]
    trade_table = trades.tail(12).to_html(index=False, classes="data", border=0) if not trades.empty else "<p>无交易。</p>"
    risk_table = risk.to_html(index=False, classes="data", border=0) if not risk.empty else "<p>无RISK事件。</p>"
    html_text = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{symbol} 双均线策略报告</title>
<style>
body{{font-family:"Microsoft YaHei","Segoe UI",Arial,sans-serif;background:#f5f7fa;color:#182230;margin:0}}
main{{max-width:1120px;margin:auto;padding:22px}}section{{background:#fff;border:1px solid #e4e7ec;border-radius:8px;padding:16px;margin:12px 0}}
h1{{margin-top:0}}.grid{{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px}}.card{{border:1px solid #e4e7ec;border-radius:8px;padding:10px}}
.label{{font-size:12px;color:#667085}}.value{{font-size:18px;font-weight:700;margin-top:4px}}table.data{{width:100%;border-collapse:collapse;font-size:12px}}table.data td,table.data th{{border-bottom:1px solid #e4e7ec;padding:7px;text-align:right}}table.data td:first-child,table.data th:first-child{{text-align:left}}
svg{{width:100%;height:auto}}@media(max-width:900px){{.grid{{grid-template-columns:repeat(2,1fr)}}}}
</style></head><body><main>
<h1>{symbol} 双均线策略报告</h1>
<p>参数：复权口径 {cfg.adjust}，MA{cfg.fast_window}/MA{cfg.slow_window}，初始资金 {cfg.initial_cash:,.0f}，单笔止损 {fmt_pct(cfg.stop_loss_pct if cfg.enable_stop_loss else None)}，最大回撤停交易 {fmt_pct(cfg.max_drawdown_stop_pct if cfg.enable_drawdown_stop else None)}。</p>
<section><h2>核心指标</h2><div class="grid">
{''.join(f'<div class="card"><div class="label">{html.escape(k)}</div><div class="value">{html.escape(v)}</div></div>' for k, v in rows)}
</div></section>
<section>{price_chart}</section>
<section>{nav_chart}</section>
<section>{dd_chart}</section>
<section>{trade_chart}</section>
<section><h2>最近交易明细</h2>{trade_table}</section>
<section><h2>RISK事件</h2>{risk_table}</section>
</main></body></html>"""
    (OUT_DIR / f"{slug}_report.html").write_text(html_text, encoding="utf-8")


def write_comparison(results: list[dict], failures: list[dict], cfg: Config) -> None:
    summary_rows = [r["summary"] for r in results] + failures
    summary_df = pd.DataFrame(summary_rows)
    write_csv(OUT_DIR / "summary.csv", summary_df)

    ok_rows = [r["summary"] for r in results]
    all_dates = []
    series = []
    if results:
        # For visual comparison, use the longest result's date axis and forward-fill each nav on date.
        idx = sorted(set().union(*[set(r["equity"]["trade_date"]) for r in results]))
        all_dates = idx
        for r in results:
            nav = r["equity"].set_index("trade_date")["strategy_nav"].reindex(idx).ffill()
            series.append({"name": r["symbol"], "values": nav.tolist()})
    nav_chart = svg_line_chart("多股票策略净值对比", all_dates, series, height=360) if results else "<p>无可用回测结果。</p>"
    scatter = svg_scatter("策略收益 / 最大回撤", ok_rows) if ok_rows else "<p>无可用回测结果。</p>"
    rank_rows = sorted(ok_rows, key=lambda r: r.get("stop_loss_count", 0), reverse=True)
    rank_table = pd.DataFrame(rank_rows)[["ts_code", "stop_loss_count", "drawdown_stop_triggered", "strategy_return", "max_drawdown"]].to_html(index=False, classes="data", border=0) if rank_rows else "<p>无RISK排行。</p>"
    table = summary_df.to_html(index=False, classes="data", border=0)
    best = max(ok_rows, key=lambda r: r["strategy_return"]) if ok_rows else None
    worst = min(ok_rows, key=lambda r: r["strategy_return"]) if ok_rows else None
    best_worst = ""
    if best and worst:
        best_worst = f"<p>最优：{best['ts_code']}，策略收益 {fmt_pct(best['strategy_return'])}；最弱：{worst['ts_code']}，策略收益 {fmt_pct(worst['strategy_return'])}。</p>"
    html_text = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>双均线策略多股票对比</title>
<style>
body{{font-family:"Microsoft YaHei","Segoe UI",Arial,sans-serif;background:#f5f7fa;color:#182230;margin:0}}
main{{max-width:1180px;margin:auto;padding:22px}}section{{background:#fff;border:1px solid #e4e7ec;border-radius:8px;padding:16px;margin:12px 0}}
table.data{{width:100%;border-collapse:collapse;font-size:12px}}table.data td,table.data th{{border-bottom:1px solid #e4e7ec;padding:7px;text-align:right;white-space:nowrap}}table.data td:first-child,table.data th:first-child{{text-align:left}}
svg{{width:100%;height:auto}}
</style></head><body><main>
<h1>双均线策略多股票对比</h1>
<p>参数：复权口径 {cfg.adjust}，MA{cfg.fast_window}/MA{cfg.slow_window}，初始资金 {cfg.initial_cash:,.0f}，成本和风控按命令行参数执行。</p>
<section><h2>表现摘要</h2>{best_worst}{table}</section>
<section>{nav_chart}</section>
<section>{scatter}</section>
<section><h2>RISK触发排行</h2>{rank_table}</section>
</main></body></html>"""
    (OUT_DIR / "comparison.html").write_text(html_text, encoding="utf-8")


def save_result(result: dict, cfg: Config) -> None:
    slug = symbol_slug(result["symbol"])
    write_csv(OUT_DIR / f"{slug}_trades.csv", result["trades"])
    write_csv(OUT_DIR / f"{slug}_equity_curve.csv", result["equity"])
    write_csv(OUT_DIR / f"{slug}_risk_events.csv", result["risk_events"])
    (OUT_DIR / f"{slug}_summary.json").write_text(
        json.dumps(result["summary"], ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    write_single_report(result, cfg)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Multi-stock dual moving average backtest tool.")
    parser.add_argument("--symbols", default="603986.SH", help="Comma-separated Tushare symbols, e.g. 603986.SH,000001.SZ")
    parser.add_argument("--start-date", default=None, help="Backtest start date YYYYMMDD")
    parser.add_argument("--end-date", default=None, help="Backtest end date YYYYMMDD")
    parser.add_argument("--adjust", choices=["none", "qfq", "hfq"], default="qfq", help="Price adjustment mode. Default qfq.")
    parser.add_argument("--refresh-data", type=parse_bool, default=False, help="Fetch and overwrite adjusted CSV cache from Tushare.")
    parser.add_argument("--lookback-days", type=int, default=365, help="Default Tushare fetch window when start-date is omitted.")
    parser.add_argument("--fast-window", type=int, default=5)
    parser.add_argument("--slow-window", type=int, default=20)
    parser.add_argument("--initial-cash", type=float, default=1_000_000)
    parser.add_argument("--buy-commission", type=float, default=0.0003)
    parser.add_argument("--sell-commission", type=float, default=0.0003)
    parser.add_argument("--stamp-tax", type=float, default=0.0005)
    parser.add_argument("--buy-slippage", type=float, default=0.0002)
    parser.add_argument("--sell-slippage", type=float, default=0.0002)
    parser.add_argument("--enable-stop-loss", type=parse_bool, default=True)
    parser.add_argument("--stop-loss-pct", type=float, default=0.08)
    parser.add_argument("--enable-drawdown-stop", type=parse_bool, default=True)
    parser.add_argument("--max-drawdown-stop-pct", type=float, default=0.20)
    return parser


def parse_args() -> Config:
    args = build_parser().parse_args()
    cfg = Config(
        symbols=[normalize_symbol(s) for s in args.symbols.split(",") if s.strip()],
        start_date=args.start_date,
        end_date=args.end_date,
        adjust=args.adjust,
        refresh_data=args.refresh_data,
        lookback_days=args.lookback_days,
        fast_window=args.fast_window,
        slow_window=args.slow_window,
        initial_cash=args.initial_cash,
        buy_commission=args.buy_commission,
        sell_commission=args.sell_commission,
        stamp_tax=args.stamp_tax,
        buy_slippage=args.buy_slippage,
        sell_slippage=args.sell_slippage,
        enable_stop_loss=args.enable_stop_loss,
        stop_loss_pct=args.stop_loss_pct,
        enable_drawdown_stop=args.enable_drawdown_stop,
        max_drawdown_stop_pct=args.max_drawdown_stop_pct,
    )
    validate_config(cfg)
    return cfg


def main() -> None:
    cfg = parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    failures = []
    for symbol in cfg.symbols:
        try:
            result = run_backtest(symbol, cfg)
            save_result(result, cfg)
            results.append(result)
            print(f"ok {symbol}: return={result['summary']['strategy_return']:.4f}")
        except Exception as exc:
            failures.append(
                {
                    "ts_code": symbol,
                    "status": str(exc),
                    "adjust": cfg.adjust,
                    "start_date": cfg.start_date or "",
                    "end_date": cfg.end_date or "",
                    "strategy_return": None,
                    "buy_hold_return": None,
                    "excess_return": None,
                    "annual_return": None,
                    "max_drawdown": None,
                    "sharpe": None,
                    "win_rate": None,
                    "trade_count": 0,
                    "stop_loss_count": 0,
                    "drawdown_stop_triggered": False,
                }
            )
            print(f"failed {symbol}: {exc}")
    write_comparison(results, failures, cfg)
    print(f"summary={OUT_DIR / 'summary.csv'}")
    print(f"comparison={OUT_DIR / 'comparison.html'}")


if __name__ == "__main__":
    main()

