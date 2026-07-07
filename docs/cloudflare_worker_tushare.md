# Cloudflare Worker Tushare 代理

这个 Worker 用于让 GitHub Pages 前端实时获取 Tushare 数据，同时避免把 Tushare token 暴露在浏览器里。

## 部署

在仓库根目录执行：

```powershell
cd workers
npx wrangler secret put TUSHARE_TOKEN
npx wrangler deploy
```

`TUSHARE_TOKEN` 填你的 Tushare Pro token。部署完成后，Wrangler 会输出类似：

```text
https://tushare-proxy.<your-subdomain>.workers.dev
```

把这个地址填入网页工具的 `Cloudflare Worker 地址` 输入框。

## 接口

健康检查：

```text
GET /health
```

获取日线数据：

```text
GET /daily?symbols=603986.SH,000001.SZ&start_date=20250101&end_date=20260707&adjust=qfq
```

参数：

- `symbols`：Tushare 股票代码，多个代码用英文逗号分隔。
- `start_date`：起始日期，格式 `YYYYMMDD`。不填时默认近一年。
- `end_date`：结束日期，格式 `YYYYMMDD`。不填时默认当前日期。
- `adjust`：复权口径，支持 `qfq`、`hfq`、`none`，默认 `qfq`。

返回格式：

```json
{
  "data": [
    {
      "symbol": "603986.SH",
      "status": "ok",
      "adjust": "qfq",
      "rows": [
        {
          "ts_code": "603986.SH",
          "trade_date": "20260707",
          "open": 120.12,
          "high": 123.45,
          "low": 119.8,
          "close": 122.3,
          "vol": 123456.78,
          "amount": 987654.32
        }
      ]
    }
  ]
}
```

## 安全说明

- 不要把 Tushare token 写进 HTML 或 JavaScript 前端文件。
- Token 只放在 Cloudflare Worker Secret：`TUSHARE_TOKEN`。
- 当前 Worker 默认允许所有来源跨域访问，便于 GitHub Pages 使用。若后续公开给更多人使用，建议把 `access-control-allow-origin` 收窄到你的 Pages 域名。
- Worker 不保存数据；每次请求实时从 Tushare 获取 `daily` 和 `adj_factor`，再返回前复权/后复权后的价格。
