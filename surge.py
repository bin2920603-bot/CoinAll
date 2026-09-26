#!/usr/bin/env python3
"""1~3분 주기로 거래대금을 조회해 단기 급등(직전 체크 대비 %증가)을 감지한다."""
import json, os, time
from datetime import datetime, timedelta, timezone
import requests

KST = timezone(timedelta(hours=9))
ROOT = os.path.dirname(os.path.abspath(__file__))
SURGE = os.path.join(ROOT, "data", "surge.json")
KEEP_MIN = 30  # 이력은 최근 30분치만 보관 (파일 용량 관리용)

def get(url, params=None, tries=4):
    for i in range(tries):
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 429:
            time.sleep(1.5 * (i + 1))
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()

def level(pct):
    if pct >= 50: return 3
    if pct >= 20: return 2
    if pct >= 10: return 1
    return 0

def main():
    markets_info = get("https://api.upbit.com/v1/market/all", {"isDetails": "false"})
    codes = [m["market"] for m in markets_info if m["market"].startswith("KRW-")]

    store = json.load(open(SURGE, encoding="utf-8")) if os.path.exists(SURGE) else {"coins": {}}
    now = datetime.now(KST)
    now_s = now.isoformat(timespec="seconds")

    tickers = {}
    for i in range(0, len(codes), 100):
        chunk = codes[i:i + 100]
        try:
            for t in get("https://api.upbit.com/v1/ticker", {"markets": ",".join(chunk)}):
                tickers[t["market"]] = t
        except Exception as e:
            print(f" ! 조회 실패: {e}")
        time.sleep(0.2)

    surges = {}
    for code, t in tickers.items():
        cur = t["acc_trade_price_24h"]
        c = store["coins"].setdefault(code, {"hist": []})
        hist = c["hist"]
        prev = hist[-1]["v"] if hist else None
        pct = None
        if prev and prev > 0:
            pct = round((cur - prev) / prev * 100, 1)
        hist.append({"t": now_s, "v": cur})
        cut = now - timedelta(minutes=KEEP_MIN)
        c["hist"] = [h for h in hist if datetime.fromisoformat(h["t"]) >= cut]
        if pct is not None:
            lvl = level(pct)
            if lvl > 0:
                surges[code] = {"pct": pct, "level": lvl, "t": now_s}

    store["updated_at"] = now_s
    store["surges"] = surges
    os.makedirs(os.path.dirname(SURGE), exist_ok=True)
    json.dump(store, open(SURGE, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"급등 감지 {len(surges)}건 (전체 {len(tickers)}종목 점검)")

if __name__ == "__main__":
    main()
