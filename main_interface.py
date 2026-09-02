import streamlit as st
import pandas as pd
import json
import pydeck as pdk
import math
import time
from extractor_TRACE import analyser_fit
from extractor_solo import analyser_fit_solo
from basegrid import gen_grid

from pymongo import MongoClient

# --- CONNEXION À LA BASE DE DONNÉES ---
@st.cache_resource
def init_connection():
    # Va lire le fichier .streamlit/secrets.toml
    return MongoClient(st.secrets["mongo"]["uri"])

client = init_connection()
db = client.trace_game # Nom de ta base de données globale
col_multi = db.joueurs_multi # Ta "boîte" pour les joueurs multijoueur
col_perso = db.joueurs_perso # Ta "boîte" pour les joueurs perso

# --- CONFIGURATION DE L'ARÈNE T.R.A.C.E (50km x 50km) ---
center_lat = 46.660988 ##MTL 45.549763
center_lon = 0.362039 ##MTL -73.569735
center_co_m = (center_lat,center_lon)
tile_length = 0.4 # km
n = 50
# Calcul de la taille d'une tuile en degrés GPS
step_lat = tile_length / 111.32  
step_lon = tile_length / (111.32 * math.cos(math.radians(center_lat)))

# On calcule les "murs" de l'arène

min_lat = center_lat - (n * step_lat * 0.5)
max_lat = center_lat + (n * step_lat * 0.5)
min_lon = center_lon - (n * step_lon * 0.5)
max_lon = center_lon + (n * step_lon * 0.5)


# --- INITIALISATION DE LA MÉMOIRE (SESSION STATE) ---

# Variables MULTI
if "tuiles_m" not in st.session_state:
    st.session_state.tuiles_m = set()
if "traces_m" not in st.session_state:
    st.session_state.traces_m = []

# Variables PERSO
if "tuiles_p" not in st.session_state:
    st.session_state.tuiles_p = set()
if "traces_p" not in st.session_state:
    st.session_state.traces_p = []
if "center_p" not in st.session_state:
    st.session_state.center_p = None

# --- CONFIGURATION DE LA PAGE ---
st.set_page_config(page_title="T.R.A.C.E. Viewer", page_icon="🏃", layout="wide")

st.title("T.R.A.C.E. - Territory Run and Amazing Challenge of Exploration", text_alignment="center")

