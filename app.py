"""
╔══════════════════════════════════════════════════════════════╗
║         MACD 瀑布動能傳導系統  v2.0                          ║
║                                                              ║
║  設計原理：                                                   ║
║  1. 時框瀑布傳導：1m→5m→15m→30m→1h→1d→1w                   ║
║     小時框動能積累，逐層推動大時框翻轉                         ║
║                                                              ║
║  2. 大時框定方向（1d/1w）確認主趨勢                           ║
║     小時框找入場點（30m Histogram D+1 預測翻正）              ║
║                                                              ║
║  3. D+1/D+2/D+3 = 提前預判翻轉時間點                        ║
║     不是等信號發生才通知，而是提前告知「即將翻正」             ║
║     讓用戶有時間準備，而不是追漲                              ║
║                                                              ║
║  4. 觸發邏輯：                                               ║
║     確認時框(1d/1h) Histogram > 0  ← 大方向多頭              ║
║     觸發時框(30m)  當前 Hist < 0   ← 尚未入場                ║
║     觸發時框(30m)  D+1 預測 > 0    ← 預計翻正 → 預警         ║
║                                                              ║
║  ── v2.1 新增（2026-07-03，因應 07-02 TSLA 暴跌）──          ║
║  5. 空頭側對稱警報：                                         ║
║     a) Hist > 0 且 D+1 < 0        → 預警：預測翻負           ║
║     b) 前根 ≥ 0 → 當根 < 0        → 警報：實際翻負           ║
║     c) Hist < 0 且 D+1 < Hist                                 ║
║        且大時框半數同向轉空       → 警報：瀑布下行           ║
║  6. 「接近反轉」閾值改用 Hist 滾動σ歸一化（0.15σ）           ║
║  7. Telegram 警報自動推送（MD5 去重，每訊號每小時一次）      ║
║  8. 空頭警報：紅色橫幅 + 反向 ATR 止損/目標                  ║
║                                                              ║
║  ── v2.2/v2.3 新增（量能整合 + 計分制 + 交易建議）──         ║
║  9. RVOL 相對量能：日內用「過去10天同時段」基準，            ║
║     解決日內 U 形量能造成的開盤誤報                          ║
║  10. VWAP 當日錨定：價格在 VWAP 上/下方作方向確認            ║
║  11. 開盤缺口偵測：跳空 ≥1.5% 直接高分警報                   ║
║  12. 計分制警報（多空對稱）：                                ║
║      翻轉 +2｜D+1 預測翻轉 +1｜加速>1.5σ +2                  ║
║      RVOL ≥2.5 +3｜1.5–2.5 +1｜<0.8 −2（記到陰/陽方向）     ║
║      VWAP 方向 +1｜大時框同向每個 +1｜缺口 +3                ║
║      ≥5 分 🔴 警報｜3–4 分 🟠 觀察｜<3 分靜默                ║
║  13. 訊號判定一律用「已收盤」bar，杜絕未收盤 bar 重繪誤報    ║
║  14. 時間戳修正為真正的美東時間；休市/非交易時段標註         ║
╚══════════════════════════════════════════════════════════════╝
"""

import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
import requests
import time
import hashlib
from zoneinfo import ZoneInfo

# ══════════════════════════════════════════════════════════════
# 頁面設定
# ══════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="MACD 瀑布動能系統",
    page_icon="🌊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ══════════════════════════════════════════════════════════════
# 設計系統 CSS
# ══════════════════════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600;700&family=Noto+Sans+TC:wght@400;500;700&display=swap');

