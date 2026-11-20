import math

def gen_grid(center_co, tile_length, n_tiles, tuiles_eq1=None, tuiles_eq2=None, tuiles_ephemeres=None, tuiles_solo=None):
    """
    Génère la grille GeoJSON :
    - Mode Multi : couleurs par équipe (Bleu, Rouge, Violet si mixte, Blanc si non sauvegardé)
    - Mode Solo : couleur violette pour les tuiles conquises
    """
    if tuiles_eq1 is None:
        tuiles_eq1 = set()
    if tuiles_eq2 is None:
        tuiles_eq2 = set()
    if tuiles_ephemeres is None:
        tuiles_ephemeres = set()
    if tuiles_solo is None:
        tuiles_solo = set()

    center_lat, center_lon = center_co
    step_lat = tile_length / 111.32
    step_lon = tile_length / (111.32 * math.cos(math.radians(center_lat)))

    min_lat = center_lat - (n_tiles * step_lat * 0.5)
    min_lon = center_lon - (n_tiles * step_lon * 0.5)

    grid_features = []
    for x in range(n_tiles):
        for y in range(n_tiles):
            lon1 = min_lon + x * step_lon
            lat1 = min_lat + y * step_lat
            lon2 = lon1 + step_lon
            lat2 = lat1 + step_lat

            coord = (x, y)

            # Mode Solo
            if tuiles_solo:
                color = [128, 0, 128, 90] if coord in tuiles_solo else [0, 0, 0, 0]
            # Mode Collectif (Multi)
            else:
                is_eq1 = coord in tuiles_eq1
                is_eq2 = coord in tuiles_eq2
                is_eph = coord in tuiles_ephemeres

                if is_eq1 and is_eq2:
                    color = [150, 50, 200, 100]  # 🟣 Violet (Les deux équipes y sont passées)
                elif is_eq1:
                    color = [0, 150, 255, 100]   # 🔵 Bleu (Uniquement A1/A2)
                elif is_eq2:
                    color = [255, 50, 50, 100]   # 🔴 Rouge (Uniquement A3)
                elif is_eph:
                    color = [255, 255, 255, 125] # ⚪ Blanc (Nouvelles tuiles non sauvegardées)
                else:
                    color = [0, 0, 0, 0]         # Transparent (Vide)

            carre = {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [lon1, lat1],
                        [lon2, lat1],
                        [lon2, lat2],
                        [lon1, lat2],
                        [lon1, lat1]
                    ]]
                },
                "properties": {
                    "case": f"X:{x} Y:{y}",
                    "fill_color": color
                }
            }
            grid_features.append(carre)

    return {"type": "FeatureCollection", "features": grid_features}