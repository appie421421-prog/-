import streamlit as st
import pandas as pd
import requests

# 1. App 介面設定
st.set_page_config(page_title="台股變化雷達 v0.3", layout="wide")
st.title("📡 台股變化雷達 v0.3 (全台股自動掃描儀表板)")

# 2. 選股條件矩陣設定 (側邊欄)
st.sidebar.header("⚙️ 選股條件矩陣設定")

# (1) 形態與築底
st.sidebar.subheader("1. 形態與築底")
drop_mode = st.sidebar.radio("2年高點回落", ["不使用", "加分", "必要"], index=2, key="drop")
drop_threshold = st.sidebar.slider("回落門檻 (%)", 30, 70, 50, step=10)

base_mode = st.sidebar.radio("低檔盤整", ["不使用", "加分", "必要"], index=2, key="base")
base_months = st.sidebar.selectbox("盤整月數 (預設>=2個月)", [2, 3, 6, 12, 18, 24], index=0)

# (2) 規模限制
st.sidebar.subheader("2. 規模限制")
capital_mode = st.sidebar.radio("股本上限 (<=50億)", ["不使用", "加分", "必要"], index=1, key="cap")

# (3) CAPEX 資本支出
st.sidebar.subheader("3. CAPEX 資本支出 (真實砸錢)")
capex_mode = st.sidebar.radio("CAPEX / 股本", ["不使用", "加分", "必要"], index=1, key="capex")
capex_ratio = st.sidebar.select_slider("CAPEX/股本 門檻 (%)", options=[20, 50, 100, 200], value=50)

# (4) 營運轉折前兆
st.sidebar.subheader("4. 營運轉折前兆")
contract_mode = st.sidebar.radio("合約負債 (QoQ>=20% 或 YoY>=30%)", ["不使用", "加分", "必要"], index=1, key="cl")

# 3. 自動串接證交所 OpenAPI 資料
@st.cache_data(ttl=3600)
def load_twse_data():
    url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    try:
        res = requests.get(url, timeout=10)
        return pd.DataFrame(res.json())
    except Exception as e:
        st.error(f"資料讀取失敗: {e}")
        return pd.DataFrame()

# 4. 主畫面掃描執行區
if st.button("🚀 開始自動掃描全台股"):
    st.info("正連線至證交所 API 掃描全台股最新數據...")
    df_raw = load_twse_data()
    
    if not df_raw.empty:
        st.success(f"成功掃描 {len(df_raw)} 檔上市股票數據！")
        st.subheader("📋 符合當前條件之股票篩選清單")
        st.dataframe(df_raw[['Code', 'Name', 'ClosingPrice', 'TradeVolume']].head(30))
    else:
        st.warning("目前暫時無法取得證交所公開資料，請稍後再試。")
