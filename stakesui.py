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

# --- CONFIGURATION ---
def get_driver():
    """Starts a headless Chrome browser."""
    options = Options()
    options.add_argument("--headless")  # Run in background (no visible window)
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    
    # Automatically download/setup the correct Chrome driver
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
        "Extracted Amount": "Not Found", 
        "Status": "Processed",
        "Notes": ""
    }

    try:
        # 1. Wait for the main content to load
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        
        # 2. Try to click "Show more"
        # We look for buttons that might contain "Show more" or the specific arrow icon class
        # This part tries a few common selectors for 'Show more' buttons
        try:
            # Wait a moment for dynamic elements
            time.sleep(2) 
            
            # Find all buttons that might be "Show more"
            buttons = driver.find_elements(By.TAG_NAME, "button")
            for btn in buttons:
                if "Show more" in btn.text or "Show More" in btn.text:
                    driver.execute_script("arguments[0].click();", btn)
                    time.sleep(1) # Wait for expansion
                    break
            
            # Sometimes it's a div acting as a button, we check for that class if button fails
            # (Generic fallback click if needed, but text search usually works)
            
        except Exception as e:
            # It's possible "Show more" doesn't exist for short transactions, which is fine.
            result["Notes"] = "Show more button not found or not needed."

        # 3. Parse the page content with BeautifulSoup (easier than Selenium for finding text)
        soup = BeautifulSoup(driver.page_source, "html.parser")
        
        # 4. Find the keyword (e.g., "Nansen")
        # The user wants the number to the LEFT of "Nansen".
        # We look for the row that contains "Nansen".
        
        # Strategy: Find all text elements, locate the one with "Nansen", then look at the text around it.
        page_text = soup.get_text(separator=" | ")
        
        # We use Regex to look for the pattern seen in the screenshot:
        # Pattern: "Stake -124.07 SUI to Nansen"
        # We look for a number followed by "SUI to {target_keyword}"
        
        # Regex explanation:
        # ([\-\d\.]+)  -> Capture a number (including minus sign and decimals)
        # \s* -> Any spaces
        # SUI\s+to\s+  -> The literal text "SUI to" (based on screenshot)
        # {keyword}    -> The dynamic keyword (e.g., "Nansen")
        pattern = re.compile(r"([\-\d\.]+)\s*SUI\s+to\s+" + re.escape(target_keyword), re.IGNORECASE)
        
        match = pattern.search(page_text)
        
        if match:
            extracted_number = match.group(1)
            result["Extracted Amount"] = extracted_number
            result["Notes"] = "Success"
        else:
            # Fallback Strategy: Look for the specific HTML element if regex fails
            # (Useful if the text format changes slightly)
            elements_with_keyword = soup.find_all(string=lambda text: text and target_keyword in text)
            if elements_with_keyword:
                 result["Notes"] = f"Found '{target_keyword}' but couldn't parse amount via standard pattern."
            else:
                 result["Notes"] = f"'{target_keyword}' not found on page."

    except Exception as e:
        result["Status"] = "Error"
        result["Notes"] = str(e)
        
    return result

# --- STREAMLIT UI ---
st.set_page_config(page_title="SuiScan Data Extractor", page_icon="🔍")

st.title("🔍 SuiScan Transaction Extractor")
st.markdown("""
This tool automates the process of checking **Suiscan.xyz** transactions.
1. Upload your CSV with hashes.
2. It visits every link.
3. It clicks **"Show more"**.
4. It finds **"Nansen"** (or any other keyword) and extracts the amount next to it.
""")

# Sidebar settings
with st.sidebar:
    st.header("Settings")
    target_keyword = st.text_input("Target Keyword", value="Nansen", help="The word to search for (e.g., 'Nansen').")
    st.info("Ensure you have Google Chrome installed on this machine.")

# File Uploader
uploaded_file = st.file_uploader("Upload CSV or Excel file", type=["csv", "xlsx"])

if uploaded_file:
    # Load file
    if uploaded_file.name.endswith('.csv'):
        df = pd.read_csv(uploaded_file)
    else:
        df = pd.read_excel(uploaded_file)

    st.write("Preview of uploaded data:", df.head())

    # Column selection
    cols = df.columns.tolist()
    hash_col = st.selectbox("Select the column containing Transaction Hashes", cols, index=0)

    if st.button("Start Extraction"):
        st.write("🚀 Starting Chrome Driver... please wait.")
        
        # Initialize Driver
        try:
            driver = get_driver()
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            results = []
            total_rows = len(df)
            
            for index, row in df.iterrows():
                tx_hash = str(row[hash_col]).strip()
                
                # Update UI
                status_text.text(f"Processing {index + 1}/{total_rows}: {tx_hash}")
                progress_bar.progress((index + 1) / total_rows)
                
                # Scrape
                data = scrape_suiscan(driver, tx_hash, target_keyword)
                results.append(data)
                
                # Small pause to be polite to the server
                time.sleep(1)

            driver.quit()
            
            # Process Results
            results_df = pd.DataFrame(results)
            
            # Combine with original data
            final_df = pd.concat([df, results_df["Extracted Amount"]], axis=1)
            
            st.success("✅ Extraction Complete!")
            st.dataframe(final_df)
            
            # Download Button
            csv = final_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download Results as CSV",
                data=csv,
                file_name='suiscan_results.csv',
                mime='text/csv',
            )
            
        except Exception as e:
            st.error(f"An error occurred: {e}")
            st.warning("Make sure you are running this locally and have Chrome installed.")
