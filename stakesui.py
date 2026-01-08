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

# --- BROWSER SETUP (ANTI-DETECTION) ---
def get_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    
    # CRITICAL: Hide "Automation" flag to prevent button locking
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
    
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

    return webdriver.Chrome(service=service, options=options)

def coordinate_click(driver):
    """
    Finds the text 'Show more', calculates its X/Y pixels, 
    and fires a click event at that exact screen location.
    """
    try:
        # Find element by text
        xpath = "//*[contains(text(), 'Show more')]"
        elements = driver.find_elements(By.XPATH, xpath)
        
        for el in elements:
            if el.is_displayed():
                # 1. Scroll to Center
                driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'center'});", el)
                time.sleep(1)
                
                # 2. COORDINATE CLICK (The Fix)
                # We calculate the center pixel of the element and click IT, not the tag.
                driver.execute_script("""
                    const el = arguments[0];
                    const rect = el.getBoundingClientRect();
                    const x = rect.left + (rect.width / 2);
                    const y = rect.top + (rect.height / 2);
                    
                    // Create a physical click at these coordinates
                    const clickEvent = new MouseEvent('click', {
                        view: window,
                        bubbles: true,
                        cancelable: true,
                        clientX: x,
                        clientY: y
                    });
                    
                    // Find whatever is at that pixel (Button, Div, Overlay) and click it
                    const topElement = document.elementFromPoint(x, y);
                    if (topElement) {
                        topElement.dispatchEvent(clickEvent);
                        topElement.click(); 
                    } else {
                        el.click(); // Fallback
                    }
                """, el)
                
                time.sleep(3) # Wait for expansion
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
        # 1. Wait for body
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        time.sleep(5) 
        
        # 2. Try Coordinate Click
        coordinate_click(driver)

        # 3. Check if we need to click MORE (Pagination loop)
        # Sometimes you have to click 'Show more' multiple times
        for _ in range(3):
            # Check if keyword is found yet
            if target_keyword.lower() in driver.page_source.lower():
                break # Found it, stop clicking
            # If not found, try clicking again
            clicked = coordinate_click(driver)
            if not clicked:
                break # No more buttons found

        # 4. Capture Screenshot
        if debug_mode:
            screenshot = driver.get_screenshot_as_png()

        # 5. Parse Content
        soup = BeautifulSoup(driver.page_source, "html.parser")
        page_text = soup.get_text(separator="  ") 
        
        # 6. Search Logic
        keyword_matches = [m.start() for m in re.finditer(re.escape(target_keyword), page_text, re.IGNORECASE)]
        
        if not keyword_matches:
            result["Notes"] = f"Keyword '{target_keyword}' not found (List collapsed?)"
        else:
            found_amount = False
            for match_index in keyword_matches:
                # Look 150 chars BEHIND the keyword
                start_slice = max(0, match_index - 150)
                text_chunk = page_text[start_slice:match_index]
                
                # Regex: Number -> Optional Space -> SUI
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
                result["Notes"] = f"Found '{target_keyword}' but amount not linked. Context: '...{snippet}...'"

    except Exception as e:
        result["Status"] = "Error"
        result["Notes"] = str(e)
        
    return result, screenshot

# --- STREAMLIT UI ---
st.set_page_config(page_title="SuiScan Data Extractor", page_icon="🔍")
st.title("🔍 SuiScan Extractor (Coordinate Click)")

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
    
    col1, col2 = st.columns(2)
    with col1:
        cols = df.columns.tolist()
        hash_col = st.selectbox("Transaction Hash Column", cols, index=0)
    with col2:
        target_keyword = st.text_input("Search Keyword", value="Nansen")
    
    debug_mode = st.checkbox("📸 Enable Debug Screenshots", value=True)
    st.write("---")
    
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
