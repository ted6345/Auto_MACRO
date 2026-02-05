import yfinance as yf
import requests
import os
import re
from datetime import datetime
from anthropic import Anthropic

# 1. 환경 변수 설정
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")


def get_market_data(ticker_symbol):
    ticker = yf.Ticker(ticker_symbol)
    # 넉넉하게 최근 데이터를 가져옵니다
    hist = ticker.history(period="10d")

    current = hist["Close"].iloc[-1]
    yesterday = hist["Close"].iloc[-2]
    one_week = hist["Close"].iloc[-6]
    one_month = hist["Close"].iloc[-22] if len(hist) >= 22 else hist["Close"].iloc[0]

    return current, yesterday, one_week, one_month


def format_change(current, prev):
    diff = current - prev
    icon = "🔼" if diff > 0 else "🔽" if diff < 0 else "➖"
    return f"{icon} {abs(diff):.2f}"


def get_fear_greed_index():
    """공포/탐욕 지수 가져오기 (Alternative.me API 사용)"""
    try:
        url = "https://api.alternative.me/fng/"
        response = requests.get(url, timeout=10)
        data = response.json()
        if data and "data" in data and len(data["data"]) > 0:
            current = int(data["data"][0]["value"])
            yesterday = (
                int(data["data"][1]["value"]) if len(data["data"]) > 1 else current
            )

            # 지수에 따른 이모지
            if current >= 75:
                emoji = "😱"  # 극도의 탐욕
                status = "극도의 탐욕"
            elif current >= 55:
                emoji = "😊"  # 탐욕
                status = "탐욕"
            elif current >= 45:
                emoji = "😐"  # 중립
                status = "중립"
            elif current >= 25:
                emoji = "😰"  # 공포
                status = "공포"
            else:
                emoji = "😨"  # 극도의 공포
                status = "극도의 공포"

            return current, yesterday, emoji, status
    except Exception as e:
        print(f"공포/탐욕 지수 가져오기 실패: {e}")
    return None, None, "❓", "데이터 없음"


