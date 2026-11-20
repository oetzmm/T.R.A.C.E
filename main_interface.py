import streamlit as st
import pydeck as pdk
import math
import time
from extractor import analyser_fit
from basegrid import gen_grid
from pymongo import MongoClient

# --- CONNEXION À LA BASE DE DONNÉES ---
@st.cache_resource
def init_connection():
    return MongoClient(st.secrets["mongo"]["uri"])

client = init_connection()
db = client.trace_game
col_multi = db.joueurs_multi
col_perso = db.joueurs_perso

# --- FONCTION DE CALCUL DES POINTS PAR ÉQUIPE ---
def calculer_details_equipe(joueurs_equipe):
    """
    Calcule le score détaillé d'une équipe selon les règles :
    - 1er déblocage d'une case par l'équipe : 10 pts
    - 1er passage d'un coéquipier supplémentaire : 7 pts
    - 2e passage d'un même joueur sur une case : 5 pts
    - 3e passage et suivants d'un même joueur : 1 pt par passage
    """
    # Structure : { "x,y": [nb_passages_joueur1, nb_passages_joueur2, ...] }
    passages_par_case = {}

    for doc in joueurs_equipe:
        # Compatibilité avec d'anciennes données sans "tile_counts"
        if "tile_counts" in doc and doc["tile_counts"]:
            counts = doc["tile_counts"]
        else:
            counts = {f"{t[0]},{t[1]}": 1 for t in doc.get("tiles_conquered", [])}

        for case_key, nb_passages in counts.items():
            if nb_passages > 0:
                passages_par_case.setdefault(case_key, []).append(nb_passages)

    nb_cases_debloquees = len(passages_par_case)
    nb_nouveaux_coequipiers = 0
    nb_deuxiemes_passages = 0
    nb_passages_bonus = 0

    for liste_passages in passages_par_case.values():
        # Chaque joueur supplémentaire après le 1er rapporte 7 pts
        if len(liste_passages) > 1:
            nb_nouveaux_coequipiers += len(liste_passages) - 1

        # Passages répétés par un même joueur (5 pts au 2e, 1 pt à partir du 3e)
        for k in liste_passages:
            if k >= 2:
                nb_deuxiemes_passages += 1
            if k >= 3:
                nb_passages_bonus += (k - 2)

    pts_deblocage = nb_cases_debloquees * 10
    pts_coequipiers = nb_nouveaux_coequipiers * 7
    pts_deuxiemes = nb_deuxiemes_passages * 5
    pts_bonus = nb_passages_bonus * 1
    total_points = pts_deblocage + pts_coequipiers + pts_deuxiemes + pts_bonus

    return {
        "total_points": total_points,
        "cases_debloquees": nb_cases_debloquees,
        "nb_coequipiers": nb_nouveaux_coequipiers,
        "nb_deuxiemes": nb_deuxiemes_passages,
        "nb_bonus": nb_passages_bonus,
        "pts_deblocage": pts_deblocage,
        "pts_coequipiers": pts_coequipiers,
        "pts_deuxiemes": pts_deuxiemes,
        "pts_bonus": pts_bonus,
        "nb_joueurs": len(joueurs_equipe)
    }

# --- CONFIGURATION DE L'ARÈNE T.R.A.C.E ---
center_lat = 46.660988
center_lon = 0.362039
tile_length_m = 0.3 # km
n_m = 30
center_co_m = (center_lat, center_lon)

# Variables pour le mode solo
tile_length_p = 0.5 # km
n_p = 50

# --- INITIALISATION DE LA MÉMOIRE (SESSION STATE) ---
if "tuiles_m" not in st.session_state:
    st.session_state.tuiles_m = set()
if "tile_counts_m" not in st.session_state:
    st.session_state.tile_counts_m = {}
if "traces_m" not in st.session_state:
    st.session_state.traces_m = []

if "tuiles_p" not in st.session_state:
    st.session_state.tuiles_p = set()
if "traces_p" not in st.session_state:
    st.session_state.traces_p = []
if "center_p" not in st.session_state:
    st.session_state.center_p = (0.000, 0.000)
if "last_choix_arene" not in st.session_state:
    st.session_state.last_choix_arene = None

