import math

# ==============================================================================
# CONFIGURATION DES COULEURS (Format RGBA : Rouge, Vert, Bleu, Opacité 0-255)
# ==============================================================================
COULEURS = {
    "vide":      [0, 0, 0, 0],         # Transparent
    "eq1":       [0, 150, 255, 100],   # Bleu (A1/A2 uniquement)
    "eq2":       [255, 50, 50, 100],   # Rouge (A3 uniquement)
    "mixte":     [150, 50, 200, 100],  # Violet (Les deux équipes)
    "ephemere":  [255, 255, 255, 125], # Blanc (Trace analysée non sauvegardée)
    "solo":      [128, 0, 128, 90],    # Violet (Mode solo)
}

KM_PAR_DEGRE_LAT = 111.32


# ==============================================================================
# GÉNÉRATION DE LA GRILLE GEOJSON
# ==============================================================================
def gen_grid(
    center_co,
    tile_length,
    n_tiles,
    tuiles_eq1=None,
    tuiles_eq2=None,
    tuiles_ephemeres=None,
    tuiles_solo=None,
):
    """
    Génère un FeatureCollection GeoJSON représentant une grille carrée (n_tiles x n_tiles).
    - Si `tuiles_solo` est fourni (même vide) : applique la coloration du mode Solo.
    - Sinon : applique la coloration par équipes du mode Collectif.
    """
    tuiles_eq1 = tuiles_eq1 or set()
    tuiles_eq2 = tuiles_eq2 or set()
    tuiles_ephemeres = tuiles_ephemeres or set()

    # Calcul des dimensions en degrés GPS et du coin sud-ouest de l'arène
    center_lat, center_lon = center_co
    step_lat = tile_length / KM_PAR_DEGRE_LAT
    step_lon = tile_length / (KM_PAR_DEGRE_LAT * math.cos(math.radians(center_lat)))

    min_lat = center_lat - (n_tiles * step_lat * 0.5)
    min_lon = center_lon - (n_tiles * step_lon * 0.5)

    grid_features = []

    for x in range(n_tiles):
        lon1 = min_lon + x * step_lon
        lon2 = lon1 + step_lon

        for y in range(n_tiles):
            lat1 = min_lat + y * step_lat
            lat2 = lat1 + step_lat
            coord = (x, y)

            # Attribution de la couleur selon le mode actif
            if tuiles_solo is not None:
                color = COULEURS["solo"] if coord in tuiles_solo else COULEURS["vide"]
            else:
                is_eq1 = coord in tuiles_eq1
                is_eq2 = coord in tuiles_eq2
                is_eph = coord in tuiles_ephemeres

                if is_eq1 and is_eq2:
                    color = COULEURS["mixte"]
                elif is_eq1:
                    color = COULEURS["eq1"]
                elif is_eq2:
                    color = COULEURS["eq2"]
                elif is_eph:
                    color = COULEURS["ephemere"]
                else:
                    color = COULEURS["vide"]

            # Construction du polygone fermé au format GeoJSON
            grid_features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [lon1, lat1],
                        [lon2, lat1],
                        [lon2, lat2],
                        [lon1, lat2],
                        [lon1, lat1],
                    ]],
                },
                "properties": {
                    "case": f"X:{x} Y:{y}",
                    "fill_color": color,
                },
            })

    return {"type": "FeatureCollection", "features": grid_features}