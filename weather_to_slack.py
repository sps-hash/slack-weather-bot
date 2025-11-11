#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import traceback
from datetime import datetime, timezone, timedelta

import requests

# -----------------------------
# 기본 설정 (좌표/로케일/이모지 등)
# -----------------------------

# 서울 마포구(독막로 211 인근) 좌표 — 필요 시 환경변수로 덮어쓰기 가능
LAT = float(os.getenv("WEATHER_LAT", "37.549"))
LON = float(os.getenv("WEATHER_LON", "126.921"))
LOCALE = os.getenv("LOCALE", "ko")  # 'ko'만 사용
KST = timezone(timedelta(hours=9))

# -----------------------------
# Open-Meteo 호출 & 매핑
# -----------------------------

OPEN_METEO_URL = (
    "https://api.open-meteo.com/v1/forecast?"
    "latitude={lat}&longitude={lon}"
    "&timezone=Asia%2FSeoul"
    "&daily=temperature_2m_min,temperature_2m_max,precipitation_probability_max,weathercode,windspeed_10m_max"
)

WEATHER_CODE_MAP_KO = {
    # WMO weather codes (대표 매핑)
    0: ("맑음", "clear"),
    1: ("구름 조금", "partly"),
    2: ("대체로 맑음", "partly"),
    3: ("흐림", "cloudy"),
    45: ("안개", "cloudy"),
    48: ("착빙 안개", "cloudy"),
    51: ("이슬비", "rain"),
    53: ("이슬비", "rain"),
    55: ("이슬비", "rain"),
    56: ("어는 이슬비", "rain"),
    57: ("어는 이슬비", "rain"),
    61: ("약한 비", "rain"),
    63: ("비", "rain"),
    65: ("강한 비", "rain"),
    66: ("어는 비", "rain"),
    67: ("어는 비", "rain"),
    71: ("약한 눈", "snow"),
    73: ("눈", "snow"),
    75: ("강한 눈", "snow"),
    77: ("눈송이/싸락눈", "snow"),
    80: ("소나기", "rain"),
    81: ("소나기", "rain"),
    82: ("강한 소나기", "rain"),
    85: ("소낙눈", "snow"),
    86: ("강한 소낙눈", "snow"),
    95: ("뇌우", "rain"),
    96: ("뇌우(우박)", "rain"),
    99: ("강한 뇌우(우박)", "rain"),
}

def map_weathercode_to_korean(code: int) -> str:
    label, _ = WEATHER_CODE_MAP_KO.get(int(code), ("알 수 없음", "etc"))
    return label

def weather_flags_from_code(code: int):
    # 추가 팁 판단용 플래그
    _, tag = WEATHER_CODE_MAP_KO.get(int(code), ("", "etc"))
    flags = set()
    if tag in ("rain",):
        flags.add("rain")
    if tag in ("snow",):
        flags.add("snow")
    if tag in ("cloudy", "partly"):
        flags.add("cloudy")
    if tag in ("clear",):
        flags.add("clear")
    return flags

def fetch_weather():
    url = OPEN_METEO_URL.format(lat=LAT, lon=LON)
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    data = r.json()

    daily = data.get("daily", {})
    # 오늘 인덱스는 0
    min_t = daily.get("temperature_2m_min", [None])[0]
    max_t = daily.get("temperature_2m_max", [None])[0]
    precip = daily.get("precipitation_probability_max", [0])[0]
    wcode = daily.get("weathercode", [0])[0]
    wind = daily.get("windspeed_10m_max", [0])[0]

    return {
        "min": round(min_t) if min_t is not None else None,
        "max": round(max_t) if max_t is not None else None,
        "precip_prob": int(precip) if precip is not None else 0,
        "weathercode": int(wcode) if wcode is not None else 0,
        "wind": float(wind) if wind is not None else 0.0,
    }

# -----------------------------
# 옷차림 추천 규칙 (최저기온 기준)
# -----------------------------

def base_outfit_by_min_temp(min_temp: float):
    """최저 기온 기준 상의/하의 추천 (간결 버전)"""
    t = min_temp
    if t <= -5:
        top = "롱패딩/두꺼운 패딩, 히트텍, 니트"
        bottom = "기모/두툼 바지"
    elif -4 <= t <= 0:
        top = "두꺼운 패딩/울코트, 니트"
        bottom = "기모 바지"
    elif 1 <= t <= 5:
        top = "울코트/가죽자켓, 니트"
        bottom = "기모/두툼 바지"
    elif 6 <= t <= 9:
        top = "트렌치/자켓, 가디건"
        bottom = "긴 바지"
    elif 10 <= t <= 12:
        top = "자켓/맨투맨/셔츠"
        bottom = "긴 바지"
    elif 13 <= t <= 16:
        top = "얇은 셔츠/가디건"
        bottom = "면 바지"
    elif 17 <= t <= 19:
        top = "롱슬리브 또는 반팔+가디건"
        bottom = "면 바지"
    elif 20 <= t <= 22:
        top = "반팔/얇은 셔츠"
        bottom = "통풍 좋은 팬츠"
    elif 23 <= t <= 26:
        top = "반팔/민소매"
        bottom = "반바지/원피스"
    else:  # >= 27
        top = "초경량 반팔/민소매, 린넨"
        bottom = "숏츠/통풍 좋은 하의"
    return top, bottom

