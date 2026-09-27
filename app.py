import re
from datetime import datetime

import numpy as np
import pandas as pd
import requests
import streamlit as st
import yfinance as yf

st.set_page_config(page_title="台股變化雷達", page_icon="📡", layout="wide")
st.title("📡 台股變化雷達")
st.caption("關閉＝完全不參與｜加分＝符合才加分、不淘汰｜必要＝不符合才淘汰｜數值 0＝不限制")

MODES = ["關閉", "加分", "必要"]
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json,text/plain,text/html,*/*"}
TWSE_BASIC = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX_BASIC = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"
TWSE_NEWLIST = "https://www.twse.com.tw/rwd/zh/company/applylisting?response=html"
MOPS_CB = "https://mops.twse.com.tw/mops/web/t120sb02_q10"
TPEX_CB = "https://www.tpex.org.tw/zh-tw/bond/issue/cbond/listed.html"


def num(v):
    try:
        return float(str(v).replace(",", "").replace("%", "").strip())
    except Exception:
        return np.nan


def fetch_json(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def fetch_text(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        return r.text
    except Exception:
        return ""


@st.cache_data(ttl=21600, show_spinner=False)
def innovation_codes():
    """以證交所『最近上市公司』官方頁的備註/名稱辨識創新板。"""
    codes = set()
    try:
        tables = pd.read_html(TWSE_NEWLIST)
        for df in tables:
            for _, row in df.iterrows():
                text = " ".join(str(x) for x in row.values)
                if "創新板" in text or re.search(r"(?:-創|KY創)\b", text):
                    m = re.search(r"(?<!\d)(\d{4})(?!\d)", text)
                    if m:
                        codes.add(m.group(1))
    except Exception:
        pass
    return codes


@st.cache_data(ttl=21600, show_spinner=False)
def stock_pool():
    rows, seen = [], set()
    innov = innovation_codes()

    twse = fetch_json(TWSE_BASIC) or []
    for x in twse:
        code = str(x.get("公司代號", x.get("Code", ""))).strip()
        if len(code) != 4 or not code.isdigit() or code.startswith("00"):
            continue

        name = str(x.get("公司簡稱", x.get("公司名稱", x.get("Name", "")))).strip()
        cap = num(x.get("實收資本額", x.get("Paidin.Capital.NTDollars", np.nan)))
        market = "創新板" if code in innov or "-創" in name or "KY創" in name else "上市"

        rows.append({
            "代號": code,
            "名稱": name,
            "市場": market,
            "產業": str(x.get("產業別", x.get("產業類別", ""))).strip(),
            "股本億": cap / 1e8 if pd.notna(cap) else np.nan,
            "symbol": code + ".TW",
        })

        seen.add(code)

    tpex = fetch_json(TPEX_BASIC) or []

    for x in tpex:
        code = str(x.get("SecuritiesCompanyCode", x.get("公司代號", ""))).strip()

        if len(code) != 4 or not code.isdigit() or code.startswith("00") or code in seen:
            continue

        name = str(
            x.get(
                "CompanyAbbreviation",
                x.get("CompanyName", x.get("公司簡稱", ""))
            )
        ).strip()

        cap = num(
            x.get(
                "Paidin.Capital.NTDollars",
                x.get("實收資本額", np.nan)
            )
        )

        rows.append({
            "代號": code,
            "名稱": name,
            "市場": "上櫃",
            "產業": str(
                x.get(
                    "SecuritiesIndustryCode",
                    x.get("產業別", "")
                )
            ).strip(),
            "股本億": cap / 1e8 if pd.notna(cap) else np.nan,
            "symbol": code + ".TWO",
        })

        seen.add(code)

    cols = ["代號", "名稱", "市場", "產業", "股本億", "symbol"]

    if not rows:
        return pd.DataFrame(columns=cols)

    return (
        pd.DataFrame(rows)[cols]
        .drop_duplicates("代號")
        .sort_values("代號")
        .reset_index(drop=True)
    )


@st.cache_data(ttl=3600, show_spinner=False)
def price_history(symbol):
    try:
        d = yf.download(
            symbol,
            period="5y",
            auto_adjust=False,
            progress=False,
            threads=False,
            timeout=15
        )

        if isinstance(d.columns, pd.MultiIndex):
            d.columns = d.columns.get_level_values(0)

        d.index = pd.to_datetime(d.index)

        required = {"Close", "High", "Low", "Volume"}

        if not required.issubset(set(d.columns)):
            return pd.DataFrame()

        return d.dropna(subset=["Close"])

    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=21600, show_spinner=False)
def fundamentals(symbol):

    z = {
        "市值億": np.nan,
        "營收成長": np.nan,
        "獲利成長": np.nan,
        "毛利率": np.nan,
        "營益率": np.nan,
        "CAPEX成長": np.nan,
        "CAPEX營收比": np.nan,
        "合約負債成長": np.nan,
        "現金流改善": np.nan,
        "存貨變化": np.nan,
        "應收變化": np.nan,
        "新聞": []
    }

    try:
        ticker = yf.Ticker(symbol)

        try:
            info = ticker.get_info() or {}

            settings = [
                ("市值億", "marketCap", 1e-8),
                ("營收成長", "revenueGrowth", 100),
                ("獲利成長", "earningsGrowth", 100),
                ("毛利率", "grossMargins", 100),
                ("營益率", "operatingMargins", 100),
            ]

            for key, src, mult in settings:
                v = num(info.get(src, np.nan))

                if pd.notna(v):
                    z[key] = v * mult

        except Exception:
            pass

        def find_row(df, words):
            if df is None or df.empty:
                return pd.Series(dtype=float)

            for idx in df.index:
                if any(w in str(idx).lower() for w in words):
                    return pd.to_numeric(
                        df.loc[idx],
                        errors="coerce"
                    ).dropna()

            return pd.Series(dtype=float)

        try:
            cf = ticker.quarterly_cashflow

            capex = find_row(
                cf,
                ["capital expenditure"]
            )

            if len(capex) >= 5 and capex.iloc[4] != 0:
                z["CAPEX成長"] = (
                    abs(capex.iloc[0]) /
                    abs(capex.iloc[4]) - 1
                ) * 100

            ocf = find_row(
                cf,
                [
                    "operating cash flow",
                    "total cash from operating"
                ]
            )

            if len(ocf) >= 2:
                z["現金流改善"] = bool(
                    ocf.iloc[0] > ocf.iloc[1]
                )

            inc = ticker.quarterly_income_stmt
            rev = find_row(
                inc,
                ["total revenue"]
            )

            if len(capex) and len(rev) and rev.iloc[0] != 0:
                z["CAPEX營收比"] = (
                    abs(capex.iloc[0]) /
                    abs(rev.iloc[0]) * 100
                )

        except Exception:
            pass

        try:
            bs = ticker.quarterly_balance_sheet

            rows = [
                ("合約負債成長", ["contract liabil"]),
                ("存貨變化", ["inventory"]),
                (
                    "應收變化",
                    [
                        "accounts receivable",
                        "receivables"
                    ]
                ),
            ]

            for key, words in rows:
                s = find_row(bs, words)

                if len(s) >= 2 and s.iloc[1] != 0:
                    z[key] = (
                        s.iloc[0] /
                        s.iloc[1] - 1
                    ) * 100

        except Exception:
            pass

        try:
            z["新聞"] = ticker.news[:10] if ticker.news else []
        except Exception:
            pass

    except Exception:
        pass

    return z


def technical(d, base_months=6):

    if d.empty:
        return {}

    c = pd.to_numeric(d["Close"], errors="coerce").dropna()
    h = pd.to_numeric(d["High"], errors="coerce").dropna()
    l = pd.to_numeric(d["Low"], errors="coerce").dropna()
    v = pd.to_numeric(d["Volume"], errors="coerce").dropna()

    if len(c) < 20:
        return {}

    p = c.iloc[-1]

    peak = h.tail(
        min(504, len(h))
    ).max()

    dd = (
        (peak - p) / peak * 100
        if peak
        else np.nan
    )

    n = min(
        len(d),
        max(
            20,
            int(base_months or 6) * 21
        )
    )

    recent = d.tail(n)

    rh = pd.to_numeric(
        recent["High"],
        errors="coerce"
    ).max()

    rl = pd.to_numeric(
        recent["Low"],
        errors="coerce"
    ).min()

    base = (
        (rh - rl) / rl * 100
        if rl
        else np.nan
    )

    ma60 = (
        c.rolling(60).mean().iloc[-1]
        if len(c) >= 60
        else np.nan
    )

    ma60d = (
        (p / ma60 - 1) * 100
        if pd.notna(ma60) and ma60
        else np.nan
    )

    w = c.resample("W").last().dropna()

    wma = (
        w.rolling(20).mean().iloc[-1]
        if len(w) >= 20
        else np.nan
    )

    wd = (
        (p / wma - 1) * 100
        if pd.notna(wma) and wma
        else np.nan
    )

    m = c.resample("ME").last().dropna()

    mma = (
        m.rolling(20).mean().iloc[-1]
        if len(m) >= 20
        else np.nan
    )

    md = (
        (p / mma - 1) * 100
        if pd.notna(mma) and mma
        else np.nan
    )

    vg = (
        (
            v.tail(20).mean() /
            v.tail(60).mean() - 1
        ) * 100
        if len(v) >= 60 and v.tail(60).mean()
        else np.nan
    )

    r20 = (
        (p / c.iloc[-20] - 1) * 100
        if len(c) >= 20
        else np.nan
    )

    r60 = (
        (p / c.iloc[-60] - 1) * 100
        if len(c) >= 60
        else np.nan
    )

    mr = m.pct_change() * 100

    same = mr[
        (mr.index.month == datetime.now().month) &
        (mr.index.year < datetime.now().year)
    ].dropna()

    cyc = (
        same.mean()
        if len(same) >= 2
        else np.nan
    )

    return {
        "現價": p,
        "高點回落": dd,
        "築底區間": base,
        "MA60距離": ma60d,
        "週MA20距離": wd,
        "月MA20距離": md,
        "量能": vg,
        "20日漲跌": r20,
        "60日漲跌": r60,
        "歷史同月平均": cyc
    }


def news_events(news):

    titles = []

    for item in news:
        if isinstance(item, dict):
            content = item.get("content", item)

            if isinstance(content, dict) and content.get("title"):
                titles.append(
                    str(content["title"])
                )

    joined = " ".join(titles).lower()

    rules = {
        "合作": [
            "合作",
            "partnership",
            "alliance",
            "strategic"
        ],
        "新客戶/訂單": [
            "訂單",
            "客戶",
            "order",
            "customer",
            "供應鏈"
        ],
        "擴產": [
            "擴產",
            "新廠",
            "產能",
            "設備",
            "capacity",
            "plant"
        ],
        "新產品/認證": [
            "新品",
            "新產品",
            "認證",
            "certification"
        ],
        "併購投資": [
            "併購",
            "收購",
            "投資",
            "acquisition",
            "merger"
        ]
    }

    events = [
        k
        for k, words in rules.items()
        if any(
            w.lower() in joined
            for w in words
        )
    ]

    return events, titles[:5]


@st.cache_data(ttl=21600, show_spinner=False)
def official_cb_codes():
    """
    CB 官方頁存在，但目前不從 HTML 中任意抓四位數
    當作公司代號，以免把日期、債券代號等誤認成股票代號。
    沒有可靠結構化欄位時回空集合。
    """
    return set()


def eval_num(
    value,
    threshold,
    direction,
    selected_mode,
    label,
    reasons,
    score,
    weight=10
):

    if selected_mode == "關閉" or threshold == 0:
        return True, score

    if pd.isna(value):
        return (
            False if selected_mode == "必要"
            else True
        ), score

    if direction == "ge":
        ok = value >= threshold

    elif direction == "le":
        ok = value <= threshold

    else:
        ok = abs(value) <= threshold

    if ok:
        reasons.append(
            f"{label} {value:.1f}"
        )
        score += weight

    return (
        ok if selected_mode == "必要"
        else True
    ), score


def eval_bool(
    value,
    selected_mode,
    label,
    reasons,
    score,
    weight=10,
    missing=False
):

    if selected_mode == "關閉":
        return True, score

    if missing:
        return (
            False if selected_mode == "必要"
            else True
        ), score

    ok = bool(value)

    if ok:
        reasons.append(label)
        score += weight

    return (
        ok if selected_mode == "必要"
        else True
    ), score


def mode(label, key):
    return st.selectbox(
        label,
        MODES,
        index=0,
        key=key
    )


with st.sidebar:

    st.header("條件")

    markets = st.multiselect(
        "市場",
        [
            "上市",
            "上櫃",
            "創新板"
        ],
        default=[
            "上市",
            "上櫃",
            "創新板"
        ]
    )

    ddm = mode("高點回落", "ddm")
    dd = st.selectbox(
        "回落門檻 %",
        [0, 30, 40, 50, 60, 70]
    )

    bm = mode("築底", "bm")
    bmo = st.selectbox(
        "築底月數",
        [0, 2, 3, 6, 12, 18, 24]
    )
    br = st.selectbox(
        "築底最大區間 %",
        [0, 10, 15, 20, 25, 30, 40, 50]
    )

    m60 = mode("MA60", "m60")
    m60v = st.selectbox(
        "MA60距離 ±%",
        [0, 5, 10, 15, 20, 30]
    )

    wm = mode("週MA20", "wm")
    wmv = st.selectbox(
        "週MA20距離 ±%",
        [0, 5, 10, 15, 20, 30]
    )

    mm = mode("月MA20", "mm")
    mmv = st.selectbox(
        "月MA20距離 ±%",
        [0, 5, 10, 15, 20, 30]
    )

    vm = mode("底部量能", "vm")
    vv = st.selectbox(
        "量能門檻 %",
        [0, 10, 20, 30, 50, 100]
    )

    rm = mode("營收成長", "rm")
    rv = st.selectbox(
        "營收門檻 %",
        [0, 5, 10, 20, 30, 50, 100]
    )

    em = mode("獲利成長", "em")
    ev = st.selectbox(
        "獲利門檻 %",
        [0, 5, 10, 20, 30, 50, 100]
    )

    cm = mode("CAPEX成長", "cm")
    cv = st.selectbox(
        "CAPEX門檻 %",
        [0, 10, 20, 30, 50, 100, 200]
    )

    crm = mode("CAPEX/營收", "crm")
    crv = st.selectbox(
        "CAPEX/營收門檻 %",
        [0, 5, 10, 20, 30, 50]
    )

    clm = mode("合約負債", "clm")
    clv = st.selectbox(
        "合約負債門檻 %",
        [0, 10, 20, 30, 50, 100]
    )

    cfm = mode(
        "營業現金流改善",
        "cfm"
    )

    mcm = mode("市值", "mcm")
    mcv = st.selectbox(
        "市值上限 億",
        [0, 50, 100, 200, 300, 500, 1000, 3000]
    )

    cam = mode("股本", "cam")
    cav = st.selectbox(
        "股本上限 億",
        [0, 10, 20, 30, 50, 100, 200]
    )

    etm = mode(
        "合作/客戶/擴產事件",
        "etm"
    )

    gm = mode("群體性", "gm")
    gv = st.selectbox(
        "同產業同步轉強比例 %",
        [0, 30, 40, 50, 60, 70]
    )

    rom = mode("族群輪動", "rom")
    rov = st.selectbox(
        "產業平均20日漲幅 %",
        [0, 3, 5, 10, 15, 20]
    )

    cym = mode("歷史循環", "cym")
    cyv = st.selectbox(
        "歷史同月平均 %",
        [0, 3, 5, 10, 15, 20]
    )


pool = stock_pool()
cb_codes = official_cb_codes()

tabs = st.tabs([
    "雷達",
    "個股",
    "族群＋CB",
    "資料來源/健康檢查"
])


with tabs[0]:

    selected = (
        pool[
            pool["市場"].isin(markets)
        ].copy()
        if not pool.empty
        else pool
    )

    st.metric(
        "股票池",
        len(selected)
    )

    limit = st.selectbox(
        "本次掃描檔數",
        [20, 50, 100, 200],
        index=1
    )

    start = st.text_input(
        "從代號開始（空白＝最前面）"
    ).strip()

    work = (
        selected[
            selected["代號"] >= start
        ].head(limit)
        if start
        else selected.head(limit)
    )

    active_modes = [
        ddm,
        bm,
        m60,
        wm,
        mm,
        vm,
        rm,
        em,
        cm,
        crm,
        clm,
        cfm,
        mcm,
        cam,
        etm,
        gm,
        rom,
        cym
    ]

    all_off = all(
        x == "關閉"
        for x in active_modes
    )

    if all_off and not work.empty:

        st.info(
            "全部條件關閉："
            "直接顯示股票，不做任何淘汰。"
        )

        st.dataframe(
            work[
                [
                    "代號",
                    "名稱",
                    "市場",
                    "產業",
                    "股本億"
                ]
            ],
            use_container_width=True,
            hide_index=True
        )

    if st.button(
        "開始掃描",
        type="primary",
        use_container_width=True
    ):

        if work.empty:

            st.error(
                "股票池目前沒有資料；"
                "這不是『沒有符合股票』。"
            )

        elif all_off:

            out = work[
                [
                    "代號",
                    "名稱",
                    "市場",
                    "產業",
                    "股本億"
                ]
            ].copy()

            out["分數"] = 0
            out["為什麼抓到"] = "全部條件關閉"

            st.dataframe(
                out,
                use_container_width=True,
                hide_index=True
            )

        else:

            res = []
            bar = st.progress(0)

            for n, (_, r) in enumerate(
                work.iterrows(),
                1
            ):

                tech = technical(
                    price_history(
                        r["symbol"]
                    ),
                    bmo or 6
                )

                fund = fundamentals(
                    r["symbol"]
                )

                keep = True
                score = 0
                why = []

                tests = [
                    (
                        tech.get(
                            "高點回落",
                            np.nan
                        ),
                        dd,
                        "ge",
                        ddm,
                        "高點回落%"
                    ),
                    (
                        tech.get(
                            "築底區間",
                            np.nan
                        ),
                        br,
                        "le",
                        bm if bmo else "關閉",
                        f"{bmo}月築底區間%"
                    ),
                    (
                        tech.get(
                            "MA60距離",
                            np.nan
                        ),
                        m60v,
                        "abs",
                        m60,
                        "MA60距離%"
                    ),
                    (
                        tech.get(
                            "週MA20距離",
                            np.nan
                        ),
                        wmv,
                        "abs",
                        wm,
                        "週MA20距離%"
                    ),
                    (
                        tech.get(
                            "月MA20距離",
                            np.nan
                        ),
                        mmv,
                        "abs",
                        mm,
                        "月MA20距離%"
                    ),
                    (
                        tech.get(
                            "量能",
                            np.nan
                        ),
                        vv,
                        "ge",
                        vm,
                        "量能%"
                    ),
                    (
                        fund["營收成長"],
                        rv,
                        "ge",
                        rm,
                        "營收成長%"
                    ),
                    (
                        fund["獲利成長"],
                        ev,
                        "ge",
                        em,
                        "獲利成長%"
                    ),
                    (
                        fund["CAPEX成長"],
                        cv,
                        "ge",
                        cm,
                        "CAPEX成長%"
                    ),
                    (
                        fund["CAPEX營收比"],
                        crv,
                        "ge",
                        crm,
                        "CAPEX/營收%"
                    ),
                    (
                        fund["合約負債成長"],
                        clv,
                        "ge",
                        clm,
                        "合約負債%"
                    ),
                    (
                        fund["市值億"],
                        mcv,
                        "le",
                        mcm,
                        "市值億"
                    ),
                    (
                        r["股本億"],
                        cav,
                        "le",
                        cam,
                        "股本億"
                    ),
                ]

                for (
                    value,
                    threshold,
                    direction,
                    md,
                    label
                ) in tests:

                    if keep:
                        keep, score = eval_num(
                            value,
                            threshold,
                            direction,
                            md,
                            label,
                            why,
                            score
                        )

                if keep:

                    keep, score = eval_bool(
                        fund[
                            "現金流改善"
                        ],
                        cfm,
                        "營業現金流改善",
                        why,
                        score,
                        missing=pd.isna(
                            fund[
                                "現金流改善"
                            ]
                        )
                    )

                evs, titles = news_events(
                    fund["新聞"]
                )

                if keep:

                    keep, score = eval_bool(
                        bool(evs),
                        etm,
                        "事件：" + ",".join(evs),
                        why,
                        score
                    )

                if keep:

                    res.append({
                        "代號":
                            r["代號"],

                        "名稱":
                            r["名稱"],

                        "市場":
                            r["市場"],

                        "產業":
                            r["產業"] or "未分類",

                        "現價":
                            tech.get(
                                "現價",
                                np.nan
                            ),

                        "高點回落%":
                            tech.get(
                                "高點回落",
                                np.nan
                            ),

                        "20日漲跌%":
                            tech.get(
                                "20日漲跌",
                                np.nan
                            ),

                        "量能%":
                            tech.get(
                                "量能",
                                np.nan
                            ),

                        "營收成長%":
                            fund[
                                "營收成長"
                            ],

                        "CAPEX成長%":
                            fund[
                                "CAPEX成長"
                            ],

                        "合約負債%":
                            fund[
                                "合約負債成長"
                            ],

                        "歷史同月%":
                            tech.get(
                                "歷史同月平均",
                                np.nan
                            ),

                        "事件":
                            ",".join(evs),

                        "分數":
                            score,

                        "理由":
                            why
                    })

                bar.progress(
                    n / max(
                        len(work),
                        1
                    )
                )

            if not res:

                st.warning(
                    "沒有股票通過目前的"
                    "『必要』條件，"
                    "或必要資料缺失。"
                )

            else:

                d = pd.DataFrame(res)

                group_stats = {}

                for industry, g in d.groupby(
                    "產業"
                ):

                    valid = g[
                        [
                            "20日漲跌%",
                            "量能%"
                        ]
                    ].dropna()

                    ratio = (
                        (
                            (
                                (
                                    valid[
                                        "20日漲跌%"
                                    ] > 0
                                )
                                &
                                (
                                    valid[
                                        "量能%"
                                    ] > 0
                                )
                            ).mean()
                            * 100
                        )
                        if len(valid)
                        else np.nan
                    )

                    avg = pd.to_numeric(
                        g[
                            "20日漲跌%"
                        ],
                        errors="coerce"
                    ).mean()

                    group_stats[
                        industry
                    ] = (
                        ratio,
                        avg
                    )

                final = []

                for _, r in d.iterrows():

                    keep = True
                    score = int(
                        r["分數"]
                    )
                    why = list(
                        r["理由"]
                    )

                    ratio, avg = (
                        group_stats[
                            r["產業"]
                        ]
                    )

                    keep, score = eval_num(
                        ratio,
                        gv,
                        "ge",
                        gm,
                        "同產業同步轉強%",
                        why,
                        score,
                        15
                    )

                    if keep:

                        keep, score = eval_num(
                            avg,
                            rov,
                            "ge",
                            rom,
                            "產業平均20日%",
                            why,
                            score,
                            15
                        )

                    if keep:

                        keep, score = eval_num(
                            r[
                                "歷史同月%"
                            ],
                            cyv,
                            "ge",
                            cym,
                            "歷史同月平均%",
                            why,
                            score
                        )

                    if keep:

                        x = r.to_dict()

                        x[
                            "群體同步%"
                        ] = ratio

                        x[
                            "產業20日%"
                        ] = avg

                        x[
                            "分數"
                        ] = score

                        x[
                            "為什麼抓到"
                        ] = (
                            " → ".join(why)
                            if why
                            else
                            "未被必要條件淘汰"
                        )

                        final.append(x)

                if final:

                    o = (
                        pd.DataFrame(final)
                        .sort_values(
                            [
                                "分數",
                                "代號"
                            ],
                            ascending=[
                                False,
                                True
                            ]
                        )
                    )

                    cols = [
                        "代號",
                        "名稱",
                        "市場",
                        "產業",
                        "現價",
                        "高點回落%",
                        "營收成長%",
                        "CAPEX成長%",
                        "合約負債%",
                        "事件",
                        "群體同步%",
                        "產業20日%",
                        "歷史同月%",
                        "分數",
                        "為什麼抓到"
                    ]

                    st.dataframe(
                        o[cols],
                        use_container_width=True,
                        hide_index=True
                    )

                else:

                    st.warning(
                        "群體性／輪動／循環的"
                        "必要條件淘汰了全部股票。"
                    )


with tabs[1]:

    code = st.text_input(
        "股票代號，例如 2330",
        key="single"
    ).strip()

    if st.button(
        "分析個股"
    ) and code:

        hit = pool[
            pool["代號"] == code
        ]

        if hit.empty:

            st.error(
                "股票池找不到這個代號。"
            )

        else:

            r = hit.iloc[0]

            d = price_history(
                r["symbol"]
            )

            tech = technical(
                d,
                6
            )

            fund = fundamentals(
                r["symbol"]
            )

            evs, titles = news_events(
                fund["新聞"]
            )

            st.subheader(
                f"{code} "
                f"{r['名稱']}｜"
                f"{r['市場']}｜"
                f"{r['產業']}"
            )

            if not d.empty:
                st.line_chart(
                    d["Close"]
                )

            detail = {
                "股本億":
                    r["股本億"],

                "市值億":
                    fund[
                        "市值億"
                    ],

                **tech,

                "營收成長%":
                    fund[
                        "營收成長"
                    ],

                "獲利成長%":
                    fund[
                        "獲利成長"
                    ],

                "毛利率%":
                    fund[
                        "毛利率"
                    ],

                "營益率%":
                    fund[
                        "營益率"
                    ],

                "CAPEX成長%":
                    fund[
                        "CAPEX成長"
                    ],

                "CAPEX/營收%":
                    fund[
                        "CAPEX營收比"
                    ],

                "合約負債成長%":
                    fund[
                        "合約負債成長"
                    ],

                "現金流改善":
                    fund[
                        "現金流改善"
                    ],

                "存貨變化%":
                    fund[
                        "存貨變化"
                    ],

                "應收變化%":
                    fund[
                        "應收變化"
                    ],

                "事件":
                    ",".join(evs)
            }

            st.dataframe(
                pd.DataFrame(
                    detail.items(),
                    columns=[
                        "項目",
                        "數值"
                    ]
                ),
                use_container_width=True,
                hide_index=True
            )

            if titles:

                st.dataframe(
                    pd.DataFrame({
                        "近期公開標題":
                            titles
                    }),
                    use_container_width=True,
                    hide_index=True
                )


with tabs[2]:

    st.subheader(
        "族群＋CB"
    )

    st.write(
        "先看族群同步轉強；"
        "CB 只提供 MOPS／櫃買中心官方入口核對。"
        "這版不從 HTML 猜 CB 公司代號，避免誤判。"
    )

    st.info(
        "CB 官方資料可查，"
        "但目前沒有採用我能確認可靠的"
        "結構化 CB 公司代號 API；"
        "因此不自動猜、不拿 CB 淘汰股票。"
    )

    st.link_button(
        "MOPS－國內轉換公司債",
        MOPS_CB
    )

    st.link_button(
        "櫃買中心－最近上櫃轉(交)換公司債",
        TPEX_CB
    )


with tabs[3]:

    st.subheader(
        "資料來源與健康檢查"
    )

    health = pd.DataFrame(
        [
            [
                "上市公司股票池",
                "TWSE OpenAPI",
                (
                    "正常"
                    if fetch_json(
                        TWSE_BASIC
                    )
                    else "目前不可讀"
                )
            ],
            [
                "上櫃公司股票池",
                "TPEx OpenAPI",
                (
                    "正常"
                    if fetch_json(
                        TPEX_BASIC
                    )
                    else "目前不可讀"
                )
            ],
            [
                "創新板辨識",
                "TWSE 最近上市公司",
                (
                    "正常"
                    if innovation_codes()
                    else "目前未辨識到"
                )
            ],
            [
                "CB",
                "MOPS / TPEx 官方頁",
                "官方頁可查；不做不可靠的自動代號猜測"
            ],
            [
                "歷史價格",
                "Yahoo Finance",
                "依個股即時連線"
            ],
            [
                "財務/新聞",
                "Yahoo Finance",
                "抓不到即顯示缺資料，不補 0"
            ],
        ],
        columns=[
            "資料",
            "來源",
            "狀態"
        ]
    )

    st.dataframe(
        health,
        use_container_width=True,
        hide_index=True
    )

    st.write(
        "群體性＝同產業內"
        "『20日上漲＋量能增加』公司比例；"
        "族群輪動＝同產業股票20日平均漲跌。"
    )

    st.write(
        "CB 自動提示只使用官方公開頁面"
        "能可靠辨識到的內容；"
        "無法可靠辨識時不做假判斷。"
    )

    st.caption(
        "頁面更新時間："
        + datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )
