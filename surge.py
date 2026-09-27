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

    # price: 현재가, acc: 당일 누적 거래대금(00시 기준) → 두 시점 차이로 5분간 거래대금을 계산
    snap = {}
    for i in range(0, len(codes), 100):
        chunk = codes[i:i + 100]
        try:
            for t in get("https://api.upbit.com/v1/ticker", {"markets": ",".join(chunk)}):
                snap[t["market"]] = {"price": t["trade_price"], "acc": t.get("acc_trade_price", 0)}
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

    # 아직 유효 시간이 지나지 않은 기존 급등은 유지
    active = {k: v for k, v in prev_active.items() if v.get("time", "") >= cut}

    new_count = 0
    for code, cur in snap.items():
        price = cur["price"]
        acc = cur["acc"]
        prevd = last_raw.get(code)
        if not isinstance(prevd, dict):
            continue  # 첫 수집이거나 이전 포맷이면 이번 회차는 기준값만 쌓고 넘어감
        prevp = prevd.get("price")
        preva = prevd.get("acc")
        if not prevp:
            continue

        pct = (price - prevp) / prevp * 100
        vol5 = (acc - preva) if (preva is not None and acc >= preva) else 0
        lv = level(pct)

        if code in active:
            # 이미 표시 중인 급등: 고점·거래량 유지 여부만 계속 갱신
            entry = active[code]
            peak = max(entry.get("peak", price), price)
            base_vol = entry.get("base_vol") or 1
            ratio = vol5 / base_vol
            vol_status = "유지" if ratio >= 0.5 else ("감소" if ratio >= 0.2 else "급감")
            pullback = round((price - peak) / peak * 100, 1) if peak else 0.0
            entry.update({"peak": peak, "pullback": pullback, "vol_status": vol_status})
            if lv and lv >= entry.get("level", 0):
                entry.update({"level": lv, "pct": round(pct, 1), "time": now_s})
        elif lv:
            active[code] = {
                "level": lv, "pct": round(pct, 1), "time": now_s,
                "peak": price, "base_vol": vol5 if vol5 > 0 else 1,
                "pullback": 0.0, "vol_status": "유지",
            }
            new_count += 1

    surges = {
        k: {
            "level": v["level"], "pct": v["pct"],
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
        {code: {"price": v["price"], "acc": v["acc"]} for code, v in snap.items()},
        open(LAST, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":")
    )

    print(f"{now_s} 급등체크 · {len(snap)}종목 조회 · 신규 {new_count}건 · 표시중 {len(surges)}건")


if __name__ == "__main__":
    check()
