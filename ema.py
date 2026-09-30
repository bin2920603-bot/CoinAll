#!/usr/bin/env python3
"""업비트 원화마켓 종목의 일봉 EMA(5·20·60·120)를 검사해
정배열(up) / 역배열(down) 종목만 data/ema.json 에 저장한다."""
import json, os, time
from datetime import datetime, timedelta, timezone
import requests

HOST = "https://api.upbit.com"
KST = timezone(timedelta(hours=9))
ROOT = os.path.dirname(os.path.abspath(__file__))
VOL = os.path.join(ROOT, "data", "volumes.json")
OUT = os.path.join(ROOT, "data", "ema.json")

# 가격이 거의 안 움직이는 스테이블코인은 표시하지 않는다
STABLE = {"USDT", "USDC", "DAI", "TUSD", "USDE", "USDD", "PYUSD", "FDUSD"}


def get(path, params, tries=4):
    last = None
    for i in range(tries):
        try:
            r = requests.get(HOST + path, params=params, timeout=10,
                             headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 429:
                last = "429 too many requests"
                time.sleep(1.5 * (i + 1))
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last = str(e)
            time.sleep(0.5)
    raise RuntimeError(last)


def ema(values, n):
    """values: 오래된 것 -> 최신 순서. 처음 n개의 평균을 시작값으로 삼아 EMA를 구한다."""
    k = 2 / (n + 1)
    e = sum(values[:n]) / n
    for v in values[n:]:
        e = v * k + e * (1 - k)
    return e


def classify(closes_old_to_new):
    """정배열 'up', 역배열 'down', 아니면 None"""
    if len(closes_old_to_new) < 120:
        return None
    e5 = ema(closes_old_to_new, 5)
    e20 = ema(closes_old_to_new, 20)
    e60 = ema(closes_old_to_new, 60)
    e120 = ema(closes_old_to_new, 120)
    if e5 > e20 > e60 > e120:
        return "up"
    if e5 < e20 < e60 < e120:
        return "down"
    return None


def main():
    coins = list(json.load(open(VOL, encoding="utf-8"))["coins"].keys())
    trend, fail = {}, 0
    for code in coins:
        sym = code.split("-", 1)[1]
        if sym.upper() in STABLE:
            continue
        try:
            c = get("/v1/candles/days", {"market": code, "count": 200})
            closes = [float(x["trade_price"]) for x in reversed(c)]
            t = classify(closes)
            if t:
                trend[code] = t
        except Exception as e:
            fail += 1
            print(f"  ! {sym}: {e}")
        time.sleep(0.12)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump({"updated_at": datetime.now(KST).isoformat(timespec="seconds"), "trend": trend},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    up = sum(1 for v in trend.values() if v == "up")
    print(f"EMA 정배열 {up} · 역배열 {len(trend) - up} · 실패 {fail} / 전체 {len(coins)}")


if __name__ == "__main__":
    main()
