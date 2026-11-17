"""Motor de datos SATIF Beni — prototipo educativo, no servicio oficial."""
from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring

import pandas as pd
import requests
from shapely.geometry import Point, shape, mapping

# Caja geográfica de consulta amplia; el recorte exacto se hace con los polígonos.
BENI_BBOX = (-68.4, -16.9, -61.0, -10.0)
BASE_MUNICIPIOS = (
    "https://lab-tecnosocial.github.io/municipios-bolivia-2024/"
    "municipios_bolivia_2024.geojson"
)
SATELLITES = {
    "VIIRS NOAA-21 (375 m)": "VIIRS_NOAA21_NRT",
    "VIIRS NOAA-20 (375 m)": "VIIRS_NOAA20_NRT",
    "VIIRS Suomi-NPP (375 m)": "VIIRS_SNPP_NRT",
    "MODIS Terra/Aqua (1 km)": "MODIS_NRT",
}


def load_beni_polygons(local_file: str | Path, *, force_download=False):
    """Obtiene geometrías de 2024, filtradas por Beni (código 08).

    Los polígonos se usan solo para análisis referencial de detecciones.
    """
    path = Path(local_file)
    geojson = None
    if path.exists() and not force_download:
        with path.open('r', encoding='utf-8') as f:
            geojson = json.load(f)
    else:
        response = requests.get(BASE_MUNICIPIOS, timeout=(8, 35))
        response.raise_for_status()
        geojson = response.json()
    features = []
    for feat in geojson.get('features', []):
        p = feat.get('properties', {})
        if str(p.get('idep', '')).zfill(2) == '08' or str(p.get('nombre_dep', '')).casefold().strip() == 'beni':
            if feat.get('geometry'):
                features.append(feat)
    if not features:
        raise ValueError('La capa no contiene municipios del Beni (idep = 08).')
    clipped = {"type": "FeatureCollection", "features": features}
    if not path.exists() or force_download:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(clipped, ensure_ascii=False), encoding='utf-8')
    return clipped


def parse_hotspots(source):
    """Lee CSV NASA FIRMS o CSV con columnas latitude, longitude, acq_date.
    Las horas NASA se expresan en UTC; no se atribuye UTC-4 de forma ficticia.
    """
    if isinstance(source, pd.DataFrame):
        df = source.copy()
    else:
        df = pd.read_csv(source, encoding='utf-8-sig')
    df.columns = [str(c).strip().lower().replace(' ', '_') for c in df.columns]
    aliases = {'latitud': 'latitude', 'longitud': 'longitude', 'fecha': 'acq_date',
               'hora': 'acq_time', 'radiative_power': 'frp', 'municipality': 'municipio'}
    df = df.rename(columns={k: v for k,v in aliases.items() if k in df.columns and v not in df.columns})
    missing = {'latitude', 'longitude', 'acq_date'} - set(df.columns)
    if missing:
        raise ValueError('Faltan columnas obligatorias: ' + ', '.join(sorted(missing)))
    for col in ('latitude','longitude','frp'):
        if col not in df.columns:
            df[col] = 0 if col == 'frp' else None
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df['acq_date'] = pd.to_datetime(df['acq_date'], errors='coerce', utc=True)
    df = df.dropna(subset=['latitude','longitude','acq_date']).copy()
    df = df[df['latitude'].between(-90,90) & df['longitude'].between(-180,180)]
    df['frp'] = df['frp'].fillna(0).clip(lower=0)
    if 'acq_time' not in df:
        df['acq_time'] = '0000'
    def clean_time(value):
        txt = str(value).split('.')[0].strip().replace(':','')
        if txt.isdigit():
            txt = txt.zfill(4)
            if len(txt) == 4 and 0 <= int(txt[:2]) <= 23 and 0 <= int(txt[2:]) <= 59:
                return txt
        return '0000'
    df['acq_time'] = df['acq_time'].map(clean_time)
    df['fecha'] = df['acq_date'].dt.strftime('%Y-%m-%d')
    df['hora_utc'] = df['acq_time'].map(lambda t: f'{t[:2]}:{t[2:]}')
    df['instante_utc'] = pd.to_datetime(df['fecha'] + ' ' + df['hora_utc'], utc=True)
    for col in ('satellite', 'confidence', 'daynight', 'instrument'):
        if col not in df.columns:
            df[col] = '—'
        df[col] = df[col].fillna('—').astype(str)
    df = df.drop_duplicates(subset=['latitude','longitude','fecha','acq_time','satellite'])
    return df.reset_index(drop=True)


