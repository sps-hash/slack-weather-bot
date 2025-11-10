import os, json, urllib.parse, urllib.request, datetime

ADDRESS = "서울 마포구"
TZ = "Asia/Seoul"
WEBHOOK = os.environ["SLACK_WEBHOOK_URL"]

def http_get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8")

def geocode(address):
    q = urllib.parse.urlencode({"q": address, "format": "json", "limit": 1})
    url = f"https://nominatim.openstreetmap.org/search?{q}"
    data = json.loads(http_get(url, headers={"User-Agent": "weather-bot"}))
    return float(data[0]["lat"]), float(data[0]["lon"])

def fetch_weather(lat, lon):
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode,precipitation_probability_max",
        "timezone": TZ,
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)
    data = json.loads(http_get(url))
    d = data["daily"]
    return {
        "tmin": d["temperature_2m_min"][0],
        "tmax": d["temperature_2m_max"][0],
        "wcode": d["weathercode"][0],
        "pop": d["precipitation_probability_max"][0],
        "rain": d["precipitation_sum"][0],
    }

def describe_weather_kor(code):
    mapping = {
        0: "☀️ 맑음", 1: "🌤️ 대체로 맑음", 2: "⛅ 구름 조금", 3: "☁️ 흐림",
        45: "🌫️ 안개", 48: "🌫️ 서리 낀 안개",
        51: "🌦️ 약한 이슬비", 61: "🌧️ 약한 비", 63: "🌧️ 비", 65: "🌧️ 강한 비",
        71: "🌨️ 약한 눈", 73: "🌨️ 눈", 75: "❄️ 강한 눈",
        95: "⛈️ 뇌우", 99: "⛈️ 우박을 동반한 뇌우"
    }
    return mapping.get(code, "🌈 알 수 없음")

def outfit_suggestion(tmin, tmax, pop, rain):
    avg = (tmin + tmax) / 2
    if rain > 0 or pop >= 60:
        extra = "\n추가 준비물: ☂️ 우산"
    else:
        extra = ""
    if avg >= 25:
        return f"상의 - 반팔 + 얇은 셔츠\n하의 - 반바지{extra}"
    elif avg >= 20:
        return f"상의 - 얇은 셔츠 + 가디건\n하의 - 면바지{extra}"
    elif avg >= 10:
        return f"상의 - 두꺼운 코트 + 니트\n하의 - 기모 바지{extra}"
    elif avg >= 0:
        return f"상의 - 패딩 + 스웨터\n하의 - 기모 바지{extra}"
    else:
        return f"상의 - 두꺼운 패딩 + 목도리\n하의 - 히트텍{extra}"

def post_to_slack(text):
    data = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(WEBHOOK, data=data, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req)

def main():
    # 🗓️ 주말 제외 (토/일에는 실행 안 함)
    today = datetime.datetime.now().date()
    if today.weekday() >= 5:
        print("주말이므로 전송 안 함")
        return

    lat, lon = geocode(ADDRESS)
    w = fetch_weather(lat, lon)

    cond = describe_weather_kor(w["wcode"])
    cond_emoji = cond.split(" ")[0] if " " in cond else ""
    cond_text = cond.split(" ", 1)[1] if " " in cond else cond
    outfit = outfit_suggestion(w["tmin"], w["tmax"], w["pop"], w["rain"])

    # 🌤️ 줄바꿈 적용된 인사 문구
    intro = f"좋은 아침입니다! {cond_emoji}\n오늘의 서울 마포구 날씨를 알려드릴게요!"

    message = f"""
{intro}

*최저* {w['tmin']}°C  *최고* {w['tmax']}°C
*날씨* {cond_text}  *강수확률* {w['pop']}%

———————————————
*오늘의 옷차림 추천 👕*
{outfit}

_매일 07:30 자동 발송 · 주말 제외_  
_데이터: Open-Meteo_
"""
    post_to_slack(message)
    print("전송 완료 ✅")

if __name__ == "__main__":
    main()
