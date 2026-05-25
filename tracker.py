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

BASE    = "https://api.taostats.io/api/dtao/stake_balance"
HEADERS = {"accept": "application/json", "Authorization": API_KEY}
RAO     = 1_000_000_000

request_count = 0

def api_get(url, params):
    global request_count
    if request_count > 0:
        print(f"  [rate limit pause {RATE_LIMIT_DELAY}s]")
        time.sleep(RATE_LIMIT_DELAY)
    request_count += 1
    r = requests.get(url, headers=HEADERS, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

def rao_to_alpha(val):
    try:
        return int(val) / RAO
    except (TypeError, ValueError):
        return 0.0

def get_current_positions(coldkey):
    data = api_get(f"{BASE}/latest/v1", {
        "coldkey": coldkey, "netuid": NETUID, "limit": 50
    })
    positions = []
    for item in data.get("data", []):
        positions.append({
            "hotkey_ss58":   item["hotkey"]["ss58"],
            "hotkey_name":   item.get("hotkey_name") or item["hotkey"]["ss58"][:12],
            "balance_alpha": rao_to_alpha(item.get("balance", 0)),
        })
    return positions

def get_balance_at_last_midnight(coldkey, hotkey_ss58):
    """Get the stake balance snapshot at the most recent midnight UTC.

    taostats stores history snapshots once per day at midnight UTC.
    We search a 4-hour window centered on the most recent midnight UTC
    to reliably catch the snapshot regardless of what time the script runs.
    """
    now_utc = datetime.now(timezone.utc)

    # Most recent midnight UTC
    last_midnight = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)

    # If we are within 5 minutes of midnight, use yesterday's midnight to be safe
    if (now_utc - last_midnight).total_seconds() < 300:
        last_midnight = last_midnight - timedelta(days=1)

    # Search window: 2 hours before to 2 hours after midnight
    ts_start = int((last_midnight - timedelta(hours=2)).timestamp())
    ts_end   = int((last_midnight + timedelta(hours=2)).timestamp())

    print(f"    Querying history window: {last_midnight.strftime('%Y-%m-%d %H:%M UTC')}")

    data = api_get(f"{BASE}/history/v1", {
        "coldkey":         coldkey,
        "hotkey":          hotkey_ss58,
        "netuid":          NETUID,
        "timestamp_start": ts_start,
        "timestamp_end":   ts_end,
        "order":           "timestamp_desc",
        "limit":           1,
    })
    items = data.get("data", [])
    if not items:
        return None, None
    item = items[0]
    bal  = rao_to_alpha(item.get("balance", 0))
    ts   = item.get("timestamp", "?")
    return bal, ts

def process_wallet(coldkey, label):
    print(f"\nProcessing {label} ({coldkey[:8]}...)")

    positions = get_current_positions(coldkey)
    if not positions:
        print(f"  No positions found!")
        return {
            "label":              label,
            "coldkey_short":      coldkey[:8] + "..." + coldkey[-6:],
            "validators":         "NO_POSITION",
            "period_start_alpha": "N/A",
            "current_alpha":      0.0,
            "earned_alpha":       "NO_POSITION",
        }

    current_total      = 0.0
    period_start_total = 0.0
    history_found      = True
    validator_names    = []

    for pos in positions:
        current_total += pos["balance_alpha"]
        validator_names.append(pos["hotkey_name"])
        print(f"  Validator: {pos['hotkey_name']}, current: {pos['balance_alpha']:.4f} alpha")

        bal_midnight, ts_midnight = get_balance_at_last_midnight(coldkey, pos["hotkey_ss58"])
        if bal_midnight is not None:
            period_start_total += bal_midnight
            print(f"    Midnight snapshot: {bal_midnight:.4f} alpha (ts: {ts_midnight})")
        else:
            history_found = False
            print(f"    No midnight snapshot found for {pos['hotkey_name']}")

    if not history_found:
        earned_str = "NO_HISTORY"
    else:
        earned_str = round(current_total - period_start_total, 6)

    return {
        "label":              label,
        "coldkey_short":      coldkey[:8] + "..." + coldkey[-6:],
        "validators":         " + ".join(validator_names),
        "period_start_alpha": round(period_start_total, 6) if history_found else "N/A",
        "current_alpha":      round(current_total, 6),
        "earned_alpha":       earned_str,
    }

def main():
    now_pst = datetime.now(timezone(timedelta(hours=-8)))
    run_ts  = now_pst.strftime("%Y-%m-%d %H:%M PST")
    print(f"\nStarting SN118 tracker run at {run_ts}")
    print(f"Rate limit delay: {RATE_LIMIT_DELAY}s between requests\n")

    rows = []
    for coldkey, label in WALLETS:
        result = process_wallet(coldkey, label)
        result["run_timestamp"] = run_ts
        rows.append(result)

    fieldnames = ["run_timestamp", "label", "coldkey_short", "validators",
                  "period_start_alpha", "current_alpha", "earned_alpha"]

    file_exists = os.path.exists(OUTPUT_CSV)
    with open(OUTPUT_CSV, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for row in rows:
            writer.writerow(row)

    print(f"\nDone - {len(rows)} rows written to {OUTPUT_CSV}")
    for r in rows:
        print(f"  {r['label']}: start={r['period_start_alpha']}  "
              f"current={r['current_alpha']}  earned={r['earned_alpha']}")

if __name__ == "__main__":
    main()
