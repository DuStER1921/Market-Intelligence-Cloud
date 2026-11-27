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

## Phase B — Cloud Feed Acceptance (manual, not production)

The daily acceptance run #2 at 2026-11-27 12:03:52 UTC confirmed 27/27 Yahoo
and 12/12 SIP daily instruments, 1,987 common sessions, 12/12 return crosschecks,
and 22/22 offline tests. Historical 5-minute SIP: 936/936; IEX: 935/936
(one XLRE bar missing). Evidence:
https://github.com/DuStER1921/Market-Intelligence-Cloud/actions/runs/45995471618/job/140493669426

Both previously deprecated Node 20 actions now use v6 (Node 24).
New cloud run required to confirm warning removal.

Run **Actions → CLOUD FEED ACCEPTANCE → Run workflow → main → market**.
Choose crypto any time, stock or both during regular NYSE trading after the
first 5-minute bar becomes eligible with a 17-minute delay (09:52 ET or later).
The stock probe uses an exact regular-session grid and checks delayed
current-session availability once. Closed or too early is NOT_RUN, not PASS.
The crypto probe uses Binance public market-data-only endpoint, 27 fixed USDT
pairs, 300 closed 5-minute bars each, exact common cutoff, and validates OHLCV,
taker volume, trade count and time sequence. Provider refusals are not bypassed.
A single successful probe is not proof of sustained availability or production readiness.
There are now 41 offline tests across feed validation and rotation metrics
(22 previously passed; 19 added, not yet executed).

## Phase C — Rotation metrics contract (pure function, not wired to real feed)

`scripts/rotation_metrics.py` accepts 122+ consecutive expected sessions of
adjusted closes (SPY + 11 sector ETFs) and raw regular-session dollar turnover
(11 sector ETFs only). The caller must supply a validated session calendar and
appropriate raw turnover; adjusted prices or adjusted volume must not be used for
raw turnover. Prefer VWAP × volume; otherwise label close × volume as a proxy.
The function calculates descriptive 1/5/20-day relative return, prior-120-session
OLS beta and residual z-score, prior-20-session turnover RVOL and share ratio,
5-session relative persistence and sector ETF participation. No future data
enters the rolling fit. No claim of ETF creation/redemption flow, constituent
breadth, predictive edge or profit. Missing symbols, missing sessions, nonfinite
data or invalid denominators fail closed. No actual results are published in this stage.

Production gates remain: sustained intraday reliability and backfill, private
output destination and data usage rights, integration on real data, research
validation with chronological holdouts and costs, then scheduling. Keep crypto
automation and local SOL projects untouched.
