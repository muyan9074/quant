# 多股票海龟交易策略工具 Spec

## 1. 目标与范围

本工具用于基于 A 股前复权日线行情数据执行海龟交易策略回测，支持单支或多支股票同时回测，并输出策略收益、买入持有收益、风险指标、交易明细和可视化结果。

第一版策略口径：

- 面向 A 股普通股票，只做多，不做空。
- 使用 Donchian 通道突破入场和跌破退出。
- 同时支持 System 1（20 日入场 / 10 日退出）、System 2（55 日入场 / 20 日退出）和双系统。
- 使用 `N = ATR(20)` 衡量波动。
- 按账户权益风险比例计算单位仓位。
- 初始突破买入 1 个单位，每上涨 `0.5N` 加仓 1 个单位，最多 4 个单位。
- 使用 `2N` 止损；止损优先于通道退出。
- 信号在收盘后确认，默认下一交易日开盘成交。
- 支持最大回撤停交易。

本 spec 定义海龟策略工具设计。首期开发目标是独立 HTML 页面；暂不要求实现 Python 回测脚本。

## 2. 输入与参数

### 2.1 股票选择

工具必须支持一支或多支 A 股股票。

输入格式使用 Tushare 标准代码：

```text
603986.SH
603986.SH,601988.SH,000001.SZ
```

多支股票独立回测，汇总表中逐支展示结果。单支股票失败不应中断其他股票。

### 2.2 数据来源

网页端支持三种数据来源：

- `Cloudflare Worker 实时获取`：通过现有 Worker `/daily` 接口实时获取 Tushare 日线数据。
- `内置前复权 CSV`：读取仓库内置 `docs/data/stocks/*.csv` 或根目录相对路径 `data/stocks/*.csv`。
- `上传 CSV`：用户在浏览器中上传一支或多支股票 CSV。

默认复权口径：

```text
adjust = qfq
```

CSV 至少必须包含：

| 字段 | 用途 |
|---|---|
| `ts_code` | 股票代码，可缺省并由文件名或输入代码补齐 |
| `trade_date` | 交易日期，格式 `YYYYMMDD` |
| `open` | 下一交易日开盘成交使用 |
| `high` | Donchian 通道和真实波幅计算 |
| `low` | Donchian 通道和真实波幅计算 |
| `close` | 信号、净值、退出和风控检查 |

推荐额外保留：

| 字段 | 用途 |
|---|---|
| `pre_close` | 真实波幅计算；缺失时使用上一交易日收盘价 |
| `vol` | 辅助图表 |
| `amount` | 辅助图表 |
| `adjust` | 展示复权口径 |

### 2.3 回测区间

支持指定回测起止日期：

```text
start_date = YYYYMMDD
end_date = YYYYMMDD
```

默认值：

- `start_date`：可用数据最早日期。
- `end_date`：可用数据最新日期。

回测区间按实际交易日过滤，不补齐自然日。

### 2.4 海龟系统参数

默认参数：

```text
system_mode = dual
entry_short = 20
exit_short = 10
entry_long = 55
exit_long = 20
atr_window = 20
```

`system_mode` 可选值：

```text
short = System 1，仅使用 20/10
long = System 2，仅使用 55/20
dual = 双系统，同时允许 20/10 与 55/20 触发入场
```

约束：

- 入场周期、退出周期和 ATR 周期必须为正整数。
- `entry_short > exit_short`。
- `entry_long > exit_long`。
- `entry_long >= entry_short`。

### 2.5 资金、仓位和加仓

默认参数：

```text
initial_cash = 1000000
risk_per_unit = 0.01
stop_n = 2
add_n = 0.5
max_units = 4
```

含义：

- `risk_per_unit`：每个单位按 `1N/1ATR` 波动承担的风险比例，默认 1%。
- `stop_n`：止损距离，默认 `2N`。
- `add_n`：加仓间隔，默认价格每上涨 `0.5N` 加 1 个单位。
- `max_units`：最大持仓单位数，默认 4。

单位仓位计算：

按经典海龟单位仓位口径，单位股数只使用 `N/ATR` 计算，不乘以止损倍数：

```text
unit_shares = account_equity * risk_per_unit / N
```

`stop_n` 只影响止损距离，不影响单位股数。默认 `stop_n = 2` 时，止损价仍为 `latest_entry_price - 2N`；因此若单单位完整触发 `2N` 止损，单单位实际亏损约为 `2 * risk_per_unit`。

第一版使用浮点份额，便于策略研究；后续可扩展为 100 股整数手。

### 2.6 成本、滑点和风控

默认成本参数沿用双均线工具：

```text
buy_commission = 0.0003
sell_commission = 0.0003
stamp_tax = 0.0005
buy_slippage = 0.0002
sell_slippage = 0.0002
```

默认启用最大回撤停交易：

```text
enable_drawdown_stop = true
max_drawdown_stop_pct = 0.20
```

约束：

- 成本、滑点不能为负数。
- `risk_per_unit`、`max_drawdown_stop_pct` 必须大于 `0` 且小于 `1`。
- `stop_n`、`add_n` 必须大于 `0`。
- `max_units` 必须为正整数。

