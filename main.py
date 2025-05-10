
from bs4 import BeautifulSoup
import urllib.request as urllib2
import re
import xlsxwriter
import streamlit as st
import requests
import json
import ast 
import pandas as pd
import time 
import geocoder
import folium
import matplotlib.pyplot as plt
from streamlit_folium import st_folium
from matplotlib.colors import to_hex
import streamlit.components.v1 as components
from folium.plugins import Fullscreen
from folium.raster_layers import WmsTileLayer


# Step 0: Settings
st.set_page_config(
    layout='wide',
    initial_sidebar_state='auto'
)

# Step 1: Get relevant IDs
@st.cache_resource(show_spinner='Laster inn annonser...')
def get_ads(max_pages=5):
    base_url = 'https://www.finn.no/realestate/homes/search.html?sort=PRICE_ASC&location=1.20061.20507&location=1.20061.20512&location=1.20061.20511&location=1.20061.20522&location=1.20061.20510&location=1.20061.20513&location=1.20061.20509&location=1.20061.20508&location=1.20061.20531&area_from=60&facilities=1&property_type=3&floor_navigator=NOTFIRST&price_collective_to=7500000&stored-id=78449579'

    all_ids = []
    for page_number in range(1, max_pages + 1):
        url = f'{base_url}&page={page_number}'
        response = requests.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        ads = soup.find_all('a', class_='sf-search-ad-link')
        page_ids = [a.get('id') for a in ads if a.get('id')]
        all_ids.extend(page_ids)
    return all_ids

ad_ids = get_ads()

# Step 2: Go through each ID and save data
@st.cache_resource(show_spinner='Henter data fra annonse...')
def ad_id_scraper(ad_id):
    url = f'https://www.finn.no/realestate/homes/ad.html?finnkode={ad_id}'
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    return soup, url

def extract_between(text, start_phrase, end_phrase):
    try:
        start_index = text.index(start_phrase) + len(start_phrase) if start_phrase else 0
        end_index = text.index(end_phrase, start_index)
        return text[start_index:end_index].strip()
    except ValueError:
        return None

@st.cache_resource(show_spinner='Henter inn data fra alle annonser...')
def get_df(ad_ids=ad_ids, test=True):
    ad_dict_list = []
    for i, ad_id in enumerate(ad_ids):
        soup, selected_url = ad_id_scraper(ad_id=ad_id) 
        elements = soup.find_all(attrs={'data-testid': True})        
        ad_dict = {}
        ad_dict['ID'] = ad_id
        ad_dict['URL'] = selected_url
        for el in elements:
            key = el['data-testid']
            value = el.get_text(strip=True)
            ad_dict[key] = value  
        # 
        keys_to_drop = [
            'share-ad-details',
            'info-plot',
            'image-gallery', 
            'gallery-main',
            'object-details',
            'map-link',
            'pricing-details',
            'pricing-links',
            'pf-finance-link',
            'ownership-history-link',
            'price-statistics-link',
            'key-info',
            'hide-more-div',
            'hide-more-button',
            'show-more-button',
            'viewings',
            'about-property',
            'hide-entire-description',
            'show-entire-description',
            'useful-links',
            'viewings-notice',
            'viewing-sale-statement-button',
            'object-location',
            'object-info',
            'viewing-note-0',
            'viewings-note-0'
            ]
        for key in keys_to_drop:
            if key in ad_dict:
                del ad_dict[key]
        #
        for key, value in ad_dict.items():
            if (key.startswith('pricing')) | (key.startswith('info-construction')) | (key.startswith('info-usable')) | (key.startswith('info-rooms')) | (key.startswith('info-open')) | (key.startswith('info-floor')) | (key.startswith('info-bedrooms')) | (key.startswith('info-plot')) | (key.startswith('info-leasehold')):
                value = ''.join(re.findall(r'\d+', value))
                if value:
                    value = int(value)
            ad_dict[key] = value
        ad_dict_list.append(ad_dict)
        if test == True and i == 2:
            break
    df = pd.DataFrame(ad_dict_list)
    df = df[df['object-title'].notna()]
    return df

df = get_df(ad_ids=ad_ids, test=False)

# Step 3: Geocoding
@st.cache_resource(show_spinner='Finner koordinater...')
def geocode_address(x):
    g = geocoder.arcgis(x)
    return g.latlng[0], g.latlng[1]

