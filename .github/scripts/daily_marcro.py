import yfinance as yf
import requests
import os
from datetime import datetime

# GitHub Secrets에서 정보를 가져옵니다
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')

def get_market_data(ticker_symbol):
    ticker = yf.Ticker(ticker_symbol)
    hist = ticker.history(period="400d")
    current = hist['Close'].iloc[-1]
    day_before = hist['Close'].iloc[-2]
    one_week = hist['Close'].iloc[-6]
    one_month = hist['Close'].iloc[-22]
    one_year = hist['Close'].iloc[-252]
    return current, day_before, one_week, one_month, one_year

def send_telegram_msg(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

tickers = {"미국 10년물 금리(%)": "^TNX", "달러 인덱스": "DX-Y.NYB", "원/달러 환율(원)": "USDKRW=X", "국제 유가(WTI, $)": "CL=F"}
report = f"📅 **매크로 브리핑 ({datetime.now().strftime('%Y-%m-%d')})**\n\n"

for name, symbol in tickers.items():
    cur, day_before, w, m, y = get_market_data(symbol)
    if symbol == "^TNX": cur, day_before, w, m, y = cur/10, day_before/10, w/10, m/10, y/10
    report += f"📊 **{name}**\n- 현재: {cur:.2f}\n- 전날: {day_before:.2f} | 1주전: {w:.2f} | 1달전: {m:.2f}\n\n"

send_telegram_msg(report)