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
    """
    Standard RPC handler with Node Rotation.
    """
    for node in RPC_NODES:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        try:
            response = requests.post(node, json=payload, headers=HEADERS, timeout=15)
            if response.status_code == 200:
                data = response.json()
                if "result" in data:
                    return data["result"]
        except Exception:
            continue 
    return None

def get_validator_map():
    """
    Downloads Phonebook. Returns empty dict if blocked (Offline Mode).
    """
    validator_map = {}
    try:
        result = make_rpc_call("suix_getLatestSuiSystemStateV2", [])
        if result:
            for v in result.get('activeValidators', []):
                validator_map[v['suiAddress'].lower()] = v['name']
    except:
        pass
    return validator_map

def parse_single_block(block_data, validator_map, target_keyword):
    """
    Logic to extract amount from a single transaction block data.
    """
    if not block_data:
        return None, "Network Error (Details missing)"
        
    target_clean = target_keyword.lower()
    found_items = []
    
    # 1. Search EVENTS
    events = block_data.get('events', [])
    for event in events:
        parsed = event.get('parsedJson', {})
        if 'validator_address' in parsed:
            val_addr = parsed.get('validator_address', '').lower()
            amount_mist = float(parsed.get('amount', 0))
            amount_sui = amount_mist / 1_000_000_000
            
            val_name = validator_map.get(val_addr, "Unknown")
            # Detect Nansen manually if phonebook failed
            if "0xa36a" in val_addr:
                val_name = "Nansen (Detected)"

            if target_clean in val_name.lower():
                return -amount_sui, f"✅ Staked to {val_name}"
            
            found_items.append((-amount_sui, f"❓ Staked to {val_name}"))

    # 2. Search BALANCE CHANGES
    for change in block_data.get('balanceChanges', []):
        owner_data = change.get('owner', {})
        if isinstance(owner_data, dict):
            owner_addr = owner_data.get('AddressOwner', '').lower()
            amount_mist = float(change.get('amount', 0))
            
            if owner_addr and amount_mist < 0:
                amount_sui = amount_mist / 1_000_000_000
                owner_name = validator_map.get(owner_addr, "Unknown")
                
                if target_clean in owner_name.lower():
                    return amount_sui, f"✅ Transfer to {owner_name}"

    # 3. Blind Mode Fallback
    if found_items:
        return found_items[0][0], f"⚠️ Blind Mode: {found_items[0][1]}"

    return None, f"No event found for '{target_keyword}'"

def fetch_batch_transactions(hashes):
    """
    TURBO MODE: Fetches multiple transactions in ONE network call.
    Uses 'sui_multiGetTransactionBlocks'.
    """
    # Prepare params: List of Hashes, then Options
    params = [
        hashes, 
        {
            "showEvents": True, 
            "showBalanceChanges": True,
            "showInput": True,
            "showEffects": True
        }
    ]
    
    # This returns a LIST of transaction blocks corresponding to the hashes
    results = make_rpc_call("sui_multiGetTransactionBlocks", params)
    return results

# --- UI ---
st.set_page_config(page_title="Sui API Extractor", page_icon="⚡")
st.title("⚡ Sui Extractor (Turbo Batch Mode)")

# Auto-Load Phonebook
if 'v_map' not in st.session_state:
    st.session_state['v_map'] = get_validator_map()

# Status Indicator
if st.session_state['v_map']:
    st.success(f"✅ Online Mode: Phonebook loaded ({len(st.session_state['v_map'])} validators).")
else:
    st.warning("⚠️ Offline Mode: Phonebook blocked. Using 'Hardcoded Detection' for Nansen.")

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
    
    if st.button("🚀 Run Turbo Extraction"):
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        # Prepare Result Lists
        # We pre-fill them with None so we can assign by index
        results_amt = [None] * len(df)
        results_notes = [None] * len(df)
        
        # BATCH SETTINGS
        BATCH_SIZE = 10 # Process 10 rows at a time
        all_hashes = df[hash_col].astype(str).str.strip().tolist()
        v_map = st.session_state.get('v_map') or {}

        total_batches = (len(all_hashes) + BATCH_SIZE - 1) // BATCH_SIZE
        
        for i in range(0, len(all_hashes), BATCH_SIZE):
            batch_hashes = all_hashes[i : i + BATCH_SIZE]
            current_batch_idx = i // BATCH_SIZE
            
            status_text.text(f"Processing Batch {current_batch_idx + 1}/{total_batches} ({len(batch_hashes)} txs)...")
            progress_bar.progress((i + 1) / len(all_hashes))
            
            # 1. FETCH BATCH
            batch_data = fetch_batch_transactions(batch_hashes)
            
            # 2. PROCESS BATCH
            if batch_data:
                # Map results back to order. 
                # Note: sui_multiGetTransactionBlocks result order usually matches request order, 
                # but we should handle mismatches if possible. 
                # For simplicity here, we assume 1:1 mapping or handle lookup.
                
                # Create a lookup dict for this batch {digest: data}
                batch_lookup = {item['digest']: item for item in batch_data if item and 'digest' in item}
                
                for j, tx_hash in enumerate(batch_hashes):
                    global_index = i + j
                    
                    if tx_hash in batch_lookup:
                        amt, note = parse_single_block(batch_lookup[tx_hash], v_map, target_keyword)
                        results_amt[global_index] = amt
                        results_notes[global_index] = note
                    else:
                        results_amt[global_index] = None
                        results_notes[global_index] = "Network Error (Batch failed for this Item)"
            else:
                # If whole batch failed
                for j in range(len(batch_hashes)):
                    results_notes[i+j] = "Network Error (Whole Batch Failed)"
            
            # Small sleep between batches is better than sleep between every row
            time.sleep(1) 
        
        df[f"Amount ({target_keyword})"] = results_amt
        df["Notes"] = results_notes
        
        st.success("✅ Done!")
        st.dataframe(df)
        st.download_button("📥 Download CSV", df.to_csv(index=False).encode('utf-8'), "sui_results_turbo.csv", "text/csv")
