# ──────────────────────────────────────────────────────────────────────────────
# Extra analysts: drop-in module
# ──────────────────────────────────────────────────────────────────────────────
import math, time, asyncio, statistics
from types import SimpleNamespace as _SN

import sys, asyncio, random, math, time, os, json, csv, statistics, uuid, threading, io, urllib.request
from typing import Dict, Any, List, Literal, Optional, Tuple
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from dataclasses import dataclass
import logging

# Fallback Proposal shim if your project hasn't imported it yet in this module scope.
try:
    Proposal  # noqa: F821
except NameError:  # very defensive, your code likely already has Proposal in scope
    def Proposal(agent, symbol, action, confidence, *_, **__):
        return _SN(agent=agent, symbol=symbol, action=action, confidence=float(confidence))

# Expect your base Agent class in scope; if not, import from your project.
try:
    Agent  # noqa: F821
except NameError:
    class Agent:
        def __init__(self, name, bus, state): self.name, self.bus, self.state = name, bus, state
        async def start(self): pass
        
# ===== FAST FEATURE HELPERS + BACKWARD-COMPATIBLE CTOR UNPACK =====
import numpy as _np

def _unpack_ctor_args(default_name, *args, **kwargs):
    """
    Supports BOTH call styles:
    - Old:  Class("Name", bus, state, cfg?)
    - New:  Class(bus, state, cfg?)
    Returns: (name, bus, state, cfg_dict)
    """
    cfg = kwargs.get("cfg", None)
    if len(args) >= 3 and isinstance(args[0], str):
        # Old style
        name, bus, state = args[0], args[1], args[2]
        if cfg is None and len(args) >= 4 and isinstance(args[3], dict):
            cfg = args[3]
    elif len(args) >= 2:
        # New style
        name, bus, state = default_name, args[0], args[1]
        if cfg is None and len(args) >= 3 and isinstance(args[2], dict):
            cfg = args[2]
    else:
        raise TypeError(f"{default_name} __init__ expects (name,bus,state[,cfg]) or (bus,state[,cfg])")
    return name, bus, state, (cfg or {})

# ---- Optional numba speedup; safe fallback to NumPy ----
try:
    from speedups_cpu import rolling_mean_var_2d  # your JIT impl
except Exception:
    def rolling_mean_var_2d(mat, win: int):
        m = mat[:, -win:].mean(axis=1)
        v = mat[:, -win:].var(axis=1)
        return m.astype(_np.float32), v.astype(_np.float32)

def _stack_prices_matrix(state, symbols, need_bars: int) -> _np.ndarray:
    """
    Return float32 matrix (N, T>=need_bars) of closes.
    Falls back to state['bars_cache'] if state['prices'] is short.
    """
    N = len(symbols)
    rows = []
    bc = state.get("bars_cache", None)
    prices = state.get("prices", {}) or {}
    for s in symbols:
        px = prices.get(s, [])
        if len(px) < need_bars and bc is not None:
            try:
                got = bc.get_last_n(s, need_bars)
                if got and len(got) >= need_bars:
                    px = got
            except Exception:
                pass
        rows.append(_np.asarray(px, dtype=_np.float32))
    max_T = max((len(r) for r in rows), default=need_bars)
    out = _np.zeros((N, max_T), dtype=_np.float32)
    for i, r in enumerate(rows):
        if r.size:
            out[i, -r.size:] = r
    return out

def ensure_fast_features(state, lookbacks=(5, 10, 20), atr_win=14, vol_windows=(20,)):
    """
    Vectorized one-shot feature calc for current universe:
      - ret{k}   for k in lookbacks     (close[t]/close[t-k]-1)
      - atr_pct  over atr_win           (abs CC mean)
      - vol{w}   for w in vol_windows   (std of daily returns over last w)
    Writes to state['features'][sym].
    """
    univ = list(state.get("universe", []) or [])
    if not univ:
        return

    need = max([atr_win] + list(lookbacks) + [max(vol_windows or [0])]) + 1
    mat = _stack_prices_matrix(state, univ, need_bars=need)  # (N, T)
    T = mat.shape[1]
    feats = state.setdefault("features", {})

    # pct-change matrix for vol/ATR; requires at least 2 bars
    if T >= 2:
        rets = (mat[:, 1:] / _np.maximum(1e-9, mat[:, :-1]) - 1.0).astype(_np.float32)
    else:
        rets = _np.zeros((len(univ), 0), dtype=_np.float32)

    # returns over lookbacks
    for k in lookbacks:
        col = _np.zeros((len(univ),), dtype=_np.float32)
        if T >= k + 1:
            col = (mat[:, -1] / _np.maximum(1e-9, mat[:, -1-k]) - 1.0).astype(_np.float32)
        for i, s in enumerate(univ):
            f = feats.setdefault(s, {})
            f[f"ret{k}"] = float(col[i])

    # ATR% proxy (mean abs return over window)
    atr_col = _np.zeros((len(univ),), dtype=_np.float32)
    if rets.shape[1] >= atr_win:
        atr_col = _np.mean(_np.abs(rets[:, -atr_win:]), axis=1).astype(_np.float32)
    for i, s in enumerate(univ):
        feats.setdefault(s, {})["atr_pct"] = float(atr_col[i])

    # vol windows (std of returns)
    for w in vol_windows:
        vcol = _np.zeros((len(univ),), dtype=_np.float32)
        if rets.shape[1] >= w:
            vcol = _np.std(rets[:, -w:], axis=1).astype(_np.float32)
        key = f"vol{w}"
        for i, s in enumerate(univ):
            feats.setdefault(s, {})[key] = float(vcol[i])


