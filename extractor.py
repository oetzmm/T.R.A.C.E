import gzip
import io
import math
from fitparse import FitFile

# ==============================================================================
# RÈGLES D'EXTRACTION (SAISON 2)
# ==============================================================================
mois = {11, 12}
annee = {2026}

SPORTS_AUTORISES = {
    "running", "walking", "hiking", "trail_running", "mountaineering",
    "track_running", "track_field", "generic", "1", "11", "17",
}

gap_ech = 10  # Garde 1 point GPS sur 10 pour alléger la carte
KM_PAR_DEGRE_LAT = 111.32


# ==============================================================================
# FONCTIONS UTILITAIRES
# ==============================================================================
def semicircles_to_degrees(semicircles):
    """Convertit des coordonnées Garmin/FIT (semicercles) en degrés décimaux."""
    if semicircles is None:
        return None
    return semicircles * (180.0 / (2**31))


def _est_dans_saison(sport_date):
    """Vérifie qu'une date appartient bien à la période de la saison active."""
    return (
        sport_date is not None
        and sport_date.month in mois
        and sport_date.year in annee
    )


# ==============================================================================
# ANALYSE DES FICHIERS .FIT / .FIT.GZ
# ==============================================================================
def analyser_fit(files_upload, center_co, n, tile_length, progress_bar=None, mode="multi"):
    """
    Analyse une liste de fichiers .fit/.fit.gz uploadés via Streamlit.

    Retourne :
        - tiles_conquered   : set de toutes les tuiles (x, y) touchées
        - total_coordinates : liste des tracés GPS [[lon, lat], ...] valides
        - tile_counts       : dict {(x, y): nb_passages} (1 passage max par activité)
        - tile_first_dates  : dict {(x, y): date_iso_la_plus_ancienne}
        - activities_list   : liste d'activités détaillées (pour le filtre anti-doublon)
    """
    tiles_conquered = set()
    tile_counts = {}
    tile_first_dates = {}
    total_coordinates = []
    activities_list = []
    seen_activities = set()

    # Limites géographiques de l'arène
    center_lat, center_lon = center_co
    step_lat = tile_length / KM_PAR_DEGRE_LAT
    step_lon = tile_length / (KM_PAR_DEGRE_LAT * math.cos(math.radians(center_lat)))

    min_lat = center_lat - (n * step_lat * 0.5)
    max_lat = center_lat + (n * step_lat * 0.5)
    min_lon = center_lon - (n * step_lon * 0.5)
    max_lon = center_lon + (n * step_lon * 0.5)

    total_fichiers = len(files_upload)

    for i, file in enumerate(files_upload):
        if progress_bar:
            progress_bar.progress((i + 1) / total_fichiers)

        file.seek(0)
        if file.name.lower().endswith(".fit.gz"):
            fitfile = FitFile(io.BytesIO(gzip.decompress(file.read())))
        else:
            fitfile = FitFile(file)

        # Variables isolées pour ce fichier (sas de quarantaine)
        coordinates = []
        tuiles_fichier = set()
        sport_type = "Unknown"
        sport_date = None
        act_valid = True

        # --- Lecture séquentielle des messages FIT avec éjection précoce ---
        try:
            record_count = 0
            date_validated = False

            for message in fitfile.get_messages():
                msg_name = message.name

                # 1. Intercepteur précoce du type de sport
                if msg_name in ("sport", "session"):
                    if sport_type == "Unknown":
                        val = message.get_value("sport") or message.get_value("sub_sport")
                        if val is not None:
                            sport_type = str(val)
                            if sport_type not in SPORTS_AUTORISES:
                                act_valid = False
                                break

                    if msg_name == "session" and sport_date is None:
                        sport_date = message.get_value("start_time")

                # 2. Lecture des points GPS
                elif msg_name == "record":
                    if sport_date is None:
                        sport_date = message.get_value("timestamp")

                    # Validation précoce de la date en mode Multi
                    if mode == "multi" and sport_date is not None and not date_validated:
                        if not _est_dans_saison(sport_date):
                            act_valid = False
                            break
                        date_validated = True

                    # Vérification du sport si présent dans les records (ex: Coros)
                    if sport_type == "Unknown":
                        val = message.get_value("activity_type") or message.get_value("sport")
                        if val is not None:
                            sport_type = str(val)
                            if sport_type not in SPORTS_AUTORISES:
                                act_valid = False
                                break

                    # Sous-échantillonnage des points GPS
                    record_count += 1
                    if record_count % gap_ech != 0:
                        continue

                    lat = semicircles_to_degrees(message.get_value("position_lat"))
                    lon = semicircles_to_degrees(message.get_value("position_long"))

                    if lat is not None and lon is not None:
                        coordinates.append([lon, lat])
                        if (min_lat <= lat <= max_lat) and (min_lon <= lon <= max_lon):
                            xtile = math.floor((lon - min_lon) / step_lon)
                            ytile = math.floor((lat - min_lat) / step_lat)
                            tuiles_fichier.add((xtile, ytile))
        except Exception:
            # Fichier corrompu ou tronqué : on conserve ce qui a pu être validé proprement
            pass

        # --- Vérification finale (hors boucle GPS) ---
        if mode == "multi" and not _est_dans_saison(sport_date):
            act_valid = False

        sport_ok = (sport_type == "Unknown") or (sport_type in SPORTS_AUTORISES)

        if act_valid and sport_ok and len(coordinates) > 1 and len(tuiles_fichier) > 0:
            date_str = str(sport_date) if sport_date is not None else "9999-12-31"
            act_id = date_str if sport_date is not None else file.name

            # Filtre anti-doublon au sein du même lot uploadé
            if act_id in seen_activities:
                continue
            seen_activities.add(act_id)

            tiles_conquered.update(tuiles_fichier)
            total_coordinates.append(coordinates)

            # +1 passage exactement par case unique de cette sortie
            for tuile in tuiles_fichier:
                tile_counts[tuile] = tile_counts.get(tuile, 0) + 1
                if tuile not in tile_first_dates or date_str < tile_first_dates[tuile]:
                    tile_first_dates[tuile] = date_str

            activities_list.append({
                "id": act_id,
                "date": date_str,
                "tiles": list(tuiles_fichier),
                "coords": coordinates,
            })

    return tiles_conquered, total_coordinates, tile_counts, tile_first_dates, activities_list