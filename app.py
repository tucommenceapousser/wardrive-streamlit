import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from folium.plugins import HeatMap
import os
import requests
from requests.auth import HTTPBasicAuth
import plotly.express as px
import json
from datetime import datetime

# ────────────────────────────────────────────────
# CONFIG SECRETE (utilise st.secrets pour sécurité)
try:
    WIGLE_API_NAME = st.secrets["WIGLE_API_NAME"]
    WIGLE_API_TOKEN = st.secrets["WIGLE_API_TOKEN"]
except KeyError:
    st.error("Configure tes secrets Wigle dans .streamlit/secrets.toml ! Ex: WIGLE_API_NAME = 'AID...'")
    st.stop()
# ────────────────────────────────────────────────

# STYLE HACKER MATRIX
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=VT323&display=swap');
    .stApp { background-color: #000000; color: #00ff41; font-family: 'VT323', monospace; }
    h1, h2, h3, p, div, label, span, .stMarkdown { color: #00ff41 !important; text-shadow: 0 0 5px #00ff41, 0 0 10px #00ff41; }
    .glitch { position: relative; animation: glitch 2s infinite; }
    @keyframes glitch { 0% { text-shadow: 2px 0 #ff00c1, -2px 0 #00ff41; } 10% { text-shadow: -2px 0 #ff00c1, 2px 0 #00ff41; } 20% { text-shadow: 2px 0 #00ff41, -2px 0 #ff00c1; } 100% { text-shadow: none; } }
    [data-testid="stSidebar"] { background-color: #0a0a0a; border-right: 2px solid #00ff41; }
    .stButton > button { background: transparent; color: #00ff41; border: 2px solid #00ff41; font-family: 'VT323', monospace; font-size: 1.2rem; }
    .stButton > button:hover { background: #00ff41; color: #000; box-shadow: 0 0 15px #00ff41; }
    .stRadio > div, .stSelectbox > div > div { background: #111 !important; color: #00ff41; border: 1px solid #00ff41; }
    hr { border-color: #00ff41; opacity: 0.5; }
    </style>
""", unsafe_allow_html=True)

st.markdown("<h2 class='glitch'>█▓▒░ MARAUDER WARDRIVE ░▒▓█</h2>", unsafe_allow_html=True)
st.markdown("<h1 class='glitch'>█▓▒░ BY TRHACKNON ░▒▓█</h1>", unsafe_allow_html=True)
st.caption("ESP32 Marauder + CYD • Wardriving 2026 • Full DIY App")

# ────────────────────────────────────────────────
# Uploader fichiers CSV (nouveau !)
uploaded_files = st.file_uploader("Upload tes wardrive_*.csv (multiples OK)", type="csv", accept_multiple_files=True)
if uploaded_files:
    for uploaded in uploaded_files:
        try:
            uploaded.seek(0)
            df_upload = pd.read_csv(uploaded)
            # Sauvegarde temp pour concat
            with open(uploaded.name, "wb") as f:
                f.write(uploaded.getbuffer())
            st.success(f"{uploaded.name} uploadé !")
        except Exception as e:
            st.warning(f"Erreur {uploaded.name}: {e}")

# Chargement data
@st.cache_data(ttl=300)
def load_data():
    folder = "."
    csv_files = [f for f in os.listdir(folder) if f.lower().endswith('.csv') and 'wardrive' in f.lower()]
    if not csv_files:
        return pd.DataFrame(), "Pas de CSV trouvés !"

    dfs = []
    errors = []
    for file in csv_files:
        try:
            df_temp = pd.read_csv(file, encoding='utf-8', on_bad_lines='skip')
            df_temp.columns = df_temp.columns.str.strip().str.lower()
            dfs.append(df_temp)
        except Exception as e:
            errors.append(f"{file}: {e}")

    if not dfs:
        return pd.DataFrame(), "\n".join(errors)

    df = pd.concat(dfs, ignore_index=True)

    # Nettoyage
    lat_col = next((c for c in df.columns if 'latitude' in c.lower()), None)
    lon_col = next((c for c in df.columns if 'longitude' in c.lower()), None)
    if not lat_col or not lon_col:
        return pd.DataFrame(), "Colonnes GPS manquantes !"

    df = df.dropna(subset=[lat_col, lon_col])
    df = df[df[lat_col].between(-90, 90) & df[lon_col].between(-180, 180)]
    df = df.rename(columns={lat_col: 'lat', lon_col: 'lon', 'mac': 'bssid', 'ssid': 'ssid', 'authmode': 'auth', 'rssi': 'rssi', 'channel': 'channel', 'firstseen': 'firstseen'})

    return df, "\n".join(errors) if errors else None

df, load_errors = load_data()
if df.empty:
    st.error("Pas de data valide ! Erreurs: " + (load_errors or "Inconnu"))
    st.stop()

# Stats rapides
total = len(df)
open_wifi = len(df[df['auth'].str.contains('none|opn', case=False, na=False)])
hidden = len(df[df['ssid'].str.strip().isin(['', '<hidden ssid>', 'hidden ssid']) | df['ssid'].isna()])
st.markdown(f"**Total APs :** {total:,}  •  **Ouverts :** {open_wifi:,}  •  **Cachés :** {hidden:,}")

# ────────────────────────────────────────────────
# Sidebar
st.sidebar.header("█ CONTROLS █")
view_mode = st.sidebar.radio("Affichage :", ["Points (tous)", "Points (ouverts)", "Points (cachés)", "Heatmap (densité)"])
ssid_regex = st.sidebar.text_input("Filtre SSID (regex, ex: Freebox|SFR)", "")
min_rssi = st.sidebar.slider("RSSI min (dBm)", -100, -30, -90)
channel_filter = st.sidebar.multiselect("Canaux", sorted(df['channel'].unique()), [])
date_min = st.sidebar.date_input("Date min (firstseen)", value=None)
heatmap_intensity = st.sidebar.slider("Intensité Heatmap", 0.1, 1.0, 0.6, step=0.1)
zoom_start = st.sidebar.slider("Zoom", 10, 18, 14)

# Filtres appliqués
df_filtered = df[df['rssi'] >= min_rssi]
if ssid_regex:
    df_filtered = df_filtered[df_filtered['ssid'].str.contains(ssid_regex, case=False, na=False, regex=True)]
if channel_filter:
    df_filtered = df_filtered[df_filtered['channel'].isin(channel_filter)]
if date_min:
    df_filtered['firstseen'] = pd.to_datetime(df_filtered['firstseen'], errors='coerce')
    df_filtered = df_filtered[df_filtered['firstseen'] >= pd.to_datetime(date_min)]

if view_mode == "Points (ouverts)":
    df_filtered = df_filtered[df_filtered['auth'].str.contains('none|opn', case=False, na=False)]
elif view_mode == "Points (cachés)":
    df_filtered = df_filtered[df_filtered['ssid'].str.strip().isin(['', '<hidden ssid>', 'hidden ssid']) | df_filtered['ssid'].isna()]

# ────────────────────────────────────────────────
# WIGLE INTEGRATION (fixé et robuste)
st.sidebar.header("█ WIGLE API █")
if st.sidebar.button("Uploader CSV vers Wigle"):
    csv_files = [f for f in os.listdir(".") if f.lower().endswith('.csv') and 'wardrive' in f.lower()]
    if not csv_files:
        st.sidebar.error("Aucun CSV !")
    else:
        with st.spinner("Upload... (quota limité)"):
            successes = []
            for csv_file in csv_files:
                try:
                    url = "https://api.wigle.net/api/v2/file/upload"
                    files = {'stumblefile': (csv_file, open(csv_file, 'rb'), 'text/csv')}
                    resp = requests.post(url, auth=HTTPBasicAuth(WIGLE_API_NAME, WIGLE_API_TOKEN), files=files, timeout=120)
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get("success"):
                            successes.append(f"{csv_file} → ID: {data.get('fileId')}")
                        else:
                            st.sidebar.warning(f"{csv_file}: {data.get('message', 'Erreur')}")
                    else:
                        st.sidebar.error(f"{csv_file}: HTTP {resp.status_code} - {resp.text[:100]}")
                except Exception as e:
                    st.sidebar.error(f"{csv_file}: {str(e)}")
            if successes:
                st.sidebar.success("\n".join(successes))
                st.sidebar.info("Check https://wigle.net/uploads")

if st.sidebar.button("Lister uploads Wigle"):
    try:
        url = "https://api.wigle.net/api/v2/file/list"
        resp = requests.get(url, auth=HTTPBasicAuth(WIGLE_API_NAME, WIGLE_API_TOKEN), timeout=60)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("success") and data.get("results"):
                st.sidebar.write("Derniers uploads:")
                for item in data["results"][:10]:
                    st.sidebar.markdown(f"- **{item.get('fileId')}**: {item.get('filename')} ({item.get('status')}) - {item.get('uploadedTs')}")
            else:
                st.sidebar.info("Vide ou erreur.")
        else:
            st.sidebar.error(f"HTTP {resp.status_code}: {resp.text}")
    except Exception as e:
        st.sidebar.error(str(e))

# Recherche Wigle (nouveau !)
st.sidebar.header("█ Recherche Wigle █")
search_ssid = st.sidebar.text_input("Rechercher SSID (ex: Freebox)")
search_lat_min, search_lat_max = st.sidebar.slider("Lat range (Paris \~48.8-48.9)", 48.0, 49.0, (48.8, 48.9), step=0.01)
search_lon_min, search_lon_max = st.sidebar.slider("Lon range (Paris \~2.2-2.5)", 2.0, 3.0, (2.2, 2.5), step=0.01)
if st.sidebar.button("Fetcher de Wigle"):
    try:
        url = "https://api.wigle.net/api/v2/network/search"
        params = {
            "ssidlike": search_ssid if search_ssid else None,
            "latrange1": search_lat_min, "latrange2": search_lat_max,
            "longrange1": search_lon_min, "longrange2": search_lon_max,
            "variance": 0.01,  # précision
            "resultsPerPage": 100
        }
        resp = requests.get(url, auth=HTTPBasicAuth(WIGLE_API_NAME, WIGLE_API_TOKEN), params=params, timeout=60)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("success") and data.get("results"):
                df_wigle = pd.DataFrame(data["results"])
                df_wigle = df_wigle.rename(columns={'trilat': 'lat', 'trilong': 'lon', 'ssid': 'ssid', 'encryption': 'auth'})
                st.session_state['df_wigle'] = df_wigle
                st.sidebar.success(f"{len(df_wigle)} réseaux trouvés ! Ajoutés à la carte en bleu.")
            else:
                st.sidebar.warning("Aucun résultat ou erreur.")
        else:
            st.sidebar.error(f"HTTP {resp.status_code}: {resp.text}")
    except Exception as e:
        st.sidebar.error(str(e))

# ────────────────────────────────────────────────
# Carte
center_lat = df_filtered['lat'].mean() if not df_filtered.empty else 48.8566
center_lon = df_filtered['lon'].mean() if not df_filtered.empty else 2.3522
m = folium.Map(location=[center_lat, center_lon], zoom_start=zoom_start, tiles="CartoDB dark_matter", attr="Dark Map")

if "Heatmap" in view_mode:
    if not df_filtered.empty:
        HeatMap(df_filtered[['lat', 'lon']].values.tolist(), min_opacity=0.3, max_opacity=heatmap_intensity, radius=12, blur=15).add_to(m)
else:
    for _, row in df_filtered.iterrows():
        ssid = row.get('ssid', '<Hidden>') or '<Hidden>'
        popup = folium.Popup(f"<b>{ssid}</b><br>BSSID: {row.get('bssid', 'N/A')}<br>Auth: {row.get('auth', 'N/A')}<br>Channel: {row.get('channel', '?')}<br>RSSI: {row.get('rssi', '?')}<br>Vu: {row.get('firstseen', 'N/A')}", max_width=300)
        color = 'lime' if 'none' in str(row.get('auth', '')).lower() else 'red'
        if 'hidden' in ssid.lower():
            color = 'magenta'
        folium.CircleMarker(location=[row['lat'], row['lon']], radius=6, color=color, fill=True, fill_color=color, fill_opacity=0.7, popup=popup).add_to(m)

# Ajout Wigle search (en bleu)
if 'df_wigle' in st.session_state and not st.session_state['df_wigle'].empty:
    for _, row in st.session_state['df_wigle'].iterrows():
        popup = folium.Popup(f"<b>{row.get('ssid', 'Unknown')}</b><br>Auth: {row.get('auth', 'N/A')}<br>From Wigle API", max_width=300)
        folium.CircleMarker(location=[row['lat'], row['lon']], radius=4, color='blue', fill=True, fill_color='blue', fill_opacity=0.5, popup=popup).add_to(m)

st_folium(m, width=1100, height=700)

# ────────────────────────────────────────────────
# Stats avancées (nouveau !)
st.header("█ STATS █")
col1, col2 = st.columns(2)
with col1:
    if not df_filtered.empty:
        fig_pie = px.pie(df_filtered, names='auth', title='Types Auth', hole=0.3, color_discrete_sequence=['lime', 'red', 'magenta'])
        st.plotly_chart(fig_pie)
with col2:
    top_ssid = df_filtered['ssid'].value_counts().head(10)
    fig_bar = px.bar(top_ssid, title='Top 10 SSIDs', color_discrete_sequence=['#00ff41'])
    st.plotly_chart(fig_bar)

st.dataframe(df_filtered.head(100), use_container_width=True)  # Table preview

# Exports
st.header("█ EXPORTS █")
if st.button("Export Carte HTML"):
    m.save("wardrive_map.html")
    st.success("Sauvegardé : wardrive_map.html")
if st.button("Export CSV filtré"):
    df_filtered.to_csv("filtered_wardrive.csv", index=False)
    st.success("Sauvegardé : filtered_wardrive.csv")
if st.button("Export Stats JSON"):
    stats = {"total": total, "ouverts": open_wifi, "cachés": hidden, "top_ssid": top_ssid.to_dict()}
    with open("stats.json", "w") as f:
        json.dump(stats, f)
    st.success("Sauvegardé : stats.json")

# Debug
with st.expander("█ DEBUG MODE █"):
    st.write("Erreurs load: ", load_errors)
    st.write("Colonnes DF: ", df.columns.tolist())
    st.write("Exemple row: ", df.iloc[0] if not df.empty else "Vide")

st.markdown("---")
st.caption("App DIY boostée • Fiable pour exo 2026 • Si bug upload persiste, partage l'erreur exacte ! 💀")
