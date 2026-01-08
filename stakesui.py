import streamlit as st
import os
import sys
import subprocess
import time
import shutil

# --- 🛠️ SELF-REPAIR BLOCK (Fixes ModuleNotFoundError) ---
# This forces the server to install libraries if requirements.txt failed
def install_libs():
    libs = ["selenium", "webdriver-manager", "beautifulsoup4", "pandas", "openpyxl"]
    for lib in libs:
        try:
            __import__(lib.replace("-", "_")) # basic check
        except ImportError:
            subprocess.check_call([sys.executable, "-m", "pip", "install", lib])

try:
    import selenium
    from selenium import webdriver
except ImportError:
    st.warning("⚙️ First-time setup: Installing missing libraries... (This takes 30s)")
    install_libs()
    st.rerun() # Restart app after install

# --- NORMAL IMPORTS ---
import pandas as pd
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import re

# --- CONFIGURATION & SETUP ---
def get_driver():
    """
    Starts a Chrome browser. 
    Auto-detects if running on Streamlit Cloud (Linux) or Local Machine.
    """
    options = Options()
    options.add_argument("--headless")  # Run in background
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    
    # QA FIX for Streamlit Cloud:
    # We check if 'chromium' is installed at the system level via packages.txt
    chromium_path = shutil.which("chromium")
    chromedriver_path = shutil.which("chromedriver")
    
    # If we are on Streamlit Cloud, use the system chromium
    if chromium_path and chromedriver_path:
        options.binary_location = chromium_path
        service = Service(chromedriver_path)
    else:
        # If we are running locally (Windows/Mac), download driver automatically
        try:
            service = Service(ChromeDriverManager().install())
        except Exception as e:
            return None

    try:
        driver = webdriver.Chrome(service=service, options=options)
        return driver
    except Exception as e:
        return None

def scrape_suiscan(driver, tx_hash, target_keyword):
    url = f"https://suiscan.xyz/mainnet/tx/{tx_hash}"
    try:
        driver.get(url)
    except Exception:
        return {"Transaction Hash": tx_hash, "Status": "Network Error", "Notes": "Could not reach URL"}
    
    col_name = f"Amount to '{target_keyword}'"
    result = {
        "Transaction Hash": tx_hash, 
        col_name: "Not Found",
        "Status": "Processed",
        "Notes": ""
    }

    try:
        # 1. Wait for page to load
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        
        # 2. Try to click "Show more"
        try:
            time.sleep(2.5) # Wait for JS to render
            buttons = driver.find_elements(By.XPATH, "//button[contains(translate(text(), 'SHOW', 'show'), 'show more')]")
            
            # Scroll down just in case
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight/3);")
            
            for btn in buttons:
                if btn.is_displayed():
                    driver.execute_script("arguments[0].click();", btn)
                    time.sleep(1)
                    break
        except Exception:
            pass 

        # 3. Parse content
        soup = BeautifulSoup(driver.page_source, "html.parser")
        page_text = soup.get_text(separator=" ") 
        
        # 4. Search logic using Regex
        safe_keyword = re.escape(target_keyword)
        pattern_str = r"([\-\d\.]+)\s+SUI\s+to\s+" + safe_keyword
        pattern = re.compile(pattern_str, re.IGNORECASE)
        
        match = pattern.search(page_text)
        
        if match:
            extracted_number = match.group(1)
            result[col_name] = extracted_number
            result["Notes"] = "Success"
        else:
            if target_keyword.lower() in page_text.lower():
                result["Notes"] = f"Found '{target_keyword}' but number pattern didn't match."
            else:
                result["Notes"] = f"Keyword '{target_keyword}' not found."

    except Exception as e:
        result["Status"] = "Error"
        result["Notes"] = str(e)
        
    return result

# --- STREAMLIT UI ---
st.set_page_config(page_title="SuiScan Data Extractor", page_icon="🔍")

st.title("🔍 SuiScan Transaction Extractor")

st.subheader("Step 1: Upload Data")
uploaded_file = st.file_uploader("Upload CSV or Excel file", type=["csv", "xlsx"])

if uploaded_file:
    try:
        if uploaded_file.name.endswith('.csv'):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)
    except Exception as e:
        st.error(f"Error reading file: {e}")
        st.stop()
    
    st.subheader("Step 2: Settings")
    col1, col2 = st.columns(2)
    
    with col1:
        cols = df.columns.tolist()
        hash_col = st.selectbox("Column with Transaction Hash", cols, index=0)
        
    with col2:
        target_keyword = st.text_input(
            "Search Keyword", 
            value="Nansen", 
            placeholder="e.g. Nansen, Coinbase"
        )

    st.write("---")
    
    if st.button("🚀 Start Extraction"):
        if not target_keyword:
            st.error("Please enter a keyword.")
        else:
            status_container = st.empty()
            status_container.info("Initializing Browser Engine... (This may take 10-20 seconds)")
            
            driver = get_driver()
            
            if driver:
                status_container.success("Browser Engine Started!")
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                results = []
                total_rows = len(df)
                
                for index, row in df.iterrows():
                    tx_hash = str(row[hash_col]).strip()
                    status_text.text(f"Scanning {index + 1}/{total_rows}: {tx_hash}")
                    progress_bar.progress((index + 1) / total_rows)
                    data = scrape_suiscan(driver, tx_hash, target_keyword)
                    results.append(data)
                    time.sleep(1) 

                driver.quit()
                
                results_df = pd.DataFrame(results)
                final_df = pd.concat([df, results_df.drop(columns=["Transaction Hash"], errors='ignore')], axis=1)
                
                st.success("✅ Extraction Complete!")
                st.dataframe(final_df)
                
                csv = final_df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label=f"📥 Download Results ({target_keyword})",
                    data=csv,
                    file_name=f'suiscan_{target_keyword}_results.csv',
                    mime='text/csv',
                )
            else:
                st.error("⚠️ Error: Browser not found. Did you add 'packages.txt'?")
                st.markdown("**How to fix:** Create a file named `packages.txt` in your repo and add `chromium` inside it.")
