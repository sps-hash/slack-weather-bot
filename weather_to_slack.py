# weather_to_slack.py
# - 평일 07:30 자동 발송 (Actions에서 스케줄)
# - 상단 타이틀 없음, 인사 2줄
# - 최저/최고/날씨/강수확률은 필드형(정렬 유지)
# - 일교차(최고-최저) 기반 레이어링 팁 포함
# - 하단 꼬릿말 제거

import os, json, urllib.parse, urllib.request, datetime as dt

# ── 설정값 ──────────────────────────────────────────────────────────────────────
ADDRESS = "서울 마포구"                 # 출력에는 쓰지 않지만 위치 계산용
TZ = "Asia/Seoul"
WEBHOOK = os.environ["SLACK_WEBHOOK_URL"]  # Incoming Webhook URL (secret)

# ── 공통 HTTP ──────────────────────────────────────────────────────────────────
def http_get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8")

# ── 지오코딩 (OSM Nominatim) ───────────────────────────────────────────────────
def geocode(address: str):
    q = urllib.parse.urlencode({"q": address, "format": "json", "limit": 1})
    url = f"https://nominatim.openstreetmap.org/search?{q}"
    data = json.loads(http_get(url, headers={"User-Agent": "slack-weather-bot"}))
    return float(data[0]["lat"]), float(data[0]["lon"])

# ── 날씨 조회 (Open-Meteo) ─────────────────────────────────────────────────────
def fetch_weather(lat: float, lon: float):
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode,precipitation_probability_max",
        "timezone": TZ,
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)
    d = json.loads(http_get(url))["daily"]
    return {
        "tmin": round(d["temperature_2m_min"][0]),
        "tmax": round(d["temperature_2m_max"][0]),
        "pop": int(d["precipitation_probability_max"][0]),  # %
        "rain": float(d["precipitation_sum"][0]),           # mm
        "wcode": int(d["weathercode"][0]),
    }

# ── 하늘상태 텍스트/이모지 ─────────────────────────────────────────────────────
def describe_weather_kor(code: int):
    mapping = {
        0: "☀️ 맑음", 1: "🌤️ 대체로 맑음", 2: "⛅ 구름 조금", 3: "☁️ 흐림",
        45: "🌫️ 안개", 48: "🌫️ 서리 낀 안개",
        51: "🌦️ 약한 이슬비", 53: "🌦️ 이슬비", 55: "🌦️ 강한 이슬비",
        61: "🌧️ 약한 비", 63: "🌧️ 비", 65: "🌧️ 강한 비",
        66: "🌧️ 어는 비", 67: "🌧️ 강한 어는 비",
        71: "🌨️ 약한 눈", 73: "🌨️ 눈", 75: "❄️ 강한 눈",
        80: "🌦️ 소나기", 81: "🌦️ 소나기", 82: "🌦️ 강한 소나기",
        95: "⛈️ 뇌우", 96: "⛈️ 우박 동반 뇌우", 99: "⛈️ 강한 우박 뇌우",
    }
    return mapping.get(code, "🌈 변동성")

# ── 옷차림 추천 (일교차 레이어링 포함, 모순 회피) ────────────────────────────────
def outfit_suggestion(tmin: int, tmax: int, pop: int, rain: float):
    # 1) 기본 복장 단계(최고기온 기준)
    if tmax <= 8:
        band = "heavy"
        top, bottom = "두꺼운 코트 + 니트", "기모 바지"
    elif tmax <= 17:
        band = "mid"
        top, bottom = "가벼운 코트/자켓 + 니트", "면바지"
    elif tmax <= 22:
        band = "light"
        top, bottom = "셔츠 또는 얇은 맨투맨", "슬랙스/면바지"
    elif tmax <= 26:
        band = "warm"
        top, bottom = "반팔 + 얇은 셔츠", "린넨/슬랙스"
    else:
        band = "hot"
        top, bottom = "반팔", "반바지/통풍 좋은 하의"

    extras = []

    # 2) 강수 보정
    if rain > 0 or pop >= 60:
        extras.append("☂️ 우산")
    elif pop >= 40:
        extras.append("우산 챙기면 든든")

    # 3) 일교차 레이어링 보정 (겹쳐입기 중심)
    diff = tmax - tmin
    if diff >= 12:
        if band == "heavy":
            extras.append("레이어드: 히트텍 + 셔츠 + 코트 (실내에서 한 겹 벗기)")
        elif band in ("mid", "light"):
            extras.append("레이어드: 얇은 이너 + 가디건/자켓 (낮엔 벗기)")
        else:
            extras.append("얇은 셔츠 위에 가벼운 가디건")
    elif diff >= 8:
        if band == "heavy":
            extras.append("얇은 이너 + 니트로 겹쳐입기")
        elif band in ("mid", "light"):
            extras.append("가디건 하나면 충분")
        else:
            extras.append("실내 에어컨 대비 가벼운 겉옷")

    return {"top": top, "bottom": bottom, "extras": extras}

# ── Slack 전송 ─────────────────────────────────────────────────────────────────
def post_blocks_to_slack(blocks, fallback=""):
    payload = {"mrkdwn": True, "text": fallback, "blocks": blocks}
    req = urllib.request.Request(
        WEBHOOK, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    urllib.request.urlopen(req)

# ── 메인 ───────────────────────────────────────────────────────────────────────
def main():
    # 주말(토/일) 제외
    if dt.date.today().weekday() >= 5:
        print("Weekend: skip")
        return

    lat, lon = geocode(ADDRESS)
    w = fetch_weather(lat, lon)

    cond = describe_weather_kor(w["wcode"])
    cond_emoji = cond.split(" ")[0] if " " in cond else ""
    cond_text  = cond.split(" ", 1)[1] if " " in cond else cond

    outfit = outfit_suggestion(w["tmin"], w["tmax"], w["pop"], w["rain"])

    # 인사 2줄 (타이틀 없음)
    intro = f"좋은 아침입니다! {cond_emoji}\n오늘의 서울 마포구 날씨를 알려드릴게요!"

    # 필드(정렬) 섹션
    fields = [
        {"type":"mrkdwn", "text": "*최저*\n" + f"{w['tmin']}°C"},
        {"type":"mrkdwn", "text": "*최고*\n" + f"{w['tmax']}°C"},
        {"type":"mrkdwn", "text": "*날씨*\n" + cond_text},
        {"type":"mrkdwn", "text": "*강수확률*\n" + f"{w['pop']}%"},
    ]
    if round(w["rain"], 1) > 0:
        fields.append({"type":"mrkdwn", "text": "*강수량*\n" + f"{round(w['rain'],1)} mm"})

    # 옷차림 섹션
    outfit_lines = [
        "*오늘의 옷차림 추천 👕*",
        f"상의 - {outfit['top']}",
        f"하의 - {outfit['bottom']}",
    ]
    if outfit["extras"]:
        outfit_lines.append("추가 팁: " + " / ".join(outfit["extras"]))

    blocks = [
        {"type":"section", "text":{"type":"mrkdwn", "text": intro}},
        {"type":"section", "fields": fields},
        {"type":"divider"},
        {"type":"section", "text":{"type":"mrkdwn", "text": "\n".join(outfit_lines)}},
    ]

    fallback = f"{cond_emoji} 최저 {w['tmin']}° / 최고 {w['tmax']}° · {cond_text}"
    post_blocks_to_slack(blocks, fallback=fallback)
    print("Sent ✅")

if __name__ == "__main__":
    main()
