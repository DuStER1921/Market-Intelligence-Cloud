"""Pure descriptive daily sector metrics. No I/O, no orders, no predictive claims.

Caller must supply adjusted closes and *raw* regular-session dollar turnover
(VWAP times volume, or explicitly documented close-times-volume proxy).
Exactly 122 or more consecutive expected sessions, ending at a common cutoff.
"""
import numpy as np
import pandas as pd

SECTORS = "XLK XLF XLV XLE XLI XLY XLP XLU XLB XLRE XLC".split()
CORE = ["SPY", *SECTORS]
BETA_WINDOW = 120
VOLUME_WINDOW = 20

def aligned_frame(frame, sessions, columns, positive):
    if not isinstance(frame,pd.DataFrame) or frame.columns.has_duplicates:
        raise ValueError("invalid frame schema")
    if set(frame.columns)!=set(columns) or not frame.index.equals(sessions):
        raise ValueError("incomplete universe or session alignment")
    data=frame.loc[:,columns].astype(float)
    if not np.isfinite(data.to_numpy()).all():
        raise ValueError("nonfinite data")
    if (data<=0).any().any() if positive else (data<0).any().any():
        raise ValueError("invalid numeric domain")
    return data

def daily_rotation(adjusted_close, dollar_turnover, expected_sessions):
    sessions=pd.DatetimeIndex(expected_sessions)
    if len(sessions)<BETA_WINDOW+2 or sessions.has_duplicates or not sessions.is_monotonic_increasing:
        raise ValueError("insufficient or invalid expected session grid")
    close=aligned_frame(adjusted_close,sessions,CORE,True)
    turnover=aligned_frame(dollar_turnover,sessions,SECTORS,False)
    returns=close.pct_change(fill_method=None).iloc[1:]
    train=returns.iloc[-(BETA_WINDOW+1):-1]
    x=train["SPY"]
    variance=float(x.var(ddof=1))
    if not np.isfinite(variance) or variance<=1e-14:
        raise ValueError("degenerate benchmark variance")
    current=returns.iloc[-1]
    prev=turnover.iloc[-(VOLUME_WINDOW+1):-1]
    current_turnover=turnover.iloc[-1]
    prev_totals=prev.sum(axis=0)
    if current_turnover.sum()<=0 or prev_totals.sum()<=0 or (prev_totals<=0).any() or (prev.median()<=0).any():
        raise ValueError("unavailable turnover denominator")
    share=current_turnover/current_turnover.sum()
    previous_share=prev_totals/prev_totals.sum()
    rows=[]
    for s in SECTORS:
        beta=float(train[s].cov(x)/variance)
        alpha=float(train[s].mean()-beta*x.mean())
        residual=float(current[s]-alpha-beta*current["SPY"])
        sigma=float((train[s]-alpha-beta*x).std(ddof=1))
        if sigma<=1e-12:
            z=None
        else:
            z=float(residual/sigma)
        rs={}
        for h in (1,5,20):
            rel=close.iloc[-1]/close.iloc[-(h+1)]-1
            rs[str(h)]=float(100*(rel[s]-rel["SPY"]))
        rows.append({"symbol":s,"rs_pp":rs,"return_1d_pct":float(100*current[s]),
                     "beta_120":beta,"residual_pp":100*residual,"residual_z":z,
                     "rvol_20":float(current_turnover[s]/prev[s].median()),
                     "turnover_share_pct":float(100*share[s]),
                     "previous_turnover_share_pct":float(100*previous_share[s]),
                     "turnover_share_ratio":float(share[s]/previous_share[s]),
                     "positive_relative_days_last5":int((returns[s].iloc[-5:]>returns["SPY"].iloc[-5:]).sum())})
    rows.sort(key=lambda r:(-r["rs_pp"]["5"],r["symbol"]))
    return {"schema":"daily-rotation-v1","asof_session":sessions[-1].date().isoformat(),
            "training_last_session":sessions[-2].date().isoformat(),
            "benchmark":"SPY","rank_by":"5-session relative return (pp)",
            "positive_sector_etfs":int((current[SECTORS]>0).sum()),
            "outperforming_sector_etfs":int((current[SECTORS]>current["SPY"]).sum()),
            "rows":rows,"interpretation":"descriptive turnover and relative strength, not net fund flow or forecast"}
