import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np

st.set_page_config(
    page_title="台股變化雷達",
    layout="wide"
)

st.title("📡 台股變化雷達")
st.caption(
    "上市＋上櫃＋創新板｜重跌築底 × 量價變化 × 基本面轉折"
)


# =========================================================
# 基本工具
# =========================================================

def clean_series(data):

    if isinstance(data, pd.DataFrame):
        if data.shape[1] == 0:
            return pd.Series(dtype=float)
        data = data.iloc[:, 0]

    return pd.to_numeric(
        data,
        errors="coerce"
    ).dropna()


# =========================================================
# 創新板公司辨識
# =========================================================

@st.cache_data(
    ttl=86400,
    show_spinner=False
)
def get_innovation_codes():

    innovation_codes = set()

    try:

        url = (
            "https://www.twse.com.tw/"
            "company/newlisting?"
            "response=html"
        )

        tables = pd.read_html(url)

        for table in tables:

            for _, row in table.iterrows():

                row_text = " ".join(
                    [
                        str(x)
                        for x in row.tolist()
                    ]
                )

                if "創新板" in row_text:

                    for value in row.tolist():

                        value = str(
                            value
                        ).strip()

                        if (
                            len(value) == 4
                            and
                            value.isdigit()
                        ):

                            innovation_codes.add(
                                value
                            )

                            break

    except Exception:
        pass


    # 官方上市資料名稱若帶「創」
    try:

        api = (
            "https://openapi.twse.com.tw/"
            "v1/opendata/t187ap03_L"
        )

        df = pd.read_json(api)

        if not df.empty:

            code_columns = [
                "公司代號",
                "股票代號",
                "證券代號"
            ]

            name_columns = [
                "公司簡稱",
                "公司名稱"
            ]

            code_col = None
            name_col = None

            for col in code_columns:

                if col in df.columns:
                    code_col = col
                    break

            for col in name_columns:

                if col in df.columns:
                    name_col = col
                    break

            if (
                code_col is not None
                and
                name_col is not None
            ):

                for _, row in df.iterrows():

                    code = str(
                        row[code_col]
                    ).strip()

                    name = str(
                        row[name_col]
                    ).strip()

                    if (
                        len(code) == 4
                        and
                        code.isdigit()
                        and
                        (
                            "-創" in name
                            or
                            "KY創" in name
                            or
                            "*-創" in name
                        )
                    ):

                        innovation_codes.add(
                            code
                        )

    except Exception:
        pass


    return innovation_codes


# =========================================================
# 判斷上市 / 上櫃
# =========================================================

@st.cache_data(
    ttl=86400,
    show_spinner=False
)
def resolve_symbol(code):

    innovation_codes = (
        get_innovation_codes()
    )


    # 先試上市
    try:

        symbol = (
            code + ".TW"
        )

        df = yf.download(
            symbol,
            period="5d",
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False,
            timeout=8
        )

        if not df.empty:

            if (
                code
                in innovation_codes
            ):

                return (
                    symbol,
                    "創新板"
                )

            return (
                symbol,
                "上市"
            )

    except Exception:
        pass


    # 再試上櫃
    try:

        symbol = (
            code + ".TWO"
        )

        df = yf.download(
            symbol,
            period="5d",
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False,
            timeout=8
        )

        if not df.empty:

            return (
                symbol,
                "上櫃"
            )

    except Exception:
        pass


    return None, None


# =========================================================
# 股價
# =========================================================

@st.cache_data(
    ttl=3600,
    show_spinner=False
)
def get_price(symbol):

    try:

        df = yf.download(
            symbol,
            period="2y",
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False,
            timeout=12
        )

        if df.empty:
            return pd.DataFrame()


        if isinstance(
            df.columns,
            pd.MultiIndex
        ):

            df.columns = (
                df.columns
                .get_level_values(0)
            )


        required = [
            "Close",
            "High",
            "Low",
            "Volume"
        ]

        for col in required:

            if col not in df.columns:
                return pd.DataFrame()


        return df.dropna(
            subset=["Close"]
        )


    except Exception:

        return pd.DataFrame()


