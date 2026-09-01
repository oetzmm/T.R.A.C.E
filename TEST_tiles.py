import pydeck as pdk
import json
import streamlit as st

# Lecture des données extraites dans le fichier "strava_traces.geojson"
with open("strava_TRACEs.geojson","r") as f:
    data = json.load(f)
with open("grid.geojson","r") as f:
    grid = json.load(f)

# Configuration du calque grille
layer_grid = pdk.Layer(
    "GeoJsonLayer",
    grid,
    pickable=True,
    stroked=True,
    filled=True,

    # Gestion du replissage des tuiles validées
    get_line_color = [255,255,255,30],
    get_fill_color = "properties.fill_color",
    
    # --- Épaisseur dynamique en PIXELS ---
    get_line_width=1,          # Épaisseur fixe à l'écran (3 pixels)
    line_width_min_pixels=1,   # Minimum absolu, pour qu'elle ne disparaisse pas
    line_width_max_pixels=10,  # Maximum absolu, pour de très gros zooms
)

print("Grid created")

# Configuration du calque traces
layer_traces = pdk.Layer(
    "GeoJsonLayer",
    data,
    pickable=True,
    stroked=True,
    filled=False,
    get_line_color="properties.color",
    
    # --- Épaisseur dynamique en PIXELS ---
    get_line_width=4,          # Épaisseur fixe à l'écran
    line_width_min_pixels=1,   # Minimum absolu
    line_width_max_pixels=10,  # Maximum absolu
)

# Paramétrage de la caméra initiale
view_state = pdk.ViewState(
    latitude=45.549763,
    longitude=-73.569735,
    zoom=12,
    min_zoom=1.5,
    max_zoom=20,

    pitch=0,           # <--- Inclinaison de la caméra (0 = vu de haut, 60 = très incliné)
    bearing=0,          # <--- Pivot de la carte
)


# 4. Assemblage final
r = pdk.Deck(
    layers=[layer_traces,layer_grid],
    initial_view_state=view_state,
    map_provider="carto",
    map_style="dark",
    tooltip=False)

# 6. Génération
r.to_html("T.R.A.C.E.html")
print("Génération réussie")