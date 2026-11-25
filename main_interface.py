import time
import pydeck as pdk
import streamlit as st
from pymongo import MongoClient

from basegrid import gen_grid
from extractor import analyser_fit

# ==============================================================================
# 1. CONFIGURATION DE LA PAGE & CONSTANTES DU JEU
# ==============================================================================
st.set_page_config(page_title="T.R.A.C.E. Viewer", page_icon="🏃", layout="wide")

# Paramètres de l'arène Multijoueur (ENSMA - Saison 2)
CENTER_LAT_M = 46.660988
CENTER_LON_M = 0.362039
CENTER_CO_M = (CENTER_LAT_M, CENTER_LON_M)
TILE_LENGTH_M = 0.3  # km
N_M = 30             # Grille 30x30 (900 cases)

# Paramètres de l'arène Solo
TILE_LENGTH_P = 0.5  # km
N_P = 50             # Grille 50x50 (2500 cases)

# Équipes et couleurs de tracés
EQUIPES = {
    "A1/A2": {"label": "🟦 Équipe A1/A2", "couleur_trace": [50, 150, 255]},
    "A3":    {"label": "🟥 Équipe A3",    "couleur_trace": [255, 50, 50]},
}

# Barème de points (Saison 2)
PTS_DEBLOCAGE = 10
PTS_COEQUIPIER = 7
PTS_DEUXIEME_PASSAGE = 5
PTS_PASSAGE_SUPP = 1


# ==============================================================================
# 2. CONNEXION MONGODB & MÉMOIRE DE SESSION
# ==============================================================================
@st.cache_resource
def init_connection():
    return MongoClient(st.secrets["mongo"]["uri"])


client = init_connection()
db = client.trace_game
col_multi = db.joueurs_multi
col_perso = db.joueurs_perso


def init_session_state():
    """Initialise les variables temporaires de session si elles n'existent pas."""
    defaults = {
        "tuiles_m": set(),
        "traces_m": [],
        "activities_m": [],
        "tuiles_p": set(),
        "traces_p": [],
        "center_p": (0.0, 0.0),
        "last_choix_arene": None,
    }
    for key, default_val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_val


init_session_state()


# ==============================================================================
# 3. FONCTIONS MÉTIER & AFFICHAGE RÉUTILISABLES
# ==============================================================================
def calculer_details_equipe(joueurs_equipe):
    """
    Calcule le score total, le détail par catégorie et la contribution
    individuelle de chaque joueur au sein d'une équipe.
    """
    # Structure : { "x,y": [(date_1er_passage, pseudo, nb_passages), ...] }
    passages_par_case = {}
    points_par_joueur = {}
    nb_activites = 0

    for doc in joueurs_equipe:
        pseudo = doc.get("pseudo", "Inconnu")
        points_par_joueur.setdefault(pseudo, 0)

        # Compatibilité avec d'anciennes données sans "tile_counts"
        nb_activites += max(
            len(doc.get("activity_ids", [])),
            len(doc.get("features", [])))

        counts = doc.get("tile_counts") or {
            f"{t[0]},{t[1]}": 1 for t in doc.get("tiles_conquered", [])
        }
        first_dates = doc.get("tile_first_dates", {})

        for case_key, nb_passages in counts.items():
            if nb_passages > 0:
                date_passage = first_dates.get(case_key, "9999-12-31")
                passages_par_case.setdefault(case_key, []).append(
                    (date_passage, pseudo, nb_passages)
                )

    nb_cases_debloquees = len(passages_par_case)
    nb_nouveaux_coequipiers = 0
    nb_deuxiemes_passages = 0
    nb_passages_bonus = 0

    for liste_visites in passages_par_case.values():
        # Le premier joueur chronologique sur la case reçoit les 10 pts, les suivants 7 pts
        liste_visites.sort(key=lambda x: (x[0], x[1]))

        if len(liste_visites) > 1:
            nb_nouveaux_coequipiers += len(liste_visites) - 1

        for idx, (_, pseudo, k) in enumerate(liste_visites):
            pts_case = PTS_DEBLOCAGE if idx == 0 else PTS_COEQUIPIER
            if k >= 2:
                nb_deuxiemes_passages += 1
                pts_case += PTS_DEUXIEME_PASSAGE
            if k >= 3:
                nb_passages_bonus += (k - 2)
                pts_case += (k - 2) * PTS_PASSAGE_SUPP

            points_par_joueur[pseudo] += pts_case

    pts_deblocage = nb_cases_debloquees * PTS_DEBLOCAGE
    pts_coequipiers = nb_nouveaux_coequipiers * PTS_COEQUIPIER
    pts_deuxiemes = nb_deuxiemes_passages * PTS_DEUXIEME_PASSAGE
    pts_bonus = nb_passages_bonus * PTS_PASSAGE_SUPP

    return {
        "total_points": pts_deblocage + pts_coequipiers + pts_deuxiemes + pts_bonus,
        "cases_debloquees": nb_cases_debloquees,
        "nb_coequipiers": nb_nouveaux_coequipiers,
        "nb_deuxiemes": nb_deuxiemes_passages,
        "nb_bonus": nb_passages_bonus,
        "pts_deblocage": pts_deblocage,
        "pts_coequipiers": pts_coequipiers,
        "pts_deuxiemes": pts_deuxiemes,
        "pts_bonus": pts_bonus,
        "nb_joueurs": len(joueurs_equipe),
        "nb_activites": nb_activites,
        "points_par_joueur": points_par_joueur,
    }


