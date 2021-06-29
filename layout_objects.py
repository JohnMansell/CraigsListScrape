import dash
import dash_core_components as dcc
import dash_html_components as html
import dash_bootstrap_components as dbc

from backend import *

# # --- Initialize Functions
get_locations()
states = get_states()
cities = get_cities('CA')
make_options = get_make_options()

colors = {
    'background': '#111111',
    'text': '#7FDBFF',
    'price': '#5dad5c',
    'blue': '#0f75bc',
    'yellow': ' #f9c445'
}

FONT = 'product_sans'

app = dash.Dash(__name__)

# --- Header
header = dbc.Row(
    dbc.Col(html.Img(src=app.get_asset_url('background/CCF_logo.png'),
                     style={'width': '12vw', 'padding-top': '60px'}),
            width={'size': 2, 'offset': 1}))

# --- Title Text
title_text = html.Div([
    dcc.Markdown("# Instantly pinpoint the **best car deals** on craigslist.",
                 style={'color': colors['blue']}),
    dcc.Markdown("#### You pick the car; our graph shows you the optimum price-to-mileage "
                 "ratio of every option in your area.",
                 style={'color': 'black', 'padding-top': '30px', 'padding-bottom': '120px'})
], style={'margin-top': '120px'})

# --- State
state_dropdown = dcc.Dropdown(id='slct_state',
                              options=states,
                              placeholder='state',
                              multi=False,
                              className='custom_dropdown',
                              clearable=False)

# --- City
city_dropdown = dcc.Dropdown(id='slct_city',
                             options=cities,
                             placeholder='city',
                             multi=False,
                             className='custom_dropdown',
                             clearable=False)

# --- Location Row
location_row = dbc.Row([
    dbc.Col(html.P("LOCATION", style={'color': 'black'}), width={'size': 3}),
    dbc.Col(state_dropdown, width={'size': 4}),
    dbc.Col(city_dropdown, width={'size': 5}),
], style={'width': '75%'})

# --- Make
make_dropdown = dcc.Dropdown(id='make_dropdown',
                             placeholder='make',
                             options=make_options,
                             className='custom_dropdown',
                             clearable=False
                             )

# --- Model
model_dropdown = dcc.Dropdown(id='model_ratio_items',
                              options=[],
                              className='custom_dropdown',
                              placeholder='model',
                              clearable=False)

make_model_row = dbc.Row(
    [
        dbc.Col(html.P("CAR", style={'color': 'black'}), width={'size': 3}),
        dbc.Col(make_dropdown, width={'size': 4}),
        dbc.Col(model_dropdown, width={'size': 5})
    ], style={'width': '75%', 'padding-top': '5px'}, justify='start'
)

# --- Details Card
details_card = dbc.Card(
    [
        dbc.CardBody(
            [
                html.H3("", id='card_title', style={'color': '#0f75bc', 'font-weight': 'bold'}),
                html.H4("", id='card_price', style={'color': 'black', 'font-weight': 'bold'}),
                html.P("", id='card_text', style={'whiteSpace': 'pre-wrap', 'color': 'black'}),
            ])
    ], id='card',
    style={'background-color': 'transparent', 'border': 'none'}
)

details_image = html.Img(src=None, id='card_img', style={'width': '20rem'})

find_cars_button = dbc.Row(dbc.Button('SEARCH',
                                      id='button_find_cars',
                                      disabled=False,
                                      className='search_button'
                                      ))

background_style_1 = {'background-image': 'url(assets/background/background_1.jpg)',
                      'background-size': 'auto',
                      'background-position': 'center',
                      'height': '100vh',
                      'width': '100vw',
                      'background-repeat': 'no-repeat'}

background_style_2 = {'background-image': 'url(assets/background/background_2.jpg)',
                      'background-size': 'auto',
                      'background-position': 'center',
                      'height': '100vh',
                      'width': '100vw',
                      'background-repeat': 'no-repeat'}
