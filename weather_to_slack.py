# weather_to_slack.py
# 포맷: 인사(2줄) → [최저/최고/날씨/강수확률(+강수량)] → ───────── → 오늘의 옷차림(상의/하의) → 💡 추가 팁(☑️ bullets)
# 기준: 최저기온 버킷(B1~B10) + 일교차/계절/날씨 보정
# 수정사항 반영:
# - "레이어/아이템" 출력 제거
# - "추가 팁 -" → "💡 추가 팁"
# - bullet을 "-"가 아닌 "☑️" 이모지로 출력

import os, json, urllib.parse, urllib.request, datetime as dt

ADDRESS = "서울 마포구"  # 지오코딩 입력
TZ = "Asia/Seoul"
WEBHOOK = os.environ["SLACK_WEBHOOK_URL"]  # Slack Incoming Webhook (GitHub Secrets)

# ---------------- HTTP ----------------
def http_get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8")

# --------------- Geocoding ------------
def geocode(address: str):
    q = urllib.parse.urlencode({"q": address, "format": "json", "limit": 1})
    url = f"https://nominatim.openstreetmap.org/search?{q}"
    data = json.loads(http_get(url, headers={"User-Agent": "slack-weather-bot"}))
    return float(data[0]["lat"]), float(data[0]["lon"])

# --------------- Weather --------------
def fetch_weather(lat: float, lon: float):
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": ",".join([
            "temperature_2m_min",
            "temperature_2m_max",
            "weathercode",
            "precipitation_probability_max",
            "precipitation_sum",
            "windspeed_10m_max"
        ]),
        "timezone": TZ,
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)
    d = json.loads(http_get(url))["daily"]
    return {
        "tmin": round(d["temperature_2m_min"][0]),
        "tmax": round(d["temperature_2m_max"][0]),
        "wcode": int(d["weathercode"][0]),
        "pop": int(d["precipitation_probability_max"][0]),   # %
        "rain": float(d["precipitation_sum"][0]),            # mm
        "wind": float(d["windspeed_10m_max"][0]),            # m/s
    }

# --------------- Season ---------------
def season_from_date(today: dt.date):
    m = today.month
    if m in (3,4,5):   return "spring"
    if m in (6,7,8):   return "summer"
    if m in (9,10,11): return "autumn"
    return "winter"

# ----------- Weather text -------------
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

def flags_from_wmo(wcode: int, pop: int, rain: float, wind: float, tmin: int, tmax: int, season: str):
    flags = set()
    # 비/눈
    if wcode in (61,63,65,66,67,80,81,82,95,96,99) or rain > 0 or pop >= 60:
        flags.add("rain")
    if wcode in (71,73,75):
        flags.add("snow")
    # 구름/맑음
    if wcode in (3,45,48): flags.add("cloudy")
    if wcode in (0,1,2):   flags.add("clear")
    # 바람(간단 임계)
    if wind >= 8.0:
        flags.add("windy")
    # 습/UV/건조(근사치)
    if season == "summer" and tmin >= 20:
        flags.add("humid")
        if tmax >= 28: flags.add("uv_high")
    if season == "winter" and tmin <= 5:
        flags.add("dry")
    return flags