# --- CONFIGURATION DE LA PAGE ---
st.set_page_config(page_title="T.R.A.C.E. Viewer", page_icon="🏃", layout="wide")
st.title("T.R.A.C.E. - Territory Run and Amazing Challenge of Exploration", text_alignment="center")

onglet_actif = st.pills(
    "Navigation",
    options=["MULTIPLAYER MODE", "SOLO MODE", "LEADERBOARDS", "GAMERULES"],
    default="GAMERULES",
    required=True,
    label_visibility="collapsed",
    width="stretch"
)

# =========================================================================================
# ONGLET 1 : MODE COLLECTIF (MULTIPLAYER)
# =========================================================================================
if onglet_actif == "MULTIPLAYER MODE":
    st.subheader("🌍 Mode Collectif -- ENSMA -- Saison 2 (1er Novembre - 31 Décembre 2026)")
    st.markdown("### 1️⃣ Ajout de tes traces")
    st.markdown("Ajoute tes fichiers `.fit` ou `.fit.gz` pour faire marquer des points à ton équipe, puis sauvegarde ta contribution en bas de page.")
    st.info("⚠️ Seules les traces de course/marche passant dans l'arène entre le **1er novembre** et le **31 décembre 2026** sont prises en compte.")

    # Zone d'upload
    with st.form("upload_form_multi", border=False):
        external_files_m = st.file_uploader(
            "Ajoute tes fichiers .fit ici",
            type=["fit", "fit.gz"],
            accept_multiple_files=True,
            key="upload_multi"
        )
        bouton_analyse_m = st.form_submit_button("Analyser ces traces", key="analyse_multi")

    if external_files_m and bouton_analyse_m:
        barre_prog_m = st.progress(0)
        st.session_state.tuiles_m.clear()
        st.session_state.tile_counts_m.clear()
        st.session_state.traces_m.clear()

        with st.spinner("Analyse des traces en cours..."):
            tuiles_m, traces_m, tile_counts_m = analyser_fit(
                external_files_m, center_co_m, n_m, tile_length_m, barre_prog_m, mode="multi"
            )
            st.session_state.tuiles_m.update(tuiles_m)
            st.session_state.tile_counts_m.update(tile_counts_m)
            st.session_state.traces_m.extend(traces_m)

        barre_prog_m.empty()
        total_passages = sum(st.session_state.tile_counts_m.values())
        st.success(f"{len(st.session_state.traces_m)} activité(s) valide(s) analysée(s) : {len(st.session_state.tuiles_m)} cases touchées ({total_passages} passages au total).")

    layers_m = []
    features_m = []

    # Calque éphémère (traces pas encore sauvegardées)
    if st.session_state.traces_m:
        for trace in st.session_state.traces_m:
            if len(trace) > 1:
                features_m.append({
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": trace}
                })
        if len(features_m) > 0:
            layer_ephemere_m = pdk.Layer(
                "GeoJsonLayer",
                {"type": "FeatureCollection", "features": features_m},
                pickable=False,
                stroked=True,
                filled=False,
                get_line_color=[255, 255, 255],
                get_line_width=4,
                line_width_min_pixels=2,
                line_width_max_pixels=10,
            )
            layers_m.append(layer_ephemere_m)

    st.markdown(f"### 🗺️ Carte collective : {n_m}x{n_m} tuiles de {int(tile_length_m * 1000)} m de côté")
    st.markdown("""
    **Légende des territoires :**  
    🟦 **A1/A2 (Bleu)** | 🟥 **A3 (Rouge)** | 🟪 **Zone mixte (les 2 équipes)** | ⬜ **Tes nouvelles tuiles (non sauvegardées)**
    """)

    tous_les_joueurs = list(col_multi.find({}, {"_id": 0}))

    tuiles_eq1_map = set()
    tuiles_eq2_map = set()

    for j in tous_les_joueurs:
        if "tiles_conquered" in j:
            tuiles = [tuple(t) if isinstance(t, list) else t for t in j["tiles_conquered"]]
            if j.get("equipe") == "A1/A2":
                tuiles_eq1_map.update(tuiles)
            elif j.get("equipe") == "A3":
                tuiles_eq2_map.update(tuiles)

    # Affichage UNIQUEMENT par équipes
    st.markdown("#### 🛡️ Affichage des traces par équipe")
    c_eq1, c_eq2 = st.columns(2)
    with c_eq1:
        afficher_eq1 = st.checkbox("Afficher les traces A1/A2 🟦", value=False)
    with c_eq2:
        afficher_eq2 = st.checkbox("Afficher les traces A3 🟥", value=False)

    for team_name, is_checked, team_color in [
        ("A1/A2", afficher_eq1, [50, 150, 255]),
        ("A3", afficher_eq2, [255, 50, 50])
    ]:
        if is_checked:
            traces_equipe = []
            for j in tous_les_joueurs:
                if j.get("equipe") == team_name:
                    traces_equipe.extend(j.get("features", []))

            if traces_equipe:
                layer_equipe = pdk.Layer(
                    "GeoJsonLayer",
                    {"type": "FeatureCollection", "features": traces_equipe},
                    pickable=False,
                    stroked=True,
                    filled=False,
                    get_line_color=team_color,
                    get_line_width=4,
                    line_width_min_pixels=2,
                    line_width_max_pixels=10,
                )
                layers_m.append(layer_equipe)

    # Grille colorée par équipes
    grille_data_m = gen_grid(
        center_co_m,
        tile_length_m,
        n_m,
        tuiles_eq1=tuiles_eq1_map,
        tuiles_eq2=tuiles_eq2_map,
        tuiles_ephemeres=st.session_state.tuiles_m
    )
    if grille_data_m:
        layer_grille_m = pdk.Layer(
            "GeoJsonLayer",
            grille_data_m,
            pickable=False,
            stroked=True,
            filled=True,
            get_line_color=[255, 255, 255, 40],
            get_fill_color="properties.fill_color",
            get_line_width=1,
            line_width_min_pixels=1,
        )
        layers_m.insert(0, layer_grille_m)

    view_state_m = pdk.ViewState(
        latitude=center_lat, longitude=center_lon,
        zoom=10, min_zoom=1.5, max_zoom=20, pitch=0, bearing=0
    )
    r_m = pdk.Deck(layers=layers_m, initial_view_state=view_state_m, map_provider="carto", map_style="dark")
    st.pydeck_chart(r_m)

    # --- SAUVEGARDE DÉFINITIVE ---
    st.markdown("---")
    st.markdown("### 2️⃣ Enregistrer ma contribution")

    colnom, coleq = st.columns(2)
    with colnom:
        pseudo_m = st.text_input("Ton nom / pseudo (utilise toujours le même !) :", key="pseudo_multi")
    with coleq:
        equipe = st.selectbox("Ton équipe :", options=["A1/A2", "A3"], key="equipe_multi")

    if st.button("Sauvegarder pour mon équipe", key="sauvegarde_multi", type="primary"):
        pseudo_clean = pseudo_m.strip()
        if pseudo_clean and features_m:
            with st.spinner("Sauvegarde en cours..."):
                tuiles_tot_m = set(st.session_state.tuiles_m)
                traces_tot_m = features_m.copy()

                # Conversion des clés (x, y) en chaînes "x,y" pour MongoDB
                tile_counts_tot = {f"{x},{y}": count for (x, y), count in st.session_state.tile_counts_m.items()}

                anciennes_data_m = col_multi.find_one({"pseudo": pseudo_clean, "equipe": equipe}, {"_id": 0})

                if anciennes_data_m:
                    if "tiles_conquered" in anciennes_data_m:
                        anciennes_tuiles_m = [tuple(t) if isinstance(t, list) else t for t in anciennes_data_m["tiles_conquered"]]
                        tuiles_tot_m.update(anciennes_tuiles_m)

                    if "features" in anciennes_data_m:
                        traces_tot_m.extend(anciennes_data_m["features"])

                    # Fusion des compteurs de passages
                    anciens_counts = anciennes_data_m.get("tile_counts", {})
                    if not anciens_counts and "tiles_conquered" in anciennes_data_m:
                        anciens_counts = {f"{t[0]},{t[1]}": 1 for t in anciennes_data_m["tiles_conquered"]}

                    for k, v in anciens_counts.items():
                        tile_counts_tot[k] = tile_counts_tot.get(k, 0) + v

                geojson_final_m = {
                    "pseudo": pseudo_clean,
                    "equipe": equipe,
                    "type": "FeatureCollection",
                    "score": len(tuiles_tot_m),
                    "tiles_conquered": list(tuiles_tot_m),
                    "tile_counts": tile_counts_tot,
                    "features": traces_tot_m
                }

                col_multi.replace_one({"pseudo": pseudo_clean, "equipe": equipe}, geojson_final_m, upsert=True)

            st.success(f"Bravo {pseudo_clean} ! Tes traces ont bien été ajoutées à l'équipe **{equipe}**.")

            st.session_state.tuiles_m.clear()
            st.session_state.tile_counts_m.clear()
            st.session_state.traces_m.clear()

            time.sleep(2)
            st.rerun()
        else:
            st.warning("Merci d'entrer ton nom et d'analyser au moins une activité valide (Novembre/Décembre 2026 dans la zone) avant d'enregistrer.")