# =========================================================
# 公司資料
# =========================================================

@st.cache_data(
    ttl=86400,
    show_spinner=False
)
def get_company_info(symbol):

    code = (
        symbol
        .split(".")[0]
    )

    name = code

    market_cap = np.nan

    capital = np.nan


    try:

        ticker = yf.Ticker(
            symbol
        )


        try:

            fast_info = (
                ticker.fast_info
            )

            value = (
                fast_info.get(
                    "market_cap",
                    None
                )
            )

            if value:

                market_cap = (
                    float(value)
                    / 1e8
                )

        except Exception:
            pass


        try:

            info = (
                ticker.get_info()
            )

            name = (
                info.get(
                    "shortName"
                )
                or
                info.get(
                    "longName"
                )
                or
                code
            )


            shares = (
                info.get(
                    "sharesOutstanding"
                )
            )


            if shares:

                capital = (
                    float(shares)
                    * 10
                    / 1e8
                )

        except Exception:
            pass


    except Exception:
        pass


    return (
        name,
        market_cap,
        capital
    )


# =========================================================
# 技術指標
# =========================================================

def calculate_metrics(
    hist,
    base_months
):

    close = clean_series(
        hist["Close"]
    )

    high = clean_series(
        hist["High"]
    )

    low = clean_series(
        hist["Low"]
    )

    volume = clean_series(
        hist["Volume"]
    )


    if (
        close.empty
        or
        high.empty
        or
        low.empty
    ):

        return None


    current_price = float(
        close.iloc[-1]
    )


    highest_price = float(
        high.max()
    )


    if highest_price > 0:

        drawdown = (
            (
                highest_price
                - current_price
            )
            / highest_price
            * 100
        )

    else:

        drawdown = np.nan


    # ==========================================
    # MA60
    # ==========================================

    if len(close) >= 60:

        ma60 = (
            close
            .rolling(60)
            .mean()
            .iloc[-1]
        )

        if (
            pd.notna(ma60)
            and
            ma60 != 0
        ):

            ma60_distance = (
                (
                    current_price
                    / ma60
                )
                - 1
            ) * 100

        else:

            ma60_distance = np.nan

    else:

        ma60_distance = np.nan


    # ==========================================
    # 週MA20
    # ==========================================

    weekly = (
        close
        .resample("W")
        .last()
    )

    if len(weekly) >= 20:

        weekly_ma20 = (
            weekly
            .rolling(20)
            .mean()
            .iloc[-1]
        )

        weekly_ma20_distance = (
            (
                current_price
                / weekly_ma20
            )
            - 1
        ) * 100

    else:

        weekly_ma20_distance = np.nan


    # ==========================================
    # 月MA20
    # ==========================================

    monthly = (
        close
        .resample("ME")
        .last()
    )

    if len(monthly) >= 20:

        monthly_ma20 = (
            monthly
            .rolling(20)
            .mean()
            .iloc[-1]
        )

        monthly_ma20_distance = (
            (
                current_price
                / monthly_ma20
            )
            - 1
        ) * 100

    else:

        monthly_ma20_distance = np.nan


    # ==========================================
    # 量能
    # ==========================================

    if len(volume) >= 60:

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

        if volume60 != 0:

            volume_change = (
                (
                    volume20
                    / volume60
                )
                - 1
            ) * 100

        else:

            volume_change = np.nan

    else:

        volume_change = np.nan


    # ==========================================
    # 築底
    # ==========================================

    days = min(
        len(hist),
        max(
            42,
            int(
                base_months
                * 21
            )
        )
    )


    recent = (
        hist
        .tail(days)
    )


    recent_high = float(
        clean_series(
            recent["High"]
        ).max()
    )

    recent_low = float(
        clean_series(
            recent["Low"]
        ).min()
    )


    if recent_low > 0:

        base_range = (
            (
                recent_high
                - recent_low
            )
            / recent_low
            * 100
        )

    else:

        base_range = np.nan


    # ==========================================
    # 防止把急跌當築底
    # ==========================================

    change20 = 0.0


    if len(close) >= 20:

        old_price = float(
            close.iloc[-20]
        )

        if old_price != 0:

            change20 = (
                (
                    current_price
                    / old_price
                )
                - 1
            ) * 100


    return {
        "price":
            current_price,

        "drawdown":
            drawdown,

        "ma60":
            ma60_distance,

        "weekly_ma20":
            weekly_ma20_distance,

        "monthly_ma20":
            monthly_ma20_distance,

        "volume":
            volume_change,

        "base_range":
            base_range,

        "change20":
            change20
    }