# ----------- Buckets (min temp) -----------
BUCKETS = [
    ("B1", -100, -5, ["롱패딩","히트텍 상하","니트"],        "기모 바지/방한 팬츠", ["기모내의","넥워머"], ["방한장갑","귀마개"], "방한부츠", "한파 보온 최우선"),
    ("B2", -4, 0,    ["두꺼운 패딩/울코트","니트"],          "기모 바지",          ["내복"],             ["목도리"],         "기모 안감 신발", "매우 추움"),
    ("B3", 1, 5,     ["울코트/가죽자켓","니트"],             "기모/두툼 바지",      ["보온 이너"],         [],                "방풍 스니커즈", "겨울 코트 시즌"),
    ("B4", 6, 9,     ["트렌치/자켓","가디건"],               "긴바지",              ["얇은 니트"],         ["가벼운 머플러(선택)"], "스니커즈", "얇은 코트/자켓 계절"),
    ("B5", 10, 12,   ["자켓/맨투맨/셔츠"],                   "긴바지",              ["가벼운 이너"],        [],                "스니커즈/로퍼", "간절기 상의 + 겉옷 1장"),
    ("B6", 13, 16,   ["얇은 셔츠/가디건"],                   "면바지",              ["레이어 친화"],        [],                "가벼운 스니커즈","봄가을 산책온도"),
    ("B7", 17, 19,   ["롱슬리브/얇은 셔츠","반팔+가디건"],   "면바지/청바지",        ["겉옷 휴대"],          [],                "스니커즈",     "선선-포근 사이"),
    ("B8", 20, 22,   ["반팔/얇은 셔츠"],                     "통풍 좋은 팬츠",        ["통풍 레이어"],        ["모자(선택)"],     "통기성 슈즈",  "초여름 경량"),
    ("B9", 23, 26,   ["반팔/반바지/원피스"],                 "흡습속건 팬츠/반바지",  ["흡습속건 이너"],      ["선크림"],         "샌들/스니커즈","여름 캐주얼"),
    ("B10",27,100,   ["민소매/반팔/린넨"],                   "아주 가벼운 하의",      ["초경량"],            ["모자","선글라스"], "샌들",        "한여름 초경량"),
]
BUCKET_ORDER = [b[0] for b in BUCKETS]

def pick_bucket(min_temp: int):
    for code, lo, hi, *_ in BUCKETS:
        if lo <= min_temp <= hi:
            return code
    return "B10"

def bucket_info(code: str):
    for b in BUCKETS:
        if b[0] == code:
            return b
    return BUCKETS[-1]

# ----------- Apparent & adjust -----------
def apparent_adjust(min_temp: int, flags: set):
    adj = 0
    if "windy" in flags:  adj -= 2
    if "rain"  in flags:  adj -= 1
    if "snow"  in flags:  adj -= 2
    if "cloudy" in flags: adj -= 1
    if "dry" in flags and min_temp <= 5: adj -= 1
    if "humid" in flags and min_temp >= 20: adj += 2
    if "uv_high" in flags and min_temp >= 20: adj += 1
    return min_temp + adj, adj

def adjust_bucket_by_apparent(bucket_code: str, min_temp: int, flags: set):
    apparent, adj = apparent_adjust(min_temp, flags)
    idx = BUCKET_ORDER.index(bucket_code)
    # ±1 단계 미세 조정
    if apparent < min_temp - 1:
        idx = max(0, idx - 1)
    elif apparent > min_temp + 1:
        idx = min(len(BUCKET_ORDER)-1, idx + 1)
    return BUCKET_ORDER[idx], adj

def apply_sensitivity(bucket_code: str, cold_sensitivity: int):
    idx = BUCKET_ORDER.index(bucket_code)
    if cold_sensitivity > 0:   idx = max(0, idx - 1)             # 더 따뜻하게
    elif cold_sensitivity < 0: idx = min(len(BUCKET_ORDER)-1, idx + 1)  # 더 가볍게
    return BUCKET_ORDER[idx]

# -------------- Comments ----------------
def delta_comment(delta: int, min_t: int, max_t: int):
    if delta >= 10:
        base = "일교차가 큽니다! 아침엔 따뜻하게, 낮엔 가볍게 — 겹쳐 입기 추천."
        if min_t >= 17:
            return base + " 낮에는 한 단계 가볍게 입어도 좋아요."
        return base
    elif delta >= 6:
        return "낮엔 포근하고 아침·저녁은 선선해요. 얇은 겉옷 챙기세요."
    else:
        return "일교차가 크지 않아 선택이 쉬워요."

def weather_comments(flags: set):
    out = []
    if "rain" in flags:   out.append("비: 방수 겉옷·신발/우산 준비.")
    if "snow" in flags:   out.append("눈: 미끄럼 주의, 보온/방수 부츠.")
    if "windy" in flags:  out.append("바람: 목도리나 머플러로 체감온도를 높이세요.")
    if "cloudy" in flags: out.append("흐림: 햇볕이 약해 체감온도가 낮아 더 추울 수 있어요!")
    if "humid" in flags:  out.append("습함: 통풍 잘 되는 소재로 쾌적하게.")
    if "dry" in flags:    out.append("건조: 보습/립밤 챙기세요.")
    if "uv_high" in flags:out.append("자외선 강함: 모자/선글라스/선크림.")
    return out