## 3. 指标计算

### 3.1 Donchian 通道

入场通道使用过去 `entry_window` 个交易日最高价，退出通道使用过去 `exit_window` 个交易日最低价。

为避免前视偏差，当前交易日信号只比较“截至前一交易日”的通道值：

```text
entry_high[t] = max(high[t-entry_window], ..., high[t-1])
exit_low[t] = min(low[t-exit_window], ..., low[t-1])
```

通道未形成前不产生信号。

### 3.2 ATR / N

真实波幅：

```text
TR[t] = max(
  high[t] - low[t],
  abs(high[t] - pre_close[t]),
  abs(low[t] - pre_close[t])
)
```

若 `pre_close` 缺失，则使用前一交易日 `close`。第一条数据没有前收盘价时，`TR = high - low`。

```text
N[t] = rolling_mean(TR, atr_window)
```

N 未形成或 `N <= 0` 时，不允许入场、加仓或更新止损。

## 4. 策略规则

### 4.1 入场信号

空仓且未触发最大回撤停交易时：

- System 1：`close[t] > entry_high_short[t]`。
- System 2：`close[t] > entry_high_long[t]`。

不同 `system_mode` 的处理：

- `short`：只检查 System 1。
- `long`：只检查 System 2。
- `dual`：同时检查 System 1 和 System 2；若同一日同时触发，优先使用 System 1 作为入场系统。

生成入场信号后，下一交易日开盘买入 1 个单位。

第一版不实现经典海龟规则中“System 1 上次盈利后跳过下一次 20 日突破”的过滤。

### 4.2 加仓信号

持仓状态下，若未达到 `max_units`，并且：

```text
close[t] >= last_entry_price + add_n * entry_N
```

则生成加仓信号，下一交易日开盘买入 1 个单位。

说明：

- `last_entry_price` 为最近一次实际买入成交价。
- `entry_N` 为最近一次买入信号日使用的 N。
- 若一日涨幅跨过多个加仓阶梯，第一版每个交易日最多只生成一个加仓信号。

### 4.3 退出信号

持仓状态下：

- 止损退出：`close[t] <= stop_price`。
- System 1 通道退出：持仓系统为 System 1 且 `close[t] < exit_low_short[t]`。
- System 2 通道退出：持仓系统为 System 2 且 `close[t] < exit_low_long[t]`。
- 最大回撤停交易：策略净值回撤达到阈值。

退出优先级：

1. 最大回撤停交易。
2. `2N` 止损。
3. Donchian 通道退出。

触发退出后，下一交易日开盘整仓卖出。

### 4.4 仓位状态

- 空仓期间资金保持现金。
- 入场后记录持仓系统、每个单位的入场日期、入场价、入场 N 和份额。
- 每次加仓后，整仓止损价更新为：

```text
stop_price = latest_entry_price - stop_n * latest_entry_N
```

- 退出时整仓卖出，并汇总为一笔完整交易。
- 不做空，不反向开仓。

## 5. 交易执行

### 5.1 信号日与成交日

第 `t` 日收盘后产生信号，第 `t+1` 个交易日开盘价成交。

若信号日为回测区间最后一个交易日，没有下一交易日，则不执行该信号，并在风控或事件信息中标注为未成交。

### 5.2 买入成交

买入成交价：

```text
buy_price = next_open * (1 + buy_slippage)
```

买入单位金额：

```text
gross_buy_amount = unit_shares * buy_price
buy_fee = gross_buy_amount * buy_commission
```

若现金不足以买入完整计算单位，则按可用现金缩小该单位份额；若可用现金不足以形成正份额，则跳过该信号。

### 5.3 卖出成交

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

## 6. 输出设计

### 6.1 页面输出

独立 HTML 页面至少包含：

- 参数面板：数据来源、股票代码、回测区间、系统模式、通道参数、ATR 参数、仓位参数、成本和风控。
- 核心指标卡片。
- 多股票汇总表。
- 策略净值对比图。
- 价格、Donchian 通道、买入点、加仓点、卖出点图。
- N / ATR 曲线。
- 交易明细表。
- 风控事件表。

### 6.2 交易明细字段

| 字段 | 含义 |
|---|---|
| `ts_code` | 股票代码 |
| `system` | `S1` 或 `S2` |
| `entry_signal_date` | 初始入场信号日期 |
| `entry_date` | 初始入场成交日期 |
| `exit_signal_date` | 退出信号日期 |
| `exit_date` | 退出成交日期 |
| `exit_reason` | `channel_exit` / `stop_loss` / `max_drawdown_stop` / `end_of_backtest` |
| `units` | 退出前持有单位数 |
| `add_count` | 加仓次数 |
| `avg_entry_price` | 加权平均入场价 |
| `exit_price` | 卖出成交价 |
| `holding_days` | 持有交易日数量 |
| `gross_return` | 未扣成本收益率 |
| `net_return` | 扣成本收益率 |
| `total_cost` | 本笔交易总成本 |