# =========================================================================================
# ONGLET 2 : LA CARTE PERSONNELLE (SOLO)
# =========================================================================================
elif onglet_actif == "SOLO MODE":
    st.subheader("🏠 Mode solo -- A domicile -- De tout temps")
    st.markdown("Ici, tu peux choisir l'arène de ton choix pour te comparer aux autres 'à domicile'.")

    col_gauche, col_droite = st.columns(2)

    with col_gauche:
        st.markdown("### 1️⃣ Définition de l'arène :")
        used_arenes = {}
        for doc in col_perso.find({"center": {"$exists": True}}, {"lieu": 1, "center": 1, "_id": 0}):
            if doc["lieu"] not in used_arenes:
                used_arenes[doc["lieu"]] = doc["center"]
        options_menu = ["Nouvelle arène"] + list(used_arenes.keys())
        choix_arene = st.selectbox("Choisis une arène existante ou crée-en une nouvelle :", options=options_menu, key="select_arene")

        if choix_arene == "Nouvelle arène":
            col1, col2 = st.columns(2)
            with col1:
                lat_perso = st.number_input("Latitude du centre", value=0.00000, format="%.6f", key="lat_p")
            with col2:
                lon_perso = st.number_input("Longitude du centre", value=0.00000, format="%.6f", key="lon_p")

            if st.button("Créer mon arène", type="primary"):
                st.session_state.center_p = (lat_perso, lon_perso)
                st.session_state.tuiles_p.clear()
                st.session_state.traces_p.clear()
                st.session_state.last_choix_arene = "Nouvelle arène"
        else:
            coords = tuple(used_arenes.get(choix_arene, (0.00000, 0.00000)))
            if st.session_state.last_choix_arene != choix_arene:
                st.session_state.center_p = coords
                st.session_state.tuiles_p.clear()
                st.session_state.traces_p.clear()
                st.session_state.last_choix_arene = choix_arene

            st.info(f"{choix_arene} (Centre : {coords[0]:.6f}, {coords[1]:.6f})")

        center_co_p = st.session_state.center_p

    with col_droite:
        st.markdown("### 2️⃣ Ajoute tes traces")
        with st.form("form_upload_solo", border=False):
            external_files_p = st.file_uploader(
                "Ajoute tes fichiers .fit ou .fit.gz",
                type=["fit", "fit.gz"],
                accept_multiple_files=True,
                key="upload_perso"
            )
            bouton_analyse_p = st.form_submit_button("Analyser ces fichiers")

        if external_files_p and bouton_analyse_p:
            barre_prog_p = st.progress(0)
            st.session_state.tuiles_p.clear()
            st.session_state.traces_p.clear()
            with st.spinner("Analyse des traces en cours..."):
                tuiles_p, traces_p, _ = analyser_fit(
                    external_files_p, center_co_p, n_p, tile_length_p, barre_prog_p, mode="solo"
                )
                st.session_state.tuiles_p.update(tuiles_p)
                st.session_state.traces_p.extend(traces_p)
                st.session_state.center_p = center_co_p

            barre_prog_p.empty()
            st.success(f"Traces ajoutées ! Score temporaire : {len(st.session_state.tuiles_p)} tuiles.")

    st.divider()
    st.markdown(f"### 🗺️ Carte solo : {n_p}x{n_p} tuiles de {int(tile_length_p * 1000)} m de côté")

    pseudos_dispo_p = []
    if choix_arene != "Nouvelle arène":
        for doc in col_perso.find({"lieu": choix_arene}, {"pseudo": 1}):
            pseudos_dispo_p.append(doc["pseudo"])

    option_par_defaut = "Traces temporaires"
    if pseudos_dispo_p:
        joueur_a_afficher = st.selectbox("Voir une performance enregistrée sur cette arène :", options=[option_par_defaut] + pseudos_dispo_p)
    else:
        joueur_a_afficher = option_par_defaut
        if choix_arene != "Nouvelle arène":
            st.info("Aucune performance enregistrée sur cette arène pour le moment.")

    layers_p = []
    colored_tiles_p = set(st.session_state.tuiles_p)
    features_p = []

    with st.spinner("Chargement de la carte..."):
        if joueur_a_afficher != option_par_defaut:
            data_joueur_p = col_perso.find_one({"pseudo": joueur_a_afficher, "lieu": choix_arene}, {"_id": 0})
            if data_joueur_p and data_joueur_p.get("features"):
                layer_joueur_p = pdk.Layer(
                    "GeoJsonLayer",
                    data_joueur_p,
                    pickable=False, stroked=True, filled=False,
                    get_line_color=[76, 175, 80],
                    get_line_width=4, line_width_min_pixels=2, line_width_max_pixels=10,
                )
                layers_p.append(layer_joueur_p)
                if "tiles_conquered" in data_joueur_p:
                    tuiles_joueur_p = [tuple(t) if isinstance(t, list) else t for t in data_joueur_p["tiles_conquered"]]
                    colored_tiles_p.update(tuiles_joueur_p)

        for trace in st.session_state.traces_p:
            if len(trace) > 1:
                features_p.append({
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": trace}
                })
        if len(features_p) > 0:
            layer_ephemere_p = pdk.Layer(
                "GeoJsonLayer",
                {"type": "FeatureCollection", "features": features_p},
                pickable=False, stroked=True, filled=False,
                get_line_color=[255, 87, 34],
                get_line_width=4, line_width_min_pixels=2, line_width_max_pixels=10,
            )
            layers_p.append(layer_ephemere_p)

        grille_data_p = gen_grid(st.session_state.center_p, tile_length_p, n_p, tuiles_solo=colored_tiles_p)
        if grille_data_p:
            layer_grille_p = pdk.Layer(
                "GeoJsonLayer",
                grille_data_p,
                pickable=False, stroked=True, filled=True,
                get_line_color=[255, 255, 255, 40],
                get_fill_color="properties.fill_color",
                get_line_width=1, line_width_min_pixels=1,
            )
            layers_p.insert(0, layer_grille_p)

        view_state_p = pdk.ViewState(
            latitude=st.session_state.center_p[0], longitude=st.session_state.center_p[1],
            zoom=10, min_zoom=1.5, max_zoom=20, pitch=0, bearing=0
        )
        r_p = pdk.Deck(layers=layers_p, initial_view_state=view_state_p, map_provider="carto", map_style="dark")
        st.pydeck_chart(r_p)

    st.markdown("---")
    st.markdown("### 3️⃣ Sauvegarde")
    c_nom, c_lieu = st.columns(2)
    with c_nom:
        pseudo_p = st.text_input("Nom:", key="pseudo_p")
    with c_lieu:
        if choix_arene == "Nouvelle arène":
            lieu_p = st.text_input("Nom de votre arène:", key="lieu_p")
        else:
            lieu_p = choix_arene
            st.info(f"Localisation : {lieu_p}")

    if st.button("Sauvegarder"):
        if pseudo_p and lieu_p and features_p:
            with st.spinner("Sauvegarde en cours..."):
                tuiles_tot_p = set(st.session_state.tuiles_p)
                traces_tot_p = features_p.copy()

                anciennes_data_p = col_perso.find_one({"pseudo": pseudo_p, "lieu": lieu_p}, {"_id": 0})
                if anciennes_data_p:
                    if "tiles_conquered" in anciennes_data_p:
                        anciennes_tuiles_p = [tuple(t) if isinstance(t, list) else t for t in anciennes_data_p["tiles_conquered"]]
                        tuiles_tot_p.update(anciennes_tuiles_p)
                    if "features" in anciennes_data_p:
                        traces_tot_p.extend(anciennes_data_p["features"])

                geojson_final_p = {
                    "pseudo": pseudo_p,
                    "lieu": lieu_p,
                    "center": st.session_state.center_p,
                    "type": "FeatureCollection",
                    "score": len(tuiles_tot_p),
                    "tiles_conquered": list(tuiles_tot_p),
                    "features": traces_tot_p
                }
                col_perso.replace_one({"pseudo": pseudo_p, "lieu": lieu_p}, geojson_final_p, upsert=True)

            st.success(f"Progression sauvegardée ! Score total de {pseudo_p} à {lieu_p} : {len(tuiles_tot_p)} tuiles.")
            st.session_state.tuiles_p.clear()
            st.session_state.traces_p.clear()
            st.session_state.last_choix_arene = lieu_p
            time.sleep(2)
            st.rerun()
        else:
            st.warning("Merci d'entrer un nom, un lieu et au moins une trace valide avant d'enregistrer.")

