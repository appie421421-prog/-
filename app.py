import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime

st.set_page_config(page_title="台股轉機雷達", layout="wide")
st.title("📡 台股轉機雷達")
st.caption("多邏輯選股：關閉＝不參與｜加分＝有就加分｜必要＝不符合就排除")

MODES = ["關閉", "加分", "必要"]


def mode(label, key, default="關閉"):
    return st.selectbox(
        label,
        MODES,
        index=MODES.index(default),
        key=key
    )


def num(v):
    try:
        return float(v)
    except:
        return np.nan


def series(x):
    if isinstance(x, pd.DataFrame):
        if x.shape[1] == 0:
            return pd.Series(dtype=float)
        x = x.iloc[:, 0]

    return pd.to_numeric(
        x,
        errors="coerce"
    ).dropna()


# =========================================================
# 自動判斷上市 / 上櫃
# =========================================================

@st.cache_data(ttl=86400, show_spinner=False)
def resolve_symbol(code):

    for suffix, market in [
        (".TW", "上市"),
        (".TWO", "上櫃")
    ]:

        try:

            df = yf.download(
                code + suffix,
                period="5d",
                progress=False,
                auto_adjust=False,
                threads=False,
                timeout=8
            )

            if not df.empty:
                return code + suffix, market

        except:
            pass

    return None, None


# =========================================================
# 2年行情
# =========================================================

@st.cache_data(ttl=3600, show_spinner=False)
def price_data(symbol):

    try:

        df = yf.download(
            symbol,
            period="2y",
            progress=False,
            auto_adjust=False,
            threads=False,
            timeout=12
        )

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        if df.empty:
            return pd.DataFrame()

        return df.dropna(
            subset=["Close"]
        )

    except:

        return pd.DataFrame()


# =========================================================
# 基本面
# =========================================================

@st.cache_data(ttl=21600, show_spinner=False)
def fundamentals(symbol):

    result = {
        "name": symbol.split(".")[0],
        "market_cap": np.nan,
        "capital": np.nan,
        "rev_growth": np.nan,
        "earn_growth": np.nan,
        "gross_margin": np.nan,
        "op_margin": np.nan,
        "capex_growth": np.nan,
        "contract_growth": np.nan,
        "industry": "",
        "sector": "",
        "cashflow_improve": False
    }

    try:

        ticker = yf.Ticker(symbol)

        # -----------------------------------------
        # 公司基本面
        # -----------------------------------------

        try:

            info = ticker.get_info()

            result["name"] = (
                info.get("shortName")
                or info.get("longName")
                or result["name"]
            )

            result["market_cap"] = (
                num(info.get("marketCap"))
                / 1e8
            )

            shares = num(
                info.get("sharesOutstanding")
            )

            if pd.notna(shares):

                result["capital"] = (
                    shares
                    * 10
                    / 1e8
                )

            result["rev_growth"] = (
                num(info.get("revenueGrowth"))
                * 100
            )

            result["earn_growth"] = (
                num(info.get("earningsGrowth"))
                * 100
            )

            result["gross_margin"] = (
                num(info.get("grossMargins"))
                * 100
            )

            result["op_margin"] = (
                num(info.get("operatingMargins"))
                * 100
            )

            result["industry"] = str(
                info.get("industry") or ""
            )

            result["sector"] = str(
                info.get("sector") or ""
            )

        except:
            pass

        # -----------------------------------------
        # CAPEX / 現金流
        # -----------------------------------------

        try:

            cf = ticker.quarterly_cashflow

            if not cf.empty:

                labels = [
                    str(i).lower()
                    for i in cf.index
                ]

                capex_rows = [
                    i
                    for i, x in enumerate(labels)
                    if "capital expenditure" in x
                ]

                if (
                    capex_rows
                    and cf.shape[1] >= 5
                ):

                    values = pd.to_numeric(
                        cf.iloc[capex_rows[0]],
                        errors="coerce"
                    ).abs().dropna()

                    if (
                        len(values) >= 5
                        and values.iloc[4] != 0
                    ):

                        result["capex_growth"] = (
                            values.iloc[0]
                            / values.iloc[4]
                            - 1
                        ) * 100

                operating_rows = [
                    i
                    for i, x in enumerate(labels)
                    if (
                        "operating cash flow" in x
                        or
                        "total cash from operating" in x
                    )
                ]

                if (
                    operating_rows
                    and cf.shape[1] >= 2
                ):

                    values = pd.to_numeric(
                        cf.iloc[operating_rows[0]],
                        errors="coerce"
                    ).dropna()

                    if len(values) >= 2:

                        result["cashflow_improve"] = (
                            values.iloc[0]
                            >
                            values.iloc[1]
                        )

        except:
            pass

        # -----------------------------------------
        # 合約負債
        # -----------------------------------------

        try:

            bs = ticker.quarterly_balance_sheet

            if not bs.empty:

                labels = [
                    str(i).lower()
                    for i in bs.index
                ]

                rows = [
                    i
                    for i, x in enumerate(labels)
                    if "contract liabil" in x
                ]

                if (
                    rows
                    and bs.shape[1] >= 2
                ):

                    values = pd.to_numeric(
                        bs.iloc[rows[0]],
                        errors="coerce"
                    ).dropna()

                    if (
                        len(values) >= 2
                        and values.iloc[1] != 0
                    ):

                        result["contract_growth"] = (
                            values.iloc[0]
                            / values.iloc[1]
                            - 1
                        ) * 100

        except:
            pass

    except:
        pass

    return result


