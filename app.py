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
    for i in range(len(hist)):
        h  = hist.iloc[i]
        hp = hist.iloc[i-1]  if i>0 else h
        m  = macd.iloc[i]
        s  = signal.iloc[i]
        mp = macd.iloc[i-1]  if i>0 else m
        sp = signal.iloc[i-1] if i>0 else s
        if   abs(h) < 0.005:                      st = "接近反轉"
        elif i>0 and hp<0 and h>=0:               st = "Histogram翻正"
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
    elif any(k in st for k in ["空頭","動能強"]):
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
@st.cache_data(ttl=60)
def fetch_data(symbol, period, interval):
    try:
        df = yf.Ticker(symbol).history(period=period, interval=interval)
        if df.empty: return pd.DataFrame()
        return df[["Open","High","Low","Close","Volume"]].dropna()
    except:
        return pd.DataFrame()


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
        macd, sig, hist = calc_macd(df["Close"])
        sts  = classify_status(hist, macd, sig)
        hv   = hist.iloc[-1]
        mv   = macd.iloc[-1]
        sv   = sts[-1]
        d1,d2,d3 = predict_next3(hist)
        results.append({
            "tf":tf, "valid":True,
            "hist":hv, "macd":mv, "status":sv,
            "trend":get_trend(mv,hv,sv),
            "d1":d1, "d2":d2, "d3":d3,
            "atr":calc_atr(df),
            "close":df["Close"].iloc[-1],
        })
    return results


def calc_resonance(cascade, confirm_tfs, trigger_tf):
    """
    共振評分：
    - 確認時框（大時框）Histogram > 0 各得 1 分
    - 觸發時框當前 < 0 且 D+1 > 0 → 進場預警 + 加 1 分
    - 觸發時框當前 < 0 且 D+1 < 0 但縮小 → 觀察信號
    """
    valid = [r for r in cascade if r.get("valid")]
    confirm_score, confirm_max = 0, 0

    for r in valid:
        if r["tf"] in confirm_tfs:
            confirm_max += 1
            if r["hist"] > 0:
                confirm_score += 1

    trig  = next((r for r in valid if r["tf"] == trigger_tf), None)
    alert = False
    atype = None

    if trig:
        h, d1 = trig["hist"], trig["d1"]
        if h < 0 and d1 > 0 and confirm_score >= max(1, confirm_max * 0.5):
            alert = True
            atype = "預警：D+1 預測翻正，準備做多"
        elif h < 0 and d1 < 0 and d1 > h:
            alert = True
            atype = "觀察：空頭動能減弱"

    total = confirm_score + (1 if alert and atype and "預警" in atype else 0)
    return {
        "score":   total,
        "max":     confirm_max + 1,
        "alert":   alert,
        "atype":   atype,
        "trigger": trig,
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
def build_tg_msg(symbol, cascade, resonance, confirm_tfs, trigger_tf, close_price, atr_1d):
    atype = resonance.get("atype","")
    trig  = resonance.get("trigger") or {}

    if resonance["alert"] and "預警" in atype:
        header = f"⚡ {symbol} 進場預警"
    elif resonance["score"] >= resonance["max"] * 0.7:
        header = f"📈 {symbol} 多頭共振"
    else:
        header = f"📊 {symbol} 市場分析"

    lines = [header, "━"*32, "【大時框方向確認】"]
    for r in cascade:
        if not r.get("valid") or r["tf"] not in confirm_tfs:
            continue
        icon = "✅" if r["hist"]>0 else "❌"
        lines.append(f"  {r['tf']:>3s}  {icon}  Hist {fmt(r['hist'],3)}  D+1 {fmt(r['d1'],3)}")

    if trig and trig.get("valid"):
        h, d1 = trig["hist"], trig["d1"]
        warn  = " ← 預計翻正 🚨" if h<0 and d1>0 else ""
        lines += [
            f"\n【觸發時框 {trigger_tf}】",
            f"  現在  Hist {fmt(h,3)}",
            f"  D+1        {fmt(d1,3)}{warn}",
            f"  D+2        {fmt(trig['d2'],3)}",
            f"  D+3        {fmt(trig['d3'],3)}",
        ]

    lines += [f"\n【共振強度】 {resonance['score']}/{resonance['max']}"]
    if atype:
        lines.append(f"【信號類型】 {atype}")

    if atr_1d > 0:
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

    lines.append(f"\n📅 {datetime.now().strftime('%Y-%m-%d %H:%M')} ET")
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
# 回測引擎
# ══════════════════════════════════════════════════════════════

BACKTEST_PERIODS = {
    "1年":  "1y",
    "2年":  "2y",
    "5年":  "5y",
    "10年": "10y",
}

@st.cache_data(ttl=300)
def fetch_backtest_layers(symbol: str) -> dict:
    """
    取回所有回測時框數據。
    瀑布傳導鏈：1w / 1d / 4h（合成）/ 1h
    1h 最多 730 天，用於 1y/2y 回測。
    5y/10y 自動使用日線觸發。
    """
    result = {}
    try:
        result["1w"] = yf.Ticker(symbol).history(period="10y",  interval="1wk").dropna()
    except: result["1w"] = pd.DataFrame()
    try:
        result["1d"] = yf.Ticker(symbol).history(period="10y",  interval="1d").dropna()
    except: result["1d"] = pd.DataFrame()
    try:
        df_1h = yf.Ticker(symbol).history(period="730d", interval="1h").dropna()
        result["1h"] = df_1h
        if not df_1h.empty:
            df_1h_c = df_1h.copy()
            df_1h_c.index = pd.to_datetime(df_1h_c.index, utc=True)
            r = df_1h_c.resample("4h")
            result["4h"] = pd.DataFrame({
                "Open":   r["Open"].first(),
                "High":   r["High"].max(),
                "Low":    r["Low"].min(),
                "Close":  r["Close"].last(),
                "Volume": r["Volume"].sum(),
            }).dropna()
        else:
            result["4h"] = pd.DataFrame()
    except:
        result["1h"] = pd.DataFrame()
        result["4h"] = pd.DataFrame()
    return result


def _calc_atr_series(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, cp = df["High"], df["Low"], df["Close"].shift(1)
    tr = pd.concat([h - l, (h - cp).abs(), (l - cp).abs()], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def _d1_series(hist: pd.Series) -> pd.Series:
    """D+1 預測序列：slope = (hist[i] - hist[i-2]) / 2，d1 = hist[i] + slope"""
    slope = (hist - hist.shift(2)) / 2.0
    return hist + slope


def _align_confirm(hist_slow: pd.Series, trig_idx: pd.DatetimeIndex) -> pd.Series:
    """把慢速時框 Histogram 向前填充對齊到觸發時框索引"""
    s = hist_slow.copy()
    s.index = pd.to_datetime(s.index, utc=True)
    return s.reindex(s.index.union(trig_idx)).ffill().reindex(trig_idx)


def run_backtest(
    layers: dict,
    period_label: str,
    hold_bars: int = 10,
    atr_sl: float = 1.5,
    atr_tp: float = 3.0,
) -> dict:
    """
    ══════════════════════════════════════════════════════
    瀑布傳導回測引擎  — 三步入場邏輯

    第一步：1w + 1d 確認大方向多頭
      1w Histogram > 0 OR 1w D+1 > 0
      1d Histogram > 0 OR 1d D+1 > 0

    第二步：4h 中間傳導層
      4h Histogram > 0 OR 4h D+1 > 0

    第三步：1h 觸發（1y/2y）/ 1d 觸發（5y/10y）
      觸發層 Histogram < 0（尚未入場）
      觸發層 D+1 > 0（預計翻正）← 核心信號
      觸發層連續2根縮減（傳導中）
    ══════════════════════════════════════════════════════
    """
    long_period = period_label in ["5年","10年"]
    trig_label  = "1d" if long_period else "1h"

    df_trig  = layers.get(trig_label, pd.DataFrame())
    df_1w    = layers.get("1w",  pd.DataFrame())
    df_1d    = layers.get("1d",  pd.DataFrame())
    df_4h    = layers.get("4h",  pd.DataFrame())

    if df_trig.empty or len(df_trig) < 60:
        return {"error": f"觸發時框 {trig_label} 數據不足", "total": 0}

    # 截取回測時間範圍
    period_days = {"1年":365,"2年":730,"5年":1825,"10年":3650}
    cutoff_days = period_days.get(period_label, 730)
    df_trig.index = pd.to_datetime(df_trig.index, utc=True)
    cutoff_dt = df_trig.index[-1] - pd.Timedelta(days=cutoff_days)
    df_trig   = df_trig[df_trig.index >= cutoff_dt]
    if len(df_trig) < 60:
        return {"error": "截取後數據不足60根", "total": 0}

    # 觸發層指標
    _, _, hist_trig = calc_macd(df_trig["Close"])
    atr_trig        = _calc_atr_series(df_trig)
    d1_trig         = _d1_series(hist_trig)
    trig_idx        = pd.to_datetime(hist_trig.index, utc=True)

    # 確認層（對齊到觸發層索引）
    def conf_arrays(df_conf):
        if df_conf is None or df_conf.empty or len(df_conf) < 26:
            return None, None
        _, _, hc = calc_macd(df_conf["Close"])
        d1c = _d1_series(hc)
        return (_align_confirm(hc, trig_idx).values,
                _align_confirm(d1c, trig_idx).values)

    c1w_h,  c1w_d1  = conf_arrays(df_1w)            # 週線
    c1d_h,  c1d_d1  = conf_arrays(df_1d if long_period else df_1d)
    c4h_h,  c4h_d1  = conf_arrays(df_4h if not long_period else None)

    # 主回測
    h_arr   = hist_trig.values.astype(float)
    d1_arr  = d1_trig.values.astype(float)
    atr_arr = atr_trig.values.astype(float)
    lo_arr  = df_trig["Low"].values.astype(float)
    hi_arr  = df_trig["High"].values.astype(float)
    c_arr   = df_trig["Close"].values.astype(float)
    dates   = trig_idx

    def layer_ok(h_a, d1_a, i):
        if h_a is None or np.isnan(h_a[i]): return True
        return float(h_a[i]) > 0 or float(d1_a[i]) > 0

    trades, in_trade = [], False
    entry_i = entry_price = entry_atr_v = None

    for i in range(30, len(h_arr) - hold_bars - 1):
        if np.isnan(atr_arr[i]) or atr_arr[i] <= 0:
            continue

        if not in_trade:
            # ── 三步入場條件 ────────────────────────────
            step1 = layer_ok(c1w_h, c1w_d1, i)     # 週線多頭
            step2 = layer_ok(c1d_h, c1d_d1, i)     # 日線多頭
            step3 = layer_ok(c4h_h, c4h_d1, i) if not long_period else True  # 4h傳導

            h_now   = float(h_arr[i])
            d1_now  = float(d1_arr[i])
            h_prev  = float(h_arr[i-1]) if i>0 else h_now
            h_prev2 = float(h_arr[i-2]) if i>1 else h_prev

            shrinking = (abs(h_now) < abs(h_prev)) and (abs(h_prev) < abs(h_prev2))

            trigger = (
                h_now  < 0    and  # 觸發層仍為負（尚未入場）
                d1_now > 0    and  # D+1 預測翻正 ← 核心
                shrinking     and  # 動能連續縮減（傳導進行中）
                h_prev < 0    and  # 前根也在空頭
                step1 and step2 and step3
            )

            if trigger:
                ei = i + 1
                if ei >= len(c_arr): continue
                in_trade    = True
                entry_i     = ei
                entry_price = float(c_arr[ei])
                entry_atr_v = float(atr_arr[i])

        elif in_trade and entry_i is not None:
            bars_held = i - entry_i
            sl = entry_price - atr_sl * entry_atr_v
            tp = entry_price + atr_tp * entry_atr_v

            exit_reason = None
            exit_price  = float(c_arr[i])

            if lo_arr[i] <= sl:
                exit_reason, exit_price = "止損", sl
            elif hi_arr[i] >= tp:
                exit_reason, exit_price = "止盈", tp
            elif bars_held >= hold_bars:
                exit_reason = "到期平倉"

            if exit_reason:
                pnl = (exit_price - entry_price) / entry_price * 100
                trades.append({
                    "entry_date":  dates[entry_i],
                    "exit_date":   dates[i],
                    "entry_price": entry_price,
                    "exit_price":  exit_price,
                    "pnl_pct":     pnl,
                    "bars_held":   bars_held,
                    "exit_reason": exit_reason,
                    "win":         pnl > 0,
                    "year":        int(dates[entry_i].year),
                    "trigger_tf":  trig_label,
                })
                in_trade = False
                entry_i = entry_price = entry_atr_v = None

    if not trades:
        return {"trades":[], "total":0, "wins":0, "losses":0,
                "win_rate":0, "avg_win":0, "avg_loss":0,
                "profit_factor":0, "max_consec_loss":0,
                "total_return":0, "by_year":{}, "trigger_tf":trig_label}

    df_t   = pd.DataFrame(trades)
    wins   = df_t[df_t["win"]]
    losses = df_t[~df_t["win"]]

    max_cl = cur_cl = 0
    for w in df_t["win"]:
        cur_cl = 0 if w else cur_cl + 1
        max_cl = max(max_cl, cur_cl)

    by_year = {}
    for yr, grp in df_t.groupby("year"):
        w = grp[grp["win"]]
        by_year[int(yr)] = {
            "total":    len(grp),
            "wins":     len(w),
            "win_rate": len(w)/len(grp)*100,
            "avg_pnl":  grp["pnl_pct"].mean(),
        }

    aw = wins["pnl_pct"].mean()   if len(wins)   > 0 else 0.0
    al = losses["pnl_pct"].mean() if len(losses) > 0 else 0.0
    pf = abs(aw*len(wins)) / abs(al*len(losses)) if len(losses)>0 and al!=0 else 99.0

    return {
        "trades": df_t.to_dict("records"), "total": len(df_t),
        "wins": len(wins), "losses": len(losses),
        "win_rate":        len(wins)/len(df_t)*100,
        "avg_win":         aw,  "avg_loss": al,
        "profit_factor":   min(pf,99.0),
        "max_consec_loss": max_cl,
        "total_return":    df_t["pnl_pct"].sum(),
        "by_year":         by_year,
        "df_trades":       df_t,
        "trigger_tf":      trig_label,
    }


def build_equity_curve(trades: list) -> go.Figure:
    """權益曲線圖"""
    if not trades:
        return go.Figure()

    df_t    = pd.DataFrame(trades)
    cum_pnl = df_t["pnl_pct"].cumsum().values
    dates   = pd.to_datetime(df_t["exit_date"])
    colors  = ["#3d8b5e" if p > 0 else "#c0392b" for p in df_t["pnl_pct"]]

    fig = make_subplots(rows=2, cols=1, shared_xaxes=False,
                        row_heights=[0.65, 0.35], vertical_spacing=0.08,
                        subplot_titles=["累計收益曲線（%）", "每筆交易盈虧（%）"])

    # 累計曲線
    fig.add_trace(go.Scatter(
        x=dates, y=cum_pnl, mode="lines+markers",
        name="累計收益",
        line=dict(color="#5a7fa8", width=2),
        marker=dict(size=4, color=colors),
        fill="tozeroy",
        fillcolor="rgba(90,127,168,0.08)",
    ), row=1, col=1)
    fig.add_hline(y=0, line_dash="dot", line_color="#aaa", row=1, col=1)

    # 逐筆柱
    fig.add_trace(go.Bar(
        x=dates, y=df_t["pnl_pct"],
        name="單筆盈虧",
        marker_color=colors,
        opacity=0.8,
    ), row=2, col=1)
    fig.add_hline(y=0, line_dash="dot", line_color="#aaa", row=2, col=1)

    fig.update_layout(
        paper_bgcolor="#fff8f0", plot_bgcolor="#fff8f0",
        font=dict(family="IBM Plex Mono, Noto Sans TC", color="#2c2c2c", size=11),
        margin=dict(l=10, r=10, t=36, b=10),
        height=420,
        showlegend=False,
    )
    fig.update_xaxes(gridcolor="#e8e3da")
    fig.update_yaxes(gridcolor="#e8e3da", zeroline=True, zerolinecolor="#c0bbb2")
    return fig


def build_yearly_chart(by_year: dict) -> go.Figure:
    """年度勝率與信號數"""
    if not by_year:
        return go.Figure()
    years     = [str(y) for y in sorted(by_year.keys())]
    win_rates = [by_year[int(y)]["win_rate"] for y in years]
    totals    = [by_year[int(y)]["total"]    for y in years]
    avg_pnls  = [by_year[int(y)]["avg_pnl"] for y in years]

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(
        x=years, y=win_rates, name="年度勝率 %",
        marker_color=["#3d8b5e" if r>=50 else "#c0392b" for r in win_rates],
        opacity=0.8,
        text=[f"{r:.0f}%" for r in win_rates],
        textposition="outside",
    ), secondary_y=False)
    fig.add_trace(go.Scatter(
        x=years, y=totals, name="信號數",
        mode="lines+markers+text",
        line=dict(color="#e07b39", width=2),
        marker=dict(size=7),
        text=totals, textposition="top center",
        textfont=dict(size=10),
    ), secondary_y=True)

    fig.add_hline(y=50, line_dash="dash", line_color="#aaa",
                  annotation_text="50%", secondary_y=False)
    fig.update_layout(
        paper_bgcolor="#fff8f0", plot_bgcolor="#fff8f0",
        font=dict(family="IBM Plex Mono, Noto Sans TC", color="#2c2c2c", size=11),
        margin=dict(l=10, r=10, t=10, b=10),
        height=260,
        legend=dict(orientation="h", y=1.1, x=0),
        barmode="group",
    )
    fig.update_xaxes(gridcolor="#e8e3da", type="category")
    fig.update_yaxes(gridcolor="#e8e3da", range=[0,110], title_text="勝率 %", secondary_y=False)
    fig.update_yaxes(gridcolor="#e8e3da", title_text="信號數", secondary_y=True)
    return fig


def render_bt_summary(result: dict, symbol: str, period_label: str,
                       hold_days: int, atr_sl: float, atr_tp: float) -> str:
    """回測摘要指標卡 HTML"""
    wr  = result["win_rate"]
    pf  = result["profit_factor"]
    wr_color  = "#3d8b5e" if wr  >= 55 else ("#e07b39" if wr  >= 45 else "#c0392b")
    pf_color  = "#3d8b5e" if pf  >= 1.5 else ("#e07b39" if pf  >= 1.0 else "#c0392b")
    tr_color  = "#3d8b5e" if result["total_return"] >= 0 else "#c0392b"

    return f"""
    <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin:12px 0;">
        <div class="metric-card">
            <div class="label">總信號數</div>
            <div class="value" style="font-size:28px;">{result['total']}</div>
            <div class="sub">{period_label} · 日線</div>
        </div>
        <div class="metric-card">
            <div class="label">整體勝率</div>
            <div class="value" style="color:{wr_color};font-size:28px;">{wr:.1f}%</div>
            <div class="sub">{result['wins']}勝 / {result['losses']}負</div>
        </div>
        <div class="metric-card">
            <div class="label">盈虧比 (PF)</div>
            <div class="value" style="color:{pf_color};font-size:28px;">{pf:.2f}</div>
            <div class="sub">平均勝 {result['avg_win']:.2f}% / 負 {result['avg_loss']:.2f}%</div>
        </div>
        <div class="metric-card">
            <div class="label">最大連虧</div>
            <div class="value" style="color:#c0392b;font-size:28px;">{result['max_consec_loss']}</div>
            <div class="sub">連續虧損次數</div>
        </div>
        <div class="metric-card">
            <div class="label">累計收益</div>
            <div class="value" style="color:{tr_color};font-size:28px;">{result['total_return']:+.1f}%</div>
            <div class="sub">持倉{hold_days}日 · SL {atr_sl}×ATR · TP {atr_tp}×ATR</div>
        </div>
    </div>"""


def render_trades_table(trades: list, max_rows: int = 20) -> str:
    """逐筆交易明細表"""
    cols = ["入場日期","出場日期","入場價","出場價","持倉根","盈虧%","結果","出場原因"]
    hdr  = "".join(f"<th>{c}</th>" for c in cols)
    body = ""
    for t in trades[-max_rows:]:
        pnl  = t["pnl_pct"]
        pc_  = "cell-pos" if pnl >= 0 else "cell-neg"
        rslt = '<span class="badge badge-bull">▲ 盈利</span>' if t["win"] else '<span class="badge badge-bear">▼ 虧損</span>'
        reason_map = {"止損":"badge-bear","止盈":"badge-bull","到期平倉":"badge-neu"}
        rc = reason_map.get(t["exit_reason"], "badge-neu")
        reason_badge = f'<span class="badge {rc}">{t["exit_reason"]}</span>'
        ed = pd.Timestamp(t["entry_date"]).strftime("%m/%d/%Y")
        xd = pd.Timestamp(t["exit_date"]).strftime("%m/%d/%Y")
        body += f"""<tr>
            <td>{ed}</td><td>{xd}</td>
            <td>{t['entry_price']:.2f}</td><td>{t['exit_price']:.2f}</td>
            <td>{t.get('bars_held', t.get('days_held', '-'))}</td>
            <td class="{pc_}">{pnl:+.2f}%</td>
            <td>{rslt}</td><td>{reason_badge}</td>
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

    st.markdown("---")
    st.markdown("**⏱ 自動刷新**")
    auto_refresh     = st.checkbox("啟用", value=False)
    refresh_interval = st.selectbox("間隔（秒）", [60,120,180,300], index=0)

    st.markdown("---")
    st.markdown("**📡 Telegram**")
    tg_token = st.text_input("Bot Token", type="password", placeholder="xxxxx:ABC...")
    tg_chat  = st.text_input("Chat ID",  placeholder="-100xxxxxxxxx")
    tg_send  = st.button("📤 發送所有信號")

    st.markdown("---")
    st.caption(f"更新：{datetime.now().strftime('%H:%M:%S')}")

if auto_refresh:
    st.markdown(f"""<script>
    setTimeout(function(){{window.location.reload();}},{refresh_interval*1000});
    </script>""", unsafe_allow_html=True)
    st.info(f"⏱ 每 {refresh_interval} 秒自動刷新")


# ══════════════════════════════════════════════════════════════
# 主頁面
# ══════════════════════════════════════════════════════════════
st.markdown("# 🌊 MACD 瀑布動能傳導系統")
chain_str   = "  →  ".join(chain_tfs) if chain_tfs else "未設定"
confirm_str = ", ".join(confirm_tfs)  if confirm_tfs else "—"
st.markdown(f"""
<div style="font-size:12px;color:#888;font-family:'IBM Plex Mono',monospace;margin-bottom:4px;">
傳導鏈：{chain_str} &nbsp;|&nbsp; 觸發：<b style="color:#f0a500">{trigger_tf}</b>
&nbsp;|&nbsp; 確認：{confirm_str}
</div>
""", unsafe_allow_html=True)
st.markdown("---")

tf_cfg      = TIMEFRAME_MAP[main_tf]
tg_msgs_all = []

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

        # ── 預警橫幅 ────────────────────────────────────────
        if resonance["alert"]:
            trig_d = resonance.get("trigger") or {}
            atype  = resonance.get("atype","")
            if "預警" in atype:
                h_now = trig_d.get("hist",0)
                d1_v  = trig_d.get("d1",0)
                st.markdown(f"""<div class="alert-card">
                    <div style="font-family:'IBM Plex Mono',monospace;font-size:15px;
                                font-weight:700;margin-bottom:10px;">
                        ⚡ 進場預警｜{symbol} [{trigger_tf}]
                    </div>
                    <div class="alert-body">
                    確認時框（{confirm_str}）✅ 多頭方向對齊<br>
                    {trigger_tf} Histogram 現在 <b style="color:#c0392b">{h_now:+.3f}</b>（仍為負）<br>
                    {trigger_tf} D+1 預測 <b style="color:#3d8b5e">{d1_v:+.3f}</b>
                    &nbsp;→&nbsp; <b>預計下一根 K 線翻正</b><br>
                    <br>
                    📌 建議：提前掛單準備做多，下一根 {trigger_tf} K線收盤確認後執行<br>
                    🛑 止損：收盤 {close_val:.2f} &minus; 1.5 × ATR({main_tf}) =
                       <b>{close_val - 1.5*atr_main:.2f}</b>
                    </div>
                </div>""", unsafe_allow_html=True)
            else:
                st.info(f"👀 {atype}｜{trigger_tf} 空頭動能縮減，持續觀察傳導鏈")

        # ── 傳導鏈總覽圖 ────────────────────────────────────
        st.plotly_chart(build_cascade_chart(cascade), use_container_width=True)

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
        st.plotly_chart(fig, use_container_width=True)

    # ── Telegram 信號 ─────────────────────────────────────────
    tg_msg = build_tg_msg(symbol, cascade, resonance,
                           confirm_tfs, trigger_tf, close_val, atr_main)
    tg_msgs_all.append(tg_msg)
    with st.expander(f"📡 Telegram 信號 — {symbol}"):
        st.markdown(f'<div class="tg-box">{tg_msg}</div>', unsafe_allow_html=True)

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
st.markdown("# 📊 信號回測分析")
st.markdown("""
<div style="font-size:12px;color:#888;font-family:'IBM Plex Mono',monospace;margin-bottom:8px;">
基於你的設計原理：Histogram 空頭縮減 + D+1 預測翻正 → 模擬入場，ATR 止損/止盈/到期平倉
</div>
""", unsafe_allow_html=True)
st.markdown("---")

# 回測設定
bt_col1, bt_col2, bt_col3, bt_col4 = st.columns(4)
with bt_col1:
    bt_symbols = st.multiselect(
        "回測股票",
        symbols if symbols else DEFAULT_SYMBOLS,
        default=symbols[:1] if symbols else ["TSLA"],
    )
with bt_col2:
    bt_period_label = st.selectbox("回測周期", list(BACKTEST_PERIODS.keys()), index=1)
    bt_period       = BACKTEST_PERIODS[bt_period_label]
with bt_col3:
    bt_hold    = st.slider("持倉K線根數", 3, 40, 10, help="1h模式=小時根數，1d模式=天數")
    bt_atr_sl  = st.slider("止損 (×ATR)", 0.5, 3.0, 1.5, 0.5)
with bt_col4:
    bt_atr_tp  = st.slider("止盈 (×ATR)", 1.0, 5.0, 3.0, 0.5)
    run_bt     = st.button("🚀 開始回測", type="primary")

if run_bt and bt_symbols:
    for bt_sym in bt_symbols:
        st.markdown(f"## 📈 {bt_sym} — {bt_period_label}回測")

        with st.spinner(f"載入 {bt_sym} 所有時框數據（1w / 1d / 4h / 1h）..."):
            layers = fetch_backtest_layers(bt_sym)

        # 根據回測周期選擇數據範圍
        long_period = bt_period_label in ["5年","10年"]
        df_check = layers.get("1h") if not long_period else layers.get("1d")
        if df_check is None or df_check.empty or len(df_check) < 60:
            st.warning(f"⚠️ {bt_sym} {'1h' if not long_period else '1d'} 數據不足，無法回測")
            continue

        if long_period:
            # 5y/10y：截取對應長度
            cutoff = {"5年": 365*5, "10年": 365*10}[bt_period_label]
            from datetime import timedelta
            cutoff_date = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=cutoff)
            for k in ["1w","1d"]:
                if layers.get(k) is not None and not layers[k].empty:
                    idx = pd.to_datetime(layers[k].index, utc=True)
                    layers[k] = layers[k][idx >= cutoff_date]

        result = run_backtest(
            layers,
            period_label = bt_period_label,
            hold_bars    = bt_hold,
            atr_sl       = bt_atr_sl,
            atr_tp       = bt_atr_tp,
        )

        if not result or result.get("total", 0) == 0:
            st.warning(f"⚠️ {bt_sym} 回測期間未找到信號，請調整參數")
            continue

        # ── 摘要指標卡 ────────────────────────────────────
        trig_tf_label = result.get("trigger_tf","1h")
        st.markdown(f"""
        <div style="font-size:12px;color:#888;font-family:'IBM Plex Mono',monospace;margin-bottom:8px;">
        入場觸發時框：<b>{trig_tf_label}</b>
        &nbsp;|&nbsp; 確認層：{'1w + 1d + 4h' if trig_tf_label=='1h' else '1w + 1d'}
        &nbsp;|&nbsp; 持倉 {bt_hold} 根K線 · 止損 {bt_atr_sl}×ATR · 止盈 {bt_atr_tp}×ATR
        </div>
        """, unsafe_allow_html=True)
        st.markdown(render_bt_summary(result, bt_sym, bt_period_label, bt_hold, bt_atr_sl, bt_atr_tp),
                    unsafe_allow_html=True)

        # ── 圖表區 ────────────────────────────────────────
        ch1, ch2 = st.columns([3, 2])
        with ch1:
            st.markdown("##### 📉 累計收益曲線")
            fig_eq = build_equity_curve(result["trades"])
            st.plotly_chart(fig_eq, use_container_width=True)
        with ch2:
            st.markdown("##### 📅 年度勝率分佈")
            fig_yr = build_yearly_chart(result["by_year"])
            st.plotly_chart(fig_yr, use_container_width=True)

        # ── 年度明細表 ────────────────────────────────────
        with st.expander("📊 年度統計明細"):
            by_year = result["by_year"]
            yr_rows = ""
            for yr in sorted(by_year.keys()):
                d   = by_year[yr]
                wrc = "#3d8b5e" if d["win_rate"]>=55 else ("#e07b39" if d["win_rate"]>=45 else "#c0392b")
                pc_ = "#3d8b5e" if d["avg_pnl"]>=0 else "#c0392b"
                yr_rows += f"""<tr>
                    <td>{yr}</td>
                    <td>{d['total']}</td>
                    <td>{d['wins']}</td>
                    <td style="color:{wrc};font-weight:700;">{d['win_rate']:.1f}%</td>
                    <td style="color:{pc_};font-weight:700;">{d['avg_pnl']:+.2f}%</td>
                </tr>"""
            yr_hdr = "".join(f"<th>{c}</th>" for c in ["年份","總信號","勝","勝率","平均盈虧"])
            st.markdown(
                f'<table class="macd-table"><thead><tr>{yr_hdr}</tr></thead><tbody>{yr_rows}</tbody></table>',
                unsafe_allow_html=True)

        # ── 逐筆交易明細 ──────────────────────────────────
        with st.expander("🔍 最近20筆交易明細"):
            st.markdown(render_trades_table(result["trades"], max_rows=20),
                        unsafe_allow_html=True)

        # ── 出場原因分佈 ──────────────────────────────────
        with st.expander("📐 出場原因分析"):
            df_trades_bt = pd.DataFrame(result["trades"])
            reason_counts = df_trades_bt["exit_reason"].value_counts()
            fig_reason = go.Figure(go.Pie(
                labels=reason_counts.index.tolist(),
                values=reason_counts.values.tolist(),
                marker=dict(colors=["#c0392b","#3d8b5e","#5a7fa8"]),
                textinfo="label+percent",
                hole=0.4,
            ))
            fig_reason.update_layout(
                paper_bgcolor="#fff8f0",
                font=dict(family="IBM Plex Mono", size=12),
                margin=dict(l=10,r=10,t=10,b=10),
                height=280,
                showlegend=False,
            )
            rc1, rc2, rc3 = st.columns(3)
            with rc1:
                st.plotly_chart(fig_reason, use_container_width=True)
            with rc2:
                # 勝率 by 出場原因
                for reason in df_trades_bt["exit_reason"].unique():
                    sub = df_trades_bt[df_trades_bt["exit_reason"]==reason]
                    wr_r = sub["win"].mean()*100 if len(sub)>0 else 0
                    wrc  = "#3d8b5e" if wr_r>=55 else ("#e07b39" if wr_r>=45 else "#c0392b")
                    st.markdown(f"""<div class="metric-card" style="margin-bottom:8px;">
                        <div class="label">{reason} 勝率</div>
                        <div class="value" style="color:{wrc};font-size:22px;">{wr_r:.1f}%</div>
                        <div class="sub">{len(sub)} 筆 · 平均 {sub['pnl_pct'].mean():+.2f}%</div>
                    </div>""", unsafe_allow_html=True)
            with rc3:
                # 最佳/最差
                best  = df_trades_bt.loc[df_trades_bt["pnl_pct"].idxmax()]
                worst = df_trades_bt.loc[df_trades_bt["pnl_pct"].idxmin()]
                st.markdown(f"""<div class="metric-card" style="margin-bottom:8px;border:1px solid #3d8b5e;">
                    <div class="label">🏆 最佳交易</div>
                    <div class="value pos">{best['pnl_pct']:+.2f}%</div>
                    <div class="sub">{pd.Timestamp(best['entry_date']).strftime('%Y/%m/%d')} 入場</div>
                </div>
                <div class="metric-card" style="border:1px solid #c0392b;">
                    <div class="label">💥 最差交易</div>
                    <div class="value neg">{worst['pnl_pct']:+.2f}%</div>
                    <div class="sub">{pd.Timestamp(worst['entry_date']).strftime('%Y/%m/%d')} 入場</div>
                </div>""", unsafe_allow_html=True)

        st.markdown("---")

elif not run_bt:
    st.info("👆 選擇股票和回測周期，點擊「開始回測」查看歷史信號成功率")

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