def get_korea_bond_yield():
    """한국 국채 금리 가져오기 (investing.com 스크래핑)"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        }

        yield_3y = None
        yield_10y = None

        # 3년물 국채 금리
        try:
            url_3y = (
                "https://kr.investing.com/rates-bonds/south-korea-3-year-bond-yield"
            )
            response_3y = requests.get(url_3y, headers=headers, timeout=10)
            if response_3y.status_code == 200:
                # 여러 패턴 시도
                patterns = [
                    r'data-test="instrument-price-last">([\d.]+)</span>',
                    r'class="text-2xl[^"]*">([\d.]+)</span>',
                    r'"last_last"[^>]*>([\d.]+)</span>',
                    r'<span[^>]*id="last_last"[^>]*>([\d.]+)</span>',
                    r'<span[^>]*class="[^"]*text-[^"]*"[^>]*>([\d.]+)</span>',
                ]
                for pattern in patterns:
                    match_3y = re.search(pattern, response_3y.text)
                    if match_3y:
                        yield_3y = float(match_3y.group(1))
                        break
        except Exception as e:
            print(f"3년물 국채 금리 가져오기 실패: {e}")

        # 10년물 국채 금리
        try:
            url_10y = (
                "https://kr.investing.com/rates-bonds/south-korea-10-year-bond-yield"
            )
            response_10y = requests.get(url_10y, headers=headers, timeout=10)
            if response_10y.status_code == 200:
                patterns = [
                    r'data-test="instrument-price-last">([\d.]+)</span>',
                    r'class="text-2xl[^"]*">([\d.]+)</span>',
                    r'"last_last"[^>]*>([\d.]+)</span>',
                    r'<span[^>]*id="last_last"[^>]*>([\d.]+)</span>',
                    r'<span[^>]*class="[^"]*text-[^"]*"[^>]*>([\d.]+)</span>',
                ]
                for pattern in patterns:
                    match_10y = re.search(pattern, response_10y.text)
                    if match_10y:
                        yield_10y = float(match_10y.group(1))
                        break
        except Exception as e:
            print(f"10년물 국채 금리 가져오기 실패: {e}")

        return yield_3y, yield_10y
    except Exception as e:
        print(f"한국 국채 금리 가져오기 실패: {e}")
    return None, None


def get_claude_insight(report_text):
    client = Anthropic(api_key=CLAUDE_API_KEY)
    prompt = f"다음은 오늘 주요 매크로 지표 데이터야:\n{report_text}\n\n이 지표들을 바탕으로 오늘 주식 투자자가 주의해야 할 점이나 시장 성격을 딱 한 문장(한 줄 평)으로 요약해줘."

    message = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def send_telegram_msg(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    requests.post(url, json=payload)


# 메인 로직
# 글로벌 지표
global_tickers = {
    "미국 10년물 금리": "^TNX",
    "달러 인덱스": "DX-Y.NYB",
    "원/달러 환율": "USDKRW=X",
    "국제 유가(WTI)": "CL=F",
    "금 가격": "GC=F",
    "비트코인": "BTC-USD",
    "S&P500": "^GSPC",
    "VIX": "^VIX",
}

# 한국 시장 지표
korea_tickers = {"KOSPI": "^KS11", "KOSDAQ": "^KQ11", "원/엔 환율": "JPYKRW=X"}

report_data = ""
summary_for_claude = ""

# 공포/탐욕 지수 먼저 추가
fear_greed_current, fear_greed_yest, fg_emoji, fg_status = get_fear_greed_index()
if fear_greed_current is not None:
    fg_change_str = format_change(fear_greed_current, fear_greed_yest)
    report_data += f"📊 **공포/탐욕 지수**: {fg_emoji} {fear_greed_current} ({fg_status}) ({fg_change_str})\n\n"
    summary_for_claude += f"공포/탐욕 지수: {fear_greed_current} ({fg_status})\n"

# 한국 시장 지표 섹션
report_data += "🇰🇷 **한국 시장**\n\n"

# 한국 국채 금리 먼저 추가
yield_3y, yield_10y = get_korea_bond_yield()
if yield_3y is not None:
    report_data += f"📊 **한국 3년물 국채 금리**: {yield_3y:.2f}%\n"
    summary_for_claude += f"한국 3년물 국채 금리: {yield_3y:.2f}%\n"
else:
    report_data += "📊 **한국 3년물 국채 금리**: 데이터 없음\n"
if yield_10y is not None:
    report_data += f"📊 **한국 10년물 국채 금리**: {yield_10y:.2f}%\n\n"
    summary_for_claude += f"한국 10년물 국채 금리: {yield_10y:.2f}%\n"
else:
    report_data += "📊 **한국 10년물 국채 금리**: 데이터 없음\n\n"

for name, symbol in korea_tickers.items():
    try:
        cur, yest, w, m = get_market_data(symbol)

        unit = ""
        if symbol in ["^KS11", "^KQ11"]:  # KOSPI, KOSDAQ
            unit = " 포인트"
        elif symbol == "JPYKRW=X":  # 원/엔 환율
            unit = " 원"

        change_str = format_change(cur, yest)
        # 변동률 계산
        change_pct = ((cur - yest) / yest * 100) if yest != 0 else 0
        change_pct_str = f"{change_pct:+.2f}%"

        report_data += (
            f"📊 **{name}**: {cur:.2f}{unit} ({change_str}, {change_pct_str})\n"
        )
        report_data += f"   - 1주전: {w:.2f} | 1달전: {m:.2f}\n\n"
        summary_for_claude += f"{name}: 현재 {cur:.2f}, 전날대비 {change_pct_str}\n"
    except Exception as e:
        print(f"{name} 데이터 가져오기 실패: {e}")
        report_data += f"📊 **{name}**: 데이터 없음\n\n"

# 글로벌 지표 섹션
report_data += "🌍 **글로벌 지표**\n\n"
for name, symbol in global_tickers.items():
    try:
        cur, yest, w, m = get_market_data(symbol)

        # 금리 보정 및 단위 설정
        unit = ""
        if symbol == "^TNX":
            cur, yest, w, m = (
                val / 10 if val > 10 else val for val in [cur, yest, w, m]
            )
            unit = "%"
        elif symbol in ["GC=F", "CL=F"]:  # 금, 유가
            unit = " USD/oz" if symbol == "GC=F" else " USD/배럴"
        elif symbol == "BTC-USD":
            unit = " USD"
        elif symbol == "^VIX":
            unit = ""
        elif symbol == "USDKRW=X":  # 원/달러 환율
            unit = " 원"
        elif symbol in ["^GSPC", "DX-Y.NYB"]:  # S&P500, 달러 인덱스
            unit = " 포인트" if symbol == "^GSPC" else ""

        change_str = format_change(cur, yest)
        report_data += f"📊 **{name}**: {cur:.2f}{unit} ({change_str})\n"
        report_data += f"   - 1주전: {w:.2f} | 1달전: {m:.2f}\n\n"
        summary_for_claude += f"{name}: 현재 {cur:.2f}, 전날대비 {change_str}\n"
    except Exception as e:
        print(f"{name} 데이터 가져오기 실패: {e}")
        report_data += f"📊 **{name}**: 데이터 없음\n\n"

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