def attribute_municipalities(data: pd.DataFrame, geojson: dict | None):
    """Recorta al Beni usando geometrías, sin etiquetar por punto cercano."""
    df = data.copy()
    if not geojson or not geojson.get('features'):
        west, south, east, north = BENI_BBOX
        df = df[df.longitude.between(west,east) & df.latitude.between(south,north)].copy()
        df['municipio'] = 'Sin identificar — falta límite'
        df['provincia'] = '—'
        df.attrs['approximate'] = True
        return df
    boundaries = []
    for feat in geojson['features']:
        geom = shape(feat['geometry'])
        if geom.is_empty:
            continue
        prop = feat.get('properties', {})
        boundaries.append((geom, str(prop.get('nombre_mun','Sin identificar')),
                           str(prop.get('nombre_prov','—'))))
    municipality, province = [], []
    for lon, lat in zip(df.longitude, df.latitude):
        pt = Point(float(lon), float(lat))
        found = next(((name, prov) for polygon, name, prov in boundaries if polygon.covers(pt)),
                     ('Fuera del Beni', '—'))
        municipality.append(found[0]); province.append(found[1])
    df['municipio'], df['provincia'] = municipality, province
    df = df[df['municipio'] != 'Fuera del Beni'].copy()
    df.attrs['approximate'] = False
    return df


def query_firms(map_key: str, product: str, day_range: int):
    """API NASA: /api/area/csv/{key}/{source}/{bbox}/{1..5}; UTC."""
    map_key = map_key.strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,128}', map_key):
        raise ValueError('La clave NASA FIRMS tiene un formato no válido.')
    if product not in SATELLITES.values() or not 1 <= int(day_range) <= 5:
        raise ValueError('Satélite o cantidad de días inválidos.')
    bounds = ','.join(map(str, BENI_BBOX))
    url = f'https://firms.modaps.eosdis.nasa.gov/api/area/csv/{map_key}/{product}/{bounds}/{day_range}'
    try:
        response = requests.get(url, timeout=(10, 50), headers={'User-Agent':'SATIF-Beni-Web/1.0'})
        response.raise_for_status()
    except requests.RequestException as exc:
        # No exponer URLs de error: contienen la MAP_KEY privada.
        code = getattr(getattr(exc, 'response', None), 'status_code', None)
        message = f'NASA FIRMS no respondió correctamente (HTTP {code}).' if code else 'No se pudo conectar con NASA FIRMS.'
        raise ValueError(message + ' Comprueba la clave, tu cuota de API y vuelve a intentar.') from None
    if 'latitude' not in response.text[:1500].lower():
        raise ValueError('NASA no devolvió un CSV de focos. Comprueba tu MAP_KEY y el servicio FIRMS.')
    return parse_hotspots(io.StringIO(response.text))


def to_geojson(df):
    features = []
    for _, row in df.iterrows():
        props = {"fecha_utc":str(row.get('fecha','')),
                 "hora_utc":str(row.get('hora_utc','')),
                 "municipio":str(row.get('municipio','')),
                 "provincia":str(row.get('provincia','')),
                 "satelite":str(row.get('satellite','')),
                 "confianza":str(row.get('confidence','')),
                 "frp_mw":float(row.get('frp',0))}
        features.append({'type':'Feature','geometry':mapping(Point(float(row.longitude),float(row.latitude))), 'properties':props})
    return json.dumps({'type':'FeatureCollection','features':features},ensure_ascii=False,indent=2).encode('utf-8')


def to_kmz(df):
    ns = 'http://www.opengis.net/kml/2.2'
    kml = Element('kml', {'xmlns':ns})
    doc = SubElement(kml,'Document')
    SubElement(doc,'name').text='Detecciones satelitales — SATIF Beni (prototipo)'
    for _, row in df.iterrows():
        pm = SubElement(doc,'Placemark')
        SubElement(pm,'name').text=f"{row.get('municipio','')} | {row.get('fecha','')}"
        SubElement(pm,'description').text=(f"Detección satelital — no confirma incendio. "
            f"Hora UTC: {row.get('hora_utc','')} | Satélite: {row.get('satellite','')} "
            f"| FRP: {float(row.get('frp',0)):.1f} MW")
        point = SubElement(pm,'Point')
        SubElement(point,'coordinates').text=f'{float(row.longitude):.7f},{float(row.latitude):.7f},0'
    output = io.BytesIO()
    with zipfile.ZipFile(output,mode='w',compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('detecciones.kml', tostring(kml,encoding='utf-8',xml_declaration=True))
    return output.getvalue()


def to_shapefile_zip(df):
    """Shapefile EPSG:4326, apto para importarse/reproyectarse en ArcGIS 10.8."""
    import shapefile
    shp, shx, dbf = io.BytesIO(),io.BytesIO(),io.BytesIO()
    with shapefile.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=shapefile.POINT, encoding='utf-8') as writer:
        writer.field('MUNICIPIO', 'C',size=100)
        writer.field('PROVINCIA', 'C',size=80)
        writer.field('FECHA_UTC','C',size=10)
        writer.field('HORA_UTC','C',size=5)
        writer.field('SATELITE','C',size=32)
        writer.field('FRP_MW','N',size=14,decimal=3)
        for _, row in df.iterrows():
            writer.point(float(row.longitude), float(row.latitude))
            writer.record(str(row.get('municipio',''))[:100],str(row.get('provincia',''))[:80],
                str(row.get('fecha',''))[:10],str(row.get('hora_utc',''))[:5],
                str(row.get('satellite',''))[:32],float(row.get('frp',0)))
    prj = ('GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",SPHEROID["WGS_1984",6378137,298.257223563]],'
           'PRIMEM["Greenwich",0],UNIT["Degree",0.0174532925199433]]')
    result = io.BytesIO()
    with zipfile.ZipFile(result,'w',zipfile.ZIP_DEFLATED) as z:
        for ext, value in [('shp',shp.getvalue()), ('shx',shx.getvalue()),('dbf',dbf.getvalue()),
                           ('prj',prj.encode()), ('cpg',b'UTF-8')]:
            z.writestr(f'focos_beni.{ext}',value)
    return result.getvalue()

