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
    # Telegram Markdown에서는 텍스트 색상 지정이 불가하므로 아이콘으로 대체합니다.
    # 상승: 🔴 / 하락: 🔵 / 보합: ⚪
    icon = "🔴" if diff > 0 else "🔵" if diff < 0 else "⚪"
    return f"{icon} {diff:+.2f}"


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
    """한국 국채 금리 가져오기

    우선순위:
    1) 네이버 금융(상대적으로 안정적)
    2) investing.com(가끔 차단/구조변경 이슈가 있어 fallback)
    """
    try:

        def _sanitize_yield(val):
            if val is None:
                return None
            # 상식적인 범위 체크 (0% ~ 20% 정도로 제한)
            if val < 0 or val > 20:
                return None
            return val

        def _parse_naver_no_today(html: str):
            m = re.search(r'no_today">[\s\S]*?<em[^>]*>([\s\S]*?)</em>', html)
            if not m:
                return None
            em_html = m.group(1)
            parts = re.findall(r'<span class="(?:no\d|jum)">([^<]+)</span>', em_html)
            if not parts:
                return None
            try:
                return float("".join(parts))
            except Exception:
                return None

        def _parse_naver_exday_diff(html: str):
            # 전일대비 숫자(절대 변화폭, %p)를 signed float로 반환
            m = re.search(r'no_exday">[\s\S]*?<em[^>]*>([\s\S]*?)</em>', html)
            if not m:
                return None
            em_html = m.group(1)
            sign = 0
            if "ico up" in em_html:
                sign = 1
            elif "ico down" in em_html:
                sign = -1
            elif "ico same" in em_html:
                sign = 0
            parts = re.findall(r'<span class="(?:no\d|jum)">([^<]+)</span>', em_html)
            if not parts:
                return None
            try:
                val = float("".join(parts))
                return val * sign
            except Exception:
                return None

        def _get_naver_interest_rate_and_diff(marketindex_cd: str):
            # 예: IRR_GOVT03Y, IRR_GOVT10Y
            url = (
                "https://finance.naver.com/marketindex/interestDetail.naver"
                f"?marketindexCd={marketindex_cd}"
            )
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            }
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code != 200:
                return None, None

            html = resp.text
            cur = _parse_naver_no_today(html)
            diff = _parse_naver_exday_diff(html)
            return cur, diff

        def _get_fred_latest_and_prev(series_id: str):
            # FRED는 API 키 없이 CSV로 최신값(월간 등)을 받을 수 있음
            url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
            resp = requests.get(url, timeout=10)
            if resp.status_code != 200:
                return None, None
            lines = [ln.strip() for ln in resp.text.splitlines() if ln.strip()]
            # header 제외하고 뒤에서부터 유효한 값 찾기
            latest = None
            prev = None
            for ln in reversed(lines[1:]):
                try:
                    _date, val = ln.split(",", 1)
                    if val == ".":
                        continue
                    if latest is None:
                        latest = float(val)
                        continue
                    prev = float(val)
                    break
                except Exception:
                    continue
            return latest, prev

        # 1) 네이버 시도 (국고채 3년은 네이버에 잘 나옴)
        y3_raw, y3_diff = _get_naver_interest_rate_and_diff("IRR_GOVT03Y")
        y10_raw, y10_diff = _get_naver_interest_rate_and_diff("IRR_GOVT10Y")
        y3 = _sanitize_yield(y3_raw)
        y10 = _sanitize_yield(y10_raw)
        if y3 is None:
            y3_diff = None
        if y10 is None:
            y10_diff = None

        # 2) investing.com fallback
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        }

        yield_3y = y3
        yield_10y = y10
        source_3y = "NAVER" if y3 is not None else None
        source_10y = "NAVER" if y10 is not None else None
        diff_3y = y3_diff
        diff_10y = y10_diff

        def _get_investing(url: str):
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code != 200:
                return None
            # 너무 broad한 패턴은 오탐이 나서, 상대적으로 좁은 패턴만 사용
            patterns = [
                r'data-test="instrument-price-last">([\d.]+)</span>',
                r'<span[^>]*id="last_last"[^>]*>([\d.]+)</span>',
            ]
            for pattern in patterns:
                m = re.search(pattern, resp.text)
                if m:
                    try:
                        return float(m.group(1))
                    except Exception:
                        return None
            return None

        try:
            if yield_3y is None:
                yield_3y = _sanitize_yield(
                    _get_investing(
                        "https://kr.investing.com/rates-bonds/south-korea-3-year-bond-yield"
                    )
                )
                if yield_3y is not None:
                    source_3y = "INVESTING"
                    diff_3y = None  # 현재는 investing에서 diff 미지원
        except Exception as e:
            print(f"3년물 국채 금리 가져오기 실패: {e}")

        try:
            if yield_10y is None:
                yield_10y = _sanitize_yield(
                    _get_investing(
                        "https://kr.investing.com/rates-bonds/south-korea-10-year-bond-yield"
                    )
                )
                if yield_10y is not None:
                    source_10y = "INVESTING"
                    diff_10y = None  # 현재는 investing에서 diff 미지원
        except Exception as e:
            print(f"10년물 국채 금리 가져오기 실패: {e}")

        # 마지막 fallback: FRED(월간 데이터일 수 있음)
        if yield_10y is None:
            latest, prev = _get_fred_latest_and_prev("IRLTLT01KRM156N")
            latest = _sanitize_yield(latest)
            prev = _sanitize_yield(prev)
            if latest is not None:
                yield_10y = latest
                source_10y = "FRED"
                diff_10y = (latest - prev) if prev is not None else None

        return yield_3y, diff_3y, yield_10y, diff_10y, source_3y, source_10y
    except Exception as e:
        print(f"한국 국채 금리 가져오기 실패: {e}")
    return None, None, None, None, None, None


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
korea_tickers = {"KOSPI": "^KS11", "KOSDAQ": "^KQ11"}