# =========================================================================================
# ONGLET 3 : LES CLASSEMENTS (LEADERBOARDS)
# =========================================================================================
elif onglet_actif == "LEADERBOARDS":
    st.header("🏆 Classements")

    col_m, col_p = st.columns(2)

    # --- CLASSEMENT 1 : COLLECTIF UNIQUEMENT (DÉTAIL DES POINTS PAR ÉQUIPE) ---
    with col_m:
        st.subheader("🌍 Mode Collectif -- Arène ENSMA -- Saison 2")
        tous_les_joueurs_m = list(col_multi.find({}, {"_id": 0}))

        joueurs_eq1 = [d for d in tous_les_joueurs_m if d.get("equipe") == "A1/A2"]
        joueurs_eq2 = [d for d in tous_les_joueurs_m if d.get("equipe") == "A3"]

        stats_eq1 = calculer_details_equipe(joueurs_eq1)
        stats_eq2 = calculer_details_equipe(joueurs_eq2)

        # Compteurs globaux en gros
        m1, m2 = st.columns(2)
        with m1:
            st.metric(
                label="🟦 Équipe A1/A2",
                value=f"{stats_eq1['total_points']} pts",
                delta=f"{stats_eq1['cases_debloquees']} cases ({100 * stats_eq1['cases_debloquees'] / (n_m**2):.1f}%)"
            )
        with m2:
            st.metric(
                label="🟥 Équipe A3",
                value=f"{stats_eq2['total_points']} pts",
                delta=f"{stats_eq2['cases_debloquees']} cases ({100 * stats_eq2['cases_debloquees'] / (n_m**2):.1f}%)"
            )

        st.divider()

        # Tableau récapitulatif détaillé des points de chaque équipe
        st.markdown("### 📊 Détail des points par équipe")
        tableau_detail = [
            {
                "Catégorie de points": "🚩 1ères conquêtes (10 pts / case)",
                "🟦 A1/A2": f"{stats_eq1['pts_deblocage']} pts ({stats_eq1['cases_debloquees']})",
                "🟥 A3": f"{stats_eq2['pts_deblocage']} pts ({stats_eq2['cases_debloquees']})"
            },
            {
                "Catégorie de points": "🤝 Nouveaux coéquipiers (7 pts)",
                "🟦 A1/A2": f"{stats_eq1['pts_coequipiers']} pts ({stats_eq1['nb_coequipiers']})",
                "🟥 A3": f"{stats_eq2['pts_coequipiers']} pts ({stats_eq2['nb_coequipiers']})"
            },
            {
                "Catégorie de points": "🔁 2èmes passages (5 pts)",
                "🟦 A1/A2": f"{stats_eq1['pts_deuxiemes']} pts ({stats_eq1['nb_deuxiemes']})",
                "🟥 A3": f"{stats_eq2['pts_deuxiemes']} pts ({stats_eq2['nb_deuxiemes']})"
            },
            {
                "Catégorie de points": "✨ Passages supplémentaires (1 pt)",
                "🟦 A1/A2": f"{stats_eq1['pts_bonus']} pts ({stats_eq1['nb_bonus']})",
                "🟥 A3": f"{stats_eq2['pts_bonus']} pts ({stats_eq2['nb_bonus']})"
            },
            {
                "Catégorie de points": "👥 Participants actifs",
                "🟦 A1/A2": f"{stats_eq1['nb_joueurs']}",
                "🟥 A3": f"{stats_eq2['nb_joueurs']}"
            },
            {
                "Catégorie de points": "🏆 TOTAL",
                "🟦 A1/A2": f"{stats_eq1['total_points']} pts",
                "🟥 A3": f"{stats_eq2['total_points']} pts"
            }
        ]
        st.dataframe(tableau_detail, use_container_width=True, hide_index=True)

        # Barre de rapport de force entre les deux équipes
        total_pts_global = stats_eq1["total_points"] + stats_eq2["total_points"]
        if total_pts_global > 0:
            part_eq1 = stats_eq1["total_points"] / total_pts_global
            st.progress(part_eq1, text=f"Part des points : A1/A2 ({part_eq1*100:.1f}%) vs A3 ({(1-part_eq1)*100:.1f}%)")
        else:
            st.info("Aucun point enregistré pour le moment sur la Saison 2.")

    # --- CLASSEMENT 2 : CHACUN CHEZ SOI (SOLO) ---
    with col_p:
        st.subheader("🏠 Mode solo -- Arène personnelle -- De tout temps")
        scores_p = []
        for doc in col_perso.find({}, {"pseudo": 1, "lieu": 1, "score": 1, "_id": 0}):
            score_p = doc.get("score", 0)
            pseudo_complet = f"{doc.get('pseudo', 'Inconnu')} ({doc.get('lieu', 'Inconnu')})"
            scores_p.append({"Joueur": pseudo_complet, "Score": score_p, "Pourcentage": round(100 * score_p / n_p**2, 2)})

        if scores_p:
            scores_p = sorted(scores_p, key=lambda x: x["Score"], reverse=True)
            st.dataframe(scores_p, use_container_width=True, hide_index=True)
            st.progress(min(scores_p[0]['Score'] / n_p**2, 1.0), text=f"Progression du leader : {100 * scores_p[0]['Score'] / n_p**2:.2f}%")
        else:
            st.info("Aucun score solo pour l'instant")