df[['latitude', 'longitude']] = df['object-address'].apply(lambda x: pd.Series(geocode_address(x)))

# Step 4: Compute other parameters
month_map = {
    "januar": "January", "februar": "February", "mars": "March", "april": "April",
    "mai": "May", "juni": "June", "juli": "July", "august": "August",
    "september": "September", "oktober": "October", "november": "November", "desember": "December"
}

def extract_datetime(text):
    if not text or pd.isna(text):
        return pd.NaT
    match = re.search(r"(\d{1,2})\. (\w+)(\d{2}:\d{2})", text)
    if match:
        day, month_no, time = match.groups()
        month = month_map.get(month_no.lower(), month_no)
        date_str = f"{day} {month} 2025 {time}"
        date = pd.to_datetime(date_str, format="%d %B %Y %H:%M", errors='coerce')
        return date
    return pd.NaT

#@st.cache_resource(show_spinner=False)
def compute_df_parameters(df):
    viewings_numbered = [col for col in df.columns if re.match(r'^viewings-\d+$', col)]
    for i, viewing_column in enumerate(viewings_numbered):
        df[f'Visning {i}'] = df[viewing_column].apply(extract_datetime)

    df['sold'] = df['object-title'].str.contains('solgt', case=False, na=False)
    df['usable-area'] = df['info-usable-area'].fillna(df['info-usable-i-area'])
    df['balkong-area'] = df['info-open-area'].fillna(df['info-usable-b-area'])
    df['square-meter-price'] = df['pricing-total-price'] / df['usable-area']
    df[['Energikarakter', 'Oppvarmingskarakter']] = df['energy-label-info'].str.split(' - ', expand=True)
    return df

df = compute_df_parameters(df=df)

# Step 5: Valg 
with st.sidebar:
    st.title('Filtere')
    total_price_max = st.number_input(label='Totalpris (kr)', value=int(round(df['pricing-total-price'].max(),-3)), step=100000, max_value=int(round(df['pricing-total-price'].max(),-3)), min_value=4000000)
    df = df[df['pricing-total-price'] < total_price_max]
    #
    square_meter_price_max = st.number_input(label='Kvadratmeterpris (kr/m²)', value=int(round(df['square-meter-price'].max(),-3)), step=5000, max_value=int(round(df['square-meter-price'].max(),-3)), min_value=0)
    df = df[df['square-meter-price'] < square_meter_price_max]
    # 
    sold = st.toggle(label='Solgt?', value=False)
    df = df[df['sold'] == sold]
    #
    balkong_size = st.slider(label='Balkongstørrelse (m²)', value=0, step=1, max_value=20, min_value=0)
    df = df[df['balkong-area'] > balkong_size]
    #
    with st.expander('Energimerker'):
        #
        energikarakter = st.multiselect(label='Energikarakter', options=df['Energikarakter'].unique(), default=df['Energikarakter'].unique())
        df = df[df['Energikarakter'].isin(energikarakter)]
        #
        oppvaringskarakter = st.multiselect(label='Oppvarmingskarakter', options=df['Oppvarmingskarakter'].unique(), default=df['Oppvarmingskarakter'].unique())
        df = df[df['Oppvarmingskarakter'].isin(oppvaringskarakter)]
    #
    st.info('Blåere farge betyr at leiligheten er dyrere. Større sirkler betyr større areal.', icon=':material/info:')


# Step 6: Vise på kart
cmap = plt.cm.get_cmap('Blues')

def value_to_color(value, min_value, max_value):
    norm = (value - min_value) / (max_value - min_value)
    return to_hex(cmap(norm))

def scale_value(value, min_value, max_value):
    min_size, max_size = 1, 10
    return min_size + (value - min_value) / (max_value - min_value) * (max_size - min_size)

def format_value(value, suffix='', is_int=True):
    if pd.isna(value):
        return None
    if is_int:
        return f"{int(value):,}{suffix}".replace(',', ' ')
    return f"{value}{suffix}"

