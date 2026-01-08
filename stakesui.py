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
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    
    # Check for Streamlit Cloud Configuration
    chromium_path = shutil.which("chromium")
    chromedriver_path = shutil.which("chromedriver")
    
    if chromium_path and chromedriver_path:
        options.binary_location = chromium_path
        service = Service(chromedriver_path)
    else:
        try:
            service = Service(ChromeDriverManager().install())
        except Exception as e:
            st.error(f"Local driver error: {e}")
            return None

    try:
        driver = webdriver.Chrome(service=service, options=options)
        return driver
    except Exception as e:
        return None

def scrape_suiscan(driver, tx_hash, target_keyword):
    """
    Robust scraping logic:
    1. Visits page.
    2. Clicks 'Show More'.
    3. Finds Keyword.
    4. Looks 'backwards' from the keyword to find the associated SUI amount.
    """
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
        # 1. Wait for page
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        
        # 2. Click "Show more" (Aggressive search for the button)
        try:
            time.sleep(3) # Give extra time for the button to appear
            buttons = driver.find_elements(By.TAG_NAME, "button")
            for btn in buttons:
                # Check for "Show" text (case insensitive) or specific classes if needed
                if "show" in btn.text.lower() and "more" in btn.text.lower():
                    if btn.is_displayed():
                        driver.execute_script("arguments[0].click();", btn)
                        time.sleep(1)
                        break
        except Exception:
            pass # Continue even if button fails, data might be visible

        # 3. Parse Content
        soup = BeautifulSoup(driver.page_source, "html.parser")
        # specific separator helps distinguish separate elements
        page_text = soup.get_text(separator="  ") 
        
        # 4. Smart Proximity Search
        # Instead of a fixed regex, we find the keyword and look at the text immediately BEFORE it.
        
        # Find all start indices of the keyword
        keyword_matches = [m.start() for m in re.finditer(re.escape(target_keyword), page_text, re.IGNORECASE)]
        
        if not keyword_matches:
            result["Notes"] = f"Keyword '{target_keyword}' not found on page."
        else:
            found_amount = False
            for match_index in keyword_matches:
                # Grab the 100 characters leading up to the keyword
                start_slice = max(0, match_index - 100)
                text_chunk = page_text[start_slice:match_index]
                
                # Look for a number pattern near "SUI" inside this chunk
                # Pattern: Number -> (optional space) -> SUI -> (optional junk) -> Keyword (implied at end)
                # Regex logic: 
                # ([\-\d\.,]+)  : Capture number (supports commas and negatives)
                # \s* : Optional space
                # SUI           : The unit
                amount_pattern = re.compile(r"([\-\d\.,]+)\s*SUI", re.IGNORECASE)
                
                # Search from the end of the chunk (closest to the keyword)
                matches_in_chunk = list(amount_pattern.finditer(text_chunk))
                
                if matches_in_chunk:
                    # Take the last match in the chunk, as it is closest to our keyword
                    best_match = matches_in_chunk[-1]
                    extracted_number = best_match.group(1)
                    
                    result[col_name] = extracted_number
                    result["Notes"] = "Success"
                    found_amount = True
                    break # Stop after finding the first valid match
            
            if not found_amount:
                # Debug info: Show user what text was actually near the keyword
                snippet = page_text[max(0, keyword_matches[0]-50) : keyword_matches[0]]
                result["Notes"] = f"Found '{target_keyword}' but couldn't find amount. Text near it: '...{snippet}...'"

    except Exception as e:
        result["Status"] = "Error"
        result["Notes"] = str(e)
        
    return result

# --- STREAMLIT UI ---
st.set_page_config(page_title="SuiScan Data Extractor", page_icon="🔍")

st.title("🔍 SuiScan Transaction Extractor")
st.markdown("Updated with **Smart Proximity Search** to find numbers even with hidden icons or formatting.")

# 1. File Uploader
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
            placeholder="e.g. Nansen, Coinbase"
        )

    st.write("---")
    
    if st.button("🚀 Start Extraction"):
        if not target_keyword:
            st.error("Please enter a keyword.")
        else:
            status_container = st.empty()
            status_container.info("Initializing Browser Engine...")
            
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
                
                # Show results
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
                st.error("⚠️ Browser Error: Could not start Chrome. Check logs.")
