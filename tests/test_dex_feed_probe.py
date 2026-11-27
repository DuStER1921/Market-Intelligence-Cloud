"""Offline tests for Phase 3 data contract."""
import unittest
from unittest.mock import Mock
from scripts import dex_feed_probe as p

NOW=1775000000
LAST=NOW//p.DAY*p.DAY-2*p.DAY
CUTOFF=NOW//p.STEP*p.STEP
POOL="0x"+"1"*40
BASE="0x"+"2"*40
QUOTE="0x"+"3"*40

def daily(kind):
    times=range(LAST-(p.HISTORY-1)*p.DAY,LAST+p.DAY,p.DAY)
    if kind=="dex_volume":
        return [[t,100] for t in times]
    if kind=="stablecoin":
        return [{"date":str(t),"totalCirculating":{"peggedUSD":100}} for t in times]
    return [{"date":t,"tvl":100} for t in times]

def candles():
    return {"data":{"attributes":{"ohlcv_list":[[t,10,11,9,10,50]
             for t in range(CUTOFF-p.BARS*p.STEP,CUTOFF,p.STEP)]}}}

def pair():
    return {"pairs":[{"chainId":"ethereum","pairAddress":POOL,
        "baseToken":{"address":BASE},"quoteToken":{"address":QUOTE},
        "priceUsd":"10","liquidity":{"usd":100000},
        "volume":{w:100 for w in ("m5","h1","h24")},
        "txns":{w:{"buys":2,"sells":1} for w in ("m5","h1","h24")}}]}

def pool_data(pool=POOL,reserve="200000"):
    return {"attributes":{"address":pool,"reserve_in_usd":reserve},
            "relationships":{"base_token":{"data":{"id":"eth_"+BASE}},
                             "quote_token":{"data":{"id":"eth_"+QUOTE}}}}

class DexTests(unittest.TestCase):
    def test_all_daily_schemas(self):
        for k in ("stablecoin","tvl","dex_volume"):
            self.assertEqual(p.daily_quality(daily(k),k,NOW)["status"],"PASS")
    def test_missing_day(self):
        self.assertEqual(p.daily_quality(daily("tvl")[:-1],"tvl",NOW)["missing_days"],1)
    def test_daily_duplicate(self):
        data=daily("tvl")
        with self.assertRaisesRegex(ValueError,"duplicate"):
            p.daily_quality(data+[data[-1]],"tvl",NOW)
    def test_current_day_excluded(self):
        data=daily("tvl")[:-1]+[{"date":NOW//p.DAY*p.DAY,"tvl":100}]
        self.assertEqual(p.daily_quality(data,"tvl",NOW)["status"],"FAIL")
    def test_negative_and_nonfinite(self):
        for value in (-1,"nan","inf",True):
            with self.assertRaises(ValueError): p.num(value)
    def test_pool_selection_by_reserve(self):
        self.assertEqual(p.choose_pool({"data":[pool_data("0x"+"4"*40,"150000"),pool_data()]},
                         "eth"),(POOL,BASE,QUOTE))
    def test_low_reserve_excluded(self):
        with self.assertRaisesRegex(ValueError,"no eligible"):
            p.choose_pool({"data":[pool_data(reserve="99999")]},"eth")
    def test_pool_wrong_network(self):
        with self.assertRaisesRegex(ValueError,"wrong token network"):
            p.choose_pool({"data":[pool_data()]},"base")
    def test_ohlcv_complete(self):
        self.assertEqual(p.ohlcv_quality(candles(),CUTOFF)["matched_bars"],p.BARS)
    def test_ohlcv_gap(self):
        data=candles()
        data["data"]["attributes"]["ohlcv_list"].pop()
        self.assertEqual(p.ohlcv_quality(data,CUTOFF)["status"],"FAIL")
    def test_ohlcv_open_bar(self):
        data=candles()
        data["data"]["attributes"]["ohlcv_list"][-1][0]=CUTOFF
        with self.assertRaisesRegex(ValueError,"open bar"): p.ohlcv_quality(data,CUTOFF)
    def test_pair_identity(self):
        self.assertEqual(p.pair_quality(pair(),"eth","ethereum",POOL,BASE,QUOTE)["status"],"PASS")
    def test_wrong_token_rejected(self):
        data=pair()
        data["pairs"][0]["baseToken"]["address"]="0x"+"5"*40
        with self.assertRaisesRegex(ValueError,"identity mismatch"):
            p.pair_quality(data,"eth","ethereum",POOL,BASE,QUOTE)
    def test_reverse_orientation_explicit(self):
        data=pair()
        data["pairs"][0]["baseToken"],data["pairs"][0]["quoteToken"]=data["pairs"][0]["quoteToken"],data["pairs"][0]["baseToken"]
        self.assertFalse(p.pair_quality(data,"eth","ethereum",POOL,BASE,QUOTE)["same_orientation"])
    def test_stablecoin_host(self):
        self.assertEqual(p.LLAMA_STABLE,"https://stablecoins.llama.fi")
        self.assertNotEqual(p.LLAMA_STABLE,p.LLAMA)
    def test_evm_bytes32_pool_selected(self):
        identifier="0x"+"AB"*32
        self.assertEqual(p.choose_pool({"data":[pool_data(identifier)]},"eth"),
                         (identifier.lower(),BASE,QUOTE))
    def test_evm_bytes32_pair_identity(self):
        identifier="0x"+"a"*64
        data=pair()
        data["pairs"][0]["pairAddress"]=identifier.upper().replace("0X","0x")
        self.assertTrue(p.pair_quality(data,"eth","ethereum",identifier,BASE,QUOTE)["same_pool"])
    def test_evm_bytes32_not_token_address(self):
        with self.assertRaisesRegex(ValueError,"invalid chain address"):
            p.token_id("eth_0x"+"a"*64,"eth")
    def test_malformed_pool_still_rejected(self):
        with self.assertRaisesRegex(ValueError,"invalid chain address"):
            p.choose_pool({"data":[pool_data("0x"+"a"*63)]},"eth")
    def test_bytes32_pool_duplicate_rejected(self):
        identifier="0x"+"a"*64
        with self.assertRaisesRegex(ValueError,"duplicate pool address"):
            p.choose_pool({"data":[pool_data(identifier),pool_data(identifier)]},"eth")
    def test_safe_validation_diagnostics(self):
        self.assertEqual(p.failure(ValueError("invalid chain address"))["reason"],"invalid chain address")
        self.assertNotIn("reason",p.failure(ValueError("UNTRUSTED_PAYLOAD")))
    def test_http_refusal_no_redirect(self):
        s=Mock()
        s.get.return_value=Mock(status_code=429)
        with self.assertRaises(p.requests.HTTPError): p.get(s,p.GECKO+"/networks")
        self.assertFalse(s.get.call_args.kwargs["allow_redirects"])
        self.assertEqual(s.get.call_count,1)

if __name__=="__main__":
    unittest.main()
