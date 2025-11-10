import os, json, urllib.parse, urllib.request, datetime

# ===== 설정 =====
ADDRESS = "서울시 마포구 독막로 211"   # 기준 주소(출력은 안 함)
TZ = "Asia/Seoul"
WEBHOOK = os.environ["SLACK_WEBHOOK_URL"]

# ===== 공용 유틸 =====
def http_get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8")

def geocode(address):
    q = urllib.parse.urlencode({"q": address, "format": "json", "limit": 1})
    url = f"https://nominatim.openstreetmap.org/search?{q}"
    txt = http_get(url, headers={"User-Agent": "weather-bot"})
    data = json.loads(txt)
    lat = float(data[0]["lat"])
    lon = float(data[0]["lon"])
    return lat, lon

def fetch_weather(lat, lon):
    params = {
        "latitude": lat, "longitude": lon,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode,precipitation_probability_max",
        "timezone": TZ,
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)
    data = json.loads(http_get(url))
    d = data["daily"]
    return {
        "tmax": round(d["temperature_2m_max"][0]),
        "tmin": round(d["temperature_2m_min"][0]),
        "rain": d["precipitation_sum"][0],
        "wcode": d["weathercode"][0],
        "pop": d["precipitation_probability_max"][0],
    }

def describe_weather_kor(code):
    # 이모지 + 한글 설명 반환
    if code == 0: return "☀️ 맑음"
    if code in (1,2): return "🌤️ 구름 조금"
    if code == 3: return "☁️ 흐림"
    if code in (45,48): return "🌫️ 안개"
    if code in (51,53,55,56,57): return "🌦️ 이슬비"
    if code in (61,63,65,66,67): return "🌧️ 비"
    if code in (80,81,82): return "🌦️ 소나기"
    if code in (95,96,99): return "⛈️ 뇌우"
    return "변동성 있음"

def outfit_suggestion(tmin, tmax, pop, rain):
    # 상/하의와 추가 준비물까지 dict로 반환
    avg = (tmin + tmax) / 2
    if avg >= 28: top,bottom="얇은 반팔 티/린넨 셔츠","반바지"
    elif avg >= 23: top,bottom="반팔 또는 얇은 셔츠","가벼운 슬랙스"
    elif avg >= 20: top,bottom="얇은 가디건/셔츠","청바지"
    elif avg >= 17: top,bottom="가벼운 자켓/니트","면바지"
    elif avg >= 12: top,bottom="얇은 코트/자켓 + 니트","긴바지"
    elif avg >= 9:  top,bottom="코트/두꺼운 가디건","기모 바지"
    elif avg >= 5:  top,bottom="두꺼운 코트 + 니트","기모 바지"
    else: top,bottom="패딩/목도리/장갑","내복 + 긴바지"
    extras=[]
    if pop >= 60 or rain >= 1: extras.append("☂️ 우산")
    if (tmax - tmin) >= 10:   extras.append("🧥 얇은 겉옷")
    return {"top": top, "bottom": bottom, "extras": extras}

def post_blocks_to_slack(blocks, fallback_text=""):
    payload = {"mrkdwn": True, "text": fallback_text, "blocks": blocks}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(WEBHOOK, data, headers={"Content-Type":"application/json"})
    urllib.request.urlopen(req)

# ===== 메인 =====
def main():
    # 주말 제외 (토:5, 일:6)
    today = datetime.date.today()
    if today.weekday() >= 5:
        return

    lat, lon = geocode(ADDRESS)
    w = fetch_weather(lat, lon)
    cond = describe_weather_kor(w["wcode"])
    cond_emoji = cond.split(" ")[0] if " " in cond else ""
    cond_text  = cond.split(" ", 1)[1] if " " in cond else cond

    outfit = outfit_suggestion(w["tmin"], w["tmax"], w["pop"], w["rain"])

    # --- Block Kit 구성 ---
    header_text = "오늘의 날씨 • 서울 마포구"
    intro = f"좋은 아침입니다! {cond} 오늘의 서울 마포구 날씨를 알려드릴게요!"

    fields = [
        {"type":"mrkdwn", "text": f"*최저*\n{w['tmin']}°C"},
        {"type":"mrkdwn", "text": f"*최고*\n{w['tmax']}°C"},
        {"type":"mrkdwn", "text": f"*날씨*\n{cond_text}"},
        {"type":"mrkdwn", "text": f"*강수확률*\n{w['pop']}%"},
    ]
    # 강수량 정보가 0이 아닐 때만 표시
    if w["rain"] and round(w["rain"],1) != 0:
        fields.append({"type":"mrkdwn", "text": f"*강수량*\n{round(w['rain'],1)} mm"})

    outfit_lines = [
        "*오늘의 옷차림 추천 👕*",
        f"상의 - {outfit['top']}",
        f"하의 - {outfit['bottom']}"
    ]
    if outfit["extras"]:
        outfit_lines.append(f"추가 준비물: {', '.join(outfit['extras'])}")

    blocks = [
        {"type":"header", "text":{"type":"plain_text", "text": header_text, "emoji": True}},
        {"type":"section", "text":{"type":"mrkdwn", "text": intro}},
        {"type":"section", "fields": fields},
        {"type":"divider"},
        {"type":"section", "text":{"type":"mrkdwn", "text": "\n".join(outfit_lines)}},
        {"type":"context", "elements":[
            {"type":"mrkdwn", "text":"매일 *07:30* 자동 발송 · 주말 제외"},
            {"type":"mrkdwn", "text":"데이터: Open-Meteo"}
        ]}
    ]

    fallback = f"{cond_emoji} 최저 {w['tmin']} / 최고 {w['tmax']} · {cond_text}"
    post_blocks_to_slack(blocks, fallback_text=fallback)

if __name__ == "__main__":
    main()
