# Market-Intelligence-Cloud
Cloud-based quantitative research, market data collection, sector rotation and cross-asset intelligence.

## Scope and safety

Independent, cloud-only market research. This public repository contains code only.
Do not add API keys, private records, licensed raw market data or private research outputs.
No local or self-hosted runners, no trading or orders, no access to unrelated repositories,
and no automatic writes to Google Drive or ChatGPT Space at this stage.

## Phase A — Daily data feed acceptance

Run **Actions → DATA FEED ACCEPTANCE → Run workflow → main**.
GitHub-hosted Ubuntu, Python 3.11, read-only repository permissions, manual trigger,
12-minute timeout, one concurrent job. No scheduled jobs are enabled.

The probe requests daily history since 2019-01-01 from Yahoo Finance (27 ETFs),
Alpaca SIP (SPY and 11 sector ETFs, all corporate-action adjustments), and FRED (4 macro series). It validates exchange
sessions, prices, volume, duplicates, missing bars, freshness, common-session alignment,
and cross-source adjusted-return differences. Individual coverage >=99.5%,
core common-session coverage >=99%; cross-source median absolute return difference
<=10 bps and 95th percentile <=50 bps are provisional engineering checks, not trading edge.
Only the quality report is published in logs/artifacts; no raw historical dataset is exported.
The report includes a historical 5-minute SIP/IEX probe for the last completed regular session, separately from daily acceptance. Live freshness, sustained intraday availability, Drive and dashboard integration are not approved.

The tests are synthetic and run before any network requests.
A successful daily probe does not approve an intraday feed or live trading.
Review provider terms and usage rights before storing or redistributing market data.

## Next gates (not enabled)

1. Review actual daily provider results and resolve failures.
2. Qualify a 5-minute feed, latency, session calendar, rate limits and backfill.
3. Validate private cloud storage and dashboard integration.
4. Only then enable five-minute scheduled collection; GitHub schedules are best effort.
5. Evaluate regression, ACF, PCA, lead-lag and regime/volatility models on aligned history.

### Alpaca access and independent verification

Stooq is retired from this acceptance workflow because access could not be established.
Set repository Actions secrets ALPACA_API_KEY and ALPACA_SECRET_KEY using the Paper
Trading account. Do not send or store keys in code, logs, issues, artifacts or chat.
The workflow uses only GET https://data.alpaca.markets/v2/stocks/bars, never trading endpoints.
Explicit SIP daily history from 2019 with adjustment=all is required for the independent
crosscheck; IEX is never substituted silently. Pagination is bounded and validated.
SIP and IEX 5-minute raw OHLCV are probed separately on SPY and all 11 sectors for
the previous completed regular session (XNYS calendar including early closes).
The expected grid requires every bar; IEX gaps can reflect venue-specific inactivity,
not necessarily a transport error. A historical probe does not measure live latency.
A 401/403/429 is recorded without URL, response body or credentials. If the account
cannot access SIP, independent verification remains NO_GO; do not buy a subscription
automatically. All 22 offline tests execute before credentials are passed into the probe.
FRED availability does not certify full history or point-in-time release alignment;
BAMLH0A0HYM2 history is provider-limited (https://fred.stlouisfed.org/series/BAMLH0A0HYM2).
No raw market data is exported. No schedule is enabled.
