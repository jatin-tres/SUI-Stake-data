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
    # 1. Initialize with empty dict (Safety)
    validator_map = {}
    
    # 2. Live Download
    result = make_rpc_call("suix_getLatestSuiSystemStateV2", [])
    if result:
        for v in result.get('activeValidators', []):
            # Map both Address -> Name AND Name -> Address
            validator_map[v['suiAddress'].lower()] = v['name']
            
    return validator_map

def parse_transaction(tx_hash, validator_map, target_keyword):
    # SAFETY FIX: If map is None, treat as empty dict to prevent crash
    if validator_map is None:
        validator_map = {}

    tx_data = make_rpc_call(
        "sui_getTransactionBlock", 
        [tx_hash, {"showEvents": True, "showBalanceChanges": True}]
    )
    
    if not tx_data:
        return "Network Error", "Server blocked request (Try running locally)"

    target_clean = target_keyword.lower()
    
    # 1. Search EVENTS
    events = tx_data.get('events', [])
    for event in events:
        parsed = event.get('parsedJson', {})
        if 'validator_address' in parsed:
            val_addr = parsed.get('validator_address', '').lower()
            amount_mist = float(parsed.get('amount', 0))
            
            # Lookup Name
            val_name = validator_map.get(val_addr, f"Unknown ({val_addr[:6]}...)")
            
            if target_clean in val_name.lower():
                amount_sui = amount_mist / 1_000_000_000
                return -amount_sui, f"✅ Staked to {val_name}"

    # 2. Search Balance Changes
    for change in tx_data.get('balanceChanges', []):
        owner_data = change.get('owner', {})
        if isinstance(owner_data, dict):
            owner_addr = owner_data.get('AddressOwner', '').lower()
            if owner_addr:
                owner_name = validator_map.get(owner_addr, f"Unknown ({owner_addr[:6]}...)")
                
                if target_clean in owner_name.lower():
                    amount_mist = float(change.get('amount', 0))
                    if amount_mist < 0:
                        return (amount_mist / 1_000_000_000), f"✅ Transfer to {owner_name}"

    return "Not Found", f"No event found linking to '{target_keyword}'"

# --- UI ---
st.set_page_config(page_title="Sui API Extractor", page_icon="⚡")
st.title("⚡ Sui Transaction Extractor (Final)")

# --- 🛠️ MEMORY FIX: Force clear stale data ---
if 'v_map' in st.session_state and st.session_state['v_map'] is None:
    del st.session_state['v_map']

# Auto-Load
if 'v_map' not in st.session_state:
    with st.spinner("Loading Phonebook..."):
        st.session_state['v_map'] = get_validator_map()
    
    if len(st.session_state['v_map']) > 0:
        st.success(f"✅ Connected! Phonebook ready ({len(st.session_state['v_map'])} validators).")
    else:
        st.warning("⚠️ Connected, but Phonebook is empty. (Network might be busy).")

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
        
        # Ensure we have a valid map (even if empty)
        v_map = st.session_state.get('v_map') or {}

        for index, row in df.iterrows():
            tx_hash = str(row[hash_col]).strip()
            
            status_text.text(f"Processing {index + 1}/{total_rows}...")
            progress_bar.progress((index + 1) / total_rows)
            
            amount, note = parse_transaction(tx_hash, v_map, target_keyword)
            
            results_amt.append(amount)
            results_notes.append(note)
            
            # 2 second pause to prevent "Network Error"
            time.sleep(2) 
        
        df[f"Amount ({target_keyword})"] = results_amt
        df["Notes"] = results_notes
        
        st.success("✅ Done!")
        st.dataframe(df)
        st.download_button("📥 Download CSV", df.to_csv(index=False).encode('utf-8'), "sui_results.csv", "text/csv")
