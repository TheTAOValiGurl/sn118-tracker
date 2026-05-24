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

request_count = 0

def api_get(url, params):
    """Make a single API request with rate-limit protection."""
    global request_count
    # Wait before every request after the first to respect 5 req/min limit
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
    """Get current staking positions for a coldkey on SN118."""
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

def get_balance_24h_ago(coldkey, hotkey_ss58):
    """Get the stake balance snapshot closest to 24 hours ago."""
    now_utc  = datetime.now(timezone.utc)
    # History is stored at midnight UTC. Ask for window ending ~20h ago
    # to reliably capture the previous midnight snapshot.
    ts_end   = int((now_utc - timedelta(hours=20)).timestamp())
    ts_start = int((now_utc - timedelta(hours=32)).timestamp())
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
    return rao_to_alpha(item.get("balance", 0)), item.get("timestamp")

def process_wallet(coldkey, label):
    print(f"  Fetching current positions for {label}...")
    positions = get_current_positions(coldkey)

    if not positions:
        return {
            "label":              label,
            "coldkey_short":      coldkey[:8] + "..." + coldkey[-6:],
            "validators":         "NO POSITION FOUND",
            "period_start_alpha": "N/A",
            "current_alpha":      "N/A",
            "earned_alpha":       "N/A",
        }

    period_start_total = 0.0
    current_total      = 0.0
    validator_names    = []
    history_found      = True

    for pos in positions:
        current_total += pos["balance_alpha"]
        validator_names.append(pos["hotkey_name"])

        print(f"  Fetching 24h history for {pos['hotkey_name']}...")
        bal_24h, ts_24h = get_balance_24h_ago(coldkey, pos["hotkey_ss58"])

        if bal_24h is not None:
            period_start_total += bal_24h
            print(f"    24h ago: {bal_24h:.4f} alpha (snapshot: {ts_24h})")
        else:
            history_found = False
            print(f"    No history snapshot found for {pos['hotkey_name']}")

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
        print(f"\n--- {label} ---")
        try:
            row = process_wallet(coldkey, label)
        except Exception as e:
            print(f"  ERROR: {e}")
            row = {
                "label":              label,
                "coldkey_short":      coldkey[:8] + "..." + coldkey[-6:],
                "validators":         f"ERROR: {e}",
                "period_start_alpha": "ERROR",
                "current_alpha":      "ERROR",
                "earned_alpha":       "ERROR",
            }
        rows.append(row)

    # Print summary table
    print(f"\n{'='*80}")
    print(f"  SN118 Daily Alpha Snapshot  |  {run_ts}")
    print(f"{'='*80}")
    print(f"{'Wallet':<24} {'Validator(s)':<22} {'24h Ago':>12} {'Now':>12} {'Earned':>10}")
    print(f"{'-'*80}")
    total_earned = 0.0
    for r in rows:
        ps  = f"{r['period_start_alpha']:>12.4f}" if isinstance(r['period_start_alpha'], float) else f"{str(r['period_start_alpha']):>12}"
        cur = f"{r['current_alpha']:>12.4f}"      if isinstance(r['current_alpha'], float)      else f"{str(r['current_alpha']):>12}"
        ea  = f"{r['earned_alpha']:>10.4f}"        if isinstance(r['earned_alpha'], float)        else f"{str(r['earned_alpha']):>10}"
        print(f"{r['coldkey_short']:<24} {r['validators'][:22]:<22} {ps} {cur} {ea}")
        if isinstance(r['earned_alpha'], float):
            total_earned += r['earned_alpha']
    print(f"{'='*80}")
    print(f"  Total earned (wallets with history): {total_earned:.4f} alpha")
    print(f"{'='*80}\n")

    # Append to CSV
    file_exists = os.path.isfile(OUTPUT_CSV)
    fieldnames  = ["run_timestamp", "label", "coldkey_short", "validators",
                   "period_start_alpha", "current_alpha", "earned_alpha"]
    with open(OUTPUT_CSV, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for r in rows:
            writer.writerow({"run_timestamp": run_ts, **r})

    print(f"Results saved to {OUTPUT_CSV}")
    print(f"Total API requests made: {request_count}")

if __name__ == "__main__":
    main()
