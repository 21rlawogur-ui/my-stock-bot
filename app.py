import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.express as px
import requests
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import json
import os

# --- [1] 앱 전체 설정 및 초기화 ---
st.set_page_config(page_title="나만의 주식 비서", layout="wide")
st.markdown("<div id='top_anchor'></div>", unsafe_allow_html=True)

# 한국 주식 수집용 브라우저 위장 헤더
NAVER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Referer": "https://finance.naver.com/"
}

# 💾 영구 저장을 위한 로컬 JSON 파일 관리 함수
PORTFOLIO_FILE = "my_portfolio.json"

def load_portfolio():
    if os.path.exists(PORTFOLIO_FILE):
        try:
            with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return [
        {"name": "삼성전자", "ticker": "005930", "is_kr": True, "buy_price": 72000, "count": 10},
        {"name": "애플", "ticker": "AAPL", "is_kr": False, "buy_price": 240.0, "count": 5},
        {"name": "테슬라", "ticker": "TSLA", "is_kr": False, "buy_price": 380.0, "count": 2}
    ]

def save_portfolio():
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(st.session_state.portfolio, f, ensure_ascii=False, indent=4)

# 세션 상태 초기화
if 'portfolio' not in st.session_state: st.session_state.portfolio = load_portfolio()
if 'shadow_cache' not in st.session_state: st.session_state.shadow_cache = {}
if 'error_log' not in st.session_state: st.session_state.error_log = "정상 가동 중"
if 'collapse_key' not in st.session_state: st.session_state.collapse_key = 0
if 'search_results' not in st.session_state: st.session_state.search_results = []
if 'gemini_api_key' not in st.session_state: st.session_state.gemini_api_key = ""
if 'chat_history' not in st.session_state: st.session_state.chat_history = []

SEARCH_DB = [
    {"name": "삼성전자", "ticker": "005930", "is_kr": True, "market": "🇰🇷 코스피"},
    {"name": "SK하이닉스", "ticker": "000660", "is_kr": True, "market": "🇰🇷 코스피"},
    {"name": "LG에너지솔루션", "ticker": "373220", "is_kr": True, "market": "🇰🇷 코스피"},
    {"name": "현대차", "ticker": "005380", "is_kr": True, "market": "🇰🇷 코스피"},
    {"name": "기아", "ticker": "000270", "is_kr": True, "market": "🇰🇷 코스피"},
    {"name": "카카오", "ticker": "035720", "is_kr": True, "market": "🇰🇷 코스피"},
    {"name": "NAVER (네이버)", "ticker": "035420", "is_kr": True, "market": "🇰🇷 코스피"},
    {"name": "에코프로비엠", "ticker": "247540", "is_kr": True, "market": "🇰🇷 코스닥"},
    {"name": "에코프로", "ticker": "086520", "is_kr": True, "market": "🇰🇷 코스닥"},
    {"name": "알테오젠", "ticker": "196170", "is_kr": True, "market": "🇰🇷 코스닥"},
    {"name": "애플 (Apple)", "ticker": "AAPL", "is_kr": False, "market": "🇺🇸 미국"},
    {"name": "테슬라 (Tesla)", "ticker": "TSLA", "is_kr": False, "market": "🇺🇸 미국"},
    {"name": "엔비디아 (NVIDIA)", "ticker": "NVDA", "is_kr": False, "market": "🇺🇸 미국"},
    {"name": "마이크로소프트", "ticker": "MSFT", "is_kr": False, "market": "🇺🇸 미국"},
    {"name": "구글 (Alphabet)", "ticker": "GOOGL", "is_kr": False, "market": "🇺🇸 미국"},
]

