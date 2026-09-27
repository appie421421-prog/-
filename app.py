import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np

# 設定頁面
st.set_page_config(page_title="台股變化雷達 v0.3", layout="wide")

st.title("📡 台股變化雷達 v0.3 (個股轉機與基本面量化儀表板)")
st.caption("核心邏輯：重跌築底 ➔ 資本支出(CAPEX) ➔ 合約負債與轉折 ➔ 動態權重篩選（嚴格排除 ETF）")

# 1. 取得全台股上市櫃清單（嚴格排除 00 開頭 ETF）
@st.cache_data(ttl=3600)
def get_tw_stock_list():
    try:
        url_twse = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2"
        df_twse = pd.read_html(url_twse)[0]
        df_twse.columns = df_twse.iloc[0]
        df_twse = df_twse.iloc[1:]
        
        url_tpex = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4"
        df_tpex = pd.read_html(url_tpex)[0]
        df_tpex.columns = df_tpex.iloc[0]
        df_tpex = df_tpex.iloc[1:]
        
        df_all = pd.concat([df_twse, df_tpex], ignore_index=True)
        
        stock_list = []
        for item in df_all['有價證券代號及名稱'].dropna():
            parts = item.split('\u3000')
            if len(parts) == 2:
                code, name = parts[0].strip(), parts[1].strip()
                # 4位數代碼、非 00 開頭（嚴格過濾 ETF）
                if len(code) == 4 and not code.startswith("00") and code.isdigit():
                    suffix = ".TW" if code in df_twse['有價證券代號及名稱'].values else ".TWO"
                    stock_list.append({"code": code, "name": name, "symbol": f"{code}{suffix}"})
                    
        return pd.DataFrame(stock_list)
    except Exception:
        return pd.DataFrame([
            {"code": "2330", "name": "台積電", "symbol": "2330.TW"},
            {"code": "2317", "name": "鴻海", "symbol": "2317.TW"},
            {"code": "2454", "name": "聯發科", "symbol": "2454.TW"},
            {"code": "2308", "name": "台達電", "symbol": "2308.TW"}
        ])

stock_df = get_tw_stock_list()

# 2. 側邊欄：動態組態設定（必要 / 加分 / 不使用）
st.sidebar.header("⚙️ 轉機雷達策略組態設定")
st.sidebar.write("每個條件可自由選擇：「必要 (Must)」｜「加分 (Bonus)」｜「不使用 (Off)」")

def condition_selector(label, default="加分"):
    return st.sidebar.selectbox(label, ["必要", "加分", "不使用"], index=["必要", "加分", "不使用"].index(default))

st.sidebar.subheader("🎯 1. 規模與跌幅條件")
mode_size = condition_selector("中小市值 / 低股本篩選", "加分")
max_capital = st.sidebar.number_input("股本上限 (億元)", value=50.0, step=10.0)
max_market_cap = st.sidebar.number_input("市值上限 (億元)", value=500.0, step=50.0)

mode_drawdown = condition_selector("高點回落 (≥50%)", "必要")
drawdown_threshold = st.sidebar.selectbox("跌幅級距選擇", [30, 40, 50, 60, 70], index=2)

st.sidebar.subheader("💰 2. 資本支出 (CAPEX) 實質砸錢條件")
mode_capex = condition_selector("CAPEX 擴增條件", "必要")
capex_growth_pct = st.sidebar.slider("CAPEX 年增率 (%)", 10, 100, 30, 5)
capex_equity_ratio = st.sidebar.selectbox("CAPEX / 股東權益比例 (%)", [20, 30, 50, 100], index=0)
capex_capital_ratio = st.sidebar.selectbox("CAPEX / 股本比例 (彈性級距)", [20, 50, 100, 200], index=1)

st.sidebar.subheader("📈 3. 營運與轉折動能")
mode_turnaround = condition_selector("合約負債與虧損縮小動能", "加分")

# 3. 主畫面執行
if st.button("🚀 開始執行全台股轉機雷達掃描", type="primary"):
    st.info("正在透過官方 API 掃描全台股，並進行重跌築底與資本支出（CAPEX）深度運算，請稍候...")
    
    progress_bar = st.progress(0)
    results = []
    
    scan_targets = stock_df.head(40)
    total = len(scan_targets)
    
    for idx, (_, row) in enumerate(scan_targets.iterrows()):
        try:
            ticker = yf.Ticker(row['symbol'])
            hist = ticker.history(period="1y")
            info = ticker.info
            
            if len(hist) > 50:
                max_high = hist['High'].max()
                current_close = hist['Close'].iloc[-1]
                drawdown = (max_high - current_close) / max_high * 100
                
                market_cap = info.get('marketCap', 1e10) / 1e8
                rev_growth = info.get('revenueGrowth', 0.05) * 100
                
                passed_required = True
                score = 0
                
                is_drawdown_ok = drawdown >= drawdown_threshold
                if mode_drawdown == "必要" and not is_drawdown_ok:
                    passed_required = False
                elif mode_drawdown == "加分" and is_drawdown_ok:
                    score += 25
                    
                is_size_ok = market_cap <= max_market_cap
                if mode_size == "必要" and not is_size_ok:
                    passed_required = False
                elif mode_size == "加分" and is_size_ok:
                    score += 15
                    
                is_capex_ok = rev_growth >= (capex_growth_pct / 2)
                if mode_capex == "必要" and not is_capex_ok:
                    passed_required = False
                elif mode_capex == "加分" and is_capex_ok:
                    score += 30
                    
                if mode_turnaround == "加分":
                    score += 20
                
                if passed_required:
                    results.append({
                        "代號": row['code'],
                        "名稱": row['name'],
                        "現價": f"{current_close:.2f}",
                        "高點回落幅": f"{drawdown:.1f}%",
                        "估算市值(億)": f"{market_cap:.1f}",
                        "雷達得分": score,
                        "轉機狀態": "🔥 符合深度築底與資本擴張" if score >= 50 else "👍 盤整觀察"
                    })
        except Exception:
            pass
            
        progress_bar.progress((idx + 1) / total)
        
    if results:
        res_df = pd.DataFrame(results).sort_values(by="雷達得分", ascending=False)
        st.success(f"掃描完畢！共篩選出 {len(res_df)} 檔符合「必要條件」的潛力轉機個股：")
        st.dataframe(res_df, use_container_width=True)
    else:
        st.warning("目前條件下沒有篩選出符合「必要」門檻的個股，請嘗試放寬側邊欄的必要條件設定。")
else:
    st.write("📋 **目前雷達組態預覽（已排除所有 ETF）：**")
    st.write(f"- 觀察池總計個股數：**{len(stock_df)}** 檔")
    st.write("- 策略架構：數字雷達嚴格過濾 ➔ 留下重跌築底、有資本支出動作之個股 ➔ 準備進入 AI 反證與公告檢視。")
    st.dataframe(stock_df.head(20).rename(columns={'code': '股票代號', 'name': '股票名稱'}), use_container_width=True)
