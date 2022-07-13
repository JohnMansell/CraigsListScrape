import locale

locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')
import dash
from dash.dependencies import Input, Output, State
from dash.exceptions import PreventUpdate
import plotly.express as px

from layout_objects import *
import webbrowser

app = dash.Dash(__name__,
                external_stylesheets=[dbc.themes.SUPERHERO],
                suppress_callback_exceptions=False,
                prevent_initial_callbacks=True)

# ----------------------------------------------------
#       App Layout
# ----------------------------------------------------

app.layout = html.Div(id='main_div', children=[

    header,
    html.Br(),

    dbc.Row([

        # --- Selection Column :: Location, Make, Model
        dbc.Col([

            title_text,

            location_row,

            make_model_row,

            find_cars_button

        ],
            width={'size': 3,
                   'offset': 1},
        ),

        # --- Graph
        dbc.Col(
            dcc.Loading(
                dbc.Collapse(
                    dcc.Graph(id='live-graph', style={'height': '60vh'}), id='collapse'), color='#f9c445', fullscreen=True),
        width={'size': 7, 'offset': 0})

    ], justify='start'),

    # --- Details Card
    dbc.Row(
        [
            dbc.Col(details_image, align='start', width={'size': 2, 'offset': 5}),
            dbc.Col(details_card, width=3)
        ], style={'align-items': 'start', 'justify-content': 'start', 'padding-top': '15px'},
        className="g-0"),

    # --- Hidden Div
    html.H1(children=["Who's Awesome"], hidden=True, id='hidden_div')

],
  style={'background-image': 'url(assets/background/background_1.jpg)',
         'background-size': 'cover',
         'background-position': 'center',
         'height': '100vh',
         'width': '100vw',
         'background-repeat': 'no-repeat'})


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

    img_src = f'car_images/{data["customdata"][1]}'

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
    Output('live-graph', 'figure'),
    Output('collapse', 'is_open'),
    Output('main_div', 'style')],
    [Input('button_find_cars', 'n_clicks')],
    [State('slct_state', 'value'),
     State('slct_city', 'value'),
     State('make_dropdown', 'value'),
     State('model_ratio_items', 'value')]
)
def on_click(n_clicks, state, city, make, model):
    if n_clicks is None:
        raise PreventUpdate

    if None in [state, city, make, model]:
        state = "CA"
        city = 'Orange County'
        make = 'honda'
        model = 'civic'
        # raise PreventUpdate

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
                                plot_bgcolor='#DEF0FF',
                                autosize=True,
                                font=dict(size=22),
                                legend=dict(bgcolor='#f9c445', x=0.8, y=0.9, font=dict(size=22))))


    fig = solve_curves(fig, df_cars)

    return [fig, True, background_style_2]


# ----------------------------------------------------
#           Run
# ----------------------------------------------------
server = app.server

if __name__ == '__main__':
    app.run_server(debug=True)