# -------------- Recommender -------------
def recommend_outfit(min_t: int, max_t: int, season: str, flags: set, user_prefs=None):
    user_prefs = user_prefs or {}
    cold_sensitivity = int(user_prefs.get("cold_sensitivity", 0))
    carry_pref = int(user_prefs.get("carry_preference", 1))  # 겉옷 휴대 기본 강화

    base_bucket = pick_bucket(min_t)
    adj_bucket, apparent_delta = adjust_bucket_by_apparent(base_bucket, min_t, flags)
    final_bucket = apply_sensitivity(adj_bucket, cold_sensitivity)

    code, lo, hi, base, bottom, layers, acc, shoe, label = bucket_info(final_bucket)
    delta = max_t - min_t

    comments = []
    dc = delta_comment(delta, min_t, max_t)
    if carry_pref == 1:
        dc = "겉옷 휴대 추천. " + dc
    comments.append(dc)
    comments += weather_comments(flags)

    debug = {
        "bucket": code, "label": label,
        "delta": delta, "season": season,
        "flags": sorted(list(flags)), "apparent_adj": apparent_delta
    }

    return {
        "headline": f"오늘 최저 {min_t}℃ / 최고 {max_t}℃ — {label}",
        "top_text": ", ".join(base),
        "bottom_text": bottom,
        "comments": comments,
        "debug": debug
    }

# --------------- Slack send --------------
def post_blocks_to_slack(blocks, fallback=""):
    payload = {"mrkdwn": True, "text": fallback, "blocks": blocks}
    req = urllib.request.Request(
        WEBHOOK, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    urllib.request.urlopen(req)

# ------------------- Main ----------------
def main():
    # 주말 스킵 (월=0 … 일=6)
    if dt.date.today().weekday() >= 5:
        print("Weekend skip")
        return

    lat, lon = geocode(ADDRESS)
    w = fetch_weather(lat, lon)

    season = season_from_date(dt.date.today())
    flags = flags_from_wmo(w["wcode"], w["pop"], w["rain"], w["wind"], w["tmin"], w["tmax"], season)

    cond = describe_weather_kor(w["wcode"])
    cond_emoji = cond.split(" ")[0] if " " in cond else ""
    cond_text  = cond.split(" ", 1)[1] if " " in cond else cond

    user_prefs = {"cold_sensitivity": 0, "carry_preference": 1}

    rec = recommend_outfit(w["tmin"], w["tmax"], season, flags, user_prefs)

    # 인사 2줄
    intro = f"좋은 아침입니다! {cond_emoji}\n오늘의 서울 마포구 날씨를 알려드릴게요!"

    # 필드
    fields = [
        {"type":"mrkdwn", "text": "*최저*\n" + f"{w['tmin']}°C"},
        {"type":"mrkdwn", "text": "*최고*\n" + f"{w['tmax']}°C"},
        {"type":"mrkdwn", "text": "*날씨*\n" + cond_text},
        {"type":"mrkdwn", "text": "*강수확률*\n" + f"{w['pop']}%"},
    ]
    if round(w["rain"], 1) > 0:
        fields.append({"type":"mrkdwn", "text": "*강수량*\n" + f"{round(w['rain'],1)} mm"})

    # 옷차림 (레이어/아이템 제거)
    outfit_lines = [
        "*오늘의 옷차림 추천 👕*",
        f"상의 - {rec['top_text']}",
        f"하의 - {rec['bottom_text']}",
    ]

    # 💡 추가 팁 (이모지 bullet ☑️)
if rec["comments"]:
    comment_lines = "\n".join([f"☑️ {c}" for c in rec["comments"][:3]])
    outfit_lines.append("")  # 하의 밑에 한 줄 띄우기
    outfit_lines.append(f"*💡 추가 팁*\n{comment_lines}")

    blocks = [
        {"type":"section", "text":{"type":"mrkdwn", "text": intro}},
        {"type":"section", "fields": fields},
        {"type":"divider"},
        {"type":"section", "text":{"type":"mrkdwn", "text": "\n".join(outfit_lines)}},
    ]

    fallback = f"{cond_emoji} 최저 {w['tmin']}° / 최고 {w['tmax']}° · {cond_text}"
    post_blocks_to_slack(blocks, fallback=fallback)
    print("Sent ✅", rec["debug"])

if __name__ == "__main__":
    main()
