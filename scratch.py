import time

import selenium.common.exceptions
from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager

from color_logging import get_logger
logger = get_logger(__name__)

WINDOW_SIZE = "1920,1080"

chrome_options = Options()
chrome_options.add_argument("--window-size=%s" % WINDOW_SIZE)
chrome_options.add_argument("--headless")


def get_car_attributes(url: str, driver):

    attr_dict = {}

    try:
        driver.get(url)
        attributes = driver.find_elements(By.CLASS_NAME, "attrgroup")

        for attr in attributes:
            for item in attr.text.split('\n'):
                if ":" in item:
                    key, value = item.split(':')
                    if key == 'odometer':
                        key = 'miles'
                    attr_dict[key] = value

        return attr_dict

    except NoSuchElementException as e:
        return {}

    finally:
        driver.close()



if __name__ == '__main__':
    with webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options) as driver:

        # --- Open URL
        driver.get("https://orangecounty.craigslist.org/search/cta?auto_make_model=honda%20civic&purveyor=owner")

        # --- Set up Wait for later
        wait = WebDriverWait(driver, 10)

        # --- Store ID of the original window
        original_window = driver.current_window_handle

        # --- Check we don't have other windows open already
        assert len(driver.window_handles) == 1

        # --- Get Car Listings
        car_objects = []
        car_listings = driver.find_elements(By.CLASS_NAME, "gallery-card")

        # --- Basic Data
        for car in car_listings:
            try:
                price = car.find_element(By.CLASS_NAME, "priceinfo")
                title = car.find_element(By.CLASS_NAME, "titlestring")
                url = title.get_attribute('href')
                print(title.text, title)
                print(price.text)
                print(f"{url = }")

                car_objects.append({'title': title, 'price': price, 'url': url})

            except NoSuchElementException:
                continue

            try:
                driver.switch_to.new_window('tab')
                print(get_car_attributes(url, driver))
                driver.switch_to.window(original_window)

            except Exception as e:
                print(e, car)

        driver.quit()

# https://orangecounty.craigslist.org/cto/d/tustin-2006-honda-civic-138k-2door/7613961355.html