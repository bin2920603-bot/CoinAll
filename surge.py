#!/usr/bin/env python3
"""15분 거래대금 기록과 별도로, 짧은 주기(5분)로 가격만 체크해서
직전 체크 대비 급등한 코인을 감지·기록한다.

index.html이 기대하는 형식으로 저장한다:
  {"surges": {"KRW-BTC": {"level": 1, "pct": 12.3}, ...}, "updated_at": "..."}

level: 1 = 10~20% 상승, 2 = 20~50%, 3 = 50%~
"""
import json, os, time
from datetime import datetime, timedelta, timezone
import requests

KST = timezone(timedelta(hours=9))
ROOT = os.path.dirname(os.path.abspath(__file__))
SURGE = os.path.join(ROOT, "data", "surge.json")       # index.html이 읽는 파일
LAST = os.path.join(ROOT, "data", "surge_last.json")   # 직전 체크 시점 가격 스냅샷
ACTIVE_MIN = 20   # 급등 표시(배지)를 몇 분간 화면에 유지할지


def get(url, params=None, tries=3):
    for i in range(tries):
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 429:
            time.sleep(1.5 * (i + 1))
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()


def level(pct):
    if pct >= 50:
        return 3
    if pct >= 20:
        return 2
    if pct >= 10:
        return 1
    return 0


def check():
    markets = get("https://api.upbit.com/v1/market/all", {"isDetails": "false"})
    codes = [m["market"] for m in markets if m["market"].startswith("KRW-")]

    prices = {}
    for i in range(0, len(codes), 100):
        chunk = codes[i:i + 100]
        try:
            for t in get("https://api.upbit.com/v1/ticker", {"markets": ",".join(chunk)}):
                prices[t["market"]] = t["trade_price"]
        except Exception as e:
            print(f" ! 조회 실패: {e}")
        time.sleep(0.15)

    last = json.load(open(LAST, encoding="utf-8")) if os.path.exists(LAST) else {}

    prev = {"active": {}}
    if os.path.exists(SURGE):
        try:
            prev = json.load(open(SURGE, encoding="utf-8"))
        except Exception:
            pass
    prev_active = prev.get("active", {})

    now = datetime.now(KST)
    now_s = now.isoformat(timespec="seconds")
    cut = (now - timedelta(minutes=ACTIVE_MIN)).isoformat(timespec="seconds")

    # 아직 유효 시간이 지나지 않은 기존 급등은 유지
    active = {k: v for k, v in prev_active.items() if v.get("time", "") >= cut}

    new_count = 0
    for code, price in prices.items():
        prevp = last.get(code)
        if prevp:
            pct = (price - prevp) / prevp * 100
            lv = level(pct)
            if lv:
                active[code] = {"level": lv, "pct": round(pct, 1), "time": now_s}
                new_count += 1

    surges = {k: {"level": v["level"], "pct": v["pct"]} for k, v in active.items()}

    os.makedirs(os.path.dirname(SURGE), exist_ok=True)
    json.dump(
        {"surges": surges, "active": active, "updated_at": now_s},
        open(SURGE, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":")
    )
    json.dump(prices, open(LAST, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))

    print(f"{now_s} 급등체크 · {len(prices)}종목 조회 · 신규 {new_count}건 · 표시중 {len(surges)}건")


if __name__ == "__main__":
    check()
