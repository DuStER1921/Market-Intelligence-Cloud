"""Deterministic offline checks for cloud probe; no provider access."""
import unittest
from unittest.mock import patch, Mock
import pandas as pd
import exchange_calendars as xcals
from scripts import cloud_feed_probe as p

def row(t):
    return [t,"10","11","9","10.5","10",t+p.STEP-1,"105",3,"5","52.5","0"]

class CloudProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cal=xcals.get_calendar("XNYS",start="2026-01-01",end="2027-01-31")
    def test_delayed_cutoff(self):
        grid,reason=p.stock_window(pd.Timestamp("2026-11-27T15:02:01Z"),self.cal)
        self.assertEqual(reason,"READY")
        self.assertEqual(len(grid),3)
        self.assertEqual(grid[-1],pd.Timestamp("2026-11-27T14:40:00Z"))
    def test_first_bar_not_ready(self):
        self.assertEqual(p.stock_window(pd.Timestamp("2026-11-27T14:49:00Z"),self.cal)[1],
                         "WAIT_FOR_FIRST_DELAYED_CLOSED_BAR")
    def test_thanksgiving_closed(self):
        self.assertEqual(p.stock_window(pd.Timestamp("2026-11-26T16:00:00Z"),self.cal)[1],"MARKET_CLOSED")
    def test_early_close_no_after_hours(self):
        self.assertEqual(p.stock_window(pd.Timestamp("2026-11-27T18:01:00Z"),self.cal)[1],
                         "OUTSIDE_REGULAR_SESSION")
    def test_dst(self):
        grid,_=p.stock_window(pd.Timestamp("2026-07-01T14:02:01Z"),self.cal)
        self.assertEqual(grid[0],pd.Timestamp("2026-07-01T13:30:00Z"))
    def test_crypto_exact_grid(self):
        cutoff=10*p.STEP
        self.assertEqual(p.crypto_grid([row(cutoff-2*p.STEP),row(cutoff-p.STEP)],cutoff,2)["status"],"PASS")
    def test_crypto_reject_duplicate(self):
        t=10*p.STEP
        with self.assertRaisesRegex(ValueError,"gap, duplicate"):
            p.crypto_grid([row(t-2*p.STEP),row(t-2*p.STEP)],t,2)
    def test_crypto_reject_open_bar(self):
        t=10*p.STEP
        with self.assertRaisesRegex(ValueError,"gap, duplicate"):
            p.crypto_grid([row(t-p.STEP),row(t)],t,2)
    def test_crypto_reject_excess_taker(self):
        t=10*p.STEP
        r=row(t-p.STEP);r[10]="106"
        with self.assertRaisesRegex(ValueError,"invalid volume"):
            p.crypto_grid([r],t,1)
    def test_crypto_reject_nonfinite(self):
        t=10*p.STEP
        r=row(t-p.STEP);r[4]="NaN"
        with self.assertRaisesRegex(ValueError,"nonfinite"):
            p.crypto_grid([r],t,1)
    def test_crypto_reject_float_timestamp(self):
        t=10*p.STEP
        r=row(t-p.STEP);r[0]=float(r[0])
        with self.assertRaisesRegex(ValueError,"noninteger"):
            p.crypto_grid([r],t,1)
    def test_provider_refusal_no_redirect(self):
        session=Mock()
        session.get.return_value=Mock(status_code=451)
        with self.assertRaises(p.requests.HTTPError):
            p.public_get(session,"/api/v3/time")
        self.assertFalse(session.get.call_args.kwargs["allow_redirects"])

if __name__=="__main__":
    unittest.main()
