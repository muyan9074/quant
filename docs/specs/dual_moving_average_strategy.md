# 多股票双均线策略工具 Spec

## 1. 目标与范围

本工具用于基于 A 股前复权日线行情数据执行双均线择时回测，支持单支或多支股票同时回测，并输出策略收益、买入持有收益、风险指标、交易明细和可视化报告。

第一版策略口径：

- 只做多，不做空。
- 短均线上穿长均线后买入。
- 短均线下穿长均线后卖出空仓。
- 信号在收盘后确认，默认下一交易日开盘成交。
- 支持单笔止损和最大回撤停交易两类风险控制。
- 默认直接从 Tushare 获取前复权数据，并缓存到本地。

本 spec 只定义策略工具设计，不要求在本阶段实现策略脚本。

## 2. 输入与参数

### 2.1 股票选择

工具必须支持一支或多支 A 股股票。

输入格式使用 Tushare 标准代码：

```text
603986.SH
603986.SH,000001.SZ,300750.SZ
```

单支股票时，输出完整交易明细、每日净值和单股报告。多支股票时，除单股结果外，还必须输出横向对比报告。

### 2.2 数据来源

优先使用本地前复权 CSV 缓存。若本地缺少指定股票或指定日期区间数据，工具应通过 Tushare 拉取 `daily + adj_factor` 并生成复权行情缓存。

建议缓存路径：

```text
data/stocks/{ts_code_normalized}_daily_{adjust}.csv
```

示例：

```text
data/stocks/603986_SH_daily_qfq.csv
```

复权口径：

```text
adjust = qfq   # 默认，前复权
adjust = hfq   # 后复权
adjust = none  # 不复权
```

默认使用 `qfq` 前复权数据。计算方法：

```text
qfq_price = raw_price * adj_factor / latest_adj_factor
hfq_price = raw_price * adj_factor / first_adj_factor
```

当前项目仍保留兆易创新未复权历史 CSV，可用于对照：

```text
data/gigadevice/603986_SH_daily_latest.csv
```

CSV 至少必须包含：

| 字段 | 用途 |
|---|---|
| `ts_code` | 股票代码 |
| `trade_date` | 交易日期，格式 `YYYYMMDD` |
| `open` | 次日开盘成交使用 |
| `close` | 均线、信号、净值和风控检查使用 |

推荐额外保留：

| 字段 | 用途 |
|---|---|
| `high` | 后续扩展风控或图表 |
| `low` | 后续扩展风控或图表 |
| `pre_close` | 数据一致性校验 |
| `change` | 数据一致性校验 |
| `pct_chg` | 辅助分析 |
| `vol` | 辅助图表 |
| `amount` | 辅助图表 |

### 2.3 回测区间

支持指定回测起止日期：

```text
start_date = YYYYMMDD
end_date = YYYYMMDD
adjust = qfq
```

默认值：

- `start_date`：可用数据最早日期。
- `end_date`：可用数据最新日期。
- `adjust`：默认 `qfq`。

回测区间按实际交易日过滤，不强行补齐自然日或工作日。

### 2.4 均线参数

默认参数：

```text
fast_window = 5
slow_window = 20
```

约束：

- `fast_window` 必须为正整数。
- `slow_window` 必须为正整数。
- `fast_window < slow_window`。

### 2.5 资金、交易成本和滑点

默认初始资金：

```text
initial_cash = 1000000
```

默认成本参数：

```text
buy_commission = 0.0003
sell_commission = 0.0003
stamp_tax = 0.0005
buy_slippage = 0.0002
sell_slippage = 0.0002
```

含义：

- 买入佣金：买入成交金额的比例。
- 卖出佣金：卖出成交金额的比例。
- 印花税：仅卖出时收取。
- 买入滑点：使买入成交价上浮。
- 卖出滑点：使卖出成交价下浮。

### 2.6 风控参数

默认启用两类风控。

```text
enable_stop_loss = true
stop_loss_pct = 0.08
enable_drawdown_stop = true
max_drawdown_stop_pct = 0.20
```