# =========================================================
# 側邊欄
# =========================================================

with st.sidebar:

    st.header(
        "⚙️ 糖球預設策略"
    )


    drawdown_threshold = (
        st.selectbox(
            "高點回落 (%)",
            [
                30,
                40,
                50,
                60,
                70
            ],
            index=2
        )
    )


    base_months = (
        st.selectbox(
            "築底觀察期（月）",
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
    )


    contraction_pct = (
        st.slider(
            "築底區間最大波動 (%)",
            10,
            60,
            20,
            5
        )
    )


    volume_threshold = (
        st.slider(
            "底部量能增加 (%)",
            0,
            100,
            30,
            5
        )
    )


    max_market_cap = (
        st.number_input(
            "市值上限（億元）",
            value=500.0,
            step=50.0
        )
    )


    max_capital = (
        st.number_input(
            "股本上限（億元）",
            value=50.0,
            step=10.0
        )
    )


    market_filter = (
        st.multiselect(
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
    )


# =========================================================
# 分頁
# =========================================================

tab1, tab2, tab3 = st.tabs(
    [
        "🔎 雷達掃描",
        "📊 個股檢查",
        "🧭 32項雷達"
    ]
)


# =========================================================
# 雷達掃描
# =========================================================

with tab1:

    st.subheader(
        "上市＋上櫃＋創新板雷達"
    )


    col1, col2 = (
        st.columns(2)
    )


    with col1:

        start_code = (
            st.number_input(
                "起始股票代號",
                min_value=1101,
                max_value=9999,
                value=1101,
                step=100
            )
        )


    with col2:

        scan_count = (
            st.selectbox(
                "這次掃描數量",
                [
                    20,
                    50,
                    100,
                    200,
                    500
                ],
                index=1
            )
        )


    if st.button(
        "🚀 開始掃描",
        type="primary"
    ):

        start = int(
            start_code
        )

        end = min(
            10000,
            start
            + int(scan_count)
        )


        codes = [
            str(code)
            for code
            in range(
                start,
                end
            )
        ]


        progress = (
            st.progress(0)
        )

        status = (
            st.empty()
        )

        results = []

        valid_stocks = 0


        for index, code in enumerate(
            codes
        ):

            status.write(
                f"正在檢查 {code}..."
            )


            symbol, market = (
                resolve_symbol(
                    code
                )
            )


            if (
                symbol
                and
                market
                in market_filter
            ):

                hist = (
                    get_price(
                        symbol
                    )
                )


                if len(hist) >= 60:

                    valid_stocks += 1


                    data = (
                        calculate_metrics(
                            hist,
                            base_months
                        )
                    )


                    if data is None:

                        progress.progress(
                            (
                                index + 1
                            )
                            / len(codes)
                        )

                        continue


                    (
                        company_name,
                        market_cap,
                        capital
                    ) = (
                        get_company_info(
                            symbol
                        )
                    )


                    drawdown_ok = (
                        pd.notna(
                            data[
                                "drawdown"
                            ]
                        )
                        and
                        data[
                            "drawdown"
                        ]
                        >=
                        drawdown_threshold
                    )


                    base_ok = (
                        pd.notna(
                            data[
                                "base_range"
                            ]
                        )
                        and
                        data[
                            "base_range"
                        ]
                        <=
                        contraction_pct
                        and
                        data[
                            "change20"
                        ]
                        >
                        -15
                    )


                    score = 0

                    reasons = []


                    if drawdown_ok:

                        reasons.append(
                            "2年高點回落 "
                            f"{data['drawdown']:.1f}%"
                        )


                    if base_ok:

                        reasons.append(
                            f"{base_months}月"
                            "築底區間 "
                            f"{data['base_range']:.1f}%"
                        )


                    if (
                        pd.notna(
                            data["ma60"]
                        )
                        and
                        abs(
                            data["ma60"]
                        )
                        <= 10
                    ):

                        score += 15

                        reasons.append(
                            "距MA60 "
                            f"{data['ma60']:+.1f}%"
                        )


                    if (
                        pd.notna(
                            data["volume"]
                        )
                        and
                        data["volume"]
                        >=
                        volume_threshold
                    ):

                        score += 20

                        reasons.append(
                            "量能增加 "
                            f"{data['volume']:+.1f}%"
                        )


                    if (
                        pd.notna(
                            market_cap
                        )
                        and
                        market_cap
                        <=
                        max_market_cap
                    ):

                        score += 10

                        reasons.append(
                            "市值 "
                            f"{market_cap:.1f}億"
                        )


                    if (
                        pd.notna(
                            capital
                        )
                        and
                        capital
                        <=
                        max_capital
                    ):

                        score += 10

                        reasons.append(
                            "股本約 "
                            f"{capital:.1f}億"
                        )


                    if (
                        drawdown_ok
                        and
                        base_ok
                    ):

                        results.append(
                            {
                                "代號":
                                    code,

                                "名稱":
                                    company_name,

                                "市場":
                                    market,

                                "現價":
                                    round(
                                        data[
                                            "price"
                                        ],
                                        2
                                    ),

                                "2年高點回落":
                                    f"{data['drawdown']:.1f}%",

                                "築底區間":
                                    f"{data['base_range']:.1f}%",

                                "MA60":
                                    (
                                        ""
                                        if
                                        pd.isna(
                                            data[
                                                "ma60"
                                            ]
                                        )
                                        else
                                        f"{data['ma60']:+.1f}%"
                                    ),

                                "週MA20":
                                    (
                                        ""
                                        if
                                        pd.isna(
                                            data[
                                                "weekly_ma20"
                                            ]
                                        )
                                        else
                                        f"{data['weekly_ma20']:+.1f}%"
                                    ),

                                "月MA20":
                                    (
                                        ""
                                        if
                                        pd.isna(
                                            data[
                                                "monthly_ma20"
                                            ]
                                        )
                                        else
                                        f"{data['monthly_ma20']:+.1f}%"
                                    ),

                                "量能":
                                    (
                                        ""
                                        if
                                        pd.isna(
                                            data[
                                                "volume"
                                            ]
                                        )
                                        else
                                        f"{data['volume']:+.1f}%"
                                    ),

                                "市值(億)":
                                    (
                                        ""
                                        if
                                        pd.isna(
                                            market_cap
                                        )
                                        else
                                        round(
                                            market_cap,
                                            1
                                        )
                                    ),

                                "股本估算(億)":
                                    (
                                        ""
                                        if
                                        pd.isna(
                                            capital
                                        )
                                        else
                                        round(
                                            capital,
                                            1
                                        )
                                    ),

                                "加分":
                                    score,

                                "為什麼抓到":
                                    " → ".join(
                                        reasons
                                    )
                            }
                        )


            progress.progress(
                (
                    index + 1
                )
                / len(codes)
            )


        status.empty()


        st.write(
            "本次檢查 "
            f"{len(codes)} 個代號，"
            f"{valid_stocks} 個"
            "有有效行情。"
        )


        if results:

            result_df = (
                pd.DataFrame(
                    results
                )
                .sort_values(
                    "加分",
                    ascending=False
                )
            )


            st.success(
                "找到 "
                f"{len(result_df)} 檔"
                "符合必要條件"
            )


            st.dataframe(
                result_df,
                use_container_width=True,
                hide_index=True
            )


        else:

            st.warning(
                "目前這個區段沒有符合"
                "「重跌＋築底」"
                "必要條件的股票。"
            )


# =========================================================
# 個股檢查
# =========================================================

with tab2:

    st.subheader(
        "個股完整檢查"
    )


    stock_code = (
        st.text_input(
            "輸入4位股票代號"
        )
    )


    if st.button(
        "查這一檔"
    ):

        stock_code = (
            stock_code
            .strip()
        )


        if not (
            len(stock_code)
            == 4
            and
            stock_code.isdigit()
        ):

            st.error(
                "請輸入4位數股票代號"
            )

        else:

            symbol, market = (
                resolve_symbol(
                    stock_code
                )
            )


            if not symbol:

                st.error(
                    "找不到這個股票代號"
                )

            else:

                hist = (
                    get_price(
                        symbol
                    )
                )


                (
                    company_name,
                    market_cap,
                    capital
                ) = (
                    get_company_info(
                        symbol
                    )
                )


                st.subheader(
                    f"{stock_code} "
                    f"{company_name}｜"
                    f"{market}"
                )


                if hist.empty:

                    st.error(
                        "抓不到股價資料"
                    )

                else:

                    data = (
                        calculate_metrics(
                            hist,
                            base_months
                        )
                    )


                    if data:

                        c1, c2, c3, c4 = (
                            st.columns(4)
                        )


                        c1.metric(
                            "現價",
                            f"{data['price']:.2f}"
                        )


                        c2.metric(
                            "2年高點回落",
                            f"{data['drawdown']:.1f}%"
                        )


                        c3.metric(
                            "距MA60",
                            (
                                "缺資料"
                                if
                                pd.isna(
                                    data["ma60"]
                                )
                                else
                                f"{data['ma60']:+.1f}%"
                            )
                        )


                        c4.metric(
                            "量能變化",
                            (
                                "缺資料"
                                if
                                pd.isna(
                                    data[
                                        "volume"
                                    ]
                                )
                                else
                                f"{data['volume']:+.1f}%"
                            )
                        )


                        st.line_chart(
                            hist["Close"]
                        )


                        st.write(
                            "市場：",
                            market
                        )


                        st.write(
                            "築底區間：",
                            f"{data['base_range']:.1f}%"
                        )


                        st.write(
                            "週MA20距離：",
                            (
                                "缺資料"
                                if
                                pd.isna(
                                    data[
                                        "weekly_ma20"
                                    ]
                                )
                                else
                                f"{data['weekly_ma20']:+.1f}%"
                            )
                        )


                        st.write(
                            "月MA20距離：",
                            (
                                "缺資料"
                                if
                                pd.isna(
                                    data[
                                        "monthly_ma20"
                                    ]
                                )
                                else
                                f"{data['monthly_ma20']:+.1f}%"
                            )
                        )


                        st.write(
                            "市值：",
                            (
                                "缺資料"
                                if
                                pd.isna(
                                    market_cap
                                )
                                else
                                f"{market_cap:.1f}億"
                            )
                        )


                        st.write(
                            "股本：",
                            (
                                "缺資料"
                                if
                                pd.isna(
                                    capital
                                )
                                else
                                f"約{capital:.1f}億"
                            )
                        )


# =========================================================
# 32項雷達
# =========================================================

with tab3:

    st.subheader(
        "32項正式雷達"
    )


    st.markdown(
        """
1. 上市＋上櫃＋創新板，排除ETF  
2. 股本、市值篩選  
3. 2年高點回落  
4. 築底時間  
5. 波動收斂  
6. MA60／週MA20／月MA20  
7. 底部放量  
8. 月營收 YoY／MoM／累計  
9. 財報轉折  
10. CAPEX  
11. 合約負債  
12. CB可轉債  
13. 擴產與公司事件  
14. 公司合作  
15. 客戶與供應鏈  
16. 題材分類  
17. 群體性  
18. 族群輪動  
19. 歷史循環  
20. 籌碼變化  
21. 公告／重大訊息／法說／新聞  
22. 事件與股價時間軸  
23. AI白話整理  
24. AI反證  
25. 個股完整頁  
26. 全市場雷達  
27. Must／Bonus／Off  
28. 自選股  
29. 異常提醒  
30. 顯示「為什麼抓到」  
31. 資料來源／日期／抓取時間  
32. 雷達只找變化，不替使用者決定買賣
"""
    )
