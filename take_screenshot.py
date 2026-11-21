"""
Capture screenshots of the SiteSage application using Selenium Headless.
"""

import sys
import time
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def capture_screenshots():
    screenshot_dir = Path("screenshots")
    screenshot_dir.mkdir(exist_ok=True)

    options = webdriver.EdgeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1280,900")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")

    try:
        driver = webdriver.Edge(options=options)
    except Exception as e:
        print(f"Edge driver failed ({e}), trying Chrome...")
        chrome_options = webdriver.ChromeOptions()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--window-size=1280,900")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        driver = webdriver.Chrome(options=chrome_options)

    try:
        # 1. Capture Initial Homepage
        print("Navigating to http://127.0.0.1:8000...")
        driver.get("http://127.0.0.1:8000")
        time.sleep(1.5)

        home_shot = screenshot_dir / "01_homepage.png"
        driver.save_screenshot(str(home_shot))
        print(f"Saved initial homepage: {home_shot}")

        # 2. Click preset 'Quotes — Einstein Quotes'
        print("Clicking preset example...")
        preset_btn = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, ".preset-pill"))
        )
        preset_btn.click()
        time.sleep(0.5)

        preset_shot = screenshot_dir / "02_form_populated.png"
        driver.save_screenshot(str(preset_shot))
        print(f"Saved populated form: {preset_shot}")

        # 3. Submit search
        print("Submitting search...")
        search_btn = driver.find_element(By.ID, "search-btn")
        search_btn.click()
        time.sleep(2.0)

        # 4. Capture Live Crawl Dashboard during crawl
        crawling_shot = screenshot_dir / "03_live_crawl_dashboard.png"
        driver.save_screenshot(str(crawling_shot))
        print(f"Saved live crawling dashboard: {crawling_shot}")

        # 5. Wait for results to be rendered
        print("Waiting for search results...")
        WebDriverWait(driver, 60).until(
            EC.visibility_of_element_located((By.ID, "answer-text-content"))
        )
        time.sleep(1.0)

        results_shot = screenshot_dir / "04_search_results.png"
        driver.save_screenshot(str(results_shot))
        print(f"Saved search results: {results_shot}")

        # 6. Expand Search Transparency Accordion
        print("Expanding transparency accordion...")
        transparency_toggle = driver.find_element(By.ID, "transparency-toggle")
        driver.execute_script("arguments[0].scrollIntoView();", transparency_toggle)
        transparency_toggle.click()
        time.sleep(1.0)

        transparency_shot = screenshot_dir / "05_transparency_bm25_explainability.png"
        driver.save_screenshot(str(transparency_shot))
        print(f"Saved transparency details: {transparency_shot}")

        # 7. Open History Drawer
        print("Opening history drawer...")
        history_btn = driver.find_element(By.ID, "btn-toggle-history")
        driver.execute_script("arguments[0].scrollIntoView();", history_btn)
        history_btn.click()
        time.sleep(1.0)

        history_shot = screenshot_dir / "06_session_history_drawer.png"
        driver.save_screenshot(str(history_shot))
        print(f"Saved session history drawer: {history_shot}")

        print("All screenshots captured successfully!")

    finally:
        driver.quit()

if __name__ == "__main__":
    capture_screenshots()
