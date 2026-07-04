import csv
import json
import re
import shutil
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CODEX_CONFIG = Path.home() / ".codex" / "config.toml"
TS_CODE = "603986.SH"
NAME = "兆易创新"
END_DATE = date.today()
START_DATE = END_DATE - timedelta(days=365)
START = START_DATE.strftime("%Y%m%d")
END = END_DATE.strftime("%Y%m%d")
FIELDS = [
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


def read_tushare_token() -> str:
    text = CODEX_CONFIG.read_text(encoding="utf-8", errors="ignore")
    match = re.search(r"https://api\.tushare\.pro/mcp/\?token=([^'\"\s]+)", text)
    if not match:
        raise RuntimeError(f"No Tushare token found in {CODEX_CONFIG}")
    return match.group(1)


def fetch_daily(token: str) -> list[dict]:
    payload = {
        "api_name": "daily",
        "token": token,
        "params": {
            "ts_code": TS_CODE,
            "start_date": START,
            "end_date": END,
        },
        "fields": ",".join(FIELDS),
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
        raise RuntimeError(f"Tushare request failed: {exc}") from exc

    if raw.get("code") != 0:
        raise RuntimeError(f"Tushare API error {raw.get('code')}: {raw.get('msg')}")

    data = raw.get("data") or {}
    fields = data.get("fields") or []
    rows = data.get("items") or []
    records = [dict(zip(fields, row)) for row in rows]
    return sorted(records, key=lambda item: item["trade_date"])


def write_csv(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records)


def write_html(path: Path, records: list[dict]) -> None:
    first = records[0]["trade_date"] if records else START
    last = records[-1]["trade_date"] if records else END
    data_json = json.dumps(records, ensure_ascii=False)
    generated = date.today().isoformat()

    template = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>__NAME__量化交易分析面板</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f7fa;
      --panel: #ffffff;
      --ink: #182230;
      --muted: #667085;
      --grid: #e4e7ec;
      --up: #d92d20;
      --down: #039855;
      --accent: #2563eb;
      --warn: #dc6803;
      --line: #475467;
      --soft: #f8fafc;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif;
      color: var(--ink);
      background: var(--bg);
    }
    header {
      padding: 22px 28px 14px;
      border-bottom: 1px solid var(--grid);
      background: var(--panel);
    }
    h1 {
      margin: 0 0 8px;
      font-size: 24px;
      font-weight: 700;
      letter-spacing: 0;
    }
    .meta {
      display: flex;
      flex-wrap: wrap;
      gap: 10px 18px;
      color: var(--muted);
      font-size: 13px;
    }
    main {
      display: grid;
      grid-template-columns: 320px minmax(0, 1fr);
      gap: 16px;
      padding: 16px;
    }
    aside, .right {
      display: grid;
      align-content: start;
      gap: 12px;
      min-width: 0;
    }
    .panel, .stat {
      background: var(--panel);
      border: 1px solid var(--grid);
      border-radius: 8px;
    }
    .stat {
      padding: 13px 14px;
    }
    .stat-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }
    .label {
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 6px;
    }
    .value {
      font-size: 19px;
      font-weight: 700;
      white-space: nowrap;
    }
    .small {
      font-size: 12px;
      color: var(--muted);
      margin-top: 5px;
      line-height: 1.45;
    }
    .panel {
      padding: 14px;
      min-width: 0;
    }
    .panel h2 {
      margin: 0 0 10px;
      font-size: 15px;
      letter-spacing: 0;
    }
    .signal {
      display: grid;
      gap: 8px;
    }
    .signal-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      padding: 8px 0;
      border-bottom: 1px solid var(--grid);
      font-size: 13px;
    }
    .signal-row:last-child { border-bottom: 0; }
    .badge {
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      padding: 3px 8px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      background: #eef4ff;
      color: #175cd3;
      white-space: nowrap;
    }
    .badge.up { background: #fef3f2; color: var(--up); }
    .badge.down { background: #ecfdf3; color: var(--down); }
    .badge.warn { background: #fffaeb; color: var(--warn); }
    .table {
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
    }
    .table th, .table td {
      padding: 7px 6px;
      border-bottom: 1px solid var(--grid);
      text-align: right;
      white-space: nowrap;
    }
    .table th:first-child, .table td:first-child { text-align: left; }
    .table th { color: var(--muted); font-weight: 600; }
    .toolbar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin-bottom: 8px;
      color: var(--muted);
      font-size: 13px;
    }
    .legend {
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
    }
    .dot {
      display: inline-block;
      width: 10px;
      height: 10px;
      border-radius: 50%;
      margin-right: 5px;
      vertical-align: -1px;
    }
    canvas {
      width: 100%;
      display: block;
    }
    #priceChart { height: 560px; }
    .subcharts {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
    }
    .subcharts canvas { height: 260px; }
    .footnote {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.6;
    }
    @media (max-width: 980px) {
      main { grid-template-columns: 1fr; }
      .subcharts { grid-template-columns: 1fr; }
    }
    @media (max-width: 560px) {
      header { padding: 18px 16px 12px; }
      main { padding: 12px; }
      .stat-grid { grid-template-columns: 1fr; }
      #priceChart { height: 520px; }
    }
  </style>
</head>
<body>
  <header>
    <h1>__NAME__（__TS_CODE__）量化交易分析面板</h1>
    <div class="meta">
      <span>数据来源：Tushare daily（未复权日线）</span>
      <span>区间：__FIRST__ - __LAST__</span>
      <span>生成日期：__GENERATED__</span>
      <span id="dataStatus">等待计算</span>
    </div>
  </header>
  <main>
    <aside>
      <section class="stat-grid" id="summaryStats"></section>
      <section class="panel">
        <h2>交易信号</h2>
        <div class="signal" id="signals"></div>
      </section>
      <section class="panel">
        <h2>关键价位</h2>
        <table class="table" id="levelsTable"></table>
      </section>
      <section class="panel">
        <h2>回测结果</h2>
        <table class="table" id="backtestTable"></table>
        <div class="small">策略：MA5 上穿 MA20 买入，下穿卖出；收益按收盘价计算，未计手续费和滑点。</div>
      </section>
      <section class="panel footnote">
        本页面所有指标都由内嵌的 Tushare 最新数据在浏览器端计算。重新运行下载脚本后，CSV、JSON、K 线、指标和回测结果会同步更新。
      </section>
    </aside>
    <section class="right">
      <section class="panel">
        <div class="toolbar">
          <div class="legend">
            <span><i class="dot" style="background: var(--up)"></i>上涨</span>
            <span><i class="dot" style="background: var(--down)"></i>下跌</span>
            <span><i class="dot" style="background: #f59e0b"></i>MA5</span>
            <span><i class="dot" style="background: #2563eb"></i>MA20</span>
            <span><i class="dot" style="background: #7c3aed"></i>MA60</span>
            <span><i class="dot" style="background: #98a2b3"></i>布林带</span>
          </div>
          <div id="hoverInfo">悬停查看单日 OHLC、成交量和指标</div>
        </div>
        <canvas id="priceChart"></canvas>
      </section>
      <section class="subcharts">
        <section class="panel">
          <h2>MACD</h2>
          <canvas id="macdChart"></canvas>
        </section>
        <section class="panel">
          <h2>RSI / KDJ</h2>
          <canvas id="oscChart"></canvas>
        </section>
        <section class="panel">
          <h2>策略净值 vs 买入持有</h2>
          <canvas id="equityChart"></canvas>
        </section>
        <section class="panel">
          <h2>日收益率分布</h2>
          <canvas id="returnChart"></canvas>
        </section>
      </section>
    </section>
  </main>
  <script>
    const records = __DATA__;
    const $ = id => document.getElementById(id);
    const n = v => Number(v);
    const fmtDate = s => `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6)}`;
    const fmtPct = v => Number.isFinite(v) ? `${(v * 100).toFixed(2)}%` : '--';
    const fmtNum = (v, d = 2) => Number.isFinite(v) ? v.toFixed(d) : '--';
    const fmtInt = v => Number.isFinite(v) ? Math.round(v).toLocaleString() : '--';
    const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    const upColor = css('--up');
    const downColor = css('--down');
    const accentColor = css('--accent');
    const gridColor = css('--grid');
    const mutedColor = css('--muted');

    function sma(values, period) {
      const out = Array(values.length).fill(null);
      let sum = 0;
      for (let i = 0; i < values.length; i++) {
        sum += values[i];
        if (i >= period) sum -= values[i - period];
        if (i >= period - 1) out[i] = sum / period;
      }
      return out;
    }

    function ema(values, period) {
      const out = Array(values.length).fill(null);
      const k = 2 / (period + 1);
      let prev = null;
      values.forEach((value, i) => {
        prev = prev === null ? value : value * k + prev * (1 - k);
        out[i] = prev;
      });
      return out;
    }

    function std(values, end, period) {
      if (end < period - 1) return null;
      const slice = values.slice(end - period + 1, end + 1);
      const avg = slice.reduce((a, b) => a + b, 0) / period;
      const variance = slice.reduce((a, b) => a + (b - avg) ** 2, 0) / period;
      return Math.sqrt(variance);
    }

    function rsi(values, period) {
      const out = Array(values.length).fill(null);
      for (let i = period; i < values.length; i++) {
        let gain = 0, loss = 0;
        for (let j = i - period + 1; j <= i; j++) {
          const diff = values[j] - values[j - 1];
          if (diff >= 0) gain += diff; else loss -= diff;
        }
        out[i] = loss === 0 ? 100 : 100 - 100 / (1 + gain / loss);
      }
      return out;
    }

    function kdj(highs, lows, closes, period = 9) {
      const k = Array(closes.length).fill(null);
      const d = Array(closes.length).fill(null);
      const j = Array(closes.length).fill(null);
      let prevK = 50, prevD = 50;
      for (let i = 0; i < closes.length; i++) {
        if (i < period - 1) continue;
        const h = Math.max(...highs.slice(i - period + 1, i + 1));
        const l = Math.min(...lows.slice(i - period + 1, i + 1));
        const rsv = h === l ? 50 : (closes[i] - l) / (h - l) * 100;
        prevK = prevK * 2 / 3 + rsv / 3;
        prevD = prevD * 2 / 3 + prevK / 3;
        k[i] = prevK;
        d[i] = prevD;
        j[i] = 3 * prevK - 2 * prevD;
      }
      return { k, d, j };
    }

    function maxDrawdown(series) {
      let peak = series[0] || 1;
      let maxDd = 0;
      series.forEach(v => {
        if (v > peak) peak = v;
        maxDd = Math.min(maxDd, v / peak - 1);
      });
      return maxDd;
    }

    function streaks(returns) {
      let up = 0, down = 0, maxUp = 0, maxDown = 0;
      returns.forEach(v => {
        if (v > 0) { up += 1; down = 0; }
        else if (v < 0) { down += 1; up = 0; }
        else { up = 0; down = 0; }
        maxUp = Math.max(maxUp, up);
        maxDown = Math.max(maxDown, down);
      });
      return { maxUp, maxDown };
    }

    function backtest(closes, maFast, maSlow) {
      const equity = Array(closes.length).fill(1);
      const trades = [];
      let position = 0;
      let entry = null;
      for (let i = 1; i < closes.length; i++) {
        const crossUp = maFast[i - 1] !== null && maSlow[i - 1] !== null && maFast[i - 1] <= maSlow[i - 1] && maFast[i] > maSlow[i];
        const crossDown = maFast[i - 1] !== null && maSlow[i - 1] !== null && maFast[i - 1] >= maSlow[i - 1] && maFast[i] < maSlow[i];
        if (!position && crossUp) {
          position = 1;
          entry = { date: records[i].trade_date, price: closes[i] };
        } else if (position && crossDown) {
          trades.push({ entry, exit: { date: records[i].trade_date, price: closes[i] }, ret: closes[i] / entry.price - 1 });
          position = 0;
          entry = null;
        }
        equity[i] = equity[i - 1] * (position ? closes[i] / closes[i - 1] : 1);
      }
      if (position && entry) {
        trades.push({ entry, exit: { date: records.at(-1).trade_date, price: closes.at(-1) }, ret: closes.at(-1) / entry.price - 1, open: true });
      }
      const closed = trades.filter(t => !t.open);
      const wins = closed.filter(t => t.ret > 0);
      const losses = closed.filter(t => t.ret <= 0);
      const avgWin = wins.length ? wins.reduce((s, t) => s + t.ret, 0) / wins.length : 0;
      const avgLoss = losses.length ? Math.abs(losses.reduce((s, t) => s + t.ret, 0) / losses.length) : 0;
      return {
        equity,
        trades,
        totalReturn: equity.at(-1) - 1,
        maxDd: maxDrawdown(equity),
        winRate: closed.length ? wins.length / closed.length : 0,
        payoff: avgLoss ? avgWin / avgLoss : null,
      };
    }

    const closes = records.map(r => n(r.close));
    const opens = records.map(r => n(r.open));
    const highs = records.map(r => n(r.high));
    const lows = records.map(r => n(r.low));
    const vols = records.map(r => n(r.vol));
    const returns = closes.map((c, i) => i ? c / closes[i - 1] - 1 : 0);
    const ma5 = sma(closes, 5);
    const ma10 = sma(closes, 10);
    const ma20 = sma(closes, 20);
    const ma60 = sma(closes, 60);
    const volMa5 = sma(vols, 5);
    const volMa20 = sma(vols, 20);
    const ema12 = ema(closes, 12);
    const ema26 = ema(closes, 26);
    const dif = closes.map((_, i) => ema12[i] - ema26[i]);
    const dea = ema(dif, 9);
    const macd = dif.map((v, i) => (v - dea[i]) * 2);
    const rsi6 = rsi(closes, 6);
    const rsi14 = rsi(closes, 14);
    const kd = kdj(highs, lows, closes);
    const bollMid = ma20;
    const bollStd = closes.map((_, i) => std(closes, i, 20));
    const bollUp = bollMid.map((v, i) => v === null || bollStd[i] === null ? null : v + 2 * bollStd[i]);
    const bollDown = bollMid.map((v, i) => v === null || bollStd[i] === null ? null : v - 2 * bollStd[i]);
    const buyHold = closes.map(c => c / closes[0]);
    const test = backtest(closes, ma5, ma20);
    const latest = records.length - 1;
    const last = records[latest];
    const latestClose = closes[latest];
    const totalReturn = latestClose / closes[0] - 1;
    const avgRet = returns.slice(1).reduce((a, b) => a + b, 0) / Math.max(1, returns.length - 1);
    const stdRet = Math.sqrt(returns.slice(1).reduce((a, b) => a + (b - avgRet) ** 2, 0) / Math.max(1, returns.length - 2));
    const annualVol = stdRet * Math.sqrt(252);
    const sharpe = annualVol ? avgRet * 252 / annualVol : null;
    const maxDd = maxDrawdown(buyHold);
    const volumeRatio = volMa20[latest] ? vols[latest] / volMa20[latest] : null;
    const atr14 = sma(records.map((r, i) => {
      if (!i) return highs[i] - lows[i];
      return Math.max(highs[i] - lows[i], Math.abs(highs[i] - closes[i - 1]), Math.abs(lows[i] - closes[i - 1]));
    }), 14);
    const streak = streaks(returns);

    function periodReturn(days) {
      if (records.length <= days) return null;
      return latestClose / closes[records.length - 1 - days] - 1;
    }

    function windowHigh(days) { return Math.max(...highs.slice(Math.max(0, records.length - days))); }
    function windowLow(days) { return Math.min(...lows.slice(Math.max(0, records.length - days))); }

    function classify() {
      const trend = ma20[latest] > ma60[latest] && latestClose > ma20[latest] ? ['多头趋势', 'up'] :
        ma20[latest] < ma60[latest] && latestClose < ma20[latest] ? ['空头趋势', 'down'] : ['震荡整理', 'warn'];
      const momentum = rsi14[latest] >= 70 ? ['动量过热', 'warn'] : rsi14[latest] >= 55 ? ['动量偏强', 'up'] :
        rsi14[latest] <= 30 ? ['超卖修复区', 'warn'] : rsi14[latest] <= 45 ? ['动量偏弱', 'down'] : ['动量中性', ''];
      const risk = annualVol >= 0.55 ? ['高波动', 'warn'] : annualVol <= 0.25 ? ['低波动', 'up'] : ['正常波动', ''];
      const volPrice = returns[latest] > 0 && volumeRatio > 1.2 ? ['价涨量增', 'up'] :
        returns[latest] < 0 && volumeRatio > 1.2 ? ['价跌量增', 'warn'] :
        volumeRatio > 1.5 ? ['显著放量', 'warn'] : ['量能正常', ''];
      const action = trend[1] === 'up' && momentum[1] !== 'warn' ? ['买入候选', 'up'] :
        trend[1] === 'down' || risk[1] === 'warn' ? ['风险偏高', 'warn'] : ['观察等待', ''];
      return { trend, momentum, risk, volPrice, action };
    }

    function renderStats() {
      const items = [
        ['最新收盘价', fmtNum(latestClose), `最新交易日 ${fmtDate(last.trade_date)}`],
        ['近一年收益', fmtPct(totalReturn), `5/20/60日：${fmtPct(periodReturn(5))} / ${fmtPct(periodReturn(20))} / ${fmtPct(periodReturn(60))}`],
        ['最大回撤', fmtPct(maxDd), `买入持有口径`],
        ['年化波动率', fmtPct(annualVol), `夏普比率 ${fmtNum(sharpe, 2)}`],
        ['成交量', `${fmtInt(vols[latest])} 手`, `20日均量 ${fmtInt(volMa20[latest])}，放量倍数 ${fmtNum(volumeRatio, 2)}x`],
        ['ATR(14)', fmtNum(atr14[latest]), `参考止损：${fmtNum(latestClose - 2 * atr14[latest])}`],
      ];
      $('summaryStats').innerHTML = items.map(([label, value, note]) => `
        <section class="stat"><div class="label">${label}</div><div class="value">${value}</div><div class="small">${note}</div></section>
      `).join('');
      $('dataStatus').textContent = `最新交易日：${fmtDate(last.trade_date)}，共 ${records.length} 个交易日`;
    }

    function renderSignals() {
      const c = classify();
      const rows = [
        ['趋势状态', c.trend],
        ['动量状态', c.momentum],
        ['风险状态', c.risk],
        ['量价关系', c.volPrice],
        ['综合信号', c.action],
        ['均线位置', [`MA5 ${fmtNum(ma5[latest])} / MA20 ${fmtNum(ma20[latest])} / MA60 ${fmtNum(ma60[latest])}`, '']],
      ];
      $('signals').innerHTML = rows.map(([label, [text, cls]]) => `
        <div class="signal-row"><span>${label}</span><span class="badge ${cls}">${text}</span></div>
      `).join('');
    }

    function renderTables() {
      const levels = [
        ['20日高点', windowHigh(20), '20日低点', windowLow(20)],
        ['60日高点', windowHigh(60), '60日低点', windowLow(60)],
        ['120日高点', windowHigh(120), '120日低点', windowLow(120)],
        ['布林上轨', bollUp[latest], '布林下轨', bollDown[latest]],
        ['距离20日高点', latestClose / windowHigh(20) - 1, '距离20日低点', latestClose / windowLow(20) - 1, true],
      ];
      $('levelsTable').innerHTML = '<tr><th>指标</th><th>值</th><th>指标</th><th>值</th></tr>' + levels.map(r => `
        <tr><td>${r[0]}</td><td>${r[4] ? fmtPct(r[1]) : fmtNum(r[1])}</td><td>${r[2]}</td><td>${r[4] ? fmtPct(r[3]) : fmtNum(r[3])}</td></tr>
      `).join('');

      const closedTrades = test.trades.filter(t => !t.open).length;
      const rows = [
        ['策略收益', fmtPct(test.totalReturn)],
        ['买入持有', fmtPct(totalReturn)],
        ['策略最大回撤', fmtPct(test.maxDd)],
        ['交易次数', `${closedTrades}`],
        ['胜率', fmtPct(test.winRate)],
        ['盈亏比', test.payoff === null ? '--' : fmtNum(test.payoff, 2)],
      ];
      $('backtestTable').innerHTML = '<tr><th>指标</th><th>值</th></tr>' + rows.map(r => `<tr><td>${r[0]}</td><td>${r[1]}</td></tr>`).join('');
    }

    function prepCanvas(canvas) {
      const dpr = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();
      canvas.width = Math.max(1, Math.floor(rect.width * dpr));
      canvas.height = Math.max(1, Math.floor(rect.height * dpr));
      const ctx = canvas.getContext('2d');
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, rect.width, rect.height);
      ctx.font = '12px "Microsoft YaHei", Arial';
      return { ctx, w: rect.width, h: rect.height };
    }

    function axis(ctx, area, min, max, ticks = 4) {
      ctx.strokeStyle = gridColor;
      ctx.fillStyle = mutedColor;
      ctx.lineWidth = 1;
      for (let i = 0; i <= ticks; i++) {
        const y = area.top + area.h * i / ticks;
        const value = max - (max - min) * i / ticks;
        ctx.beginPath();
        ctx.moveTo(area.left, y);
        ctx.lineTo(area.left + area.w, y);
        ctx.stroke();
        ctx.fillText(fmtNum(value), 8, y + 4);
      }
    }

    function drawLine(ctx, values, area, min, max, color, width = 1.5) {
      ctx.strokeStyle = color;
      ctx.lineWidth = width;
      ctx.beginPath();
      let started = false;
      values.forEach((v, i) => {
        if (v === null || !Number.isFinite(v)) return;
        const x = area.left + area.w * i / Math.max(1, values.length - 1);
        const y = area.top + (max - v) / (max - min || 1) * area.h;
        if (!started) { ctx.moveTo(x, y); started = true; }
        else ctx.lineTo(x, y);
      });
      ctx.stroke();
    }

    function drawPrice(hoverIndex = -1) {
      const canvas = $('priceChart');
      const { ctx, w, h } = prepCanvas(canvas);
      const pad = { left: 62, right: 18, top: 18, bottom: 34 };
      const priceH = Math.round((h - pad.top - pad.bottom) * 0.66);
      const volTop = pad.top + priceH + 24;
      const volH = h - volTop - pad.bottom;
      const priceVals = [...highs, ...lows, ...ma5.filter(Boolean), ...ma20.filter(Boolean), ...ma60.filter(Boolean), ...bollUp.filter(Boolean), ...bollDown.filter(Boolean)];
      const minP = Math.min(...priceVals);
      const maxP = Math.max(...priceVals);
      const maxVol = Math.max(...vols, ...volMa20.filter(Boolean));
      const xStep = (w - pad.left - pad.right) / records.length;
      const candleW = Math.max(2, Math.min(10, xStep * 0.62));
      const yPrice = p => pad.top + (maxP - p) / (maxP - minP || 1) * priceH;
      const yVol = v => volTop + volH - v / (maxVol || 1) * volH;
      const area = { left: pad.left, top: pad.top, w: w - pad.left - pad.right, h: priceH };
      axis(ctx, area, minP, maxP, 5);
      records.forEach((r, i) => {
        const x = pad.left + i * xStep + xStep / 2;
        const open = opens[i], close = closes[i], high = highs[i], low = lows[i];
        const up = close >= open;
        const color = up ? upColor : downColor;
        ctx.strokeStyle = color;
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.moveTo(x, yPrice(high));
        ctx.lineTo(x, yPrice(low));
        ctx.stroke();
        const y1 = yPrice(Math.max(open, close));
        const y2 = yPrice(Math.min(open, close));
        const bodyH = Math.max(1, y2 - y1);
        if (up) ctx.strokeRect(x - candleW / 2, y1, candleW, bodyH);
        else ctx.fillRect(x - candleW / 2, y1, candleW, bodyH);
        ctx.globalAlpha = 0.55;
        ctx.fillRect(x - candleW / 2, yVol(vols[i]), candleW, volTop + volH - yVol(vols[i]));
        ctx.globalAlpha = 1;
      });
      drawLine(ctx, bollUp, area, minP, maxP, '#98a2b3', 1);
      drawLine(ctx, bollMid, area, minP, maxP, '#98a2b3', 1);
      drawLine(ctx, bollDown, area, minP, maxP, '#98a2b3', 1);
      drawLine(ctx, ma5, area, minP, maxP, '#f59e0b', 1.6);
      drawLine(ctx, ma20, area, minP, maxP, '#2563eb', 1.6);
      drawLine(ctx, ma60, area, minP, maxP, '#7c3aed', 1.6);
      drawLine(ctx, volMa20, { left: pad.left, top: volTop, w: area.w, h: volH }, 0, maxVol, '#475467', 1.4);
      ctx.fillStyle = mutedColor;
      [0, Math.floor(records.length / 4), Math.floor(records.length / 2), Math.floor(records.length * 3 / 4), records.length - 1].forEach(i => {
        const x = pad.left + i * xStep + xStep / 2;
        ctx.fillText(fmtDate(records[i].trade_date), Math.min(x - 34, w - 88), h - 12);
      });
      ctx.fillText('成交量', 8, volTop + 14);
      if (hoverIndex >= 0) {
        const x = pad.left + hoverIndex * xStep + xStep / 2;
        ctx.strokeStyle = accentColor;
        ctx.beginPath();
        ctx.moveTo(x, pad.top);
        ctx.lineTo(x, h - pad.bottom);
        ctx.stroke();
      }
    }

    function drawMacd() {
      const { ctx, w, h } = prepCanvas($('macdChart'));
      const area = { left: 48, top: 16, w: w - 62, h: h - 42 };
      const vals = [...dif, ...dea, ...macd].filter(Number.isFinite);
      const min = Math.min(...vals), max = Math.max(...vals);
      axis(ctx, area, min, max, 4);
      const zeroY = area.top + (max - 0) / (max - min || 1) * area.h;
      const step = area.w / records.length;
      macd.forEach((v, i) => {
        const x = area.left + i * step + step / 2;
        const y = area.top + (max - v) / (max - min || 1) * area.h;
        ctx.fillStyle = v >= 0 ? upColor : downColor;
        ctx.fillRect(x - Math.max(1, step * 0.35), Math.min(y, zeroY), Math.max(1, step * 0.7), Math.abs(zeroY - y));
      });
      drawLine(ctx, dif, area, min, max, '#2563eb', 1.5);
      drawLine(ctx, dea, area, min, max, '#f59e0b', 1.5);
    }

    function drawOsc() {
      const { ctx, w, h } = prepCanvas($('oscChart'));
      const area = { left: 48, top: 16, w: w - 62, h: h - 42 };
      axis(ctx, area, 0, 100, 4);
      [30, 70].forEach(v => {
        const y = area.top + (100 - v) / 100 * area.h;
        ctx.strokeStyle = '#fdb022';
        ctx.beginPath();
        ctx.moveTo(area.left, y);
        ctx.lineTo(area.left + area.w, y);
        ctx.stroke();
      });
      drawLine(ctx, rsi6, area, 0, 100, '#2563eb', 1.5);
      drawLine(ctx, rsi14, area, 0, 100, '#7c3aed', 1.5);
      drawLine(ctx, kd.k, area, 0, 100, '#f59e0b', 1.2);
      drawLine(ctx, kd.d, area, 0, 100, '#039855', 1.2);
    }

    function drawEquity() {
      const { ctx, w, h } = prepCanvas($('equityChart'));
      const area = { left: 48, top: 16, w: w - 62, h: h - 42 };
      const vals = [...buyHold, ...test.equity];
      const min = Math.min(...vals), max = Math.max(...vals);
      axis(ctx, area, min, max, 4);
      drawLine(ctx, buyHold, area, min, max, '#98a2b3', 1.5);
      drawLine(ctx, test.equity, area, min, max, '#2563eb', 2);
    }

    function drawReturns() {
      const { ctx, w, h } = prepCanvas($('returnChart'));
      const area = { left: 42, top: 16, w: w - 56, h: h - 42 };
      const data = returns.slice(1);
      const min = Math.min(...data), max = Math.max(...data);
      const bins = 18;
      const counts = Array(bins).fill(0);
      data.forEach(v => {
        const idx = Math.max(0, Math.min(bins - 1, Math.floor((v - min) / (max - min || 1) * bins)));
        counts[idx] += 1;
      });
      const maxCount = Math.max(...counts);
      axis(ctx, area, 0, maxCount, 4);
      const barW = area.w / bins;
      counts.forEach((c, i) => {
        const x = area.left + i * barW;
        const y = area.top + area.h - c / maxCount * area.h;
        const mid = min + (i + 0.5) / bins * (max - min);
        ctx.fillStyle = mid >= 0 ? upColor : downColor;
        ctx.fillRect(x + 2, y, Math.max(2, barW - 4), area.top + area.h - y);
      });
      ctx.fillStyle = mutedColor;
      ctx.fillText(`最大单日涨幅 ${fmtPct(Math.max(...data))}`, area.left, h - 12);
      ctx.fillText(`最大单日跌幅 ${fmtPct(Math.min(...data))}`, Math.max(area.left, w - 170), h - 12);
    }

    function renderAll() {
      renderStats();
      renderSignals();
      renderTables();
      drawPrice();
      drawMacd();
      drawOsc();
      drawEquity();
      drawReturns();
    }

    $('priceChart').addEventListener('mousemove', event => {
      const rect = $('priceChart').getBoundingClientRect();
      const idx = Math.max(0, Math.min(records.length - 1, Math.floor((event.clientX - rect.left - 62) / ((rect.width - 80) / records.length))));
      const r = records[idx];
      $('hoverInfo').textContent = `${fmtDate(r.trade_date)} 开 ${fmtNum(n(r.open))} 高 ${fmtNum(n(r.high))} 低 ${fmtNum(n(r.low))} 收 ${fmtNum(n(r.close))} 量 ${fmtInt(n(r.vol))}手 MA20 ${fmtNum(ma20[idx])} RSI14 ${fmtNum(rsi14[idx])}`;
      drawPrice(idx);
    });
    $('priceChart').addEventListener('mouseleave', () => {
      $('hoverInfo').textContent = '悬停查看单日 OHLC、成交量和指标';
      drawPrice();
    });
    window.addEventListener('resize', renderAll);
    renderAll();
  </script>
</body>
</html>
"""
    html = (
        template
        .replace("__NAME__", NAME)
        .replace("__TS_CODE__", TS_CODE)
        .replace("__FIRST__", first)
        .replace("__LAST__", last)
        .replace("__GENERATED__", generated)
        .replace("__DATA__", data_json)
    )
    path.write_text(html, encoding="utf-8")


def main() -> None:
    out_dir = ROOT / "data" / "gigadevice"
    docs_dir = ROOT / "docs"
    out_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)

    token = read_tushare_token()
    records = fetch_daily(token)
    if not records:
        raise RuntimeError("No daily records returned by Tushare")

    first = records[0]["trade_date"]
    last = records[-1]["trade_date"]
    json_path = out_dir / f"603986_SH_daily_{first}_{last}.json"
    csv_path = out_dir / f"603986_SH_daily_{first}_{last}.csv"
    latest_json_path = out_dir / "603986_SH_daily_latest.json"
    latest_csv_path = out_dir / "603986_SH_daily_latest.csv"
    dashboard_path = ROOT / "gigadevice_dashboard.html"
    root_index_path = ROOT / "index.html"
    docs_index_path = docs_dir / "index.html"

    payload = json.dumps(records, ensure_ascii=False, indent=2)
    json_path.write_text(payload, encoding="utf-8")
    latest_json_path.write_text(payload, encoding="utf-8")
    write_csv(csv_path, records)
    write_csv(latest_csv_path, records)
    write_html(dashboard_path, records)
    shutil.copyfile(dashboard_path, root_index_path)
    shutil.copyfile(dashboard_path, docs_index_path)

    print(f"records={len(records)}")
    print(f"date_range={first}-{last}")
    print(f"json={json_path}")
    print(f"csv={csv_path}")
    print(f"latest_json={latest_json_path}")
    print(f"latest_csv={latest_csv_path}")
    print(f"html={dashboard_path}")
    print(f"root_index={root_index_path}")
    print(f"docs_index={docs_index_path}")


if __name__ == "__main__":
    main()
