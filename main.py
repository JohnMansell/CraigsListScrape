import json

import dash
import dash_core_components as dcc
import dash_html_components as html
from dash.dependencies import Input, Output, State
import plotly.graph_objs as go
import plotly.express as px
import dash_bootstrap_components as dbc

from backend import *
from layout_objects import *
import numpy as np

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.CYBORG])





# ----------------------------------------------------
#       App Layout
# ----------------------------------------------------

app.layout = html.Div([

    header,

    html.Br(),

    dbc.Row([

        # --- Selection Column :: Location, Make, Model
        dbc.Col([

            # --- Row 1 :: Text
            html.H5('Location'),

            # --- State
            state_dropdown,

            # --- City
            city_dropdown,

            # --- Make Model
            html.H5('Make / Model'),

            # --- Make
            make_dropdown,

            # --- Model
            model_dropdown

        ],
            width={'size': 2,
                   'offset': 1}
        ),

        # --- Graph
        dbc.Spinner(dbc.Col(dcc.Graph(id='live-graph', animate=True)),
                    color='primary',
                    type='border',
                    fullscreen=False,
                    size='lg'),

        # --- Details
        details_card,

    ]),

    # --- Find Cars
    dbc.Row(find_cars_button, justify='center')

])


# ----------------------------------------------------
#           Call Backs
# ----------------------------------------------------

@app.callback(
    dash.dependencies.Output('slct_city', 'options'),
    [dash.dependencies.Input('slct_state', 'value')]
)
def update_city_dropdown(state):
    return get_cities(state)


@app.callback(Output('model_ratio_items', 'options'),
              Input('make_dropdown', 'value'))
def update_make_radio_items(make):
    model_options = get_model_options(make)
    return model_options


@app.callback([Output('button_find_cars', 'disabled'),
               Output('button_find_cars', 'outline')],
              [Input('model_ratio_items', 'value')],
              [State('slct_city', 'value'),
               State('slct_state', 'value')])
def make_button_clickable(model, city, state):
    return [False, False]

    # if None in [model, city, state]:
    #     return [True, True]
    #
    # else:
    #     return [False, False]

@app.callback(
    [Output('card_title', 'children'),
     Output('card_text', 'children')],
    [Input('live-graph', 'hoverData')]
)
def display_hover_data(hoverData):

    data = hoverData['points'][0]

    title = data['hovertext']
    miles = data['x']
    price = data['y']
    attributes = data['customdata'][2]
    details = [f'{key}: {attributes[key]} \n' for key in sorted(attributes.keys())]

    return [title, details]


@app.callback([
    Output('live-graph', 'figure')],
    [Input('button_find_cars', 'n_clicks')],
    [State('slct_state', 'value'),
     State('slct_city', 'value'),
     State('make_dropdown', 'value'),
     State('model_ratio_items', 'value')]
)
def on_click(n_clicks, state, city, make, model):

    if None in [city, state]:
        state = 'CA'
        city = 'Orange County'
        make = 'Honda'
        model = 'Civic'

    # --- Owner
    url = build_url(state, city, make, model, 'owner')
    car_elems = get_car_elems(url)

    df_cars = get_all_cars(car_elems, 'owner')
    df_cars = df_cars.sort_values(by=['miles'])

    fig = (px.scatter(df_cars,
                      x='miles',
                      y='price',
                      custom_data=['url', 'image', 'attributes'],
                      hover_name='title'))

    # --- Dealer
    # url = build_url(state, city, make, model, 'dealer')
    # car_elems = get_car_elems(url)
    #
    # df_cars = get_all_cars(car_elems, 'dealer')
    # fig.add_trace(px.scatter(df_cars, x='miles', y='price', custom_data=['url', 'image'], hover_name='title'))


    max_x = max(df_cars.miles) + 5000
    max_y = max(df_cars.price) + 1000

    fig.update_layout(go.Layout(xaxis=dict(range=[0, max_x]),
                                yaxis=dict(range=[0, max_y]),
                                height=700, width=1200))
    fig = solve_curves(fig, df_cars)

    return [fig]


# ----------------------------------------------------
#           Run
# ----------------------------------------------------

if __name__ == '__main__':
    app.run_server(debug=True)