# --- [2] ⚡ 실시간 데이터 수집 엔진 ---
@st.cache_data(ttl=5) 
def get_korea_live_data(code_or_index):
    try:
        if code_or_index in ["KOSPI", "KOSDAQ"]:
            url = f"https://polling.finance.naver.com/api/realtime?query=SERVICE_INDEX:{code_or_index}"
        else:
            url = f"https://polling.finance.naver.com/api/realtime?query=SERVICE_ITEM:{code_or_index}"
        res = requests.get(url, headers=NAVER_HEADERS, timeout=3).json()
        data = res['result']['areas'][0]['datas'][0]
        price = float(data['nv'])
        if code_or_index in ["KOSPI", "KOSDAQ"]: price = price / 100.0
        change = float(data['cr'])
        st.session_state.shadow_cache[code_or_index] = (price, change)
        return price, change
    except Exception as e:
        st.session_state.error_log = f"❌ 국내 갱신 실패 ({code_or_index}): {str(e)}"
        return st.session_state.shadow_cache.get(code_or_index, (0.0, 0.0))

# ⭐️ [핵심 패치] 야후 서버 클라우드 차단 우회를 위한 fast_info 이중 엔진
@st.cache_data(ttl=30)
def get_global_live_data(ticker):
    try:
        stock = yf.Ticker(ticker)
        
        # 1순위 우회 엔진: 차단 확률이 극히 낮은 fast_info 접근법
        if hasattr(stock, 'fast_info'):
            cur = float(stock.fast_info.last_price)
            prev = float(stock.fast_info.previous_close)
            if prev > 0:
                change = ((cur - prev) / prev) * 100
                st.session_state.shadow_cache[ticker] = (cur, change)
                return cur, change

        # 2순위 백업 엔진: 휴일/주말 차이 극복을 위해 데이터를 5일치로 넉넉하게 스캔
        hist = stock.history(period="5d")
        if not hist.empty and len(hist) >= 2:
            cur = float(hist['Close'].iloc[-1])
            prev = float(hist['Close'].iloc[-2])
            change = ((cur - prev) / prev) * 100
            st.session_state.shadow_cache[ticker] = (cur, change)
            return cur, change
            
        raise ValueError("yfinance 데이터를 가져올 수 없습니다.")
    except Exception as e:
        st.session_state.error_log = f"❌ 해외 갱신 실패 ({ticker}): {str(e)}"
        return st.session_state.shadow_cache.get(ticker, (0.0, 0.0))

@st.cache_data(ttl=86400)
def get_heavy_market_cap(ticker):
    if ticker in ["KOSPI", "KOSDAQ", "^GSPC", "^IXIC", "^DJI"]: return 1
    try: 
        stock = yf.Ticker(ticker)
        return float(stock.fast_info.market_cap)
    except: 
        try:
            return float(stock.info.get('marketCap', 1))
        except:
            return 1

# --- 📰 구글 실시간 뉴스 RSS 수집 엔진 ---
@st.cache_data(ttl=1800) 
def fetch_stock_news(ticker, name, is_kr):
    news_list = []
    try:
        query_str = f"{name} 주식" if is_kr else f"{name} stock"
        query = urllib.parse.quote(query_str)
        url = f"https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"
        
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        xml_data = urllib.request.urlopen(req, timeout=5).read()
        root = ET.fromstring(xml_data)
        
        for item in root.findall('.//item')[:3]:
            title = item.find('title').text
            link = item.find('link').text
            clean_title = title.split(' - ')[0] if ' - ' in title else title
            publisher = title.split(' - ')[-1] if ' - ' in title else "뉴스"
            
            news_list.append({
                "title": clean_title,
                "publisher": publisher,
                "link": link,
                "type": "뉴스"
            })
    except Exception:
        pass

    if not news_list:
        news_list = [{"title": f"{name} 관련 최신 뉴스를 불러오지 못했습니다.", "publisher": "시스템", "link": "#", "type": "알림"}]
    return news_list

