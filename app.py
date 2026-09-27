import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np

st.set_page_config(page_title="台股變化雷達", layout="wide")

st.title("📡 台股變化雷達")
st.caption("找重跌、築底與開始出現變化的台股。缺資料就標示缺資料，不使用假數字代替。")


# =========================================================
# 1. 取得上市＋上櫃股票清單
# =========================================================
@st.cache_data(ttl=86400)
def get_tw_stock_list():

    stock_list = []

    for mode, suffix in [(2, ".TW"), (4, ".TWO")]:

        try:
            url = f"https://isin.twse.com.tw/isin/C_public.jsp?strMode={mode}"

            df = pd.read_html(url)[0]

            df.columns = df.iloc[0]
            df = df.iloc[1:].copy()

            column = "有價證券代號及名稱"

            for item in df[column].dropna().astype(str):

                parts = item.split("\u3000")

                if len(parts) >= 2:

                    code = parts[0].strip()
                    name = parts[1].strip()

                    # 只留四位數普通股票
                    # 排除 00 開頭 ETF
                    if (
                        code.isdigit()
                        and len(code) == 4
                        and not code.startswith("00")
                    ):

                        stock_list.append(
                            {
                                "code": code,
                                "name": name,
                                "symbol": code + suffix,
                            }
                        )

        except Exception:
            pass

    return (
        pd.DataFrame(stock_list)
        .drop_duplicates("code")
        .reset_index(drop=True)
    )


# =========================================================
# 2. 股價資料
# =========================================================
@st.cache_data(ttl=3600)
def get_price(symbol):

    try:

        df = yf.download(
            symbol,
            period="2y",
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False,
        )

        if df.empty:
            return pd.DataFrame()

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        return df.dropna(how="all")

    except Exception:

        return pd.DataFrame()


# =========================================================
# 3. 技術面計算
# =========================================================
def technical_metrics(hist):

    close = hist["Close"].dropna()
    high = hist["High"].dropna()
    volume = hist["Volume"].dropna()

    current_price = float(close.iloc[-1])

    two_year_high = float(high.max())

    drawdown = (
        (two_year_high - current_price)
        / two_year_high
        * 100
    )

    # MA60
    if len(close) >= 60:

        ma60 = float(
            close.rolling(60).mean().iloc[-1]
        )

        ma60_distance = (
            current_price / ma60 - 1
        ) * 100

    else:

        ma60_distance = np.nan

    # 20日量 vs 60日量
    if len(volume) >= 60:

        volume20 = float(
            volume.tail(20).mean()
        )

        volume60 = float(
            volume.tail(60).mean()
        )

        volume_change = (
            volume20 / volume60 - 1
        ) * 100

    else:

        volume_change = np.nan

    return (
        current_price,
        drawdown,
        ma60_distance,
        volume_change,
    )


# =========================================================
# 4. 股票池
# =========================================================
try:

    stock_df = get_tw_stock_list()

except Exception as e:

    st.error(f"股票清單讀取失敗：{e}")

    st.stop()


# =========================================================
# 5. 側邊欄
# =========================================================
with st.sidebar:

    st.header("⚙️ 糖球預設策略")

    st.caption(
        "預設值已直接設定好，平常不用每次重新調整。"
    )

    drawdown_threshold = st.selectbox(
        "高點回落 (%)",
        [30, 40, 50, 60, 70],
        index=2,
    )

    base_months = st.selectbox(
        "築底觀察期（月）",
        [2, 3, 6, 12, 18, 24],
        index=2,
    )

    contraction_pct = st.slider(
        "築底區間最大波動 (%)",
        10,
        50,
        20,
        5,
    )

    volume_threshold = st.slider(
        "底部量能增加 (%)",
        0,
        100,
        30,
        5,
    )

    max_market_cap = st.number_input(
        "市值上限（億元）",
        min_value=0.0,
        max_value=100000.0,
        value=500.0,
        step=50.0,
    )

    st.divider()

    st.write("必要：高點回落＋築底")

    st.write(
        "加分：市值、MA60、底部放量"
    )

    st.caption(
        "CAPEX、合約負債、CB、營收、籌碼等尚未接到真實資料前，不使用假數字代替。"
    )


# =========================================================
# 6. 主頁
# =========================================================
tab1, tab2, tab3 = st.tabs(
    [
        "🔎 全市場雷達",
        "📊 個股檢查",
        "🧭 完整雷達項目",
    ]
)