含义：

- `stop_loss_pct = 0.08`：单笔持仓亏损达到 8% 后触发清仓。
- `max_drawdown_stop_pct = 0.20`：策略净值从历史高点回撤达到 20% 后停止后续交易。

约束：

- 风控比例必须大于 `0` 且小于 `1`。
- 成本和滑点不能为负数。

## 3. 策略规则

### 3.1 均线计算

使用收盘价计算短均线和长均线：

```text
MA_fast = rolling_mean(close, fast_window)
MA_slow = rolling_mean(close, slow_window)
```

均线未形成前不产生交易信号。

### 3.2 买入信号

金叉条件：

```text
前一交易日 MA_fast <= MA_slow
当前交易日 MA_fast > MA_slow
```

若当前为空仓，且最大回撤停交易未触发，则生成买入信号。

### 3.3 卖出信号

死叉条件：

```text
前一交易日 MA_fast >= MA_slow
当前交易日 MA_fast < MA_slow
```

若当前持仓，则生成卖出信号。

### 3.4 仓位规则

- 金叉时满仓买入。
- 死叉、单笔止损或最大回撤控制触发时全部卖出。
- 空仓期间资金保持现金。
- 不做空。
- 不加仓。
- 不重复买入。

## 4. 交易执行

### 4.1 信号日与成交日

第 `t` 日收盘后产生信号，第 `t+1` 个交易日开盘价成交。

若信号日为回测区间最后一个交易日，没有下一交易日，则不执行该信号，并在报告中记录为未成交事件。

### 4.2 买入成交

买入成交价：

```text
buy_price = next_open * (1 + buy_slippage)
```

买入佣金：

```text
buy_fee = gross_buy_amount * buy_commission
```

满仓买入时，应确保：

```text
cash_after_buy >= 0
```

可买股数或持仓数量的处理第一版可使用浮点份额，便于策略研究；若后续面向真实 A 股交易，可扩展为 100 股整数手约束。

### 4.3 卖出成交

卖出成交价：

```text
sell_price = next_open * (1 - sell_slippage)
```

卖出成本：

```text
sell_fee = gross_sell_amount * sell_commission
stamp_tax_fee = gross_sell_amount * stamp_tax
```

卖出后全部转为现金。

## 5. 风险控制

### 5.1 单笔止损

单笔止损只在持仓状态下生效。

持仓成本基准为实际买入成交价：

```text
entry_price = buy_price
```

每日收盘后检查：

```text
close / entry_price - 1 <= -stop_loss_pct
```

若触发：

- 在下一交易日开盘价卖出。
- 卖出计入卖出滑点、卖出佣金和印花税。
- 交易退出原因记录为 `stop_loss`。
- 风控事件记录触发日期、触发价格、阈值和实际亏损率。
- 止损清仓后，后续仍可根据新的金叉信号重新开仓，除非最大回撤停交易已触发。

### 5.2 最大回撤停交易

每日基于策略总资产净值计算历史高点：

```text
equity_peak = max(equity_curve)
drawdown = equity / equity_peak - 1
```

每日收盘后检查：

```text
drawdown <= -max_drawdown_stop_pct
```

若触发：

- 风险状态标记为 `halted_by_drawdown`。
- 若当前持仓，则在下一交易日开盘价清仓。
- 清仓后停止后续所有新开仓。
- 后续资金保持现金至回测结束。
- 交易退出原因记录为 `max_drawdown_stop`。
- 风控事件记录触发日期、触发净值、历史峰值、阈值和实际回撤。

### 5.3 退出条件优先级

每日收盘后按以下顺序检查退出条件：

1. 最大回撤控制。
2. 单笔止损。
3. 均线死叉。

若同一日多个退出条件同时满足，只执行最高优先级原因。

若最大回撤控制已触发，不再处理新的买入信号。

## 6. 输出设计

### 6.1 单股票交易明细

文件：

```text
reports/dual_ma/{ts_code}_trades.csv
```

字段：

