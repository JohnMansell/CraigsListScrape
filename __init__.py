import locale

locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')
import dash
from dash.dependencies import Input, Output, State
import plotly.express as px

from layout_objects import *
import webbrowser

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.SUPERHERO], suppress_callback_exceptions=False)

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
            width={'size': 1,
                   'offset': 1}
        ),

        # --- Graph
        dbc.Spinner(dbc.Col(
            [
                dcc.Graph(id='live-graph', animate=True, hoverData=None),
                find_cars_button
            ], align='center'),
            color='primary',
            type='border',
            fullscreen=False,
            size='lg',
            show_initially=False),

        # --- Details
        details_card,

    ]),

    # --- Find Cars
    html.H1(children=["Who Awesome"], hidden=True, id='hidden_div')

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
    # if None in [model, city, state]:
    #     return [True, True]
    #
    # else:
    #     return [False, False]
    return [False, False]


@app.callback(
    [Output('card_title', 'children'),
     Output('card_price', 'children'),
     Output('card_text', 'children'),
     Output('card_img', 'src')],
    [Input('live-graph', 'hoverData')]
)
def display_hover_data(hoverData):
    if hoverData is None:
        return ["", "", "", ""]

    data = hoverData['points'][0]
    title = data['hovertext']
    dolars, cents = locale.currency(data['y'], grouping=True).split('.')
    attributes = data['customdata'][2]
    details = [f'{key}: {attributes[key]} \n' for key in sorted(attributes.keys())]

    img_src = f'{data["customdata"][1]}'
    img = app.get_asset_url(img_src)

    return [title, dolars, details, img]


# --- Live Graph : On Click
app.clientside_callback(
    """
    function(clickData) {
    
        if (clickData == null)
            { return " " }
    
        var url = clickData['points'][0]['customdata'][0];
        window.open(url);
        return " ";
    }
    """,
    Output('hidden_div', 'children'),
    Input('live-graph', 'clickData')
)


@app.callback([
    Output('live-graph', 'figure')],
    [Input('button_find_cars', 'n_clicks')],
    [State('slct_state', 'value'),
     State('slct_city', 'value'),
     State('make_dropdown', 'value'),
     State('model_ratio_items', 'value')]
)
def on_click(n_clicks, state, city, make, model):

    if n_clicks is None:
        fig = go.Figure()
        fig.update_layout(height=900, width=1500)
        return [fig]

    if None in [city, state]:
        state = 'CA'
        city = 'Orange County'
        make = 'Honda'
        model = 'Civic'

    # --- Owner
    url = build_url(state, city, make, model, 'owner')
    car_elems = get_car_elems(url)
    df_owner = get_all_cars(car_elems, 'owner')

    # --- Dealer
    url = build_url(state, city, make, model, 'dealer')
    car_elems = get_car_elems(url)
    df_dealer = get_all_cars(car_elems, 'dealer')

    # --- Data Frame
    df_cars = pd.concat([df_owner, df_dealer])
    df_cars = df_cars.sort_values(by=['miles'])

    # --- Figure
    fig = px.scatter(df_cars,
                     x='miles',
                     y='price',
                     custom_data=['url', 'image', 'attributes'],
                     color='owner_type',
                     hover_name='title',
                     color_discrete_map={'owner': 'blue', 'dealer': 'red'}
                     )

    max_x = max(df_cars.miles) + 5000
    max_y = max(df_cars.price) + 1000

    fig.update_layout(go.Layout(xaxis=dict(range=[0, max_x]),
                                yaxis=dict(range=[0, max_y]),
                                height=900, width=1500))

    fig = solve_curves(fig, df_cars)

    return [fig]


# ----------------------------------------------------
#           Run
# ----------------------------------------------------
server = app.server


if __name__ == '__main__':
    app.run_server(debug=True)
