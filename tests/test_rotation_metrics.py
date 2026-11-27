"""Offline synthetic rotation metric checks; not trading backtests."""
import unittest
import numpy as np
import pandas as pd
from scripts import rotation_metrics as m

class RotationTests(unittest.TestCase):
    def setUp(self):
        self.sessions=pd.bdate_range("2024-01-01",periods=130)
        rng=np.random.default_rng(19)
        market=rng.normal(.0002,.01,len(self.sessions))
        prices={"SPY":100*np.cumprod(1+market)}
        for i,s in enumerate(m.SECTORS):
            prices[s]=100*np.cumprod(1+market*(.5+i*.1)+rng.normal(0,.003,len(market)))
        self.prices=pd.DataFrame(prices,index=self.sessions)
        self.turn=pd.DataFrame(1000.,index=self.sessions,columns=m.SECTORS)
    def get(self,prices=None,turn=None):
        return m.daily_rotation(self.prices if prices is None else prices,
                                self.turn if turn is None else turn,self.sessions)
    def test_all_sectors_and_share(self):
        result=self.get()
        self.assertEqual(len(result["rows"]),11)
        self.assertAlmostEqual(sum(r["turnover_share_pct"] for r in result["rows"]),100)
        self.assertEqual(result["training_last_session"],self.sessions[-2].date().isoformat())
    def test_turnover_baseline_excludes_today(self):
        t=self.turn.copy();t.loc[self.sessions[-1],"XLK"]=4000
        row=next(r for r in self.get(turn=t)["rows"] if r["symbol"]=="XLK")
        self.assertEqual(row["rvol_20"],4)
        self.assertAlmostEqual(row["turnover_share_ratio"],44/14)
    def test_beta_fit_excludes_current_return(self):
        changed=self.prices.copy();changed.loc[self.sessions[-1],"XLK"]*=1.2
        a=next(r for r in self.get()["rows"] if r["symbol"]=="XLK")
        b=next(r for r in self.get(prices=changed)["rows"] if r["symbol"]=="XLK")
        self.assertEqual(a["beta_120"],b["beta_120"])
        self.assertNotEqual(a["residual_pp"],b["residual_pp"])
    def test_missing_session_rejected(self):
        with self.assertRaisesRegex(ValueError,"session alignment"):
            self.get(prices=self.prices.drop(self.sessions[5]))
    def test_missing_sector_rejected(self):
        with self.assertRaisesRegex(ValueError,"incomplete universe"):
            self.get(turn=self.turn.drop(columns="XLK"))
    def test_zero_baseline_rejected(self):
        t=self.turn.copy();t["XLK"]=0
        with self.assertRaisesRegex(ValueError,"denominator"):
            self.get(turn=t)
    def test_relative_rank_descending(self):
        rows=self.get()["rows"]
        self.assertEqual([r["rs_pp"]["5"] for r in rows],sorted([r["rs_pp"]["5"] for r in rows],reverse=True))

if __name__=="__main__":
    unittest.main()
