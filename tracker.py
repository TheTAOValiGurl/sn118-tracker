import requests
import csv
import os
import time
from datetime import datetime, timezone, timedelta

API_KEY = os.environ.get("TAOSTATS_API_KEY", "")
NETUID  = 118
OUTPUT_CSV = "sn118_daily_alpha.csv"

WALLETS = [
    ("5GU1RuZTnencf9ETjtStxSWrh5UyMUxpJDjy5Y74fCnvLCPJ", "Wallet1_Ditto"),
    ("5F9tvGHYMkoJ95biTvmscmnW6bxzXq5VUsGhX4q4fZvpu2sy",  "Wallet2_1T1BAI"),
    ("5CZtgF1xChRMKXrihA62smGMvhtRCaSsyz1tRqngCJQoVL4f",  "Wallet3_taobotE2L"),
    ("5FnxK1znrcQka73mPaHJgY4s14ryGVvmXtUwFHw9so2AdWsE",  "Wallet4_TAOcom"),
    ("5DcFxprQ9LCwezrjetRwfJeAd2bVTVgzu3eENRg9tGNnD9on",  "Wallet5_TAOcom"),
    ("5GUEJ2h8anTrN2UpJTTyPopbKKCRkAC3WsFc2wrqTbFpmN6U",  "Wallet6_taobotTAOcom"),
    ("5HYKqWwQgcWnRNbzCwX6gDA9RF6VBdAmaKxJFyQ17NUTiHGg",  "Wallet7_DittoTAOcom"),
]

BASE    = "https://api.taostats.io/api/dtao/stake_balance"
HEADERS = {"accept": "application/json", "Authorization": API_KEY}
RAO     = 1_000_000_000

def rao_to_alpha(val):
    try:
        return int(val) / RAO
    except (TypeError, ValueError):
        return 0.0

def get_current_positions(coldkey):
    url = f"{BASE}/latest/v1"
    params = {"coldkey": coldkey, "netuid": NETUID, "limit": 50}
    r = requests.get(url, headers=HEADERS, params=params, timeout=30)
    r.raise_for_status()
    positions = []
    for item in r.json().get("data", []):
        positions.append({
            "hotkey_ss58":   item["hotkey"]["ss58"],
            "hotkey_name":   item.get("hotkey_name") or item["hotkey"]["ss58"][:12],
            "balance_alpha": rao_to_alpha(item.get("balance", 0)),
        })
    return positions

def get_balance_24h_ago(coldkey, hotkey_ss58):
    url = f"{BASE}/history/v1"
    now_utc  = datetime.now(timezone.utc)
    ts_end   = int((now_utc - timedelta(hours=20)).timestamp())
    ts_start = int((now_utc - timedelta(hours=30)).timestamp())
    params = {
        "coldkey":         coldkey,
        "hotkey":          hotkey_ss58,
        "netuid":          NETUID,
        "timestamp_start": ts_start,
        "timestamp_end":   ts_end,
        "order":           "timestamp_desc",
        "limit":           1,
    }
    r = requests.get(url, headers=HEADERS, params=params, timeout=30)
    r.raise_for_status()
    data = r.json().get("data", [])
    if not data:
        return None, None
    item = data[0]
    return rao_to_alpha(item.get("balance", 0)), item.get("timestamp")

def process_wallet(coldkey, label):
    positions = get_current_positions(coldkey)
    if not positions:
        return {
            "label": label,
            "coldkey_short":      coldkey[:8] + "..." + coldkey[-6:],
            "validators":         "NO POSITION",
            "period_start_alpha": None,
            "current_alpha":      None,
            "earned_alpha":       None,
        }
    period_start_total = 0.0
    current_total      = 0.0
    validator_names    = []
    for pos in positions:
        current_total += pos["balance_alpha"]
        validator_names.append(pos["hotkey_name"])
        bal_24h, _ = get_balance_24h_ago(coldkey, pos["hotkey_ss58"])
        period_start_total += bal_24h if bal_24h is not None else 0.0
        time.sleep(0.3)
    earned = current_total - period_start_total
    return {
        "label":              label,
        "coldkey_short":      coldkey[:8] + "..." + coldkey[-6:],
        "validators":         " + ".join(validator_names),
        "period_start_alpha": round(period_start_total, 6),
        "current_alpha":      round(current_total,      6),
        "earned_alpha":       round(earned,             6),
    }

def main():
    now_pst = datetime.now(timezone(timedelta(hours=-8)))
    run_ts  = now_pst.strftime("%Y-%m-%d %H:%M PST")
    rows = []
    for coldkey, label in WALLETS:
        print(f"Fetching {label}...")
        try:
            row = process_wallet(coldkey, label)
        except Exception as e:
            row = {
                "label": label,
                "coldkey_short": coldkey[:8] + "...",
                "validators": f"ERROR: {e}",
                "period_start_alpha": None,
                "current_alpha": None,
                "earned_alpha": None,
            }
        rows.append(row)
        time.sleep(0.5)

    print(f"\n{'='*75}")
    print(f"  SN118 Daily Alpha Snapshot  |  {run_ts}")
    print(f"{'='*75}")
    print(f"{'Wallet':<24} {'Validator(s)':<22} {'Start':>13} {'Current':>13} {'Earned':>10}")
    print(f"{'-'*75}")
    for r in rows:
        ps  = f"{r['period_start_alpha']:>13.4f}" if r['period_start_alpha'] is not None else f"{'N/A':>13}"
        cur = f"{r['current_alpha']:>13.4f}"      if r['current_alpha']      is not None else f"{'N/A':>13}"
        ea  = f"{r['earned_alpha']:>10.4f}"        if r['earned_alpha']        is not None else f"{'N/A':>10}"
        print(f"{r['coldkey_short']:<24} {r['validators'][:22]:<22} {ps} {cur} {ea}")
    total = sum(r['earned_alpha'] for r in rows if r['earned_alpha'] is not None)
    print(f"{'='*75}")
    print(f"  Total earned today: {total:.4f} alpha")
    print(f"{'='*75}\n")

    file_exists = os.path.isfile(OUTPUT_CSV)
    fieldnames  = ["run_timestamp","label","coldkey_short","validators",
                   "period_start_alpha","current_alpha","earned_alpha"]
    with open(OUTPUT_CSV, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for r in rows:
            writer.writerow({"run_timestamp": run_ts, **r})
    print(f"Saved to {OUTPUT_CSV}")

if __name__ == "__main__":
    main()
