import gzip
from fitparse import FitFile
import math
import io

def semicircles_to_degrees(semicircles):
    """Fonction de conversion des données "semicercles" vers classique (Lat/Long)"""
    if semicircles is None:
        return None
    return semicircles * (180.0 / (2**31))

## ----------------FONCTION D'ANALYSE DES FICHIERS FIT---------------

def analyser_fit(files_upload,center_co,n,tile_length,progress_bar,mode="multi"):
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
    step_lat = tile_length / 111.32  
    step_lon = tile_length / (111.32 * math.cos(math.radians(center_lat)))

    min_lat = center_lat - (n * step_lat * 0.5)
    max_lat = center_lat + (n * step_lat * 0.5)
    min_lon = center_lon - (n * step_lon * 0.5)
    max_lon = center_lon + (n * step_lon * 0.5)

    #1 Configuration des règles selon le mode
    sports_autorises = ['running', 'walking', 'hiking', 'trail_running', 'mountaineering', 'track_running', 'track_field', 'generic', '1', '11', '17']

    total_fichiers = len(files_upload)

    for i, file in enumerate(files_upload):
        if progress_bar:
            progress_bar.progress((i + 1) / total_fichiers)
        filename_lower = file.name.lower()
        file.seek(0)
        
        if filename_lower.endswith(".fit.gz"):
            fitfile = FitFile(io.BytesIO(gzip.decompress(file.read())))
            
        else:
            fitfile = FitFile(file)
        
        # Valeur par défaut si non trouvé
        coordinates = []
        sport_type = "Unknown"
        sport_date = None
        act_valid = True
        marque_montre = "Unknown"

        try:
            nb_cases_avant = len(tiles_conquered)
            record_count = 0
            date_validated = False
            for message in fitfile.get_messages():
                # --- Detection de la marque ---
                if message.name == 'file_id':
                    val = message.get_value('manufacturer')
                    if val is not None:
                        marque_montre = str(val) # ex: "1" (Garmin), "294" (Coros), "123" (Polar)

                # --- Lecture d'en-tête (GARMIN/POLAR) ---
                elif message.name == 'session':
                    if sport_type == "Unknown":
                        val = message.get_value('sport') or message.get_value('sub_sport')
                        if val is not None: sport_type = str(val)
                    if sport_date is None:
                        sport_date = message.get_value('start_time')

                # --- Lecture des points GPS (COROS et extraction) ---
                elif message.name == 'record':
                    if sport_date is None:
                        sport_date = message.get_value('timestamp')
                    if mode == "multi" and sport_date is not None and not date_validated:
                        if (sport_date.month not in [9,10]) or (sport_date.year != 2026):
                            act_valid = False
                            break
                        date_validated = True

                    if sport_type == "Unknown":
                        val = message.get_value('activity_type') or message.get_value('sport')
                        if val is not None: sport_type = str(val)

                    if sport_type != "Unknown" and sport_type not in sports_autorises:
                        act_valid = False
                        break

                    record_count += 1
                    if record_count % 10 != 0: # Filtrage des données
                        continue

                    lat = semicircles_to_degrees(message.get_value('position_lat'))
                    lon = semicircles_to_degrees(message.get_value('position_long'))

                    if lat is not None and lon is not None:
                        coordinates.append([lon, lat])
                        if (min_lat <= lat <= max_lat) and (min_lon <= lon <= max_lon):
                            xtile = math.floor((lon - min_lon) / step_lon)
                            ytile = math.floor((lat - min_lat) / step_lat)
                            tiles_conquered.add((xtile, ytile))
        except Exception as e:
            pass  # Ignorer les erreurs de lecture de fichier FIT

        # Validation et sauvegarde finale
        if act_valid and len(coordinates) > 1 and len(tiles_conquered) > nb_cases_avant:
            track_color = [252,76,2] if mode == "multi" else [255, 87, 34] # Orange classique en multi, nuance différente en solo
            
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
                    "date": str(sport_date),
                    "watch_brand": marque_montre,

                }
            }
            geojson_data["features"].append(feature)
            total_coordinates.append(coordinates)
            print(f"Trace OK ({mode}) : {file.name} - Sport: {sport_type} - Date: {sport_date} - Marque: {marque_montre} - Points: {len(coordinates)}")
        else:
            print(f"Trace IGNORÉE ({mode}) : {file.name} - Sport: {sport_type} - Date: {sport_date} - Marque: {marque_montre} - Points: {len(coordinates)}")
    return tiles_conquered, total_coordinates