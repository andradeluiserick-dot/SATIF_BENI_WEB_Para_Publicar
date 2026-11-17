"""SATIF BENI / Centro de monitoreo - versión web V2.

Prototipo independiente; fuentes: NASA FIRMS, NASA GIBS, Open-Meteo.
Nunca incluir una MAP_KEY dentro de este archivo ni en el navegador.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from html import escape
from pathlib import Path

import folium
from folium.plugins import Fullscreen, HeatMap, MarkerCluster, MeasureControl
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from core import (SATELLITES, attribute_municipalities, fetch_weather,
                  group_hotspots_grid, load_beni_polygons, parse_hotspots,
                  query_firms_period, to_geojson, to_kmz, to_shapefile_zip)

ROOT = Path(__file__).resolve().parent
POLY_FILE = ROOT / 'datos' / 'municipios_beni_2024.geojson'
DEMO_FILE = ROOT / 'datos' / 'datos_simulados.csv'

st.set_page_config(page_title='SATIF BENI | Centro de monitoreo',page_icon='🛰️',
                   layout='wide',initial_sidebar_state='expanded')

st.markdown('''
<style>
/* El contraste no depende del tema del sistema del visitante. */
[data-testid="stAppViewContainer"] {background:#f0f5fa!important;color:#183047!important}
[data-testid="stSidebar"] {background:#f8fafc!important;border-right:1px solid #d7e2ec!important}
[data-testid="stSidebar"] * {color:#1c3448}
.block-container {max-width:1720px;padding-top:1.25rem;padding-bottom:2.5rem}
h1,h2,h3,h4 {color:#122d44!important;letter-spacing:-.025em}
[data-testid="stMetric"] {background:#fff!important;border:1px solid #dce6ef;border-top:3px solid #21778b;border-radius:13px;padding:15px 16px;box-shadow:0 5px 14px #102d4609}
[data-testid="stMetricLabel"] p {color:#3b5970!important;font-weight:650!important}
[data-testid="stMetricValue"] {color:#102c45!important;font-weight:800!important}
[data-testid="stAlert"] {border-radius:12px}
[data-testid="stHorizontalBlock"] {gap:1.05rem}
[data-testid="stDataFrame"] {border:1px solid #dbe6f0;border-radius:11px}
[data-testid="stWidgetLabel"] p {color:#1f4257!important;font-weight:650}
.hero {background:linear-gradient(118deg,#0e2941,#11576a 70%,#1a6a67);border-radius:19px;
 padding:25px 28px;color:#fff;box-shadow:0 8px 30px #12365124;margin-bottom:19px}
.hero .eyebrow {font-size:.78rem;letter-spacing:.17em;font-weight:800;color:#9ce7d9;margin-bottom:7px}
.hero h1 {color:#fff!important;font-size:clamp(1.7rem,3vw,2.7rem);font-weight:850;margin:0}
.hero p {color:#d4eaf2;margin:7px 0 0;font-size:.95rem}
.hero .tag {display:inline-block;color:#d4fcf1;border:1px solid #76c9b4;background:#1f625f;
 padding:4px 10px;border-radius:60px;margin-top:13px;font-size:.75rem;font-weight:750}
.info-strip {background:#e5f2f5;color:#204c60;border:1px solid #c4dce7;padding:12px 17px;
 border-radius:11px;margin-bottom:17px;font-size:.9rem}
.kicker {font-size:.78rem;color:#287386;font-weight:850;letter-spacing:.12em;margin:16px 0 3px}
.legend {background:#fff;padding:12px;border-radius:10px;border:1px solid #dbe7f1;color:#364e64;font-size:.83rem;margin-top:8px}
.fine {font-size:.79rem;color:#567184;line-height:1.65}
.status-pill {display:inline-block;border-radius:6px;background:#e6f7ed;color:#126344;padding:4px 8px;font-size:.78rem;font-weight:750}
[data-testid="stSidebar"] [data-testid="stButton"] button[kind="primary"] {background:#1b6a80;color:white}
@media(max-width:720px){.block-container{padding:.65rem}.hero{padding:18px}.hero p{font-size:.84rem}}
</style>
''',unsafe_allow_html=True)

GIBS_LAYERS = {
    'VIIRS NOAA-21 · color natural':'VIIRS_NOAA21_CorrectedReflectance_TrueColor',
    'VIIRS NOAA-20 · color natural':'VIIRS_NOAA20_CorrectedReflectance_TrueColor',
    'VIIRS Suomi-NPP · color natural':'VIIRS_SNPP_CorrectedReflectance_TrueColor',
    'MODIS Terra · color natural':'MODIS_Terra_CorrectedReflectance_TrueColor',
    'MODIS Terra · bandas 7-2-1':'MODIS_Terra_CorrectedReflectance_Bands721',
}

@st.cache_data(ttl=12*3600,show_spinner=False)
def boundaries():
    return load_beni_polygons(POLY_FILE)

@st.cache_data(ttl=18*60,show_spinner=False)
def firms_cached(map_key: str, product: str, start_iso: str, days: int):
    return query_firms_period(map_key,product,start_iso,days)

@st.cache_data(ttl=25*60,show_spinner=False)
def weather_cached(lat: float, lon: float):
    return fetch_weather(lat,lon)


def server_key():
    value = os.environ.get('NASA_FIRMS_MAP_KEY','').strip()
    if value:
        return value
    try:
        return str(st.secrets.get('NASA_FIRMS_MAP_KEY','')).strip()
    except Exception:
        return ''


def fmt_num(x):
    return f'{int(x):,}'.replace(',','.')


def formatted_frp(v):
    try:
        return f'{float(v):.1f}'
    except Exception:
        return '—'


def color_frp(v):
    """No expresa peligro ni extensión quemada; codificación visual de FRP solamente."""
    if pd.isna(v): return '#64748b'
    if float(v)>=50: return '#dc2626'
    if float(v)>=10: return '#f97316'
    return '#eab308'


def municipality_center(muni, shapes):
    if muni=='Todo el Beni' or not shapes: return (-13.7,-65.15)
    from shapely.geometry import shape
    for feature in shapes.get('features',[]):
        if feature.get('properties',{}).get('nombre_mun') == muni:
            pt = shape(feature['geometry']).representative_point()
            return (round(float(pt.y),5),round(float(pt.x),5))
    return (-13.7,-65.15)


def gibs_url(layer:str,image_date:date):
    return ('https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/'
        f'{layer}/default/{image_date.isoformat()}/GoogleMapsCompatible_Level9/'
        '{z}/{y}/{x}.jpg')


def build_map(df, shapes, municipality, view, base, imagery_date, imagery_layer,
              grid_km=5, max_points=2500):
    center=municipality_center(municipality,shapes)
    m=folium.Map(location=center,zoom_start=7,tiles=None,prefer_canvas=True,
                 control_scale=True,zoom_control=True)
    folium.TileLayer('OpenStreetMap',name='Calles · OpenStreetMap',show=base=='Calles OSM').add_to(m)
    folium.TileLayer('CartoDB positron',name='Mapa claro',show=base=='Mapa claro').add_to(m)
    esri='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
    folium.TileLayer(tiles=esri,attr='Esri, Maxar y colaboradores',
                     name='Imagen satelital · Esri',show=base in ('Esri satélite','NASA GIBS')).add_to(m)
    if base=='NASA GIBS':
        folium.TileLayer(tiles=gibs_url(imagery_layer,imagery_date),
            attr='NASA EOSDIS GIBS',name=f'NASA GIBS · {imagery_date}',
            overlay=True,control=True,opacity=.92,max_zoom=19,max_native_zoom=9).add_to(m)
    if shapes:
        folium.GeoJson(
            shapes,name='Municipios · Beni',
            style_function=lambda f: {
                'color':'#21a58c' if municipality=='Todo el Beni' or f['properties'].get('nombre_mun')==municipality else '#a7b9ad',
                'weight':2.7 if municipality!='Todo el Beni' and f['properties'].get('nombre_mun')==municipality else 1.1,
                'fillColor':'#35b3a0','fillOpacity':.11 if municipality=='Todo el Beni' or f['properties'].get('nombre_mun')==municipality else .035},
            tooltip=folium.GeoJsonTooltip(fields=['nombre_mun','nombre_prov'],aliases=['Municipio','Provincia'],sticky=False)
        ).add_to(m)
    if not df.empty:
        show=df.head(max_points)
        if view=='Mapa de calor (densidad)':
            HeatMap(show[['latitude','longitude']].values.tolist(),name='Densidad de detecciones',
                    radius=18,blur=13,min_opacity=.3,show=True).add_to(m)
        elif view=='Cuadrícula aproximada':
            tile = group_hotspots_grid(show,grid_km)
            group=folium.FeatureGroup(name=f'Celdas · aprox. {grid_km} km')
            for row in tile.head(900).itertuples(index=False):
                r=6+min(17,float(row.detecciones)*1.1)
                folium.CircleMarker([row.latitud,row.longitud],radius=r,
                    color='#a34119',fill_color='#ed793e',fill_opacity=.7,
                    tooltip=f'{row.detecciones} detecciones · {row.fecha}',
                    popup=folium.Popup(f'{row.municipio}: {row.detecciones} detecciones en celda aproximada. No indica hectáreas quemadas.',max_width=260)).add_to(group)
            group.add_to(m)
        else:
            markers=MarkerCluster(name='Focos satelitales',disableClusteringAtZoom=11,show=True)
            for row in show.itertuples(index=False):
                clr=color_frp(row.frp)
                popup=(f'<b>{escape(str(row.municipio))}</b><br>'
                    f'{escape(str(row.fecha))} {escape(str(row.hora_utc))} UTC<br>'
                    f'Satélite: {escape(str(row.satellite))}<br>'
                    f'FRP: {formatted_frp(row.frp)} MW<br>'
                    f'Confianza: {escape(str(row.confidence))}<br>'
                    f'Lat/Lon: {row.latitude:.5f}, {row.longitude:.5f}<hr>'
                    'Detección térmica: no equivale a incendio confirmado.')
                folium.CircleMarker([row.latitude,row.longitude],radius=5.4,
                     color='#fff',weight=1.4,fill_color=clr,fill_opacity=.95,
                     tooltip=f'{row.fecha} · {escape(str(row.municipio))}',
                     popup=folium.Popup(popup,max_width=300)).add_to(markers)
            markers.add_to(m)
    if municipality!='Todo el Beni' and shapes:
        from shapely.geometry import shape
        feature=next((f for f in shapes['features'] if f['properties'].get('nombre_mun')==municipality),None)
        if feature:
            w,s,e,n=shape(feature['geometry']).bounds
            m.fit_bounds([[s,w],[n,e]])
    if municipality=='Todo el Beni':
        m.fit_bounds([[-16.9,-68.5],[-10.0,-61.0]])
    folium.LayerControl(collapsed=True).add_to(m)
    Fullscreen(position='topright').add_to(m)
    MeasureControl(position='topright',primary_length_unit='kilometers',primary_area_unit='hectares').add_to(m)
    return m


def report_html(data, muni, meta):
    """Reporte independiente, HTML imprimible, no incluye ningún secreto."""
    now=datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    daily=(data.groupby('fecha').size().sort_index().items() if not data.empty else [])
    rows=''.join(f'<tr><td>{escape(str(day))}</td><td>{int(count)}</td></tr>' for day,count in daily)
    munis=(data.groupby('municipio').size().sort_values(ascending=False).head(15).items() if not data.empty else [])
    places=''.join(f'<tr><td>{escape(str(m))}</td><td>{int(count)}</td></tr>' for m,count in munis)
    return f'''<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>Reporte SATIF BENI</title><style>body{{font:14px Arial;color:#153047;max-width:940px;margin:32px auto;padding:20px}}
header{{background:#123d55;color:white;padding:24px;border-radius:12px}}h1{{margin:4px 0}}h2{{margin-top:26px;color:#176477}}
table{{border-collapse:collapse;width:100%;margin-top:12px}}td,th{{text-align:left;padding:9px;border-bottom:1px solid #dfe8f0}}
th{{background:#edf5fa}}.note{{background:#fff4e4;padding:14px;border-left:4px solid #db8a2a;margin-top:22px}}
@media print{{body{{margin:0}}}}</style></head><body>
<header><small>MONITOREO TÉCNICO · PROTOTIPO INDEPENDIENTE</small><h1>SATIF BENI</h1><div>Informe de detecciones térmicas satelitales</div></header>
<p><b>Territorio:</b> {escape(muni)}<br><b>Consulta:</b> {escape(meta)}<br><b>Generado:</b> {now}</p>
<h2>Resumen</h2><p><b>Detecciones filtradas:</b> {len(data):,} (no incendios confirmados)</p>
<h2>Evolución por fecha (UTC)</h2><table><tr><th>Fecha</th><th>Detecciones</th></tr>{rows}</table>
<h2>Distribución municipal</h2><table><tr><th>Municipio</th><th>Detecciones</th></tr>{places}</table>
<div class="note"><b>Interpretación:</b> Los focos detectados por satélite NO confirman incendios;
no delimitan áreas quemadas ni cuantifican propagación. FRP mide potencia radiativa, no riesgo oficial.
Los datos pueden tener retrasos y limitaciones por nubosidad y cobertura satelital.</div>
<footer><p>Fuente: NASA FIRMS, según el conjunto de datos seleccionado. Cartografía municipal referencial.
Coordenadas SIG: WGS84 / EPSG:4326. Fecha de elaboración en UTC.</p></footer></body></html>'''.encode('utf-8')


st.markdown('''<div class="hero"><div class="eyebrow">GEOPLATAFORMA DE MONITOREO AMBIENTAL · BOLIVIA</div>
<h1>🛰️ SATIF BENI <span style="color:#89e0cf">/</span> Centro de monitoreo</h1>
<p>Focos de calor NASA FIRMS · imágenes diarias NASA GIBS · meteorología · municipios · informes SIG</p>
<div class="tag">PROTOTIPO INDEPENDIENTE · NO EMITE ALERTAS OFICIALES</div></div>''',unsafe_allow_html=True)

with st.sidebar:
    st.markdown('### ⚙️ Centro de control')
    st.caption('Fuentes satelitales y análisis territorial')
    source=st.radio('Origen de las detecciones',
        ['NASA FIRMS · datos reales','Importar CSV NASA/INPE','Demostración ficticia'],
        help='No confundir datos de prueba con datos de satélite.')
    try:
        shapes=boundaries()
        st.success(f"Cartografía municipal: {len(shapes['features'])} unidades cargadas")
    except Exception:
        shapes=None
        st.warning('No se pudo cargar el mapa municipal. Se utilizará una región aproximada.')
    if st.button('↻ Actualizar cartografía',use_container_width=True):
        boundaries.clear()
        st.rerun()

    raw=None
    context='Sin consulta'
    is_demo=False
    if source.startswith('NASA'):
        key=server_key()
        if key:
            st.success('Conexión NASA: clave configurada en el servidor')
        else:
            st.error('NASA sin configurar: falta MAP_KEY en los secretos de Streamlit.')
            st.markdown('[Solicitar clave NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/api/map_key/)')
            st.caption('En Streamlit Cloud: Manage app → Settings → Secrets. Nunca pongas la clave en GitHub ni dentro de un archivo HTML.')
        sat_options=list(SATELLITES)
        sensors=st.multiselect('Satélites para consultar',sat_options,
                    default=sat_options[:2],max_selections=3)
        period_mode=st.radio('Periodo de consulta',['Últimos días','Fechas definidas'],horizontal=True)
        if period_mode=='Últimos días':
            n_days=st.slider('Número de días',1,15,3)
            period_start=date.today()-timedelta(days=n_days-1)
            period_end=date.today()
        else:
            period=st.date_input('Desde / Hasta (UTC)',
                value=(date.today()-timedelta(days=2),date.today()),
                max_value=date.today())
            if isinstance(period,tuple) and len(period)==2:
                period_start, period_end=period
            else:
                period_start=period_end=None
            n_days=((period_end-period_start).days+1 if period_start and period_end else 0)
        st.caption('Consultas de hasta 5 días por llamada, agrupadas en bloques. Máximo 15 días por búsqueda.')
        if st.button('🔄 Consultar NASA FIRMS',type='primary',use_container_width=True):
            if not key:
                st.error('Primero guarda la nueva MAP_KEY en los secretos de Streamlit.')
            elif not sensors:
                st.warning('Selecciona un satélite.')
            elif n_days<1 or n_days>15 or not period_start or not period_end:
                st.warning('Elige un periodo válido de 1 a 15 días.')
            else:
                frames=[]; failures=[]
                with st.spinner('Consultando NASA FIRMS mediante el servidor…'):
                    for label in sensors:
                        product=SATELLITES[label]
                        for offset in range(0,n_days,5):
                            days=min(5,n_days-offset)
                            start=(period_start+timedelta(days=offset)).isoformat()
                            try:
                                frames.append(firms_cached(key,product,start,days))
                            except Exception as exc:
                                failures.append(f'{label} · {start}: {str(exc)}')
                if frames:
                    joined=pd.concat(frames,ignore_index=True)
                    joined=joined.drop_duplicates(subset=['latitude','longitude','fecha','hora_utc','satellite'])
                    st.session_state['nasa_df']=joined
                    st.session_state['nasa_meta']=(f'{period_start} a {period_end} UTC · '+', '.join(sensors))
                    st.session_state['nasa_stamp']=datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')
                    st.session_state['nasa_failures']=failures
                else:
                    st.error('No se obtuvo ningún bloque válido de NASA FIRMS. Comprueba la clave, rango, disponibilidad y cuota.')
                    for err in failures[:3]: st.caption(err)
        if 'nasa_df' in st.session_state:
            raw=st.session_state['nasa_df']
            context=st.session_state.get('nasa_meta','NASA FIRMS')
            st.caption('Última consulta desde servidor: '+st.session_state.get('nasa_stamp','—'))
            if st.session_state.get('nasa_failures'):
                st.warning(f"Consulta PARCIAL: fallaron {len(st.session_state['nasa_failures'])} bloques. No interpretar el total como exhaustivo.")
        else:
            st.info('Pulsa «Consultar NASA FIRMS» para obtener detecciones reales.')
    elif source.startswith('Importar'):
        upload=st.file_uploader('Subir CSV de focos',type='csv',help='Ej.: NASA FIRMS (latitude, longitude, acq_date).')
        if upload:
            try:
                raw=parse_hotspots(upload)
                context='CSV importado · '+upload.name
                st.success(f'{len(raw)} registros aceptados')
            except Exception as exc:
                st.error(f'No se pudo leer el CSV: {str(exc)}')
    else:
        raw=parse_hotspots(DEMO_FILE)
        context='SIMULACIÓN · datos inventados, no usar para emergencias'
        is_demo=True
        st.warning('🧪 DATOS FICTICIOS. Solo sirven para probar los controles.')
    st.divider()
    st.caption('**Fuentes y ayudas**')
    st.markdown('[NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/api/area) · '
                '[NASA Worldview](https://worldview.earthdata.nasa.gov/) · '
                '[Open-Meteo](https://open-meteo.com/en/docs)')

if is_demo:
    st.error('MODO DEMOSTRACIÓN — Los puntos dibujados NO son detecciones reales.',icon='⚠️')

if raw is None:
    data=parse_hotspots(pd.DataFrame(columns=['latitude','longitude','acq_date','frp']))
    data['municipio']=pd.Series(dtype='str');data['provincia']=pd.Series(dtype='str')
else:
    data=attribute_municipalities(raw,shapes)

if shapes is None:
    st.warning('⚠️ Sin capa municipal, el análisis utiliza solo un recuadro aproximado. No se pueden asignar detecciones a municipios con certeza.')

municipios=sorted({f['properties'].get('nombre_mun','') for f in shapes['features'] if f.get('properties',{}).get('nombre_mun')}) if shapes else []
if 'Guayaramerín' in municipios:
    default=municipios.index('Guayaramerín')+1
else:
    default=0

st.markdown('<div class="kicker">01 / FILTROS GEOGRÁFICOS Y VISUALIZACIÓN</div>',unsafe_allow_html=True)
col_a,col_b,col_c,col_d=st.columns([1.65,1.05,1.15,1.2])
with col_a:
    muni=st.selectbox('Municipio', ['Todo el Beni']+municipios,index=default,
                      help='Municipios del Beni, cartografía referencial.')
with col_b:
    if not data.empty:
        dates=sorted(data['fecha'].dropna().unique())
        filter_dates=st.select_slider('Fechas de detección (UTC)',options=dates,
            value=(dates[0],dates[-1])) if len(dates)>1 else (dates[0],dates[0])
    else:
        st.text_input('Fechas de detección (UTC)',value='Sin datos',disabled=True)
        filter_dates=(None,None)
with col_c:
    view=st.selectbox('Representación', ['Focos individuales','Mapa de calor (densidad)','Cuadrícula aproximada'])
with col_d:
    base=st.selectbox('Mapa base',['Esri satélite','NASA GIBS','Mapa claro','Calles OSM'])

filtered=data.copy()
if filter_dates[0] is not None:
    filtered=filtered[(filtered.fecha>=filter_dates[0]) & (filtered.fecha<=filter_dates[1])]
if muni!='Todo el Beni':
    filtered=filtered[filtered.municipio==muni]
filtered=filtered.sort_values('instante_utc',ascending=False).reset_index(drop=True)

k1,k2,k3,k4,k5=st.columns(5)
count=len(filtered)
last=filtered['instante_utc'].max() if count else None
k1.metric('Detecciones satelitales',fmt_num(count),help='No son incendios confirmados.')
k2.metric('Municipios con focos',fmt_num(filtered.municipio.nunique()) if count and shapes else '—')
k3.metric('Días registrados',fmt_num(filtered.fecha.nunique()) if count else '0')
k4.metric('FRP promedio',f'{filtered.frp.mean():.1f} MW' if count else '—',help='Potencia radiativa del fuego; no mide área quemada.')
k5.metric('Último registro UTC',last.strftime('%d/%m %H:%M') if last is not None else '—')

recent=0
if count and not is_demo:
    recent=int((filtered.instante_utc >= pd.Timestamp.now(tz='UTC')-pd.Timedelta(hours=24)).sum())
if recent:
    st.warning(f'🛰️ {fmt_num(recent)} detecciones en las últimas 24 horas en la zona seleccionada. Verifica su estado en campo; no son incendios confirmados.')
elif count and is_demo:
    st.info('Los indicadores usan datos simulados. No deben utilizarse en decisiones operativas.')
else:
    st.info('Sin registros para este filtro. Esto NO garantiza ausencia de incendios.')

st.markdown('<div class="kicker">02 / MAPA DE FOCOS DE CALOR</div>',unsafe_allow_html=True)
mapleft,mapright=st.columns([3.25,1.08],gap='large')
with mapright:
    st.markdown('**Capas NASA GIBS**')
    layer_name=st.selectbox('Imagen diaria',list(GIBS_LAYERS.keys()))
    imagery_date=st.date_input('Fecha de imagen',value=date.today()-timedelta(days=2),
                   max_value=date.today(),key='gibs_date')
    grid_km=st.select_slider('Celda de agrupación (km)',options=[3,5,8,10,15],value=5)
    st.markdown('''<div class="legend"><b>Intensidad de FRP, sólo visual:</b><br>
    🟡 Menor de 10 MW<br>🟠 Entre 10 y 49 MW<br>🔴 50 MW o más<br><br>
    <b>No representa:</b> riesgo oficial, superficie afectada ni perímetro de incendio.</div>''',unsafe_allow_html=True)
    st.caption('Los mosaicos de NASA GIBS pueden demorarse en publicarse; si no están disponibles, selecciona Esri satélite.')
with mapleft:
    if len(filtered)>2500:
        st.caption('Mostrando 2.500 puntos recientes en el mapa. Las estadísticas y exportaciones incluyen todos los registros filtrados.')
    mp=build_map(filtered,shapes,muni,view,base,imagery_date,GIBS_LAYERS[layer_name],grid_km)
    st_folium(mp,height=580,width=None,returned_objects=[],key='beni_map_v2')
    st.caption('Herramienta de medición en el mapa · WGS84 (EPSG:4326) · imágenes Esri/OSM/NASA.')

with st.expander('🛰️ Comparar imágenes satelitales antes y después (NASA GIBS)'):
    before_col,after_col=st.columns(2)
    with before_col:
        before_date=st.date_input('Fecha anterior',value=date.today()-timedelta(days=8),max_value=date.today(),key='gibs_before')
    with after_col:
        after_date=st.date_input('Fecha posterior',value=date.today()-timedelta(days=2),max_value=date.today(),key='gibs_after')
    if before_date>=after_date:
        st.warning('La fecha anterior debe ser menor que la posterior.')
    if st.button('🛰️ Mostrar comparación',use_container_width=True):
        st.session_state['compare_dates']=(before_date,after_date)
    if 'compare_dates' in st.session_state:
        d0,d1=st.session_state['compare_dates']
        t1,t2=st.columns(2)
        with t1:
            st.markdown(f'**ANTES · {d0}**')
            st_folium(build_map(filtered.head(700),shapes,muni,'Focos individuales','NASA GIBS',d0,GIBS_LAYERS[layer_name]),
                      height=390,width=None,returned_objects=[],key='map_before')
        with t2:
            st.markdown(f'**DESPUÉS · {d1}**')
            st_folium(build_map(filtered.head(700),shapes,muni,'Focos individuales','NASA GIBS',d1,GIBS_LAYERS[layer_name]),
                      height=390,width=None,returned_objects=[],key='map_after')
        st.caption('Comparación visual, no cálculo automático de cicatrices de quema, dNBR ni hectáreas quemadas.')

st.markdown('<div class="kicker">03 / EVOLUCIÓN TEMPORAL Y CONCENTRACIONES</div>',unsafe_allow_html=True)
chart_left,chart_right=st.columns([1.45,1])
with chart_left:
    st.subheader('Detecciones por día (UTC)')
    if not filtered.empty:
        daily=filtered.groupby('fecha').size().rename('Detecciones')
        st.bar_chart(daily,height=285)
    else: st.caption('Consulta NASA FIRMS o importa un CSV para ver los registros.')
with chart_right:
    st.subheader('Municipios con más detecciones')
    if not filtered.empty and shapes:
        grouped=filtered.groupby('municipio').size().sort_values(ascending=False).head(10)
        st.bar_chart(grouped.rename('Detecciones'),height=285,horizontal=True)
    else: st.caption('Se requiere una capa municipal y focos atribuidos.')

with st.expander('🟠 Ver núcleos de detecciones cercanas (agrupación aproximada)'):
    if filtered.empty:
        st.info('Aún no hay puntos para calcular agrupaciones.')
    else:
        clusters=group_hotspots_grid(filtered,grid_km)
        top=clusters.head(20).rename(columns={'fecha':'Fecha UTC','municipio':'Municipio',
                    'detecciones':'Nº detecciones','latitud':'Latitud','longitud':'Longitud','frp_max_mw':'FRP máximo (MW)'})
        st.dataframe(top[['Fecha UTC','Municipio','Nº detecciones','FRP máximo (MW)','Latitud','Longitud']],
                     hide_index=True,use_container_width=True)
        st.download_button('⬇ Descargar agrupaciones CSV',clusters.to_csv(index=False).encode('utf-8-sig'),
            file_name='satif_beni_agrupaciones.csv',mime='text/csv')
        st.caption('Se agrupan observaciones por fecha UTC y celdas angulares equivalentes aproximadamente a los km indicados. No son incendios independientes ni áreas quemadas.')

st.markdown('<div class="kicker">04 / METEOROLOGÍA Y CONDICIONES DE VIGILANCIA</div>',unsafe_allow_html=True)
met_a,met_b=st.columns([1,1.55],gap='large')
lat,lon=municipality_center(muni,shapes)
with met_a:
    st.markdown(f'**Punto de referencia: {muni}**')
    st.caption(f'Latitud {lat:.4f}, longitud {lon:.4f} · información meteorológica modelada para el centro seleccionado.')
    get_met=st.button('🌡️ Consultar meteorología (Open-Meteo)',type='secondary',use_container_width=True)
    if get_met:
        try:
            st.session_state['weather_data']=weather_cached(lat,lon)
            st.session_state['weather_point']=(lat,lon)
        except Exception as exc:
            st.error(str(exc))
    met=st.session_state.get('weather_data') if st.session_state.get('weather_point')==(lat,lon) else None
    with st.expander('Umbrales orientativos, editables'):
        tlimit=st.number_input('Temperatura desde (°C)',min_value=0,max_value=60,value=30)
        wlimit=st.number_input('Viento desde (km/h)',min_value=0,max_value=140,value=30)
        hlimit=st.number_input('Humedad igual o menor que (%)',min_value=0,max_value=100,value=30)
with met_b:
    if not met:
        st.info('Pulsa «Consultar meteorología» para ver los valores actuales del modelo y el pronóstico próximo.')
    else:
        cur=met['current']
        a,b,c,d=st.columns(4)
        a.metric('Temperatura',f"{cur.get('temperature_2m','—')} °C")
        b.metric('Humedad relativa',f"{cur.get('relative_humidity_2m','—')} %")
        c.metric('Viento',f"{cur.get('wind_speed_10m','—')} km/h")
        d.metric('Ráfagas',f"{cur.get('wind_gusts_10m','—')} km/h")
        st.caption(f"Modelo válido a las {cur.get('time','—')} (hora Bolivia UTC−4); dirección de viento: {cur.get('wind_direction_10m','—')}°; nubosidad: {cur.get('cloud_cover','—')}%.")
        breaches=[]
        vals=[cur.get('temperature_2m'),cur.get('wind_speed_10m'),cur.get('relative_humidity_2m')]
        if all(isinstance(v,(float,int)) for v in vals):
            if vals[0]>=tlimit: breaches.append('temperatura alta')
            if vals[1]>=wlimit: breaches.append('viento fuerte')
            if vals[2]<=hlimit: breaches.append('humedad baja')
            if breaches:
                st.warning('⚠️ Condiciones que ameritan vigilancia: '+', '.join(breaches)+'. Estos umbrales son orientativos, no una alerta oficial.')
            else:
                st.success('Los umbrales meteorológicos seleccionados no están superados. Esto no descarta incendios.')
        else:
            st.info('Datos meteorológicos incompletos: no se evalúan umbrales.')
        hourly=met.get('hourly',{})
        if hourly.get('time'):
            frame=pd.DataFrame({'Hora':hourly['time'],
                 'Temperatura (°C)':hourly.get('temperature_2m',[]),
                 'Humedad (%)':hourly.get('relative_humidity_2m',[]),
                 'Viento (km/h)':hourly.get('wind_speed_10m',[]),
                 'Lluvia (mm)':hourly.get('precipitation',[])})
            if not frame.empty:
                from_zone=cur.get('time','')[:13]
                next12=frame[frame.Hora.str[:13]>=from_zone].head(12).set_index('Hora')
                if not next12.empty:
                    st.line_chart(next12[['Temperatura (°C)','Viento (km/h)']],height=185)
                    with st.expander('Pronóstico de las próximas 12 horas'):
                        st.dataframe(next12,hide_index=False,use_container_width=True)

st.markdown('<div class="kicker">05 / DATOS Y EXPORTACIÓN PARA ARCGIS Y QGIS</div>',unsafe_allow_html=True)
if not filtered.empty:
    cols=['fecha','hora_utc','municipio','provincia','latitude','longitude','frp','satellite','confidence','daynight']
    st.dataframe(filtered[cols].rename(columns={'fecha':'Fecha UTC','hora_utc':'Hora UTC','municipio':'Municipio',
        'provincia':'Provincia','latitude':'Latitud','longitude':'Longitud','frp':'FRP MW',
        'satellite':'Satélite','confidence':'Confianza','daynight':'Día/Noche'}),
        hide_index=True,use_container_width=True,height=300)
    dl_a,dl_b,dl_c,dl_d,dl_e=st.columns(5)
    dl_a.download_button('⬇ CSV',filtered[cols].to_csv(index=False).encode('utf-8-sig'),
         file_name='SATIF_Beni_focos.csv',mime='text/csv',use_container_width=True)
    dl_b.download_button('⬇ GeoJSON',to_geojson(filtered),
         file_name='SATIF_Beni_focos.geojson',mime='application/geo+json',use_container_width=True)
    dl_c.download_button('⬇ KMZ',to_kmz(filtered),
         file_name='SATIF_Beni_focos.kmz',mime='application/vnd.google-earth.kmz',use_container_width=True)
    dl_d.download_button('⬇ SHP (ZIP)',to_shapefile_zip(filtered),
         file_name='SATIF_Beni_focos_SHP.zip',mime='application/zip',use_container_width=True)
    dl_e.download_button('⬇ Informe HTML',report_html(filtered,muni,context),
         file_name='SATIF_Beni_informe.html',mime='text/html',use_container_width=True)
else:
    st.info('Las descargas estarán disponibles después de cargar detecciones para el área seleccionada.')

st.markdown('''<div class="info-strip"><b>Para ArcGIS 10.8:</b> CSV, GeoJSON, KMZ y SHP se entregan en WGS84 (EPSG:4326).
Para trabajar en Guayaramerín, reproyecta la capa a <b>WGS 1984 UTM Zone 20S (EPSG:32720)</b> usando la herramienta Project.
Para municipios de otras zonas verifica su huso UTM.</div>''',unsafe_allow_html=True)
with st.expander('📘 Metodología, fuentes y limitaciones'):
    st.markdown('''
- **NASA FIRMS:** detecciones térmicas por MODIS y VIIRS. Se consultan los satélites elegidos, por bloques de 1 a 5 días y una caja geográfica que contiene Beni; el recorte exacto se hace por intersección con los polígonos municipales.
- **NASA GIBS:** imágenes diarias para inspección visual de la superficie. Puede haber nubosidad, fechas sin imagen o desfase en publicación; dos imágenes no sustituyen un cálculo dNBR.
- **Open-Meteo:** información meteorológica modelada para un punto de referencia. **No** es la meteorología histórica de cada detección.
- **Agrupaciones:** celdas aproximadas y densidades de puntos, no número de incendios, ni tamaño del incendio, ni hectáreas quemadas.
- **Cartografía municipal:** datos referenciales 2024, no son pronunciamiento de jurisdicción ni límites definitivos.
- **Alcance:** plataforma independiente de demostración técnica. No sustituye reportes oficiales, evaluación en campo ni gestión de emergencias. Los resultados parciales y retrasos de satélite se deben interpretar con cautela.

Fuentes: [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/api/area) ·
[NASA GIBS](https://gibs.earthdata.nasa.gov/) ·
[Open-Meteo](https://open-meteo.com/en/docs) ·
[Municipios Bolivia 2024](https://lab-tecnosocial.github.io/municipios-bolivia-2024/).
    ''')
st.caption(f'🛰️ SATIF BENI V2 · {escape(context)} · Monitoreo bajo demanda · Datos satelitales ≠ incendios confirmados.')
