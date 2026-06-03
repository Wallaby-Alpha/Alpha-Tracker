"""
Solana Wallet Intelligence
===========================
Three-tab Streamlit app — deploy free on Streamlit Community Cloud.

Tab 1 — Cohort Analyzer:     classify holders by total wallet net worth
Tab 2 — Whale Overlap:       find what tokens the big wallets currently share
Tab 3 — Recent Acquisitions: what have whales/sharks actually bought in last N days

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
from datetime import datetime, timezone, timedelta

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
tab1, tab2, tab3 = st.tabs(["🐋 Cohort Analyzer", "🔍 Whale Overlap", "📅 Recent Buys"])


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
            st.success(f"✅ {len(big_wallets)} Whale/Shark wallets saved — available in Whale Overlap and Recent Buys tabs.")

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


# ── acquisition helpers (Tab 3) ───────────────────────────────────────────────
def fetch_signatures(wallet: str, helius_url: str, limit: int = 100) -> list:
    payload = {
        "jsonrpc": "2.0", "id": "sigs",
        "method": "getSignaturesForAddress",
        "params": [wallet, {"limit": limit}],
    }
    try:
        r = requests.post(helius_url, json=payload, timeout=30)
        r.raise_for_status()
        return r.json().get("result", [])
    except Exception:
        return []


def fetch_transaction(sig: str, helius_url: str):
    payload = {
        "jsonrpc": "2.0", "id": "tx",
        "method": "getTransaction",
        "params": [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
    }
    try:
        r = requests.post(helius_url, json=payload, timeout=30)
        r.raise_for_status()
        return r.json().get("result")
    except Exception:
        return None


def parse_token_inflows(tx, wallet: str, sig: str) -> list:
    """Return list of token inflows for `wallet` in `tx`."""
    inflows = []
    if not tx:
        return inflows

    meta       = tx.get("meta", {})
    block_time = tx.get("blockTime", 0)

    pre  = {e["accountIndex"]: e for e in meta.get("preTokenBalances", [])}
    post = {e["accountIndex"]: e for e in meta.get("postTokenBalances", [])}

    # Collect indices owned by this wallet
    wallet_indices = set()
    for i, key_info in enumerate(tx.get("transaction", {}).get("message", {}).get("accountKeys", [])):
        pubkey = key_info if isinstance(key_info, str) else key_info.get("pubkey", "")
        if pubkey == wallet:
            wallet_indices.add(i)
    for idx in set(pre) | set(post):
        entry = post.get(idx) or pre.get(idx, {})
        if entry.get("owner") == wallet:
            wallet_indices.add(idx)

    for idx in wallet_indices:
        pre_entry  = pre.get(idx, {})
        post_entry = post.get(idx, {})
        pre_amt    = float((pre_entry.get("uiTokenAmount") or {}).get("uiAmount") or 0)
        post_amt   = float((post_entry.get("uiTokenAmount") or {}).get("uiAmount") or 0)
        if post_amt > pre_amt:
            mint = post_entry.get("mint") or pre_entry.get("mint", "unknown")
            if mint in SKIP_TOKENS:
                continue
            inflows.append({
                "mint":            mint,
                "amount_received": round(post_amt - pre_amt, 6),
                "timestamp":       block_time,
                "date":            datetime.fromtimestamp(block_time, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                "tx_sig":          sig,
            })
    return inflows


def scan_wallet_acquisitions(wallet: str, helius_url: str, cutoff_ts: int) -> list:
    """Fetch and parse all token inflows for a wallet since cutoff_ts."""
    acquisitions = []
    sigs = fetch_signatures(wallet, helius_url, limit=100)
    for sig_info in sigs:
        if sig_info.get("blockTime", 0) < cutoff_ts:
            break   # newest-first — safe to stop
        tx     = fetch_transaction(sig_info["signature"], helius_url)
        found  = parse_token_inflows(tx, wallet, sig_info["signature"])
        acquisitions.extend(found)
        time.sleep(0.1)
    return acquisitions


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 3 — RECENT ACQUISITIONS
# ══════════════════════════════════════════════════════════════════════════════
with tab3:
    st.header("Recent Buys")
    st.caption("What tokens have whales/sharks actually purchased in the last N days?")

    with st.expander("ℹ️ How to use", expanded=False):
        st.markdown("""
