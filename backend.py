import requests
from bs4 import BeautifulSoup
import webbrowser
import pandas as pd
import pickle
import urllib.request
import os
import plotly.graph_objs as go
from scipy.optimize import curve_fit
import re

import numpy as np

CWD = os.path.dirname(__file__)

df_locations = None

df_make_path = os.path.join(CWD, 'resources/df_make_model.p')

if os.path.exists(df_make_path):
    df_make = pickle.load(open(df_make_path, 'rb'))


class car_object:
    def __init__(self, owner_type):
        self.owner_type = owner_type

        self.miles = 0
        self.price = 0
        self.url = ""
        self.title = ""
        self.attributes = {}
        self.hover_data = ''
        self.image = None


df_car_object_path = os.path.join(CWD, 'resources/p_car_objects.p')
if os.path.exists(df_car_object_path):
    car_object_dict = pickle.load(open(df_car_object_path, 'rb'))

else:
    car_object_dict = {}


def sanitize_string(text_in):
    emoji_pattern = re.compile("["
                               u"\U0001F600-\U0001F64F"  # emoticons
                               u"\U0001F300-\U0001F5FF"  # symbols & pictographs
                               u"\U0001F680-\U0001F6FF"  # transport & map symbols
                               u"\U0001F1E0-\U0001F1FF"  # flags (iOS)
                               "]+", flags=re.UNICODE)

    text_out = emoji_pattern.sub(r'', text_in)

    return text_out


def get_locations():

    global df_locations

    df_cities_path = os.path.join(CWD, 'resources/df_cities.p')
    if os.path.exists(df_cities_path):
        df_locations = pickle.load(open(df_cities_path, 'rb'))
        return

    href_list = []
    cities_list = []
    states_list = []

    # --- Get geo site list
    URL = 'https://geo.craigslist.org/iso/us'
    page = requests.get(URL)
    soup = BeautifulSoup(page.content, 'html.parser')

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
    df_locations = pd.DataFrame({'href': href_list,
                              'city': cities_list,
                              'state': states_list})

    pickle.dump(df_locations, open(df_cities_path, 'wb'))

    return


def get_states():

    states = df_locations['state'].unique().tolist()
    states_list = [{'value': state, 'label': state} for state in sorted(states)]

    return states_list


def get_cities(state):
    df_state = df_locations[df_locations['state'] == state]
    cities = df_state['city'].tolist()

    city_options = [{'label': city, 'value': city} for city in cities]

    return city_options


def build_url(state, city, make, model, owner_type):

    global df_locations

    df = df_locations[df_locations['city'] == city]
    base_url = df.href.tolist()[0]

    owner = 'cto' if owner_type == 'owner' else 'ctd'
    query = '?auto_make_model='

    URL = base_url + '/d/cars-trucks-by-owner/search/' + owner + query + make + '%20' + model

    return URL


def download_image(url):
    name = str(url.split('/')[-1])

    img_path = os.path.join(CWD, f'assets/car_images/{name}')

    if not os.path.exists(img_path):
        urllib.request.urlretrieve(url, img_path)

    return name


def on_click(event):
    url = event.artist.obj.url

    chrome_path = '/usr/bin/google-chrome %s'
    webbrowser.get(chrome_path).open(url)


def get_car_elems(URL):
    page = requests.get(URL)
    soup = BeautifulSoup(page.content, 'html.parser')
    results = soup.find(class_='rows')
    car_elems = results.find_all('li', class_='result-row') if results else list()

    return car_elems


def get_all_cars(car_elems, owner_type):

    car_objects = []
    cars_from_pickle = 0

    for car in car_elems:
        try:
            id = car['data-pid']
            if id in car_object_dict:
                car_objects.append(car_object_dict[id])
                cars_from_pickle += 1
                continue

            price = car.find('span', class_='result-price').text.strip()[1:]
            url = car.find('a', class_='result-image gallery')['href']
            title = car.find('a', class_='result-title hdrlnk').text.strip()
            title = sanitize_string(title)

        except TypeError:
            print("Cant connect")
            continue

        # --- Car Image
        image_url = 'https://images.craigslist.org/{}_300x300.jpg'
        ids = [item.get('data-ids').replace('3:', '') for item in car.findAll("a", {"class": "result-image gallery"}, limit=10)]
        images = [image_url.format(i.split(',')[0]) for i in ids]
        try:
            download_image(images[0])
        except:
            print("No Image", image_url, "ids = ", ids)

        # --- Price
        price = price.replace(',', '')
        price = int(price)

        # --- Car Details
        try:
            car_page = requests.get(url)
            car_soup = BeautifulSoup(car_page.content, 'html.parser')
            attributes = car_soup.find_all('p', class_='attrgroup')

        except ConnectionError:
            continue

        # --- Initialize Car
        car = car_object(owner_type)
        car.price = price
        car.title = title
        car.url = url
        car.image = ids[0].split(',')[0] + '_300x300.jpg'

        # --- Get attributes
        for att in attributes:
            spans = att.find_all('span')

            for span in spans:
                text = span.text.strip()
                if ':' not in text:
                    continue

                key, value = text.split(':')
                car.attributes[key] = value
                if key == 'odometer':
                    car.miles = int(value)

        car.hover_data = "\n".join([f'{key}:{car.attributes[key]}' for key in car.attributes])

        car_object_dict[id] = car
        car_objects.append(car)

    pickle.dump(car_object_dict, open(df_car_object_path, 'wb'))

    df_cars = pd.DataFrame([o.__dict__ for o in car_objects])

    return df_cars


def get_make_options():

    global df_make
    make_unique = df_make.make.unique()

    make_options = [{'label': make, 'value': make} for make in sorted(make_unique)]
    return make_options


def solve_curves(fig, df_cars):

    def func(x, a, b, c):
        return a * np.exp(-b * x) + c

    owners = {'owner': 'blue', 'dealer': 'red'}

    for owner_type in owners:

        df = df_cars[(df_cars['owner_type'] == owner_type) &
                     (df_cars['price'] > 500)]

        X = np.array(df['miles'].tolist())
        Y = np.array(df['price'].tolist())

        if len(Y) < 2:
            continue

        try:
            popt, pcov = curve_fit(func, X, Y, [2000, 0, 4000])

        except RuntimeError:
            continue

        fig.add_trace(go.Scatter(x=X,
                                 y=func(X, *popt),
                                 mode='lines',
                                 hoverinfo='skip',
                                 name=owner_type,
                                 line=dict(color=owners[owner_type], width=2)
                                 ))

    return fig


def get_model_options(make):
    global df_make

    df_make_filtered = df_make[df_make['make'] == make]
    models_list = df_make_filtered.model.unique()

    model_options = [{'label': model, 'value': model} for model in models_list]
    return model_options
