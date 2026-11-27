"""Alpaca read-only data probes. Never print headers, payloads or credentials."""
import os
import time
import numpy as np
import pandas as pd
import requests

URL = "https://data.alpaca.markets/v2/stocks/bars"
FIELDS = {"o":"Open","h":"High","l":"Low","c":"Close","v":"Volume"}

def credentials():
    key = os.environ.get("ALPACA_API_KEY","").strip()
    secret = os.environ.get("ALPACA_SECRET_KEY","").strip()
    return {"APCA-API-KEY-ID":key,"APCA-API-SECRET-KEY":secret} if key and secret else None

def fetch_bars(symbols, feed, timeframe, start, end, adjustment, headers):
    if feed not in ("sip","iex") or timeframe not in ("1Day","5Min"):
        raise ValueError("invalid feed or timeframe")
    if not headers:
        raise ValueError("missing Alpaca credentials")
    params={"symbols":",".join(symbols),"feed":feed,"timeframe":timeframe,
            "start":start,"end":end,"adjustment":adjustment,"limit":10000,"sort":"asc"}
    result={s:[] for s in symbols}
    seen=set()
    with requests.Session() as session:
        for page in range(30):
            for attempt in range(3):
                response=session.get(URL,params=params,headers=headers,timeout=20,allow_redirects=False)
                if response.status_code in (429,500,502,503,504) and attempt<2:
                    time.sleep(2**attempt)
                    continue
                break
            if response.status_code != 200:
                raise requests.HTTPError("Alpaca HTTP error",response=response)
            body=response.json()
            if not isinstance(body.get("bars"),dict) or "next_page_token" not in body:
                raise ValueError("invalid Alpaca response")
            for symbol,rows in body["bars"].items():
                if symbol not in result or not isinstance(rows,list):
                    raise ValueError("unexpected symbol or bar list")
                result[symbol].extend(rows)
            token=body["next_page_token"]
            if token is None:
                return result,page+1
            if not isinstance(token,str) or not token or token in seen:
                raise ValueError("invalid pagination token")
            seen.add(token)
            params["page_token"]=token
    raise ValueError("pagination cap exceeded")

def frame(rows):
    if not rows:
        raise ValueError("empty Alpaca bars")
    data=pd.DataFrame(rows)
    index=pd.to_datetime(data.pop("t"),utc=True,errors="raise")
    data=data.rename(columns=FIELDS)[list(FIELDS.values())].apply(pd.to_numeric,errors="coerce")
    data.index=pd.DatetimeIndex(index)
    if data.index.has_duplicates:
        raise ValueError("duplicate Alpaca timestamps")
    if not np.isfinite(data.to_numpy()).all():
        raise ValueError("nonfinite OHLCV")
    if (data[["Open","High","Low","Close"]]<=0).any().any() or (data.Volume<0).any():
        raise ValueError("invalid price or volume")
    if ((data.High<data[["Open","Low","Close"]].max(axis=1)) |
        (data.Low>data[["Open","High","Close"]].min(axis=1))).any():
        raise ValueError("invalid OHLC geometry")
    return data.sort_index()

def daily_frame(rows):
    data=frame(rows)
    local=data.index.tz_convert("America/New_York")
    if not (local == local.normalize()).all():
        raise ValueError("invalid daily timestamp")
    data.index=local.tz_localize(None).normalize()
    return data

def intraday_quality(rows, expected):
    data=frame(rows)
    # Fetch interval includes only regular-session timestamps; reject off-grid rows.
    if not data.index.isin(expected).all():
        raise ValueError("unexpected intraday timestamp")
    missing=expected.difference(data.index)
    return {"status":"PASS" if len(missing)==0 else "FAIL",
            "rows":len(data),"expected":len(expected),"missing":len(missing),
            "coverage":round(len(data)/len(expected),6),
            "first_utc":data.index[0].isoformat(),"last_utc":data.index[-1].isoformat()}
