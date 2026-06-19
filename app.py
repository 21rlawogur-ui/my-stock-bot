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

# ⭐️ [핵심 패치] 네이버 및 야후 차단 방지용 일반 브라우저 위장 신분증
STANDARD_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
}
NAVER_HEADERS = STANDARD_HEADERS.copy()
NAVER_HEADERS["Referer"] = "https://finance.naver.com/"

# ⭐️ 야후 파이낸스 전용 로봇 우회 세션 생성
yf_session = requests.Session()
yf_session.headers.update(STANDARD_HEADERS)

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

@st.cache_data(ttl=30)
def get_global_live_data(ticker):
    try:
        stock = yf.Ticker(ticker, session=yf_session)
        hist = stock.history(period="2d")
        if not hist.empty and len(hist) >= 1:
            cur = hist['Close'].iloc[-1]
            change = 0.0
            if len(hist) >= 2:
                change = ((cur - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2]) * 100
            st.session_state.shadow_cache[ticker] = (cur, change)
            return cur, change
        raise ValueError("yfinance 응답 없음")
    except Exception as e:
        st.session_state.error_log = f"❌ 해외 갱신 실패 ({ticker}): {str(e)}"
        return st.session_state.shadow_cache.get(ticker, (0.0, 0.0))

@st.cache_data(ttl=86400)
def get_heavy_market_cap(ticker):
    if ticker in ["KOSPI", "KOSDAQ", "^GSPC", "^IXIC", "^DJI"]: return 1
    try: 
        stock = yf.Ticker(ticker, session=yf_session)
        return stock.info.get('marketCap', 1)
    except: return 1

# --- 📰 구글 실시간 뉴스 RSS 수집 엔진 ---
@st.cache_data(ttl=1800) 
def fetch_stock_news(ticker, name, is_kr):
    news_list = []
    try:
        query_str = f"{name} 주식" if is_kr else f"{name}
