"""Offline synthetic tests: no network and no real market data."""
import unittest
import pandas as pd
import numpy as np
import requests
from scripts import feed_acceptance as f

class FeedQualityTests(unittest.TestCase):
    def setUp(self):
        self.expected = f.EXPECTED
        self.df = pd.DataFrame({"Open":100.0,"High":102.0,"Low":99.0,
            "Close":101.0,"Adj Close":100.5,"Volume":1000.0}, index=self.expected)
    def test_valid_full_calendar(self):
        report, prices=f.quality(self.df,"Adj Close")
        self.assertEqual(report["status"],"PASS")
        self.assertEqual(len(prices),len(self.expected))
    def test_stooq_close(self):
        report,_=f.quality(self.df.drop(columns="Adj Close"),"Close")
        self.assertEqual(report["status"],"PASS")
    def test_stale(self):
        report,_=f.quality(self.df.iloc[:-1],"Adj Close")
        self.assertEqual(report["status"],"FAIL")
        self.assertFalse(report["fresh"])
    def test_missing_history(self):
        report,_=f.quality(self.df.iloc[30:],"Adj Close")
        self.assertEqual(report["status"],"FAIL")
    def test_duplicates(self):
        with self.assertRaisesRegex(ValueError,"duplicate sessions"):
            f.quality(pd.concat([self.df,self.df.iloc[-1:]]),"Adj Close")
    def test_unexpected_session(self):
        bad=self.df.iloc[-1:].copy()
        bad.index=pd.DatetimeIndex(["2018-12-31"])
        with self.assertRaisesRegex(ValueError,"unexpected session dates"):
            f.quality(pd.concat([self.df,bad]),"Adj Close")
    def test_nonfinite(self):
        self.df.iloc[0,0]=np.nan
        with self.assertRaisesRegex(ValueError,"nonfinite"):
            f.quality(self.df,"Adj Close")
    def test_nonpositive(self):
        self.df.iloc[0,0]=0
        with self.assertRaisesRegex(ValueError,"invalid price"):
            f.quality(self.df,"Adj Close")
    def test_geometry(self):
        self.df.iloc[0,self.df.columns.get_loc("High")]=98
        with self.assertRaisesRegex(ValueError,"invalid OHLC"):
            f.quality(self.df,"Adj Close")
    def test_no_missing_adjusted_close(self):
        with self.assertRaisesRegex(ValueError,"missing required price"):
            f.quality(self.df.drop(columns="Adj Close"),"Adj Close")
    def test_exception_sanitization(self):
        self.assertNotIn("SECRET",str(f.failure(RuntimeError("SECRET"))))

    def test_http_status_without_secret(self):
        response=requests.Response()
        response.status_code=403
        result=f.failure(requests.HTTPError("SECRET",response=response))
        self.assertEqual(result["http_status"],403)
        self.assertNotIn("SECRET",str(result))
    def test_missing_secondary_blocks_comparison(self):
        result=f.compare_sources("SPY",{"SPY":self.df["Adj Close"]},{})
        self.assertEqual(result["status"],"BLOCKED")
        self.assertEqual(result["missing_sources"],["alpaca_sip"])
    def test_identical_returns_pass(self):
        a=pd.Series(np.linspace(100,200,len(self.expected)),index=self.expected)
        result=f.compare_sources("SPY",{"SPY":a},{"SPY":a*2})
        self.assertEqual(result["status"],"PASS")
        self.assertEqual(result["paired_daily_returns"],len(a)-1)
    def test_no_bridging_missing_session(self):
        a=pd.Series(np.linspace(100,200,len(self.expected)),index=self.expected)
        b=a.drop(a.index[10])
        result=f.compare_sources("SPY",{"SPY":a},{"SPY":b})
        self.assertEqual(result["paired_daily_returns"],len(a)-3)

if __name__=="__main__":
    unittest.main()
