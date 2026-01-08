import streamlit as st
import pandas as pd
import requests
import time
import random

# --- CONFIGURATION: MULTI-NODE REDUNDANCY ---
# We use a list of public nodes. If one fails, we switch to the next.
RPC_NODES = [
    "https://fullnode.mainnet.sui.io:443",
    "https://sui-mainnet.nodeinfra.com:443",
    "https://mainnet.sui.rpcpool.com:443",
    "https://sui-mainnet-endpoint.blockvision.org",
    "https://sui-rpc.publicnode.com"
]

def make_rpc_request(method, params):
    """
    Tries to send the request to each node in the list until one works.
    """
    for url in RPC_NODES:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params
        }
        try:
            response = requests.post(url, json=payload, timeout=10)
            data = response.json()
            
            # If the node sent an error message back, skip to next node
            if "error" in data:
                continue 
                
            # If successful, return data
            if "result" in data:
                return data["result"]
                
        except Exception:
            continue # Try next node on connection failure
            
    return None # All nodes failed

def get_validator_map():
    """
    Fetches the list of active validators to map Addresses <-> Names.
    """
    result = make_rpc_request("suix_getLatestSuiSystemStateV2", [])
    
    if not result:
        st.error("❌ All RPC nodes are busy. Please wait 1 minute and try again.")
        return {}
        
    active_validators = result.get('activeValidators', [])
    
    validator_map = {}
    for v in active_validators:
        name = v['name']
        address = v['suiAddress']
        validator_map[address] = name
        validator_map[name] = address 
        
    return validator_map

def get_transaction_details(tx_hash, validator_map, target_keyword):
    """
    Fetches tx details and parses events for the keyword.
    """
    result = make_rpc_request(
        "sui_getTransactionBlock", 
        [
            tx_hash,
            {
                "showInput": True,
                "showEffects": True,
                "showEvents": True,
                "showBalanceChanges": True
            }
        ]
    )
    
    if not result:
        return "Network Error", "Could not fetch TX details"

    # 1. Search in EVENTS (Standard Staking)
    events = result.get('events', [])
    for event in events:
        if "RequestAddStake" in event.get('type', ''):
            parsed_json = event.get('parsedJson', {})
            validator_address = parsed_json.get('validator_address')
            amount_mist = parsed_json.get('amount')
            
            # Lookup Name
            val_name = validator_map.get(validator_address, "Unknown Validator")
            
            # Check Match
            if target_keyword.lower() in val_name.lower():
                amount_sui = float(amount_mist) / 1_000_000_000
                return -amount_sui, f"Success: Staked to {val_name}"

    # 2. Search Balance Changes (Direct Transfers)
    balance_changes = result.get('balanceChanges', [])
    for change in balance_changes:
        owner_data = change.get('owner', {})
        
        # Handle different owner formats
        owner_address = None
        if isinstance(owner_data, dict):
            owner_address = owner_data.get('AddressOwner')
            
        if owner_address:
            owner_name = validator_map.get(owner_address, "")
            
            if target_keyword.lower() in owner_name.lower():
                amount_mist = int(change.get('amount', 0))
                if amount_mist < 0:
                    amount_sui = float(amount_mist) / 1_000_000_000
                    return amount_sui, f"Success: Transfer to {owner_name}"

    return "Not Found", f"No transaction found involving '{target_keyword}'"

# --- UI ---
st.set_page_config(page_title="Sui API Extractor", page_icon="⚡")
st.title("⚡ Sui Transaction Extractor (Multi-Node)")

if 'validator_map' not in st.session_state:
    with st.spinner("Connecting to Blockchain (Trying 5 different nodes)..."):
        data = get_validator_map()
        if data:
            st.session_state['validator_map'] = data
            st.success(f"✅ Connected! Indexed {len(data)//2} validators.")

uploaded_file = st.file_uploader("Upload CSV/Excel", type=["csv", "xlsx"])

if uploaded_file and 'validator_map' in st.session_state:
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
            status_text.text(f"Querying {index + 1}/{total_rows}: {tx_hash[:10]}...")
            progress_bar.progress((index + 1) / total_rows)
            
            amount, note = get_transaction_details(
                tx_hash, 
                st.session_state['validator_map'], 
                target_keyword
            )
            
            results_amt.append(amount)
            results_notes.append(note)
            time.sleep(0.1)
        
        df[f"Amount to '{target_keyword}'"] = results_amt
        df["Notes"] = results_notes
        
        st.success("✅ Done!")
        st.dataframe(df)
        
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Download Results", csv, "sui_api_results.csv", "text/csv")