# =========================================================================================
# ONGLET 4 : LES RÈGLES DU JEU
# =========================================================================================
elif onglet_actif == "GAMERULES":
    st.subheader("Comment jouer à T.R.A.C.E. ?")

    st.markdown("""
    **T.R.A.C.E.** est un jeu collectif de conquête de territoire basé sur vos traces GPS réelles.
    L'arène autour de l'ENSMA est une grille de **9 km × 9 km**, découpée en cases de **300 mètres de côté**.

    ### ⚔️ Saison 2 : Le Choc des Équipes (**A1/A2** 🟦 vs **A3** 🟥)
    * **Période :** Du **1er Novembre au 31 Décembre 2026**.
    * **Sports autorisés :** Course à pied, trail et marche uniquement (laissez les vélos au garage !).
    * **Objectif :** Faire marquer le maximum de points à son équipe. L'équipe qui a le plus de points au 31 décembre remporte la saison !

    ### 🎯 Comment sont calculés les points ?
    Le comptage est **100 % indépendant pour chaque équipe** (ce que fait l'équipe adverse ne vous enlève aucun point). Chaque sortie valide passant dans une case compte pour **1 passage** :

    | Situation sur une case (pour ton équipe) | Points gagnés |
    | :--- | :---: |
    | 🚩 **Tu débloques une case vierge** pour ton équipe (1er passage de l'équipe) | **+10 pts** |
    | 🤝 **Tu découvres une case déjà débloquée par un coéquipier** (ton 1er passage perso) | **+7 pts** |
    | 🔁 **Tu repasses une 2ème fois** dans une case où tu es déjà allé(e) | **+5 pts** |
    | ✨ **Tu y repasses une 3ème fois, 4ème fois, etc.** | **+1 pt** par sortie |

    ### ⚙️ Comment participer ?
    1. Récupérez vos sorties en fichiers `.fit` ou `.fit.gz` depuis Strava, Garmin, Coros, Polar ou Suunto.
    2. Dans **MULTIPLAYER MODE**, uploadez vos fichiers et cliquez sur *Analyser ces traces*.
    3. Indiquez votre **pseudo** *(gardez toujours le même pour que votre score soit bien compté !)* et choisissez votre **équipe** (**A1/A2** ou **A3**), puis cliquez sur **Sauvegarder**.
    4. *(Bonus)* Un **Mode Solo** reste disponible pour créer votre propre arène chez vous, sans limite de date.

    ### ⚠️ Avertissement ⚠️
    #### **Ne vous mettez pas en danger pour débloquer une case, le créateur de ce jeu décline toute responsabilité.**
    """)