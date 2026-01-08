import streamlit as st
import pandas as pd
import requests
import time

# --- CONFIGURATION ---
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Content-Type": "application/json"
}

RPC_NODES = [
    "https://fullnode.mainnet.sui.io:443",
    "https://sui-rpc.publicnode.com",
    "https://sui-mainnet.nodeinfra.com:443",
    "https://mainnet.sui.rpcpool.com:443",
    "https://rpc.mainnet.sui.io:443"
]

def make_rpc_call(method, params):
    for node in RPC_NODES:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        try:
            response = requests.post(node, json=payload, headers=HEADERS, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if "result" in data:
                    return data["result"]
        except Exception:
            continue 
    return None

def get_validator_map():
    """
    Downloads the official list. Returns empty dict {} if failed (Prevent Crash).
    """
    validator_map = {}
    try:
        result = make_rpc_call("suix_getLatestSuiSystemStateV2", [])
        if result:
            for v in result.get('activeValidators', []):
                validator_map[v['suiAddress'].lower()] = v['name']
    except:
        pass # Fail silently, we will use Blind Mode
    return validator_map

def parse_transaction(tx_hash, validator_map, target_keyword):
    # 1. SAFETY FIX: Ensure map is never None
    if validator_map is None:
        validator_map = {}

    tx_data = make_rpc_call(
        "sui_getTransactionBlock", 
        [tx_hash, {"showEvents": True, "showBalanceChanges": True}]
    )
    
    if not tx_data:
        return "Network Error", "Server blocked request"

    target_clean = target_keyword.lower()
    found_items = []

    # 2. Search EVENTS
    events = tx_data.get('events', [])
    for event in events:
        parsed = event.get('parsedJson', {})
        
        # We look for ANY event that has a validator address
        if 'validator_address' in parsed:
            val_addr = parsed.get('validator_address', '').lower()
            amount_mist = float(parsed.get('amount', 0))
            amount_sui = amount_mist / 1_000_000_000
            
            # RESOLVE NAME
            val_name = validator_map.get(val_addr, "Unknown")
            
            # Backup: Check for Nansen prefix based on your screenshot
            if "0xa36a" in val_addr:
                val_name = "Nansen (Likely)"

            # LOGIC:
            # 1. If name matches Nansen -> Return immediately
            # 2. If name is Unknown -> Save it as a backup (Blind Mode)
            
            match_found = target_clean in val_name.lower()
            
            if match_found:
                return -amount_sui, f"✅ Staked to {val_name}"
            else:
                # Save non-matching result just in case the phonebook failed
                found_items.append((-amount_sui, f"❓ Staked to {val_name} ({val_addr[:6]}...)"))

    # 3. Search BALANCE CHANGES (Transfers)
    for change in tx_data.get('balanceChanges', []):
        owner_data = change.get('owner', {})
        if isinstance(owner_data, dict):
            owner_addr = owner_data.get('AddressOwner', '').lower()
            amount_mist = float(change.get('amount', 0))
            
            if owner_addr and amount_mist < 0:
                amount_sui = amount_mist / 1_000_000_000
                owner_name = validator_map.get(owner_addr, "Unknown")
                
                if target_clean in owner_name.lower():
                    return amount_sui, f"✅ Transfer to {owner_name}"

    # 4. BLIND MODE RETURN
    # If we didn't find "Nansen" specifically, but we found OTHER staking events,
    # return the first one. This ensures you see the numbers even if the name is missing.
    if found_items:
        amt, note = found_items[0]
        return amt, f"⚠️ Blind Mode: {note}"

    return "Not Found", f"No event found for '{target_keyword}'"

# --- UI ---
st.set_page_config(page_title="Sui API Extractor", page_icon="⚡")
st.title("⚡ Sui Stake Transaction Extractor (Unbreakable)")

# 🛠️ MEMORY FIX: Force clear corrupted data
if 'v_map' in st.session_state and st.session_state['v_map'] is None:
    st.session_state['v_map'] = {}

# Auto-Load
if 'v_map' not in st.session_state or not st.session_state['v_map']:
    with st.spinner("Loading Phonebook..."):
        st.session_state['v_map'] = get_validator_map()
    
    count = len(st.session_state['v_map'])
    if count > 5:
        st.success(f"✅ Online: Phonebook loaded ({count} validators).")
    else:
        st.warning(f"⚠️ Offline Mode: Phonebook blocked. App will extract RAW addresses.")

uploaded_file = st.file_uploader("Upload CSV/Excel", type=["csv", "xlsx"])

if uploaded_file:
    if uploaded_file.name.endswith('.csv'):
        df = pd.read_csv(uploaded_file)
    else:
        df = pd.read_excel(uploaded_file)
    
    col1, col2 = st.columns(2)
    with col1:
        cols = df.columns.tolist()
        hash_col = st.selectbox("Transaction Hash Column", cols)
    with col2:
        target_keyword = st.text_input("Search for Validator", value="Nansen")
    
    if st.button("🚀 Run Extraction"):
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        results_amt = []
        results_notes = []
        total_rows = len(df)
        
        # 🛠️ SAFETY: Handle both None and Empty Dict
        v_map = st.session_state.get('v_map') or {}

        for index, row in df.iterrows():
            tx_hash = str(row[hash_col]).strip()
            
            status_text.text(f"Processing {index + 1}/{total_rows}...")
            progress_bar.progress((index + 1) / total_rows)
            
            amount, note = parse_transaction(tx_hash, v_map, target_keyword)
            
            results_amt.append(amount)
            results_notes.append(note)
            
            time.sleep(1.5) # Prevent rate limits
        
        df[f"Amount ({target_keyword})"] = results_amt
        df["Notes"] = results_notes
        
        st.success("✅ Done!")
        st.dataframe(df)
        st.download_button("📥 Download CSV", df.to_csv(index=False).encode('utf-8'), "sui_results.csv", "text/csv")
