# Polygon.io API Notes

## Authentication
- API key passed as query param: `?apiKey=xxx` or header `Authorization: Bearer xxx`
- Key sourced from `POLYGON_API_KEY` environment variable

## Aggregates (Bars) Endpoint
- `GET /v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from}/{to}`
- `timespan`: minute, hour, day, week, month, quarter, year
- `multiplier`: 1, 5, 15, etc.
- Date format: YYYY-MM-DD or Unix ms
- **No pagination**: Unlike other Polygon endpoints, aggregates do NOT return `next_url`
- **Result limit**: 50,000 bars per request
  - 1-min bars: ~128 trading days per request (390 min/day)
  - 5-min bars: ~640 trading days
  - Safe strategy: chunk by calendar month (max ~8,580 1-min bars per month)
- `adjusted=true` (default) returns split-adjusted prices
- `sort=asc` returns chronological order

## Response Shape
```json
{
  "ticker": "AAPL",
  "queryCount": 390,
  "resultsCount": 390,
  "adjusted": true,
  "results": [
    {
      "v": 1234567,      // volume
      "vw": 150.1234,    // VWAP
      "o": 149.50,       // open
      "c": 150.25,       // close
      "h": 150.75,       // high
      "l": 149.10,       // low
      "t": 1641220800000, // timestamp (Unix ms)
      "n": 5432          // number of transactions
    }
  ],
  "status": "OK",
  "request_id": "abc123"
}
```

## Ticker Details Endpoint
- `GET /v3/reference/tickers/{ticker}`
- Returns: name, market, locale, type, currency, sic_code, etc.
- Rate limit shared with aggregates

## Ticker Search Endpoint
- `GET /v3/reference/tickers?search={query}&active=true&limit=100`
- Search by name or symbol prefix

## Plan Tier Differences
- **Starter ($29/mo)**: 5 years history, unlimited calls, 15-min delay
- **Developer ($79/mo)**: 10 years history, unlimited calls, 15-min delay
- **Advanced ($199/mo)**: 20+ years history, unlimited calls, real-time
- Code is identical across tiers; API simply returns no data for dates outside plan window

## Rate Limits
- Unlimited API calls on all paid plans
- In practice, use token-bucket at ~50 req/s to be a good citizen
- 429 responses include `Retry-After` header (seconds)

## Gotchas
- Aggregates for non-trading hours return empty (no pre/post-market by default)
- `adjusted=true` means historical splits are reflected -- prices may differ from raw historical
- Timestamps are in UTC (Unix milliseconds)
- Weekends/holidays return no data (expected, not an error)
- Low-liquidity tickers may have sparse minute bars (missing minutes = no trades)
