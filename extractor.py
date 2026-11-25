import gzip
from fitparse import FitFile
import math
import io


### Dates autorisées
mois = [11, 12]
annee = [2026]

def semicircles_to_degrees(semicircles):
    """Fonction de conversion des données "semicercles" vers classique (Lat/Long)"""
    if semicircles is None:
        return None
    return semicircles * (180.0 / (2**31))

## ----------------FONCTION D'ANALYSE DES FICHIERS FIT---------------

def analyser_fit(files_upload, center_co, n, tile_length, progress_bar, mode="multi"):
    tiles_conquered = set()
    tile_counts = {}
    tile_first_dates = {}
    total_coordinates = []
    activities_list = []      # Liste propre par activité (pour l'anti-doublon)
    seen_activities = set()   # Bloque les doublons au sein d'un même upload

    center_lat, center_lon = center_co
    step_lat = tile_length / 111.32
    step_lon = tile_length / (111.32 * math.cos(math.radians(center_lat)))

    min_lat = center_lat - (n * step_lat * 0.5)
    max_lat = center_lat + (n * step_lat * 0.5)
    min_lon = center_lon - (n * step_lon * 0.5)
    max_lon = center_lon + (n * step_lon * 0.5)

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
        tuiles_fichier = set() # 🚨 Garantit 1 seul passage max par case pour CE fichier
        sport_type = "Unknown"
        sport_date = None
        act_valid = True
        marque_montre = "Unknown"

        try:
            record_count = 0
            date_validated = False
            for message in fitfile.get_messages():
                if message.name == 'file_id':
                    val = message.get_value('manufacturer')
                    if val is not None:
                        marque_montre = str(val)

                elif message.name == 'sport':
                    val = message.get_value('sport') or message.get_value('sub_sport')
                    if val is not None:
                        sport_type = str(val)
                        if sport_type not in sports_autorises:
                            act_valid = False
                            break

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

                elif message.name == 'record':
                    if sport_date is None:
                        sport_date = message.get_value('timestamp')
                    if mode == "multi" and sport_date is not None and not date_validated:
                        if (sport_date.month not in [11, 12]) or (sport_date.year != 2026):
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
                            tuiles_fichier.add((xtile, ytile)) # UNIQUEMENT dans le set ici !
        except Exception:
            pass

        # --- VALIDATION EN DEHORS DE LA BOUCLE DES POINTS GPS ---
        if act_valid and (sport_type == "Unknown" or sport_type in sports_autorises) and len(coordinates) > 1 and len(tuiles_fichier) > 0:
            date_str = str(sport_date) if sport_date is not None else "9999-12-31"
            act_id = date_str if sport_date is not None else file.name

            # On ignore si cette même sortie est en double dans l'upload
            if act_id in seen_activities:
                continue
            seen_activities.add(act_id)

            tiles_conquered.update(tuiles_fichier)
            total_coordinates.append(coordinates)

            # +1 exactement par tuile unique de CETTE sortie
            for tuile in tuiles_fichier:
                tile_counts[tuile] = tile_counts.get(tuile, 0) + 1
                if tuile not in tile_first_dates or date_str < tile_first_dates[tuile]:
                    tile_first_dates[tuile] = date_str

            activities_list.append({
                "id": act_id,
                "date": date_str,
                "tiles": list(tuiles_fichier),
                "coords": coordinates
            })

    return tiles_conquered, total_coordinates, tile_counts, tile_first_dates, activities_list