report_data = ""
summary_for_claude = ""

# 공포/탐욕 지수 먼저 추가
fear_greed_current, fear_greed_yest, fg_emoji, fg_status = get_fear_greed_index()
if fear_greed_current is not None:
    fg_change_str = format_change(fear_greed_current, fear_greed_yest)
    report_data += f"📊 **공포/탐욕 지수**: {fg_emoji} {fear_greed_current} ({fg_status}) ({fg_change_str})\n\n"
    summary_for_claude += f"공포/탐욕 지수: {fear_greed_current} ({fg_status})\n"

# 한국 시장 지표 섹션
report_data += "🇰🇷 **한국 시장**\n"

# 한국 국채 금리 먼저 추가
yield_3y, yield_3y_diff, yield_10y, yield_10y_diff, yield_3y_src, yield_10y_src = (
    get_korea_bond_yield()
)
if yield_3y is not None:
    if yield_3y_diff is not None:
        report_data += (
            f"  - 📊 **한국 3년물 국채 금리**: {yield_3y:.2f}% "
            f"({format_change(yield_3y, yield_3y - yield_3y_diff)})\n"
        )
    else:
        report_data += f"  - 📊 **한국 3년물 국채 금리**: {yield_3y:.2f}%\n"
    summary_for_claude += f"한국 3년물 국채 금리: {yield_3y:.2f}%\n"
else:
    report_data += "  - 📊 **한국 3년물 국채 금리**: 데이터 없음\n"

# 3년물/10년물 사이 가독성용 개행
report_data += "\n"

if yield_10y is not None:
    yield_10y_note = " (FRED·월간)" if yield_10y_src == "FRED" else ""
    if yield_10y_diff is not None:
        report_data += (
            f"  - 📊 **한국 10년물 국채 금리**{yield_10y_note}: {yield_10y:.2f}% "
            f"({format_change(yield_10y, yield_10y - yield_10y_diff)})\n"
        )
    else:
        report_data += (
            f"  - 📊 **한국 10년물 국채 금리**{yield_10y_note}: {yield_10y:.2f}%\n"
        )
    summary_for_claude += f"한국 10년물 국채 금리{yield_10y_note}: {yield_10y:.2f}%\n"
else:
    report_data += "  - 📊 **한국 10년물 국채 금리**: 데이터 없음\n"

report_data += "\n"

for name, symbol in korea_tickers.items():
    try:
        cur, yest, w, m = get_market_data(symbol)

        unit = ""
        if symbol in ["^KS11", "^KQ11"]:  # KOSPI, KOSDAQ
            unit = " 포인트"
        # 원/엔 환율은 제거됨

        change_str = format_change(cur, yest)
        # 변동률 계산
        change_pct = ((cur - yest) / yest * 100) if yest != 0 else 0
        change_pct_icon = "🔴" if change_pct > 0 else "🔵" if change_pct < 0 else "⚪"
        change_pct_str = f"{change_pct_icon} {change_pct:+.2f}%"

        report_data += (
            f"  - 📊 **{name}**: {cur:.2f}{unit} ({change_str}, {change_pct_str})\n"
        )
        report_data += f"      - 1주전: {w:.2f} | 1달전: {m:.2f}\n\n"
        summary_for_claude += f"{name}: 현재 {cur:.2f}, 전날대비 {change_pct_str}\n"
    except Exception as e:
        print(f"{name} 데이터 가져오기 실패: {e}")
        report_data += f"  - 📊 **{name}**: 데이터 없음\n\n"

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
        report_data += f"- 📊 **{name}**: {cur:.2f}{unit} ({change_str})\n"
        report_data += f"    - 1주전: {w:.2f} | 1달전: {m:.2f}\n\n"
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

# 로그(가독성 확인용 출력)
# - final_report는 항상 출력 (Actions 로그에서 확인)
# - summary_for_claude / report_data는 DEBUG_PRINT=1 일 때만 출력
debug_print = os.getenv("DEBUG_PRINT", "").strip().lower() in ("1", "true", "yes")
if debug_print:
    print("----- summary_for_claude -----")
    print(summary_for_claude)
    print("----- report_data -----")
    print(report_data)
print("----- final_report -----")
print(final_report)

# 실행
send_telegram_msg(final_report)
