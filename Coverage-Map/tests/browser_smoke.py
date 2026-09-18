"""Optional: run with an interpreter providing Selenium and installed Chrome."""
from pathlib import Path
import subprocess
import tempfile

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

ROOT = Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    artifacts = Path(tempfile.mkdtemp(prefix="coverage-browser-"))
    process = subprocess.Popen([str(ROOT/".venv/Scripts/python.exe"),str(ROOT/"tests/serve_demo.py")], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    driver = None
    try:
        line = process.stdout.readline().strip()
        if not line.startswith("READY "):
            raise RuntimeError("Fixture server failed: " + line)
        address = line.removeprefix("READY ")
        options = webdriver.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--window-size=1450,1050")
        options.set_capability("goog:loggingPrefs", {"browser":"ALL"})
        driver = webdriver.Chrome(options=options)
        wait = WebDriverWait(driver,20)
        driver.get(address+"/Coverage/")
        wait.until(lambda d: "actualisées" in d.find_element(By.ID,"status").text)
        assert not driver.find_element(By.ID,"clients-section").is_displayed()
        driver.find_element(By.ID,"gps").send_keys("34.025, -4.995")
        driver.find_element(By.CSS_SELECTOR,"#gps-form button").click()
        wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR,".operator-match")) == 3)
        assert "5" in driver.find_element(By.ID,"pco-rows").text
        driver.save_screenshot(str(artifacts/"map-desktop.png"))
        driver.set_window_size(390,844)
        driver.save_screenshot(str(artifacts/"map-mobile.png"))
        driver.set_window_size(1450,1050)
        driver.get(address+"/Coverage/admin")
        driver.find_element(By.ID,"password").send_keys("synthetic-test-password")
        driver.find_element(By.CSS_SELECTOR,".login button").click()
        wait.until(lambda d: "Configuration prête" in d.find_element(By.ID,"admin-status").text)
        driver.save_screenshot(str(artifacts/"admin.png"))
        driver.find_element(By.CSS_SELECTOR,'input[name="IAM"]').click()
        driver.find_element(By.CSS_SELECTOR,'input[name="clients"]').click()
        driver.find_element(By.CSS_SELECTOR,"#visibility-form button").click()
        wait.until(lambda d: "Visibilité enregistrée" in d.find_element(By.ID,"admin-status").text)
        driver.get(address+"/Coverage/")
        wait.until(lambda d: d.find_element(By.ID,"clients-section").is_displayed())
        driver.find_element(By.ID,"gps").send_keys("34.025, -4.995")
        driver.find_element(By.CSS_SELECTOR,"#gps-form button").click()
        wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR,".operator-match")) == 2)
        driver.find_element(By.ID,"client-query").send_keys("fictif")
        driver.find_element(By.CSS_SELECTOR,"#clients-form button").click()
        wait.until(lambda d: "Client fictif" in d.find_element(By.ID,"client-rows").text)
        errors = [entry for entry in driver.get_log("browser") if entry["level"] == "SEVERE" and ("Uncaught" in entry["message"] or "SyntaxError" in entry["message"])]
        assert not errors, errors
        print("Browser smoke PASS: map/GPS/PCO/admin/permissions/client search through portal.")
        print(f"Screenshots: {artifacts}")
    finally:
        if driver: driver.quit()
        if process.poll() is None:
            process.communicate("\n",timeout=15)
        else:
            process.communicate(timeout=15)