def afficher_compteurs_equipes(stats_eq1, stats_eq2):
    """Affiche les deux compteurs d'équipes côte à côte avec titres agrandis."""
    total_cases = N_M**2
    col1, col2 = st.columns(2)

    for col, eq_key, stats in [(col1, "A1/A2", stats_eq1), (col2, "A3", stats_eq2)]:
        with col:
            st.markdown(f"### {EQUIPES[eq_key]['label']}")
            pct_cases = 100 * stats["cases_debloquees"] / total_cases
            st.metric(
                label=EQUIPES[eq_key]["label"],
                value=f"{stats['total_points']} pts",
                delta=f"{stats['cases_debloquees']} cases ({pct_cases:.1f}%)",
                label_visibility="collapsed",
            )


def extraire_tuiles_equipe(joueurs):
    """Retourne l'ensemble des tuples (x, y) conquis par une liste de joueurs."""
    tuiles = set()
    for doc in joueurs:
        for t in doc.get("tiles_conquered", []):
            tuiles.add(tuple(t) if isinstance(t, list) else t)
    return tuiles


def creer_calque_traces(geojson_data, couleur):
    """Crée un calque PyDeck GeoJsonLayer pour afficher des tracés GPS."""
    return pdk.Layer(
        "GeoJsonLayer",
        geojson_data,
        pickable=False,
        stroked=True,
        filled=False,
        get_line_color=couleur,
        get_line_width=4,
        line_width_min_pixels=2,
        line_width_max_pixels=10,
    )


def creer_calque_grille(grille_data):
    """Crée le calque PyDeck GeoJsonLayer pour la grille colorée."""
    return pdk.Layer(
        "GeoJsonLayer",
        grille_data,
        pickable=False,
        stroked=True,
        filled=True,
        get_line_color=[255, 255, 255, 40],
        get_fill_color="properties.fill_color",
        get_line_width=1,
        line_width_min_pixels=1,
    )


def afficher_carte(layers, center_co, zoom=10):
    """Affiche une carte PyDeck centrée sur `center_co` en thème sombre."""
    view_state = pdk.ViewState(
        latitude=center_co[0],
        longitude=center_co[1],
        zoom=zoom,
        min_zoom=1.5,
        max_zoom=20,
        pitch=0,
        bearing=0,
    )
    deck = pdk.Deck(
        layers=layers,
        initial_view_state=view_state,
        map_provider="carto",
        map_style="dark",
    )
    st.pydeck_chart(deck)


# ==============================================================================
# 4. EN-TÊTE & NAVIGATION
# ==============================================================================
st.title("T.R.A.C.E. - Territory Run and Amazing Challenge of Exploration", text_alignment="center")

onglet_actif = st.pills(
    "Navigation",
    options=["MODE PAR ÉQUIPE", "MODE SOLO", "CLASSEMENTS", "RÈGLES DU JEU"],
    default="RÈGLES DU JEU",
    required=True,
    label_visibility="collapsed",
    width="stretch",
)


