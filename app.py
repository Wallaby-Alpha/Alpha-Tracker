"""
Solana Holder Cohort Analyzer
==============================
Streamlit app — deploy free on Streamlit Community Cloud.

To add paid access gating later:
  1. In Streamlit Cloud dashboard → Secrets, add:
        ACCESS_CODES = ["code1", "code2", "code3"]
  2. Uncomment the gating block below (search "GATING").
"""

import io
import json
import time
import requests
import pandas as pd
import streamlit as st
from collections import defaultdict

# ── page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Holder Cohort Analyzer",
    page_icon="🔬",
    layout="centered",
)

# ── minimal dark-ish styling ──────────────────────────────────────────────────
st.markdown("""
<style>
    .cohort-header { font-size: 1.1rem; font-weight: 700; margin-top: 1.2rem; }
    .wallet-row { font-family: monospace; font-size: 0.82rem; padding: 2px 0; }
    .summary-box {
        background: #1e1e2e;
        border-radius: 10px;
        padding: 1rem 1.5rem;
        margin-bottom: 1rem;
        color: #cdd6f4;
    }
    .stProgress > div > div { background-color: #89b4fa; }
</style>
""", unsafe_allow_html=True)

# ── constants ─────────────────────────────────────────────────────────────────
COHORT_BRACKETS = [
    {"name": "Whale 🐋",   "emoji": "🐋", "min_usd": 100_000, "max_usd": float("inf"),  "color": "#cba6f7"},
    {"name": "Shark 🦈",   "emoji": "🦈", "min_usd": 25_000,  "max_usd": 100_000,       "color": "#89b4fa"},
    {"name": "Dolphin 🐬", "emoji": "🐬", "min_usd": 5_000,   "max_usd": 25_000,        "color": "#94e2d5"},
    {"name": "Fish 🐟",    "emoji": "🐟", "min_usd": 500,     "max_usd": 5_000,         "color": "#a6e3a1"},
    {"name": "Minnow 🦐",  "emoji": "🦐", "min_usd": 0,       "max_usd": 500,           "color": "#f38ba8"},
]
MAX_WALLETS = 150

# ── helpers ───────────────────────────────────────────────────────────────────
def fetch_wallet_usd_value(wallet: str, helius_url: str) -> float:
    payload = {
        "jsonrpc": "2.0",
        "id": "wallet-value",
        "method": "getAssetsByOwner",
        "params": {
            "ownerAddress": wallet,
            "page": 1,
            "limit": 1000,
            "displayOptions": {"showFungible": True},
        },
    }
    try:
        resp = requests.post(helius_url, json=payload, timeout=30)
        resp.raise_for_status()
        items = resp.json().get("result", {}).get("items", [])
        total = 0.0
        for item in items:
            token_info = item.get("token_info", {})
            price_info = token_info.get("price_info", {})
            if price_info:
                price  = float(price_info.get("price_per_token", 0))
                bal    = float(token_info.get("balance", 0))
                dec    = int(token_info.get("decimals", 0))
                actual = bal / (10 ** dec) if dec > 0 else bal
                total += actual * price
        return total
    except Exception:
        return 0.0


def assign_cohort(usd_value: float) -> str:
    for b in COHORT_BRACKETS:
        if b["min_usd"] <= usd_value < b["max_usd"]:
            return b["name"]
    return "Minnow 🦐"


