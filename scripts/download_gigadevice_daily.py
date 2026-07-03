import csv
import json
import re
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CODEX_CONFIG = Path.home() / ".codex" / "config.toml"
TS_CODE = "603986.SH"
NAME = "兆易创新"
START_DATE = "20250701"
END_DATE = "20260701"
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
            "start_date": START_DATE,
            "end_date": END_DATE,
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
    first = records[0]["trade_date"] if records else START_DATE
    last = records[-1]["trade_date"] if records else END_DATE
    max_close = max((float(r["close"]) for r in records), default=0)
    min_close = min((float(r["close"]) for r in records), default=0)
    total_volume = sum(float(r["vol"]) for r in records)
    avg_volume = total_volume / len(records) if records else 0
    data_json = json.dumps(records, ensure_ascii=False)

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{NAME}近一年交易面板</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f5f7fa;
      --panel: #ffffff;
      --ink: #1f2933;
      --muted: #667085;
      --grid: #e4e7ec;
      --up: #d92d20;
      --down: #039855;
      --accent: #2563eb;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif;
      color: var(--ink);
      background: var(--bg);
    }}
    header {{
      padding: 22px 28px 12px;
      border-bottom: 1px solid var(--grid);
      background: var(--panel);
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 24px;
      font-weight: 700;
      letter-spacing: 0;
    }}
    .meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px 18px;
      color: var(--muted);
      font-size: 13px;
    }}
    main {{
      display: grid;
      grid-template-columns: 260px minmax(0, 1fr);
      gap: 16px;
      padding: 16px;
    }}
    aside {{
      display: grid;
      align-content: start;
      gap: 10px;
    }}
    .stat, .chart-wrap {{
      background: var(--panel);
      border: 1px solid var(--grid);
      border-radius: 8px;
    }}
    .stat {{
      padding: 14px;
    }}
    .label {{
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 6px;
    }}
    .value {{
      font-size: 20px;
      font-weight: 700;
    }}
    .chart-wrap {{
      min-width: 0;
      padding: 12px;
    }}
    .toolbar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin-bottom: 8px;
      color: var(--muted);
      font-size: 13px;
    }}
    .legend {{
      display: flex;
      gap: 14px;
      flex-wrap: wrap;
    }}
    .dot {{
      display: inline-block;
      width: 10px;
      height: 10px;
      border-radius: 50%;
      margin-right: 6px;
      vertical-align: -1px;
    }}
    canvas {{
      width: 100%;
      height: 620px;
      display: block;
    }}
    @media (max-width: 860px) {{
      main {{ grid-template-columns: 1fr; }}
      canvas {{ height: 560px; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>{NAME}（{TS_CODE}）近一年交易价格与成交量</h1>
    <div class="meta">
      <span>数据来源：Tushare daily</span>
      <span>区间：{first} - {last}</span>
      <span>生成日期：{date.today().isoformat()}</span>
    </div>
  </header>
  <main>
    <aside>
      <section class="stat"><div class="label">交易日数量</div><div class="value">{len(records)}</div></section>
      <section class="stat"><div class="label">收盘价区间</div><div class="value">{min_close:.2f} - {max_close:.2f}</div></section>
      <section class="stat"><div class="label">平均成交量（手）</div><div class="value">{avg_volume:,.0f}</div></section>
      <section class="stat"><div class="label">最新收盘价</div><div class="value">{float(records[-1]["close"]):.2f}</div></section>
    </aside>
    <section class="chart-wrap">
      <div class="toolbar">
        <div class="legend">
          <span><i class="dot" style="background: var(--up)"></i>上涨</span>
          <span><i class="dot" style="background: var(--down)"></i>下跌</span>
          <span><i class="dot" style="background: var(--accent)"></i>成交量</span>
        </div>
        <div id="hoverInfo">悬停查看单日 OHLC 与成交量</div>
      </div>
      <canvas id="chart"></canvas>
    </section>
  </main>
  <script>
    const records = {data_json};
    const canvas = document.getElementById('chart');
    const info = document.getElementById('hoverInfo');
    const ctx = canvas.getContext('2d');

    function n(v) {{ return Number(v); }}
    function fmtDate(s) {{ return `${{s.slice(0, 4)}}-${{s.slice(4, 6)}}-${{s.slice(6)}}`; }}
    function resize() {{
      const dpr = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();
      canvas.width = Math.floor(rect.width * dpr);
      canvas.height = Math.floor(rect.height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      draw();
    }}

    function draw(hoverIndex = -1) {{
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      ctx.clearRect(0, 0, w, h);
      const pad = {{ left: 62, right: 18, top: 18, bottom: 42 }};
      const priceH = Math.round((h - pad.top - pad.bottom) * 0.68);
      const gap = 24;
      const volTop = pad.top + priceH + gap;
      const volH = h - volTop - pad.bottom;
      const plotW = w - pad.left - pad.right;
      const highs = records.map(r => n(r.high));
      const lows = records.map(r => n(r.low));
      const vols = records.map(r => n(r.vol));
      const minP = Math.min(...lows);
      const maxP = Math.max(...highs);
      const pRange = maxP - minP || 1;
      const maxVol = Math.max(...vols) || 1;
      const xStep = plotW / records.length;
      const candleW = Math.max(2, Math.min(10, xStep * 0.62));
      const yPrice = p => pad.top + (maxP - p) / pRange * priceH;
      const yVol = v => volTop + volH - v / maxVol * volH;

      ctx.strokeStyle = '#e4e7ec';
      ctx.lineWidth = 1;
      ctx.font = '12px "Microsoft YaHei", Arial';
      ctx.fillStyle = '#667085';
      for (let i = 0; i <= 5; i++) {{
        const y = pad.top + priceH * i / 5;
        const price = maxP - pRange * i / 5;
        ctx.beginPath();
        ctx.moveTo(pad.left, y);
        ctx.lineTo(w - pad.right, y);
        ctx.stroke();
        ctx.fillText(price.toFixed(2), 8, y + 4);
      }}
      for (let i = 0; i <= 3; i++) {{
        const y = volTop + volH * i / 3;
        ctx.beginPath();
        ctx.moveTo(pad.left, y);
        ctx.lineTo(w - pad.right, y);
        ctx.stroke();
      }}

      records.forEach((r, i) => {{
        const x = pad.left + i * xStep + xStep / 2;
        const open = n(r.open), close = n(r.close), high = n(r.high), low = n(r.low);
        const up = close >= open;
        const color = up ? '#d92d20' : '#039855';
        ctx.strokeStyle = color;
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.moveTo(x, yPrice(high));
        ctx.lineTo(x, yPrice(low));
        ctx.stroke();
        const y1 = yPrice(Math.max(open, close));
        const y2 = yPrice(Math.min(open, close));
        const bodyH = Math.max(1, y2 - y1);
        if (up) {{
          ctx.strokeRect(x - candleW / 2, y1, candleW, bodyH);
        }} else {{
          ctx.fillRect(x - candleW / 2, y1, candleW, bodyH);
        }}
        ctx.globalAlpha = 0.62;
        ctx.fillRect(x - candleW / 2, yVol(n(r.vol)), candleW, volTop + volH - yVol(n(r.vol)));
        ctx.globalAlpha = 1;
      }});

      ctx.fillStyle = '#667085';
      const ticks = [0, Math.floor(records.length / 4), Math.floor(records.length / 2), Math.floor(records.length * 3 / 4), records.length - 1];
      ticks.forEach(i => {{
        const x = pad.left + i * xStep + xStep / 2;
        ctx.fillText(fmtDate(records[i].trade_date), Math.min(x - 34, w - 86), h - 14);
      }});
      ctx.fillText('成交量', 8, volTop + 14);

      if (hoverIndex >= 0 && records[hoverIndex]) {{
        const x = pad.left + hoverIndex * xStep + xStep / 2;
        ctx.strokeStyle = '#2563eb';
        ctx.beginPath();
        ctx.moveTo(x, pad.top);
        ctx.lineTo(x, h - pad.bottom);
        ctx.stroke();
      }}
    }}

    canvas.addEventListener('mousemove', event => {{
      const rect = canvas.getBoundingClientRect();
      const w = canvas.clientWidth;
      const padLeft = 62, padRight = 18;
      const plotW = w - padLeft - padRight;
      const xStep = plotW / records.length;
      const idx = Math.max(0, Math.min(records.length - 1, Math.floor((event.clientX - rect.left - padLeft) / xStep)));
      const r = records[idx];
      info.textContent = `${{fmtDate(r.trade_date)}}  开 ${{n(r.open).toFixed(2)}}  高 ${{n(r.high).toFixed(2)}}  低 ${{n(r.low).toFixed(2)}}  收 ${{n(r.close).toFixed(2)}}  量 ${{n(r.vol).toLocaleString()}}手`;
      draw(idx);
    }});
    canvas.addEventListener('mouseleave', () => {{
      info.textContent = '悬停查看单日 OHLC 与成交量';
      draw();
    }});
    window.addEventListener('resize', resize);
    resize();
  </script>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def main() -> None:
    out_dir = ROOT / "data" / "gigadevice"
    out_dir.mkdir(parents=True, exist_ok=True)
    token = read_tushare_token()
    records = fetch_daily(token)
    if not records:
        raise RuntimeError("No daily records returned by Tushare")

    json_path = out_dir / "603986_SH_daily_20250701_20260701.json"
    csv_path = out_dir / "603986_SH_daily_20250701_20260701.csv"
    html_path = ROOT / "gigadevice_dashboard.html"

    json_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(csv_path, records)
    write_html(html_path, records)

    print(f"records={len(records)}")
    print(f"json={json_path}")
    print(f"csv={csv_path}")
    print(f"html={html_path}")


if __name__ == "__main__":
    main()
