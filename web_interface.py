
# --- Selenium
from selenium import webdriver
from selenium.webdriver import ActionChains
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.support.wait import WebDriverWait

import urllib.request

# --- Logging
from color_logging import *
logger = get_logger(__name__)


# -------------------------------------------------------
#               Initialize Web Driver
# -------------------------------------------------------


class Web_Interface:
    def __init__(self):
        WINDOW_SIZE = "1920,1080"
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--window-size=%s" % WINDOW_SIZE)

        # Selenium Manager locates (or downloads) Chrome and chromedriver
        self.driver = webdriver.Chrome(options=chrome_options)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            logger.exception(exc_val)

        self.driver.quit()

    def get_all_listings(self, url):
        self.driver.get(url)
        car_elems = WebDriverWait(self.driver, timeout=10).until(
            lambda d: d.find_elements(By.CLASS_NAME, "gallery-card"))

        return car_elems

    def get_car_attributes(self, url):

        original_page = self.driver.current_window_handle
        self.driver.switch_to.new_window('tab')
        attr_dict = {}

        try:
            self.driver.get(url)
            attributes = self.driver.find_elements(By.CLASS_NAME, "attrgroup")

            for attr in attributes:
                for item in attr.text.split('\n'):
                    if ":" in item.strip():
                        key, value = item.split(':')
                        attr_dict[key] = value
        except NoSuchElementException as e:
            logger.error(f"Unable to load attributes for {url}")
            pass

        finally:
            self.driver.close()
            self.driver.switch_to.window(original_page)

        return attr_dict

    @staticmethod
    def get_car_info(car):
        try:
            # --- Objects
            title_object = car.find_element(By.CLASS_NAME, "posting-title")
            price_object = car.find_element(By.CLASS_NAME, "priceinfo")

            # --- Convert
            price = price_object.text
            price = price.replace(',', '').replace('$', '')
            price = int(price)

            title = title_object.text
            url = title_object.get_attribute('href')

            # --- Numeric posting id is on the parent search-result div; urls no longer contain it
            id = car.find_element(By.XPATH, '..').get_attribute('data-pid') or url.rstrip('/').split('/')[-1]

            return price, title, url, id

        except NoSuchElementException as e:
            logger.error(f"NoSuchElementException")
            return 0, "", None, None

    def get_car_image(self, car):

        actions = ActionChains(self.driver)

        img = car.find_element(By.TAG_NAME, 'img')
        url = img.get_attribute("src")

        if not url:
            actions.move_to_element(car).perform()
            url = img.get_attribute("src")

        if not url:
            logger.error(f"{car} has no img src")
            return "placeholder.png"

        name = str(url.split('/')[-1])

        img_path = f'assets/car_images/{name}'

        logger.debug(f"Downloading Image {url}")
        if not os.path.exists(img_path):
            filename, headers = urllib.request.urlretrieve(url, img_path)
            logger.debug(f"{filename=}")
            logger.debug(f"{headers=}")
        return name