# ==============================================================================
# 5. ONGLET 1 : MODE COLLECTIF (MULTIPLAYER)
# ==============================================================================
if onglet_actif == "MODE PAR ÉQUIPE":
    st.subheader("🌍 Saison 2 -- Choc des PROMOS (1er Novembre - 31 Décembre 2026)")

    # --- 5.1 Chargement unique des données et compteurs en tête ---
    tous_les_joueurs_m = list(col_multi.find({}, {"_id": 0}))
    joueurs_eq1 = [d for d in tous_les_joueurs_m if d.get("equipe") == "A1/A2"]
    joueurs_eq2 = [d for d in tous_les_joueurs_m if d.get("equipe") == "A3"]

    stats_eq1 = calculer_details_equipe(joueurs_eq1)
    stats_eq2 = calculer_details_equipe(joueurs_eq2)

    afficher_compteurs_equipes(stats_eq1, stats_eq2)
    st.divider()

    # --- 5.2 Légende et filtres de la carte ---
    st.markdown(
        "🟦 **A1/A2 (Bleu)** | 🟥 **A3 (Rouge)** | 🟪 **Zone mixte (les 2 équipes)** "
        "| ⬜ **Tes nouvelles tuiles (non sauvegardées)**"
    )

    c_eq1, c_eq2 = st.columns(2)
    with c_eq1:
        afficher_eq1 = st.checkbox("Afficher les traces A1/A2 🟦", value=True)
    with c_eq2:
        afficher_eq2 = st.checkbox("Afficher les traces A3 🟥", value=True)

    # --- 5.3 Construction des calques de la carte ---
    tuiles_eq1_map = extraire_tuiles_equipe(joueurs_eq1)
    tuiles_eq2_map = extraire_tuiles_equipe(joueurs_eq2)

    grille_data_m = gen_grid(
        CENTER_CO_M,
        TILE_LENGTH_M,
        N_M,
        tuiles_eq1=tuiles_eq1_map if afficher_eq1 else set(),
        tuiles_eq2=tuiles_eq2_map if afficher_eq2 else set(),
        tuiles_ephemeres=st.session_state.tuiles_m,
    )
    layers_m = [creer_calque_grille(grille_data_m)]

    # Calques des traces enregistrées par équipe
    for eq_key, est_coche, liste_joueurs in [
        ("A1/A2", afficher_eq1, joueurs_eq1),
        ("A3", afficher_eq2, joueurs_eq2),
    ]:
        if est_coche:
            traces_equipe = [f for j in liste_joueurs for f in j.get("features", [])]
            if traces_equipe:
                layers_m.append(
                    creer_calque_traces(
                        {"type": "FeatureCollection", "features": traces_equipe},
                        EQUIPES[eq_key]["couleur_trace"],
                    )
                )

    # Calque des traces temporaires (analysées mais pas encore sauvegardées)
    features_ephemeres = [
        {"type": "Feature", "geometry": {"type": "LineString", "coordinates": tr}}
        for tr in st.session_state.traces_m
        if len(tr) > 1
    ]
    if features_ephemeres:
        layers_m.append(
            creer_calque_traces(
                {"type": "FeatureCollection", "features": features_ephemeres},
                [255, 255, 255],
            )
        )

    afficher_carte(layers_m, CENTER_CO_M)
    st.markdown(f"### Arène par équipe : {N_M}×{N_M} tuiles de {int(TILE_LENGTH_M * 1000)} m de côté")

    # --- 5.4 Bloc 1 : Upload et analyse des traces ---
    st.divider()
    st.markdown("### 1️⃣ Ajout et analyse de tes traces")
    st.info(
        "⚠️ Seules les traces de course/marche passant dans l'arène entre le "
        "**1er novembre** et le **31 décembre 2026** sont prises en compte."
    )

    with st.form("upload_form_multi", border=False):
        external_files_m = st.file_uploader(
            "Ajoute tes fichiers .fit ou .fit.gz ici",
            type=["fit", "fit.gz"],
            accept_multiple_files=True,
            key="upload_multi",
        )
        bouton_analyse_m = st.form_submit_button("Analyser ces traces", key="analyse_multi")

    if external_files_m and bouton_analyse_m:
        barre_prog_m = st.progress(0)
        st.session_state.tuiles_m.clear()
        st.session_state.traces_m.clear()
        st.session_state.activities_m.clear()

        with st.spinner("Analyse des traces en cours..."):
            tuiles_m, traces_m, _, _, activities_m = analyser_fit(
                external_files_m, CENTER_CO_M, N_M, TILE_LENGTH_M, barre_prog_m, mode="multi"
            )
            st.session_state.tuiles_m.update(tuiles_m)
            st.session_state.traces_m.extend(traces_m)
            st.session_state.activities_m.extend(activities_m)

        barre_prog_m.empty()

        if st.session_state.activities_m:
            total_passages = sum(len(act["tiles"]) for act in st.session_state.activities_m)
            st.session_state["analyse_msg_m"] = (
                "success",
                f"{len(st.session_state.activities_m)} activité(s) valide(s) affichée(s) sur la carte : "
                f"{len(st.session_state.tuiles_m)} cases touchées.",
            )
        else:
            st.session_state["analyse_msg_m"] = (
                "warning",
                "Aucune activité valide trouvée, vérifie le sport, la zone et les dates (Nov/Déc 2026).",
            )
        st.rerun()

    # Affichage persistant du retour de l'analyse
    msg_info = st.session_state.get("analyse_msg_m")
    if msg_info:
        (st.success if msg_info[0] == "success" else st.warning)(msg_info[1])

    # --- 5.5 Bloc 2 : Sauvegarde définitive en base ---
    st.markdown("---")
    st.markdown("### 2️⃣ Enregistrer ma contribution")

    col_nom, col_eq = st.columns(2)
    with col_nom:
        pseudo_m = st.text_input("Ton nom / pseudo (utilise toujours le même !) :", key="pseudo_multi")
    with col_eq:
        equipe = st.selectbox("Ton équipe :", options=list(EQUIPES.keys()), key="equipe_multi")

    if st.button("Sauvegarder", key="sauvegarde_multi", type="primary"):
        pseudo_clean = pseudo_m.strip()
        if pseudo_clean and st.session_state.activities_m:
            with st.spinner("Sauvegarde en cours..."):
                anciennes_data = col_multi.find_one(
                    {"pseudo": pseudo_clean, "equipe": equipe}, {"_id": 0}
                )

                tuiles_tot = set()
                traces_tot = []
                tile_counts_tot = {}
                tile_first_dates_tot = {}
                saved_activity_ids = set()

                # Rechargement de l'historique existant du joueur
                if anciennes_data:
                    tuiles_tot.update(
                        tuple(t) if isinstance(t, list) else t
                        for t in anciennes_data.get("tiles_conquered", [])
                    )
                    traces_tot.extend(anciennes_data.get("features", []))
                    tile_counts_tot.update(anciennes_data.get("tile_counts", {}))
                    tile_first_dates_tot.update(anciennes_data.get("tile_first_dates", {}))
                    saved_activity_ids.update(anciennes_data.get("activity_ids", []))

                # Fusion des nouvelles activités avec filtre anti-doublon
                nb_ajoutees = 0
                nb_doublons = 0

                for act in st.session_state.activities_m:
                    if act["id"] in saved_activity_ids:
                        nb_doublons += 1
                        continue

                    saved_activity_ids.add(act["id"])
                    nb_ajoutees += 1
                    traces_tot.append({
                        "type": "Feature",
                        "geometry": {"type": "LineString", "coordinates": act["coords"]},
                    })

                    for x, y in set(tuple(t) for t in act["tiles"]):
                        tuiles_tot.add((x, y))
                        key = f"{x},{y}"
                        tile_counts_tot[key] = tile_counts_tot.get(key, 0) + 1
                        if key not in tile_first_dates_tot or act["date"] < tile_first_dates_tot[key]:
                            tile_first_dates_tot[key] = act["date"]

                if nb_ajoutees == 0:
                    st.warning("Cette ou ces activité(s) ont déjà été enregistrées pour ton pseudo !")
                else:
                    geojson_final = {
                        "pseudo": pseudo_clean,
                        "equipe": equipe,
                        "type": "FeatureCollection",
                        "score": len(tuiles_tot),
                        "tiles_conquered": list(tuiles_tot),
                        "tile_counts": tile_counts_tot,
                        "tile_first_dates": tile_first_dates_tot,
                        "activity_ids": list(saved_activity_ids),
                        "features": traces_tot,
                    }
                    col_multi.replace_one(
                        {"pseudo": pseudo_clean, "equipe": equipe}, geojson_final, upsert=True
                    )

                    msg = f"{pseudo_clean} : {nb_ajoutees} nouvelle(s) activité(s) ajoutée(s) à l'équipe **{equipe}**."
                    if nb_doublons > 0:
                        msg += f" ({nb_doublons} doublon(s) ignoré(s).)"
                    st.success(msg)

                    st.session_state.tuiles_m.clear()
                    st.session_state.traces_m.clear()
                    st.session_state.activities_m.clear()
                    st.session_state.pop("analyse_msg_m", None)

                    time.sleep(2)
                    st.rerun()
        else:
            st.warning(
                "Merci d'entrer ton nom et d'analyser au moins une activité valide "
                "(Novembre/Décembre 2026 et dans la zone) avant d'enregistrer."
            )