# --- 🤖 Gemini AI 활용 요약 및 대화 엔진 ---
def ask_gemini_ai(prompt, context_news=""):
    api_key = st.session_state.get("gemini_api_key", "")
    if not api_key:
        return "⚠️ 사이드바에 **Gemini API Key**를 입력하고 **[🔑 API 키 적용]** 버튼을 눌러주세요!"
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    
    system_instruction = "당신은 전문 주식 투자 분석가입니다. 제공된 실시간 뉴스 헤드라인들을 바탕으로 현재 시장 상황을 분석하고, 투자자가 알기 쉽고 명확하게 답변하세요."
    full_prompt = f"{system_instruction}\n\n[실시간 수집된 뉴스 데이터]:\n{context_news}\n\n[사용자 요청사항]:\n{prompt}"
    
    payload = {"contents": [{"parts": [{"text": full_prompt}]}]}
    
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=15)
        res_json = res.json()
        return res_json['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        return f"❌ AI 연동 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."

# --- [3] 공통 그래프 빌더 ---
def draw_heatmap(df, path_col, value_col, color_col, title):
    fig = px.treemap(df, path=[px.Constant(title), path_col], values=value_col, color=color_col,
                     color_continuous_scale=['#ff4b4b', '#262730', '#00cc00'], color_continuous_midpoint=0,
                     custom_data=["현재가", "오늘등락률(%)"])
    fig.update_traces(hovertemplate="<b>%{label}</b><br>현재가: %{customdata[0]}<br>오늘 등락: %{customdata[1]:.2f}%",
                      texttemplate="<b>%{label}</b><br>%{customdata[0]}<br>%{customdata[1]:.2f}%", textfont=dict(size=18, color="white"))
    fig.update_layout(width=700, height=700, margin=dict(t=10, b=10, l=10, r=10))
    st.plotly_chart(fig, use_container_width=False)

# ==========================================
# 🧱 화면 UI 레이아웃 및 제어부
# ==========================================
title_col, btn_col = st.columns([5, 1])
with title_col:
    st.title("📈 나만의 맞춤형 주식 비서")
    st.write("실시간 자산 포트폴리오와 AI 대화형 뉴스 리포트가 결합된 통합 플랫폼입니다.")

with btn_col:
    st.write(""); st.write("")
    if st.button("🗂️ 지수 모두 접기", key="global_collapse_btn", use_container_width=True):
        st.session_state.collapse_key += 1
        st.rerun()

st.divider()

# --- [4] 사이드바 (포트폴리오 관리, API 키 제어, 검색창) ---
st.sidebar.header("⚙️ 시스템 설정 및 관리")

gemini_key_input = st.sidebar.text_input("🤖 Gemini API Key 입력", type="password", value=st.session_state.get("gemini_api_key", ""))
if st.sidebar.button("🔑 API 키 적용", use_container_width=True):
    st.session_state.gemini_api_key = gemini_key_input
    if gemini_key_input: st.sidebar.success("API 키가 성공적으로 적용되었습니다! 🎉")
    else: st.sidebar.warning("키가 비어있습니다. 다시 확인해 주세요.")

st.sidebar.subheader("🔄 실시간 동기화 제어")
auto_refresh = st.sidebar.toggle("⏱️ 자동 실시간 갱신 활성화", value=False)
refresh_rate = st.sidebar.slider("갱신 주기 설정 (초)", 5, 60, 10, step=5)

if st.sidebar.button("⚡ 뉴스 및 캐시 강제 리셋", key="force_sync_btn", use_container_width=True):
    get_korea_live_data.clear()
    get_global_live_data.clear()
    fetch_stock_news.clear()
    st.toast("최신 뉴스와 시세를 다시 불러왔습니다!", icon="🔥")
    st.rerun()

st.sidebar.info(f"🛰️ 상태: {st.session_state.error_log}")
st.sidebar.markdown("---")

with st.sidebar.expander("🔍 주식 검색 및 추가 (해외 티커 지원)", expanded=True):
    search_keyword = st.text_input("종목명 또는 티커 입력 (예: 삼성, SPYM, QQQ)", key="stock_search_input")
    
    if st.button("🔍 검색 실행", key="btn_execute_search", use_container_width=True):
        if search_keyword.strip():
            df_db = pd.DataFrame(SEARCH_DB)
            filtered_df = df_db[df_db['name'].str.contains(search_keyword, case=False) | df_db['ticker'].str.contains(search_keyword, case=False)]
            st.session_state.search_results = filtered_df.to_dict('records')
            
            if not st.session_state.search_results:
                with st.spinner("글로벌 시장에서 티커를 검색 중입니다..."):
                    test_ticker = search_keyword.strip().upper()
                    cur, _ = get_global_live_data(test_ticker)
                    
                    if cur > 0:
                        st.session_state.search_results = [{
                            "name": f"{test_ticker} (글로벌 종목)",
                            "ticker": test_ticker,
                            "is_kr": False,
                            "market": "🌐 글로벌 직접검색"
                        }]
                        st.toast(f"글로벌 시장에서 '{test_ticker}'를 찾았습니다!", icon="🎯")
                    else:
                        st.toast("내장 DB 및 글로벌 시장에서 찾을 수 없습니다. (정확한 티커인지 확인해 주세요)", icon="❓")
        else:
            st.session_state.search_results = []
            st.toast("검색어를 한 글자 이상 입력해 주세요.", icon="⚠️")

    if st.session_state.search_results:
        st.markdown("---")
        st.markdown("##### 🎯 매칭된 종목 목록")
        for idx, r in enumerate(st.session_state.search_results[:6]):
            col_text, col_btn = st.columns([3, 1])
            col_text.markdown(f"**{r['name']}**<br><span style='color:gray; font-size:11px;'>{r['market']} | {r['ticker']}</span>", unsafe_allow_html=True)
            
            if col_btn.button("➕", key=f"add_stock_{idx}_{r['ticker']}", use_container_width=True):
                if any(p['ticker'] == r['ticker'] for p in st.session_state.portfolio):
                    st.toast("이미 등록된 관심 종목입니다.", icon="⚠️")
                else:
                    if r['is_kr']: cur, _ = get_korea_live_data(r['ticker'])
                    else: cur, _ = get_global_live_data(r['ticker'])
                    
                    st.session_state.portfolio.append({
                        "name": r['name'].split(" (")[0], "ticker": r['ticker'], "is_kr": r['is_kr'], "buy_price": cur if cur > 0 else 100.0, "count": 1.0 
                    })
                    save_portfolio() 
                    st.toast(f"{r['name']} 자산 리스트 편입 및 저장 완료!", icon="✅")
                    st.session_state.search_results = [] 
                    st.rerun()

st.sidebar.subheader("🗂️ 나의 보유 종목 리스트")
to_delete = None
for i, item in enumerate(st.session_state.portfolio):
    edit_state_key = f"edit_active_{item['ticker']}"
    if edit_state_key not in st.session_state: st.session_state[edit_state_key] = False
        
    st.sidebar.markdown(f"### 📌 {item['name']} ({item['ticker']})")
    unit = "원" if item['is_kr'] else "$"
    step_val = 500.0 if item['is_kr'] else 1.0
    
    if item['is_kr']: cur_price, _ = get_korea_live_data(item['ticker'])
    else: cur_price, _ = get_global_live_data(item['ticker'])
    cur_price_str = f"{cur_price:,.0f}" if item['is_kr'] else f"{cur_price:,.2f}"

    if not st.session_state[edit_state_key]:
        st.sidebar.write(f"현재가: **{cur_price_str}{unit}**")
        st.sidebar.caption(f"평단가: {item['buy_price']:,}{unit} / 수량: {item['count']:,}주")
        if st.sidebar.button("✏️ 수정", key=f"btn_open_edit_{i}"):
            st.session_state[edit_state_key] = True
            st.rerun()
    else:
        edited_buy = st.sidebar.number_input(f"평단가 수정", min_value=0.0, value=float(item['buy_price']), step=step_val, key=f"edit_buy_{i}")
        edited_count = st.sidebar.number_input(f"수량 수정", min_value=0.0, value=float(item['count']), step=1.0, key=f"edit_count_{i}")
        col_save, col_del = st.sidebar.columns(2)
        
        if col_save.button("✅ 완료", key=f"save_{i}"):
            st.session_state.portfolio[i]['buy_price'] = edited_buy
            st.session_state.portfolio[i]['count'] = edited_count
            save_portfolio() 
            st.session_state[edit_state_key] = False 
            st.rerun()
        if col_del.button("❌ 삭제", key=f"del_{i}"):
            to_delete = i
            st.session_state[edit_state_key] = False

if to_delete is not None:
    st.session_state.portfolio.pop(to_delete)
    save_portfolio() 
    st.rerun()


# --- [5] 메인 화면 왼쪽: 포트폴리오 자산지도 및 지수 전광판 ---
left_view, right_view = st.columns([4, 3])

with left_view:
    st.subheader("🟩 나의 보유 자산 현황")
    portfolio_data = []
    all_news_context = "" 
    
    for item in st.session_state.portfolio:
        if item['is_kr']: current, daily_change = get_korea_live_data(item['ticker'])
        else: current, daily_change = get_global_live_data(item['ticker'])
        
        exchange_rate = 1 if item['is_kr'] else 1400
        total_money = (item['buy_price'] * item['count']) * exchange_rate
        cur_str = f"{current:,.0f}원" if item['is_kr'] else f"${current:,.2f}"
        
        portfolio_data.append({"종목명": item['name'], "현재가": cur_str, "오늘등락률(%)": daily_change, "투자금액": total_money})
        
        ticker_news = fetch_stock_news(item['ticker'], item['name'], item['is_kr'])
        for n in ticker_news:
            all_news_context += f"[{item['name']}] {n['title']}\n"

    if portfolio_data:
        draw_heatmap(pd.DataFrame(portfolio_data), "종목명", "투자금액", "오늘등락률(%)", "나의 포트폴리오")

    st.divider()
    
    st.subheader("🗺️ 글로벌 시장 종합 히트맵")
    index_map = {
        "🇰🇷 1. 코스피 (KOSPI)": {"engine": "KR", "code": "KOSPI", "display_unit": "pt"},
        "🇰🇷 2. 코스닥 (KOSDAQ)": {"engine": "KR", "code": "KOSDAQ", "display_unit": "pt"},
        "🇺🇸 3. 미국 S&P 500": {"engine": "US", "code": "^GSPC", "display_unit": "pt"},
        "🇺🇸 4. 미국 나스닥": {"engine": "US", "code": "^IXIC", "display_unit": "pt"},
        "🇺🇸 5. 미국 다우존스": {"engine": "US", "code": "^DJI", "display_unit": "pt"}
    }
    markets = {
        "🇰🇷 1. 코스피 (KOSPI)": {"삼성전자":"005930.KS", "SK하이닉스":"000660.KS", "현대차":"005380.KS"},
        "🇰🇷 2. 코스닥 (KOSDAQ)": {"에코프로비엠":"247540.KQ", "알테오젠":"196170.KQ"},
        "🇺🇸 3. 미국 S&P 500": {"애플":"AAPL", "마이크로소프트":"MSFT", "엔비디아":"NVDA"},
        "🇺🇸 4. 미국 나스닥": {"애플":"AAPL", "테슬라":"TSLA", "엔비디아":"NVDA"},
        "🇺🇸 5. 미국 다우존스": {"유나이티드헬스":"UNH", "골드만삭스":"GS", "홈디포":"HD"}
    }

    for market_name, tickers in markets.items():
        with st.expander(market_name, expanded=False, key=f"exp_{market_name}_{st.session_state.collapse_key}"):
            meta = index_map[market_name]
            if meta['engine'] == "KR": idx_current, idx_change = get_korea_live_data(meta['code'])
            else: idx_current, idx_change = get_global_live_data(meta['code'])
            
            st.metric(label=f"{meta['code']} 종합 지수", value=f"{idx_current:,.2f} {meta['display_unit']}", delta=f"{idx_change:+.2f}%")
            
            market_data = []
            is_kr_market = (meta['engine'] == "KR")
            for name, ticker in tickers.items():
                if is_kr_market: cur, change = get_korea_live_data(ticker.split(".")[0])
                else: cur, change = get_global_live_data(ticker)
                m_cap = get_heavy_market_cap(ticker)
                cur_str = f"{cur:,.0f}원" if is_kr_market else f"${cur:,.2f}"
                market_data.append({"종목명": name, "현재가": cur_str, "오늘등락률(%)": change, "시가총액": m_cap})
            
            draw_heatmap(pd.DataFrame(market_data), "종목명", "시가총액", "오늘등락률(%)", market_name)


# --- [6] 📰 메인 화면 오른쪽: 맞춤형 뉴스 브리핑 & AI 주식 챗봇 대화창 ---
with right_view:
    st.subheader("📰 진짜! 내 종목 최신 뉴스")
    
    for item in st.session_state.portfolio:
        with st.expander(f"🔔 {item['name']} 최신 헤드라인", expanded=True):
            news_items = fetch_stock_news(item['ticker'], item['name'], item['is_kr'])
            for n in news_items:
                st.markdown(f"**🔵 뉴스** [{n['title']}]({n['link']}) *(출처: {n['publisher']})*")
    
    st.markdown("---")
    st.subheader("🤖 AI 대화형 주식 리포트 비서")
    
    if st.button("✨ 수집된 뉴스로 오늘의 핵심 요약 브리핑 발행", key="btn_ai_report", use_container_width=True):
        with st.spinner("방금 긁어온 실시간 뉴스를 마이닝하고 있습니다..."):
            brief_prompt = "현재 수집된 보유 종목들의 뉴스를 종합하여, 투자자가 오늘 장에서 반드시 알아야 할 종목별 핵심 리스크 및 주요 이슈를 3줄 요약 양식으로 가독성 좋게 정리해 줘."
            ai_response = ask_gemini_ai(brief_prompt, all_news_context)
            st.session_state.chat_history.append({"role": "assistant", "content": ai_response})

    st.caption("💡 대화 예시: '오늘 종목들 뉴스 요약본 보니까 시장의 리스크가 뭐라고 생각해?'")
    
    for message in st.session_state.chat_history:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            
    if chat_input := st.chat_input("AI 주식 비서에게 실시간 뉴스에 대해 질문해 보세요..."):
        with st.chat_message("user"):
            st.markdown(chat_input)
        st.session_state.chat_history.append({"role": "user", "content": chat_input})
        
        with st.chat_message("assistant"):
            with st.spinner("컨텍스트 파악 및 답변 빌드 중..."):
                ai_answer = ask_gemini_ai(chat_input, all_news_context)
                st.markdown(ai_answer)
        st.session_state.chat_history.append({"role": "assistant", "content": ai_answer})

st.markdown("""
    <style>
    .top-btn { position: fixed; bottom: 20px; right: 20px; background-color: #ff4b4b; color: white !important; padding: 10px 15px; border-radius: 5px; text-decoration: none; font-weight: bold; box-shadow: 2px 2px 5px rgba(0,0,0,0.3); z-index: 999999; }
    .top-btn:hover { background-color: #ff3333; }
    </style>
    <a href="#top_anchor" class="top-btn">▲ TOP</a>
""", unsafe_allow_html=True)

# --- [7] ⏱️ 초정밀 백엔드 클록 루프 ---
if auto_refresh:
    try:
        time.sleep(refresh_rate)
        st.rerun()
    except Exception:
        pass