# =========================================================
# 全市場雷達
# =========================================================
with tab1:

    st.subheader("全台股掃描")

    st.write(
        f"目前股票池：{len(stock_df)} 檔"
    )

    scan_options = [
        50,
        100,
        200,
        500,
        len(stock_df),
    ]

    scan_options = sorted(
        list(set(scan_options))
    )

    scan_limit = st.selectbox(
        "這次掃描數量",
        scan_options,
        index=min(
            1,
            len(scan_options) - 1
        ),
    )

    if st.button(
        "🚀 開始掃描",
        type="primary",
    ):

        targets = stock_df.head(
            scan_limit
        )

        progress_bar = st.progress(0)

        results = []

        total = len(targets)

        for i, (_, stock) in enumerate(
            targets.iterrows()
        ):

            hist = get_price(
                stock["symbol"]
            )

            if len(hist) >= 60:

                (
                    price,
                    drawdown,
                    ma60_distance,
                    volume_change,
                ) = technical_metrics(hist)

                # -------------------------
                # 築底區間
                # -------------------------
                days = min(
                    len(hist),
                    int(base_months * 21),
                )

                recent = hist.tail(days)

                recent_high = float(
                    recent["High"].max()
                )

                recent_low = float(
                    recent["Low"].min()
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

                # -------------------------
                # 避免一路下跌被誤判築底
                # -------------------------
                close = hist[
                    "Close"
                ].dropna()

                if len(close) >= 20:

                    recent20_change = (
                        float(close.iloc[-1])
                        / float(close.iloc[-20])
                        - 1
                    ) * 100

                else:

                    recent20_change = 0

                base_ok = (
                    pd.notna(base_range)
                    and base_range
                    <= contraction_pct
                    and recent20_change
                    > -15
                )

                drawdown_ok = (
                    drawdown
                    >= drawdown_threshold
                )

                # -------------------------
                # 市值
                # 抓不到就空白
                # 不亂填
                # -------------------------
                market_cap = np.nan

                try:

                    ticker = yf.Ticker(
                        stock["symbol"]
                    )

                    fast_info = (
                        ticker.fast_info
                    )

                    value = fast_info.get(
                        "market_cap",
                        None,
                    )

                    if value:

                        market_cap = (
                            float(value)
                            / 100000000
                        )

                except Exception:

                    pass

                score = 0

                reasons = []

                if drawdown_ok:

                    reasons.append(
                        f"2年高點回落 {drawdown:.1f}%"
                    )

                if base_ok:

                    reasons.append(
                        f"近{base_months}月波動區間 {base_range:.1f}%"
                    )

                # MA60 加分
                if (
                    pd.notna(
                        ma60_distance
                    )
                    and abs(
                        ma60_distance
                    )
                    <= 10
                ):

                    score += 15

                    reasons.append(
                        f"距MA60 {ma60_distance:+.1f}%"
                    )

                # 底部放量
                if (
                    pd.notna(
                        volume_change
                    )
                    and volume_change
                    >= volume_threshold
                ):

                    score += 20

                    reasons.append(
                        f"近20日量較60日均量 {volume_change:+.1f}%"
                    )

                # 中小市值
                if (
                    pd.notna(
                        market_cap
                    )
                    and market_cap
                    <= max_market_cap
                ):

                    score += 10

                    reasons.append(
                        f"市值約 {market_cap:.1f} 億"
                    )

                # -------------------------
                # 必要條件
                # -------------------------
                if (
                    drawdown_ok
                    and base_ok
                ):

                    results.append(
                        {
                            "代號":
                                stock["code"],

                            "名稱":
                                stock["name"],

                            "現價":
                                round(
                                    price,
                                    2,
                                ),

                            "2年高點回落":
                                f"{drawdown:.1f}%",

                            "築底區間":
                                f"{base_range:.1f}%",

                            "MA60距離":
                                (
                                    ""
                                    if pd.isna(
                                        ma60_distance
                                    )
                                    else
                                    f"{ma60_distance:+.1f}%"
                                ),

                            "量能變化":
                                (
                                    ""
                                    if pd.isna(
                                        volume_change
                                    )
                                    else
                                    f"{volume_change:+.1f}%"
                                ),

                            "市值(億)":
                                (
                                    ""
                                    if pd.isna(
                                        market_cap
                                    )
                                    else
                                    round(
                                        market_cap,
                                        1,
                                    )
                                ),

                            "技術加分":
                                score,

                            "為什麼抓到":
                                " → ".join(
                                    reasons
                                ),
                        }
                    )

            progress_bar.progress(
                (i + 1) / total
            )

        if results:

            result_df = pd.DataFrame(
                results
            )

            result_df = (
                result_df.sort_values(
                    by="技術加分",
                    ascending=False,
                )
            )

            st.success(
                f"找到 {len(result_df)} 檔符合目前必要條件"
            )

            st.dataframe(
                result_df,
                use_container_width=True,
                hide_index=True,
            )

        else:

            st.warning(
                "目前掃描範圍沒有符合必要條件的股票。"
            )


# =========================================================
# 7. 個股檢查
# =========================================================
with tab2:

    st.subheader("個股檢查")

    stock_code = st.text_input(
        "輸入股票代號，例如 2330"
    )

    if stock_code:

        hit = stock_df[
            stock_df["code"]
            == stock_code.strip()
        ]

        if hit.empty:

            st.warning(
                "找不到這個股票代號"
            )

        else:

            stock = hit.iloc[0]

            hist = get_price(
                stock["symbol"]
            )

            st.subheader(
                f"{stock['code']} {stock['name']}"
            )

            if hist.empty:

                st.error(
                    "目前抓不到股價資料"
                )

            else:

                (
                    price,
                    drawdown,
                    ma60_distance,
                    volume_change,
                ) = technical_metrics(
                    hist
                )

                col1, col2, col3, col4 = (
                    st.columns(4)
                )

                col1.metric(
                    "現價",
                    f"{price:.2f}",
                )

                col2.metric(
                    "2年高點回落",
                    f"{drawdown:.1f}%",
                )

                col3.metric(
                    "距 MA60",
                    (
                        "缺資料"
                        if pd.isna(
                            ma60_distance
                        )
                        else
                        f"{ma60_distance:+.1f}%"
                    ),
                )

                col4.metric(
                    "量能變化",
                    (
                        "缺資料"
                        if pd.isna(
                            volume_change
                        )
                        else
                        f"{volume_change:+.1f}%"
                    ),
                )

                st.line_chart(
                    hist["Close"]
                )

            # -------------------------
            # 真實功能狀態
            # -------------------------
            st.subheader(
                "資料模組狀態"
            )

            status_df = pd.DataFrame(
                [
                    [
                        "股價／跌幅／均線／量能",
                        "已接",
                    ],
                    [
                        "上市櫃股票池",
                        "已接",
                    ],
                    [
                        "股本／正式市值來源",
                        "待接官方資料",
                    ],
                    [
                        "月營收 YoY／MoM／累計",
                        "待接官方資料",
                    ],
                    [
                        "財報／毛利／EPS／現金流／存貨／應收",
                        "待接官方資料",
                    ],
                    [
                        "CAPEX",
                        "待接財報資料，不以營收成長冒充",
                    ],
                    [
                        "合約負債",
                        "待接財報資料",
                    ],
                    [
                        "CB 可轉債",
                        "待接公開資訊",
                    ],
                    [
                        "外資／投信／自營商／融資融券",
                        "待接官方資料",
                    ],
                    [
                        "公告／法說／合作／擴產／客戶",
                        "待接公開資訊",
                    ],
                    [
                        "群體性／族群輪動／歷史循環",
                        "待資料完成後運算",
                    ],
                ],
                columns=[
                    "項目",
                    "狀態",
                ],
            )

            st.dataframe(
                status_df,
                use_container_width=True,
                hide_index=True,
            )


# =========================================================
# 8. 32項正式雷達範圍
# =========================================================
with tab3:

    st.subheader(
        "正式版雷達功能範圍"
    )

    st.markdown(
        """
### 技術與規模
上市＋上櫃股票池、股本、市值、2年高點回落、築底時間、波動收斂、MA60、週MA20、月MA20、底部放量。

### 營收與基本面
月營收 YoY、MoM、累計營收、連續成長、由負轉正、成長加速、毛利率、營業利益、EPS、現金流、存貨、應收帳款。

### CAPEX
CAPEX 年增率、CAPEX／股本、CAPEX／股東權益、CAPEX／營收。

### 合約負債
季增、連續增加、突然增加，以及後續是否轉成營收。

### CB 可轉債
發行日期、規模、轉換價、轉換期間、價格調整、轉換狀態與股價時間軸。

### 公司事件
擴產、新廠、新產線、設備、認證、新產品、新市場、新客戶、轉虧為盈、併購、投資與處分。

### 合作與供應鏈
公司合作、策略聯盟、共同開發、供貨、採購、訂單、客戶、上下游與供應鏈關係。

### 題材
AI、機器人、半導體、PCB、散熱、伺服器、軍工、生技等，可多標籤。

### 群體性
同產業、同題材、上下游公司是否同時出現營收、量價、法人、CAPEX 等變化。

### 族群輪動
找原本安靜、後來整群開始出現變化的族群，並保存歷史。

### 歷史循環
多年股價、營收、季節性、產業循環與量價規律。

### 籌碼
外資、投信、自營商、融資融券及可取得的大戶持股資料。

### 公告與新聞
重大訊息、公告、法說、新聞，保留日期、來源與原文。

### AI整理
把財報、公告與法說整理成白話，同時找正面證據與反證，不自行猜測缺失資料。

### 個股完整頁
技術面、基本面、CAPEX、合約負債、CB、事件、合作、供應鏈、題材、群體性、籌碼、循環與新聞時間軸。

### 全市場雷達
掃描全台上市櫃股票，找近期新出現的變化。

### 自選股與提醒
保存自選股，追蹤營收、公告、CB、合作、籌碼與群體變化。

### 原始資料追蹤
所有重要數字與判斷保留來源、資料日期與抓取時間。

---

雷達負責找出異常、轉折、群體、輪動、循環與事件。

每一檔被抓出的股票都必須說明「為什麼被抓到」，不能只顯示一個分數。
"""
    )