# ==============================================================================
# 6. ONGLET 2 : MODE SOLO (ARÈNE PERSONNELLE)
# ==============================================================================
elif onglet_actif == "MODE SOLO":
    st.subheader("🏠 Mode solo -- À domicile -- De tout temps")
    st.markdown("Ici, tu peux choisir l'arène de ton choix pour te comparer aux autres « à domicile ».")

    col_gauche, col_droite = st.columns(2)

    # --- 6.1 Sélection ou création de l'arène ---
    with col_gauche:
        st.markdown("### 1️⃣ Définition de l'arène")
        used_arenes = {}
        for doc in col_perso.find({"center": {"$exists": True}}, {"lieu": 1, "center": 1, "_id": 0}):
            used_arenes.setdefault(doc["lieu"], doc["center"])

        options_menu = ["Nouvelle arène"] + list(used_arenes.keys())
        choix_arene = st.selectbox(
            "Choisis une arène existante ou crée-en une nouvelle :",
            options=options_menu,
            key="select_arene",
        )

        if choix_arene == "Nouvelle arène":
            c_lat, c_lon = st.columns(2)
            with c_lat:
                lat_perso = st.number_input("Latitude du centre", value=0.0, format="%.6f", key="lat_p")
            with c_lon:
                lon_perso = st.number_input("Longitude du centre", value=0.0, format="%.6f", key="lon_p")

            if st.button("Créer mon arène", type="primary"):
                st.session_state.center_p = (lat_perso, lon_perso)
                st.session_state.tuiles_p.clear()
                st.session_state.traces_p.clear()
                st.session_state.last_choix_arene = "Nouvelle arène"
        else:
            coords = tuple(used_arenes.get(choix_arene, (0.0, 0.0)))
            if st.session_state.last_choix_arene != choix_arene:
                st.session_state.center_p = coords
                st.session_state.tuiles_p.clear()
                st.session_state.traces_p.clear()
                st.session_state.last_choix_arene = choix_arene

            st.info(f"{choix_arene} (Centre : {coords[0]:.6f}, {coords[1]:.6f})")

        center_co_p = st.session_state.center_p

    # --- 6.2 Upload et analyse des traces Solo ---
    with col_droite:
        st.markdown("### 2️⃣ Ajoute tes traces")
        with st.form("form_upload_solo", border=False):
            external_files_p = st.file_uploader(
                "Ajoute tes fichiers .fit ou .fit.gz",
                type=["fit", "fit.gz"],
                accept_multiple_files=True,
                key="upload_perso",
            )
            bouton_analyse_p = st.form_submit_button("Analyser ces fichiers")

        if external_files_p and bouton_analyse_p:
            barre_prog_p = st.progress(0)
            st.session_state.tuiles_p.clear()
            st.session_state.traces_p.clear()

            with st.spinner("Analyse des traces en cours..."):
                tuiles_p, traces_p, _, _, _ = analyser_fit(
                    external_files_p, center_co_p, N_P, TILE_LENGTH_P, barre_prog_p, mode="solo"
                )
                st.session_state.tuiles_p.update(tuiles_p)
                st.session_state.traces_p.extend(traces_p)
                st.session_state.center_p = center_co_p

            barre_prog_p.empty()
            st.success(f"Traces ajoutées ! Score temporaire : {len(st.session_state.tuiles_p)} tuiles.")

    # --- 6.3 Affichage de la carte Solo ---
    st.divider()
    st.markdown(f"### 🗺️ Carte solo : {N_P}×{N_P} tuiles de {int(TILE_LENGTH_P * 1000)} m de côté")

    pseudos_dispo_p = (
        [doc["pseudo"] for doc in col_perso.find({"lieu": choix_arene}, {"pseudo": 1})]
        if choix_arene != "Nouvelle arène"
        else []
    )

    option_par_defaut = "Traces temporaires"
    if pseudos_dispo_p:
        joueur_a_afficher = st.selectbox(
            "Voir une performance enregistrée sur cette arène :",
            options=[option_par_defaut] + pseudos_dispo_p,
        )
    else:
        joueur_a_afficher = option_par_defaut
        if choix_arene != "Nouvelle arène":
            st.info("Aucune performance enregistrée sur cette arène pour le moment.")

    layers_p = []
    colored_tiles_p = set(st.session_state.tuiles_p)
    features_p = [
        {"type": "Feature", "geometry": {"type": "LineString", "coordinates": tr}}
        for tr in st.session_state.traces_p
        if len(tr) > 1
    ]

    with st.spinner("Chargement de la carte..."):
        # Trace sauvegardée sélectionnée (Vert)
        if joueur_a_afficher != option_par_defaut:
            data_joueur_p = col_perso.find_one(
                {"pseudo": joueur_a_afficher, "lieu": choix_arene}, {"_id": 0}
            )
            if data_joueur_p and data_joueur_p.get("features"):
                layers_p.append(creer_calque_traces(data_joueur_p, [76, 175, 80]))
                colored_tiles_p.update(
                    tuple(t) if isinstance(t, list) else t
                    for t in data_joueur_p.get("tiles_conquered", [])
                )

        # Traces temporaires (Orange)
        if features_p:
            layers_p.append(
                creer_calque_traces(
                    {"type": "FeatureCollection", "features": features_p},
                    [255, 87, 34],
                )
            )

        # Grille Solo en arrière-plan
        grille_data_p = gen_grid(
            st.session_state.center_p, TILE_LENGTH_P, N_P, tuiles_solo=colored_tiles_p
        )
        layers_p.insert(0, creer_calque_grille(grille_data_p))

        afficher_carte(layers_p, st.session_state.center_p)

    # --- 6.4 Sauvegarde Solo ---
    st.markdown("---")
    st.markdown("### 3️⃣ Sauvegarde")
    c_nom, c_lieu = st.columns(2)
    with c_nom:
        pseudo_p = st.text_input("Nom :", key="pseudo_p")
    with c_lieu:
        if choix_arene == "Nouvelle arène":
            lieu_p = st.text_input("Nom de votre arène :", key="lieu_p")
        else:
            lieu_p = choix_arene
            st.info(f"Localisation : {lieu_p}")

    if st.button("Sauvegarder"):
        pseudo_p_clean = pseudo_p.strip()
        lieu_p_clean = lieu_p.strip()

        if pseudo_p_clean and lieu_p_clean and features_p:
            with st.spinner("Sauvegarde en cours..."):
                tuiles_tot_p = set(st.session_state.tuiles_p)
                traces_tot_p = features_p.copy()

                anciennes_data_p = col_perso.find_one(
                    {"pseudo": pseudo_p_clean, "lieu": lieu_p_clean}, {"_id": 0}
                )
                if anciennes_data_p:
                    tuiles_tot_p.update(
                        tuple(t) if isinstance(t, list) else t
                        for t in anciennes_data_p.get("tiles_conquered", [])
                    )
                    traces_tot_p.extend(anciennes_data_p.get("features", []))

                geojson_final_p = {
                    "pseudo": pseudo_p_clean,
                    "lieu": lieu_p_clean,
                    "center": st.session_state.center_p,
                    "type": "FeatureCollection",
                    "score": len(tuiles_tot_p),
                    "tiles_conquered": list(tuiles_tot_p),
                    "features": traces_tot_p,
                }
                col_perso.replace_one(
                    {"pseudo": pseudo_p_clean, "lieu": lieu_p_clean}, geojson_final_p, upsert=True
                )

            st.success(
                f"Progression sauvegardée ! Score total de {pseudo_p_clean} à {lieu_p_clean} : "
                f"{len(tuiles_tot_p)} tuiles."
            )
            st.session_state.tuiles_p.clear()
            st.session_state.traces_p.clear()
            st.session_state.last_choix_arene = lieu_p_clean
            time.sleep(2)
            st.rerun()
        else:
            st.warning("Merci d'entrer un nom, un lieu et au moins une trace valide avant d'enregistrer.")


