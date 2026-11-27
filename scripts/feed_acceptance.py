"""Read-only, daily-feed acceptance probe. No raw data exported."""
import io
import json
import sys
from datetime import datetime, timedelta
from importlib.metadata import version
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import numpy as np
import pandas as pd
import requests
import yfinance as yf

SECTORS = "XLK XLF XLV XLE XLI XLY XLP XLU XLB XLRE XLC".split()
SYMBOLS = ["SPY", *SECTORS, *"QQQ DIA IWM RSP KBE KRE SMH SOXX HYG LQD TLT IEF SHY GLD SLV".split()]
START = "2019-01-01"
# Exclude current New York date even when the probe runs after close.
END = datetime.now(ZoneInfo("America/New_York")).date()
CAL = xcals.get_calendar("XNYS", start=START, end=str(END))
EXPECTED = pd.DatetimeIndex(CAL.sessions_in_range(START, str(END-timedelta(days=1)))).tz_localize(None)
REPORT = {"asof_utc": datetime.now(ZoneInfo("UTC")).isoformat(), "start": START,
          "last_expected_session": str(EXPECTED[-1].date()), "expected_sessions": len(EXPECTED),
          "scope": "daily research, not intraday or production approval",
          "versions": {p: version(p) for p in ("yfinance","pandas","numpy","requests","exchange-calendars")},
          "yahoo": {}, "stooq": {}, "fred": {}, "comparison": {}}

def norm(df):
    df = df.copy()
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    return df.sort_index()

def quality(df, price):
    if df.empty or price not in df:
        raise ValueError("empty or missing required price")
    df = norm(df)
    if df.index.has_duplicates:
        raise ValueError("duplicate sessions")
    if not df.index.isin(EXPECTED).all():
        raise ValueError("unexpected session dates")
    fields = ["Open", "High", "Low", "Close", "Volume", price]
    if not all(c in df for c in fields):
        raise ValueError("missing OHLCV or adjusted price")
    clean = df[fields].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(clean.to_numpy()).all():
        raise ValueError("nonfinite OHLCV")
    if (clean[["Open","High","Low","Close",price]] <= 0).any().any() or (clean["Volume"] < 0).any():
        raise ValueError("invalid price or volume")
    if ((clean.High < clean[["Open","Low","Close"]].max(axis=1)) |
        (clean.Low > clean[["Open","High","Close"]].min(axis=1))).any():
        raise ValueError("invalid OHLC geometry")
    missing = EXPECTED.difference(df.index)
    coverage = len(df)/len(EXPECTED)
    latest = df.index[-1] == EXPECTED[-1]
    return {"status": "PASS" if coverage >= .98 and latest else "FAIL",
            "rows": len(df), "coverage": round(coverage,6), "missing_sessions": len(missing),
            "first": str(df.index[0].date()), "last": str(df.index[-1].date()),
            "fresh": bool(latest)}, df[price].astype(float)

def failure(exc):
    # Do not print provider response bodies, headers or credentials in public logs.
    return {"status":"FAIL","error_type": type(exc).__name__,
            "reason": str(exc) if isinstance(exc,ValueError) and str(exc) in (
              "empty or missing required price","duplicate sessions","unexpected session dates",
              "missing OHLCV or adjusted price","nonfinite OHLCV","invalid price or volume","invalid OHLC geometry",
              "insufficient overlap","empty FRED data","stale FRED data") else "provider or validation error"}

