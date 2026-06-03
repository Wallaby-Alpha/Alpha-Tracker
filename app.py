"""
Solana Wallet Intelligence
===========================
Two-tab Streamlit app — deploy free on Streamlit Community Cloud.

Tab 1 — Cohort Analyzer:  classify holders by total wallet net worth
Tab 2 — Whale Overlap:    find what tokens the big wallets share / are buying

To add paid access gating later:
  1. In Streamlit Cloud dashboard → Secrets, add:
        ACCESS_CODES = ["code1", "code2", "code3"]
  2. Uncomment the GATING BLOCK below.
"""

import io
import time
import requests
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from collections import defaultdict

# ── page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Solana Wallet Intel",
    page_icon="🔬",
    layout="centered",
)

st.markdown("""
<style>
    .stProgress > div > div { background-color: #89b4fa; }
    code { font-size: 0.78rem; }
</style>
""", unsafe_allow_html=True)

# ── constants ─────────────────────────────────────────────────────────────────
COHORT_BRACKETS = [
    {"name": "Whale 🐋",   "min_usd": 100_000, "max_usd": float("inf")},
    {"name": "Shark 🦈",   "min_usd": 25_000,  "max_usd": 100_000},
    {"name": "Dolphin 🐬", "min_usd": 5_000,   "max_usd": 25_000},
    {"name": "Fish 🐟",    "min_usd": 500,     "max_usd": 5_000},
    {"name": "Minnow 🦐",  "min_usd": 0,       "max_usd": 500},
]

SKIP_TOKENS = {
    "So11111111111111111111111111111111111111112",   # wSOL
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB", # USDT
}

MAX_WALLETS = 150


# ══════════════════════════════════════════════════════════════════════════════
# GATING BLOCK — uncomment when you want to sell access
# ══════════════════════════════════════════════════════════════════════════════
# def check_access():
#     valid_codes = st.secrets.get("ACCESS_CODES", [])
#     code = st.text_input("Enter access code", type="password", key="access_code")
#     if not code:
#         st.info("Enter your access code to continue. Purchase at [your-site.com](https://your-site.com).")
#         st.stop()
#     if code not in valid_codes:
#         st.error("Invalid access code.")
#         st.stop()
# check_access()
# ══════════════════════════════════════════════════════════════════════════════


# ── shared API helpers ────────────────────────────────────────────────────────
def get_assets(wallet: str, helius_url: str) -> list:
    """Fetch all fungible assets for a wallet via Helius DAS."""
    payload = {
        "jsonrpc": "2.0", "id": "wai",
        "method": "getAssetsByOwner",
        "params": {
            "ownerAddress": wallet,
            "page": 1, "limit": 1000,
            "displayOptions": {"showFungible": True},
        },
    }
    try:
        r = requests.post(helius_url, json=payload, timeout=30)
        r.raise_for_status()
        return r.json().get("result", {}).get("items", [])
    except Exception:
        return []


def wallet_usd_value(assets: list) -> float:
    total = 0.0
    for item in assets:
        ti = item.get("token_info", {})
        pi = ti.get("price_info", {})
        if pi:
            price  = float(pi.get("price_per_token", 0))
            bal    = float(ti.get("balance", 0))
            dec    = int(ti.get("decimals", 0))
            actual = bal / (10 ** dec) if dec > 0 else bal
            total += actual * price
    return total


def assign_cohort(usd: float) -> str:
    for b in COHORT_BRACKETS:
        if b["min_usd"] <= usd < b["max_usd"]:
            return b["name"]
    return "Minnow 🦐"


