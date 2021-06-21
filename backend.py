import dash_bootstrap_components as dbc
import requests
from bs4 import BeautifulSoup
import webbrowser
import pandas as pd
import pickle
import urllib.request
import os
import plotly.graph_objs as go
from scipy.optimize import curve_fit
import plotly.express as px
import matplotlib.pyplot as plt
import re

import numpy as np

df_locations = None

if os.path.exists('resources/df_make_model.p'):
    df_make = pickle.load(open('resources/df_make_model.p', 'rb'))


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


path = 'resources/p_car_objects.p'
if os.path.exists(path):
    car_object_dict = pickle.load(open(path, 'rb'))

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

    print(text_in)
    print(text_out, "\n\n")

    return text_out


def get_locations():

    global df_locations

    pickle_path = 'resources/df_cities.p'
    if os.path.exists(pickle_path):
        df_locations = pickle.load(open(pickle_path, 'rb'))
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

    pickle.dump(df_locations, open(pickle_path, 'wb'))

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

    if not os.path.exists(f'assets/{name}'):
        urllib.request.urlretrieve(url, f'assets/{name}')
        print(url)

    return name


def on_click(event):
    url = event.artist.obj.url

    chrome_path = '/usr/bin/google-chrome %s'
    webbrowser.get(chrome_path).open(url)


def get_car_elems(URL):
    page = requests.get(URL)
    soup = BeautifulSoup(page.content, 'html.parser')
    results = soup.find(class_='rows')
    car_elems = results.find_all('li', class_='result-row')

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
            print("No Image", image_url)

        # --- Price
        price = price.replace(',', '')
        price = int(price)

        # --- Car Details
        try:
            car_page = requests.get(url)
            car_soup = BeautifulSoup(car_page.content, 'html.parser')
            attributes = car_soup.find_all('p', class_='attrgroup')

        except ConnectionError:
            print("Not connected -- ", url)
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

    pickle.dump(car_object_dict, open(path, 'wb'))

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

#
# # --- Get Owner Cars
# URL = base_url + owner + query + make + '+' + model
# elems = get_car_elems(URL)
# get_all_cars(elems, 'owner')
#
# # --- Get Dealer Cars
# URL = base_url + dealer + query + make + '+' + model
# elems = get_car_elems(URL)
# get_all_cars(elems, 'dealer')
#
#
# # --- Plot
# fig, ax = plt.subplots()
#
# # --- Annotate
# annot = plt.annotate("John", xy=(0, 0), xytext=(20, 20),
#                     textcoords="offset points",
#                     bbox=dict(boxstyle="round", fc="w"),
#                     arrowprops=dict(arrowstyle="->"))
# annot.set_visible(True)
#
# artists = []
# picture_artists = []
#
# for car in car_object_dict:
#
#     # --- Salvage
#     if 'title status' in car.attributes and (car.attributes['title status'] == 'salvage' or car.attributes['title status'] == 'rebuilt'):
#         print("\n\n\nRebuilt")
#         artist = ax.plot(car.x, car.y, color='orange', picker=5)[0]
#         artist.obj = car
#         artists.append(artist)
#         continue
#
#     # --- Owner
#     if car.owner_type == 'owner':
#         artist = ax.plot(car.x, car.y, 'ro', picker=5)[0]
#         artist.obj = car
#         artists.append(artist)
#
#     # --- Dealer
#     if car.owner_type == 'dealer':
#         artist = ax.plot(car.x, car.y, 'bo', picker=5)[0]
#         artist.obj = car
#         artists.append(artist)
#
#
# def hover(event):
#     vis = annot.get_visible()
#
#     for artist in artists:
#         cont, ind = artist.contains(event)
#         if cont:
#             pos = (event.x, event.y)
#             update_annotation(artist, pos)
#             annot.set_visible(True)
#             fig.canvas.draw_idle()
#             return
#
#         else:
#             annot.set_visible(False)
#             fig.canvas.draw_idle()
#
#             for artist in picture_artists:
#                 artist.remove()
#                 picture_artists.remove(artist)
#
#             plt.draw()
#
#
# def update_annotation(artist, pos):
#     car = artist.obj
#     car.attributes['title'] = car.title
#     car_dict = ([key + car.attributes[key] for key in car.attributes.keys()])
#     annot.set_text("\n".join(car_dict))
#     annot.get_bbox_patch().set_alpha(0.4)
#     annot.xy = (car.x, car.y)
#
#     car_picture = mpimg.imread('assets/' + car.image)
#     imagebox = OffsetImage(car_picture, zoom=0.8)
#     ab = AnnotationBbox(imagebox, (car.x - 20000, car.y - 2000))
#
#     picture_artist = ax.add_artist(ab)
#     picture_artists.append(picture_artist)
#
#
# fig.canvas.callbacks.connect('pick_event', on_click)
# fig.canvas.mpl_connect("motion_notify_event", hover)
# plt.title(make + " " + model)
# plt.grid(which='both', axis='both')
# plt.show()

