"""Synthetic Alpaca protocol and timestamp tests; no live credentials."""
import unittest
from unittest.mock import patch, Mock
import pandas as pd
from scripts import alpaca_feed as a

def row(t):
    return {"t":t,"o":100,"h":102,"l":99,"c":101,"v":500}

class AlpacaTests(unittest.TestCase):
    def test_daily_ny_session_dates_across_dst(self):
        data=a.daily_frame([row("2026-03-06T05:00:00Z"),row("2026-03-09T04:00:00Z")])
        self.assertEqual(list(data.index),list(pd.to_datetime(["2026-03-06","2026-03-09"])))
    def test_reject_nonmidnight(self):
        with self.assertRaisesRegex(ValueError,"invalid daily timestamp"):
            a.daily_frame([row("2026-03-06T15:00:00Z")])
    def test_duplicate_timestamps(self):
        r=row("2026-11-25T14:30:00Z")
        with self.assertRaisesRegex(ValueError,"duplicate"):
            a.frame([r,r])
    def test_early_close_grid(self):
        grid=pd.date_range("2026-11-27T14:30:00Z","2026-11-27T18:00:00Z",freq="5min",inclusive="left")
        report=a.intraday_quality([row(t.isoformat()) for t in grid],grid)
        self.assertEqual(report["expected"],42)
        self.assertEqual(report["status"],"PASS")
        self.assertEqual(a.intraday_quality([row(t.isoformat()) for t in grid[:-1]],grid)["status"],"FAIL")
    def test_off_grid(self):
        grid=pd.date_range("2026-11-25T14:30:00Z",periods=2,freq="5min")
        with self.assertRaisesRegex(ValueError,"unexpected intraday"):
            a.intraday_quality([row("2026-11-25T14:31:00Z")],grid)
    def test_paginated_symbols(self):
        with patch.object(a.requests,"Session") as factory:
            session=factory.return_value.__enter__.return_value
            p1,p2=Mock(status_code=200),Mock(status_code=200)
            p1.json.return_value={"bars":{"SPY":[row("2026-11-25T05:00:00Z")]},"next_page_token":"next"}
            p2.json.return_value={"bars":{"XLK":[row("2026-11-25T05:00:00Z")]},"next_page_token":None}
            session.get.side_effect=[p1,p2]
            result,pages=a.fetch_bars(["SPY","XLK"],"sip","1Day","2026-11-25","2026-11-26","all",{"fake":"fake"})
            self.assertEqual(pages,2)
            self.assertEqual([len(result[s]) for s in ("SPY","XLK")],[1,1])
            self.assertTrue(all(c.kwargs["allow_redirects"] is False for c in session.get.call_args_list))
    def test_http_forbidden_no_fallback(self):
        with patch.object(a.requests,"Session") as factory:
            session=factory.return_value.__enter__.return_value
            session.get.return_value=Mock(status_code=403)
            with self.assertRaises(a.requests.HTTPError):
                a.fetch_bars(["SPY"],"sip","1Day","2026-11-25","2026-11-26","all",{"fake":"fake"})
            self.assertEqual(session.get.call_count,1)

if __name__=="__main__":
    unittest.main()