# ==============================================================================
# 7. ONGLET 3 : CLASSEMENTS (LEADERBOARDS)
# ==============================================================================
elif onglet_actif == "CLASSEMENTS":
    st.header("🏆 Classements")

    col_m, col_p = st.columns(2, gap="medium")

    # --- 7.1 Classement Collectif (Saison 2) ---
    with col_m:
        st.subheader("🌍 Mode Collectif -- Arène ENSMA -- Saison 2")
        tous_les_joueurs_m = list(col_multi.find({}, {"_id": 0}))

        stats_eq1 = calculer_details_equipe([d for d in tous_les_joueurs_m if d.get("equipe") == "A1/A2"])
        stats_eq2 = calculer_details_equipe([d for d in tous_les_joueurs_m if d.get("equipe") == "A3"])

        afficher_compteurs_equipes(stats_eq1, stats_eq2)
        st.divider()

        # Tableau récapitulatif des points par catégorie
        st.markdown("### 📊 Détail des points par équipe")
        tableau_detail = [
            {
                "Catégorie de points": f"🚩 1ères conquêtes ({PTS_DEBLOCAGE} pts / case)",
                "🟦 A1/A2": f"{stats_eq1['pts_deblocage']} pts ({stats_eq1['cases_debloquees']})",
                "🟥 A3": f"{stats_eq2['pts_deblocage']} pts ({stats_eq2['cases_debloquees']})",
            },
            {
                "Catégorie de points": f"🤝 Nouveaux coéquipiers ({PTS_COEQUIPIER} pts)",
                "🟦 A1/A2": f"{stats_eq1['pts_coequipiers']} pts ({stats_eq1['nb_coequipiers']})",
                "🟥 A3": f"{stats_eq2['pts_coequipiers']} pts ({stats_eq2['nb_coequipiers']})",
            },
            {
                "Catégorie de points": f"🔁 2èmes passages ({PTS_DEUXIEME_PASSAGE} pts)",
                "🟦 A1/A2": f"{stats_eq1['pts_deuxiemes']} pts ({stats_eq1['nb_deuxiemes']})",
                "🟥 A3": f"{stats_eq2['pts_deuxiemes']} pts ({stats_eq2['nb_deuxiemes']})",
            },
            {
                "Catégorie de points": f"✨ Passages supplémentaires ({PTS_PASSAGE_SUPP} pt)",
                "🟦 A1/A2": f"{stats_eq1['pts_bonus']} pts ({stats_eq1['nb_bonus']})",
                "🟥 A3": f"{stats_eq2['pts_bonus']} pts ({stats_eq2['nb_bonus']})",
            },
            {
                "Catégorie de points": "👥 Participants actifs",
                "🟦 A1/A2": f"{stats_eq1['nb_joueurs']}",
                "🟥 A3": f"{stats_eq2['nb_joueurs']}",
            },
            {
                            "Catégorie de points": "🎯Nombre d'activités de l'équipe",
                            "🟦 A1/A2": f"{stats_eq1['nb_activites']}",
                            "🟥 A3": f"{stats_eq2['nb_activites']}",
                        },
            {
                "Catégorie de points": "🏆 TOTAL",
                "🟦 A1/A2": f"{stats_eq1['total_points']} pts",
                "🟥 A3": f"{stats_eq2['total_points']} pts",
            },
        ]
        st.dataframe(tableau_detail, use_container_width=True, hide_index=True)

        # Jauge bicolore du rapport de force
        total_pts_global = stats_eq1["total_points"] + stats_eq2["total_points"]
        if total_pts_global > 0:
            pct_eq1 = (stats_eq1["total_points"] / total_pts_global) * 100
            pct_eq2 = 100 - pct_eq1

            st.markdown(
                f'<div style="margin-top:12px;margin-bottom:16px;">'
                f'<div style="display:flex;justify-content:space-between;font-weight:600;font-size:0.95rem;margin-bottom:6px;">'
                f'<span style="color:#3296FF;">🟦 A1/A2 : {pct_eq1:.1f}% ({stats_eq1["total_points"]} pts)</span>'
                f'<span style="color:#FF3232;">{pct_eq2:.1f}% ({stats_eq2["total_points"]} pts) : A3 🟥</span>'
                f"</div>"
                f'<div style="display:flex;width:100%;height:22px;border-radius:11px;overflow:hidden;background-color:#262730;box-shadow:inset 0 1px 3px rgba(0,0,0,0.4);">'
                f'<div style="width:{pct_eq1:.2f}%;background:linear-gradient(90deg,#0077CC,#3296FF);transition:width 0.5s ease;"></div>'
                f'<div style="width:{pct_eq2:.2f}%;background:linear-gradient(90deg,#FF3232,#CC0000);transition:width 0.5s ease;"></div>'
                f"</div></div>",
                unsafe_allow_html=True,
            )
        else:
            st.info("Aucun point enregistré pour le moment sur la Saison 2.")

        # Tableaux des contributions individuelles par équipe
        st.markdown("### 👥 Contributions des joueurs")
        col_tab1, col_tab2 = st.columns(2)

        for col_tab, eq_key, stats_eq in [
            (col_tab1, "A1/A2", stats_eq1),
            (col_tab2, "A3", stats_eq2),
        ]:
            with col_tab:
                st.markdown(f"**{EQUIPES[eq_key]['label']}**")
                total_eq = stats_eq["total_points"]
                contribs = sorted(
                    stats_eq["points_par_joueur"].items(),
                    key=lambda x: x[1],
                    reverse=True,
                )

                if contribs:
                    lignes = [
                        {
                            "Pseudo": pseudo,
                            "Score": f"{pts} pts",
                            "% dans l'équipe": f"{(pts / total_eq * 100) if total_eq > 0 else 0.0:.1f}%",
                        }
                        for pseudo, pts in contribs
                    ]
                    st.dataframe(lignes, use_container_width=True, hide_index=True)
                else:
                    st.info("Aucun participant pour le moment.")

    # --- 7.2 Classement Solo ---
    with col_p:
        st.subheader("🏠 Mode solo -- Arène personnelle -- De tout temps")
        scores_p = []
        for doc in col_perso.find({}, {"pseudo": 1, "lieu": 1, "score": 1, "_id": 0}):
            score_p = doc.get("score", 0)
            pseudo_complet = f"{doc.get('pseudo', 'Inconnu')} ({doc.get('lieu', 'Inconnu')})"
            scores_p.append({
                "Joueur": pseudo_complet,
                "Score": score_p,
                "Pourcentage": round(100 * score_p / (N_P**2), 2),
            })

        if scores_p:
            scores_p.sort(key=lambda x: x["Score"], reverse=True)
            st.dataframe(scores_p, use_container_width=True, hide_index=True)
            pct_leader = 100 * scores_p[0]["Score"] / (N_P**2)
            st.progress(min(pct_leader / 100, 1.0), text=f"Progression du leader : {pct_leader:.2f}%")
        else:
            st.info("Aucun score solo pour l'instant")


