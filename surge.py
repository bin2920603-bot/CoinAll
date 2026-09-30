#!/usr/bin/env python3
"""15분 거래대금 기록과 별도로, 짧은 주기(5분)로 가격만 체크해서
직전 체크 대비 급등·급락하는 코인을 '초기'에 감지·기록한다.

index.html이 기대하는 형식으로 저장한다:
  {"surges": {"KRW-BTC": {"level": 1, "pct": 3.4, "dir": "up"}, ...}, "updated_at": "..."}

level: 1 = 3~5%(거래대금 폭증 동반), 2 = 5~10%, 3 = 10%~
dir: up(급등) / down(급락)
"""
import json, os, time
from datetime import datetime, timedelta, timezone
import requests

KST = timezone(timedelta(hours=9))
ROOT = os.path.dirname(os.path.abspath(__file__))
SURGE = os.path.join(ROOT, "data", "surge.json")       # index.html이 읽는 파일
LAST = os.path.join(ROOT, "data", "surge_last.json")   # 직전 체크 시점 스냅샷
ACTIVE_MIN = 20   # 표시(배지)를 몇 분간 화면에 유지할지

MIN_PCT = 3.0             # 5분 사이 이만큼 움직이면 후보
SPIKE = 3.0               # 직전 5분 거래대금의 몇 배면 '폭증'으로 볼지
MIN_VOL5 = 300_000_000    # 5분 거래대금 3억 원 미만은 (10% 미만이면) 무시


def get(url, params=None, tries=3):
    for i in range(tries):
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 429:
            time.sleep(1.5 * (i + 1))
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()


def level(p, vol5, spike):
    """p: 변동폭 절댓값(%)"""
    if p >= 10:
        return 3
    if vol5 < MIN_VOL5:
        return 0
    if p >= 5:
        return 2
    if p >= MIN_PCT and spike:
        return 1
    return 0


def check():
    markets = get("https://api.upbit.com/v1/market/all", {"isDetails": "false"})
    codes = [m["market"] for m in markets if m["market"].startswith("KRW-")]

    snap = {}
    for i in range(0, len(codes), 100):
        chunk = codes[i:i + 100]
        try:
            for t in get("https://api.upbit.com/v1/ticker", {"markets": ",".join(chunk)}):
                snap[t["market"]] = {"price": t["trade_price"], "acc": t.get("acc_trade_price", 0), "v5": 0}
        except Exception as e:
            print(f" ! 조회 실패: {e}")
        time.sleep(0.15)

    last_raw = json.load(open(LAST, encoding="utf-8")) if os.path.exists(LAST) else {}

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

    active = {k: v for k, v in prev_active.items() if v.get("time", "") >= cut}

    new_up = new_down = 0
    for code, cur in snap.items():
        price = cur["price"]
        acc = cur["acc"]
        prevd = last_raw.get(code)
        if not isinstance(prevd, dict):
            continue
        prevp = prevd.get("price")
        preva = prevd.get("acc")
        vol5 = (acc - preva) if (preva is not None and acc >= preva) else 0
        cur["v5"] = vol5
        if not prevp:
            continue

        pct = (price - prevp) / prevp * 100
        d = "up" if pct >= 0 else "down"
        prev_v5 = prevd.get("v5")
        spike = prev_v5 is not None and vol5 >= SPIKE * max(prev_v5, MIN_VOL5 / SPIKE)
        lv = level(abs(pct), vol5, spike)

        if code in active:
            entry = active[code]
            edir = entry.get("dir", "up")
            if edir == "up":
                peak = max(entry.get("peak", price), price)
                base_vol = entry.get("base_vol") or 1
                ratio = vol5 / base_vol
                vol_status = "유지" if ratio >= 0.5 else ("감소" if ratio >= 0.2 else "급감")
                pullback = round((price - peak) / peak * 100, 1) if peak else 0.0
                entry.update({"peak": peak, "pullback": pullback, "vol_status": vol_status})
            if lv and d == edir and lv >= entry.get("level", 0):
                entry.update({"level": lv, "pct": round(pct, 1), "time": now_s})
        elif lv:
            active[code] = {
                "dir": d, "level": lv, "pct": round(pct, 1), "time": now_s,
                "peak": price, "base_vol": vol5 if vol5 > 0 else 1,
                "pullback": 0.0, "vol_status": "유지" if d == "up" else None,
            }
            if d == "up":
                new_up += 1
            else:
                new_down += 1

    surges = {
        k: {
            "level": v["level"], "pct": v["pct"], "dir": v.get("dir", "up"),
            "pullback": v.get("pullback", 0.0), "vol_status": v.get("vol_status", "유지"),
        }
        for k, v in active.items()
    }

    os.makedirs(os.path.dirname(SURGE), exist_ok=True)
    json.dump(
        {"surges": surges, "active": active, "updated_at": now_s},
        open(SURGE, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":")
    )
    json.dump(
        {code: {"price": v["price"], "acc": v["acc"], "v5": v["v5"]} for code, v in snap.items()},
        open(LAST, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":")
    )

    print(f"{now_s} 체크 · {len(snap)}종목 · 신규 급등 {new_up}건 · 신규 급락 {new_down}건 · 표시중 {len(surges)}건")


if __name__ == "__main__":
    check()
