
# --- Python
import pandas as pd
import pickle
from scipy.optimize import curve_fit
import re
import numpy as np
import plotly.graph_objs as go


# --- Project
from web_interface import Web_Interface

# --- Logging
from color_logging import *
logger = get_logger(__name__)


CWD = os.path.dirname(__file__)


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
        self.id = 0


DF_CAR_OBJECT_PATH = os.path.join(CWD, 'resources/p_car_objects.p')


class Backend:
    def __init__(self):

        self.web = Web_Interface()
        self.makes_and_models = None
        self.locations = None
        self.car_object_dict = {}

        # --- Object Dict
        if os.path.exists(DF_CAR_OBJECT_PATH):
            self.car_object_dict = pickle.load(open(DF_CAR_OBJECT_PATH, 'rb'))

    @staticmethod
    def sanitize_string(text_in):
        emoji_pattern = re.compile('['
                                   u'\U0001F600-\U0001F64F'  # emoticons
                                   u'\U0001F300-\U0001F5FF'  # symbols & pictographs
                                   u'\U0001F680-\U0001F6FF'  # transport & map symbols
                                   u'\U0001F1E0-\U0001F1FF'  # flags (iOS)
                                   ']+', flags=re.UNICODE)

        text_out = emoji_pattern.sub(r'', text_in)

        return text_out

    def get_makes_and_models(self):
        if self.makes_and_models is not None:
            return self.makes_and_models

        df_make_model_path = os.path.join(CWD, 'resources/df_make_model.p')

        if os.path.exists(df_make_model_path):
            self.makes_and_models = pickle.load(open(df_make_model_path, 'rb'))
            return self.makes_and_models

        raise FileNotFoundError(f"{df_make_model_path}")

    def get_locations(self) -> pd.DataFrame:

        if self.locations is not None:
            return self.locations

        df_cities_path = os.path.join(CWD, 'resources/df_cities.p')
        if os.path.exists(df_cities_path):
            self.locations = pickle.load(open(df_cities_path, 'rb'))
            return self.locations

    def get_states(self):
        df_locations = self.get_locations()
        states = df_locations['state'].unique().tolist()
        states_list = [{'value': state, 'label': state} for state in sorted(states)]

        return states_list

    def get_cities(self, state):
        df_locations = self.get_locations()
        df_state = df_locations[df_locations['state'] == state]
        cities = df_state['city'].tolist()

        city_options = [{'label': city, 'value': city} for city in cities]

        return city_options

    def build_url(self, state, city, make, model, owner_type):
        df_locations = self.get_locations()
        df = df_locations[df_locations['city'] == city]
        base_url = df.href.tolist()[0]

        owner = 'cto' if owner_type == 'owner' else 'ctd'

        URL = f"{base_url}/search/cta?auto_make_model={make}%20{model}&purveyor={owner_type}"
        logger.info(f"Search URL = {URL}")

        return URL

    def get_car_objects(self, car_listings, owner_type):

        car_objects = []
        cars_from_pickle = 0

        for car in car_listings:
            try:
                # --- Info
                price, title, url, id = self.web.get_car_info(car)
                if not url:
                    continue

                # --- Already Exists
                if id and id in self.car_object_dict:
                    car_objects.append(self.car_object_dict[id])
                    cars_from_pickle += 1
                    logger.info(self.car_object_dict[id].title)
                    continue

                # --- Create Object
                car_obj = car_object(owner_type)
                car_obj.id = id
                car_obj.price = price
                car_obj.title = title
                car_obj.url = url
                car_obj.image = self.web.get_car_image(car)

                # --- Details
                car_obj.attributes = self.web.get_car_attributes(car_obj.url)
                car_obj.hover_data = "\n".join([f'{key}:{car_obj.attributes[key]}' for key in car_obj.attributes])

                # --- Milage
                odometer = car_obj.attributes.get('odometer', '').replace(',', '').strip()
                if odometer:
                    car_obj.miles = int(odometer)

                # --- Save for Later
                if car_obj.image != "placeholder.png":
                    self.car_object_dict[car_obj.id] = car_obj
                    car_objects.append(car_obj)
                    logger.info(f"{car_obj.title}")

                    pickle.dump(self.car_object_dict, open(DF_CAR_OBJECT_PATH, 'wb'))


            except Exception as e:
                logger.exception(e)
                continue

        df_cars = pd.DataFrame([o.__dict__ for o in car_objects])

        return df_cars

    def get_make_options(self):
        df_makes = self.get_makes_and_models()
        make_unique = df_makes.make.unique()

        make_options = [{'label': make, 'value': make} for make in sorted(make_unique)]
        return make_options

    def get_model_options(self, make):
        df_makes = self.get_makes_and_models()
        df_make_filtered = df_makes[df_makes['make'] == make]
        models_list = df_make_filtered.model.unique()

        model_options = [{'label': model, 'value': model} for model in models_list]
        return model_options

    def get_all_cars(self, state, city, make, model):
        url = self.build_url(state, city, make, model, 'owner')
        car_listings = self.web.get_all_listings(url)
        df_owner = self.get_car_objects(car_listings, 'owner')

        return df_owner

    @staticmethod
    def solve_curves(fig, df_cars):

        def func(x, a, b, c):
            return a * np.exp(-b * x) + c

        def remove_outliers(df, column):
            Q1 = df[column].quantile(0.25)
            Q3 = df[column].quantile(0.75)

            IRQ = Q3 - Q1
            df_out = df[~((df[column] < (Q1 - 1.5 * IRQ)) | (df[column] > (Q3 + 1.5 * IRQ)))]

            return df_out

        owners = {'owner': 'blue', 'dealer': 'red'}

        for owner_type in owners:

            df = df_cars[(df_cars['owner_type'] == owner_type)]

            X = np.array(df['miles'].tolist())
            Y = np.array(df['price'].tolist())

            if len(Y) < 2:
                continue

            try:
                # popt, pcov = curve_fit(func, X, Y, [2000, 0, 4000])
                popt, pcov = curve_fit(func, X, Y)

                fig.add_trace(go.Scatter(x=X,
                                         y=func(X, *popt),
                                         mode='lines',
                                         hoverinfo='skip',
                                         name=owner_type,
                                         line=dict(color=owners[owner_type], width=2)
                                         ))

            except RuntimeError as e:
                logger.exception(e)

        return fig