# =========================================================
# 技術面
# =========================================================

def tech(df, months):

    close = series(df["Close"])
    high = series(df["High"])
    low = series(df["Low"])
    volume = series(df["Volume"])

    if len(close) < 20:
        return {}

    price = float(close.iloc[-1])

    peak = float(high.max())

    drawdown = (
        (peak - price)
        / peak
        * 100
        if peak
        else np.nan
    )

    # -----------------------------------------
    # 築底區間
    # -----------------------------------------

    days = min(
        len(df),
        max(
            42,
            months * 21
        )
    )

    recent = df.tail(days)

    recent_high = num(
        series(
            recent["High"]
        ).max()
    )

    recent_low = num(
        series(
            recent["Low"]
        ).min()
    )

    base_range = (
        (
            recent_high
            - recent_low
        )
        / recent_low
        * 100
        if recent_low
        else np.nan
    )

    # -----------------------------------------
    # MA60
    # -----------------------------------------

    ma60 = (
        close
        .rolling(60)
        .mean()
        .iloc[-1]
        if len(close) >= 60
        else np.nan
    )

    ma_distance = (
        (
            price
            / ma60
            - 1
        )
        * 100
        if pd.notna(ma60)
        and ma60
        else np.nan
    )

    # -----------------------------------------
    # 量能
    # -----------------------------------------

    volume20 = (
        volume
        .tail(20)
        .mean()
    )

    volume60 = (
        volume
        .tail(60)
        .mean()
    )

    volume_growth = (
        (
            volume20
            / volume60
            - 1
        )
        * 100
        if len(volume) >= 60
        and volume60
        else np.nan
    )

    # -----------------------------------------
    # 防止把急跌當築底
    # -----------------------------------------

    change20 = (
        (
            price
            / close.iloc[-20]
            - 1
        )
        * 100
        if len(close) >= 20
        and close.iloc[-20]
        else np.nan
    )

    return {
        "price": price,
        "drawdown": drawdown,
        "base": base_range,
        "ma60": ma_distance,
        "volume": volume_growth,
        "change20": change20
    }


# =========================================================
# 通用條件判斷
# =========================================================