# ────────────── tiny helpers ──────────────
def _cfg(dct, *path, default=None):
    cur = dct or {}
    for k in path:
        if not isinstance(cur, dict): return default
        cur = cur.get(k, {})
    return cur if cur else (default if isinstance(default, (dict, list)) else (cur or default))

def _series(state, sym):
    arr = (state.get("prices", {}) or {}).get(sym)
    return arr if isinstance(arr, (list, tuple)) and len(arr) else None

def _last(state, sym, default=None):
    seq = _series(state, sym)
    return (seq[-1] if (seq and len(seq)) else default)

def _prev_close(state, sym, default=None):
    # prefer server-computed prev_close if present; else bars[-2]
    pc_map = state.get("prev_close", {}) or {}
    if sym in pc_map: return pc_map[sym]
    seq = _series(state, sym)
    return (seq[-2] if (seq and len(seq) >= 2) else default)

def _sma(seq, n):
    if not seq or len(seq) < n: return None
    return sum(seq[-n:]) / float(n)

def _stdev(seq, n):
    if not seq or len(seq) < n: return None
    return statistics.pstdev(seq[-n:])

def _rollmax(seq, n):
    if not seq or len(seq) < n: return None
    return max(seq[-n:])

def _rollmin(seq, n):
    if not seq or len(seq) < n: return None
    return min(seq[-n:])

def _clip01(x): 
    try: return 0.0 if x is None else 1.0 if x > 1 else (0.0 if x < 0 else float(x))
    except Exception: return 0.0

def _allow_shorts(state):
    return bool(((state.get("config", {}) or {}).get("risk", {}) or {}).get("allow_shorts", False))



    
# ──────────────────────────────────────────────────────────────────────────────
# 1) VolBreakoutAnalyst — Donchian+volatility breakout timing
# cfg["analysts"]["VolBreakoutAnalyst"] = {"lookback": 20, "z_k": 1.0, "min_bars": 40, "top_k": 15}
# ──────────────────────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────────────────────
# 2) GapFadeAnalyst — fade large overnight gaps (MR intraday/1–2 day)
# cfg["analysts"]["GapFadeAnalyst"] = {"gap_thr": 0.03, "max_gap": 0.12, "top_k": 10}
# ──────────────────────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────────────────
# 3) LiquidityFilterAnalyst — contributes HOLD to lower quorum when illiquid
# cfg["analysts"]["LiquidityFilterAnalyst"] = {
#     "min_adv": 3_000_000,
#     "max_spread_bps": 30,
#     "min_price": 5,             # optional
#     "max_price": 80             # optional
# }
# Expects state["altdata"]["liquidity"][sym] like {"adv": float, "spread_bps": float}
# Also (optionally) uses latest price from state to screen a price band.
# ──────────────────────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────────────────────
# 4) RegimeFilter — writes state["regime"] = "ON"/"OFF" using breadth + MA trend
# cfg["analysts"]["RegimeFilter"] = {"ma": 200, "breadth_sym_count": 200, "on_thr": 0.55, "off_thr": 0.45}
# ──────────────────────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────────────────
# 5) QualityAnalyst — prefers high-quality fundamentals (needs altdata.quality)
# cfg["analysts"]["QualityAnalyst"] = {"top_k": 20}
# Expects state["altdata"]["quality"][sym] in [0..1] or a numeric rank/score.
# ──────────────────────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────────────────
# 6) ValueAnalyst — favors cheaper names (needs altdata.value)
# cfg["analysts"]["ValueAnalyst"] = {"top_k": 20}
# Expects state["altdata"]["value"][sym] where higher = cheaper (e.g., FCF yield)
# ──────────────────────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────────────────
# 7) EarningsSurpriseAnalyst — leans with recent surprises (needs altdata.earnings)
# cfg["analysts"]["EarningsSurpriseAnalyst"] = {"min_abs_surprise": 0.02, "half_life_days": 10}
# Expects state["altdata"]["earnings"][sym] like {"surprise": +0.07, "days_since": 3}
# ──────────────────────────────────────────────────────────────────────────────



