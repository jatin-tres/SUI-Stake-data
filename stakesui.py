import streamlit as st
import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import time
import re
import shutil

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
    
    # QA FIX: Streamlit Cloud requires explicit binary locations
    # We check if 'chromium' is installed at the system level (common in Streamlit Cloud)
    chromium_path = shutil.which("chromium")
    chromedriver_path = shutil.which("chromedriver")
    
    if chromium_path and chromedriver_path:
        # We are likely on Streamlit Cloud or Linux with system packages
        options.binary_location = chromium_path
        service = Service(chromedriver_path)
    else:
        # We are likely on a Local Windows/Mac machine
        # webdriver_manager handles the download automatically
        try:
            service = Service(ChromeDriverManager().install())
        except Exception as e:
            st.error(f"Error setting up local Chrome driver: {e}")
            return None

    try:
        driver = webdriver.Chrome(service=service, options=options)
        return driver
    except Exception as e:
        st.error(f"Failed to launch Chrome: {e}")
        return None

def scrape_suiscan(driver, tx_hash, target_keyword):
    """
    Visits the Suiscan page, clicks 'Show more', and finds the number associated with the keyword.
    """
    url = f"https://suiscan.xyz/mainnet/tx/{tx_hash}"
    try:
        driver.get(url)
    except Exception:
        return {"Transaction Hash": tx_hash, "Status": "Network Error", "Notes": "Could not reach URL"}
    
    # Dynamic column name based on keyword
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
            time.sleep(2.5) # Wait for JS to render buttons
            # Find buttons that contain "Show" (case insensitive)
            buttons = driver.find_elements(By.XPATH, "//button[contains(translate(text(), 'SHOW', 'show'), 'show more')]")
            
            if not buttons:
                # Fallback: sometimes it's just a div or span with text
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
                time.sleep(0.5)
            
            for btn in buttons:
                if btn.is_displayed():
                    driver.execute_script("arguments[0].click();", btn)
                    time.sleep(1) # Wait for expansion
                    break
        except Exception:
            # It's okay if we fail to click, the text might already be there
            pass 

        # 3. Parse content
        # We use space separator to prevent text merging across tags
        soup = BeautifulSoup(driver.page_source, "html.parser")
        page_text = soup.get_text(separator=" ") 
        
        # 4. Search logic using Regex
        # We clean extra spaces in regex to be safe
        # Pattern looks for: Number ... SUI ... to ... Keyword
        safe_keyword = re.escape(target_keyword)
        
        # Regex Explanation:
        # ([\-\d\.]+)   -> Capture the number (e.g. -124.07)
        # \s+           -> One or more spaces
        # SUI           -> The unit
        # .*?           -> Any characters (non-greedy) in between (handles 'to', arrows, etc)
        # {keyword}     -> The target name
        pattern_str = r"([\-\d\.]+)\s+SUI\s+to\s+" + safe_keyword
        pattern = re.compile(pattern_str, re.IGNORECASE)
        
        match = pattern.search(page_text)
        
        if match:
            extracted_number = match.group(1)
            result[col_name] = extracted_number
            result["Notes"] = "Success"
        else:
            # Fallback search: Just check if keyword exists at all
            if target_keyword.lower() in page_text.lower():
                result["Notes"] = f"Found '{target_keyword}' but could not parse exact amount pattern."
            else:
                result["Notes"] = f"Keyword '{target_keyword}' not found on page."

    except Exception as e:
        result["Status"] = "Error"
        result["Notes"] = str(e)
        
    return result

# --- STREAMLIT UI ---
st.set_page_config(page_title="SuiScan Data Extractor", page_icon="🔍")

st.title("🔍 SuiScan Transaction Extractor")
st.markdown("This tool uses a headless browser to scrape transaction details from Suiscan.")

# 1. File Uploader
st.subheader("Step 1: Upload Data")
uploaded_file = st.file_uploader("Upload CSV or Excel file", type=["csv", "xlsx"])

if uploaded_file:
    # Load file
    try:
        if uploaded_file.name.endswith('.csv'):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)
    except Exception as e:
        st.error(f"Error reading file: {e}")
        st.stop()
    
    # 2. Settings
    st.subheader("Step 2: Settings")
    col1, col2 = st.columns(2)
    
    with col1:
        cols = df.columns.tolist()
        hash_col = st.selectbox("Column with Transaction Hash", cols, index=0)
        
    with col2:
        target_keyword = st.text_input(
            "Search Keyword", 
            value="Nansen", 
            placeholder="e.g. Nansen, Coinbase",
            help="The app searches for 'Amount SUI to [Keyword]'"
        )

    st.write("---")
    
    # 3. Execution
    if st.button("🚀 Start Extraction"):
        if not target_keyword:
            st.error("Please enter a keyword.")
        else:
            st.info("Initializing Browser Engine...")
            
            driver = get_driver()
            
            if driver:
                st.success("Browser Engine Started!")
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
                    
                    # Be polite to the server
                    time.sleep(1) 

                driver.quit()
                
                # Show results
                results_df = pd.DataFrame(results)
                # Merge logic: Drop duplicate 'Transaction Hash' if it exists in results_df
                final_df = pd.concat([df, results_df.drop(columns=["Transaction Hash"], errors='ignore')], axis=1)
                
                st.success("✅ Extraction Complete!")
                st.dataframe(final_df)
                
                # Download
                csv = final_df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label=f"📥 Download Results ({target_keyword})",
                    data=csv,
                    file_name=f'suiscan_{target_keyword}_results.csv',
                    mime='text/csv',
                )
            else:
                st.error("Could not initialize the browser driver. Please check logs.")