- Run **Cohort Analyzer** first to auto-populate wallets, or paste/upload your own list
- Set your lookback window (1–30 days)
- Results show every token acquired, flagged when 2+ wallets bought the same one — that's your coordination signal
- Stablecoins and wSOL are filtered automatically
""")

    # Wallet source — same pattern as Tab 2
    t3_source = st.radio(
        "Wallet source",
        ["Use Whales/Sharks from Cohort tab", "Paste wallets manually", "Upload new CSV"],
        key="t3_source",
        horizontal=True,
    )

    t3_wallets = []

    if t3_source == "Use Whales/Sharks from Cohort tab":
        saved3 = st.session_state.get("whale_wallets", [])
        if saved3:
            st.success(f"{len(saved3)} wallets loaded from Cohort Analysis.")
            t3_wallets = saved3
            with st.expander("View wallets"):
                for w in saved3:
                    st.code(w)
        else:
            st.info("Run the Cohort Analyzer first to populate this automatically.")

    elif t3_source == "Paste wallets manually":
        raw3 = st.text_area(
            "Paste wallet addresses (one per line)",
            height=150,
            placeholder="7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU\n...",
            key="t3_paste",
        )
        if raw3.strip():
            t3_wallets = [w.strip() for w in raw3.strip().splitlines() if len(w.strip()) >= 32]
            st.caption(f"{len(t3_wallets)} addresses detected.")

    else:
        t3_file = st.file_uploader("Upload wallet CSV", type=["csv"], key="t3_file")
        if t3_file:
            t3_wallets = parse_wallets_from_csv(t3_file)
            if t3_wallets:
                st.caption(f"{len(t3_wallets)} addresses found.")
            else:
                st.error("No valid Solana addresses detected in CSV.")

    col_a, col_b = st.columns(2)
    with col_a:
        t3_days = st.slider("Lookback (days)", 1, 30, 7, 1, key="t3_days")
    with col_b:
        t3_max  = st.slider("Max wallets to scan", 5, 50, 20, 5, key="t3_max",
                             help="Each wallet scans up to 100 recent txs — keep low for speed")

    t3_min_shared = st.slider(
        "Highlight when bought by N+ wallets",
        2, 10, 2, 1, key="t3_min_shared",
        help="Tokens bought by this many wallets are flagged as coordination signals",
    )

    t3_btn = st.button(
        "📅 Run Acquisition Scan",
        type="primary",
        disabled=not (helius_key and t3_wallets),
        key="t3_btn",
    )

    if t3_btn:
        wallets3   = t3_wallets[:t3_max]
        cutoff_ts  = int((datetime.now(timezone.utc) - timedelta(days=t3_days)).timestamp())
        cutoff_str = datetime.fromtimestamp(cutoff_ts, tz=timezone.utc).strftime("%Y-%m-%d")

        if len(t3_wallets) > t3_max:
            st.info(f"Capped to {t3_max} wallets.")

        st.markdown(f"**Scanning {len(wallets3)} wallets for buys since {cutoff_str}...**")
        st.caption("This tab reads raw transactions — it's slower than the others. ~2–5s per wallet.")

        prog3   = st.progress(0)
        status3 = st.empty()

        all_acq        = []          # flat list of acquisition dicts
        token_wallets3 = defaultdict(set)   # mint -> set of wallets that bought it
        token_meta3    = {}          # mint -> {symbol, name}

        for i, wallet in enumerate(wallets3):
            status3.text(f"[{i+1}/{len(wallets3)}] {wallet[:12]}... scanning transactions")
            acqs = scan_wallet_acquisitions(wallet, HELIUS_URL, cutoff_ts)

            for acq in acqs:
                mint = acq["mint"]
                token_wallets3[mint].add(wallet)
                acq["wallet"] = wallet
                all_acq.append(acq)

                # Try to grab symbol/name from a parallel DAS call if not seen yet
                if mint not in token_meta3:
                    token_meta3[mint] = {"symbol": mint[:8], "name": ""}

            prog3.progress((i + 1) / len(wallets3))

        status3.empty()
        prog3.empty()

        if not all_acq:
            st.warning(f"No token inflows found in the last {t3_days} days for these wallets.")
        else:
            # Enrich metadata in one batch DAS call
            unknown_mints = [m for m in token_meta3 if token_meta3[m]["name"] == ""]
            if unknown_mints:
                for i in range(0, len(unknown_mints), 100):
                    batch = unknown_mints[i:i+100]
                    try:
                        r = requests.post(HELIUS_URL, json={
                            "jsonrpc": "2.0", "id": "batch-meta",
                            "method": "getAssetBatch",
                            "params": {"ids": batch},
                        }, timeout=30)
                        for asset in r.json().get("result", []):
                            mint = asset.get("id", "")
                            if mint:
                                meta = asset.get("content", {}).get("metadata", {})
                                token_meta3[mint] = {
                                    "symbol": meta.get("symbol", mint[:8]),
                                    "name":   meta.get("name", "Unknown"),
                                }
                    except Exception:
                        pass

            # Build summary: one row per (mint, wallet) — deduplicated by buy events
            summary = []
            for mint, buying_wallets in token_wallets3.items():
                meta    = token_meta3.get(mint, {"symbol": mint[:8], "name": ""})
                n_buys  = len(buying_wallets)
                # collect all individual acquisition events for this mint
                events  = [a for a in all_acq if a["mint"] == mint]
                total_amt = sum(e["amount_received"] for e in events)
                latest  = max(e["date"] for e in events)
                summary.append({
                    "mint":           mint,
                    "symbol":         meta["symbol"],
                    "name":           meta["name"],
                    "wallets_bought": n_buys,
                    "total_received": round(total_amt, 4),
                    "last_seen":      latest,
                    "coordinated":    n_buys >= t3_min_shared,
                })

            summary.sort(key=lambda x: (-x["wallets_bought"], x["last_seen"]))

            # ── coordination signals (top of page) ───────────────────────────
            coordinated = [s for s in summary if s["coordinated"]]
            if coordinated:
                st.markdown("---")
                st.subheader(f"🚨 Coordination Signals — bought by {t3_min_shared}+ wallets")
                st.caption("These tokens were independently acquired by multiple whales/sharks in your window.")
                coord_rows = []
                for s in coordinated:
                    coord_rows.append({
                        "Symbol":          s["symbol"],
                        "Name":            s["name"],
                        "Wallets Bought":  s["wallets_bought"],
                        "Total Received":  s["total_received"],
                        "Last Buy":        s["last_seen"],
                        "Mint":            s["mint"],
                    })
                st.dataframe(pd.DataFrame(coord_rows), use_container_width=True, hide_index=True)

                for s in coordinated:
                    buying_ws = sorted(token_wallets3[s["mint"]])
                    with st.expander(f"**{s['symbol']}** — {s['wallets_bought']} wallets · {s['name']}"):
                        st.caption(f"Mint: `{s['mint']}`")
                        events = sorted(
                            [a for a in all_acq if a["mint"] == s["mint"]],
                            key=lambda x: x["timestamp"], reverse=True
                        )
                        for ev in events:
                            st.markdown(
                                f"- `{ev['wallet'][:12]}...`  +{ev['amount_received']:,.2f} tokens  ·  {ev['date']}"
                            )
            else:
                st.info(f"No tokens were bought by {t3_min_shared}+ wallets in this window. Try lowering the threshold or extending the lookback.")

            # ── full acquisition table ────────────────────────────────────────
            st.markdown("---")
            st.subheader(f"📋 All acquisitions ({len(summary)} unique tokens)")
            all_rows = []
            for s in summary:
                all_rows.append({
                    "Symbol":         s["symbol"],
                    "Name":           s["name"],
                    "Wallets":        s["wallets_bought"],
                    "Total Received": s["total_received"],
                    "Last Buy":       s["last_seen"],
                    "🚨 Signal":      "✅" if s["coordinated"] else "",
                    "Mint":           s["mint"],
                })
            st.dataframe(pd.DataFrame(all_rows), use_container_width=True, hide_index=True)

            # ── download ──────────────────────────────────────────────────────
            st.markdown("---")
            dl3_rows = []
            for acq in all_acq:
                meta = token_meta3.get(acq["mint"], {"symbol": "", "name": ""})
                dl3_rows.append({
                    "wallet":          acq["wallet"],
                    "mint":            acq["mint"],
                    "symbol":          meta["symbol"],
                    "name":            meta["name"],
                    "amount_received": acq["amount_received"],
                    "date":            acq["date"],
                    "tx_sig":          acq["tx_sig"],
                    "wallets_bought":  len(token_wallets3[acq["mint"]]),
                    "coordinated":     len(token_wallets3[acq["mint"]]) >= t3_min_shared,
                })
            csv3 = pd.DataFrame(dl3_rows).sort_values(
                ["coordinated", "wallets_bought"], ascending=[False, False]
            ).to_csv(index=False).encode()
            st.download_button(
                "⬇️ Download acquisition CSV", csv3,
                f"whale_acquisitions_{t3_days}d.csv", "text/csv"
            )