### 6.3 风控事件字段

| 字段 | 含义 |
|---|---|
| `ts_code` | 股票代码 |
| `event_date` | 触发日期 |
| `event_type` | `stop_loss` / `max_drawdown_stop` |
| `trigger_value` | 触发价格、回撤或净值 |
| `threshold` | 阈值 |
| `execution_date` | 实际执行日期 |
| `execution_price` | 实际执行价格 |
| `status` | `executed` / `not_executed_no_next_day` / `halted_no_position` |

### 6.4 汇总指标

单股结果和多股汇总表应包含：

- 策略累计收益。
- 买入持有收益。
- 超额收益，计算为策略累计收益减去同期国债收益。
- 年化收益。
- 最大回撤。
- 夏普比率。
- 胜率。
- 交易次数。
- 盈亏比。
- 平均持有天数。
- 加仓次数。
- 止损次数。
- 最大回撤停交易是否触发。

## 7. 未来命令行接口

后续若新增 Python 脚本，建议路径：

```text
scripts/turtle_strategy.py
```

建议命令行示例：

```powershell
python scripts/turtle_strategy.py `
  --symbols 603986.SH,601988.SH `
  --start-date 20250101 `
  --end-date 20260703 `
  --adjust qfq `
  --system-mode dual `
  --entry-short 20 `
  --exit-short 10 `
  --entry-long 55 `
  --exit-long 20 `
  --atr-window 20 `
  --risk-per-unit 0.01 `
  --stop-n 2 `
  --add-n 0.5 `
  --max-units 4
```

## 8. 校验规则与边界情况

### 8.1 参数校验

必须校验：

- 股票代码不能为空。
- 起始日期小于等于结束日期。
- 入场、退出和 ATR 周期为正整数。
- `entry_short > exit_short`。
- `entry_long > exit_long`。
- `entry_long >= entry_short`。
- `risk_per_unit` 大于 0 且小于 1。
- `stop_n`、`add_n` 大于 0。
- `max_units` 为正整数。
- 成本和滑点不能为负数。
- 最大回撤阈值大于 0 且小于 1。

### 8.2 数据校验

必须校验：

- 数据包含 `trade_date/open/high/low/close`。
- 日期升序。
- 开盘价、最高价、最低价、收盘价为正数。
- `high >= low`。
- 回测区间内有效交易日数量大于 `max(entry_long, atr_window) + 2`。

### 8.3 交易边界

必须处理：

- N 未形成时不产生交易信号。
- 空仓状态下只处理入场，不处理退出。
- 达到最大单位数后不再加仓。
- 同一交易日最多生成一个加仓信号。
- 最后一日信号因没有下一交易日开盘价不执行。
- 现金不足时缩小单位份额或跳过买入。

### 8.4 风控边界

必须处理：

- 止损优先于通道退出。
- 最大回撤停交易优先级最高。
- 最大回撤停交易触发后不再开新仓。
- 触发最大回撤时若无持仓，记录为停交易事件但不生成卖出交易。
- 触发风控后的成交按下一交易日开盘价执行。

### 8.5 多股票边界

必须处理：

- 每支股票按自身交易日独立回测。
- 对比净值图按各自首个有效回测日归一化为 `1.0`。
- 某支股票数据缺失或参数不足时，在汇总表标注失败原因，不中断其他股票。

## 9. 测试计划

### 9.1 单股票基础回测

使用：

```text
symbols = 603986.SH
system_mode = dual
默认通道、ATR、仓位、成本和风控
```

预期：

- 产生 N、Donchian 通道和净值曲线。
- 入场、加仓、退出标记正常显示。
- 交易明细包含系统、单位数、加仓次数和收益。

### 9.2 多股票对比

使用内置：

```text
603986.SH,601988.SH
```

预期：

- 汇总表包含两支股票。
- 单支股票失败不影响另一支。
- 净值对比图正常绘制。

### 9.3 参数变化

测试：

- `20/10`、`55/20`、双系统切换。
- `risk_per_unit` 改变单位仓位和收益波动。
- `max_units` 改变加仓次数。
- `stop_n` 和 `add_n` 改变退出与加仓行为。

### 9.4 边界与错误提示

测试：

- 数据少于 `max(entry_long, atr_window) + 2` 日时提示数据不足。
- 最后一日出现入场或退出信号时不执行。
- N 为 0 或价格非法时不交易并提示。
- 浏览器控制台无脚本错误，表格和图表不溢出。

## 10. 假设与后续扩展

### 10.1 当前假设

- 第一版只做 A 股多头研究，不做空。
- 默认使用前复权 `qfq` 数据。
- 使用浮点份额，不强制 100 股整数手。
- 不实现 System 1 上次盈利后的跳过过滤。
- 网页端不保存用户数据或交易结果。

### 10.2 后续扩展

后续可扩展：

- 100 股整数手。
- System 1 盈利过滤。
- 做空或期货合约乘数。
- 指数基准。
- Python 批量报告。
- 多策略同屏比较。
- 参数网格搜索和热力图。
