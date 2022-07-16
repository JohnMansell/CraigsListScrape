
# --- Modules
import requests
import pandas as pd
from bs4 import BeautifulSoup

# --- Logging
from color_logging import *
logger = get_logger(__name__)

# --- Constants
HEADERS = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/103.0.0.0 Safari/537.36'}


def url_request(url):
    try:
        page = requests.get(url, headers=HEADERS)
    except Exception as e:
        logger.error(e)

    if page.status_code != 200:
        logger.error(f"{page.status_code=}. {page.reason=}. {url=}")

    return page


def get_cities_from_web():
    # --- Get geo site list
    URL = 'https://geo.craigslist.org/iso/us'
    page = url_request(URL)
    soup = BeautifulSoup(page.content, 'html.parser')

    href_list = list()
    cities_list = list()
    states_list = list()

    # --- Parse Cities
    for ultag in soup.find_all('ul', {'class': 'height6 geo-site-list'}):
        for litag in ultag.find_all('li'):

            text = litag.text
            try:
                city, state = text.split(',')
            except:
                print("-------------")
                print(text)
                city = input("City :: ")
                state = input("State :: ")

                if len(city) == 0:
                    city = text.title()

            href_list.append(litag.a.get('href'))
            cities_list.append(city.title())
            states_list.append(state)

    # --- Data Frame
    return pd.DataFrame({'href': href_list,
                         'city': cities_list,
                         'state': states_list})


def get_car_elems(URL):
    logger.debug(f"Get car elements from {URL}")
    page = url_request(URL)
    if not page:
        return list()

    soup = BeautifulSoup(page.content, 'html.parser')
    results = soup.find(class_='rows')
    car_elems = results.find_all('li', class_='result-row') if results else list()

    return car_elems


def get_car_attributes(url):
    logger.debug(f"Getting car attributes {url=}")
    car_page = url_request(url)
    car_soup = BeautifulSoup(car_page.content, 'html.parser')
    attributes = car_soup.find_all('p', class_='attrgroup')

    return attributes