m = folium.Map(location=[df['latitude'].mean(), df['longitude'].mean()], zoom_start=12)
for _, row in df.iterrows():
    tooltip_parts = []
    address = row['object-address'].split(',')[0] if pd.notna(row['object-address']) else ''
    tooltip_parts.append(f"<i>{address}</i><br>")
    fields = [
        ("Totalpris", row['pricing-total-price'], " kr"),
        ("Prisantydning", row['pricing-incicative-price'], " kr"),
        ("Felleskost/mnd", row['pricing-common-monthly-cost'], " kr"),
        ("Fellesgjeld", row['pricing-joint-debt'], " kr"),
        ("Internt bruksareal", row['info-usable-i-area'], " m²"),
        ("Eksternt bruksareal", row['info-usable-e-area'], " m²"),
        ("Innglasset balkong", row['info-usable-b-area'], " m²"),
        ("Balkong/terrasse", row['info-open-area'], " m²"),
        ("Bruksareal", row['info-usable-area'], " m²"),
        ("Etasje", row['info-floor'], ""),
        ("Antall soverom", row['info-bedrooms'], ""),
        ("Antall rom", row['info-rooms'], ""),
        ("Byggeår", row['info-construction-year'], ""),
        ("Eierform", row['info-ownership-type'], ""),
        ("Kvadratmeterpris", row['square-meter-price'], " kr/m²"),
        ("Energikarakter", row['Energikarakter'], ""),
        ("Oppvarmingskarakter", row['Oppvarmingskarakter'], "")
    ]
    tooltip_parts.append("--- <br>")
    for label, value, suffix in fields:
        formatted = format_value(value, suffix, is_int=isinstance(value, (int, float)))
        if formatted:
            tooltip_parts.append(f"{label}: <strong>{formatted}</strong><br>")
    tooltip_content = "\n".join(tooltip_parts)
    folium.CircleMarker(
        location=[row['latitude'], row['longitude']],
        radius=scale_value(value=row['usable-area'], min_value=60, max_value=90),
        color=value_to_color(value=row['pricing-total-price'], min_value=5000000, max_value=7500000),
        fill=True,
        fill_color=value_to_color(value=row['pricing-total-price'], min_value=5000000, max_value=7500000),
        fill_opacity=0.5,
        tooltip=folium.Tooltip(tooltip_content)
    ).add_to(m)

satellite_url = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
satellite_attribution = 'Esri, Maxar, Earthstar Geographics, and the GIS User Community'
folium.TileLayer(
    tiles=satellite_url,
    attr=satellite_attribution,
    name='Satellite',
    overlay=True,
    control=True
).add_to(m)

cartodb_url = "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png"
cartodb_attribution = 'CartoDB, OpenStreetMap contributors'
folium.TileLayer(
    tiles=cartodb_url,
    attr=cartodb_attribution,
    name='CartoDB Positron',
    overlay=True,
    control=True
).add_to(m)

# https://asplanviak.maps.arcgis.com/home/item.html?id=8aa6b06460394ad797a59de82dead917
folium.LayerControl().add_to(m)

Fullscreen().add_to(m)


c1, c2 = st.columns([2, 1])
with c1:
    with st.container(border=True, height=400):
        st.write(f"**Det er {len(df)} leiligheter som vises på kartet**")
        last_object_clicked = st_folium(m, use_container_width=True, returned_objects=['last_object_clicked'], height=300)
        if last_object_clicked['last_object_clicked'] == None:
            st.stop()
        buffer_degrees = 60 / 111000  # ≈ 0.000045

        lat = last_object_clicked['last_object_clicked']['lat']
        lng = last_object_clicked['last_object_clicked']['lng']

        lat_min = lat - buffer_degrees
        lat_max = lat + buffer_degrees
        lng_min = lng - buffer_degrees
        lng_max = lng + buffer_degrees

        df = df[
            (df['latitude'] >= lat_min) & (df['latitude'] <= lat_max) &
            (df['longitude'] >= lng_min) & (df['longitude'] <= lng_max)
        ].reset_index(drop=True)
with c2:
    with st.container(border=True, height=400):
        st.write(f"**{df['object-address'][0].split(',')[0]}**")
        url = df['URL'].iloc[0]
        
        st.write(f"*{df['object-title'][0]}*")
        st.markdown(f"[Gå til annonsen]({url})", unsafe_allow_html=True)
        date_0 = df['Visning 0'][0]
        date_1 = df['Visning 1'][0]
        if date_0 is not None:
            st.write(f"Visningen er: {date_0.day}.{date_0.month} ({date_0})")
        if date_1 is not None:
            st.write(f"Visningen er: {date_1.day}.{date_1.month} ({date_1})")
        
        if pd.notna(df['preemption'][0]):
            st.write(f"Om forkjøpsrett: <{df['preemption'][0]}>")
        else:
            st.write('Det er ikke forkjøpsrett')
