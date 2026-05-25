import requests
import csv
import os
import time
from datetime import datetime, timezone, timedelta

API_KEY    = os.environ.get("TAOSTATS_API_KEY", "")
NETUID     = 118
OUTPUT_CSV = "sn118_daily_alpha.csv"

# Free tier: 5 requests per minute = 1 request every 12 seconds minimum
# We use 15 seconds to be safe
RATE_LIMIT_DELAY = 15

WALLETS = [
    ("5GU1RuZTnencf9ETjtStxSWrh5UyMUxpJDjy5Y74fCnvLCPJ", "Wallet1_Ditto"),
    ("5F9tvGHYMkoJ95biTvmscmnW6bxzXq5VUsGhX4q4fZvpu2sy", "Wallet2_1T1BAI"),
    ("5CZtgF1xChRMKXrihA62smGMvhtRCaSsyz1tRqngCJQoVL4f", "Wallet3_taobotE2L"),
    ("5FnxK1znrcQka73mPaHJgY4s14ryGVvmXtUwFHw9so2AdWsE", "Wallet4_TAOcom"),
    ("5DcFxprQ9LCwezrjetRwfJeAd2bVTVgzu3eENRg9tGNnD9on", "Wallet5_TAOcom"),
    ("5GUEJ2h8anTrN2UpJTTyPopbKKCRkAC3WsFc2wrqTbFpmN6U", "Wallet6_taobotTAOcom"),
    ("5HYKqWwQgcWnRNbzCwX6gDA9RF6VBdAmaKxJFyQ17NUTiHGg", "Wallet7_DittoTAOcom"),
]

HEADERS = {
    "Authorization": API_KEY,
    "accept": "application/json",
}
BASE_URL = "https://api.taostats.io/api"


def get_current_positions(coldkey):
    url = f"{BASE_URL}/dtao/stake_balance/latest/v1"
    params = {"coldkey": coldkey, "netuid": NETUID, "limit": 20}
    resp = requests.get(url, headers=HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    positions = []
    for item in data.get("data", []):
        bal = int(item["balance"]) / 1e9
        if bal > 0:
            positions.append({
                "hotkey": item["hotkey"]["ss58"],
                "hotkey_name": item.get("hotkey_name", "unknown"),
                "balance": bal
            })
    return positions


def get_midnight_snapshot(coldkey, hotkey):
    url = f"{BASE_URL}/dtao/stake_balance/history/v1"
    params = {
        "coldkey": coldkey,
        "hotkey": hotkey,
        "netuid": NETUID,
        "days": 1,
        "limit": 50,
    }
    resp = requests.get(url, headers=HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    items = data.get("data", [])
    if not items:
        return None, None
    for item in items:
        ts = item["timestamp"]
        hour_part = ts[11:16]
        if hour_part >= "23:50":
            bal = int(item["balance"]) / 1e9
            return bal, ts
    newest = items[0]
    return int(newest["balance"]) / 1e9, newest["timestamp"]


def get_wallet_data(coldkey, label):
    now_utc = datetime.now(timezone.utc)
    run_ts = now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
    run_date = now_utc.strftime("%Y-%m-%d")
    print(f"  Fetching current positions for {label}...")
    positions = get_current_positions(coldkey)
    time.sleep(RATE_LIMIT_DELAY)
    if not positions:
        return {
            "run_timestamp": run_ts, "run_date": run_date,
            "wallet_label": label, "coldkey": coldkey,
            "hotkey": "N/A", "hotkey_name": "N/A",
            "current_alpha": "N/A", "period_start_alpha": "N/A",
            "earned_alpha": "N/A", "notes": "no_active_positions",
        }
    total_current = 0.0
    total_period_start = 0.0
    hotkey_names = []
    missing_history = []
    period_start_ts = None
    for i, pos in enumerate(positions):
        total_current += pos["balance"]
        hotkey_names.append(pos["hotkey_name"] or pos["hotkey"][:12])
        print(f"  Fetching history for {pos['hotkey_name']} ({pos['hotkey'][:12]})...")
        ps_bal, ps_ts = get_midnight_snapshot(coldkey, pos["hotkey"])
        if i < len(positions) - 1:
            time.sleep(RATE_LIMIT_DELAY)
        if ps_bal is not None:
            total_period_start += ps_bal
            if period_start_ts is None:
                period_start_ts = ps_ts
            print(f"    period_start={ps_bal:.6f} (from {ps_ts})")
        else:
            missing_history.append(pos["hotkey_name"] or pos["hotkey"][:12])
            print(f"    WARNING: No history found for {pos['hotkey_name']}")
    time.sleep(RATE_LIMIT_DELAY)
    if missing_history and total_period_start == 0.0:
        notes = f"NO_HISTORY: {'+'.join(missing_history)}"
        earned = "N/A"
        period_start_str = "N/A"
    elif missing_history:
        notes = f"PARTIAL missing:{'+'.join(missing_history)}"
        earned = total_current - total_period_start
        period_start_str = f"{total_period_start:.6f}"
    else:
        earned = total_current - total_period_start
        notes = f"validators:{'+'.join(hotkey_names)}"
        period_start_str = f"{total_period_start:.6f}"
    return {
        "run_timestamp": run_ts, "run_date": run_date,
        "wallet_label": label, "coldkey": coldkey,
        "hotkey": "+".join(p["hotkey"][:12] for p in positions),
        "hotkey_name": "+".join(hotkey_names),
        "current_alpha": f"{total_current:.6f}",
        "period_start_alpha": period_start_str,
        "earned_alpha": f"{earned:.6f}" if earned != "N/A" else "N/A",
        "notes": notes,
    }


def append_to_csv(rows):
    fieldnames = [
        "run_timestamp", "run_date", "wallet_label", "coldkey",
        "hotkey", "hotkey_name",
        "current_alpha", "period_start_alpha", "earned_alpha", "notes"
    ]
    file_exists = os.path.isfile(OUTPUT_CSV)
    with open(OUTPUT_CSV, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main():
    if not API_KEY:
        raise RuntimeError("TAOSTATS_API_KEY environment variable not set")
    print(f"Starting SN118 tracker run at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    rows = []
    for coldkey, label in WALLETS:
        print(f"\nProcessing {label} ({coldkey[:12]}...):")
        row = get_wallet_data(coldkey, label)
        rows.append(row)
        print(f"  Result: current={row['current_alpha']}, period_start={row['period_start_alpha']}, earned={row['earned_alpha']}")
    append_to_csv(rows)
    print(f"\nDone! Appended {len(rows)} rows to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()

