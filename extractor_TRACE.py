import gzip
from fitparse import FitFile
import math
import io

STRAVA_DATA = "C:/Users/mateo/Documents/Strava viewer/## T.R.A.C.E/TRACE_DATABASE/MANU/activities"
TRACE_OUTPUT = "strava_TRACEs.geojson"

def semicircles_to_degrees(semicircles):
    """Fonction de conversion des données "semicercles" vers classique (Lat/Long)"""
    if semicircles is None:
        return None
    return semicircles * (180.0 / (2**31))

## ----------------FONCTION D'ANALYSE PRINCIPALE---------------

def analyser_fit(files_upload,center_co,n,tile_length,progress_bar):
    """
    Prend une liste de fichiers uploadés via Streamlit et renvoie les tuiles et les traces.
    """
    tiles_conquered = set()
    total_coordinates = []
    geojson_data = {                # Structure de base du GeoJSON
    "type": "FeatureCollection",
    "features": []
    }

    center_lat, center_lon = center_co
    # Calcul de la taille d'une tuile (500m) en degrés GPS
    step_lat = tile_length / 111.32  
    step_lon = tile_length / (111.32 * math.cos(math.radians(center_lat)))

    # On calcule les "murs" de l'arène (25 km de chaque côté = 50 tuiles)
    min_lat = center_lat - (n * step_lat * 0.5)
    max_lat = center_lat + (n * step_lat * 0.5)
    min_lon = center_lon - (n * step_lon * 0.5)
    max_lon = center_lon + (n * step_lon * 0.5)

    # --- EXTRACTION DES FICHIERS .FIT DE STRAVA ---
    print("Extraction started...")

    total_fichiers = len(files_upload)

    for i, file in enumerate(files_upload):
        if progress_bar:
            progress_bar.progress((i + 1) / total_fichiers)
        filename_lower = file.name.lower()
        file.seek(0)
        
        if filename_lower.endswith(".fit.gz"):
            donnees_brutes = file.read()
            donnees_decompressees = gzip.decompress(donnees_brutes)
            fichier_virtuel = io.BytesIO(donnees_decompressees)
            fitfile = FitFile(fichier_virtuel)
            
        elif filename_lower.endswith(".fit"):
            fitfile = FitFile(file)
        coordinates = []
        sport_type = "Unknown" # Valeur par défaut si non trouvé
        sport_date = None # Valeur par défaut si non trouvé
        act_valid = True

        try:
            nb_cases_avant = len(tiles_conquered)
            record_count = 0
            date_validated = False
            
            # On lit TOUS les messages un par un
            for message in fitfile.get_messages():
                
                # --- 1. LECTURE DE L'EN-TÊTE (Idéal pour Garmin et Polar) ---
                if message.name == 'session':
                    if sport_type == "Unknown":
                        val = message.get_value('sport') or message.get_value('sub_sport')
                        if val is not None:
                            sport_type = str(val)
                            
                    if sport_date is None:
                        sport_date = message.get_value('start_time')
                        
                # --- 2. LECTURE DES POINTS GPS (Idéal pour Coros) ---
                elif message.name == 'record':
                    
                    # Fallback date : si absente de l'en-tête
                    if sport_date is None:
                        sport_date = message.get_value('timestamp')
                        
                    # Validation UNIQUE de la date pour le mode Multi
                    if sport_date is not None and not date_validated:
                        if (sport_date.month not in [9,10]) or (sport_date.year != 2026):
                            print(f'Date hors délai : {sport_date}')
                            act_valid = False
                            break
                        date_validated = True

                    # Fallback sport : si absent de l'en-tête
                    if sport_type == "Unknown":
                        val = message.get_value('activity_type') or message.get_value('sport')
                        if val is not None:
                            sport_type = str(val)

                    # Vérification du sport
                    if sport_type != "Unknown" and sport_type not in ["running", "hiking", "walking", "trail_running", "1"]:
                        print(f"Sport invalide : {sport_type}")
                        act_valid = False
                        break

                    # Sous-échantillonnage (1 point sur 10)
                    record_count += 1
                    if record_count % 10 != 0:
                        continue
                        
                    lat_val = message.get_value('position_lat')
                    lon_val = message.get_value('position_long')

                    if lat_val is not None and lon_val is not None:
                        lat = semicircles_to_degrees(lat_val)
                        lon = semicircles_to_degrees(lon_val)
                        
                        coordinates.append([lon, lat])
                        
                        if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon:
                            xtile = math.floor((lon - min_lon)/step_lon)
                            ytile = math.floor((lat - min_lat)/step_lat)
                            tiles_conquered.add((xtile,ytile))

        except Exception as e:
            # Si le fichier plante au milieu (typique Coros sur ses champs propriétaires),
            # le code atterrit ici, ignore le crash, et passe directement à la sauvegarde finale.
            pass

        # N'oublie pas : ce bloc doit bien être EN DEHORS du try/except !
        if act_valid and len(coordinates) > 1 and (len(tiles_conquered) - nb_cases_avant != 0):
            track_color = [252, 76, 2] # ORANGE

            feature = {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": coordinates
                },
                "properties": {
                    "nomFichier": file.name,
                    "sport": sport_type,
                    "color": track_color,
                    "date" : str(sport_date),
                }
            }
            geojson_data["features"].append(feature)
            total_coordinates.append(coordinates)
            print(f"Track added : {file.name} | Sport : {sport_type} ({len(coordinates)} points)")
