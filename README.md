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
Stooq (SPY and 11 sector ETFs), and FRED (4 macro series). It validates exchange
sessions, prices, volume, duplicates, missing bars, freshness, common-session alignment,
and cross-source adjusted-return differences. Individual coverage >=99.5%,
core common-session coverage >=99%; cross-source median absolute return difference
<=10 bps and 95th percentile <=50 bps are provisional engineering checks, not trading edge.
Only the quality report is published in logs/artifacts; no raw historical dataset is exported.
The report explicitly separates intraday, Drive and dashboard gates as NOT_RUN.

The tests are synthetic and run before any network requests.
A successful daily probe does not approve an intraday feed or live trading.
Review provider terms and usage rights before storing or redistributing market data.

## Next gates (not enabled)

1. Review actual daily provider results and resolve failures.
2. Qualify a 5-minute feed, latency, session calendar, rate limits and backfill.
3. Validate private cloud storage and dashboard integration.
4. Only then enable five-minute scheduled collection; GitHub schedules are best effort.
5. Evaluate regression, ACF, PCA, lead-lag and regime/volatility models on aligned history.
