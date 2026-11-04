import math

def gen_grid(center_co,tile_length, n_tiles, tuiles_eq1, tuiles_eq2, tuiles_ephemeres=None):
    """Génère la grille avec des couleurs spécifiques par équipes pour le mode Multi."""
    if tuiles_ephemeres is None:
        tuiles_ephemeres = set()

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
            lon1 = min_lon + x * step_lon
            lat1 = min_lat + y * step_lat
            lon2 = lon1 + step_lon
            lat2 = lat1 + step_lat
            
            coord = (x, y)
            is_eq1 = coord in tuiles_eq1
            is_eq2 = coord in tuiles_eq2
            is_eph = coord in tuiles_ephemeres
            
            # --- LOGIQUE DES COULEURS DE TUILES (RÈGLE STRICTE) ---
            if is_eq1 and is_eq2:
                color = [150, 50, 200, 100]  # 🟣 Violet (Les deux équipes y sont passées)
            elif is_eq1:
                color = [0, 150, 255, 100]   # 🔵 Bleu (Appartient UNIQUEMENT à l'Équipe 1)
            elif is_eq2:
                color = [255, 50, 50, 100]   # 🔴 Rouge (Appartient UNIQUEMENT à l'Équipe 2)
            elif is_eph:
                color = [255, 255, 255, 125] # ⚪ Blanc (Territoire vierge fraîchement uploadé, pas encore sauvegardé)
            else:
                color = [0, 0, 0, 0]         # Transparent (Vide)
            
            carre = { # Le format GeoJSON demande de fermer le polygone en répétant le 1er point
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [lon1, lat1], 
                        [lon2, lat1], 
                        [lon2, lat2], 
                        [lon1, lat2], 
                        [lon1, lat1]
                    ]]},
                "properties": {"case": f"X:{x} Y:{y}",
                        "fill_color": [128, 0, 128, 90] if (x,y) in tuiles_ephemeres else [255,255,255,0]
                }}
            grid_features.append(carre)
    return {"type": "FeatureCollection", "features": grid_features}
