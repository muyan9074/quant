const TUSHARE_API = "https://api.tushare.pro";
const DEFAULT_LOOKBACK_DAYS = 365;
const MAX_SYMBOLS = 20;
const CACHE_TTL_SECONDS = 3600;

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "access-control-allow-origin": "*",
      "access-control-allow-methods": "GET,POST,OPTIONS",
      "access-control-allow-headers": "content-type",
      "cache-control": "no-store",
    },
  });
}

function cacheKey(url) {
  return new Request(url.toString(), { method: "GET" });
}

async function cachedJson(requestUrl, loader) {
  const cache = caches.default;
  const key = cacheKey(requestUrl);
  const cached = await cache.match(key);
  if (cached) return cached;

  const response = json(await loader());
  response.headers.set("cache-control", `public, max-age=${CACHE_TTL_SECONDS}`);
  await cache.put(key, response.clone());
  return response;
}

function yyyymmdd(date) {
  const y = date.getUTCFullYear();
  const m = String(date.getUTCMonth() + 1).padStart(2, "0");
  const d = String(date.getUTCDate()).padStart(2, "0");
  return `${y}${m}${d}`;
}

function defaultDates() {
  const end = new Date();
  const start = new Date(end.getTime() - DEFAULT_LOOKBACK_DAYS * 24 * 60 * 60 * 1000);
  return { startDate: yyyymmdd(start), endDate: yyyymmdd(end) };
}

function parseSymbols(raw) {
  const symbols = String(raw || "")
    .split(",")
    .map((s) => s.trim().toUpperCase())
    .filter(Boolean);
  return Array.from(new Set(symbols));
}

function validateDate(value, name) {
  if (!/^\d{8}$/.test(value)) throw new Error(`${name} must be YYYYMMDD`);
  return value;
}

async function callTushare(env, apiName, params, fields) {
  if (!env.TUSHARE_TOKEN) throw new Error("TUSHARE_TOKEN secret is not configured");
  const res = await fetch(TUSHARE_API, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      api_name: apiName,
      token: env.TUSHARE_TOKEN,
      params,
      fields,
    }),
  });
  const body = await res.json();
  if (!res.ok) throw new Error(`Tushare HTTP ${res.status}`);
  if (body.code !== 0) throw new Error(body.msg || `Tushare error code ${body.code}`);
  const columns = body.data?.fields || [];
  const items = body.data?.items || [];
  return items.map((row) => Object.fromEntries(columns.map((field, i) => [field, row[i]])));
}

function isAdjFactorRateLimit(err) {
  return /adj_factor|频率超限|限频|frequency/i.test(String(err?.message || err));
}

function applyAdjustment(dailyRows, factorRows, adjust) {
  const factorByDate = new Map(factorRows.map((r) => [String(r.trade_date), Number(r.adj_factor)]));
  const sorted = dailyRows
    .filter((r) => factorByDate.has(String(r.trade_date)))
    .sort((a, b) => String(a.trade_date).localeCompare(String(b.trade_date)));

  if (!sorted.length) return [];
  const lastFactor = factorByDate.get(String(sorted[sorted.length - 1].trade_date));

  return sorted.map((r) => {
    const factor = factorByDate.get(String(r.trade_date));
    let ratio = 1;
    if (adjust === "qfq") ratio = factor / lastFactor;
    if (adjust === "hfq") ratio = factor;
    const scale = (value) => Number((Number(value) * ratio).toFixed(4));
    return {
      ts_code: r.ts_code,
      trade_date: String(r.trade_date),
      open: scale(r.open),
      high: scale(r.high),
      low: scale(r.low),
      close: scale(r.close),
      pre_close: scale(r.pre_close),
      change: Number(r.change),
      pct_chg: Number(r.pct_chg),
      vol: Number(r.vol),
      amount: Number(r.amount),
      adj_factor: factor,
      adjust,
    };
  });
}

async function loadSymbol(env, symbol, startDate, endDate, adjust) {
  const params = { ts_code: symbol, start_date: startDate, end_date: endDate };
  const daily = await callTushare(
    env,
    "daily",
    params,
    "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount",
  );
  if (adjust === "none") {
    return {
      rows: daily.sort((a, b) => String(a.trade_date).localeCompare(String(b.trade_date))),
      adjust: "none",
      warnings: [],
    };
  }
  try {
    const factors = await callTushare(env, "adj_factor", params, "ts_code,trade_date,adj_factor");
    return { rows: applyAdjustment(daily, factors, adjust), adjust, warnings: [] };
  } catch (err) {
    if (!isAdjFactorRateLimit(err)) throw err;
    return {
      rows: daily.sort((a, b) => String(a.trade_date).localeCompare(String(b.trade_date))),
      adjust: "none",
      warnings: [`adj_factor unavailable: ${err.message}. Returned unadjusted daily data.`],
    };
  }
}

async function handleDaily(request, env) {
  const url = new URL(request.url);
  let body = {};
  if (request.method === "POST") body = await request.json().catch(() => ({}));

  const defaults = defaultDates();
  const symbols = parseSymbols(body.symbols || url.searchParams.get("symbols"));
  const startDate = validateDate(body.start_date || url.searchParams.get("start_date") || defaults.startDate, "start_date");
  const endDate = validateDate(body.end_date || url.searchParams.get("end_date") || defaults.endDate, "end_date");
  const adjust = String(body.adjust || url.searchParams.get("adjust") || "qfq").toLowerCase();

  if (!symbols.length) throw new Error("symbols is required");
  if (symbols.length > MAX_SYMBOLS) throw new Error(`symbols cannot exceed ${MAX_SYMBOLS}`);
  if (!["none", "qfq", "hfq"].includes(adjust)) throw new Error("adjust must be none, qfq, or hfq");
  if (startDate > endDate) throw new Error("start_date must be earlier than or equal to end_date");

  const data = [];
  for (const symbol of symbols) {
    try {
      const result = await loadSymbol(env, symbol, startDate, endDate, adjust);
      data.push({
        symbol,
        rows: result.rows,
        status: "ok",
        adjust: result.adjust,
        requested_adjust: adjust,
        warnings: result.warnings,
        start_date: startDate,
        end_date: endDate,
      });
    } catch (err) {
      data.push({ symbol, rows: [], status: "error", error: err.message });
    }
  }
  return json({ data });
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") return json({});
    const url = new URL(request.url);
    try {
      if (url.pathname === "/" || url.pathname === "/health") {
        return json({ ok: true, service: "tushare-proxy" });
      }
      if (url.pathname === "/daily" && request.method === "GET") {
        return cachedJson(url, () => handleDaily(request, env).then((res) => res.json()));
      }
      if (url.pathname === "/daily") return handleDaily(request, env);
      return json({ error: "Not found" }, 404);
    } catch (err) {
      return json({ error: err.message }, 400);
    }
  },
};
