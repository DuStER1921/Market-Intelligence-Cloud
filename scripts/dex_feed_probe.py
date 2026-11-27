"""Phase 3: public read-only DEX/on-chain data qualification, not a trading scanner."""
import json
import math
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import requests

NETWORKS = {"Solana":("solana","solana"),"Ethereum":("eth","ethereum"),"Base":("base","base")}
LLAMA="https://api.llama.fi"
LLAMA_STABLE="https://stablecoins.llama.fi"
GECKO="https://api.geckoterminal.com/api/v2"
DEX="https://api.dexscreener.com"
DAY=86400
STEP=300
HISTORY=31
BARS=48
MIN_RESERVE=100000

def iso(t):
    return datetime.fromtimestamp(t,timezone.utc).isoformat()

def num(v, positive=False):
    if isinstance(v,bool) or not isinstance(v,(str,int,float)):
        raise ValueError("invalid numeric type")
    x=float(v)
    if not math.isfinite(x) or x<0 or (positive and x==0):
        raise ValueError("invalid numeric domain")
    return x

def epoch(v):
    if type(v) is int:
        return v
    if isinstance(v,str) and re.fullmatch(r"[0-9]{1,12}",v):
        return int(v)
    raise ValueError("invalid timestamp")

def count(v):
    if type(v) is not int or v<0:
        raise ValueError("invalid transaction count")
    return v

def address(v,network):
    pattern=r"[1-9A-HJ-NP-Za-km-z]{32,44}" if network=="solana" else r"0x[0-9a-fA-F]{40}"
    if not isinstance(v,str) or not re.fullmatch(pattern,v):
        raise ValueError("invalid chain address")
    return v if network=="solana" else v.lower()

def pool_id(v,network):
    # EVM singleton AMMs (e.g. Uniswap v4) identify pools by bytes32 IDs.
    # Keep token address validation strictly 20 bytes, independently.
    if network!="solana" and isinstance(v,str) and re.fullmatch(r"0x[0-9a-fA-F]{64}",v):
        return v.lower()
    return address(v,network)

def token_id(value,network):
    prefix=network+"_"
    if not isinstance(value,str) or not value.startswith(prefix):
        raise ValueError("wrong token network")
    return address(value[len(prefix):],network)

def daily_quality(rows, kind, now):
    if not isinstance(rows,list) or not rows:
        raise ValueError("empty daily history")
    today=now//DAY*DAY
    last=today-2*DAY
    expected=set(range(last-(HISTORY-1)*DAY,last+DAY,DAY))
    seen=set()
    closed=set()
    for row in rows:
        if kind=="dex_volume":
            if not isinstance(row,list) or len(row)!=2:
                raise ValueError("invalid daily volume schema")
            date,value=row
        else:
            date=row["date"]
            value=row["totalCirculating"]["peggedUSD"] if kind=="stablecoin" else row["tvl"]
        t=epoch(date)
        if t<min(expected) or t>=today:
            continue
        if t%DAY or t in seen:
            raise ValueError("duplicate or non-UTC daily timestamp")
        seen.add(t)
        num(value)
        closed.add(t)
    missing=expected-closed
    latest=max(closed) if closed else None
    return {"status":"PASS" if not missing else "FAIL","required_days":HISTORY,
            "matched_days":HISTORY-len(missing),"missing_days":len(missing),
            "required_through_utc":iso(last),
            "latest_closed_date_utc":iso(latest) if latest is not None else None}

def choose_pool(body,network):
    if not isinstance(body["data"],list):
        raise ValueError("invalid pool list")
    eligible=[]
    seen=set()
    for p in body["data"]:
        a=p["attributes"]
        if a.get("reserve_in_usd") is None:
            continue
        reserve=num(a["reserve_in_usd"])
        if reserve<MIN_RESERVE:
            continue
        pool=pool_id(a["address"],network)
        if pool in seen:
            raise ValueError("duplicate pool address")
        seen.add(pool)
        rel=p["relationships"]
        base=token_id(rel["base_token"]["data"]["id"],network)
        quote=token_id(rel["quote_token"]["data"]["id"],network)
        if base==quote:
            raise ValueError("identical pool tokens")
        eligible.append((reserve,pool,base,quote))
    if not eligible:
        raise ValueError("no eligible liquid pool")
    # Deterministic within this provider page, not a market-wide liquidity ranking.
    _,pool,base,quote=sorted(eligible,key=lambda x:(-x[0],x[1]))[0]
    return pool,base,quote