def build_additional_tips(min_temp: float, max_temp: float, wcode: int, precip_prob: int, windspeed: float):
    tips = []
    delta = (max_temp - min_temp) if (min_temp is not None and max_temp is not None) else 0

    # 일교차
    if delta >= 10:
        tips.append("겉옷 휴대 추천. 일교차가 큽니다! 아침엔 따뜻하게, 낮엔 가볍게 — 겹쳐 입기 추천.")
    elif 6 <= delta <= 9:
        tips.append("겉옷 휴대 추천. 낮엔 포근하고 아침·저녁은 선선해요. 얇은 겉옷 챙기세요.")

    # 날씨 코드 기반
    flags = weather_flags_from_code(wcode)
    if "rain" in flags or precip_prob >= 60:
        tips.append("비 : 방수 겉옷·신발/우산 준비.")
    if "snow" in flags:
        tips.append("눈 : 미끄럼 주의, 따뜻하고 방수되는 신발.")
    if "cloudy" in flags:
        tips.append("흐림 : 햇볕에 약해 체감온도가 낮아 더 추울 수 있어요!")
    # 바람(간이 기준)
    if windspeed >= 6:  # m/s 기준. 6~ = 약간 강한 바람
        tips.append("바람 : 목/손목을 막아 체감온도를 높이세요.")

    return tips

def build_outfit_recommendation(min_temp, max_temp, weathercode, precip_prob, windspeed,
                                season=None, user_prefs=None):
    top, bottom = base_outfit_by_min_temp(min_temp)
    tips = build_additional_tips(min_temp, max_temp, weathercode, precip_prob, windspeed)
    return {"top": top, "bottom": bottom, "tips": tips}

# -----------------------------
# Slack 메시지 포맷
# -----------------------------

def build_slack_markdown(min_t, max_t, weather_text, precip_prob, top, bottom, tips):
    # 1️⃣ 인사 + 설명
    text = (
        "좋은 아침입니다! ☀️\n"
        "오늘의 서울 마포구 날씨를 알려드릴게요!\n\n"
    )

    # 2️⃣ 날씨 정보 (2x2 배치)
    text += (
        f"*최저* {min_t}℃   |   *최고* {max_t}℃\n"
        f"*날씨* {weather_text}   |   *강수확률* {precip_prob}%\n\n"
    )

    # 3️⃣ 옷차림 추천
    text += (
        "──────────────────────────────\n"
        f"*오늘의 옷차림 추천 👕*\n"
        f"상의 - {top}\n"
        f"하의 - {bottom}\n\n"
    )

    # 4️⃣ 추가 팁 (전구 위치 / 체크 표시 수정)
    if tips:
        text += "*추가 팁 💡*\n"
        text += "\n".join([f"✔️ {t}" for t in tips])

    return text

# -----------------------------
# Slack Webhook 전송
# -----------------------------

def post_to_slack(webhook_url: str, payload: dict):
    headers = {"Content-Type": "application/json; charset=utf-8"}
    r = requests.post(webhook_url, headers=headers, data=json.dumps(payload), timeout=10)
    ok = (200 <= r.status_code < 300)
    return ok, r.text

# -----------------------------
# main
# -----------------------------

if __name__ == "__main__":
    try:
        webhook = os.getenv("SLACK_WEBHOOK_URL")
        if not webhook:
            print("[fatal] SLACK_WEBHOOK_URL secret not set")
            sys.exit(2)

        w = fetch_weather()  # {min,max,precip_prob,weathercode,wind}
        if w.get("min") is None or w.get("max") is None:
            print("[fatal] weather missing required fields")
            sys.exit(3)

        # 1) 추천 계산
        recommendation = build_outfit_recommendation(
            min_temp=w["min"],
            max_temp=w["max"],
            weathercode=w.get("weathercode"),
            precip_prob=w.get("precip_prob"),
            windspeed=w.get("wind"),
            season=None,
            user_prefs=None
        )

        # 2) 메시지 생성
        text = build_slack_markdown(
            min_t=w["min"],
            max_t=w["max"],
            weather_text=map_weathercode_to_korean(w.get("weathercode")),
            precip_prob=w.get("precip_prob"),
            top=recommendation.get("top", ""),
            bottom=recommendation.get("bottom", ""),
            tips=recommendation.get("tips", []),
        )

        # 3) 전송
        ok, body = post_to_slack(webhook, {"text": text})
        if not ok:
            print("[slack] post failed:", body)
            sys.exit(4)

        print("[done] message posted.")

    except Exception:
        traceback.print_exc()
        sys.exit(1)
