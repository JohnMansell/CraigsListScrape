import dash_core_components as dcc
import dash_html_components as html
import dash_bootstrap_components as dbc
from backend import *

# --- Initialize Functions
get_locations()
states = get_states()
cities = get_cities('CA')
make_options = get_make_options()

colors = {
    'background': '#111111',
    'text': '#7FDBFF',
    'price': '#5dad5c'
}

# --- Header
header = dbc.Row(html.H1('CraigsList Car Finder', style={'color': colors['text']}), justify="center")

# --- State
state_dropdown = dcc.Dropdown(id='slct_state',
                              options=states,
                              placeholder='STATE',
                              multi=False,
                              style={'width': '100%',
                                     'color': '#6c698a'}
                              )


# --- City
city_dropdown = dcc.Dropdown(id='slct_city',
                             options=cities,
                             placeholder='CITY',
                             multi=False,
                             style={'width': '100%',
                                    'margin-bottom': '30px',
                                    'color': '#6c698a'})

# --- Make
make_dropdown = dcc.Dropdown(id='make_dropdown',
                             placeholder='MAKE',
                             options=make_options,
                             style={'width': '100%',
                                    'color': '#6c698a'}
                             )

# --- Model
model_dropdown = dcc.RadioItems(id='model_ratio_items',
                                options=[],
                                labelStyle={'display': 'block'})

# --- Details Card
details_card = dbc.Card(
    [
        dbc.CardImg(src="",
                    top=True,
                    id='card_img'),
        dbc.CardBody(
            [
                html.H4("Card Title", id='card_title'),
                html.H5("Price", id='card_price', style={'color': colors['price']}),
                html.P("Card text", id='card_text', style={'whiteSpace': 'pre-wrap'}),
                html.Div(children=[], hidden=True, id='hidden_div')
            ])
    ], id='card',
    style={'width': '18rem'}

)

find_cars_button = dbc.Row(dbc.Button('Find Cars',
                              color='primary',
                              id='button_find_cars',
                              disabled=True,
                              outline=True,
                              size='lg',
                              ),
                           justify='center')