def ohlcv_quality(body,cutoff):
    rows=body["data"]["attributes"]["ohlcv_list"]
    if not isinstance(rows,list):
        raise ValueError("invalid OHLCV list")
    expected=set(range(cutoff-BARS*STEP,cutoff,STEP))
    seen=set()
    for row in rows:
        if not isinstance(row,list) or len(row)!=6:
            raise ValueError("invalid OHLCV schema")
        t=epoch(row[0])
        if t not in expected or t in seen:
            raise ValueError("unexpected, duplicate or open bar")
        seen.add(t)
        o,h,l,c=[num(v,positive=True) for v in row[1:5]]
        num(row[5])
        if h<max(o,l,c) or l>min(o,h,c):
            raise ValueError("invalid OHLC geometry")
    return {"status":"PASS" if seen==expected else "FAIL","required_bars":BARS,
            "matched_bars":len(seen),"missing_bars":len(expected-seen),
            "cutoff_utc":iso(cutoff)}

def pair_quality(body,network,dex_chain,pool,base,quote):
    if not isinstance(body["pairs"],list):
        raise ValueError("invalid pair list")
    found=[p for p in body["pairs"] if p.get("chainId")==dex_chain
           and pool_id(p["pairAddress"],network)==pool]
    if len(found)!=1:
        raise ValueError("missing or ambiguous matching pair")
    p=found[0]
    b=address(p["baseToken"]["address"],network)
    q=address(p["quoteToken"]["address"],network)
    if {b,q}!={base,quote}:
        raise ValueError("token identity mismatch")
    num(p["priceUsd"],positive=True)
    num(p["liquidity"]["usd"],positive=True)
    for window in ("m5","h1","h24"):
        num(p["volume"][window])
        count(p["txns"][window]["buys"])
        count(p["txns"][window]["sells"])
    return {"status":"PASS","same_pool":True,"same_token_set":True,
            "same_orientation":(b,q)==(base,quote),
            "validated_windows":["m5","h1","h24"],
            "snapshot_source_timestamp":"NOT_PROVIDED",
            "note":"identity and schema only; no synchronized price/volume equivalence"}

def get(session,url,params=None):
    # No redirects, retry storms, auth, alternate hosts or bypasses.
    response=session.get(url,params=params,timeout=(5,15),allow_redirects=False)
    if response.status_code!=200:
        raise requests.HTTPError("provider refusal or error",response=response)
    return response.json()

# Conservative per-run pacing; shared runner/IP traffic remains outside our control.
GECKO_INTERVAL=20
GECKO_RETRY_LIMIT=2
GECKO_MAX_WAIT=90

def retry_delay(value, now):
    if value is None:
        return 60
    try:
        if re.fullmatch(r"[0-9]{1,10}",value):
            return max(60,int(value))
        dt=parsedate_to_datetime(value)
        if dt.tzinfo is None:
            return 60
        return max(60,math.ceil(dt.timestamp()-now))
    except (TypeError,ValueError,OverflowError):
        return 60

class GeckoClient:
    """Single paced client per probe; no alternate host or unbounded retries."""
    def __init__(self,session):
        self.session=session
        self.next_allowed=0.0
        self.attempts=0
        self.rate_limits=0
        self.retries=0
        self.wait_seconds=0.0
        self.stopped=False

    def wait(self,seconds):
        if seconds>0:
            time.sleep(seconds)
            self.wait_seconds+=seconds

    def get(self,url,params=None):
        if self.stopped:
            raise ValueError("GeckoTerminal paused after rate limit")
        if not url.startswith(GECKO+"/"):
            raise ValueError("invalid GeckoTerminal endpoint")
        for attempt in range(2):
            self.wait(max(0,self.next_allowed-time.monotonic()))
            self.next_allowed=time.monotonic()+GECKO_INTERVAL
            self.attempts+=1
            try:
                return get(self.session,url,params)
            except requests.HTTPError as exc:
                if exc.response is None or exc.response.status_code!=429:
                    raise
                self.rate_limits+=1
                delay=retry_delay(exc.response.headers.get("Retry-After"),time.time())
                if attempt or self.retries>=GECKO_RETRY_LIMIT or delay>GECKO_MAX_WAIT:
                    self.stopped=True
                    raise
                self.retries+=1
                self.next_allowed=max(self.next_allowed,time.monotonic()+delay)
        raise RuntimeError("unreachable GeckoTerminal retry state")

    def diagnostics(self):
        return {"attempts":self.attempts,"rate_limit_responses":self.rate_limits,
                "retries":self.retries,"wait_seconds":round(self.wait_seconds,3),
                "minimum_request_interval_seconds":GECKO_INTERVAL,
                "stopped_after_rate_limit":self.stopped}

