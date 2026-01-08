import streamlit as st
import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import time
import re
import shutil

# --- CONFIGURATION & SETUP ---
def get_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    chromium_path = shutil.which("chromium")
    chromedriver_path = shutil.which("chromedriver")
    
    if chromium_path and chromedriver_path:
        options.binary_location = chromium_path
        service = Service(chromedriver_path)
    else:
        try:
            service = Service(ChromeDriverManager().install())
        except Exception:
            return None

    try:
        driver = webdriver.Chrome(service=service, options=options)
        return driver
    except Exception:
        return None

def force_click_element(driver, element):
    """
    Tries 4 different ways to click a stubborn element.
    """
    # Method 1: Standard Click
    try:
        element.click()
        return True
    except Exception:
        pass

    # Method 2: JavaScript Click (Bypasses UI overlays)
    try:
        driver.execute_script("arguments[0].click();", element)
        return True
    except Exception:
        pass

    # Method 3: ActionChains (Simulates real mouse movement)
    try:
        actions = ActionChains(driver)
        actions.move_to_element(element).click().perform()
        return True
    except Exception:
        pass
        
    # Method 4: Parent JavaScript Click (If the text itself is unclickable)
    try:
        driver.execute_script("arguments[0].parentElement.click();", element)
        return True
    except Exception:
        pass

    return False

def scrape_suiscan(driver, tx_hash, target_keyword, debug_mode):
    url = f"https://suiscan.xyz/mainnet/tx/{tx_hash}"
    try:
        driver.get(url)
    except Exception:
        return {"Transaction Hash": tx_hash, "Status": "Network Error", "Notes": "Could not reach URL"}, None
    
    col_name = f"Amount to '{target_keyword}'"
    result = {
        "Transaction Hash": tx_hash, 
        col_name: "Not Found",
        "Status": "Processed",
        "Notes": ""
    }
    screenshot = None

    try:
        # 1. Wait for page load
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        time.sleep(4) 
        
        # --- 🛠️ FIX: BRUTE FORCE EXPANDER ---
        clicked_successfully = False
        
        # Locate candidates for "Show more"
        # We look for ANY element containing that text
        candidates = driver.find_elements(By.XPATH, "//*[contains(text(), 'Show more')]")
        
        for btn in candidates:
            if btn.is_displayed():
                # Scroll to center
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                time.sleep(1)
                
                # Try all 4 click methods on this button
                if force_click_element(driver, btn):
                    time.sleep(2) # Wait for expansion
                    clicked_successfully = True
                    # Verify? (Optional: check if "Show less" appeared)
                    break
        
        if not clicked_successfully:
             result["Notes"] += " (Warning: Could not click 'Show more')"
        # ----------------------------------------

        # 3. Capture Screenshot (Post-Click)
        if debug_mode:
            screenshot = driver.get_screenshot_as_png()

        # 4. Parse Content
        soup = BeautifulSoup(driver.page_source, "html.parser")
        page_text = soup.get_text(separator="  ") 
        
        # 5. Search Logic (Smart Proximity)
        keyword_matches = [m.start() for m in re.finditer(re.escape(target_keyword), page_text, re.IGNORECASE)]
        
        if not keyword_matches:
            # Fallback: Maybe it's "Show More" (Capital M) or different text?
            result["Notes"] = f"Keyword '{target_keyword}' not found (List likely collapsed)."
        else:
            found_amount = False
            for match_index in keyword_matches:
                # Look 100 chars BEHIND the keyword
                start_slice = max(0, match_index - 100)
                text_chunk = page_text[start_slice:match_index]
                
                # Regex logic: Number -> Optional Space -> SUI
                amount_pattern = re.compile(r"([\-\d\.,]+)\s*SUI", re.IGNORECASE)
                matches_in_chunk = list(amount_pattern.finditer(text_chunk))
                
                if matches_in_chunk:
                    best_match = matches_in_chunk[-1] 
                    result[col_name] = best_match.group(1)
                    result["Notes"] = "Success"
                    found_amount = True
                    break 
            
            if not found_amount:
                snippet = page_text[max(0, keyword_matches[0]-50) : keyword_matches[0]]
                result["Notes"] = f"Found '{target_keyword}' but couldn't link amount. Context: '...{snippet}...'"

    except Exception as e:
        result["Status"] = "Error"
        result["Notes"] = str(e)
        
    return result, screenshot

# --- STREAMLIT UI ---
st.set_page_config(page_title="SuiScan Data Extractor", page_icon="🔍")

st.title("🔍 SuiScan Transaction Extractor")
st.markdown("Extracts validator stake amounts. **Updated with Brute Force Clicker.**")

# 1. Upload
st.subheader("Step 1: Upload Data")
uploaded_file = st.file_uploader("Upload CSV/Excel", type=["csv", "xlsx"])

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
        hash_col = st.selectbox("Transaction Hash Column", cols, index=0)
        
    with col2:
        target_keyword = st.text_input("Search Keyword", value="Nansen")
    
    debug_mode = st.checkbox("📸 Enable Debug Screenshots", value=True)

    st.write("---")
    
    # 3. Run
    if st.button("🚀 Start Extraction"):
        if not target_keyword:
            st.error("Please enter a keyword.")
        else:
            status_container = st.empty()
            status_container.info("Starting Browser Engine...")
            
            driver = get_driver()
            
            if driver:
                status_container.success("Browser Active!")
                progress_bar = st.progress(0)
                status_text = st.empty()
                debug_area = st.expander("Debug Screenshots", expanded=True)
                
                results = []
                total_rows = len(df)
                
                for index, row in df.iterrows():
                    tx_hash = str(row[hash_col]).strip()
                    
                    status_text.text(f"Scanning {index + 1}/{total_rows}: {tx_hash}")
                    progress_bar.progress((index + 1) / total_rows)
                    
                    data, screenshot = scrape_suiscan(driver, tx_hash, target_keyword, debug_mode)
                    results.append(data)
                    
                    if debug_mode and screenshot and data[f"Amount to '{target_keyword}'"] == "Not Found":
                        with debug_area:
                            st.warning(f"❌ Failed on: {tx_hash}")
                            st.image(screenshot, caption=f"View of {tx_hash}", width=700)
                    
                    time.sleep(1)

                driver.quit()
                
                results_df = pd.DataFrame(results)
                final_df = pd.concat([df, results_df.drop(columns=["Transaction Hash"], errors='ignore')], axis=1)
                
                st.success("✅ Done!")
                st.dataframe(final_df)
                
                csv = final_df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label=f"📥 Download Results",
                    data=csv,
                    file_name=f'suiscan_results.csv',
                    mime='text/csv',
                )
            else:
                st.error("⚠️ Browser Error: Could not start Chrome. Check logs.")
