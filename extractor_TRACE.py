import os
import gzip
import json
from fitparse import FitFile
import gpxpy
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
            
            # --- LE DÉTECTEUR DE FICHIER ILLISIBLE ---
            if b'.FIT' not in donnees_decompressees[:14]:
                print(f"\n🚨 ANOMALIE sur le fichier : {file.name}")
                print("Ce n'est pas un fichier FIT valide. Voici ses 50 premiers caractères :")
                print(donnees_decompressees[:50])
                print("--------------------------------------------------\n")
                continue # On ignore ce fichier et on passe au suivant
            
            fichier_virtuel = io.BytesIO(donnees_decompressees)
            fitfile = FitFile(fichier_virtuel)
            
        elif filename_lower.endswith(".fit"):
            fitfile = FitFile(file)
        coordinates = []
        sport_type = "Unknown" # Valeur par défaut si non trouvé
        sport_date = None # Valeur par défaut si non trouvé
        act_valid = True

        try:
            # 1. Traitement uniquement pour les extensions .FIT
            # Lecture dans les metadonnées de la session, séléction des activités valides
            for session in fitfile.get_messages('session'):
                for data in session:
                    if data.name == 'sport':
                        sport_type = data.value
                        if sport_type not in ['running','walking','hiking']:
                            print(f'Wrong sport : {data.value}')
                            act_valid = False
                    elif data.name == 'start_time':
                        sport_date = data.value
                        '''if sport_date.year != 2026 or sport_date.month not in [5,6,7,8] :
                            print(f'Date not in range : {sport_date.day}/{sport_date.month}/{sport_date.year}')
                            act_valid = False'''
                break

            # 3. Extraction des points d'enregistrement ("records")
            if not act_valid :
                continue

            for record in fitfile.get_messages('record'):
                lat = None
                lon = None
                alt = 0.0
                for data in record:
                    if data.name == 'position_lat':
                        lat = semicircles_to_degrees(data.value)
                    elif data.name == 'position_long':
                        lon = semicircles_to_degrees(data.value)
                    elif data.name in ('altitude', 'enhanced_altitude'):
                        alt = float(data.value)
                
                if lat is not None and lon is not None:
                    coordinates.append([lon, lat])

                    if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon:
                        xtile = math.floor((lon - min_lon)/step_lon)
                        ytile = math.floor((lat - min_lat)/step_lat)

                        tiles_conquered.add((xtile,ytile))

            # Si le fichier contient un parcours valide, on crée la ligne (Feature)
            if len(coordinates) > 1 and sport_date:

                track_color = [252, 76, 2] # ORANGE par défaut (track_color = [0, 153, 255] # BLEU CLAIR pour le vélo)

                feature = {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": coordinates
                    },
                    "properties": {
                        "nomFichier": file,
                        "sport": sport_type,
                        "color": track_color,
                        "date" : sport_date,
                    }
                }
                geojson_data["features"].append(feature)
                total_coordinates.append(coordinates)
                print(f"Track added : {file} | Sport : {sport_type} ({len(coordinates)} points) | Date : {sport_date}")
            else:
                # Activitées ignorées car pas de données GPS (ex: natation en piscine, tapis de course)
                print(f"Ignored (no GPS) : {file} | Sport : {sport_type} | Date : {sport_date}")

        except Exception as e:
            # Fichiers inutilisables ou corrompus
            print(f"Erreur lors de la lecture de {file.name} : {e}")
    return tiles_conquered, total_coordinates