def failure(exc):
    report={"status":"FAIL","error_type":type(exc).__name__}
    # Only expose fixed validation messages, never untrusted provider payloads.
    if isinstance(exc,ValueError) and str(exc) in (
        "invalid numeric type","invalid numeric domain","invalid timestamp",
        "invalid transaction count","invalid chain address","wrong token network",
        "invalid pool list","duplicate pool address","identical pool tokens",
        "no eligible liquid pool","empty daily history","invalid daily volume schema",
        "duplicate or non-UTC daily timestamp","invalid OHLCV list",
        "invalid OHLCV schema","unexpected, duplicate or open bar",
        "invalid OHLC geometry","invalid pair list","missing or ambiguous matching pair",
        "token identity mismatch","GeckoTerminal paused after rate limit","invalid GeckoTerminal endpoint"):
        report["reason"]=str(exc)
    if isinstance(exc,requests.HTTPError) and exc.response is not None:
        report["http_status"]=exc.response.status_code
    return report

def guarded(fn):
    try:
        return fn()
    except Exception as exc:
        return failure(exc)

def probe():
    now=int(time.time())
    cutoff=(now-120)//STEP*STEP
    report={"schema":"dex-feed-acceptance-v1","asof_utc":iso(now),
            "scope":"one dynamic pool sample per network, daily and closed 5-minute history qualification only",
            "chains":{},"gates":{"bridge_flows":"NOT_RUN","wallet_activity":"NOT_RUN",
            "persistent_storage":"NOT_RUN","dashboard_integration":"NOT_RUN",
            "live_soak":"NOT_RUN","edge_research":"NOT_RUN"}}
    with requests.Session() as s:
        gecko=GeckoClient(s)
        for chain,(network,dex_chain) in NETWORKS.items():
            r={}
            report["chains"][chain]=r
            r["stablecoin_nominal_usd_peg"]=guarded(lambda:daily_quality(
                get(s,LLAMA_STABLE+"/stablecoincharts/"+chain),"stablecoin",now))
            r["tvl_usd"]=guarded(lambda:daily_quality(
                get(s,LLAMA+"/v2/historicalChainTvl/"+chain),"tvl",now))
            r["dex_volume_usd"]=guarded(lambda:daily_quality(get(s,LLAMA+"/overview/dexs/"+chain.lower(),
                {"excludeTotalDataChart":"false","excludeTotalDataChartBreakdown":"true"})["totalDataChart"],
                "dex_volume",now))
            try:
                pool,base,quote=choose_pool(gecko.get(GECKO+"/networks/"+network+"/pools",{"page":1}),network)
                r["pool_selection"]={"status":"PASS","pool_address":pool,
                    "method":"highest reported reserve among eligible first-page pools",
                    "pool_identifier_type":"evm_bytes32" if network!="solana" and len(pool)==66 else "address"}
            except Exception as exc:
                r["pool_selection"]=failure(exc)
                r["ohlcv"]={"status":"BLOCKED"}
                r["dexscreener"]={"status":"BLOCKED"}
                continue
            r["ohlcv"]=guarded(lambda:ohlcv_quality(gecko.get(
                GECKO+"/networks/"+network+"/pools/"+pool+"/ohlcv/minute",
                {"aggregate":5,"limit":BARS,"before_timestamp":cutoff-1,"currency":"usd","token":"base"}),cutoff))
            r["dexscreener"]=guarded(lambda:pair_quality(get(s,DEX+"/latest/dex/pairs/"+dex_chain+"/"+pool),
                network,dex_chain,pool,base,quote))
    report["geckoterminal_request_health"]=gecko.diagnostics()
    finished=int(time.time())
    report["finished_utc"]=iso(finished)
    report["ohlcv_cutoff_age_seconds"]=finished-cutoff
    complete=all(v["status"]=="PASS" for r in report["chains"].values() for v in r.values())
    report["status"]="PASS" if complete and 0<=finished-cutoff<=900 else "FAIL"
    return report

def main():
    report=guarded(probe)
    print(json.dumps(report,indent=2,allow_nan=False))
    return 0 if report["status"]=="PASS" else 1

if __name__=="__main__":
    raise SystemExit(main())
