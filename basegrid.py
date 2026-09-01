import math


def gen_grid(center_co,tile_length,n_tiles,tiles=None):
    """ crée la grille de départ vide
    """
    if tiles is None:
        tiles = set()
    center_lat,center_lon = center_co
    # Calcul de la taille d'une tuile en degrés GPS
    step_lat = tile_length / 111.32  
    step_lon = tile_length / (111.32 * math.cos(math.radians(center_lat)))
    # On calcule les "murs" de l'arène
    min_lat = center_lat - (n_tiles * step_lat * 0.5)
    max_lat = center_lat + (n_tiles * step_lat * 0.5)
    min_lon = center_lon - (n_tiles * step_lon * 0.5)
    max_lon = center_lon + (n_tiles * step_lon * 0.5)
    # Création des n_tiles colonnes (x) et n_tiles lignes (y)
    grid_features = []
    for x in range(n_tiles):
        for y in range(n_tiles):        # Calcul des 4 coins du carré
            bl_lon = min_lon + (x * step_lon)
            bl_lat = min_lat + (y * step_lat)
            
            br_lon = min_lon + ((x + 1) * step_lon)
            br_lat = min_lat + (y * step_lat)
            
            tr_lon = min_lon + ((x + 1) * step_lon)
            tr_lat = min_lat + ((y + 1) * step_lat)
            
            tl_lon = min_lon + (x * step_lon)
            tl_lat = min_lat + ((y + 1) * step_lat)
            
            carre = { # Le format GeoJSON demande de fermer le polygone en répétant le 1er point
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [bl_lon, bl_lat], 
                        [br_lon, br_lat], 
                        [tr_lon, tr_lat], 
                        [tl_lon, tl_lat], 
                        [bl_lon, bl_lat]
                    ]]},
                "properties": {"case": f"X:{x} Y:{y}",
                        "fill_color": [128, 0, 128, 90] if (x,y) in tiles else [255,255,255,0]
                }}
            grid_features.append(carre)
    return grid_features
