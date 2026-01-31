import yfinance as yf
import requests
import os
from datetime import datetime
from anthropic import Anthropic

# 1. 환경 변수 설정
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')
CLAUDE_API_KEY = os.getenv('CLAUDE_API_KEY')

def get_market_data(ticker_symbol):
    ticker = yf.Ticker(ticker_symbol)
    # 넉넉하게 최근 데이터를 가져옵니다
    hist = ticker.history(period="10d") 
    
    current = hist['Close'].iloc[-1]
    yesterday = hist['Close'].iloc[-2]
    one_week = hist['Close'].iloc[-6]
    one_month = hist['Close'].iloc[-22] if len(hist) >= 22 else hist['Close'].iloc[0]
    
    return current, yesterday, one_week, one_month

def format_change(current, prev):
    diff = current - prev
    icon = "🔼" if diff > 0 else "🔽" if diff < 0 else "➖"
    return f"{icon} {abs(diff):.2f}"

def get_claude_insight(report_text):
    client = Anthropic(api_key=CLAUDE_API_KEY)
    prompt = f"다음은 오늘 주요 매크로 지표 데이터야:\n{report_text}\n\n이 지표들을 바탕으로 오늘 주식 투자자가 주의해야 할 점이나 시장 성격을 딱 한 문장(한 줄 평)으로 요약해줘."
    
    message = client.messages.create(
        model="claude-3-5-sonnet-20240620",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text

def send_telegram_msg(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

# 메인 로직
tickers = {
    "미국 10년물 금리": "^TNX",
    "달러 인덱스": "DX-Y.NYB",
    "원/달러 환율": "USDKRW=X",
    "국제 유가(WTI)": "CL=F"
}

report_data = ""
summary_for_claude = ""

for name, symbol in tickers.items():
    cur, yest, w, m = get_market_data(symbol)
    
    # 금리 보정 및 단위 설정
    unit = ""
    if symbol == "^TNX":
        cur, yest, w, m = (val/10 if val > 10 else val for val in [cur, yest, w, m])
        unit = "%"
    
    change_str = format_change(cur, yest)
    report_data += f"📊 **{name}**: {cur:.2f}{unit} ({change_str})\n"
    report_data += f"   - 1주전: {w:.2f} | 1달전: {m:.2f}\n\n"
    summary_for_claude += f"{name}: 현재 {cur:.2f}, 전날대비 {change_str}\n"

# Claude 인사이트 가져오기
try:
    insight = get_claude_insight(summary_for_claude)
except Exception as e:
    insight = "인사이트를 불러오는 중 오류가 발생했습니다."
    print(e)

final_report = f"📅 **매크로 브리핑 ({datetime.now().strftime('%Y-%m-%d')})**\n\n"
final_report += report_data
final_report += f"💡 **Claude 한줄평**\n{insight}"

# 실행
send_telegram_msg(final_report)