# --- CRÉATION DU MENU (Remplacement des onglets) ---
# Injection du style CSS pour personnaliser les st.pills
st.markdown(
    """
    <style>
    /* Couleur des pastilles lorsqu'elles sont sélectionnées (actives) */
    div[data-testid="stPills"] button[aria-selected="true"] {
        background-color: #fc4c02 !important;
        color: white !important;
    }
    
    /* Couleur des pastilles au survol de la souris */
    div[data-testid="stPills"] button:hover {
        background-color: #f0f2f6 !important;
        color: black !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)
onglet_actif = st.pills(
    "Navigation",
    options = ["MULTIPLAYER MODE", "SOLO MODE", "LEADERBOARDS", "GAMERULES"],
    default="GAMERULES", # L'onglet par défaut au chargement
    width="stretch",
    label_visibility="collapsed",
    )

# ==========================================
# ONGLET 1 : LA CARTE INTERACTIVE (MULTI)
# ==========================================
if onglet_actif == "MULTIPLAYER MODE":
    st.subheader("🏠 Carte multijoueur - ENSMA")
    st.markdown("### 1️⃣ Ajoute tes traces")
    st.info("Tu peux ajouter tes fichiers .fit en plusieurs fois. Ils s'accumuleront sur la carte de façon temporaire.")
    
    # Zone d'upload
    external_files_m = st.file_uploader(
            "Ajoute tes fichiers .fit ici", 
            type=["fit","fit.gz"], 
            accept_multiple_files=True,
            key="upload_multi"
        )
        
    if external_files_m:
        if st.button("Analyser ces fichiers", key="analyse_multi"):
            barre_prog_m = st.progress(0)
            with st.spinner("Analyse des traces en cours..."):
                tuiles_m, traces_m = analyser_fit(external_files_m, center_co_m, n, tile_length, barre_prog_m)

                # L'ASTUCE ANTI-16MB : On ne garde qu'un point GPS sur 10
                traces_m_allegees = [trace[::10] for trace in traces_m]

                st.session_state.tuiles_m.update(tuiles_m)
                st.session_state.traces_m.extend(traces_m_allegees)

            barre_prog_m.empty()
            st.success(f"Traces ajoutées ! Score temporaire : {len(st.session_state.tuiles_m)} tuiles.")
            
    layers_m = []
    colored_tiles_m = set()
    with st.spinner("Chargement de la carte multijoueur en cours..."):
        # Calque 1 : Traces éphémères du joueur (bleu)
        if st.session_state.traces_m:
            colored_tiles_m.update(st.session_state.tuiles_m)
            features_m = []
            for i in st.session_state.traces_m:
                if len(i) > 1:
                    features_m.append({
                        "type": "Feature",
                        "geometry": {"type": "LineString", "coordinates": i}
                    })
            geojson_m = {"type":"FeatureCollection", "features":features_m}
            layer_ephemere_m = pdk.Layer(
                "GeoJsonLayer",
                geojson_m,
                pickable=False,
                stroked=True,
                filled=False,
                get_line_color=[0, 191, 255], 
                get_line_width=4,          
                line_width_min_pixels=2,   
                line_width_max_pixels=10,  
            )
            layers_m.append(layer_ephemere_m)

        st.markdown("### Affichage carte multijoueur")
        pseudo_dispo_m = []
        for joueur in col_multi.find({}, {"pseudo": 1}): 
            pseudo_dispo_m.append(joueur["pseudo"])

        palette = [[255, 87, 34], [76, 175, 80], [156, 39, 176], [255, 193, 7], [233, 30, 99]]

        if pseudo_dispo_m:
            colonnes_m = st.columns(len(pseudo_dispo_m))

            for i, pseudo_m in enumerate(pseudo_dispo_m):
                color_m = palette[i % len(palette)]
                with colonnes_m[i]:
                    afficher_joueur_m = st.checkbox(f"{pseudo_m}", value=True)

                if afficher_joueur_m:
                    # On cherche le document unique où le pseudo correspond, sans le champ _id
                    data_joueur_m = col_multi.find_one({"pseudo": pseudo_m}, {"_id": 0})

                    layer_joueur_m = pdk.Layer(
                        "GeoJsonLayer",
                        data_joueur_m,
                        pickable=False,
                        stroked=True,
                        filled=False,
                        get_line_color=color_m,
                        get_line_width=4,
                        line_width_min_pixels=2,
                        line_width_max_pixels=10,
                        id=f"layer_{pseudo_m}"
                        )
                    layers_m.append(layer_joueur_m)

                    if "tiles_conquered" in data_joueur_m:
                        tuiles_joueur_m = [tuple(t) if isinstance(t,list) else t for t in data_joueur_m["tiles_conquered"]]
                        colored_tiles_m.update(tuiles_joueur_m)

        grille_data_m = gen_grid(center_co_m, tile_length, n, colored_tiles_m)
        
        # Calque 2 : la grille colorée selon les tuiles conquises
        if grille_data_m:
            layer_grille_m = pdk.Layer(
                "GeoJsonLayer",
                grille_data_m,
                pickable=False,
                stroked=True,
                filled=True,
                get_line_color=[255,255,255,40],
                get_fill_color="properties.fill_color",
                get_line_width=1,
                line_width_min_pixels=1,
            )
            layers_m.insert(0, layer_grille_m)

        # AFFICHAGE
        view_state_m = pdk.ViewState(latitude=center_lat, longitude=center_lon, zoom=10, min_zoom=1.5, max_zoom=20, pitch=0, bearing=0)
        r_m = pdk.Deck(layers=layers_m, initial_view_state=view_state_m, map_provider="carto", map_style="dark")
        st.pydeck_chart(r_m)

    # --- SAUVEGARDE DÉFINITIVE ---
    st.markdown("---")
    st.markdown("### 2️⃣ Sauvegarde ton score")

    pseudo_m = st.text_input("Entrer un pseudo:", key='pseudo_multi')
    
    if st.button("Sauvegarder", key='sauvegarde_multi'):
        if pseudo_m and features_m:
            with st.spinner("Sauvegarde en cours..."):
                tuiles_tot_m = set(st.session_state.tuiles_m)
                traces_tot_m = features_m.copy()

                # On cherche l'historique du joueur dans la BDD (remplace os.path.exists)
                anciennes_data_m = col_multi.find_one({"pseudo": pseudo_m}, {"_id": 0})
                
                if anciennes_data_m:
                    if "tiles_conquered" in anciennes_data_m:
                        anciennes_tuiles_m = [tuple(t) if isinstance(t,list) else t for t in anciennes_data_m["tiles_conquered"]]
                        tuiles_tot_m.update(anciennes_tuiles_m)
                        
                    if "features" in anciennes_data_m:
                        traces_tot_m.extend(anciennes_data_m["features"])
                
                geojson_final_m = {
                    "pseudo": pseudo_m, # Indispensable pour retrouver le joueur plus tard
                    "type": "FeatureCollection",
                    "score": len(tuiles_tot_m),
                    "tiles_conquered": list(tuiles_tot_m),
                    "features": traces_tot_m
                }

                # Sauvegarde cloud
                col_multi.replace_one({"pseudo": pseudo_m}, geojson_final_m, upsert=True)       
            st.success(f"Progression sauvegardée ! Score total de {pseudo_m} : {len(tuiles_tot_m)} tuiles.")
            
            st.session_state.tuiles_m.clear()
            st.session_state.traces_m.clear()
            
            time.sleep(2)
            st.rerun()
        else:
            st.warning("Merci d'analyser vos fichiers et d'entrer un pseudo avant d'enregistrer.")

# ==========================================
# ONGLET 2 : LA CARTE PERSONNELLE (PERSO)
# ==========================================
elif onglet_actif == "SOLO MODE":
    st.subheader("🏠 Carte personnelle - Mode solo")
    st.markdown("Ici tu peux choisir l'arène de ton choix pour te comparer aux autres 'à domicile'.")

    # 1. Saisie des coordonnées
    st.markdown("### 1️⃣ Définis le centre de ton arène :")
    
    col1, col2 = st.columns(2)
    with col1:
        lat_perso = st.number_input("Latitude du centre", value=0.0000, format="%.6f", key="lat_p")
    with col2:
        lon_perso = st.number_input("Longitude du centre", value=0.0000, format="%.6f", key="lon_p")

    center_co_p = (lat_perso, lon_perso)
    
    # 2. Upload spécifique
    external_files_p = st.file_uploader(
            "Ajoute tes fichiers .fit",
            type=["fit","fit.gz"],
            accept_multiple_files=True,
            key="upload_perso")
    
    if external_files_p:
        if st.button("Analyser ces fichiers", key='analyse_perso'):
            barre_prog_p = st.progress(0)
            with st.spinner("Analyse des traces en cours..."):
                tuiles_p, traces_p = analyser_fit_solo(external_files_p, center_co_p, n, tile_length, barre_prog_p)

                # L'ASTUCE ANTI-16MB : On ne garde qu'un point GPS sur 10
                traces_p_allegees = [trace[::10] for trace in traces_p]

                st.session_state.tuiles_p.update(tuiles_p)
                st.session_state.traces_p.extend(traces_p_allegees)
                st.session_state.center_p = center_co_p

            barre_prog_p.empty()
            st.success(f"Traces ajoutées ! Score temporaire : {len(st.session_state.tuiles_p)} tuiles.")
            
    layers_p = []
    colored_tiles_p = set()
    
    # Calque 1 : Traces éphémères du joueur (Orange)
    if st.session_state.traces_p and st.session_state.center_p:
        colored_tiles_p.update(st.session_state.tuiles_p)
        features_p = []
        for i in st.session_state.traces_p:
            if len(i) > 1:
                features_p.append({
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": i}
                })
        geojson_p = {"type":"FeatureCollection", "features":features_p}
        layer_ephemere_p = pdk.Layer(
            "GeoJsonLayer",
            geojson_p,
            pickable=False,
            stroked=True,
            filled=False,
            get_line_color=[255, 87, 34], # Orange
            get_line_width=4,          
            line_width_min_pixels=2,   
            line_width_max_pixels=10,  
        )
        layers_p.append(layer_ephemere_p)

        grille_data_p = gen_grid(st.session_state.center_p, tile_length, n, colored_tiles_p)
        
        # Calque 2 : la grille colorée selon les tuiles conquises
        if grille_data_p:
            layer_grille_p = pdk.Layer(
                "GeoJsonLayer",
                grille_data_p,
                pickable=False,
                stroked=True,
                filled=True,
                get_line_color=[255,255,255,40],
                get_fill_color="properties.fill_color",
                get_line_width=1,
                line_width_min_pixels=1,
            )
            layers_p.insert(0, layer_grille_p)

        # Paramétrage de la caméra initiale sur les coordonnées perso
        view_state_p = pdk.ViewState(latitude=st.session_state.center_p[0], longitude=st.session_state.center_p[1], zoom=10, min_zoom=1.5, max_zoom=20, pitch=0, bearing=0)
        r_p = pdk.Deck(layers=layers_p, initial_view_state=view_state_p, map_provider="carto", map_style="dark")
        st.pydeck_chart(r_p)

    # --- SAUVEGARDE DÉFINITIVE (PERSO) ---
    st.markdown("---")
    st.markdown("### Sauvegarder mon score")
    
    pseudo_p = st.text_input("Entrer un pseudo:", key='pseudo_p')
    lieu_p = st.text_input("Localisation (ex: Paris, Lyon...)", key='lieu_p')
    
    with st.form("sauvegarde_perso"):
        if st.form_submit_button("Sauvegarde ta progression"):
            if pseudo_p and lieu_p and features_p:
                with st.spinner("Sauvegarde en cours..."):
                    tuiles_tot_p = set(st.session_state.tuiles_p)
                    traces_tot_p = features_p.copy()

                    # On cherche dans la BDD avec le pseudo ET le lieu
                    anciennes_data_p = col_perso.find_one({"pseudo": pseudo_p, "lieu": lieu_p}, {"_id": 0})

                    if anciennes_data_p:
                        if "tiles_conquered" in anciennes_data_p:
                            anciennes_tuiles_p = [tuple(t) if isinstance(t,list) else t for t in anciennes_data_p["tiles_conquered"]]
                            tuiles_tot_p.update(anciennes_tuiles_p)
                            
                        if "features" in anciennes_data_p:
                            traces_tot_p.extend(anciennes_data_p["features"])
                    
                    geojson_final_p = {
                        "pseudo": pseudo_p, # Obligatoire pour MongoDB
                        "lieu": lieu_p,     # Obligatoire pour différencier les arènes
                        "type": "FeatureCollection",
                        "score": len(tuiles_tot_p),
                        "tiles_conquered": list(tuiles_tot_p),
                        "features": traces_tot_p
                    }
                    
                    # Remplacement/Création en cloud
                    col_perso.replace_one({"pseudo": pseudo_p, "lieu": lieu_p}, geojson_final_p, upsert=True)

                st.success(f"Progression sauvegardée ! Score total de {pseudo_p} à {lieu_p} : {len(tuiles_tot_p)} tuiles.")
                
                st.session_state.tuiles_p.clear()
                st.session_state.traces_p.clear()
                
                time.sleep(2)
                st.rerun()
                
            else:
                st.warning("Merci d'analyser vos fichiers et d'entrer pseudo + localisation avant d'enregistrer.")
  
# ==========================================
# ONGLET 3 : LE TABLEAU DES SCORES
# ==========================================
elif onglet_actif == "LEADERBOARDS":
    st.header("🏆 Les Classements")
    
    col_m, col_p = st.columns(2)
    
    # --- CLASSEMENT 1 : ARÈNE OFFICIELLE ---
    with col_m:
        st.subheader("🌍 Mode multijoueur")
        scores_m = []
        # On ne récupère que le pseudo et le score pour aller très vite
        for doc in col_multi.find({}, {"pseudo": 1, "score": 1, "_id": 0}):
            scores_m.append({"Joueur": doc["pseudo"], "Score": doc.get("score", 0)})
        if scores_m:
            scores_m = sorted(scores_m, key=lambda x: x["Score"], reverse=True)
            st.dataframe(scores_m, use_container_width=True, hide_index=True)
            st.progress(scores_m[0]["Score"]/(n/tile_length)**2, text=f"Progression du leader: {100*scores_m[0]["Score"]/(n/tile_length)**2}%")
        else:
            st.info("Aucun score multi pour l'instant")

    # --- CLASSEMENT 2 : CHACUN CHEZ SOI ---
    with col_p:
        st.subheader("🏠 Mode solo")
        scores_p = []

        for doc in col_perso.find({},{"pseudo":1,"lieu":1,"score":1,"_id":0}):
            score_p = doc.get("score",0)
            pseudo_complet = f"{doc.get('pseudo','Inconnu')}({doc.get('lieu','Inconnu')})"
            scores_p.append({"Joueur":pseudo_complet,"Score":score_p,"Pourcentage":100*score_p/(n/tile_length)**2})

        if scores_p:
            scores_p = sorted(scores_p, key=lambda x: x["Score"], reverse=True)
            st.dataframe(scores_p, use_container_width=True, hide_index=True)
            st.progress(scores_p[0]["Score"]/(n/tile_length)**2, text=f"Progression du leader: {100*scores_p[0]["Score"]/(n/tile_length)**2:.2f}%")
        else:
            st.info("Aucun score solo pour l'instant")


# ==========================================
# ONGLET 4 : LES RÈGLES DU JEU
# ==========================================
elif onglet_actif == "GAMERULES":
    st.subheader("Comment jouer à T.R.A.C.E. ?")
    
    st.markdown("""
    **T.R.A.C.E.** est un jeu de conquête de territoire basé sur vos traces GPS réelles. 
    L'arène est une immense grille de **50 km par 50 km**, découpée en cases carrée de 400 mètres de côté.

    ### 📜 Règles :
    1. **Le sport :** Seules la course à pied et la marche sont autorisées. Laissez les vélos au garage ! (ou payez moi et je développe la même appli en version cycliste)
    2. **La période :** La saison multijoueur actuelle se déroule sur le premier semestre **du 1er septembre 26 au 31 janvier 27**.
    3. **La zone :** Les traces qui ne débloquent aucune case de l'arène ne sont pas considérées pour alléger l'affichage et la mémoire utilisée.
    4. **La capture :** Il suffit que votre trace GPS traverse une case pour que celle-ci soit capturée.
    5. **Pas de double-points :** Repasser dans une case que vous avez déjà conquise ne rapporte aucun point supplémentaire. L'objectif est l'**EXPLORATION**.

    ### ⚙️ Comment faire :
    1. Allez sur strava ou tout logiciel de gestion de montre GPS (garmin, suunto, coros)
    2. Téléchargez vos activités en fichiers .fit ou .fit.gz (une par une ou toutes à la fois c'est vous qui voyez)
    3. Uploadez ces fichiers et participez à la compétition: en multijoueur à l'ENSMA ou en solo chez vous!

    ### ⚠️ Avertissement :
    ## Ne vous mettez pas en danger pour débloquer une case, le créateur de ce jeu décline toute responsabilité.""")