html, body, [class*="css"] {
    font-family: 'Noto Sans TC', sans-serif;
    background-color: #f5f2ed;
    color: #2c2c2c;
}
.stApp { background-color: #f5f2ed; }
[data-testid="stSidebar"] {
    background-color: #ede9e2;
    border-right: 1px solid #d4cfc6;
}
h1,h2,h3 { font-family: 'IBM Plex Mono', monospace; color: #2c2c2c; }

/* ── 指標卡片 ── */
.metric-card {
    background: #fff8f0;
    border: 1px solid #d4cfc6;
    border-radius: 12px;
    padding: 14px 16px;
    margin: 4px 0;
    font-family: 'IBM Plex Mono', monospace;
    height: 100%;
    box-sizing: border-box;
}
.metric-card .label {
    font-size: 10px; color: #999;
    text-transform: uppercase; letter-spacing: 1px;
}
.metric-card .value {
    font-size: 22px; font-weight: 700; margin: 4px 0 2px;
}
.metric-card .sub { font-size: 12px; color: #777; }

/* ── 顏色 ── */
.pos { color: #3d8b5e; }
.neg { color: #c0392b; }
.neu { color: #7a7a7a; }

/* ── Badge ── */
.badge {
    display: inline-block; padding: 2px 8px;
    border-radius: 4px; font-size: 11px; font-weight: 700;
}
.badge-bull { background:#d4edda; color:#1e6b3d; }
.badge-bear { background:#fde8e8; color:#9b2335; }
.badge-warn { background:#fff3cd; color:#7d5a00; }
.badge-neu  { background:#e8e8e8; color:#555; }

/* ── MACD 表格 ── */
.macd-table {
    width:100%; border-collapse:collapse;
    font-family:'IBM Plex Mono',monospace; font-size:12px;
    background:#fff8f0; border-radius:10px;
    overflow:hidden; border:1px solid #d4cfc6;
}
.macd-table th {
    background:#e8e3da; color:#555; padding:9px 10px;
    text-align:center; font-weight:700; font-size:10px;
    letter-spacing:0.5px; white-space:nowrap;
}
.macd-table td {
    padding:8px 10px; text-align:center;
    border-bottom:1px solid #ede9e2; white-space:nowrap;
}
.macd-table tr:last-child td { border-bottom:none; }
.macd-table tr:hover td { background:#f0ece5; }
.cell-pos { color:#3d8b5e; font-weight:700; }
.cell-neg { color:#c0392b; font-weight:700; }

/* ── 預警卡片 ── */
.alert-card {
    background:linear-gradient(135deg,#fffbf0,#fff3d4);
    border:2px solid #f0c040; border-radius:12px;
    padding:16px 20px; margin:8px 0;
}
.alert-card-bear {
    background:linear-gradient(135deg,#fff5f4,#fde8e8);
    border:2px solid #c0392b; border-radius:12px;
    padding:16px 20px; margin:8px 0;
}
.alert-body {
    font-size:13px; color:#444; line-height:2;
    font-family:'IBM Plex Mono',monospace;
}

/* ── 共振評分 ── */
.resonance-score {
    display:inline-flex; align-items:center; gap:4px;
    background:#fff8f0; border:1px solid #d4cfc6;
    border-radius:20px; padding:4px 14px;
    font-family:'IBM Plex Mono',monospace; font-size:12px;
}
.star-on  { color:#f0a500; font-size:15px; }
.star-off { color:#ddd;    font-size:15px; }

/* ── Telegram 預覽 ── */
.tg-box {
    background:#fff8f0; border:1px solid #d4cfc6;
    border-left:4px solid #4a8c6f; border-radius:8px;
    padding:14px 18px; font-size:12px;
    white-space:pre-wrap; font-family:'IBM Plex Mono',monospace;
    line-height:1.8;
}

/* ── 趨勢 pill ── */
.pill-bull { background:#d4edda; color:#1e6b3d; padding:3px 10px; border-radius:20px; font-weight:700; font-size:11px; display:inline-block; }
.pill-bear { background:#fde8e8; color:#9b2335; padding:3px 10px; border-radius:20px; font-weight:700; font-size:11px; display:inline-block; }
.pill-neu  { background:#e8e8e8; color:#555;    padding:3px 10px; border-radius:20px; font-weight:700; font-size:11px; display:inline-block; }
.pill-warn { background:#fff3cd; color:#7d5a00; padding:3px 10px; border-radius:20px; font-weight:700; font-size:11px; display:inline-block; }

hr { border-color:#d4cfc6; }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
# 常數
# ══════════════════════════════════════════════════════════════
CASCADE_CHAIN = ["1m","5m","15m","30m","1h","1d","1w"]

TIMEFRAME_MAP = {
    "1m":  {"period":"1d",   "interval":"1m"},
    "5m":  {"period":"5d",   "interval":"5m"},
    "15m": {"period":"10d",  "interval":"15m"},
    "30m": {"period":"30d",  "interval":"30m"},
    "1h":  {"period":"60d",  "interval":"1h"},
    "1d":  {"period":"180d", "interval":"1d"},
    "1w":  {"period":"2y",   "interval":"1wk"},
    "1mo": {"period":"5y",   "interval":"1mo"},
}

DEFAULT_SYMBOLS = ["TSLA","AAPL","AMZN","NVDA","MSFT"]

STATUS_NEXT_DAY = {
    "空頭動能強":    ("跌勢延續",    "bear"),
    "空頭減弱":      ("跌速放慢",    "warn"),
    "跌勢放緩":      ("接近底部",    "warn"),
    "空頭衰退":      ("技術反彈",    "warn"),
    "接近反轉":      ("金叉概率提升","neu"),
    "多頭開始回補":  ("動能轉正",    "bull"),
    "Histogram翻正": ("短線突破",    "bull"),
    "Histogram翻負": ("跌勢展開",    "bear"),
    "MACD金叉確認":  ("多頭加速",    "bull"),
    "多頭加速":      ("趨勢延續",    "bull"),
    "強勢多頭":      ("趨勢延續",    "bull"),
}


# ══════════════════════════════════════════════════════════════
# 核心計算
# ══════════════════════════════════════════════════════════════
def calc_ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

def calc_macd(close, fast=12, slow=26, signal=9):
    ml  = calc_ema(close, fast) - calc_ema(close, slow)
    sl  = calc_ema(ml, signal)
    return ml, sl, ml - sl

def calc_atr(df, period=14):
    h, l, cp = df["High"], df["Low"], df["Close"].shift(1)
    tr = pd.concat([h-l, (h-cp).abs(), (l-cp).abs()], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean().iloc[-1]

# ── v2.2 量能指標 ────────────────────────────────────────────
INTRADAY_IVS = {"1m","5m","15m","30m","1h","60m","90m"}

def calc_rvol(df):
    """
    RVOL（日內版）：當前 bar 成交量 ÷ 過去10天「同一時段」平均量。
    日內量能天然呈 U 形（開盤/尾盤爆量、午盤清淡），
    用同時段基準才不會在開盤時段永遠誤報放量。
    """
    try:
        tod  = df.index.strftime("%H:%M")
        base = df["Volume"].groupby(tod).transform(
            lambda s: s.shift(1).rolling(10, min_periods=3).mean())
        return df["Volume"] / base
    except Exception:
        return pd.Series(np.nan, index=df.index)

def calc_rvol_simple(df, n=20):
    """RVOL（日/週線版）：當前量 ÷ 前 n 根平均量"""
    base = df["Volume"].shift(1).rolling(n, min_periods=5).mean()
    return df["Volume"] / base

def calc_vwap(df):
    """當日錨定 VWAP（僅日內時框有意義）"""
    tp  = (df["High"] + df["Low"] + df["Close"]) / 3
    day = df.index.normalize()
    cum_pv = (tp * df["Volume"]).groupby(day).cumsum()
    cum_v  = df["Volume"].groupby(day).cumsum()
    return cum_pv / cum_v.replace(0, np.nan)

def calc_rolling_vwap(df, n=20):
    """
    滾動 VWAP（日線／週線用）。
    日線一根 K = 一天，用「當日錨定」會退化成該根自己的典型價
    （價格跟自己比恆等於零，毫無資訊量），故改用 n 根滾動的
    成交量加權均價，作為中期持倉成本錨。
    """
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    pv = (tp * df["Volume"]).rolling(n, min_periods=max(3, n//4)).sum()
    v  = df["Volume"].rolling(n, min_periods=max(3, n//4)).sum()
    return pv / v.replace(0, np.nan)

def predict_next3(hist):
    """
    D+1: 線性外推（延續當前動能斜率）
    D+2: 動能開始鈍化（斜率減半）
    D+3: 慣性衰減（大概率回落）
    """
    if len(hist) < 3:
        return 0.0, 0.0, 0.0
    v = hist.iloc[-3:].values
    slope = (v[-1] - v[0]) / 2
    d1 = v[-1] + slope
    d2 = d1 + slope * 0.5
    d3 = d2 - abs(slope) * 0.3
    return d1, d2, d3

def classify_status(hist, macd, signal):
    out = []
    # 反轉閾值用 Histogram 滾動標準差歸一化（取代固定 0.005，
    # 否則 TSLA 5m 級別的 Hist 永遠不會命中「接近反轉」）
    sig_roll = hist.rolling(40, min_periods=5).std()
    for i in range(len(hist)):
        h  = hist.iloc[i]
        hp = hist.iloc[i-1]  if i>0 else h
        m  = macd.iloc[i]
        s  = signal.iloc[i]
        mp = macd.iloc[i-1]  if i>0 else m
        sp = signal.iloc[i-1] if i>0 else s
        sg = sig_roll.iloc[i]
        thr = max(0.005, 0.15 * sg) if pd.notna(sg) else 0.005
        if   abs(h) < thr:                        st = "接近反轉"
        elif i>0 and hp<0 and h>=0:               st = "Histogram翻正"
        elif i>0 and hp>=0 and h<0:               st = "Histogram翻負"
        elif i>0 and m>s and mp<=sp:              st = "MACD金叉確認"
        elif h>0 and m>0:                          st = "強勢多頭"
        elif h>0 and i>0 and h>hp:                st = "多頭加速"
        elif h<0 and i>0 and h<hp:                st = "空頭動能強"
        elif h<0 and i>0 and abs(h)<abs(hp):      st = "空頭減弱" if h<=hp else "跌勢放緩"
        elif h<0:                                  st = "空頭動能強"
        else:                                      st = "多頭加速"
        out.append(st)
    return out

def get_trend(macd_val, hist_val, status):
    if macd_val>0 and hist_val>0:   return "強勢多頭"
    elif hist_val>0:                 return "多頭趨勢"
    elif hist_val<0 and macd_val<0: return "空頭趨勢"
    elif any(k in status for k in ["接近反轉","翻正","金叉"]): return "趨勢反轉中"
    else:                            return "震盪觀望"

def trend_pill(tr):
    m = {"強勢多頭":"bull","多頭趨勢":"bull","空頭趨勢":"bear","趨勢反轉中":"warn"}
    c = m.get(tr,"neu")
    i = {"bull":"▲","bear":"▼","warn":"◆","neu":"●"}[c]
    return f'<span class="pill-{c}">{i} {tr}</span>'

def badge_html(st):
    if any(k in st for k in ["多頭","翻正","金叉","放緩"]):
        return f'<span class="badge badge-bull">▲ {st}</span>'
    elif any(k in st for k in ["空頭","動能強","翻負"]):
        return f'<span class="badge badge-bear">▼ {st}</span>'
    elif any(k in st for k in ["接近反轉","減弱"]):
        return f'<span class="badge badge-warn">◆ {st}</span>'
    return f'<span class="badge badge-neu">● {st}</span>'

def nd_badge(status):
    txt, typ = STATUS_NEXT_DAY.get(status, ("待觀察","neu"))
    i = {"bull":"▲","bear":"▼","warn":"◆","neu":"●"}.get(typ,"●")
    return f'<span class="badge badge-{typ}">{i} {txt}</span>'

def fmt(v, d=3):
    return f"{v:+.{d}f}"

def pc(v):
    if v == "—": return "<td>—</td>"
    fv = float(v.replace("+",""))
    c  = "cell-pos" if fv>=0 else "cell-neg"
    return f'<td class="{c}">{v}</td>'


# ══════════════════════════════════════════════════════════════
# 資料獲取
# ══════════════════════════════════════════════════════════════
def fetch_data(symbol, period, interval):
    """
    Session-state 快取版本：
    - 每次頁面載入檢查快取是否過期
    - 過期（超過 refresh_interval 秒）→ 清除快取，重新拉取
    - 未過期 → 直接返回 session_state 中的 DataFrame
    - 完全不依賴 st.cache_data，確保自動刷新時數據一定更新
    """
    import time as _t
    ttl      = st.session_state.get("refresh_interval", 60)
    cache_key = f"df_{symbol}_{period}_{interval}"
    ts_key    = f"ts_{symbol}_{period}_{interval}"
    now       = _t.time()

    # 檢查是否需要更新
    last_fetch = st.session_state.get(ts_key, 0)
    if now - last_fetch >= ttl or cache_key not in st.session_state:
        # 過期或從未拉取 → 重新取數據
        try:
            df = yf.Ticker(symbol).history(period=period, interval=interval)
            if df.empty:
                df = pd.DataFrame()
            else:
                df = df[["Open","High","Low","Close","Volume"]].dropna()
        except:
            df = pd.DataFrame()
        st.session_state[cache_key] = df
        st.session_state[ts_key]    = now

    return st.session_state[cache_key]


# ══════════════════════════════════════════════════════════════
# 瀑布傳導分析
# ══════════════════════════════════════════════════════════════
def analyze_cascade(symbol, chain):
    results = []
    for tf in chain:
        cfg = TIMEFRAME_MAP.get(tf)
        if not cfg:
            continue
        df = fetch_data(symbol, cfg["period"], cfg["interval"])
        if df.empty or len(df) < 30:
            results.append({"tf":tf, "valid":False})
            continue
        intraday = cfg["interval"] in INTRADAY_IVS
        macd, sig, hist = calc_macd(df["Close"])
        sts  = classify_status(hist, macd, sig)
        hv   = hist.iloc[-1]     # 最後一根（可能未收盤，僅顯示用）
        mv   = macd.iloc[-1]
        sv   = sts[-1]

        # ── v2.2：訊號判定一律用「已收盤」bar，避免未收盤 bar 重繪 ──
        hist_closed = hist.iloc[:-1] if len(hist) > 1 else hist
        hc  = hist_closed.iloc[-1]
        hcp = hist_closed.iloc[-2] if len(hist_closed) > 1 else hc
        # D+1/D+2/D+3 由已收盤序列外推（= 對「當前形成中 bar」的預測，不重繪）
        d1, d2, d3 = predict_next3(hist_closed)
        sigma = hist_closed.iloc[-40:].std() if len(hist_closed) >= 10 else max(abs(hc), 1e-9)

        # 動能加速（已收盤最後 3 根，>1.5σ 才算，過濾雜訊）
        accel_dn = accel_up = False
        if len(hist_closed) >= 3 and pd.notna(sigma) and sigma > 0:
            h3 = hist_closed.iloc[-3:].values
            accel_dn = bool(hc < 0 and h3[0] > h3[1] > h3[2] and (h3[0]-h3[2]) > 1.5*sigma)
            accel_up = bool(hc > 0 and h3[0] < h3[1] < h3[2] and (h3[2]-h3[0]) > 1.5*sigma)

        # ── 量能：RVOL（已收盤 bar）──
        rv_series = calc_rvol(df) if intraday else calc_rvol_simple(df)
        rvol = rv_series.iloc[-2] if len(rv_series) > 1 else np.nan

        # ── VWAP（已收盤 bar 位置）──
        #    日內：當日錨定 VWAP｜日/週線：20 根滾動 VWAP
        vwap_val, below_vwap = None, None
        vwap_kind = "當日VWAP" if intraday else "20期滾動VWAP"
        vw = calc_vwap(df) if intraday else calc_rolling_vwap(df)
        if len(vw) > 1 and pd.notna(vw.iloc[-2]):
            vwap_val   = float(vw.iloc[-2])
            below_vwap = bool(df["Close"].iloc[-2] < vwap_val)

        # ── 缺口（日內：當日開盤跳空｜日/週線：該根開盤 vs 前一根收盤）──
        gap_pct = None
        if intraday:
            days = df.index.normalize()
            uday = days.unique()
            if len(uday) >= 2:
                prev_close = df["Close"][days == uday[-2]].iloc[-1]
                gap_pct    = float(df["Open"][days == uday[-1]].iloc[0] / prev_close - 1)
        elif len(df) >= 3:
            prev_close = df["Close"].iloc[-3]
            if prev_close:
                gap_pct = float(df["Open"].iloc[-2] / prev_close - 1)

        bar_dn = bool(df["Close"].iloc[-2] < df["Open"].iloc[-2]) if len(df) > 1 else False

        results.append({
            "tf":tf, "valid":True,
            "hist":hv, "macd":mv, "status":sv,
            "hist_prev": hist.iloc[-2] if len(hist) > 1 else hv,
            "hist_c":hc, "hist_c_prev":hcp,
            "d1":d1, "d2":d2, "d3":d3,
            "sigma":sigma, "accel_dn":accel_dn, "accel_up":accel_up,
            "rvol": float(rvol) if pd.notna(rvol) else None,
            "vwap":vwap_val, "below_vwap":below_vwap, "vwap_kind":vwap_kind,
            "gap_pct":gap_pct, "bar_dn":bar_dn,
            "last_bar_day": str(df.index[-1].date()),
            "trend":get_trend(mv,hv,sv),
            "atr":calc_atr(df),
            "close":df["Close"].iloc[-1],
        })
    return results


ALERT_RED    = 5   # >= 5 分 → 紅色警報（立即行動級）
ALERT_YELLOW = 3   # 3–4 分  → 橙色觀察（提高注意）

def calc_resonance(cascade, confirm_tfs, trigger_tf):
    """
    v2.2 計分制警報引擎（多空完全對稱，全部用已收盤 bar 判定）：

      事件分：
        Histogram 翻轉          +2
        D+1 預測翻轉            +1
        動能加速（3根遞減>1.5σ） +2
        開盤缺口 |gap| >= 1.5%   +3
        大時框同向               每個 +1
      量能分（記到已收盤 K 線的陰/陽方向）：
        RVOL >= 2.5  +3（機構級）
        RVOL 1.5–2.5 +1（顯著放量）
        RVOL <  0.8  −2（縮量 → 大概率洗盤，壓制警報）
      位置分：
        價格 < VWAP → 空方 +1；價格 > VWAP → 多方 +1

      判定：事件錨定 — 必須至少有一個「事件分」訊號才能構成警報，
        同向/量能/VWAP 分只能加成、不能單獨發起（防止全天亂響）；
        取多/空較高分方向（同分空方優先＝風險優先）
        >= 5 分 → 紅色警報（推送）
        3–4 分 → 橙色觀察（推送）
        <  3 分 → 靜默
    """
    valid = [r for r in cascade if r.get("valid")]
    confirm_score, bear_score, confirm_max = 0, 0, 0
    for r in valid:
        if r["tf"] in confirm_tfs:
            confirm_max += 1
            h_ref = r.get("hist_c", r["hist"])
            if   h_ref > 0: confirm_score += 1
            elif h_ref < 0: bear_score    += 1

    trig      = next((r for r in valid if r["tf"] == trigger_tf), None)
    alert     = False
    atype     = None
    direction = None
    level     = None
    pts, detail = 0, []
    bear_pts, bull_pts = 0, 0
    bear_dt,  bull_dt  = [], []

    if trig:
        hc   = trig.get("hist_c", 0)
        hcp  = trig.get("hist_c_prev", hc)
        d1   = trig.get("d1", 0)
        rvol = trig.get("rvol")
        bvw  = trig.get("below_vwap")
        gap  = trig.get("gap_pct")

        # ── 空頭事件 ──────────────────────────────────────
        bear_evt = bull_evt = False
        if hcp >= 0 and hc < 0:
            bear_pts += 2; bear_dt.append("Histogram 翻負 +2"); bear_evt = True
        if hc > 0 and d1 < 0:
            bear_pts += 1; bear_dt.append("D+1 預測翻負 +1"); bear_evt = True
        if trig.get("accel_dn"):
            bear_pts += 2; bear_dt.append("空頭加速 >1.5σ +2"); bear_evt = True
        if gap is not None and gap <= -0.015:
            bear_pts += 3; bear_dt.append(f"開盤缺口 {gap*100:+.1f}% +3"); bear_evt = True
        if bear_score:
            bear_pts += bear_score
            bear_dt.append(f"大時框同向 ×{bear_score} +{bear_score}")

        # ── 多頭事件（鏡像）──────────────────────────────
        if hcp <= 0 and hc > 0:
            bull_pts += 2; bull_dt.append("Histogram 翻正 +2"); bull_evt = True
        if hc < 0 and d1 > 0:
            bull_pts += 1; bull_dt.append("D+1 預測翻正 +1"); bull_evt = True
        if trig.get("accel_up"):
            bull_pts += 2; bull_dt.append("多頭加速 >1.5σ +2"); bull_evt = True
        if gap is not None and gap >= 0.015:
            bull_pts += 3; bull_dt.append(f"開盤缺口 {gap*100:+.1f}% +3"); bull_evt = True
        if confirm_score:
            bull_pts += confirm_score
            bull_dt.append(f"大時框同向 ×{confirm_score} +{confirm_score}")

        # ── 量能分（依已收盤 K 線陰陽記方向）─────────────
        if rvol is not None and not np.isnan(rvol):
            vp, vtxt = 0, None
            if   rvol >= 2.5: vp, vtxt =  3, f"RVOL {rvol:.1f}× 機構級 +3"
            elif rvol >= 1.5: vp, vtxt =  1, f"RVOL {rvol:.1f}× 放量 +1"
            elif rvol <  0.8: vp, vtxt = -2, f"RVOL {rvol:.1f}× 縮量 −2"
            if vtxt:
                if trig.get("bar_dn"):
                    bear_pts += vp; bear_dt.append(vtxt)
                else:
                    bull_pts += vp; bull_dt.append(vtxt)

        # ── VWAP 位置分 ──────────────────────────────────
        if bvw is True:
            bear_pts += 1; bear_dt.append("價格 < VWAP +1")
        elif bvw is False:
            bull_pts += 1; bull_dt.append("價格 > VWAP +1")

        # ── 判定（事件錨定：無觸發框事件則不構成警報，
        #    同向分/量能分/VWAP分只能「加成」不能「發起」）──
        cands = []
        if bear_evt and bear_pts >= ALERT_YELLOW:
            cands.append(("bear", bear_pts, bear_dt))
        if bull_evt and bull_pts >= ALERT_YELLOW:
            cands.append(("bull", bull_pts, bull_dt))
        if cands:
            # 同分時取列表首位 = 空方優先（風險優先原則）
            direction, pts, detail = max(cands, key=lambda c: c[1])
            alert = True
            level = "red" if pts >= ALERT_RED else "yellow"
            if direction == "bear":
                atype = (f"警報：空頭 {pts} 分，建議減倉/離場" if level == "red"
                         else f"觀察：空頭訊號累積 {pts} 分")
            else:
                atype = (f"預警：多頭 {pts} 分，準備做多" if level == "red"
                         else f"觀察：多頭訊號累積 {pts} 分")

    # 星級共振分（沿用原顯示邏輯，按警報方向計對齊數）
    base  = bear_score if direction == "bear" else confirm_score
    total = base + (1 if alert else 0)
    return {
        "score":     total,
        "max":       confirm_max + 1,
        "alert":     alert,
        "atype":     atype,
        "direction": direction,
        "level":     level,
        "pts":       pts,
        "bear_pts":  bear_pts,
        "bull_pts":  bull_pts,
        "detail":    detail,
        "trigger":   trig,
    }


def stars_html(score, max_score):
    n      = 5
    filled = round(score / max_score * n) if max_score > 0 else 0
    s = "".join([
        '<span class="star-on">★</span>' if i < filled
        else '<span class="star-off">★</span>'
        for i in range(n)
    ])
    return f'<span class="resonance-score">{s} &nbsp;共振 {score}/{max_score}</span>'


# ══════════════════════════════════════════════════════════════
# 圖表
# ══════════════════════════════════════════════════════════════
def fmt_labels(index, interval):
    intraday = interval in ["1m","5m","15m","30m","1h","60m","90m"]
    out = []
    for ts in index:
        dt = pd.Timestamp(ts)
        try: dt = dt.tz_convert("America/New_York") if dt.tzinfo else dt
        except: pass
        out.append(dt.strftime("%m/%d %H:%M") if intraday else dt.strftime("%m/%d"))
    return out

def make_ticks(labels, interval):
    intraday = interval in ["1m","5m","15m","30m","1h","60m","90m"]
    step     = max(1, len(labels)//12)
    sel      = labels[::step]
    if not intraday:
        return sel, sel
    tt, prev = [], None
    for lbl in sel:
        parts = lbl.split(" ")
        d, t  = parts[0], (parts[1] if len(parts)>1 else lbl)
        tt.append(lbl if d != prev else t)
        prev = d
    return sel, tt

def build_macd_chart(df, symbol, macd, signal, hist, interval="1d"):
    xl = fmt_labels(df.index,     interval)
    xm = fmt_labels(macd.index,   interval)
    xh = fmt_labels(hist.index,   interval)
    xs = fmt_labels(signal.index, interval)

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.52,0.48], vertical_spacing=0.05,
                        subplot_titles=[f"{symbol} 收盤價", "MACD (12,26,9)"])

    fig.add_trace(go.Scatter(x=xl, y=df["Close"].values, mode="lines",
        name="收盤價", line=dict(color="#5a7fa8",width=2)), row=1,col=1)

    colors = ["#3d8b5e" if v>=0 else "#c0392b" for v in hist.values]
    fig.add_trace(go.Bar(x=xh, y=hist.values, name="Histogram",
        marker_color=colors, opacity=0.85), row=2,col=1)
    fig.add_trace(go.Scatter(x=xm, y=macd.values, mode="lines", name="MACD",
        line=dict(color="#5a7fa8",width=1.5)), row=2,col=1)
    fig.add_trace(go.Scatter(x=xs, y=signal.values, mode="lines", name="Signal",
        line=dict(color="#e07b39",width=1.5,dash="dot")), row=2,col=1)
    fig.add_hline(y=0, line_dash="dot", line_color="#bbb", row=2, col=1)

    tv, tt = make_ticks(xl, interval)
    xcfg = dict(type="category", tickvals=tv, ticktext=tt,
                tickangle=-35, gridcolor="#e8e3da", showgrid=True)
    fig.update_layout(
        paper_bgcolor="#fff8f0", plot_bgcolor="#fff8f0",
        font=dict(family="IBM Plex Mono, Noto Sans TC", color="#2c2c2c", size=11),
        margin=dict(l=10,r=10,t=36,b=20),
        legend=dict(orientation="h", y=1.02, x=0),
        height=480, xaxis_rangeslider_visible=False,
        xaxis=xcfg, xaxis2=xcfg,
    )
    fig.update_yaxes(gridcolor="#e8e3da", zeroline=True, zerolinecolor="#c0bbb2")
    return fig


def build_cascade_chart(cascade):
    """
    瀑布傳導總覽圖：
    - 實色柱 = 當前 Histogram
    - 半透明柱 = D+1 預測
    一眼看清傳導方向是否對齊
    """
    valid  = [r for r in cascade if r.get("valid")]
    tfs    = [r["tf"]   for r in valid]
    hists  = [r["hist"] for r in valid]
    d1s    = [r["d1"]   for r in valid]

    c_now  = ["#3d8b5e" if h>=0 else "#c0392b" for h in hists]
    c_pred = ["rgba(61,139,94,0.35)" if d>=0 else "rgba(192,57,43,0.35)" for d in d1s]
    b_pred = ["#3d8b5e" if d>=0 else "#c0392b" for d in d1s]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=tfs, y=hists, name="當前 Histogram",
        marker_color=c_now,
        text=[fmt(h,3) for h in hists],
        textposition="outside",
        textfont=dict(size=10, family="IBM Plex Mono"),
    ))
    fig.add_trace(go.Bar(
        x=tfs, y=d1s, name="D+1 預測",
        marker_color=c_pred,
        marker_line=dict(width=2, color=b_pred),
        text=[fmt(d,3) for d in d1s],
        textposition="outside",
        textfont=dict(size=10, family="IBM Plex Mono"),
    ))
    fig.add_hline(y=0, line_dash="dot", line_color="#aaa")
    fig.update_layout(
        paper_bgcolor="#fff8f0", plot_bgcolor="#fff8f0",
        font=dict(family="IBM Plex Mono", color="#2c2c2c", size=11),
        margin=dict(l=10,r=10,t=10,b=10),
        height=230, barmode="group",
        legend=dict(orientation="h", y=1.12, x=0),
        xaxis=dict(gridcolor="#e8e3da", type="category"),
        yaxis=dict(gridcolor="#e8e3da", zeroline=False),
    )
    return fig


# ══════════════════════════════════════════════════════════════
# MACD 表格
# ══════════════════════════════════════════════════════════════
def build_macd_table(df, n=10):
    macd, signal, hist = calc_macd(df["Close"])
    sts = classify_status(hist, macd, signal)
    d1,d2,d3 = predict_next3(hist)
    tail = df.tail(n)
    rows = []
    for i in range(len(tail)):
        h   = hist.tail(n).iloc[i]
        m   = macd.tail(n).iloc[i]
        st  = sts[-n:][i]
        last= i == len(tail)-1
        rows.append({
            "日線":  tail.index[i].strftime("%m/%d"),
            "收盤":  f"{tail['Close'].iloc[i]:.2f}",
            "MACD":  fmt(m,3),
            "Hist":  fmt(h,3),
            "狀態":  st,
            "下一交易日": st,
            "D+1":   fmt(d1,3) if last else "—",
            "D+2":   fmt(d2,3) if last else "—",
            "D+3":   fmt(d3,3) if last else "—",
            "_h":h, "_m":m, "_st":st,
        })
    return pd.DataFrame(rows), macd, signal, hist

def render_table(df_t):
    cols = ["日線","收盤","MACD","Hist","狀態","下一交易日","D+1","D+2","D+3"]
    hdr  = "".join(f"<th>{c}</th>" for c in cols)
    body = ""
    for _, r in df_t.iterrows():
        hc = "cell-pos" if r["_h"]>=0 else "cell-neg"
        mc = "cell-pos" if float(r["MACD"].replace("+",""))>=0 else "cell-neg"
        body += f"""<tr>
            <td>{r['日線']}</td><td>{r['收盤']}</td>
            <td class="{mc}">{r['MACD']}</td>
            <td class="{hc}">{r['Hist']}</td>
            <td>{badge_html(r['狀態'])}</td>
            <td>{nd_badge(r['下一交易日'])}</td>
            {pc(r['D+1'])}{pc(r['D+2'])}{pc(r['D+3'])}
        </tr>"""
    return f'<table class="macd-table"><thead><tr>{hdr}</tr></thead><tbody>{body}</tbody></table>'


# ══════════════════════════════════════════════════════════════
# Telegram
# ══════════════════════════════════════════════════════════════
# ── v2.4 排序比較 + 深度分析 Prompt 產生器 ──────────────────────
_LEVEL_RANK = {"red": 2, "yellow": 1, None: 0}

def leaning(r):
    """未達警報門檻時的潛在傾向：比較底層多/空分數（非正式訊號，僅供排序參考）"""
    bp, sp = r.get("bull_pts", 0), r.get("bear_pts", 0)
    if bp == 0 and sp == 0:
        return None
    return "bear" if sp >= bp else "bull"

def rank_key(r):
    """
    排序鍵（由粗到細）：
      1. 正式警報等級（紅>橙>無）
      2. 正式警報分數
      3. 底層潛在傾向分（即使未觸發警報，分數越高代表方向性越強）
         → 這一層修正「大時框很少翻轉 → 全部靜默 → 排序退化成輸入順序」的問題
      4. 同分時空頭優先（風險優先顯示）
    """
    lvl     = _LEVEL_RANK.get(r["level"], 0)
    pts     = r["pts"]
    sub     = max(r.get("bull_pts", 0), r.get("bear_pts", 0))
    eff_dir = r["direction"] or leaning(r)
    return (lvl, pts, sub, 1 if eff_dir == "bear" else 0)

def build_analysis_prompt(rank_data, main_tf, trigger_tf):
    """
    產生可直接貼給任意 AI（ChatGPT / Claude / Gemini 等）的深度分析 Prompt。
    本系統只做「技術面 + 量能」的程式化判定；Prompt 的用途是請另一個 AI
    補上本系統做不到的部分：基本面、新聞事件、產業比較、情緒面交叉驗證。
    """
    if not rank_data:
        return ""
    ranked = sorted(rank_data, key=rank_key, reverse=True)
    ny = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")

    L = []
    L.append(f"# 股票技術面排行分析請求（數據時間：{ny}）")
    L.append("")
    L.append("以下是我用自建的 MACD 瀑布傳導 + RVOL/VWAP 量能計分系統，")
    L.append(f"對多支股票在 {main_tf} 主時框、{trigger_tf} 觸發時框下跑出的技術面排行結果。")
    _vk = next((r.get("vwap_kind") for r in rank_data if r.get("vwap_kind")), None)
    if _vk:
        L.append(f"（VWAP 定義：{_vk}；日內為當日錨定，日/週線為 20 期滾動成交量加權均價）")
    L.append("請你在此技術面基礎上，補充做以下深度分析：")
    L.append("1. 逐一檢查近期基本面／財報／新聞事件，是否與技術面訊號吻合或衝突")
    L.append("2. 若有多支同向訊號，比較哪一支的風險報酬比最佳，並說明原因")
    L.append("3. 指出技術面看似強烈、但基本面有潛在風險的標的（反之亦然）")
    L.append("4. 給出這批股票的優先順序建議（若只能選 1–2 支操作）")
    L.append("")
    L.append("## 排行結果（依警報等級與評分排序；無正式警報時退回「潛在傾向分」排序）")
    all_silent = all(r["pts"] == 0 for r in ranked)
    if all_silent:
        L.append("")
        L.append("⚠️ 注意：這批標的目前都沒有觸發正式警報（大時框較少翻轉是正常現象），"
                  "下表的「方向/評分」是尚未達門檻的潛在傾向分，僅供參考，"
                  "請勿當作已確認的技術訊號來解讀。")
    L.append("")
    L.append("| 排名 | 代碼 | 方向 | 等級 | 評分 | 收盤 | ATR% | 趨勢 | RVOL | VWAP位置 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for i, r in enumerate(ranked, 1):
        eff_dir = r["direction"] or leaning(r)
        sub     = max(r.get("bull_pts", 0), r.get("bear_pts", 0))
        dirn  = {"bear":"🔴空頭","bull":"🟢多頭",None:"⚪中性"}.get(eff_dir,"⚪中性")
        if not r["direction"] and eff_dir:
            dirn += "(潛在)"
        lvl   = {"red":"紅色警報","yellow":"橙色觀察",None:"靜默"}.get(r["level"],"靜默")
        score_disp = r["pts"] if r["pts"] else f"潛在{sub}"
        rvol  = f"{r['rvol']:.2f}×" if r.get("rvol") is not None else "—"
        if r.get("vwap") and r.get("below_vwap") is not None:
            vwapp = (f"{'下方' if r['below_vwap'] else '上方'} "
                     f"{abs(r['close']/r['vwap']-1)*100:.2f}%（{r['vwap']:.2f}）")
        else:
            vwapp = "—"
        L.append(f"| {i} | {r['symbol']} | {dirn} | {lvl} | {score_disp} | "
                  f"{r['close']:.2f} | {r['atr_pct']:.2f}% | {r['trend']} | {rvol} | {vwapp} |")

    L.append("")
    L.append("## 各標的技術細節")
    for r in ranked:
        L.append(f"\n### {r['symbol']}")
        if r["atype"]:
            L.append(f"- 判定：{r['atype']}")
        if r.get("detail"):
            L.append(f"- 評分依據：{'；'.join(r['detail'])}")
        if r.get("gap_pct") is not None and abs(r["gap_pct"]) >= 0.003:
            L.append(f"- 開盤缺口：{r['gap_pct']*100:+.2f}%")
        casc = r.get("cascade") or []
        if casc:
            tf_line = "、".join(
                f"{c['tf']}:{c['hist']:+.3f}(D+1 {c['d1']:+.3f})"
                for c in casc if c.get("hist") is not None
            )
            L.append(f"- 各時框 Histogram：{tf_line}")

    L.append("")
    L.append("---")
    L.append("以上數據為程式化技術指標計算結果，非投資建議；"
              "請結合你查得到的最新公開資訊進行判斷。")
    return "\n".join(L)


def build_trade_plan(direction, level, pts, trig, style):
    """
    依警報方向/等級/風格產生交易建議。
    激進：訊號 bar 即進場、1.0×ATR 緊止損、允許加倉、含持倉處置
    穩健：等下一根收盤確認、1.5×ATR 止損
    ATR 一律用「觸發時框」的 ATR（日內訊號配日內止損距離）。
    """
    if not trig or not trig.get("valid"):
        return []
    px = trig.get("close")
    a  = trig.get("atr", 0)
    if not px or not a or a <= 0:
        return []
    L = [f"\n【交易建議｜{style}】"]

    if style == "激進":
        if direction == "bear":
            if level == "red":
                L += [
                    f"  空單進場  市價 {px:.2f}（訊號 bar 即進場，不等確認）",
                    f"  止損      {px + 1.0*a:.2f}（+1.0×ATR 觸發時框）",
                    f"  目標1     {px - 1.5*a:.2f}（-1.5×ATR，到手止損移保本）",
                    f"  目標2     {px - 3.0*a:.2f}（-3.0×ATR，追蹤出場）",
                    f"  倉位      首倉全額；評分 ≥7 可於反抽 VWAP 加倉一次",
                    f"  持多倉    立即減半；跌破 VWAP 全部離場",
                ]
            else:
                L += [
                    f"  試探空單  ≤1/3 倉位 @ {px:.2f}",
                    f"  止損      {px + 0.75*a:.2f}（+0.75×ATR 收緊）",
                    f"  升級      評分升至 ≥5 補至全倉；退回 <3 分立即平倉",
                ]
        else:  # bull
            if level == "red":
                L += [
                    f"  多單進場  市價 {px:.2f}（訊號 bar 即進場，不等確認）",
                    f"  止損      {px - 1.0*a:.2f}（-1.0×ATR 觸發時框）",
                    f"  目標1     {px + 1.5*a:.2f}（+1.5×ATR，到手止損移保本）",
                    f"  目標2     {px + 3.0*a:.2f}（+3.0×ATR，追蹤出場）",
                    f"  倉位      首倉全額；評分 ≥7 可於回踩 VWAP 加倉一次",
                    f"  持空倉    立即減半；站回 VWAP 全部回補",
                ]
            else:
                L += [
                    f"  試探多單  ≤1/3 倉位 @ {px:.2f}",
                    f"  止損      {px - 0.75*a:.2f}（-0.75×ATR 收緊）",
                    f"  升級      評分升至 ≥5 補至全倉；退回 <3 分立即平倉",
                ]
    else:  # 穩健
        if level == "red":
            if direction == "bear":
                L += [
                    f"  空單進場  下一根 K 線收盤確認後 @ 市價",
                    f"  止損      {px + 1.5*a:.2f}（+1.5×ATR 觸發時框）",
                    f"  目標      {px - 2.0*a:.2f} / {px - 3.5*a:.2f}",
                    f"  持多倉    減倉並收緊止損至 {px + 1.0*a:.2f}",
                ]
            else:
                L += [
                    f"  多單進場  下一根 K 線收盤確認後 @ 市價",
                    f"  止損      {px - 1.5*a:.2f}（-1.5×ATR 觸發時框）",
                    f"  目標      {px + 2.0*a:.2f} / {px + 3.5*a:.2f}",
                ]
        else:
            L += ["  僅觀察，暫不建倉；等評分升級或翻轉確認"]

    L.append("  ⚠️ 程式化參考，非投資建議")
    return L


def build_tg_msg(symbol, cascade, resonance, confirm_tfs, trigger_tf, close_price, atr_1d, plan_style="穩健"):
    atype     = resonance.get("atype","")
    trig      = resonance.get("trigger") or {}
    direction = resonance.get("direction")
    level     = resonance.get("level")
    pts       = resonance.get("pts", 0)

    if resonance["alert"] and direction == "bear" and level == "red":
        header = f"🔴 {symbol} 風險警報（空頭 {pts} 分）"
    elif resonance["alert"] and direction == "bull" and level == "red":
        header = f"⚡ {symbol} 進場預警（多頭 {pts} 分）"
    elif resonance["alert"] and direction == "bear":
        header = f"🟠 {symbol} 觀察訊號（空頭 {pts} 分）"
    elif resonance["alert"]:
        header = f"👀 {symbol} 觀察訊號（多頭 {pts} 分）"
    elif resonance["score"] >= resonance["max"] * 0.7:
        header = f"📈 {symbol} 多頭共振"
    else:
        header = f"📊 {symbol} 市場分析"

    lines = [header, "━"*32, "【大時框方向確認】"]
    for r in cascade:
        if not r.get("valid") or r["tf"] not in confirm_tfs:
            continue
        aligned = (r["hist"] < 0) if direction == "bear" else (r["hist"] > 0)
        icon = "✅" if aligned else "❌"
        lines.append(f"  {r['tf']:>3s}  {icon}  Hist {fmt(r['hist'],3)}  D+1 {fmt(r['d1'],3)}")

    if trig and trig.get("valid"):
        h, d1 = trig["hist"], trig["d1"]
        hc    = trig.get("hist_c", h)
        if   hc < 0 and d1 > 0: warn = " ← 預計翻正 🚨"
        elif hc > 0 and d1 < 0: warn = " ← 預計翻負 ⚠️"
        else:                   warn = ""
        lines += [
            f"\n【觸發時框 {trigger_tf}】",
            f"  已收盤 Hist {fmt(hc,3)}  ← 訊號判定用",
            f"  形成中 Hist {fmt(h,3)}（未收盤，僅預覽）",
            f"  D+1        {fmt(d1,3)}{warn}",
            f"  D+2        {fmt(trig['d2'],3)}",
            f"  D+3        {fmt(trig['d3'],3)}",
        ]

        # ── v2.2 量能確認 ──────────────────────────────────
        vparts = []
        rv = trig.get("rvol")
        if rv is not None:
            tag = "機構級 🔥" if rv >= 2.5 else ("放量" if rv >= 1.5 else ("縮量" if rv < 0.8 else "正常"))
            vparts.append(f"RVOL  {rv:.2f}×（{tag}）")
        vw = trig.get("vwap")
        if vw:
            pos  = "下方" if trig.get("below_vwap") else "上方"
            dist = abs(trig["close"]/vw - 1) * 100
            kind = trig.get("vwap_kind", "VWAP")
            vparts.append(f"{kind}  {vw:.2f}（價格在{pos} {dist:.2f}%）")
        gp = trig.get("gap_pct")
        if gp is not None and abs(gp) >= 0.003:
            vparts.append(f"缺口  {gp*100:+.2f}%")
        if vparts:
            lines += ["\n【量能確認】"] + [f"  {p}" for p in vparts]

    # ── v2.2 警報評分明細 ─────────────────────────────────
    if resonance.get("detail"):
        badge = "🔴 警報" if level == "red" else "🟠 觀察"
        lines += [f"\n【警報評分 {pts} 分｜{badge}】"]
        lines += [f"  • {d}" for d in resonance["detail"]]

    # ── v2.3 交易建議 ─────────────────────────────────────
    if resonance["alert"]:
        lines += build_trade_plan(direction, level, pts, trig, plan_style)

    lines += [f"\n【共振強度】 {resonance['score']}/{resonance['max']}"]
    if atype:
        lines.append(f"【信號類型】 {atype}")

    if atr_1d > 0:
        if direction == "bear":
            stop = close_price + 1.5 * atr_1d
            tg1  = close_price - 2.0 * atr_1d
            tg2  = close_price - 3.5 * atr_1d
            lines += [
                f"\n【參考位置｜空頭】 收盤 {close_price:.2f}",
                f"  止損  {stop:.2f}  (+1.5×ATR)",
                f"  目標1 {tg1:.2f}  (-2.0×ATR)",
                f"  目標2 {tg2:.2f}  (-3.5×ATR)",
                f"  ATR   {atr_1d:.3f}",
            ]
        else:
            stop = close_price - 1.5 * atr_1d
            tg1  = close_price + 2.0 * atr_1d
            tg2  = close_price + 3.5 * atr_1d
            lines += [
                f"\n【參考位置】 收盤 {close_price:.2f}",
                f"  止損  {stop:.2f}  (-1.5×ATR)",
                f"  目標1 {tg1:.2f}  (+2.0×ATR)",
                f"  目標2 {tg2:.2f}  (+3.5×ATR)",
                f"  ATR   {atr_1d:.3f}",
            ]

    # ── v2.2：真正的美東時間 + 休市標註 ────────────────────
    ny = datetime.now(ZoneInfo("America/New_York"))
    stale = (trig.get("last_bar_day") and ny.strftime("%Y-%m-%d") != trig["last_bar_day"])
    if ny.weekday() >= 5 or stale:
        lines.insert(2, "⏸ 非交易時段／休市，以下為最近收盤數據")
    lines.append(f"\n📅 {ny.strftime('%Y-%m-%d %H:%M')} ET")
    return "\n".join(lines)

def send_telegram(token, chat_id, text):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id":chat_id,"text":text,"parse_mode":"Markdown"},
            timeout=10,
        )
        return r.status_code==200, r.text
    except Exception as e:
        return False, str(e)



# ══════════════════════════════════════════════════════════════
# 回測引擎  ── 忠實還原三步入場邏輯
# ══════════════════════════════════════════════════════════════
#
#  入場三步驟：
#  Step 1  1d + 1h Histogram > 0          ← 大方向多頭確認
#  Step 2  傳導鏈預警：
#           1m D+1 > 0 → 5m D+1 > 0 → 15m D+1 > 0 → 30m D+1 > 0
#           （小時框 D+1 依序預測翻正 → 預警發出）
#  Step 3  30m Histogram 實際翻正          ← 執行入場
#
#  回測資料：最近 60 天日內 1m/5m/15m/30m/1h + 日線 1d
#  出場：持倉 N 根 30m K 線 或 ATR 止損/止盈
# ══════════════════════════════════════════════════════════════

BACKTEST_PERIODS = {
    "1年":  "1y",
    "2年":  "2y",
    "5年":  "5y",
    "10年": "10y",
}

# 回測固定用 60 天日內數據
BT_INTRADAY_CONFIGS = {
    "1m":  {"period": "7d",  "interval": "1m"},
    "5m":  {"period": "60d", "interval": "5m"},
    "15m": {"period": "60d", "interval": "15m"},
    "30m": {"period": "60d", "interval": "30m"},
    "1h":  {"period": "60d", "interval": "1h"},
    "1d":  {"period": "180d","interval": "1d"},
}


def fetch_bt_tf(symbol: str, period: str, interval: str) -> pd.DataFrame:
    """回測數據：session_state 快取，TTL = 300 秒（回測不需要即時數據）"""
    import time as _t
    cache_key = f"bt_{symbol}_{period}_{interval}"
    ts_key    = f"bt_ts_{symbol}_{period}_{interval}"
    now       = _t.time()
    if now - st.session_state.get(ts_key, 0) >= 300 or cache_key not in st.session_state:
        try:
            df = yf.Ticker(symbol).history(period=period, interval=interval)
            if df.empty:
                df = pd.DataFrame()
            else:
                df = df[["Open","High","Low","Close","Volume"]].dropna()
                if df.index.tz is not None:
                    df.index = df.index.tz_convert("America/New_York").tz_localize(None)
        except:
            df = pd.DataFrame()
        st.session_state[cache_key] = df
        st.session_state[ts_key]    = now
    return st.session_state[cache_key]


def get_d1_series(df: pd.DataFrame) -> pd.Series:
    """
    為 df 每一根 K 線計算當時的 D+1 預測值。
    使用 rolling 方式，每個時間點只用歷史數據（無未來偷看）。
    """
    _, _, hist = calc_macd(df["Close"])
    d1_vals = pd.Series(index=df.index, dtype=float)
    for i in range(3, len(hist)):
        v     = hist.iloc[i-2:i+1].values          # 最近3根
        slope = (v[-1] - v[0]) / 2
        d1_vals.iloc[i] = v[-1] + slope
    return d1_vals, hist


def _latest_before(series: pd.Series, t) -> float:
    """取時間點 t 之前（含）最新的有效值，用於跨時框對齊"""
    sub = series[series.index <= t].dropna()
    return float(sub.iloc[-1]) if len(sub) > 0 else np.nan


def align_to_30m(df_30m: pd.DataFrame,
                 df_5m:  pd.DataFrame,
                 df_15m: pd.DataFrame,
                 df_1h:  pd.DataFrame,
                 df_1d:  pd.DataFrame) -> pd.DataFrame:
    """
    以 30m K 線為基準時間軸，對齊各時框最新狀態。
    每根 30m K 線結束時，查詢當時各時框的最新值（無未來偷看）。
    """
    # 計算各時框的 D+1 預測序列 和 Histogram 序列
    # get_d1_series 回傳 (d1_series, hist_series)
    d1_5m,  hist_5m  = get_d1_series(df_5m)
    d1_15m, hist_15m = get_d1_series(df_15m)
    d1_30m, hist_30m = get_d1_series(df_30m)
    d1_1h,  hist_1h  = get_d1_series(df_1h)
    # 1d 只需要 Histogram（不需要 D+1 預測），calc_macd 回傳3個值
    _, _, hist_1d = calc_macd(df_1d["Close"])

    rows = []
    for i in range(10, len(df_30m)):
        t30 = df_30m.index[i]   # 當前 30m K 線結束時間

        # 30m 本身（直接用 index，不需要 latest_before）
        h30   = float(hist_30m.iloc[i])
        d1_30 = float(d1_30m.iloc[i]) if not pd.isna(d1_30m.iloc[i]) else np.nan

        # 5m / 15m / 1h：t30 之前最新值
        h5    = _latest_before(hist_5m,  t30)
        d5    = _latest_before(d1_5m,    t30)
        h15   = _latest_before(hist_15m, t30)
        d15   = _latest_before(d1_15m,   t30)
        h1h   = _latest_before(hist_1h,  t30)
        d1h   = _latest_before(d1_1h,    t30)

        # 1d：取 t30 日期當天或之前最新日線
        t30_date = pd.Timestamp(t30).date()
        sub_1d   = hist_1d[pd.to_datetime(hist_1d.index).date <= t30_date]
        h1d      = float(sub_1d.iloc[-1]) if len(sub_1d) > 0 else np.nan

        rows.append({
            "time":  t30,
            "close": df_30m["Close"].iloc[i],
            # 30m
            "h30":   h30,
            "d1_30": d1_30,
            # 5m
            "h5":    h5,
            "d1_5":  d5,
            # 15m
            "h15":   h15,
            "d1_15": d15,
            # 1h 確認
            "h1h":   h1h,
            "d1_1h": d1h,
            # 1d 確認
            "h1d":   h1d,
        })

    return pd.DataFrame(rows).set_index("time")


def run_cascade_backtest(symbol: str, atr_sl: float = 1.5,
                          atr_tp: float = 3.0, hold_bars: int = 6,
                          exit_mode: str = "固定根數") -> dict:
    """
    三步瀑布傳導回測（最近 60 天 30m K 線）

    正確的三步時序邏輯：
    ┌─ 每根 K 線持續檢查 ──────────────────────────────────┐
    │ Step 1  h1d > 0 AND h1h > 0   → 大方向多頭確認      │
    │ Step 2  預警根：h30 < 0                              │
    │         AND d1_5>0, d1_15>0, d1_30>0               │
    │         （傳導鏈 D+1 全部預測翻正，但30m尚未翻）     │
    │ Step 3  入場根（預警根的下一根）：                   │
    │         h30_prev < 0 AND h30_now >= 0               │
    │         （30m 實際翻正 → 當根收盤入場）              │
    └──────────────────────────────────────────────────────┘
    出場模式（exit_mode）：
      "固定根數"    → 持倉 hold_bars 根 30m K 線後平倉
      "30m轉負"     → 30m Histogram 再次轉負時出場
      "1d/1h轉負"   → 1d 或 1h Histogram 轉負時出場（跟隨大趨勢）
    所有模式均疊加 ATR 止損 / ATR 止盈保護
    """
    # ── 載入所有時框 ─────────────────────────────────────
    dfs = {}
    for tf, cfg in BT_INTRADAY_CONFIGS.items():
        df = fetch_bt_tf(symbol, cfg["period"], cfg["interval"])
        if df.empty:
            return {"error": f"{tf} 數據載入失敗"}
        dfs[tf] = df

    # ── 時框對齊 ─────────────────────────────────────────
    try:
        aligned = align_to_30m(
            dfs["30m"], dfs["5m"], dfs["15m"], dfs["1h"], dfs["1d"]
        )
    except Exception as e:
        return {"error": f"時框對齊失敗: {e}"}

    if len(aligned) < 20:
        return {"error": "有效數據不足20根30m K線"}

    atr_30m = calc_atr(dfs["30m"])

    # ── 診斷計數器（找出哪一步卡住）─────────────────────
    diag = {
        "total_bars":    len(aligned),
        "step1_pass":    0,   # 1d+1h 都多頭的 bar 數
        "step2_alert":   0,   # Step2 預警觸發次數
        "step3_entry":   0,   # Step3 實際入場次數
        "skip_nan":      0,
    }

    # ── 主回測循環 ────────────────────────────────────────
    trades        = []
    in_trade      = False
    entry_price   = entry_bar = None
    prev_alerted  = False   # 上一根是否已發出 Step2 預警

    close_arr = aligned["close"].values
    h30_arr   = aligned["h30"].values
    d1_30_arr = aligned["d1_30"].values
    d1_5_arr  = aligned["d1_5"].values
    d1_15_arr = aligned["d1_15"].values
    h1h_arr   = aligned["h1h"].values
    h1d_arr   = aligned["h1d"].values
    times     = aligned.index

    for i in range(5, len(aligned)):
        # NaN 跳過
        if np.isnan(h30_arr[i]) or np.isnan(close_arr[i]):
            diag["skip_nan"] += 1
            prev_alerted = False
            continue

        if not in_trade:
            # ── Step 1：大方向確認 ─────────────────────────
            s1_1d = (not np.isnan(h1d_arr[i]) and h1d_arr[i] > 0)
            s1_1h = (not np.isnan(h1h_arr[i]) and h1h_arr[i] > 0)
            step1 = s1_1d and s1_1h
            if step1:
                diag["step1_pass"] += 1

            if not step1:
                prev_alerted = False
                continue

            # ── Step 3 優先：上一根已預警，本根是否翻正？──
            if prev_alerted:
                h30_prev = h30_arr[i-1]
                step3 = (h30_prev < 0 and h30_arr[i] >= 0)
                if step3:
                    in_trade    = True
                    entry_bar   = i
                    entry_price = close_arr[i]
                    diag["step3_entry"] += 1
                    prev_alerted = False
                    continue
                # 若上一根預警後本根仍負，繼續等（不重置 prev_alerted，
                # 但要重新判斷 Step2 是否仍然成立）

            # ── Step 2：傳導鏈 D+1 預測翻正（預警根）─────
            s2_5m  = (not np.isnan(d1_5_arr[i])  and d1_5_arr[i]  > 0)
            s2_15m = (not np.isnan(d1_15_arr[i]) and d1_15_arr[i] > 0)
            s2_30m = (not np.isnan(d1_30_arr[i]) and d1_30_arr[i] > 0)
            s2_neg = (h30_arr[i] < 0)   # 30m 當前仍為負（尚未翻正）

            step2 = s2_5m and s2_15m and s2_30m and s2_neg
            if step2:
                prev_alerted = True
                diag["step2_alert"] += 1
            else:
                # Step2 不滿足，重置預警狀態
                prev_alerted = False

        else:
            # ── 出場檢測 ──────────────────────────────────
            prev_alerted = False
            bars_held = i - entry_bar
            cur  = close_arr[i]
            sl   = entry_price - atr_sl * atr_30m
            tp   = entry_price + atr_tp * atr_30m

            reason = exit_price = None

            # ATR 止損（所有模式共用）
            if cur <= sl:
                reason, exit_price = "止損", max(sl, cur)
            # ATR 止盈（所有模式共用）
            elif cur >= tp:
                reason, exit_price = "止盈", min(tp, cur)
            # ── 出場模式 ──────────────────────────────────
            elif exit_mode == "固定根數":
                if bars_held >= hold_bars:
                    reason, exit_price = "固定根數平倉", cur

            elif exit_mode == "30m轉負":
                # 30m Histogram 從正轉負時出場
                h30_cur  = h30_arr[i]
                h30_prev_e = h30_arr[i-1] if i > 0 else h30_cur
                if h30_prev_e >= 0 and h30_cur < 0:
                    reason, exit_price = "30m轉負出場", cur
                # 保底：超過 hold_bars*3 根未出場則強制平倉
                elif bars_held >= hold_bars * 3:
                    reason, exit_price = "保底平倉", cur

            elif exit_mode == "1d/1h轉負":
                # 1d 或 1h Histogram 轉負時出場
                h1h_cur = h1h_arr[i]
                h1h_prv = h1h_arr[i-1] if i > 0 else h1h_cur
                h1d_cur = h1d_arr[i]
                h1d_prv = h1d_arr[i-1] if i > 0 else h1d_cur
                h1h_neg = (not np.isnan(h1h_cur) and not np.isnan(h1h_prv)
                           and h1h_prv >= 0 and h1h_cur < 0)
                h1d_neg = (not np.isnan(h1d_cur) and not np.isnan(h1d_prv)
                           and h1d_prv >= 0 and h1d_cur < 0)
                if h1h_neg:
                    reason, exit_price = "1h轉負出場", cur
                elif h1d_neg:
                    reason, exit_price = "1d轉負出場", cur
                # 保底：超過 hold_bars*5 根未出場則強制平倉
                elif bars_held >= hold_bars * 5:
                    reason, exit_price = "保底平倉", cur

            if reason:
                pnl = (exit_price - entry_price) / entry_price * 100
                trades.append({
                    "entry_time":  times[entry_bar],
                    "exit_time":   times[i],
                    "entry_price": entry_price,
                    "exit_price":  exit_price,
                    "bars_held":   bars_held,
                    "pnl_pct":     pnl,
                    "win":         pnl > 0,
                    "exit_reason": reason,
                    "date":        pd.Timestamp(times[entry_bar]).date(),
                })
                in_trade    = False
                entry_price = entry_bar = None

    if not trades:
        return {
            "trades": [], "total": 0, "wins": 0, "losses": 0,
            "win_rate": 0, "avg_win": 0, "avg_loss": 0,
            "profit_factor": 0, "max_consec_loss": 0,
            "total_return": 0, "aligned": aligned, "diag": diag,
        }

    df_t   = pd.DataFrame(trades)
    wins   = df_t[df_t["win"]]
    losses = df_t[~df_t["win"]]

    # 最大連虧
    mc = cur_mc = 0
    for w in df_t["win"]:
        cur_mc = 0 if w else cur_mc + 1
        mc     = max(mc, cur_mc)

    aw = wins["pnl_pct"].mean()   if len(wins)   > 0 else 0
    al = losses["pnl_pct"].mean() if len(losses) > 0 else 0
    pf = abs(aw * len(wins)) / abs(al * len(losses)) if len(losses) > 0 and al != 0 else 99

    return {
        "trades":          trades,
        "df_trades":       df_t,
        "total":           len(df_t),
        "wins":            len(wins),
        "losses":          len(losses),
        "win_rate":        len(wins) / len(df_t) * 100,
        "avg_win":         aw,
        "avg_loss":        al,
        "profit_factor":   min(pf, 99),
        "max_consec_loss": mc,
        "total_return":    df_t["pnl_pct"].sum(),
        "aligned":         aligned,
        "diag":            diag,
    }


# ── 回測圖表 ──────────────────────────────────────────────────

def build_bt_entry_chart(aligned: pd.DataFrame, trades: list) -> go.Figure:
    """
    在 30m Histogram 圖上標注入場/出場點
    """
    _, _, hist_vals = calc_macd(pd.Series(aligned["close"].values,
                                           index=aligned.index))
    xl     = [str(t) for t in aligned.index]
    colors = ["#3d8b5e" if v >= 0 else "#c0392b" for v in aligned["h30"]]

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.5, 0.5], vertical_spacing=0.06,
                        subplot_titles=["30m 收盤價  ▲入場  ▼出場", "30m Histogram + D+1 預測"])

    # 收盤線
    fig.add_trace(go.Scatter(
        x=xl, y=aligned["close"].values, mode="lines",
        name="收盤", line=dict(color="#5a7fa8", width=1.5),
    ), row=1, col=1)

    # 入場/出場標記
    if trades:
        entry_x = [str(t["entry_time"]) for t in trades]
        entry_y = [t["entry_price"]     for t in trades]
        exit_x  = [str(t["exit_time"])  for t in trades]
        exit_y  = [t["exit_price"]      for t in trades]
        win_clr = ["#3d8b5e" if t["win"] else "#c0392b" for t in trades]

        fig.add_trace(go.Scatter(
            x=entry_x, y=entry_y, mode="markers",
            name="入場", marker=dict(symbol="triangle-up", size=12,
                                     color=win_clr, line=dict(width=1, color="#fff")),
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=exit_x, y=exit_y, mode="markers",
            name="出場", marker=dict(symbol="triangle-down", size=12,
                                     color=win_clr, line=dict(width=1, color="#fff")),
        ), row=1, col=1)

    # Histogram 柱
    fig.add_trace(go.Bar(
        x=xl, y=aligned["h30"].values, name="30m Hist",
        marker_color=colors, opacity=0.8,
    ), row=2, col=1)

    # D+1 預測線
    fig.add_trace(go.Scatter(
        x=xl, y=aligned["d1_30"].values, mode="lines",
        name="D+1 預測", line=dict(color="#e07b39", width=1.5, dash="dot"),
    ), row=2, col=1)
    fig.add_hline(y=0, line_dash="dot", line_color="#bbb", row=2, col=1)

    # x 軸抽稀
    step = max(1, len(xl)//14)
    tv   = xl[::step]

    fig.update_layout(
        paper_bgcolor="#fff8f0", plot_bgcolor="#fff8f0",
        font=dict(family="IBM Plex Mono", color="#2c2c2c", size=10),
        margin=dict(l=10, r=10, t=36, b=10),
        height=500,
        legend=dict(orientation="h", y=1.02, x=0),
        xaxis=dict(type="category", tickvals=tv, tickangle=-35, gridcolor="#e8e3da"),
        xaxis2=dict(type="category", tickvals=tv, tickangle=-35, gridcolor="#e8e3da"),
    )
    fig.update_yaxes(gridcolor="#e8e3da", zeroline=True, zerolinecolor="#c0bbb2")
    return fig


def build_equity_curve(trades: list) -> go.Figure:
    if not trades:
        return go.Figure()
    df_t    = pd.DataFrame(trades)
    cum     = df_t["pnl_pct"].cumsum().values
    colors  = ["#3d8b5e" if p > 0 else "#c0392b" for p in df_t["pnl_pct"]]
    xlabels = [str(t["entry_time"])[:16] for t in trades]

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.6, 0.4], vertical_spacing=0.06,
                        subplot_titles=["累計收益（%）", "每筆盈虧（%）"])
    fig.add_trace(go.Scatter(
        x=xlabels, y=cum, mode="lines+markers",
        name="累計收益", line=dict(color="#5a7fa8", width=2),
        fill="tozeroy", fillcolor="rgba(90,127,168,0.08)",
        marker=dict(size=5, color=colors),
    ), row=1, col=1)
    fig.add_hline(y=0, line_dash="dot", line_color="#aaa", row=1, col=1)
    fig.add_trace(go.Bar(
        x=xlabels, y=df_t["pnl_pct"].values,
        name="單筆", marker_color=colors, opacity=0.85,
    ), row=2, col=1)
    fig.add_hline(y=0, line_dash="dot", line_color="#aaa", row=2, col=1)
    step = max(1, len(xlabels)//10)
    tv   = xlabels[::step]
    fig.update_layout(
        paper_bgcolor="#fff8f0", plot_bgcolor="#fff8f0",
        font=dict(family="IBM Plex Mono", color="#2c2c2c", size=10),
        margin=dict(l=10, r=10, t=36, b=10), height=380, showlegend=False,
        xaxis=dict(type="category", tickvals=tv, tickangle=-35, gridcolor="#e8e3da"),
        xaxis2=dict(type="category", tickvals=tv, tickangle=-35, gridcolor="#e8e3da"),
    )
    fig.update_yaxes(gridcolor="#e8e3da", zeroline=True, zerolinecolor="#c0bbb2")
    return fig


def render_bt_kpi(result: dict, symbol: str, hold_bars: int,
                   atr_sl: float, atr_tp: float) -> str:
    wr  = result["win_rate"]
    pf  = result["profit_factor"]
    tr  = result["total_return"]
    wc  = "#3d8b5e" if wr >= 55 else ("#e07b39" if wr >= 45 else "#c0392b")
    pc_ = "#3d8b5e" if pf >= 1.5 else ("#e07b39" if pf >= 1.0 else "#c0392b")
    tc  = "#3d8b5e" if tr >= 0   else "#c0392b"
    return f"""
    <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin:14px 0;">
        <div class="metric-card">
            <div class="label">總信號</div>
            <div class="value" style="font-size:30px;">{result['total']}</div>
            <div class="sub">最近60天 30m</div>
        </div>
        <div class="metric-card">
            <div class="label">整體勝率</div>
            <div class="value" style="color:{wc};font-size:30px;">{wr:.1f}%</div>
            <div class="sub">{result['wins']}勝 {result['losses']}負</div>
        </div>
        <div class="metric-card">
            <div class="label">盈虧比 PF</div>
            <div class="value" style="color:{pc_};font-size:30px;">{pf:.2f}</div>
            <div class="sub">勝 {result['avg_win']:.2f}% / 負 {result['avg_loss']:.2f}%</div>
        </div>
        <div class="metric-card">
            <div class="label">最大連虧</div>
            <div class="value" style="color:#c0392b;font-size:30px;">{result['max_consec_loss']}</div>
            <div class="sub">連續次數</div>
        </div>
        <div class="metric-card">
            <div class="label">累計收益</div>
            <div class="value" style="color:{tc};font-size:30px;">{tr:+.1f}%</div>
            <div class="sub">持{hold_bars}根·SL {atr_sl}×·TP {atr_tp}×ATR</div>
        </div>
    </div>"""


def render_trades_table(trades: list, max_rows: int = 25) -> str:
    cols = ["入場時間","出場時間","入場價","出場價","持倉根","盈虧%","結果","原因"]
    hdr  = "".join(f"<th>{c}</th>" for c in cols)
    body = ""
    reason_cls = {"止損":"badge-bear","止盈":"badge-bull","到期平倉":"badge-neu"}
    for t in trades[-max_rows:]:
        pnl = t["pnl_pct"]
        pc_ = "cell-pos" if pnl >= 0 else "cell-neg"
        rslt= '<span class="badge badge-bull">▲ 盈</span>' if t["win"]               else '<span class="badge badge-bear">▼ 虧</span>'
        rc  = reason_cls.get(t["exit_reason"], "badge-neu")
        rb  = f'<span class="badge {rc}">{t["exit_reason"]}</span>'
        et  = str(t["entry_time"])[:16]
        xt  = str(t["exit_time"])[:16]
        body += f"""<tr>
            <td>{et}</td><td>{xt}</td>
            <td>{t['entry_price']:.2f}</td><td>{t['exit_price']:.2f}</td>
            <td>{t['bars_held']}</td>
            <td class="{pc_}">{pnl:+.2f}%</td>
            <td>{rslt}</td><td>{rb}</td>
        </tr>"""
    return f'<table class="macd-table"><thead><tr>{hdr}</tr></thead><tbody>{body}</tbody></table>'


# ══════════════════════════════════════════════════════════════
# Sidebar
# ══════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("## 🌊 系統設定")
    st.markdown("---")

    raw     = st.text_area("股票代碼（逗號分隔）", value=",".join(DEFAULT_SYMBOLS), height=75)
    symbols = [s.strip().upper() for s in raw.split(",") if s.strip()]

    st.markdown("**主時框（K線分析）**")
    main_tf = st.selectbox("時間框架", list(TIMEFRAME_MAP.keys()), index=5)

    st.markdown("**🌊 瀑布傳導鏈**")
    chain_tfs = st.multiselect(
        "選擇時框（系統自動由小到大排序）",
        CASCADE_CHAIN,
        default=["30m","1h","1d","1w"],
    )
    chain_tfs = [tf for tf in CASCADE_CHAIN if tf in chain_tfs]

    if len(chain_tfs) >= 2:
        trigger_tf  = st.selectbox("⚡ 入場觸發時框（最小）", chain_tfs, index=0)
        confirm_tfs = [tf for tf in chain_tfs if tf != trigger_tf]
    else:
        trigger_tf  = chain_tfs[0] if chain_tfs else "30m"
        confirm_tfs = []

    st.markdown("**🎯 交易建議風格**")
    plan_style = st.radio(
        "風格", ["穩健", "激進"], horizontal=True, index=0,
        label_visibility="collapsed",
        help="穩健：等下一根收盤確認、1.5×ATR 止損｜"
             "激進：訊號 bar 即進場、1.0×ATR 緊止損、允許加倉、含持倉處置",
    )

    st.markdown("---")
    st.markdown("**⏱ 自動刷新**")
    auto_refresh     = st.checkbox("啟用", value=False)
    refresh_interval = st.selectbox("間隔（秒）", [60,120,180,300], index=0)
    # 存入 session_state 供 fetch_data 動態快取使用
    st.session_state["refresh_interval"] = refresh_interval

    st.markdown("---")
    st.markdown("**📡 Telegram**")
    tg_token = st.text_input("Bot Token", type="password", placeholder="xxxxx:ABC...")
    tg_chat  = st.text_input("Chat ID",  placeholder="-100xxxxxxxxx")
    tg_auto  = st.checkbox("🔔 警報自動推送", value=False,
                            help="偵測到預警/警報時自動推送 Telegram（同一訊號每小時最多一次），"
                                 "需配合「自動刷新」使用")
    tg_send  = st.button("📤 發送所有信號")

    st.markdown("---")
    if st.button("🔄 立即清除快取", help="強制清除所有數據快取，下次載入重新拉取"):
        # 清除所有數據快取（含刷新計時器，確保立即重新拉取）
        keys_to_del = [k for k in st.session_state.keys()
                       if k.startswith(("df_","ts_","bt_","bt_ts_","_last_page"))]
        for k in keys_to_del:
            del st.session_state[k]
        st.success(f"✅ 已清除 {len(keys_to_del)} 個快取，正在重新載入...")
        st.rerun()
    st.caption(f"更新：{datetime.now().strftime('%H:%M:%S')}")

if auto_refresh:
    from streamlit_autorefresh import st_autorefresh
    # st_autorefresh 用 React component 定時觸發 st.rerun()
    # 每次 rerun 前自動清除數據快取，確保數據一定更新
    _count = st_autorefresh(
        interval=refresh_interval * 1000,  # 毫秒
        limit=None,                         # 無限次
        key="autorefresh_timer",
    )
    if _count > 0:
        # 每次 autorefresh 觸發時清除數據快取
        _keys_expired = [k for k in st.session_state.keys()
                         if k.startswith(("df_","ts_"))]
        for _k in _keys_expired:
            del st.session_state[_k]
    st.info(f"⏱ 每 {refresh_interval} 秒自動更新 · 已刷新 {_count} 次")


# ══════════════════════════════════════════════════════════════
# 主頁面
# ══════════════════════════════════════════════════════════════
st.markdown("# 🌊 MACD 瀑布動能傳導系統")
import time as _time_main
_ttl_now = st.session_state.get("refresh_interval", 60)
_slot_ts = (int(_time_main.time()) // _ttl_now) * _ttl_now
_data_ts = datetime.fromtimestamp(_slot_ts).strftime("%H:%M:%S")
chain_str   = "  →  ".join(chain_tfs) if chain_tfs else "未設定"
confirm_str = ", ".join(confirm_tfs)  if confirm_tfs else "—"
st.markdown(f"""
<div style="font-size:12px;color:#888;font-family:'IBM Plex Mono',monospace;margin-bottom:4px;">
傳導鏈：{chain_str} &nbsp;|&nbsp; 觸發：<b style="color:#f0a500">{trigger_tf}</b>
&nbsp;|&nbsp; 確認：{confirm_str}
&nbsp;|&nbsp; 📡 數據批次：<b style="color:#3d8b5e">{_data_ts}</b>
&nbsp;{"&nbsp;|&nbsp; ⏱ 每 " + str(_ttl_now) + " 秒更新" if auto_refresh else ""}
</div>
""", unsafe_allow_html=True)
st.markdown("---")

tf_cfg      = TIMEFRAME_MAP[main_tf]
tg_msgs_all = []
rank_data   = []

for symbol in symbols:
    st.markdown(f"## 🔷 {symbol}")

    with st.spinner(f"載入 {symbol}..."):
        df_main = fetch_data(symbol, tf_cfg["period"], tf_cfg["interval"])

    if df_main.empty or len(df_main) < 30:
        st.warning(f"⚠️ {symbol} 數據不足，跳過")
        st.markdown("---")
        continue

    df_t, macd_s, sig_s, hist_s = build_macd_table(df_main, n=10)
    last      = df_t.iloc[-1]
    macd_val  = float(last["MACD"].replace("+",""))
    hist_val  = last["_h"]
    status_v  = last["_st"]
    close_val = float(last["收盤"])
    trend     = get_trend(macd_val, hist_val, status_v)
    d1,d2,d3  = predict_next3(hist_s)
    atr_main  = calc_atr(df_main)

    # ── 頂部四格指標 ────────────────────────────────────────
    c1,c2,c3,c4 = st.columns(4)
    prev  = df_main["Close"].iloc[-2]
    chg   = close_val - prev
    pct   = chg / prev * 100
    with c1:
        dc,ds = ("pos","▲") if chg>=0 else ("neg","▼")
        st.markdown(f"""<div class="metric-card">
            <div class="label">收盤 ({main_tf})</div>
            <div class="value">{close_val:.2f}</div>
            <div class="sub {dc}">{ds} {chg:+.2f} ({pct:+.2f}%)</div>
        </div>""", unsafe_allow_html=True)
    with c2:
        hc = "pos" if hist_val>=0 else "neg"
        st.markdown(f"""<div class="metric-card">
            <div class="label">Histogram</div>
            <div class="value {hc}">{hist_val:+.3f}</div>
            <div class="sub">{status_v}</div>
        </div>""", unsafe_allow_html=True)
    with c3:
        d1c = "pos" if d1>=0 else "neg"
        st.markdown(f"""<div class="metric-card">
            <div class="label">三日推演</div>
            <div class="value {d1c}">{d1:+.3f}</div>
            <div class="sub">D+2 {d2:+.3f} &nbsp;|&nbsp; D+3 {d3:+.3f}</div>
        </div>""", unsafe_allow_html=True)
    with c4:
        st.markdown(f"""<div class="metric-card">
            <div class="label">趨勢 / ATR</div>
            <div style="margin:8px 0 4px">{trend_pill(trend)}</div>
            <div class="sub">ATR {atr_main:.3f}</div>
        </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── 瀑布傳導核心面板 ────────────────────────────────────
    if chain_tfs:
        with st.spinner("計算傳導鏈..."):
            cascade   = analyze_cascade(symbol, chain_tfs)
            resonance = calc_resonance(cascade, confirm_tfs, trigger_tf)

        # 標題 + 共振評分
        col_t, col_s = st.columns([3,2])
        with col_t:
            st.markdown("#### 🌊 瀑布動能傳導鏈")
        with col_s:
            st.markdown(
                f"<div style='text-align:right;margin-top:10px'>{stars_html(resonance['score'],resonance['max'])}</div>",
                unsafe_allow_html=True)

        # ── 預警橫幅（v2.2 計分制：紅色警報卡 / 橙色觀察條）──
        if resonance["alert"]:
            trig_d  = resonance.get("trigger") or {}
            atype   = resonance.get("atype","")
            lvl     = resonance.get("level")
            pts_v   = resonance.get("pts",0)
            det_ls  = resonance.get("detail",[])
            det_html = "".join(f"&nbsp;&nbsp;• {d}<br>" for d in det_ls)
            plan_ls  = build_trade_plan(resonance.get("direction"), lvl, pts_v,
                                        trig_d, plan_style)
            plan_html = "".join(
                f"&nbsp;&nbsp;{p.strip()}<br>" for p in plan_ls
                if not p.startswith("\n【"))
            hc_v  = trig_d.get("hist_c",0)
            hcp_v = trig_d.get("hist_c_prev",0)
            d1_v  = trig_d.get("d1",0)
            rv_v  = trig_d.get("rvol")
            rv_txt = f"｜RVOL {rv_v:.2f}×" if rv_v is not None else ""

            if resonance.get("direction") == "bear" and lvl == "red":
                st.markdown(f"""<div class="alert-card-bear">
                    <div style="font-family:'IBM Plex Mono',monospace;font-size:15px;
                                font-weight:700;margin-bottom:10px;color:#9b2335;">
                        🔴 風險警報 {pts_v} 分｜{symbol} [{trigger_tf}]{rv_txt}
                    </div>
                    <div class="alert-body">
                    {atype}<br>
                    {trigger_tf} Histogram（已收盤）前根 <b>{hcp_v:+.3f}</b> → 現在
                    <b style="color:#c0392b">{hc_v:+.3f}</b>｜D+1 預測
                    <b style="color:#c0392b">{d1_v:+.3f}</b><br>
                    <br><b>評分明細：</b><br>{det_html}
                    <br><b>交易建議（{plan_style}）：</b><br>{plan_html}
                    </div>
                </div>""", unsafe_allow_html=True)
            elif resonance.get("direction") == "bull" and lvl == "red":
                st.markdown(f"""<div class="alert-card">
                    <div style="font-family:'IBM Plex Mono',monospace;font-size:15px;
                                font-weight:700;margin-bottom:10px;">
                        ⚡ 進場預警 {pts_v} 分｜{symbol} [{trigger_tf}]{rv_txt}
                    </div>
                    <div class="alert-body">
                    {atype}<br>
                    {trigger_tf} Histogram（已收盤）現在 <b>{hc_v:+.3f}</b>｜D+1 預測
                    <b style="color:#3d8b5e">{d1_v:+.3f}</b><br>
                    <br><b>評分明細：</b><br>{det_html}
                    <br><b>交易建議（{plan_style}）：</b><br>{plan_html}
                    </div>
                </div>""", unsafe_allow_html=True)
            elif resonance.get("direction") == "bear":
                plan_txt = "  \n".join(p.strip() for p in plan_ls if not p.startswith("\n【"))
                st.warning(f"🟠 {atype}｜" + "、".join(det_ls) + "  \n" + plan_txt)
            else:
                plan_txt = "  \n".join(p.strip() for p in plan_ls if not p.startswith("\n【"))
                st.info(f"👀 {atype}｜" + "、".join(det_ls) + "  \n" + plan_txt)

        # ── 傳導鏈總覽圖 ────────────────────────────────────
        st.plotly_chart(build_cascade_chart(cascade), use_container_width=True, key=f"cascade_{symbol}_{id(cascade)}")

        # ── 傳導鏈各時框卡片 ────────────────────────────────
        valid_c = [r for r in cascade if r.get("valid")]
        if valid_c:
            cols_c = st.columns(len(valid_c))
            for idx, r in enumerate(valid_c):
                hc  = "pos" if r["hist"]>=0 else "neg"
                is_trig = r["tf"] == trigger_tf
                border  = "border:2px solid #f0a500;" if is_trig else ""
                role    = "⚡ 觸發時框" if is_trig else ("✅ 確認時框" if r["tf"] in confirm_tfs else "")

                # D+1/D+2/D+3 顏色
                def dspan(v):
                    c = "pos" if v>=0 else "neg"
                    return f'<span class="{c}" style="font-weight:700;">{v:+.3f}</span>'

                # 如果是觸發時框且即將翻正，高亮 D+1
                d1_extra = ""
                if is_trig and r["hist"]<0 and r["d1"]>0:
                    d1_extra = ' style="background:#fff3cd;border-radius:4px;padding:0 4px;"'

                with cols_c[idx]:
                    st.markdown(f"""<div class="metric-card" style="{border}">
                        <div style="display:flex;justify-content:space-between;align-items:center;">
                            <div class="label">{r['tf'].upper()}</div>
                            <div style="font-size:10px;background:#e8e3da;color:#555;
                                        padding:1px 7px;border-radius:3px;font-weight:700;
                                        font-family:'IBM Plex Mono',monospace;">
                                ATR {r['atr']:.3f}
                            </div>
                        </div>
                        <div class="value {hc}" style="font-size:20px;margin:6px 0 2px;">
                            {r['hist']:+.3f}
                        </div>
                        <div style="margin-bottom:8px;">{trend_pill(r['trend'])}</div>
                        <div style="border-top:1px solid #e8e3da;padding-top:8px;
                                    font-family:'IBM Plex Mono',monospace;font-size:11px;">
                            <div style="display:flex;justify-content:space-between;margin-bottom:3px;">
                                <span style="color:#aaa;">D+1</span>
                                <span{d1_extra}>{dspan(r['d1'])}</span>
                            </div>
                            <div style="display:flex;justify-content:space-between;margin-bottom:3px;">
                                <span style="color:#aaa;">D+2</span>{dspan(r['d2'])}
                            </div>
                            <div style="display:flex;justify-content:space-between;">
                                <span style="color:#aaa;">D+3</span>{dspan(r['d3'])}
                            </div>
                        </div>
                        {f'<div style="margin-top:7px;font-size:10px;color:#f0a500;font-weight:700;font-family:IBM Plex Mono,monospace;">{role}</div>' if role else ''}
                    </div>""", unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

    else:
        cascade   = []
        resonance = {"score":0,"max":0,"alert":False,"atype":None,"trigger":None}

    # ── MACD 表格 ────────────────────────────────────────────
    st.markdown("#### 📋 近 10 根 K 線 MACD 分析")
    st.markdown(render_table(df_t), unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    # ── MACD 圖表 ────────────────────────────────────────────
    with st.expander(f"📈 {symbol} MACD 圖表", expanded=True):
        cdf = df_main.tail(60)
        fig = build_macd_chart(cdf, symbol,
                                macd_s.tail(60), sig_s.tail(60), hist_s.tail(60),
                                interval=tf_cfg["interval"])
        st.plotly_chart(fig, use_container_width=True, key=f"macd_chart_{symbol}")

    # ── Telegram 信號 ─────────────────────────────────────────
    if chain_tfs:
        tg_msg = build_tg_msg(symbol, cascade, resonance,
                               confirm_tfs, trigger_tf, close_val, atr_main,
                               plan_style=plan_style)
        tg_msgs_all.append(tg_msg)

        # ── v2.4：蒐集排序比較數據（供排行榜與深度分析 Prompt 使用）──
        trig_d = resonance.get("trigger") or {}
        rank_data.append({
            "symbol": symbol, "close": close_val, "atr": atr_main,
            "atr_pct": (atr_main/close_val*100) if close_val else 0,
            "trend": trend,
            "alert": resonance["alert"], "direction": resonance.get("direction"),
            "level": resonance.get("level"), "pts": resonance.get("pts", 0),
            "bull_pts": resonance.get("bull_pts", 0), "bear_pts": resonance.get("bear_pts", 0),
            "atype": resonance.get("atype"),
            "score": resonance["score"], "max": resonance["max"],
            "detail": resonance.get("detail", []),
            "rvol": trig_d.get("rvol"), "below_vwap": trig_d.get("below_vwap"),
            "vwap": trig_d.get("vwap"), "vwap_kind": trig_d.get("vwap_kind"),
            "gap_pct": trig_d.get("gap_pct"),
            "trigger_tf": trigger_tf,
            "cascade": [
                {"tf": r["tf"], "hist": r.get("hist_c", r.get("hist")), "d1": r.get("d1")}
                for r in cascade if r.get("valid")
            ],
        })
    else:
        tg_msg = ""

    # ── 警報自動推送（去重：symbol+方向+等級 每小時最多一次）──
    if chain_tfs and tg_auto and resonance["alert"] and tg_token and tg_chat:
        _dk = hashlib.md5(
            f"{symbol}|{resonance.get('direction')}|{resonance.get('level')}|{trigger_tf}|"
            f"{datetime.now(ZoneInfo('America/New_York')).strftime('%Y-%m-%d %H')}".encode()
        ).hexdigest()
        _sent = st.session_state.setdefault("tg_sent_hashes", set())
        if _dk not in _sent:
            ok_auto, _ = send_telegram(tg_token, tg_chat, tg_msg)
            if ok_auto:
                _sent.add(_dk)
                st.toast(f"🔔 已自動推送 {symbol} 警報", icon="📡")
    if chain_tfs:
        with st.expander(f"📡 Telegram 信號 — {symbol}"):
            st.markdown(f'<div class="tg-box">{tg_msg}</div>', unsafe_allow_html=True)

    st.markdown("---")


# ── v2.4 排序比較 + 深度分析 Prompt ─────────────────────────────
if rank_data:
    st.markdown("## 🏆 排序比較")
    ranked = sorted(rank_data, key=rank_key, reverse=True)
    disp_rows = []
    for i, r in enumerate(ranked, 1):
        eff_dir = r["direction"] or leaning(r)
        sub     = max(r.get("bull_pts", 0), r.get("bear_pts", 0))
        if r["direction"]:
            dirn = {"bear":"🔴 空頭","bull":"🟢 多頭"}[r["direction"]]
        elif eff_dir:
            dirn = {"bear":f"🔴 偏空（未達門檻，潛在 {sub} 分）",
                    "bull":f"🟢 偏多（未達門檻，潛在 {sub} 分）"}[eff_dir]
        else:
            dirn = "⚪ 中性"
        lvl  = {"red":"🔴 紅色警報","yellow":"🟠 橙色觀察",None:"⚪ 靜默"}.get(r["level"],"⚪ 靜默")
        disp_rows.append({
            "排名": i, "代碼": r["symbol"], "方向": dirn, "等級": lvl,
            "評分": r["pts"] if r["pts"] else f"(潛在{sub})",
            "收盤": f"{r['close']:.2f}",
            "ATR%": f"{r['atr_pct']:.2f}%", "趨勢": r["trend"],
            "RVOL": f"{r['rvol']:.2f}×" if r.get("rvol") is not None else "—",
            "VWAP位置": (
                f"{'下方' if r['below_vwap'] else '上方'} "
                f"{abs(r['close']/r['vwap']-1)*100:.2f}%"
                if r.get("vwap") and r.get("below_vwap") is not None else "—"
            ),
        })
    st.dataframe(pd.DataFrame(disp_rows), hide_index=True, use_container_width=True)
    if all(r["pts"] == 0 for r in rank_data):
        st.caption("⚠️ 這批標的目前都沒有正式警報（大時框本來就少見翻轉屬正常），"
                   "排序改用「潛在傾向分」——僅供參考，不代表已觸發訊號。")

    st.markdown("#### 📋 最佳股票分析 Prompt · 複製後貼入任意 AI 進行深度分析")
    st.caption("本系統只做技術面 + 量能的程式化判定；把下方內容貼給 ChatGPT / Claude / "
               "Gemini 等，可補上基本面、新聞、產業比較等本系統覆蓋不到的部分。")
    prompt_text = build_analysis_prompt(rank_data, main_tf, trigger_tf)
    st.code(prompt_text, language="markdown")

st.markdown("---")

# ── 批量發送 Telegram ─────────────────────────────────────────
if tg_send:
    if not tg_token or not tg_chat:
        st.error("請填寫 Bot Token 和 Chat ID")
    else:
        ok = sum(1 for msg in tg_msgs_all
                 if (send_telegram(tg_token, tg_chat, msg)[0] or time.sleep(0.5) or False))
        st.success(f"✅ 已發送 {ok}/{len(tg_msgs_all)} 個信號")



# ══════════════════════════════════════════════════════════════
# 回測區塊（主頁面底部）
# ══════════════════════════════════════════════════════════════
st.markdown("# 📊 三步瀑布傳導回測")
st.markdown("""
<div style="font-family:'IBM Plex Mono',monospace;font-size:12px;color:#888;
            background:#fff8f0;border:1px solid #d4cfc6;border-left:4px solid #5a7fa8;
            border-radius:8px;padding:12px 16px;margin-bottom:12px;line-height:1.9;">
<b>回測邏輯（忠實還原三步入場）：</b><br>
Step 1 &nbsp;→&nbsp; 1d + 1h Histogram > 0 &nbsp;（大方向多頭確認）<br>
Step 2 &nbsp;→&nbsp; 5m D+1 > 0 &nbsp;+&nbsp; 15m D+1 > 0 &nbsp;+&nbsp; 30m D+1 > 0 &nbsp;（傳導鏈預警）<br>
Step 3 &nbsp;→&nbsp; 30m Histogram 前根 &lt; 0 → 當根 ≥ 0 &nbsp;（實際翻正，執行入場）<br>
<b>數據範圍：最近 60 天日內數據（5m / 15m / 30m / 1h / 1d）</b>
</div>
""", unsafe_allow_html=True)
st.markdown("---")

# ── 回測參數設定 ──────────────────────────────────────────────
bc1, bc2, bc3, bc4 = st.columns(4)
with bc1:
    bt_symbols = st.multiselect(
        "回測股票",
        symbols if symbols else DEFAULT_SYMBOLS,
        default=symbols[:1] if symbols else ["TSLA"],
    )
with bc2:
    bt_exit_mode = st.radio(
        "📤 出場模式",
        ["固定根數", "30m轉負", "1d/1h轉負"],
        index=0,
        help=(
            "固定根數：持倉滿 N 根 30m K 線後平倉\n"
            "30m轉負：30m Histogram 再次轉負時出場\n"
            "1d/1h轉負：1h 或 1d Histogram 轉負時出場（跟隨大趨勢）"
        ),
    )
    bt_hold = st.slider(
        "固定根數（30m K線）" if bt_exit_mode == "固定根數" else "保底根數倍率參考",
        3, 48, 6,
        disabled=(bt_exit_mode != "固定根數"),
        help="固定根數模式：持倉 N 根後平倉\n動態模式：作為保底上限倍率的基礎",
    )
with bc3:
    bt_atr_sl = st.slider("止損 (×ATR 30m)", 0.5, 3.0, 1.5, 0.5)
    bt_atr_tp = st.slider("止盈 (×ATR 30m)", 1.0, 6.0, 3.0, 0.5)
with bc4:
    st.markdown("**出場模式說明**")
    if bt_exit_mode == "固定根數":
        _md_title = "🕐 固定根數"
        _md_info  = f"持倉 <b>{bt_hold}</b> 根 30m K線 ≈ {bt_hold//2}小時<br>止損/盈：30m ATR<br><br>適合：短線、震盪市"
    elif bt_exit_mode == "30m轉負":
        _md_title = "🔄 30m 轉負出場"
        _md_info  = "30m Histogram 正→負 時出場<br>止損/盈：30m ATR<br><br>適合：日內趨勢跟蹤"
    else:
        _md_title = "📅 1d/1h 轉負出場"
        _md_info  = "1h 或 1d Histogram 轉負時出場<br>止損/盈：30m ATR<br><br>適合：波段持倉數天"
    st.markdown(
        '<div class="metric-card" style="font-size:11px;line-height:1.9;">'
        + '<div class="label">' + _md_title + '</div>'
        + '<div style="margin-top:8px;">' + _md_info + '</div></div>',
        unsafe_allow_html=True,
    )
    run_bt = st.button("🚀 開始回測", type="primary", use_container_width=True)

if run_bt and bt_symbols:
    for bt_sym in bt_symbols:
        mode_label = {
            "固定根數":  f"固定 {bt_hold} 根 30m",
            "30m轉負":   "30m Histogram 轉負",
            "1d/1h轉負": "1d/1h Histogram 轉負",
        }[bt_exit_mode]
        st.markdown(f"## 📈 {bt_sym}  —  最近60天 · 出場：{mode_label}")

        with st.spinner(f"載入 {bt_sym} 多時框數據並計算..."):
            result = run_cascade_backtest(
                bt_sym, atr_sl=bt_atr_sl, atr_tp=bt_atr_tp,
                hold_bars=bt_hold, exit_mode=bt_exit_mode,
            )

        # 錯誤處理
        if "error" in result:
            st.error(f"⚠️ {bt_sym}：{result['error']}")
            continue

        if result.get("total", 0) == 0:
            diag = result.get("diag", {})
            total_bars  = diag.get("total_bars",  "?")
            step1_pass  = diag.get("step1_pass",  0)
            step2_alert = diag.get("step2_alert", 0)
            step3_entry = diag.get("step3_entry", 0)

            # 找出卡在哪一步
            if step1_pass == 0:
                bottleneck = "❌ Step 1 從未通過：1d / 1h Histogram 未同時 > 0（大方向未確認多頭）"
                tip = "目前市場可能處於空頭或震盪。建議等待 1d 和 1h 同時翻正後再回測。"
            elif step2_alert == 0:
                bottleneck = "❌ Step 2 從未觸發：Step1 通過但傳導鏈 D+1 未同時預測翻正"
                tip = "5m / 15m / 30m 的 D+1 預測未能同時 > 0。可能是震盪市，或者 5m 數據 yfinance 只能取 7天，可能不足。"
            elif step3_entry == 0:
                bottleneck = "❌ Step 3 從未入場：預警發出但 30m Histogram 翻正時 Step1 已失效"
                tip = "預警發出的下一根 K 線，1d 或 1h 已轉負。市場變化快，大方向短暫失效。可嘗試放寬 Step1 條件。"
            else:
                bottleneck = "⚠️ 信號找到但未生成交易記錄，請檢查數據"
                tip = ""

            st.warning(f"⚠️ {bt_sym}：60天內未找到完整三步入場信號")
            st.markdown(f"""
            <div style="background:#fff8f0;border:1px solid #d4cfc6;border-radius:10px;
                        padding:16px 20px;font-family:'IBM Plex Mono',monospace;font-size:12px;
                        line-height:2;">
            <b>📊 診斷報告</b><br>
            ─────────────────────────────────────<br>
            總 30m K 線數：<b>{total_bars}</b> 根<br>
            Step 1 通過（1d+1h 同時多頭）：<b>{step1_pass}</b> 根
            &nbsp;{"✅" if step1_pass > 0 else "❌"}<br>
            Step 2 預警觸發（傳導鏈D+1翻正）：<b>{step2_alert}</b> 次
            &nbsp;{"✅" if step2_alert > 0 else "❌"}<br>
            Step 3 實際入場（30m翻正）：<b>{step3_entry}</b> 次
            &nbsp;{"✅" if step3_entry > 0 else "❌"}<br>
            ─────────────────────────────────────<br>
            <b>瓶頸：</b>{bottleneck}<br>
            <b>建議：</b>{tip}
            </div>
            """, unsafe_allow_html=True)
            continue

        # ── KPI 卡片 ──────────────────────────────────────
        st.markdown(render_bt_kpi(result, bt_sym, bt_hold, bt_atr_sl, bt_atr_tp),
                    unsafe_allow_html=True)

        # ── 主圖：入場標注在 30m 圖上 ───────────────────────
        st.markdown("##### 🎯 30m K線入場/出場標注圖")
        st.markdown("""
        <div style="font-size:11px;color:#aaa;font-family:'IBM Plex Mono',monospace;margin-bottom:6px;">
        ▲ 綠色三角 = 盈利入場 &nbsp;|&nbsp; ▲ 紅色三角 = 虧損入場 &nbsp;|&nbsp;
        橙色虛線 = D+1預測（翻正即觸發Step2）
        </div>""", unsafe_allow_html=True)
        fig_entry = build_bt_entry_chart(result["aligned"], result["trades"])
        st.plotly_chart(fig_entry, use_container_width=True, key=f"bt_entry_{bt_sym}")

        # ── 副圖：權益曲線 ────────────────────────────────
        st.markdown("##### 📉 累計收益曲線")
        fig_eq = build_equity_curve(result["trades"])
        st.plotly_chart(fig_eq, use_container_width=True, key=f"bt_eq_{bt_sym}")

        # ── 出場原因分析 ──────────────────────────────────
        col_pie, col_reason, col_extreme = st.columns(3)
        df_t_bt = pd.DataFrame(result["trades"])

        with col_pie:
            st.markdown("##### 出場原因分佈")
            rc_counts = df_t_bt["exit_reason"].value_counts()
            fig_pie = go.Figure(go.Pie(
                labels=rc_counts.index.tolist(),
                values=rc_counts.values.tolist(),
                marker=dict(colors=["#c0392b","#3d8b5e","#5a7fa8"]),
                textinfo="label+percent", hole=0.4,
            ))
            fig_pie.update_layout(
                paper_bgcolor="#fff8f0",
                font=dict(family="IBM Plex Mono", size=11),
                margin=dict(l=0,r=0,t=10,b=0), height=220, showlegend=False,
            )
            st.plotly_chart(fig_pie, use_container_width=True, key=f"bt_pie_{bt_sym}")

        with col_reason:
            st.markdown("##### 各出場方式勝率")
            for reason in ["止損","止盈","到期平倉"]:
                sub = df_t_bt[df_t_bt["exit_reason"]==reason]
                if len(sub) == 0: continue
                wr_r = sub["win"].mean()*100
                wc_r = "#3d8b5e" if wr_r>=55 else ("#e07b39" if wr_r>=45 else "#c0392b")
                st.markdown(f"""<div class="metric-card" style="margin-bottom:8px;">
                    <div class="label">{reason}</div>
                    <div class="value" style="color:{wc_r};font-size:20px;">{wr_r:.1f}%</div>
                    <div class="sub">{len(sub)}筆 · 均 {sub['pnl_pct'].mean():+.2f}%</div>
                </div>""", unsafe_allow_html=True)

        with col_extreme:
            st.markdown("##### 最佳 / 最差")
            best  = df_t_bt.loc[df_t_bt["pnl_pct"].idxmax()]
            worst = df_t_bt.loc[df_t_bt["pnl_pct"].idxmin()]
            st.markdown(f"""
            <div class="metric-card" style="margin-bottom:8px;border:1.5px solid #3d8b5e;">
                <div class="label">🏆 最佳交易</div>
                <div class="value pos">{best['pnl_pct']:+.2f}%</div>
                <div class="sub">{str(best['entry_time'])[:16]}</div>
                <div class="sub">{best['exit_reason']}</div>
            </div>
            <div class="metric-card" style="border:1.5px solid #c0392b;">
                <div class="label">💥 最差交易</div>
                <div class="value neg">{worst['pnl_pct']:+.2f}%</div>
                <div class="sub">{str(worst['entry_time'])[:16]}</div>
                <div class="sub">{worst['exit_reason']}</div>
            </div>""", unsafe_allow_html=True)

        # ── 逐筆明細 ──────────────────────────────────────
        with st.expander("🔍 逐筆交易明細（最近25筆）"):
            st.markdown(render_trades_table(result["trades"], max_rows=25),
                        unsafe_allow_html=True)

        st.markdown("---")

elif not run_bt:
    st.markdown("""
    <div style="text-align:center;padding:40px;color:#aaa;
                font-family:'IBM Plex Mono',monospace;font-size:13px;">
    👆 選擇股票，設定參數，點擊「開始回測」<br><br>
    系統將嚴格按照三步入場邏輯，在最近60天30m K線上<br>
    模擬每一個信號的入場和出場，統計真實成功率
    </div>
    """, unsafe_allow_html=True)

st.markdown("""
<div style='text-align:center;color:#bbb;font-size:11px;margin-top:20px;
            font-family:IBM Plex Mono,monospace;'>
MACD 瀑布動能傳導系統 v2.0 ｜ 數據：Yahoo Finance ｜ 僅供參考，不構成投資建議
</div>
""", unsafe_allow_html=True)

st.markdown("""
<div style='text-align:center;color:#bbb;font-size:11px;margin-top:20px;
            font-family:IBM Plex Mono,monospace;'>
MACD 瀑布動能傳導系統 v2.0 ｜ 數據：Yahoo Finance ｜ 僅供參考，不構成投資建議
</div>
""", unsafe_allow_html=True)