def detect_address_col(df: pd.DataFrame):
    for col in df.columns:
        if df[col].astype(str).str.match(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$").any():
            return col
    return None


def parse_wallets_from_csv(uploaded) -> list:
    df = pd.read_csv(io.BytesIO(uploaded.read()))
    col = detect_address_col(df)
    if not col:
        return []
    return df[col].dropna().astype(str).str.strip().unique().tolist()


# ── global sidebar: API key + remember me ────────────────────────────────────
with st.sidebar:
    st.title("🔬 Solana Wallet Intel")
    st.markdown("---")

    # localStorage bridge — saves key client-side only
    components.html("""
<script>
(function() {
    const saved = localStorage.getItem('helius_api_key');
    if (saved) {
        window.parent.postMessage({type: 'helius_key', key: saved}, '*');
    }
})();
window.addEventListener('message', function(e) {
    if (e.data && e.data.type === 'save_helius_key')
        localStorage.setItem('helius_api_key', e.data.key);
    if (e.data && e.data.type === 'clear_helius_key')
        localStorage.removeItem('helius_api_key');
});
</script>
""", height=0)

    if "helius_key_value" not in st.session_state:
        st.session_state["helius_key_value"] = ""

    helius_key = st.text_input(
        "Helius API Key",
        type="password",
        placeholder="Paste key — stays in your browser",
        value=st.session_state["helius_key_value"],
        key="helius_key_input",
    )
    remember = st.checkbox("Remember in this browser", value=True)

    if helius_key:
        st.session_state["helius_key_value"] = helius_key
        if remember:
            components.html(f"""
<script>
window.parent.postMessage({{type: 'save_helius_key', key: '{helius_key}'}}, '*');
</script>
""", height=0)
        else:
            components.html("""
<script>
window.parent.postMessage({type: 'clear_helius_key'}, '*');
</script>
""", height=0)

    if not helius_key:
        st.info("💡 Saved key auto-fills after page load.")

    st.markdown("---")
    st.caption("Get a free key at [helius.dev](https://helius.dev)")


HELIUS_URL = f"https://mainnet.helius-rpc.com/?api-key={helius_key.strip()}" if helius_key else ""


# ── tabs ──────────────────────────────────────────────────────────────────────
tab1, tab2 = st.tabs(["🐋 Cohort Analyzer", "🔍 Whale Overlap"])


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 1 — COHORT ANALYZER
# ══════════════════════════════════════════════════════════════════════════════
with tab1:
    st.header("Cohort Analyzer")
    st.caption("Classify token holders by total wallet net worth.")

    with st.expander("ℹ️ How to use", expanded=False):
        st.markdown("""
1. Export a holder list as CSV from Solscan, Birdeye, or similar
2. Upload it below and hit **Run Cohort Analysis**
3. Whales & Sharks found here are automatically available in the **Whale Overlap** tab
""")

    c1_file = st.file_uploader("Upload holder CSV", type=["csv"], key="c1_file")
    c1_max  = st.slider("Max wallets", 10, MAX_WALLETS, 50, 10, key="c1_max")
    c1_btn  = st.button("🚀 Run Cohort Analysis", type="primary",
                        disabled=not (helius_key and c1_file), key="c1_btn")

    if c1_btn:
        wallets = parse_wallets_from_csv(c1_file)
        if not wallets:
            st.error("No valid Solana addresses found in CSV.")
            st.stop()
        if len(wallets) > c1_max:
            st.info(f"CSV has {len(wallets)} addresses — analyzing top {c1_max}.")
            wallets = wallets[:c1_max]

        st.markdown("---")
        prog = st.progress(0)
        status = st.empty()

        cohort_buckets = defaultdict(list)
        rows = []

        for i, wallet in enumerate(wallets):
            status.text(f"[{i+1}/{len(wallets)}] {wallet[:12]}...")
            assets    = get_assets(wallet, HELIUS_URL)
            net_worth = wallet_usd_value(assets)
            label     = assign_cohort(net_worth)
            cohort_buckets[label].append({"wallet": wallet, "net_worth": net_worth})
            rows.append({"wallet": wallet, "net_worth_usd": round(net_worth, 2), "cohort": label})
            prog.progress((i + 1) / len(wallets))
            time.sleep(0.2)

        status.empty()
        prog.empty()

        # Save whales+sharks to session state for Tab 2
        big_wallets = [
            r["wallet"] for r in rows
            if r["cohort"] in ("Whale 🐋", "Shark 🦈")
        ]
        st.session_state["whale_wallets"] = big_wallets
        if big_wallets:
            st.success(f"✅ {len(big_wallets)} Whale/Shark wallets saved — available in the Whale Overlap tab.")

        # Distribution metrics
        st.markdown("---")
        st.subheader("📊 Distribution")
        total = len(wallets)
        cols  = st.columns(len(COHORT_BRACKETS))
        for col, bracket in zip(cols, COHORT_BRACKETS):
            count = len(cohort_buckets[bracket["name"]])
            col.metric(bracket["name"], count, f"{count/total*100:.1f}%")

        # Per-cohort tables
        st.markdown("---")
        st.subheader("🏷️ Holders by Cohort")
        for bracket in COHORT_BRACKETS:
            members = cohort_buckets[bracket["name"]]
            if not members:
                continue
            with st.expander(f"{bracket['name']}  ·  {len(members)} holders"):
                df_out = pd.DataFrame([
                    {"Wallet": m["wallet"], "Net Worth (USD)": f"${m['net_worth']:,.2f}"}
                    for m in sorted(members, key=lambda x: -x["net_worth"])
                ])
                st.dataframe(df_out, use_container_width=True, hide_index=True)

        # Download
        st.markdown("---")
        csv_bytes = pd.DataFrame(rows).sort_values("net_worth_usd", ascending=False).to_csv(index=False).encode()
        st.download_button("⬇️ Download results CSV", csv_bytes, "holder_cohorts.csv", "text/csv")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 2 — WHALE OVERLAP
# ══════════════════════════════════════════════════════════════════════════════
with tab2:
    st.header("Whale Overlap")
    st.caption("See what tokens a group of wallets share — find what the big players are all holding.")

    with st.expander("ℹ️ How to use", expanded=False):
        st.markdown("""
**Two ways to load wallets:**
- Run the Cohort Analyzer first → Whales & Sharks auto-populate here
- Or paste wallet addresses directly (one per line)

Results show every token held by 2+ of the wallets, ranked by how many wallets share it.
Stablecoins and wSOL are filtered out automatically.
""")

    # Source selector
    source = st.radio(
        "Wallet source",
        ["Use Whales/Sharks from Cohort tab", "Paste wallets manually", "Upload new CSV"],
        key="t2_source",
        horizontal=True,
    )

    t2_wallets = []

    if source == "Use Whales/Sharks from Cohort tab":
        saved = st.session_state.get("whale_wallets", [])
        if saved:
            st.success(f"{len(saved)} wallets loaded from Cohort Analysis.")
            t2_wallets = saved
            with st.expander("View wallets"):
                for w in saved:
                    st.code(w)
        else:
            st.info("Run the Cohort Analyzer first to populate this automatically.")

    elif source == "Paste wallets manually":
        raw = st.text_area(
            "Paste wallet addresses (one per line)",
            height=150,
            placeholder="7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU\n...",
            key="t2_paste",
        )
        if raw.strip():
            t2_wallets = [w.strip() for w in raw.strip().splitlines() if len(w.strip()) >= 32]
            st.caption(f"{len(t2_wallets)} addresses detected.")

    else:  # Upload new CSV
        t2_file = st.file_uploader("Upload wallet CSV", type=["csv"], key="t2_file")
        if t2_file:
            t2_wallets = parse_wallets_from_csv(t2_file)
            if t2_wallets:
                st.caption(f"{len(t2_wallets)} addresses found.")
            else:
                st.error("No valid Solana addresses detected in CSV.")

    t2_max = st.slider("Max wallets to scan", 5, MAX_WALLETS, 30, 5, key="t2_max")
    min_shared = st.slider("Min wallets sharing a token (filter noise)", 2, 10, 2, 1, key="t2_min")

    t2_btn = st.button(
        "🔍 Run Overlap Analysis",
        type="primary",
        disabled=not (helius_key and t2_wallets),
        key="t2_btn",
    )

    if t2_btn:
        wallets = t2_wallets[:t2_max]
        if len(t2_wallets) > t2_max:
            st.info(f"Capped to {t2_max} wallets.")

        st.markdown("---")
        prog2   = st.progress(0)
        status2 = st.empty()

        token_counts   = defaultdict(int)
        token_metadata = {}
        token_holders  = defaultdict(list)

        for i, wallet in enumerate(wallets):
            status2.text(f"[{i+1}/{len(wallets)}] {wallet[:12]}...")
            assets = get_assets(wallet, HELIUS_URL)
            seen_this_wallet = set()

            for asset in assets:
                mint      = asset.get("id", "")
                interface = asset.get("interface", "")
                if interface != "FungibleToken" or mint in SKIP_TOKENS:
                    continue
                ti  = asset.get("token_info", {})
                bal = float(ti.get("balance", 0))
                if bal <= 0 or mint in seen_this_wallet:
                    continue

                seen_this_wallet.add(mint)
                token_counts[mint] += 1
                token_holders[mint].append(wallet)

                if mint not in token_metadata:
                    meta = asset.get("content", {}).get("metadata", {})
                    pi   = ti.get("price_info", {})
                    token_metadata[mint] = {
                        "symbol":    meta.get("symbol", "???"),
                        "name":      meta.get("name", "Unknown"),
                        "price_usd": float(pi.get("price_per_token", 0)),
                    }

            prog2.progress((i + 1) / len(wallets))
            time.sleep(0.2)

        status2.empty()
        prog2.empty()

        # Filter and sort
        shared = {m: c for m, c in token_counts.items() if c >= min_shared}
        sorted_tokens = sorted(shared.items(), key=lambda x: -x[1])

        if not sorted_tokens:
            st.warning(f"No tokens found shared by {min_shared}+ wallets.")
        else:
            st.subheader(f"🏆 {len(sorted_tokens)} shared tokens found")

            # Summary table
            summary_rows = []
            for mint, count in sorted_tokens[:50]:
                meta = token_metadata[mint]
                summary_rows.append({
                    "Symbol":        meta["symbol"],
                    "Name":          meta["name"],
                    "Wallets Holding": count,
                    "% of Group":    f"{count/len(wallets)*100:.1f}%",
                    "Price (USD)":   f"${meta['price_usd']:,.6f}" if meta["price_usd"] > 0 else "—",
                    "Mint":          mint,
                })
            st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

            # Expandable detail per token
            st.markdown("---")
            st.subheader("🔎 Token Detail")
            for mint, count in sorted_tokens[:30]:
                meta    = token_metadata[mint]
                holders = token_holders[mint]
                pct     = count / len(wallets) * 100
                with st.expander(f"**{meta['symbol']}** — {count} wallets ({pct:.1f}%)  ·  {meta['name']}"):
                    st.caption(f"Mint: `{mint}`")
                    if meta["price_usd"] > 0:
                        st.caption(f"Price: ${meta['price_usd']:,.6f}")
                    for h in holders:
                        st.code(h)

            # Download
            st.markdown("---")
            dl_rows = []
            for mint, count in sorted_tokens:
                meta = token_metadata[mint]
                for h in token_holders[mint]:
                    dl_rows.append({
                        "mint": mint,
                        "symbol": meta["symbol"],
                        "name": meta["name"],
                        "wallets_holding": count,
                        "wallet": h,
                    })
            csv2 = pd.DataFrame(dl_rows).to_csv(index=False).encode()
            st.download_button("⬇️ Download overlap CSV", csv2, "whale_overlap.csv", "text/csv")