# ──────────────────────────────────────────────────────────────────────────────
# 8) PostEarningsDriftAnalyst — continuation for ~20 trading days post surprise
# cfg["analysts"]["PostEarningsDriftAnalyst"] = {"window_days": 20, "min_move": 0.03}
# Needs the same altdata.earnings (days_since). Uses price drift confirmation.
# ──────────────────────────────────────────────────────────────────────────────



# ──────────────────────────────────────────────────────────────────────────────
# 9) InsiderFlowAnalyst — clustered officer buys as a positive signal
# cfg["analysts"]["InsiderFlowAnalyst"] = {"min_dollar": 250000, "lookback_days": 90}
# Expects state["altdata"]["insiders"][sym] like {"net_buy_usd": ..., "days_since": ...}
# ──────────────────────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────────────────
# 10) DefensiveAnalyst — low-vol “defensive” BUYs in OFF regime
# cfg["analysts"]["DefensiveAnalyst"] = {"vol_lb": 60, "top_k": 10}
# ──────────────────────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────────────────
# 11) ShortHedgeAnalyst — index/sector SELL overlay when OFF regime
# cfg["analysts"]["ShortHedgeAnalyst"] = {"tickers": ["SPY","QQQ"], "ma": 200}
# ──────────────────────────────────────────────────────────────────────────────
            
            
            

# ---------- Analysts ----------
# ---------- New Analyst: Volatility & Opportunity (1–5 day) ----------
















import datetime as _dt

def _as_list(x):
    if x is None: return []
    if isinstance(x, list): return x
    if isinstance(x, dict): return [x]
    return []

def _parse_date_any(s):
    if not s: return None
    # try common layouts
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return _dt.datetime.strptime(str(s)[:len(fmt)], fmt).date()
        except Exception:
            continue
    # last resort: fromisoformat (py3.11 tolerates some variants)
    try:
        return _dt.date.fromisoformat(str(s)[:10])
    except Exception:
        return None

def _today_date(state):
    # if you keep a 'today' in state (e.g., for backtests), prefer it
    ts = state.get("sim_time") or state.get("_now_ts")
    if ts:
        try: return _dt.datetime.fromtimestamp(float(ts)).date()
        except Exception: pass
    return _dt.date.today()

def _earnings_latest_tuple(ed_entry, state):
    """
    Returns (days_since:int, surprise:float or None) for the most recent earnings record.
    Accepts dict or list-of-dicts with flexible field names.
    """
    recs = _as_list(ed_entry)
    if not recs:
        return None, None

    # Pick "most recent": prefer explicit days_since, else latest date
    today = _today_date(state)
    best = None
    best_ds = None

    for r in recs:
        if not isinstance(r, dict):
            continue

        # 1) days_since if present
        ds = r.get("days_since")
        if ds is None:
            # 2) else derive from any likely date field
            date_field = r.get("date") or r.get("report_date") or r.get("reportDate") or r.get("earningDate") or r.get("fiscalDateEnding")
            d = _parse_date_any(date_field)
            if d:
                ds = (today - d).days
        try:
            ds = int(ds) if ds is not None else None
        except Exception:
            ds = None

        if ds is None or ds < 0:
            continue

        if best_ds is None or ds <= best_ds:
            best, best_ds = r, ds

    if best is None:
        return None, None

    # Surprise (signed)
    spr = best.get("surprise")
    if spr is None:
        spr = best.get("surprise_pct") or best.get("surprisePercent") or best.get("surprise_percent")
    try:
        spr = float(spr) if spr is not None else None
    except Exception:
        spr = None

    # If still None, try derive from EPS actual/estimate
    if spr is None:
        actual = best.get("eps_actual") or best.get("actualEPS") or best.get("reportedEPS")
        est    = best.get("eps_estimate") or best.get("estimatedEPS") or best.get("consensusEPS")
        try:
            actual = float(actual); est = float(est)
            if est and abs(est) > 1e-9:
                spr = (actual - est) / abs(est)    # fraction (+ = beat)
        except Exception:
            pass

    # If it's clearly a percentage like 7.5 for +7.5%, convert to fraction
    if spr is not None and abs(spr) > 2.0:
        spr = spr / 100.0

    return best_ds, spr

