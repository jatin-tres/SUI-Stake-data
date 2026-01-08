import streamlit as st
import pandas as pd
import requests
import time
import random

# --- CONFIGURATION: SERVER ROTATION ---
# We iterate through these nodes. If one fails, we hit the next one.
RPC_NODES = [
    "https://sui-rpc.publicnode.com",
    "https://fullnode.mainnet.sui.io:443",
    "https://sui-mainnet.nodeinfra.com:443",
    "https://mainnet.sui.rpcpool.com:443",
    "https://sui-mainnet-endpoint.blockvision.org",
    "https://rpc.mainnet.sui.io:443"
]

def robust_rpc_call(method, params):
    """
    Tries every node in the list. Retries infinitely until success or total exhaustion.
    """
    max_retries = 3
    for attempt in range(max_retries):
        for node in RPC_NODES:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": method,
                "params": params
            }
            try:
                # 5 second timeout to prevent hanging
                response = requests.post(node, json=payload, timeout=5)
                
                if response.status_code == 200:
                    data = response.json()
                    if "result" in data:
                        return data["result"]
                    elif "error" in data:
                        # If node explicitly errors (e.g. invalid hash), stop trying this hash
                        if "not found" in str(data['error']).lower():
                            return None
            except Exception:
                continue # Silently try the next node
            
        # If all nodes failed, wait a bit and try the loop again
        time.sleep(2)
    
    return None # Gave up after trying all nodes 3 times

def get_validator_map():
    """
    Forces the download of the validator list.
    """
    st.write("🔄 Downloading Validator 'Phonebook' from Blockchain...")
    
    result = robust_rpc_call("suix_getLatestSuiSystemStateV2", [])
    
    if not result:
        return {}
        
    active_validators = result.get('activeValidators', [])
    
    validator_map = {}
    for v in active_validators:
        name = v['name']
        address = v['suiAddress']
        # Normalize to lower case for easier matching
        validator_map[address.lower()] = name
        validator_map[name.lower()] = address 
        
    return validator_map

def parse_transaction(tx_hash, validator_map, target_keyword):
    """
    Decodes the transaction and looks for 'RequestAddStake' events.
    """
    result = robust_rpc_call(
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
        return "Network Error", "Could not fetch data after multiple retries."

    target_clean = target_keyword.lower()
    
    # 1. Check Events (The most reliable source for Staking)
    events = result.get('events', [])
    for event in events:
        if "RequestAddStake" in event.get('type', ''):
            parsed = event.get('parsedJson', {})
            val_addr = parsed.get('validator_address', '').lower()
            amount_mist = float(parsed.get('amount', 0))
            
            # Find Name
            val_name = validator_map.get(val_addr, f"Unknown ({val_addr[:6]}...)")
            
            # Check Match
            if target_clean in val_name.lower():
                amount_sui = amount_mist / 1_000_000_000
                return -amount_sui, f"✅ Success: Staked to {val_name}"
            else:
                # Debugging: If we found a stake but it wasn't Nansen, tell the user who it was
                return None, f"⚠️ Found stake to '{val_name}', not '{target_keyword}'"

    # 2. Check Balance Changes (Transfers)
    balance_changes = result.get('balanceChanges', [])
    for change in balance_changes:
        owner_data = change.get('owner', {})
        if isinstance(owner_data, dict):
            owner_addr = owner_data.get('AddressOwner', '').lower()
            if owner_addr:
                owner_name = validator_map.get(owner_addr, f"Unknown ({owner_addr[:6]}...)")
                
                if target_clean in owner_name.lower():
                    amount_mist = float(change.get('amount', 0))
                    if amount_mist < 0:
                        return (amount_mist / 1_000_000_000), f"✅ Success: Transfer to {owner_name}"

    return "Not Found", f"No event found linking to '{target_keyword}'"

# --- UI ---
st.set_page_config(page_title="Sui API Extractor", page_icon="⚡")
st.title("⚡ Sui Transaction Extractor (Bulldozer)")

# 1. AUTO-START VALIDATOR FETCH
if 'validator_map' not in st.session_state or len(st.session_state['validator_map']) == 0:
    with st.spinner("Connecting to Sui Network..."):
        v_map = get_validator_map()
        if len(v_map) > 0:
            st.session_state['validator_map'] = v_map
            st.success(f"✅ Connected! Phonebook loaded with {len(v_map)//2} validators.")
        else:
            st.error("❌ Could not download Validator List. Please refresh the page to try again.")
            st.stop() # BLOCK EXECUTION until map is loaded

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
                st.session_state['validator_map'], 
                target_keyword
            )
            
            # Clean up output
            if amount is None: 
                amount = "0"
            
            results_amt.append(amount)
            results_notes.append(note)
            
            # Small breath to avoid rate limits
            time.sleep(0.2)
        
        # Add columns
        df[f"Amount ({target_keyword})"] = results_amt
        df["Notes"] = results_notes
        
        st.success("✅ Extraction Complete!")
        st.dataframe(df)
        
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Download Results", csv, "sui_results.csv", "text/csv")
