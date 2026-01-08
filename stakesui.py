import streamlit as st
import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service
from bs4 import BeautifulSoup
import time
import re

# --- CONFIGURATION & SETUP ---
def get_driver():
    """Starts a headless Chrome browser."""
    options = Options()
    options.add_argument("--headless")  # Run in background
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    
    # Auto-install and setup Chrome driver
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    return driver

def scrape_suiscan(driver, tx_hash, target_keyword):
    """
    Visits the Suiscan page, clicks 'Show more', and finds the number associated with the keyword.
    """
    url = f"https://suiscan.xyz/mainnet/tx/{tx_hash}"
    driver.get(url)
    
    result = {
        "Transaction Hash": tx_hash, 
        f"Amount sent to '{target_keyword}'": "Not Found", # Dynamic column name
        "Status": "Processed",
        "Notes": ""
    }

    try:
        # 1. Wait for page to load
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        
        # 2. Try to click "Show more" to reveal all details
        try:
            time.sleep(2) # Brief wait for scripts
            buttons = driver.find_elements(By.TAG_NAME, "button")
            clicked = False
            for btn in buttons:
                if "Show more" in btn.text or "Show More" in btn.text:
                    driver.execute_script("arguments[0].click();", btn)
                    time.sleep(1) # Wait for expansion
                    clicked = True
                    break
            if not clicked:
                result["Notes"] = "No 'Show more' button found (might be visible already)."
        except Exception:
            pass # Continue even if click fails

        # 3. Parse content
        soup = BeautifulSoup(driver.page_source, "html.parser")
        page_text = soup.get_text(separator=" | ")
        
        # 4. Search logic using Regex
        # Pattern: [Number] SUI to [Keyword]
        # Example: "-124.07 SUI to Nansen"
        # We capture the number group ([\-\d\.]+)
        pattern = re.compile(r"([\-\d\.]+)\s*SUI\s+to\s+" + re.escape(target_keyword), re.IGNORECASE)
        
        match = pattern.search(page_text)
        
        if match:
            extracted_number = match.group(1)
            result[f"Amount sent to '{target_keyword}'"] = extracted_number
            result["Notes"] = "Success"
        else:
            result["Notes"] = f"Keyword '{target_keyword}' not found in transaction details."

    except Exception as e:
        result["Status"] = "Error"
        result["Notes"] = str(e)
        
    return result

# --- STREAMLIT UI ---
st.set_page_config(page_title="SuiScan Data Extractor", page_icon="🔍")

st.title("🔍 SuiScan Transaction Extractor")
st.markdown("Upload your hashes, define who you are looking for, and get the data.")

# 1. File Uploader
st.subheader("Step 1: Upload Data")
uploaded_file = st.file_uploader("Upload CSV or Excel file", type=["csv", "xlsx"])

if uploaded_file:
    # Load file
    if uploaded_file.name.endswith('.csv'):
        df = pd.read_csv(uploaded_file)
    else:
        df = pd.read_excel(uploaded_file)
    
    # 2. Column Selection
    st.subheader("Step 2: Settings")
    col1, col2 = st.columns(2)
    
    with col1:
        cols = df.columns.tolist()
        hash_col = st.selectbox("Which column has the Hash?", cols, index=0)
        
    with col2:
        # --- CUSTOM SEARCH BOX ---
        target_keyword = st.text_input(
            "Who are we searching for?", 
            value="Nansen", 
            placeholder="e.g. Nansen, Coinbase, Binance",
            help="The app will look for this word and grab the number next to it."
        )

    st.write("---")
    
    # 3. Execution
    if st.button("🚀 Start Extraction"):
        if not target_keyword:
            st.error("Please enter a keyword to search for.")
        else:
            st.info(f"Starting Chrome... Searching for transactions involving **{target_keyword}**.")
            
            try:
                driver = get_driver()
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                results = []
                total_rows = len(df)
                
                for index, row in df.iterrows():
                    tx_hash = str(row[hash_col]).strip()
                    
                    status_text.text(f"Scanning {index + 1}/{total_rows}: {tx_hash}...")
                    progress_bar.progress((index + 1) / total_rows)
                    
                    data = scrape_suiscan(driver, tx_hash, target_keyword)
                    results.append(data)
                    
                    time.sleep(1) # Be polite to the server

                driver.quit()
                
                # Show results
                results_df = pd.DataFrame(results)
                final_df = pd.concat([df, results_df.drop(["Transaction Hash"], axis=1)], axis=1)
                
                st.success("✅ Done!")
                st.dataframe(final_df)
                
                # Download
                csv = final_df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label=f"📥 Download Data (Filtered for {target_keyword})",
                    data=csv,
                    file_name=f'suiscan_{target_keyword}_results.csv',
                    mime='text/csv',
                )
                
            except Exception as e:
                st.error(f"Error: {e}")
                st.warning("Ensure Chrome is installed and you are running this locally.")