# --- Extensiones V2: consultas históricas, meteorología y núcleos de focos ---
def query_firms_period(map_key: str, product: str, start_date: str, day_range: int):
    """Consulta NASA FIRMS para [start_date, start_date + day_range-1] (UTC).

    La clave nunca se registra ni se incluye en el texto de errores.
    """
    from datetime import date, timedelta
    map_key = map_key.strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,128}', map_key):
        raise ValueError('La MAP_KEY no tiene un formato válido.')
    if product not in SATELLITES.values() or not 1 <= int(day_range) <= 5:
        raise ValueError('Producto satelital o rango de días incorrecto.')
    try:
        start = date.fromisoformat(start_date)
    except (TypeError, ValueError):
        raise ValueError('Fecha inicial incorrecta: usa AAAA-MM-DD.') from None
    if start > date.today() or start + timedelta(days=day_range - 1) > date.today():
        raise ValueError('No se permiten fechas futuras.')
    bbox = ','.join(map(str, BENI_BBOX))
    url = (f'https://firms.modaps.eosdis.nasa.gov/api/area/csv/'
           f'{map_key}/{product}/{bbox}/{day_range}/{start.isoformat()}')
    try:
        res = requests.get(url, timeout=(10, 55), headers={'User-Agent':'SATIF-Beni-Web/2.0'})
        res.raise_for_status()
    except requests.RequestException as exc:
        code = getattr(getattr(exc,'response',None),'status_code',None)
        # Importante: requests.RequestException.__str__ puede contener la URL, y por tanto la clave.
        raise ValueError(f'La consulta FIRMS falló (HTTP {code or "sin respuesta"}). Revisa cuota, período y producto.') from None
    if 'latitude' not in res.text[:1500].lower():
        raise ValueError('NASA FIRMS no respondió con un CSV de detecciones válido.')
    out = parse_hotspots(io.StringIO(res.text))
    out['producto'] = product
    return out


def fetch_weather(lat: float, lon: float):
    """Meteorología actual/modelada y pronóstico horario en Bolivia (UTC-4)."""
    params = {
        'latitude': round(float(lat),5), 'longitude': round(float(lon),5),
        'current': 'temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m,wind_gusts_10m,cloud_cover',
        'hourly': 'temperature_2m,relative_humidity_2m,wind_speed_10m,precipitation_probability,precipitation',
        'forecast_days': 2, 'timezone': 'America/La_Paz', 'wind_speed_unit':'kmh'
    }
    try:
        r = requests.get('https://api.open-meteo.com/v1/forecast',params=params,timeout=(7,28))
        r.raise_for_status()
        data = r.json()
        if not isinstance(data.get('current'),dict):
            raise ValueError('Datos meteorológicos incompletos.')
        return data
    except requests.RequestException:
        raise ValueError('No fue posible consultar Open-Meteo. Revisa la conexión.') from None


def group_hotspots_grid(df: pd.DataFrame, cell_km: int = 5):
    """Agrupación aproximada por día UTC y celdas; no identifica incendios.

    Se usa tamaño angular aproximado considerando la latitud; una celda no es
    un perímetro quemado ni un núcleo científicamente delimitado.
    """
    if df.empty:
        return pd.DataFrame(columns=['fecha','latitud','longitud','detecciones','frp_max_mw','municipio'])
    if not 1 <= cell_km <= 25:
        raise ValueError('Tamaño de celda no válido')
    import math
    tmp = df.copy()
    latstep = cell_km / 111.0
    # longitud aprox a la latitud media del Beni
    lonstep = cell_km / (111.0 * math.cos(math.radians(13.7)))
    tmp['celda_y'] = (tmp.latitude / latstep).apply(math.floor)
    tmp['celda_x'] = (tmp.longitude / lonstep).apply(math.floor)
    agg = tmp.groupby(['fecha','celda_x','celda_y'],as_index=False).agg(
        latitud=('latitude','mean'), longitud=('longitude','mean'),
        detecciones=('latitude','size'), frp_max_mw=('frp','max'),
        municipio=('municipio','first'))
    return agg.sort_values(['detecciones','fecha'],ascending=[False,False]).reset_index(drop=True)
