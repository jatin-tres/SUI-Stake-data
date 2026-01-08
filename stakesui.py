import streamlit as st
import pandas as pd
import requests
import time

# --- CONFIGURATION: MULTI-NODE & STEALTH ---
# 1. We use a Fake User-Agent to bypass simple blocks
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Content-Type": "application/json"
}

# 2. List of Public RPC Nodes (We try all of them)
RPC_NODES = [
    "https://sui-rpc.publicnode.com",
    "https://fullnode.mainnet.sui.io:443",
    "https://sui-mainnet.nodeinfra.com:443",
    "https://mainnet.sui.rpcpool.com:443",
    "https://sui-mainnet-endpoint.blockvision.org",
    "https://rpc.mainnet.sui.io:443",
    "https://sui-mainnet.public.blastapi.io"
]

def make_rpc_call(method, params):
    """
    Tries every node in the list with a fake header.
    """
    for node in RPC_NODES:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        try:
            response = requests.post(node, json=payload, headers=HEADERS, timeout=5)
            if response.status_code == 200:
                data = response.json()
                if "result" in data:
                    return data["result"]
        except Exception:
            continue # Try next node
    return None

def get_validator_map():
    """
    Attempts to download the 'Phonebook' (Address -> Name).
    If this fails (due to blocking), we return None and run in 'Blind Mode'.
    """
    result = make_rpc_call("suix_getLatestSuiSystemStateV2", [])
    if not result:
        return None 
    
    validator_map = {}
    for v in result.get('activeValidators', []):
        validator_map[v['suiAddress'].lower()] = v['name']
    return validator_map

def parse_transaction(tx_hash, validator_map, target_keyword):
    """
    Extracts staking info. Works even if validator_map is missing.
    """
    tx_data = make_rpc_call(
        "sui_getTransactionBlock", 
        [tx_hash, {"showEvents": True, "showBalanceChanges": True}]
    )
    
    if not tx_data:
        return "Network Error", "Could not fetch TX details (All nodes blocked)"

    # SEARCH STRATEGY
    target_clean = target_keyword.lower()
    found_info = []

    # 1. Check Events (RequestAddStake)
    events = tx_data.get('events', [])
    for event in events:
        if "RequestAddStake" in event.get('type', ''):
            parsed = event.get('parsedJson', {})
            val_addr = parsed.get('validator_address', '').lower()
            amount_mist = float(parsed.get('amount', 0))
            amount_sui = amount_mist / 1_000_000_000
            
            # Resolve Name
            if validator_map:
                val_name = validator_map.get(val_addr, "Unknown")
                # Precise Filter
                if target_clean in val_name.lower():
                    return -amount_sui, f"✅ Staked to {val_name}"
            else:
                # Blind Mode: We don't know the name, so we return the Address
                # User has to verify if this address is Nansen
                found_info.append(f"Staked {-amount_sui} SUI to {val_addr[:6]}...")

    # 2. Check Balance Changes (Transfers)
    if not found_info:
        for change in tx_data.get('balanceChanges', []):
            owner_data = change.get('owner', {})
            if isinstance(owner_data, dict):
                owner_addr = owner_data.get('AddressOwner', '').lower()
                amount_mist = float(change.get('amount', 0))
                
                if owner_addr and amount_mist < 0:
                    amount_sui = amount_mist / 1_000_000_000
                    
                    if validator_map:
                        owner_name = validator_map.get(owner_addr, "")
                        if target_clean in owner_name.lower():
                             return amount_sui, f"✅ Transfer to {owner_name}"
                    else:
                         # Blind Mode
                         found_info.append(f"Sent {amount_sui} SUI to {owner_addr[:6]}...")

    # Final Decision
    if found_info:
        # If we are in Blind Mode, return the first likely candidate
        return "Check Notes", f"⚠️ Blind Mode (Map Failed). Found: {', '.join(found_info)}"
        
    return "Not Found", f"No matching event found for '{target_keyword}'"

# --- UI ---
st.set_page_config(page_title="Sui API Extractor", page_icon="⚡")
st.title("⚡ Sui Transaction Extractor (Fail-Safe)")

# 1. Auto-Load Phonebook (With specific error handling)
if 'v_map' not in st.session_state:
    with st.spinner("Connecting to Sui Network..."):
        st.session_state['v_map'] = get_validator_map()
        
    if st.session_state['v_map']:
        st.success(f"✅ Online: Loaded {len(st.session_state['v_map'])} validators.")
    else:
        st.warning("⚠️ Offline Mode: Could not download Validator Names (Blocked). App will extract Addresses instead.")

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
        
        for index, row in df.iterrows():
            tx_hash = str(row[hash_col]).strip()
            
            status_text.text(f"Processing {index + 1}/{total_rows}...")
            progress_bar.progress((index + 1) / total_rows)
            
            amount, note = parse_transaction(
                tx_hash, 
                st.session_state.get('v_map'), 
                target_keyword
            )
            
            results_amt.append(amount)
            results_notes.append(note)
            time.sleep(0.2) # Rate limit protection
        
        df[f"Amount ({target_keyword})"] = results_amt
        df["Notes"] = results_notes
        
        st.success("✅ Done!")
        st.dataframe(df)
        st.download_button("📥 Download CSV", df.to_csv(index=False).encode('utf-8'), "sui_results.csv", "text/csv")
