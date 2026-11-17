# SATIF BENI / Centro de Monitoreo Web V2

**Prototipo independiente**, no es SATIF oficial ni reemplaza la verificación de incendios en campo.

## Contenido

- `app.py`: aplicación Streamlit con panel de control, mapa, gráficas, comparación NASA GIBS y meteorología.
- `core.py`: descarga/corte de datos NASA FIRMS, atribución municipal y exportaciones SIG.
- `requirements.txt`: dependencias que instala automáticamente Streamlit Community Cloud.
- `.streamlit/config.toml`: paleta de alto contraste.
- `datos/datos_simulados.csv`: puntos ficticios exclusivamente para demostración.
- `pruebas/`: tests sin depender de una clave NASA real.

## Cómo actualizar tu página que ya está en Streamlit

Tu repositorio actual es `andradeluiserick-dot/satif-beni-web` y el archivo principal se ubica dentro de la carpeta `SATIF_BENI_WEB_Para_Publicar`.

1. Descarga el ZIP y pulsa «Extraer todo».
2. En GitHub, entra a **satif-beni-web → SATIF_BENI_WEB_Para_Publicar** (la carpeta ya existe).
3. Selecciona **Agregar archivo / Add file → Cargar archivos / Upload files**.
4. Abre la carpeta extraída del mismo nombre y arrastra **su contenido** (`app.py`, `core.py`, `requirements.txt`, `README.md`, `datos` y `.streamlit`, etc.), **no arrastres el ZIP ni una carpeta adicional dentro de la que ya existe**.
5. Verifica que los archivos `app.py` y `core.py` se actualicen. Pulsa **Commit changes / Confirmar cambios**.
6. Streamlit debería desplegar la versión actualizada automáticamente a partir del commit. Si surge un error, abre **Manage app → Logs** y comprueba la rama y ruta del archivo principal.

**Ruta principal**: `SATIF_BENI_WEB_Para_Publicar/app.py`.

Si GitHub no permite reemplazar archivos con el cargador, puedes usar **GitHub Desktop** para copiar/reemplazar los archivos localmente y realizar *Commit* y *Push*; no hace falta crear otro repositorio.

## Activar NASA FIRMS de forma segura

**ATENCIÓN**: Tu clave anterior apareció en mensajes e incluso dentro de un HTML V5. Solicita una clave nueva o gestiona la anterior desde NASA FIRMS. Nunca la incluyas en código HTML, `app.py`, `README.md`, un ZIP público ni capturas de pantalla.

1. Ingresa a https://firms.modaps.eosdis.nasa.gov/api/map_key/ y solicita o renueva tu MAP_KEY.
2. En Streamlit Community Cloud, abre tu aplicación → **Manage app** (abajo a la derecha) → menú **⋮** → **Settings** → **Secrets**.
3. Pega este texto, sustituyendo el marcador por la nueva clave, y pulsa **Save**:

    ```toml
    NASA_FIRMS_MAP_KEY = "PEGA_AQUI_TU_CLAVE_NUEVA"
    ```

4. Vuelve a la web y pulsa **Consultar NASA FIRMS**.

La clave se usa **solo desde el servidor**. La aplicación no solicita ni muestra la clave a los visitantes. El archivo `.streamlit/secrets.toml` **NO debe** subirse nunca a GitHub.

## Uso de los filtros

- Filtro: municipio del Beni o todo el departamento.
- Origen: NASA FIRMS (real), CSV importado, o demostración ficticia.
- Satélites: VIIRS NOAA-21, NOAA-20, Suomi-NPP y MODIS. Hasta tres productos simultáneos.
- Periodos: 1 a 15 días, por bloques API de hasta cinco días. No todas las fechas/sensores tienen datos.
- Imágenes: NASA GIBS por fecha, con comparación antes/después. Si falta un mosaico del día, aparece la base de Esri.
- Tiempo: Open-Meteo para el centro del municipio seleccionado; los umbrales son indicativos y **no** avisos oficiales.
- Exportaciones: CSV, GeoJSON, KMZ, Shapefile ZIP e informe HTML imprimible como PDF.

**Coordenadas de salida**: EPSG:4326. Para ArcGIS 10.8, importar y proyectar a EPSG:32720 para Guayaramerín (y revisar huso UTM en otros municipios).

## Limitaciones científicas y técnicas

- Una detección de calor no equivale a un incendio confirmado o aislado.
- Densidades y agrupaciones no miden área quemada.
- La meteorología modelada corresponde a la hora de consulta, no a la hora histórica de cada foco.
- La API NASA y las imágenes NASA GIBS pueden presentar retrasos, restricciones por cuota o vacíos de cobertura.
- Los límites municipales son cartografía referencial que no resuelve cuestiones administrativas ni jurisdiccionales.
- Se necesitan Internet y servicios externos operativos; el sitio no es una herramienta oficial de emergencia.

## Referencias

- NASA FIRMS Area API: https://firms.modaps.eosdis.nasa.gov/api/area
- NASA FIRMS MAP_KEY: https://firms.modaps.eosdis.nasa.gov/api/map_key/
- NASA GIBS: https://gibs.earthdata.nasa.gov/
- Open-Meteo Forecast API: https://open-meteo.com/en/docs
- Municipalidades Bolivia 2024: https://lab-tecnosocial.github.io/municipios-bolivia-2024/
- Streamlit Secrets: https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app/app-settings

## Pruebas

Ejecutado en el entorno de preparación: `pytest -q pruebas/test_core.py pruebas/test_v2.py` — 8 pruebas aprobadas; se comprobó también que `app.py` compila con Python. No fue posible arrancar Streamlit en el entorno de preparación por una restricción de acceso a dependencias externas. Queda pendiente comprobar la interfaz una vez publicada en Streamlit Community Cloud.