def detect_address_column(df: pd.DataFrame):
    for col in df.columns:
        if df[col].astype(str).str.match(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$").any():
            return col
    return None


# ══════════════════════════════════════════════════════════════════════════════
# GATING BLOCK — uncomment when you want to sell access
# ══════════════════════════════════════════════════════════════════════════════
# def check_access():
#     """Returns True if the user has a valid access code."""
#     valid_codes = st.secrets.get("ACCESS_CODES", [])
#     code = st.text_input("Enter access code", type="password", key="access_code")
#     if not code:
#         st.info("Enter your access code to continue. Purchase at [your-site.com](https://your-site.com).")
#         st.stop()
#     if code not in valid_codes:
#         st.error("Invalid access code.")
#         st.stop()
#
# check_access()   ← uncomment this line too
# ══════════════════════════════════════════════════════════════════════════════


# ── UI ────────────────────────────────────────────────────────────────────────
st.title("🔬 Holder Cohort Analyzer")
st.caption("Classify Solana token holders by wallet net worth using Helius DAS API.")

with st.expander("ℹ️ How to use", expanded=False):
    st.markdown("""
1. Get a free Helius API key at [helius.dev](https://helius.dev)
2. Export a holder list as CSV from Solscan, Birdeye, or similar — any CSV with a column of wallet addresses works
3. Paste your key, upload the CSV, hit **Run Analysis**
4. Results show each holder's total portfolio value bucketed into cohorts

**Note:** Analysis is capped at 150 wallets to keep it fast. For larger runs, use the script version.
""")

# ── inputs ────────────────────────────────────────────────────────────────────
st.markdown("### Configuration")

helius_key = st.text_input(
    "Helius API Key",
    type="password",
    placeholder="Paste your key here — it stays in your browser, never stored",
)

uploaded_file = st.file_uploader(
    "Upload holder CSV",
    type=["csv"],
    help="Any CSV with a column of Solana wallet addresses",
)

max_wallets = st.slider(
    "Max wallets to analyze",
    min_value=10,
    max_value=MAX_WALLETS,
    value=50,
    step=10,
    help="More wallets = slower. Each call ~0.2s.",
)

run_btn = st.button("🚀 Run Analysis", type="primary", disabled=not (helius_key and uploaded_file))

# ── analysis ──────────────────────────────────────────────────────────────────
if run_btn:
    helius_url = f"https://mainnet.helius-rpc.com/?api-key={helius_key.strip()}"

    # parse CSV
    df = pd.read_csv(io.BytesIO(uploaded_file.read()))
    addr_col = detect_address_column(df)
    if not addr_col:
        st.error("Could not find a Solana address column in your CSV. Make sure at least one column contains wallet addresses.")
        st.stop()

    wallets = df[addr_col].dropna().astype(str).str.strip().unique().tolist()
    if len(wallets) > max_wallets:
        st.info(f"CSV has {len(wallets)} addresses — analyzing top {max_wallets}.")
        wallets = wallets[:max_wallets]

    st.markdown("---")
    st.markdown(f"**Analyzing {len(wallets)} wallets...** *(est. {len(wallets) * 0.25:.0f}s)*")

    progress_bar = st.progress(0)
    status_text  = st.empty()

    cohort_buckets: dict[str, list] = defaultdict(list)
    results_rows   = []

    for i, wallet in enumerate(wallets):
        status_text.text(f"[{i+1}/{len(wallets)}] {wallet[:12]}...")
        net_worth = fetch_wallet_usd_value(wallet, helius_url)
        label     = assign_cohort(net_worth)
        cohort_buckets[label].append({"wallet": wallet, "net_worth": net_worth})
        results_rows.append({"wallet": wallet, "net_worth_usd": round(net_worth, 2), "cohort": label})
        progress_bar.progress((i + 1) / len(wallets))
        time.sleep(0.2)

    status_text.empty()
    progress_bar.empty()

    # ── results ───────────────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("📊 Cohort Distribution")

    total = len(wallets)
    cols  = st.columns(len(COHORT_BRACKETS))
    for col, bracket in zip(cols, COHORT_BRACKETS):
        count = len(cohort_buckets[bracket["name"]])
        pct   = count / total * 100 if total else 0
        col.metric(bracket["name"], f"{count}", f"{pct:.1f}%")

    st.markdown("---")
    st.subheader("🏷️ Holders by Cohort")

    for bracket in COHORT_BRACKETS:
        members = cohort_buckets[bracket["name"]]
        if not members:
            continue
        with st.expander(f"{bracket['name']}  ·  {len(members)} holders", expanded=len(members) > 0):
            sorted_members = sorted(members, key=lambda x: -x["net_worth"])
            rows = []
            for m in sorted_members:
                rows.append({
                    "Wallet": m["wallet"],
                    "Net Worth (USD)": f"${m['net_worth']:,.2f}",
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # ── download ──────────────────────────────────────────────────────────────
    st.markdown("---")
    results_df = pd.DataFrame(results_rows).sort_values("net_worth_usd", ascending=False)
    csv_bytes  = results_df.to_csv(index=False).encode()
    st.download_button(
        label="⬇️ Download full results CSV",
        data=csv_bytes,
        file_name="holder_cohorts.csv",
        mime="text/csv",
    )
