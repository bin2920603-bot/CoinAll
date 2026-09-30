#!/usr/bin/env python3
"""15분 거래대금 기록과 별도로, 짧은 주기(5분)로 가격만 체크해서
급등·급락하는 코인을 '초기'에 감지·기록한다. (5분 / 15분 / 30분 구간 비교)

index.html이 기대하는 형식으로 저장한다:
  {"surges": {"KRW-BTC": {"level": 1, "pct": 3.4, "dir": "up"}, ...}, "updated_at": "..."}

level: 1 = 초기(3~5%대), 2 = 5~10%, 3 = 10%~
dir: up(급등) / down(급락)
"""
import json, os, time
from datetime import datetime, timedelta, timezone
import requests

KST = timezone(timedelta(hours=9))
ROOT = os.path.dirname(os.path.abspath(__file__))
SURGE = os.path.join(ROOT, "data", "surge.json")       # index.html이 읽는 파일
LAST = os.path.join(ROOT, "data", "surge_last.json")   # 직전 스냅샷 + 최근 40분 가격 기록
ACTIVE_MIN = 20   # 표시(배지)를 몇 분간 화면에 유지할지
HIST_MIN = 40     # 가격 기록을 몇 분치 남길지

MIN_PCT = 3.0             # 5분 사이 이만큼 움직이면 후보(거래대금 폭증 필요)
SPIKE = 3.0               # 직전 5분 거래대금의 몇 배면 '폭증'으로 볼지
MIN_VOL5 = 300_000_000    # 5분 거래대금 3억 원 미만은 (10% 미만이면) 무시
MIN15 = 5.0               # 15분 사이 이만큼 움직이면 표시
MIN30 = 8.0               # 30분 사이 이만큼 움직이면 표시
MIN_VOL_WIN = 500_000_000 # 15·30분 구간 거래대금 최소 5억 원 (10% 이상이면 무시하고 표시)


def get(url, params=None, tries=3):
    for i in range(tries):
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 429:
            time.sleep(1.5 * (i + 1))
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()


def find_ref(hist, now_ts, minutes):
    """hist에서 '지금으로부터 minutes분 전'에 가장 가까운 기록을 찾는다."""
    target = now_ts - minutes * 60
    best, best_d = None, None
    for ts, p, a in hist:
        age = (now_ts - ts) / 60
        if minutes - 4 <= age <= minutes + 6:
            d = abs(ts - target)
            if best_d is None or d < best_d:
                best, best_d = (ts, p, a), d
    return best


def check():
    markets = get("https://api.upbit.com/v1/market/all", {"isDetails": "false"})
    codes = [m["market"] for m in markets if m["market"].startswith("KRW-")]

    snap = {}
    for i in range(0, len(codes), 100):
        chunk = codes[i:i + 100]
        try:
            for t in get("https://api.upbit.com/v1/ticker", {"markets": ",".join(chunk)}):
                snap[t["market"]] = {"price": t["trade_price"], "acc": t.get("acc_trade_price", 0), "v5": 0, "hist": []}
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
    now_ts = int(now.timestamp())
    cut = (now - timedelta(minutes=ACTIVE_MIN)).isoformat(timespec="seconds")

    active = {k: v for k, v in prev_active.items() if v.get("time", "") >= cut}

    new_up = new_down = 0
    for code, cur in snap.items():
        price = cur["price"]
        acc = cur["acc"]
        prevd = last_raw.get(code)
        old_hist = []
        if isinstance(prevd, dict):
            old_hist = [h for h in prevd.get("hist", []) if now_ts - h[0] <= HIST_MIN * 60]
        cur["hist"] = old_hist + [[now_ts, price, acc]]

        if not isinstance(prevd, dict):
            continue
        prevp = prevd.get("price")
        preva = prevd.get("acc")
        vol5 = (acc - preva) if (preva is not None and acc >= preva) else 0
        cur["v5"] = vol5
        if not prevp:
            continue

        # ── 5분 구간
        pct5 = (price - prevp) / prevp * 100
        prev_v5 = prevd.get("v5")
        spike = prev_v5 is not None and vol5 >= SPIKE * max(prev_v5, MIN_VOL5 / SPIKE)
        a5 = abs(pct5)
        t5 = a5 >= 10 or (vol5 >= MIN_VOL5 and (a5 >= 5 or (a5 >= MIN_PCT and spike)))

        cands = []
        if t5:
            cands.append(pct5)

        # ── 15분 / 30분 구간
        for minutes, min_pct, min_vol in ((15, MIN15, MIN_VOL_WIN), (30, MIN30, MIN_VOL_WIN * 2)):
            ref = find_ref(old_hist, now_ts, minutes)
            if not ref:
                continue
            _, rp, ra = ref
            if not rp:
                continue
            pct = (price - rp) / rp * 100
            vol = (acc - ra) if acc >= ra else 0
            ap = abs(pct)
            if ap >= 10 or (ap >= min_pct and vol >= min_vol):
                cands.append(pct)

        if not cands:
            pct, lv = 0.0, 0
        else:
            pct = max(cands, key=abs)
            ap = abs(pct)
            lv = 3 if ap >= 10 else (2 if ap >= 5 else 1)
        d = "up" if pct >= 0 else "down"

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
            if lv and d == edir and (lv >= entry.get("level", 0) or abs(pct) > abs(entry.get("pct", 0))):
                entry.update({"level": max(lv, entry.get("level", 0)), "pct": round(pct, 1), "time": now_s})
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
        {code: {"price": v["price"], "acc": v["acc"], "v5": v["v5"], "hist": v["hist"]} for code, v in snap.items()},
        open(LAST, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":")
    )

    print(f"{now_s} 체크 · {len(snap)}종목 · 신규 급등 {new_up}건 · 신규 급락 {new_down}건 · 표시중 {len(surges)}건")


if __name__ == "__main__":
    check()
