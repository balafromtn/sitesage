"""
End-to-end browser integration tests for SiteSage web interface.
Uses Selenium in headless mode to test real DOM interactions, form submission,
and responsive rendering.
"""

import sys
import time
from pathlib import Path

import pytest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def get_headless_driver():
    """Attempt to initialize headless Edge or Chrome."""
    try:
        opts = webdriver.EdgeOptions()
        opts.add_argument("--headless=new")
        opts.add_argument("--window-size=1280,900")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--no-sandbox")
        return webdriver.Edge(options=opts)
    except Exception:
        try:
            chrome_opts = webdriver.ChromeOptions()
            chrome_opts.add_argument("--headless=new")
            chrome_opts.add_argument("--window-size=1280,900")
            chrome_opts.add_argument("--disable-gpu")
            chrome_opts.add_argument("--no-sandbox")
            return webdriver.Chrome(options=chrome_opts)
        except Exception:
            return None


class TestBrowserInterfaceE2E:
    @classmethod
    def setup_class(cls):
        cls.base_url = "http://127.0.0.1:8000"
        cls.server_running = False
        try:
            import urllib.request
            with urllib.request.urlopen(cls.base_url, timeout=0.5) as resp:
                if resp.status == 200:
                    cls.server_running = True
        except Exception:
            cls.server_running = False

        if cls.server_running:
            cls.driver = get_headless_driver()
        else:
            cls.driver = None

    @classmethod
    def teardown_class(cls):
        if getattr(cls, "driver", None):
            try:
                cls.driver.quit()
            except Exception:
                pass

    def test_homepage_elements(self):
        if not self.driver or not getattr(self, "server_running", False):
            pytest.skip("SiteSage server is not running on 127.0.0.1:8000")

        self.driver.get(self.base_url)
        time.sleep(1)

        # Check title and branding
        assert "SiteSage" in self.driver.title
        brand_h1 = self.driver.find_element(By.TAG_NAME, "h1")
        assert "SiteSage" in brand_h1.text

        # Check form inputs
        url_input = self.driver.find_element(By.ID, "url-input")
        question_input = self.driver.find_element(By.ID, "question-input")
        slider = self.driver.find_element(By.ID, "max-pages-input")
        search_btn = self.driver.find_element(By.ID, "search-btn")

        assert url_input.is_displayed()
        assert question_input.is_displayed()
        assert slider.is_displayed()
        assert search_btn.is_displayed()

    def test_preset_interaction_and_slider(self):
        if not self.driver or not getattr(self, "server_running", False):
            pytest.skip("SiteSage server is not running on 127.0.0.1:8000")

        self.driver.get(self.base_url)
        time.sleep(1)

        # Click first preset button
        preset = WebDriverWait(self.driver, 5).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, ".preset-pill"))
        )
        preset.click()

        url_val = self.driver.find_element(By.ID, "url-input").get_attribute("value")
        q_val = self.driver.find_element(By.ID, "question-input").get_attribute("value")

        assert "http" in url_val
        assert len(q_val) >= 3

    def test_history_drawer_toggle(self):
        if not self.driver or not getattr(self, "server_running", False):
            pytest.skip("SiteSage server is not running on 127.0.0.1:8000")

        self.driver.get(self.base_url)
        time.sleep(1)

        history_btn = self.driver.find_element(By.ID, "btn-toggle-history")
        history_btn.click()
        time.sleep(0.5)

        drawer = self.driver.find_element(By.ID, "history-drawer")
        assert "open" in drawer.get_attribute("class")

        # Close history
        close_btn = self.driver.find_element(By.ID, "btn-close-history")
        close_btn.click()
        time.sleep(0.5)
        assert "open" not in drawer.get_attribute("class")

    def test_mobile_viewport_responsiveness(self):
        if not self.driver or not getattr(self, "server_running", False):
            pytest.skip("SiteSage server is not running on 127.0.0.1:8000")

        # Set mobile viewport
        self.driver.set_window_size(500, 700)
        self.driver.get(self.base_url)
        time.sleep(0.5)

        # Ensure container width adapts to viewport without horizontal scroll overflow
        inner_width = self.driver.execute_script("return window.innerWidth")
        container = self.driver.find_element(By.CLASS_NAME, "app-container")
        assert container.size["width"] <= inner_width

        # Restore size
        self.driver.set_window_size(1280, 900)