# 1) EarningsProximityVetoAnalyst — HOLD near earnings

# 2) RelativeVolumeAnalyst — BUY boost when RVOL high (and optional direction filter)

# 3) VolRegimeAnalyst — HOLD gate when VIX / realized vol is high

# ──────────────────────────────────────────────────────────────────────────────
# DrawdownGuardAnalyst — portfolio (or proxy) drawdown cool-down gate
# cfg["analysts"]["DrawdownGuardAnalyst"] = {
#   "dd_soft": 0.20, "dd_hard": 0.30,
#   "cooldown_bars": 10,
#   "conf_soft": 0.75, "conf_hard": 0.95,
#   "proxy": "SPY"        # used if portfolio NAV not available
# }
# Publishes HOLD to make quorum harder when DD is elevated. Hard breach ⇒
# stronger HOLD and start a cool-down window (bars) during which new entries
# are discouraged.
# ──────────────────────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────────────────
# GapGoAnalyst — classify gap-and-go vs. fade; default = HOLD to avoid fading go
# cfg["analysts"]["GapGoAnalyst"] = {
#   "gap_min": 0.02,              # minimum gap to consider
#   "trend_lookback": 20,         # trend horizon
#   "trend_thr": 0.03,            # min |trend| to call "go"
#   "mode": "hold",               # "hold" (block fades) or "reinforce" (BUY/SELL with the go)
#   "min_conf": 0.35, "max_conf": 0.90
# }
# Logic:
#   gap_up & trend_up  (>|trend_thr|) → "gap-and-go"
#   gap_dn & trend_dn  (>|trend_thr|) → "gap-and-go"
# Default behavior publishes HOLD so MeanRev/GAP-FADE won’t fight strong continuation
# (set mode="reinforce" to emit BUY on up-go, SELL on down-go).
# ──────────────────────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────────────────
# 52-Week-High Proximity (“Fresh Highs”)
# cfg["analysts"]["Week52HighAnalyst"] = {
#   "lb": 252, "proximity": 0.03, "contract_win": 20, "prior_win": 40,
#   "min_conf": 0.3, "max_conf": 0.9, "top_k": 12
# }
# ──────────────────────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────────────────
# Volatility-Contraction / NR7 (“VCP”)
# cfg["analysts"]["VolatilityContractionAnalyst"] = {
#   "nrn": 7, "lookback": 20, "rs_lb": 20, "min_conf": 0.3, "max_conf": 0.85, "top_k": 15, "spy": "SPY"
# }
# Uses H-L if available; falls back to |ΔC|.
# ──────────────────────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────────────────
# Overnight-Edge Split (Close→Open vs Open→Close)
# cfg["analysts"]["OvernightEdgeAnalyst"] = { "lookback": 120, "min_edge": 0.0005, "top_k": 15 }
# Requires O/C. Falls back gracefully if missing.
# ──────────────────────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────────────────
# Residual Momentum (idiosyncratic RS)
# cfg["analysts"]["ResidualMomentumAnalyst"] = {
#   "lookback": 126, "tail": 21, "peer_mode": "spy", "spy": "SPY",
#   "min_conf": 0.25, "max_conf": 0.9, "allow_sell": true, "top_k": 20
# }
# If peer_mode == "sector", uses altdata.sector_etf[symbol] -> ETF ticker.
# ──────────────────────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────────────────
# Anchored-VWAP-to-Event (AVWAP Earn)
# cfg["analysts"]["AvwapEarningsAnalyst"] = {
#   "anchor": "earnings", "max_days": 60, "min_dist": 0.0, "max_dist": 0.06,
#   "require_contraction": true, "contr_win": 20, "contr_prior": 40
# }
# Tries OHLCV; falls back to C*Vol; last event = most recent from altdata.earnings.
# ──────────────────────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────────────────
# Breadth/Dispersion Regime Boost
# cfg["analysts"]["DispersionRegimeAnalyst"] = {
#   "r_lb": 20, "high_thr": 0.12, "low_thr": 0.06, "boost_top_n": 8,
#   "min_conf": 0.25, "max_conf": 0.6
# }
# Sets state["dispersion"]="HIGH"/"LOW"; boosts momentum in HIGH, gates in LOW.
# ──────────────────────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────────────────
# Calendar/OPEX & Turn-of-Month Tilt (lightweight)
# cfg["analysts"]["CalendarTiltAnalyst"] = {
#   "turn_window": 3, "opex_window": 1, "boost_top_n": 8, "min_conf": 0.2, "max_conf": 0.5
# }
# ──────────────────────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────────────────
# Pair/Relative-Value (within industry)
# cfg["analysts"]["PairRelativeValueAnalyst"] = {
#   "group_key": "industry", "lb": 20, "top_n_per_grp": 2, "min_conf": 0.3, "max_conf": 0.8
# }
# Uses altdata[group_key][symbol] to form groups; prefers near-highs with lower ATR%.
# ──────────────────────────────────────────────────────────────────────────────