| 字段 | 含义 |
|---|---|
| `ts_code` | 股票代码 |
| `entry_signal_date` | 买入信号日期 |
| `entry_date` | 实际买入日期 |
| `entry_price` | 买入成交价 |
| `exit_signal_date` | 卖出或风控信号日期 |
| `exit_date` | 实际卖出日期 |
| `exit_price` | 卖出成交价 |
| `exit_reason` | `death_cross` / `stop_loss` / `max_drawdown_stop` / `end_of_backtest` |
| `holding_days` | 持有交易日数量 |
| `gross_return` | 未扣成本收益率 |
| `net_return` | 扣成本收益率 |
| `total_cost` | 本笔交易总成本 |

### 6.2 单股票每日净值

文件：

```text
reports/dual_ma/{ts_code}_equity_curve.csv
```

字段：

| 字段 | 含义 |
|---|---|
| `trade_date` | 交易日期 |
| `position` | 持仓份额或持仓状态 |
| `is_halted` | 是否已触发最大回撤停交易 |
| `cash` | 现金 |
| `position_value` | 持仓市值 |
| `total_asset` | 总资产 |
| `strategy_nav` | 策略净值 |
| `buy_hold_nav` | 买入持有净值 |
| `drawdown` | 策略回撤 |

### 6.3 风控事件

文件：

```text
reports/dual_ma/{ts_code}_risk_events.csv
```

字段：

| 字段 | 含义 |
|---|---|
| `ts_code` | 股票代码 |
| `event_date` | 风控触发日期 |
| `event_type` | `stop_loss` / `max_drawdown_stop` |
| `trigger_value` | 触发时实际亏损率或回撤率 |
| `threshold` | 风控阈值 |
| `execution_date` | 实际清仓日期 |
| `execution_price` | 实际清仓价格 |
| `status` | `executed` / `not_executed_no_next_day` |

### 6.4 单股票汇总指标

单股报告和多股汇总表都应包含：

- 累计收益。
- 年化收益。
- 最大回撤。
- 夏普比率。
- 胜率。
- 交易次数。
- 盈亏比。
- 平均持有天数。
- 止损次数。
- 是否触发最大回撤停交易。
- 买入持有收益。
- 策略相对买入持有的超额收益。

### 6.5 多股票对比输出

文件：

```text
reports/dual_ma/summary.csv
reports/dual_ma/comparison.html
```

`summary.csv` 字段：

| 字段 | 含义 |
|---|---|
| `ts_code` | 股票代码 |
| `status` | `ok` 或失败原因 |
| `start_date` | 实际回测开始日期 |
| `end_date` | 实际回测结束日期 |
| `strategy_return` | 策略累计收益 |
| `buy_hold_return` | 买入持有收益 |
| `excess_return` | 超额收益 |
| `annual_return` | 年化收益 |
| `max_drawdown` | 最大回撤 |
| `sharpe` | 夏普比率 |
| `win_rate` | 胜率 |
| `trade_count` | 交易次数 |
| `stop_loss_count` | 止损次数 |
| `drawdown_stop_triggered` | 是否触发最大回撤停交易 |

`comparison.html` 至少包含：

- 多股票绩效对比表。
- 多股票策略净值对比图。
- 收益 / 回撤散点图。
- 风控触发次数排行。
- 最优和最差策略表现摘要。

## 7. 命令行接口

后续实现脚本建议路径：

```text
scripts/dual_ma_strategy.py
```

命令行示例：

```powershell
python scripts/dual_ma_strategy.py `
  --symbols 603986.SH,000001.SZ `
  --start-date 20250101 `
  --end-date 20260703 `
  --adjust qfq `
  --refresh-data false `
  --fast-window 5 `
  --slow-window 20 `
  --initial-cash 1000000 `
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

默认参数：

```text
symbols = 603986.SH
adjust = qfq
refresh_data = false
lookback_days = 365
fast_window = 5
slow_window = 20
initial_cash = 1000000
buy_commission = 0.0003
sell_commission = 0.0003
stamp_tax = 0.0005
buy_slippage = 0.0002
sell_slippage = 0.0002
enable_stop_loss = true
stop_loss_pct = 0.08
enable_drawdown_stop = true
max_drawdown_stop_pct = 0.20
start_date = 数据最早日期
end_date = 数据最新日期
```

