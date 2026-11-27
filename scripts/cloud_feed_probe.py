"""Manual cloud acceptance: fresh delayed SIP and Binance spot 5-minute grids.
No orders, raw market data, secrets, or private research results in output.
"""
import argparse
from decimal import Decimal, InvalidOperation
import json
import time

import exchange_calendars as xcals
import pandas as pd
import requests
from scripts import alpaca_feed as alpaca

STOCK = "SPY XLK XLF XLV XLE XLI XLY XLP XLU XLB XLRE XLC".split()
CRYPTO = "BTC ETH SOL BNB SUI AVAX ADA NEAR DOGE PEPE BONK WIF SHIB FLOKI AAVE UNI CRV ARB OP STRK FET RENDER TAO XRP XLM LINK FIL".split()
BINANCE = "https://data-api.binance.vision"
STEP = 300_000
BARS = 300

def safe_error(exc):
    result = {"status":"FAIL","error_type":type(exc).__name__}
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        result["http_status"] = int(exc.response.status_code)
    return result

def stock_window(now, cal):
    now = pd.Timestamp(now).tz_convert("UTC")
    local_day = now.tz_convert("America/New_York").date().isoformat()
    if not cal.is_session(local_day):
        return None, "MARKET_CLOSED"
    session = cal.date_to_session(local_day)
    op, cl = cal.session_open(session), cal.session_close(session)
    if not op <= now < cl:
        return None, "OUTSIDE_REGULAR_SESSION"
    # 15-minute entitlement delay plus 2-minute publication buffer.
    cutoff = min((now-pd.Timedelta(minutes=17)).floor("5min"), cl)
    if cutoff <= op:
        return None, "WAIT_FOR_FIRST_DELAYED_CLOSED_BAR"
    return pd.date_range(op, cutoff, freq="5min", inclusive="left"), "READY"

def stock_probe():
    now = pd.Timestamp.now(tz="UTC")
    cal = xcals.get_calendar("XNYS")
    expected, reason = stock_window(now, cal)
    report = {"schema":"cloud-feed-acceptance-v1","market":"stocks","feed":"sip",
              "asof_utc":now.isoformat(),"scope":"single current-session delayed snapshot",
              "symbols":{}}
    if expected is None:
        return dict(report, status="NOT_RUN", reason=reason)
    if not alpaca.credentials():
        return dict(report, status="BLOCKED", reason="Alpaca secrets missing")
    cutoff = expected[-1]+pd.Timedelta(minutes=5)
    report.update(cutoff_utc=cutoff.isoformat(), expected_per_symbol=len(expected),
                  planned_delay_seconds=(now-cutoff).total_seconds())
    try:
        rows,pages=alpaca.fetch_bars(STOCK,"sip","5Min",expected[0].isoformat(),
            (cutoff-pd.Timedelta(seconds=1)).isoformat(),"raw",alpaca.credentials())
        report["pages"]=pages
        for symbol in STOCK:
            try:
                report["symbols"][symbol]=alpaca.intraday_quality(rows[symbol],expected)
            except Exception as exc:
                report["symbols"][symbol]=safe_error(exc)
        complete = len(report["symbols"])==len(STOCK) and all(
            r["status"]=="PASS" for r in report["symbols"].values())
        finished=pd.Timestamp.now(tz="UTC")
        age=(finished-cutoff).total_seconds()
        report.update(finished_utc=finished.isoformat(),cutoff_age_seconds=age)
        report["status"]="PASS" if complete and 0<=age<=27*60 else "FAIL"
        return report
    except Exception as exc:
        return dict(report, **safe_error(exc))

def number(value):
    if isinstance(value,bool):
        raise ValueError("invalid numeric type")
    try:
        d=Decimal(str(value))
    except InvalidOperation:
        raise ValueError("invalid numeric value") from None
    if not d.is_finite():
        raise ValueError("nonfinite numeric value")
    return d

def integer(value):
    if type(value) is not int:
        raise ValueError("noninteger timestamp or count")
    return value

def crypto_grid(rows,cutoff,count=BARS):
    if not isinstance(rows,list) or len(rows)!=count or cutoff%STEP:
        raise ValueError("unexpected kline count or cutoff")
    start=cutoff-count*STEP
    for i,row in enumerate(rows):
        if not isinstance(row,list) or len(row)!=12:
            raise ValueError("invalid kline schema")
        t=start+i*STEP
        if integer(row[0])!=t or integer(row[6])!=t+STEP-1:
            raise ValueError("gap, duplicate or unexpected kline time")
        o,h,l,c,v,q,buy_base,buy_quote=[number(row[j]) for j in (1,2,3,4,5,7,9,10)]
        if min(o,h,l,c)<=0 or h<max(o,l,c) or l>min(o,h,c):
            raise ValueError("invalid OHLC")
        if min(v,q,buy_base,buy_quote)<0 or buy_base>v or buy_quote>q or integer(row[8])<0:
            raise ValueError("invalid volume or trades")
    return {"status":"PASS","rows":len(rows),"missing":0}

def public_get(session,path,params=None):
    response=session.get(BINANCE+path,params=params,timeout=10,allow_redirects=False)
    if response.status_code!=200:
        raise requests.HTTPError("Binance public data error",response=response)
    return response.json()

def crypto_probe():
    report={"schema":"cloud-feed-acceptance-v1","market":"crypto","feed":"Binance public spot",
            "asof_utc":pd.Timestamp.now(tz="UTC").isoformat(),"symbols":{},
            "expected_per_symbol":BARS,"scope":"single closed-bar snapshot, no futures or execution"}
    with requests.Session() as session:
        try:
            server=integer(public_get(session,"/api/v3/time")["serverTime"])
            local=int(time.time()*1000)
            if abs(server-local)>10000:
                return dict(report,status="FAIL",reason="CLOCK_SKEW")
            cutoff=((server-2000)//STEP)*STEP
            report["cutoff_utc"]=pd.Timestamp(cutoff,unit="ms",tz="UTC").isoformat()
            report["server_clock_skew_ms"]=server-local
        except Exception as exc:
            return dict(report,**safe_error(exc))
        for index,symbol in enumerate(CRYPTO):
            try:
                rows=public_get(session,"/api/v3/klines",{"symbol":symbol+"USDT","interval":"5m",
                    "startTime":cutoff-BARS*STEP,"endTime":cutoff-1,"limit":BARS})
                report["symbols"][symbol]=crypto_grid(rows,cutoff)
            except Exception as exc:
                error=safe_error(exc)
                report["symbols"][symbol]=error
                # Never bypass entitlement/geographic restrictions or rate limits.
                if error.get("http_status") in (401,403,418,429,451):
                    for remaining in CRYPTO[index+1:]:
                        report["symbols"][remaining]={"status":"BLOCKED","reason":"provider refusal or rate limit"}
                    break
        age=int(time.time()*1000)-cutoff
        complete=len(report["symbols"])==len(CRYPTO) and all(
            r["status"]=="PASS" for r in report["symbols"].values())
        report["cutoff_age_seconds"]=age/1000
        report["status"]="PASS" if complete and 0<=age<=420000 else "FAIL"
        return report

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("market",choices=("stock","crypto"))
    args=parser.parse_args()
    try:
        report=stock_probe() if args.market=="stock" else crypto_probe()
    except Exception as exc:
        report={"market":args.market,**safe_error(exc)}
    print(json.dumps(report,indent=2,allow_nan=False))
    return 0 if report["status"]=="PASS" else 2 if report["status"]=="NOT_RUN" else 1

if __name__=="__main__":
    raise SystemExit(main())