# ==============================================================================
# 8. ONGLET 4 : RÈGLES DU JEU (GAMERULES)
# ==============================================================================
elif onglet_actif == "RÈGLES DU JEU":

    st.subheader("Règles du Jeu")

    st.markdown("""
    **T.R.A.C.E.** est un jeu de conquête de territoire basé sur vos traces GPS réelles.
    L'arène autour de l'ENSMA est une grille de **9 km × 9 km**, découpée en cases de **300 mètres de côté**.

    ### ⚔️ Saison 2 : CHOC DES PROMOS (🟦**A1/A2** vs 🟥**A3**)
    * **Période :** Du **1er Novembre au 31 Décembre 2026**.
    * **Sports autorisés :** Course à pied, trail et marche uniquement.
    * **Objectif :** Faire marquer le maximum de points à son équipe. L'équipe qui a le plus de points au 31 décembre remporte la saison !

    ### 🎯 Comment gagner des points ?
    Le comptage est **100 % indépendant pour chaque équipe** (ce que fait l'équipe adverse ne vous enlève aucun point). Chaque sortie valide passant dans une case compte pour **1 passage** :

    | Situation sur une case (pour ton équipe) | Points gagnés |
    | :--- | :---: |
    | 🚩 **Tu débloques une case vierge** pour ton équipe (1er passage de l'équipe) | **+10 pts** |
    | 🤝 **Tu découvres une case déjà débloquée par un coéquipier** (ton 1er passage perso) | **+7 pts** |
    | 🔁 **Tu repasses une 2ème fois** dans une case où tu es déjà allé(e) | **+5 pts** |
    | ✨ **Tu y repasses une 3ème fois, 4ème fois, etc.** | **+1 pt** par sortie |
    | ⚠️ **Un seul passage par sortie** est comptabilisé pour une case donnée (même si tu passes plusieurs fois dans la même case lors d'une sortie). |
    ### ⚙️ Comment participer ?
    1. Récupérez vos sorties en fichiers `.fit` ou `.fit.gz` depuis Strava, Garmin, Coros, Polar ou Suunto.
    2. Dans **MULTIPLAYER MODE**, uploadez vos fichiers et cliquez sur *Analyser ces traces*.
    3. Indiquez votre **pseudo** *(gardez toujours le même pour que votre score soit bien compté !)* et choisissez votre **équipe** (**A1/A2** ou **A3**), puis cliquez sur **Sauvegarder**.
    4. Un **Mode Solo** reste disponible pour créer votre propre arène chez vous, sans limite de date.

    ### ⚠️ Avertissement ⚠️
    #### **Ne vous mettez pas en danger pour débloquer une case, le créateur de ce jeu décline toute responsabilité.**
    """)