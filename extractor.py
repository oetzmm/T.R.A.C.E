import gzip
from fitparse import FitFile
import math
import io


### Dates autorisées
mois = [9, 10, 11, 12]
annee = [2026]

def semicircles_to_degrees(semicircles):
    """Fonction de conversion des données "semicercles" vers classique (Lat/Long)"""
    if semicircles is None:
        return None
    return semicircles * (180.0 / (2**31))

## ----------------FONCTION D'ANALYSE DES FICHIERS FIT---------------

def analyser_fit(files_upload, center_co, n, tile_length, progress_bar, mode="multi"):
    """
    Prend une liste de fichiers uploadés via Streamlit et renvoie :
    - tiles_conquered : set des tuiles uniques (x, y)
    - total_coordinates : liste des traces valides
    - tile_counts : dictionnaire {(x, y): nb_passages} (1 passage max par activité)
    """
    tiles_conquered = set()
    tile_counts = {}
    total_coordinates = []
    geojson_data = {
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

    # Configuration des sports autorisés
    sports_autorises = [
        'running', 'walking', 'hiking', 'trail_running', 'mountaineering',
        'track_running', 'track_field', 'generic', '1', '11', '17'
    ]

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

        coordinates = []
        tuiles_fichier = set() # Un set par fichier => max 1 passage par case pour une même sortie
        sport_type = "Unknown"
        sport_date = None
        act_valid = True
        marque_montre = "Unknown"

        try:
            record_count = 0
            date_validated = False
            for message in fitfile.get_messages():
                # --- Détection de la marque ---
                if message.name == 'file_id':
                    val = message.get_value('manufacturer')
                    if val is not None:
                        marque_montre = str(val)

                # --- Intercepteur précoce ---
                elif message.name == 'sport':
                    val = message.get_value('sport') or message.get_value('sub_sport')
                    if val is not None:
                        sport_type = str(val)
                        if sport_type not in sports_autorises:
                            act_valid = False
                            break

                # --- Lecture d'en-tête (GARMIN/POLAR) ---
                elif message.name == 'session':
                    if sport_type == "Unknown":
                        val = message.get_value('sport') or message.get_value('sub_sport')
                        if val is not None:
                            sport_type = str(val)
                            if sport_type not in sports_autorises:
                                act_valid = False
                                break
                    if sport_date is None:
                        sport_date = message.get_value('start_time')

                # --- Lecture des points GPS (COROS et extraction) ---
                elif message.name == 'record':
                    if sport_date is None:
                        sport_date = message.get_value('timestamp')

                    # Validation Saison 2 : du 1er Novembre au 31 Décembre 2026
                    if mode == "multi" and sport_date is not None and not date_validated:
                        if (sport_date.month not in mois) or (sport_date.year not in annee):
                            act_valid = False
                            break
                        date_validated = True

                    if sport_type == "Unknown":
                        val = message.get_value('activity_type') or message.get_value('sport')
                        if val is not None:
                            sport_type = str(val)

                    if sport_type != "Unknown" and sport_type not in sports_autorises:
                        act_valid = False
                        break

                    record_count += 1
                    if record_count % 10 != 0:
                        continue

                    lat = semicircles_to_degrees(message.get_value('position_lat'))
                    lon = semicircles_to_degrees(message.get_value('position_long'))

                    if lat is not None and lon is not None:
                        coordinates.append([lon, lat])
                        if (min_lat <= lat <= max_lat) and (min_lon <= lon <= max_lon):
                            xtile = math.floor((lon - min_lon) / step_lon)
                            ytile = math.floor((lat - min_lat) / step_lat)
                            tuiles_fichier.add((xtile, ytile))
        except Exception:
            pass

        # Validation et sauvegarde finale
        if act_valid and (sport_type == "Unknown" or sport_type in sports_autorises) and len(coordinates) > 1 and len(tuiles_fichier) > 0:
            tiles_conquered.update(tuiles_fichier)

            # On incrémente de +1 chaque tuile traversée lors de CETTE sortie
            for tuile in tuiles_fichier:
                tile_counts[tuile] = tile_counts.get(tuile, 0) + 1

            track_color = [252, 76, 2] if mode == "multi" else [255, 87, 34]
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
            print(f"Trace OK ({mode}) : {file.name} - Sport: {sport_type} - Date: {sport_date} - Points: {len(coordinates)}")
        else:
            print(f"Trace IGNORÉE ({mode}) : {file.name} - Sport: {sport_type} - Date: {sport_date}")

    return tiles_conquered, total_coordinates, tile_counts