import numpy as np
import pandas as pd

# Auto-generated exports for extracted classes
from .FeatureAccelerator import FeatureAccelerator
from .VolBreakoutAnalyst import VolBreakoutAnalyst
from .GapFadeAnalyst import GapFadeAnalyst
from .LiquidityFilterAnalyst import LiquidityFilterAnalyst
from .RegimeFilter import RegimeFilter
from .QualityAnalyst import QualityAnalyst
from .ValueAnalyst import ValueAnalyst
from .EarningsSurpriseAnalyst import EarningsSurpriseAnalyst
from .PostEarningsDriftAnalyst import PostEarningsDriftAnalyst
from .InsiderFlowAnalyst import InsiderFlowAnalyst
from .DefensiveAnalyst import DefensiveAnalyst
from .ShortHedgeAnalyst import ShortHedgeAnalyst
from .VolatilityOpportunityAnalyst import VolatilityOpportunityAnalyst
from .LiquidityAndSpreadAnalyst import LiquidityAndSpreadAnalyst
from .ValueScreenAnalyst import ValueScreenAnalyst
from .ShortInterestSqueezeAnalyst import ShortInterestSqueezeAnalyst
from .SectorRotationAnalyst import SectorRotationAnalyst
from .InsiderActivityAnalyst import InsiderActivityAnalyst
from .CrossMarketRelativeStrengthAnalyst import CrossMarketRelativeStrengthAnalyst
from .MomentumAnalyst import MomentumAnalyst
from .MeanRevAnalyst import MeanRevAnalyst
from .CrossSectionMomentumAnalyst import CrossSectionMomentumAnalyst
from .EarningsProximityVetoAnalyst import EarningsProximityVetoAnalyst
from .RelativeVolumeAnalyst import RelativeVolumeAnalyst
from .VolRegimeAnalyst import VolRegimeAnalyst
from .DrawdownGuardAnalyst import DrawdownGuardAnalyst
from .GapGoAnalyst import GapGoAnalyst
from .Week52HighAnalyst import Week52HighAnalyst
from .VolatilityContractionAnalyst import VolatilityContractionAnalyst
from .OvernightEdgeAnalyst import OvernightEdgeAnalyst
from .ResidualMomentumAnalyst import ResidualMomentumAnalyst
from .AvwapEarningsAnalyst import AvwapEarningsAnalyst
from .DispersionRegimeAnalyst import DispersionRegimeAnalyst
from .CalendarTiltAnalyst import CalendarTiltAnalyst
from .PairRelativeValueAnalyst import PairRelativeValueAnalyst
from .BreakoutAnalyst import BreakoutAnalyst

__all__ = [
    'FeatureAccelerator',
    'VolBreakoutAnalyst',
    'GapFadeAnalyst',
    'LiquidityFilterAnalyst',
    'RegimeFilter',
    'QualityAnalyst',
    'ValueAnalyst',
    'EarningsSurpriseAnalyst',
    'PostEarningsDriftAnalyst',
    'InsiderFlowAnalyst',
    'DefensiveAnalyst',
    'ShortHedgeAnalyst',
    'VolatilityOpportunityAnalyst',
    'LiquidityAndSpreadAnalyst',
    'ValueScreenAnalyst',
    'ShortInterestSqueezeAnalyst',
    'SectorRotationAnalyst',
    'InsiderActivityAnalyst',
    'CrossMarketRelativeStrengthAnalyst',
    'MomentumAnalyst',
    'MeanRevAnalyst',
    'CrossSectionMomentumAnalyst',
    'EarningsProximityVetoAnalyst',
    'RelativeVolumeAnalyst',
    'VolRegimeAnalyst',
    'DrawdownGuardAnalyst',
    'GapGoAnalyst',
    'Week52HighAnalyst',
    'VolatilityContractionAnalyst',
    'OvernightEdgeAnalyst',
    'ResidualMomentumAnalyst',
    'AvwapEarningsAnalyst',
    'DispersionRegimeAnalyst',
    'CalendarTiltAnalyst',
    'PairRelativeValueAnalyst',
    'BreakoutAnalyst',
]