## 8. 校验规则与边界情况

### 8.1 参数校验

必须校验：

- 股票代码不能为空。
- `fast_window < slow_window`。
- 起始日期小于等于结束日期。
- 成本、滑点、止损阈值和最大回撤阈值不能为负数。
- `stop_loss_pct` 和 `max_drawdown_stop_pct` 大于 `0` 且小于 `1`。

### 8.2 数据校验

必须校验：

- 数据包含 `trade_date/open/close`。
- 日期升序。
- 开盘价和收盘价为正数。
- 回测区间内有效交易日数量大于 `slow_window + 2`。

### 8.3 交易边界

必须处理：

- 连续金叉不会重复买入。
- 空仓状态下死叉不会卖出。
- 持仓状态下金叉不会重复加仓。
- 最后一日信号或风控事件因没有下一交易日成交价而不执行，但报告应标注为未成交事件。

### 8.4 风控边界

必须处理：

- 单笔止损只影响当前持仓，不永久停止交易。
- 最大回撤控制一旦触发，后续不再开仓。
- 若最大回撤控制和单笔止损同日触发，优先记录为最大回撤控制。
- 触发风控后的成交按下一交易日开盘价执行，成交价可能不同于触发阈值价格。

### 8.5 多股票边界

必须处理：

- 每支股票按自身交易日独立回测。
- 对比净值图按各自首个有效回测日归一化为 `1.0`。
- 股票数据缺失或参数不满足时，在汇总表中标注失败原因，不中断其他股票回测。

## 9. 测试计划

### 9.1 单股票基础回测

使用：

```text
symbols = 603986.SH
fast_window = 5
slow_window = 20
默认成本
默认风控
```

预期：

- 生成交易明细。
- 生成每日净值。
- 生成风控事件文件。
- 生成单股 HTML 报告。

### 9.2 多股票对比

输入至少两支股票。

预期：

- 汇总表包含每支股票。
- 单支股票失败不影响其他股票。
- 净值对比图正常生成。
- 风控字段正常展示。

### 9.3 参数变化

测试：

- `MA10/MA60` 改变信号和交易结果。
- 不同手续费和滑点影响净收益。
- 不同止损率和最大回撤阈值影响退出原因和停交易状态。
- 不同起止日期正确过滤数据。

### 9.4 风控逻辑

测试：

- 单笔止损触发后退出原因为 `stop_loss`。
- 最大回撤触发后退出原因为 `max_drawdown_stop`。
- 最大回撤触发后不再开新仓。
- 同日多退出条件触发时按优先级处理。

### 9.5 结果一致性

检查：

- 金叉和死叉日期与均线交叉一致。
- 信号日和成交日相差一个交易日。
- 每日总资产 = 现金 + 持仓市值。
- 策略净值从 `1.0` 开始。
- 最大回撤不大于 `0`。

### 9.6 输出检查

检查：

- 输出 CSV 可读。
- HTML 报告可本地打开。
- 图表无空白。
- 浏览器控制台无脚本错误。

## 10. 假设与后续扩展

### 10.1 当前假设

- 第一版以 A 股普通股票为目标，只做多，不做空。
- 默认使用 Tushare `daily + adj_factor` 生成前复权 `qfq` 数据。
- 多股票对比重点比较策略表现，不强行对齐所有股票交易日。
- 成本和风控参数为研究假设，不代表具体券商真实规则。
- 第一版可使用浮点份额，不强制 100 股整数手。

### 10.2 后续扩展

后续可扩展：

- 后复权数据、未复权数据和不同复权口径对比。
- 100 股整数手交易约束。
- 多参数网格搜索。
- 多策略对比。
- 指数基准比较。
- Tushare 自动补数据。
- 将双均线策略模块集成到当前 GitHub Pages 主面板。
