import streamlit as st
import pandas as pd
import requests
import time

# --- CONFIGURATION ---
SUI_RPC_URL = "https://fullnode.mainnet.sui.io:443"

# --- HELPER FUNCTIONS ---

def get_validator_map():
    """
    Asks Sui Blockchain for the list of all active validators.
    Returns a dictionary: {'0xAddress': 'Validator Name'}
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "suix_getLatestSuiSystemStateV2",
        "params": []
    }
    
    try:
        response = requests.post(SUI_RPC_URL, json=payload).json()
        active_validators = response['result']['activeValidators']
        
        validator_map = {}
        for v in active_validators:
            # Map the unique SUI Address to the Name (e.g. "Nansen")
            name = v['name']
            address = v['suiAddress']
            validator_map[address] = name
            validator_map[name] = address # Reverse lookup too
            
        return validator_map
    except Exception as e:
        st.error(f"Failed to fetch validator list: {e}")
        return {}

def get_transaction_details(tx_hash, validator_map, target_keyword):
    """
    Fetches tx details and looks for staking events involving the keyword.
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "sui_getTransactionBlock",
        "params": [
            tx_hash,
            {
                "showInput": True,
                "showEffects": True,
                "showEvents": True,
                "showBalanceChanges": True
            }
        ]
    }
    
    try:
        response = requests.post(SUI_RPC_URL, json=payload).json()
        
        if "error" in response:
            return "Invalid Hash", f"RPC Error: {response['error']['message']}"
            
        result = response.get('result', {})
        events = result.get('events', [])
        
        # 1. Search in EVENTS (The most accurate for Staking)
        # We look for "RequestAddStake" events
        for event in events:
            # Check if this is a staking event
            if "RequestAddStake" in event.get('type', ''):
                parsed_json = event.get('parsedJson', {})
                validator_address = parsed_json.get('validator_address')
                amount_mist = parsed_json.get('amount')
                
                # Identify the name of this validator
                val_name = validator_map.get(validator_address, "Unknown Validator")
                
                # CHECK: Does the name contain our keyword? (e.g. "Nansen")
                if target_keyword.lower() in val_name.lower():
                    # Convert MIST to SUI (1 SUI = 1,000,000,000 MIST)
                    amount_sui = float(amount_mist) / 1_000_000_000
                    return -amount_sui, f"Success: Staked to {val_name}"

        # 2. Fallback: Search in Balance Changes (If not a standard stake event)
        # Sometimes it's just a transfer to an address owned by 'Nansen'
        balance_changes = result.get('balanceChanges', [])
        for change in balance_changes:
            owner = change.get('owner', {}).get('AddressOwner')
            if owner:
                # Check if this owner address belongs to our target name
                owner_name = validator_map.get(owner, "")
                
                if target_keyword.lower() in owner_name.lower():
                    amount_mist = int(change.get('amount', 0))
                    # Only look for negative amounts (sending money out)
                    if amount_mist < 0:
                        amount_sui = float(amount_mist) / 1_000_000_000
                        return amount_sui, f"Success: Transfer to {owner_name}"

        return "Not Found", f"No transaction found involving '{target_keyword}'"

    except Exception as e:
        return "Error", str(e)

# --- STREAMLIT UI ---
st.set_page_config(page_title="Sui API Extractor", page_icon="⚡")

st.title("⚡ Sui Transaction Extractor (Direct API)")
st.markdown("""
**Method:** Direct Blockchain RPC (Bypasses Suiscan website completely).
**Status:** ✅ Immune to 'Show More' buttons and Anti-Bot blocking.
""")

# 1. Load Validators on Start
if 'validator_map' not in st.session_state:
    with st.spinner("Connecting to Sui Mainnet & downloading Validator list..."):
        st.session_state['validator_map'] = get_validator_map()
    st.success(f"Connected! Database contains {len(st.session_state['validator_map'])} validators.")

# 2. Upload
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
        target_keyword = st.text_input("Search for Validator (Name)", value="Nansen")
    
    if st.button("🚀 Run Extraction"):
        if not target_keyword:
            st.error("Please enter a keyword.")
        else:
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            results_amt = []
            results_notes = []
            total_rows = len(df)
            
            for index, row in df.iterrows():
                tx_hash = str(row[hash_col]).strip()
                status_text.text(f"Querying Blockchain {index + 1}/{total_rows}: {tx_hash[:10]}...")
                progress_bar.progress((index + 1) / total_rows)
                
                # HIT THE API
                amount, note = get_transaction_details(
                    tx_hash, 
                    st.session_state['validator_map'], 
                    target_keyword
                )
                
                results_amt.append(amount)
                results_notes.append(note)
                
                # Tiny pause to be nice to public RPC
                time.sleep(0.1)
            
            # Attach results
            df[f"Amount to '{target_keyword}'"] = results_amt
            df["Notes"] = results_notes
            
            st.success("✅ Done!")
            st.dataframe(df)
            
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download Results",
                data=csv,
                file_name="sui_api_results.csv",
                mime="text/csv"
            )