def evaluate(
    label,
    value,
    threshold,
    direction,
    selected_mode,
    score,
    reasons
):

    if selected_mode == "關閉":
        return True, score

    if pd.isna(value):

        if selected_mode == "必要":
            return False, score

        return True, score

    if direction == "ge":

        ok = (
            value
            >= threshold
        )

    else:

        ok = (
            value
            <= threshold
        )

    if ok:

        if selected_mode == "加分":
            score += 10

        reasons.append(
            f"{label} {value:.1f}"
        )

        return True, score

    if selected_mode == "必要":
        return False, score

    return True, score


# =========================================================
# 側邊欄
# =========================================================

with st.sidebar:

    st.header("🎛️ 多邏輯條件")

    st.caption(
        "每一項都可以獨立使用"
    )

    market_filter = st.multiselect(
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

    st.divider()

    # ==========================================
    # 價格邏輯
    # ==========================================

    st.subheader("價格／築底")

    drawdown_mode = mode(
        "高點回落",
        "drawdown_mode",
        "必要"
    )

    drawdown_threshold = st.selectbox(
        "跌幅門檻 %",
        [
            0,
            30,
            40,
            50,
            60,
            70
        ],
        index=3
    )

    base_mode = mode(
        "築底／收斂",
        "base_mode",
        "必要"
    )

    base_months = st.selectbox(
        "觀察月數",
        [
            2,
            3,
            6,
            12,
            18,
            24
        ],
        index=2
    )

    base_threshold = st.selectbox(
        "最大區間 %",
        [
            0,
            15,
            20,
            25,
            30,
            40,
            50
        ],
        index=2
    )

    ma_mode = mode(
        "接近 MA60",
        "ma_mode",
        "加分"
    )

    ma_threshold = st.selectbox(
        "MA60 距離 ±%",
        [
            0,
            5,
            10,
            15,
            20
        ],
        index=2
    )

    volume_mode = mode(
        "底部放量",
        "volume_mode",
        "加分"
    )

    volume_threshold = st.selectbox(
        "放量門檻 %",
        [
            0,
            10,
            20,
            30,
            50,
            100
        ],
        index=3
    )

    st.divider()

    # ==========================================
    # 基本面邏輯
    # ==========================================

    st.subheader("基本面轉折")

    revenue_mode = mode(
        "營收成長",
        "revenue_mode",
        "加分"
    )

    revenue_threshold = st.selectbox(
        "營收成長門檻 %",
        [
            0,
            5,
            10,
            20,
            30,
            50
        ],
        index=0
    )

    earnings_mode = mode(
        "獲利成長",
        "earnings_mode",
        "加分"
    )

    earnings_threshold = st.selectbox(
        "獲利成長門檻 %",
        [
            0,
            5,
            10,
            20,
            30,
            50
        ],
        index=0
    )

    cashflow_mode = mode(
        "營業現金流改善",
        "cashflow_mode",
        "加分"
    )

    st.divider()

    # ==========================================
    # 擴張型
    # ==========================================

    st.subheader("擴張／訂單")

    capex_mode = mode(
        "CAPEX增加",
        "capex_mode",
        "加分"
    )

    capex_threshold = st.selectbox(
        "CAPEX年增門檻 %",
        [
            0,
            10,
            20,
            30,
            50,
            100
        ],
        index=3
    )

    contract_mode = mode(
        "合約負債增加",
        "contract_mode",
        "加分"
    )

    contract_threshold = st.selectbox(
        "合約負債成長門檻 %",
        [
            0,
            10,
            20,
            30,
            50
        ],
        index=2
    )

    st.divider()

    # ==========================================
    # 公司大小
    # ==========================================

    st.subheader("公司大小")

    size_mode = mode(
        "中小型股",
        "size_mode",
        "加分"
    )

    max_market_cap = st.number_input(
        "市值上限（億）",
        value=500.0
    )

    max_capital = st.number_input(
        "股本上限（億）",
        value=50.0
    )

    st.divider()

    # ==========================================
    # 事件／群體型
    # ==========================================

    st.subheader("事件／群體")

    cb_mode = mode(
        "CB事件",
        "cb_mode",
        "關閉"
    )

    event_mode = mode(
        "合作／擴產／新客戶",
        "event_mode",
        "關閉"
    )

    group_mode = mode(
        "群體性",
        "group_mode",
        "關閉"
    )

    rotation_mode = mode(
        "族群輪動",
        "rotation_mode",
        "關閉"
    )

    cycle_mode = mode(
        "歷史循環",
        "cycle_mode",
        "關閉"
    )


# =========================================================
# 頁面
# =========================================================

tab1, tab2, tab3, tab4 = st.tabs(
    [
        "🚨 全市場雷達",
        "🔍 個股完整檢查",
        "🧠 邏輯說明",
        "⭐ 自選觀察"
    ]
)


# =========================================================
# 全市場雷達
# =========================================================

with tab1:

    st.subheader(
        "全市場多邏輯雷達"
    )

    c1, c2 = st.columns(2)

    start_code = int(
        c1.number_input(
            "起始代號",
            1101,
            9999,
            1101,
            100
        )
    )

    scan_count = c2.selectbox(
        "掃描數量",
        [
            20,
            50,
            100,
            200,
            500
        ],
        index=1
    )

    if st.button(
        "🚀 開始雷達掃描",
        type="primary"
    ):

        rows = []

        progress = st.progress(0)

        status = st.empty()

        codes = range(
            start_code,
            min(
                10000,
                start_code
                + scan_count
            )
        )

        for index, number in enumerate(codes):

            code = str(number)

            status.write(
                f"掃描 {code}"
            )

            symbol, market = (
                resolve_symbol(code)
            )

            if (
                symbol
                and
                market
                in market_filter
            ):

                prices = price_data(
                    symbol
                )

                if len(prices) >= 60:

                    technical = tech(
                        prices,
                        base_months
                    )

                    fundamental = fundamentals(
                        symbol
                    )

                    keep = True

                    score = 0

                    reasons = []

                    # ==================================
                    # 跌幅
                    # ==================================

                    keep, score = evaluate(
                        "高點回落%",
                        technical.get(
                            "drawdown",
                            np.nan
                        ),
                        drawdown_threshold,
                        "ge",
                        drawdown_mode,
                        score,
                        reasons
                    )

                    # ==================================
                    # 築底
                    # ==================================

                    if (
                        keep
                        and
                        base_mode
                        != "關閉"
                    ):

                        value = technical.get(
                            "base",
                            np.nan
                        )

                        ok = (
                            pd.notna(value)
                            and
                            (
                                base_threshold == 0
                                or
                                value
                                <= base_threshold
                            )
                            and
                            technical.get(
                                "change20",
                                -99
                            )
                            > -15
                        )

                        if ok:

                            if (
                                base_mode
                                == "加分"
                            ):
                                score += 10

                            reasons.append(
                                f"{base_months}月築底 "
                                f"{value:.1f}%"
                            )

                        elif (
                            base_mode
                            == "必要"
                        ):

                            keep = False

                    # ==================================
                    # MA60
                    # ==================================

                    if (
                        keep
                        and
                        ma_mode
                        != "關閉"
                    ):

                        value = abs(
                            technical.get(
                                "ma60",
                                np.nan
                            )
                        )

                        keep, score = evaluate(
                            "距MA60%",
                            value,
                            ma_threshold,
                            "le",
                            ma_mode,
                            score,
                            reasons
                        )

                    # ==================================
                    # 量能
                    # ==================================

                    if keep:

                        keep, score = evaluate(
                            "量能變化%",
                            technical.get(
                                "volume",
                                np.nan
                            ),
                            volume_threshold,
                            "ge",
                            volume_mode,
                            score,
                            reasons
                        )

                    # ==================================
                    # 營收
                    # ==================================

                    if keep:

                        keep, score = evaluate(
                            "營收成長%",
                            fundamental[
                                "rev_growth"
                            ],
                            revenue_threshold,
                            "ge",
                            revenue_mode,
                            score,
                            reasons
                        )

                    # ==================================
                    # 獲利
                    # ==================================

                    if keep:

                        keep, score = evaluate(
                            "獲利成長%",
                            fundamental[
                                "earn_growth"
                            ],
                            earnings_threshold,
                            "ge",
                            earnings_mode,
                            score,
                            reasons
                        )

                    # ==================================
                    # CAPEX
                    # ==================================

                    if keep:

                        keep, score = evaluate(
                            "CAPEX成長%",
                            fundamental[
                                "capex_growth"
                            ],
                            capex_threshold,
                            "ge",
                            capex_mode,
                            score,
                            reasons
                        )

                    # ==================================
                    # 合約負債
                    # ==================================

                    if keep:

                        keep, score = evaluate(
                            "合約負債成長%",
                            fundamental[
                                "contract_growth"
                            ],
                            contract_threshold,
                            "ge",
                            contract_mode,
                            score,
                            reasons
                        )

                    # ==================================
                    # 現金流
                    # ==================================

                    if (
                        keep
                        and
                        cashflow_mode
                        != "關閉"
                    ):

                        ok = fundamental[
                            "cashflow_improve"
                        ]

                        if ok:

                            if (
                                cashflow_mode
                                == "加分"
                            ):
                                score += 10

                            reasons.append(
                                "營業現金流改善"
                            )

                        elif (
                            cashflow_mode
                            == "必要"
                        ):

                            keep = False

                    # ==================================
                    # 中小型股
                    # ==================================

                    if (
                        keep
                        and
                        size_mode
                        != "關閉"
                    ):

                        market_cap = fundamental[
                            "market_cap"
                        ]

                        capital = fundamental[
                            "capital"
                        ]

                        known = (
                            pd.notna(
                                market_cap
                            )
                            or
                            pd.notna(
                                capital
                            )
                        )

                        ok = (
                            (
                                pd.isna(
                                    market_cap
                                )
                                or
                                market_cap
                                <= max_market_cap
                            )
                            and
                            (
                                pd.isna(
                                    capital
                                )
                                or
                                capital
                                <= max_capital
                            )
                        )

                        if (
                            known
                            and
                            ok
                        ):

                            if (
                                size_mode
                                == "加分"
                            ):
                                score += 10

                            reasons.append(
                                "中小市值／低股本"
                            )

                        elif (
                            size_mode
                            == "必要"
                        ):

                            keep = False

                    # ==================================
                    # 尚未有可靠結構化資料的項目
                    # 不准把「未知」當成「符合」
                    # ==================================

                    unavailable = [
                        (
                            "CB",
                            cb_mode
                        ),
                        (
                            "合作／擴產／新客戶",
                            event_mode
                        ),
                        (
                            "群體性",
                            group_mode
                        ),
                        (
                            "族群輪動",
                            rotation_mode
                        ),
                        (
                            "歷史循環",
                            cycle_mode
                        )
                    ]

                    for (
                        label,
                        selected_mode
                    ) in unavailable:

                        if (
                            selected_mode
                            == "必要"
                        ):
                            keep = False

                    # ==================================
                    # 最終結果
                    # ==================================

                    if keep:

                        rows.append(
                            {
                                "代號":
                                    code,

                                "名稱":
                                    fundamental[
                                        "name"
                                    ],

                                "市場":
                                    market,

                                "現價":
                                    round(
                                        technical[
                                            "price"
                                        ],
                                        2
                                    ),

                                "跌幅":
                                    f"{technical['drawdown']:.1f}%",

                                "築底區間":
                                    f"{technical['base']:.1f}%",

                                "營收成長":
                                    (
                                        ""
                                        if
                                        pd.isna(
                                            fundamental[
                                                "rev_growth"
                                            ]
                                        )
                                        else
                                        f"{fundamental['rev_growth']:.1f}%"
                                    ),

                                "獲利成長":
                                    (
                                        ""
                                        if
                                        pd.isna(
                                            fundamental[
                                                "earn_growth"
                                            ]
                                        )
                                        else
                                        f"{fundamental['earn_growth']:.1f}%"
                                    ),

                                "CAPEX":
                                    (
                                        ""
                                        if
                                        pd.isna(
                                            fundamental[
                                                "capex_growth"
                                            ]
                                        )
                                        else
                                        f"{fundamental['capex_growth']:.1f}%"
                                    ),

                                "合約負債":
                                    (
                                        ""
                                        if
                                        pd.isna(
                                            fundamental[
                                                "contract_growth"
                                            ]
                                        )
                                        else
                                        f"{fundamental['contract_growth']:.1f}%"
                                    ),

                                "分數":
                                    score,

                                "為什麼抓到":
                                    (
                                        " → ".join(
                                            reasons
                                        )
                                        or
                                        "目前啟用條件皆未限制"
                                    )
                            }
                        )

            progress.progress(
                (
                    index + 1
                )
                / scan_count
            )

        status.empty()

        if rows:

            result = pd.DataFrame(
                rows
            )

            result = result.sort_values(
                "分數",
                ascending=False
            )

            st.success(
                f"找到 {len(result)} 檔"
            )

            st.dataframe(
                result,
                use_container_width=True,
                hide_index=True
            )

        else:

            st.warning(
                "本次沒有符合「必要」條件的股票。"
                "不想限制的條件請改成「關閉」。"
            )


# =========================================================
# 個股完整檢查
# =========================================================

with tab2:

    st.subheader(
        "單一股票完整檢查"
    )

    stock_code = st.text_input(
        "股票代號，例如 2330、6488"
    )

    if st.button(
        "分析這一檔"
    ):

        stock_code = stock_code.strip()

        symbol, market = (
            resolve_symbol(
                stock_code
            )
        )

        if not symbol:

            st.error(
                "找不到上市／上櫃行情"
            )

        else:

            prices = price_data(
                symbol
            )

            fundamental = fundamentals(
                symbol
            )

            if prices.empty:

                st.error(
                    "抓不到行情"
                )

            else:

                technical = tech(
                    prices,
                    base_months
                )

                st.header(
                    f"{stock_code} "
                    f"{fundamental['name']}｜"
                    f"{market}"
                )

                c1, c2, c3, c4 = (
                    st.columns(4)
                )

                c1.metric(
                    "現價",
                    f"{technical['price']:.2f}"
                )

                c2.metric(
                    "2年高點回落",
                    f"{technical['drawdown']:.1f}%"
                )

                c3.metric(
                    "MA60距離",
                    (
                        f"{technical['ma60']:+.1f}%"
                        if
                        pd.notna(
                            technical[
                                "ma60"
                            ]
                        )
                        else
                        "缺資料"
                    )
                )

                c4.metric(
                    "量能變化",
                    (
                        f"{technical['volume']:+.1f}%"
                        if
                        pd.notna(
                            technical[
                                "volume"
                            ]
                        )
                        else
                        "缺資料"
                    )
                )

                st.line_chart(
                    prices["Close"]
                )

                details = pd.DataFrame(
                    [
                        [
                            "市場",
                            market
                        ],
                        [
                            "產業",
                            fundamental[
                                "industry"
                            ]
                            or
                            fundamental[
                                "sector"
                            ]
                            or
                            "缺資料"
                        ],
                        [
                            "市值（億）",
                            fundamental[
                                "market_cap"
                            ]
                        ],
                        [
                            "股本估算（億）",
                            fundamental[
                                "capital"
                            ]
                        ],
                        [
                            "營收成長%",
                            fundamental[
                                "rev_growth"
                            ]
                        ],
                        [
                            "獲利成長%",
                            fundamental[
                                "earn_growth"
                            ]
                        ],
                        [
                            "毛利率%",
                            fundamental[
                                "gross_margin"
                            ]
                        ],
                        [
                            "營業利益率%",
                            fundamental[
                                "op_margin"
                            ]
                        ],
                        [
                            "CAPEX成長%",
                            fundamental[
                                "capex_growth"
                            ]
                        ],
                        [
                            "合約負債成長%",
                            fundamental[
                                "contract_growth"
                            ]
                        ],
                        [
                            "營業現金流改善",
                            (
                                "是"
                                if
                                fundamental[
                                    "cashflow_improve"
                                ]
                                else
                                "否／缺資料"
                            )
                        ]
                    ],
                    columns=[
                        "雷達項目",
                        "目前值"
                    ]
                )

                st.dataframe(
                    details,
                    use_container_width=True,
                    hide_index=True
                )

                st.caption(
                    "資料抓取時間："
                    + datetime.now().strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                )


# =========================================================
# 邏輯說明
# =========================================================

with tab3:

    st.subheader(
        "多套選股邏輯"
    )

    st.markdown(
        """
### 關閉
完全不參與判斷。

### 加分
有符合就加分，沒有符合不淘汰。

### 必要
一定要符合，否則直接排除。

---

因此可以分開跑：

**邏輯 A｜重跌築底**

跌幅＝必要  
築底＝必要  
其他＝關閉或加分

**邏輯 B｜基本面轉折**

跌幅＝關閉  
築底＝關閉  
營收＝必要  
獲利＝加分  
現金流＝加分

**邏輯 C｜公司正在擴張**

跌幅＝關閉  
CAPEX＝必要  
合約負債＝加分  
營收＝加分

**邏輯 D｜小公司開始有變化**

中小型股＝必要  
營收＝加分  
CAPEX＝加分  
量能＝加分

**邏輯 E｜未來群體雷達**

群體性  
族群輪動  
供應鏈  
同產業同步變化

---

目前真正參與程式運算：

- 2年高點回落
- 築底／波動收斂
- 防止一路急跌被誤判築底
- MA60
- 底部量能
- 市值
- 股本
- 營收成長
- 獲利成長
- 毛利率
- 營業利益率
- 營業現金流
- CAPEX
- 合約負債

CB、合作／新客戶、群體性、族群輪動、歷史循環，
目前沒有可靠資料時不會亂填成「符合」。
"""
    )


# =========================================================
# 自選股
# =========================================================

with tab4:

    st.subheader(
        "⭐ 自選觀察"
    )

    watchlist = st.text_area(
        "輸入股票代號，用逗號分隔，例如：2330,6488,2317"
    )

    if st.button(
        "更新自選股"
    ):

        output = []

        codes = [
            x.strip()
            for x in watchlist
            .replace(
                "，",
                ","
            )
            .split(",")
            if x.strip()
        ]

        for code in codes:

            symbol, market = (
                resolve_symbol(
                    code
                )
            )

            if symbol:

                prices = price_data(
                    symbol
                )

                fundamental = fundamentals(
                    symbol
                )

                if not prices.empty:

                    technical = tech(
                        prices,
                        base_months
                    )

                    output.append(
                        {
                            "代號":
                                code,

                            "名稱":
                                fundamental[
                                    "name"
                                ],

                            "市場":
                                market,

                            "現價":
                                round(
                                    technical[
                                        "price"
                                    ],
                                    2
                                ),

                            "2年回落%":
                                round(
                                    technical[
                                        "drawdown"
                                    ],
                                    1
                                ),

                            "營收成長%":
                                fundamental[
                                    "rev_growth"
                                ],

                            "獲利成長%":
                                fundamental[
                                    "earn_growth"
                                ],

                            "CAPEX成長%":
                                fundamental[
                                    "capex_growth"
                                ],

                            "合約負債成長%":
                                fundamental[
                                    "contract_growth"
                                ]
                        }
                    )

        if output:

            st.dataframe(
                pd.DataFrame(
                    output
                ),
                use_container_width=True,
                hide_index=True
            )

        else:

            st.warning(
                "沒有可顯示的自選股資料"
            )
