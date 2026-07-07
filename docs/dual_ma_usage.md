# 双均线策略工具使用说明

## 数据来源与复权口径

双均线策略工具默认直接从 Tushare 获取行情数据，并生成前复权数据缓存。

默认复权参数：

```text
--adjust qfq
```

工具使用 Tushare `daily + adj_factor` 生成复权行情：

```text
前复权价格 = 原始价格 * 当日复权因子 / 最新复权因子
后复权价格 = 原始价格 * 当日复权因子 / 首日复权因子
```

缓存文件位置：

```text
data/stocks/603986_SH_daily_qfq.csv
data/stocks/603986_SH_daily_hfq.csv
data/stocks/603986_SH_daily_none.csv
```

其中 `qfq` 是默认口径，适合双均线、RSI、MACD、布林带等技术指标和普通策略回测。

## 基础运行

默认运行兆易创新 `603986.SH`，使用前复权数据、MA5/MA20、默认成本和默认风控：

```powershell
python scripts/dual_ma_strategy.py
```

如果本地没有 `qfq` 缓存，工具会尝试从 Tushare 拉取并生成：

```text
data/stocks/603986_SH_daily_qfq.csv
```

## 强制刷新 Tushare 数据

```powershell
python scripts/dual_ma_strategy.py `
  --symbols 603986.SH `
  --adjust qfq `
  --refresh-data true
```

## 多股票回测

```powershell
python scripts/dual_ma_strategy.py `
  --symbols 603986.SH,000001.SZ,300750.SZ `
  --adjust qfq `
  --start-date 20250101 `
  --end-date 20260703
```

如果某支股票拉取失败或本地数据不足，会在 `summary.csv` 中记录失败原因，不中断其他股票。

## 调整均线、成本和风控

```powershell
python scripts/dual_ma_strategy.py `
  --symbols 603986.SH `
  --adjust qfq `
  --fast-window 10 `
  --slow-window 60 `
  --buy-commission 0.0003 `
  --sell-commission 0.0003 `
  --stamp-tax 0.0005 `
  --buy-slippage 0.0002 `
  --sell-slippage 0.0002 `
  --enable-stop-loss true `
  --stop-loss-pct 0.08 `
  --enable-drawdown-stop true `
  --max-drawdown-stop-pct 0.20
```

## 输出文件

```text
reports/dual_ma/summary.csv
reports/dual_ma/comparison.html
reports/dual_ma/{ts_code}_trades.csv
reports/dual_ma/{ts_code}_equity_curve.csv
reports/dual_ma/{ts_code}_risk_events.csv
reports/dual_ma/{ts_code}_report.html
```

重点查看：

- `comparison.html`：多股票对比报告。
- `{ts_code}_report.html`：单股票策略报告。
- `{ts_code}_trades.csv`：交易明细。
- `{ts_code}_risk_events.csv`：止损和最大回撤风控事件。