def main():
    yahoo, stooq = {}, {}
    # Batch requests, no auto-adjust: explicitly use adjusted closes for research.
    for offset in range(0, len(SYMBOLS), 6):
        batch = SYMBOLS[offset:offset+6]
        try:
            raw = yf.download(batch, start=START, end=str(END), interval="1d",
                auto_adjust=False, group_by="ticker", threads=False, progress=False, timeout=20)
            for ticker in batch:
                try:
                    if not isinstance(raw.columns, pd.MultiIndex):
                        raise ValueError("unexpected response shape")
                    df = raw[ticker].dropna(how="all")
                    REPORT["yahoo"][ticker], yahoo[ticker] = quality(df, "Adj Close")
                except Exception as exc:
                    REPORT["yahoo"][ticker] = failure(exc)
        except Exception as exc:
            for ticker in batch:
                REPORT["yahoo"][ticker] = failure(exc)
    # Independent secondary source on benchmark and all sectors, bounded requests.
    for ticker in ["SPY", *SECTORS]:
        try:
            response = requests.get("https://stooq.com/q/d/l/", params={
                "s": ticker.lower()+".us", "i":"d", "d1":START.replace("-",""),
                "d2":str(END-timedelta(days=1)).replace("-","")}, timeout=15)
            response.raise_for_status()
            df = pd.read_csv(io.StringIO(response.text), index_col="Date", parse_dates=True)
            REPORT["stooq"][ticker], stooq[ticker] = quality(df,"Close")
        except Exception as exc:
            REPORT["stooq"][ticker] = failure(exc)
    for ticker in ["SPY", *SECTORS]:
        try:
            # Reindex to exchange calendar before returns: no bridging missing days.
            aligned = pd.concat([yahoo[ticker], stooq[ticker]],axis=1).reindex(EXPECTED)
            returns = np.log(aligned).diff().dropna()
            if len(returns) < 250:
                raise ValueError("insufficient overlap")
            diff = (returns.iloc[:,0]-returns.iloc[:,1]).abs()*10000
            median,p95 = float(diff.median()),float(diff.quantile(.95))
            REPORT["comparison"][ticker] = {"status":"PASS" if median<=10 and p95<=50 else "FAIL",
                "paired_daily_returns":len(diff),"median_abs_difference_bps":round(median,3),
                "p95_abs_difference_bps":round(p95,3),
                "note":"adjustment conventions may differ; not proof of true total returns"}
        except Exception as exc:
            REPORT["comparison"][ticker] = failure(exc)
    for series in ("VIXCLS","DGS10","DGS2","BAMLH0A0HYM2"):
        try:
            response=requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv",
                params={"id":series,"cosd":START,"coed":str(END)},timeout=15)
            response.raise_for_status()
            frame=pd.read_csv(io.StringIO(response.text))
            dates=pd.to_datetime(frame.iloc[:,0],errors="coerce")
            vals=pd.to_numeric(frame[series],errors="coerce")
            valid=dates[dates.notna() & np.isfinite(vals)]
            if len(valid)<250 or valid.duplicated().any():
                raise ValueError("empty FRED data")
            last=valid.max().date()
            age=(END-last).days
            REPORT["fred"][series]={"status":"PASS" if 0<=age<=10 else "FAIL",
                "observations":len(valid),"last":str(last),"age_calendar_days":age,
                "note":"latest vintage, publication lag not validated"}
        except Exception as exc:
            REPORT["fred"][series]=failure(exc)
    core=["SPY",*SECTORS]
    primary=all(REPORT["yahoo"][s]["status"]=="PASS" for s in core)
    secondary=all(REPORT["stooq"][s]["status"]=="PASS" for s in core)
    compare=all(REPORT["comparison"][s]["status"]=="PASS" for s in core)
    macro=all(x["status"]=="PASS" for x in REPORT["fred"].values())
    REPORT["gates"]={"core_primary":primary,"core_secondary":secondary,
                     "crosscheck":compare,"macro":macro,
                     "extended_primary":all(x["status"]=="PASS" for x in REPORT["yahoo"].values()),
                     "intraday":"NOT_RUN","drive_write":"NOT_RUN","dashboard_integration":"NOT_RUN"}
    REPORT["verdict"]="GO_FOR_DAILY_RESEARCH_REVIEW" if primary and secondary and compare and macro else "NO_GO"
    print(json.dumps(REPORT,indent=2,allow_nan=False))
    # Public logs contain only data quality metrics, not raw OHLCV or private data.
    return 0 if REPORT["verdict"].startswith("GO") else 1

if __name__=="__main__":
    sys.exit(main())
