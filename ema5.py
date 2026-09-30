#!/usr/bin/env python3
"""업비트 5분봉 EMA(7·20·50·200)+VWAP100 정배열/역배열/early 를 data/ema5.json 에 저장한다."""
import json, os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from ema import get, ema, STABLE, VOL, KST

OUT = os.path.join(os.path.dirname(VOL), "ema5.json")
CROSS_LOOKBACK = 6   # 최근 5분봉 6개 안에 넘었으면 early 후보
MIN_GAP = 0.0002     # EMA7이 EMA20보다 최소 0.02% 위에 있어야 함
SLOPE_BARS = 2       # EMA20이 2개 봉 전보다 올라와 있어야 함


def vwap(highs, lows, closes, vols, n=100):
    h, l, c, v = highs[-n:], lows[-n:], closes[-n:], vols[-n:]
    total = sum(v)
    if total == 0:
        return None
    return sum((h[i] + l[i] + c[i]) / 3 * v[i] for i in range(len(v))) / total


def classify5(highs, lows, closes, vols):
    if len(closes) < 210:
        return None
    e7 = ema(closes, 7)
    e20 = ema(closes, 20)
    e50 = ema(closes, 50)
    e200 = ema(closes, 200)
    vw = vwap(highs, lows, closes, vols, 100)
    if vw is None:
        return None
    last = closes[-1]

    if e7 > e20 > e50 > e200 and last > vw:
        return "up"
    if e7 < e20 < e50 < e200 and last < vw:
        return "down"

    if e7 > e20 and last > vw and last > e50:
        if (e7 - e20) / e20 < MIN_GAP:
            return None
        e20_prev = ema(closes[:-SLOPE_BARS], 20)
        if e20 <= e20_prev:
            return None
        for k in range(1, CROSS_LOOKBACK + 1):
            past = closes[:-k]
            if len(past) < 201:
                break
            if ema(past, 7) <= ema(past, 20):
                return "early"
    return None


def check(code):
    sym = code.split("-", 1)[1]
    if sym.upper() in STABLE:
        return code, None, False
    try:
        c1 = get("/v1/candles/minutes/5", {"market": code, "count": 200})
        c2 = get("/v1/candles/minutes/5", {"market": code, "count": 100,
                                            "to": c1[-1]["candle_date_time_utc"]})
        c = list(reversed(c1 + c2))   # 오래된 것 -> 최신
        highs = [float(x["high_price"]) for x in c]
        lows = [float(x["low_price"]) for x in c]
        closes = [float(x["trade_price"]) for x in c]
        vols = [float(x["candle_acc_trade_volume"]) for x in c]
        return code, classify5(highs, lows, closes, vols), False
    except Exception as e:
        print(f"  ! {sym}: {e}")
        return code, None, True


def main():
    store = json.load(open(VOL, encoding="utf-8"))
    coins = list(store["coins"].keys())
    trend, fail = {}, 0
    with ThreadPoolExecutor(max_workers=3) as ex:
        for code, t, failed in ex.map(check, coins):
            fail += failed
            if t:
                trend[code] = t
    json.dump({"updated_at": datetime.now(KST).isoformat(timespec="seconds"), "trend": trend},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    up = sum(1 for v in trend.values() if v == "up")
    down = sum(1 for v in trend.values() if v == "down")
    early = sum(1 for v in trend.values() if v == "early")
    print(f"5분봉 정배열 {up} · 역배열 {down} · 넘는중 {early} · 실패 {fail} / 전체 {len(coins)}")


if __name__ == "__main__":
    main()
