# Scraper de propiedades en República Dominicana

Proyecto grupal: extrae 200 propiedades de cada fuente (Corotos, SuperCasas, Plusval = 600),
las junta en una tabla de pandas, genera un reporte con ydata-profiling y un reporte de
estatus del scraping.

## Cómo correrlo
Se recomienda Python 3.10 a 3.12 (`ydata-profiling` puede no instalar en versiones más nuevas).
```bash
python -m venv venv
venv\Scripts\activate        # Windows  (en Linux/Mac: source venv/bin/activate)
python -m pip install -r requirements.txt
python scraper_propiedades.py
```
Antes de correr: cambiar `AUTORES` (nombres de los 5 integrantes) y `TASA_USD_A_DOP`
(tasa del día) al inicio de `scraper_propiedades.py`.
Tarda unos 10 a 15 minutos porque pausa 1 segundo entre requests y abre el detalle de
cada anuncio de Corotos y SuperCasas.

## Archivos que genera (carpeta `salida/`)
| Archivo | Contenido |
|---|---|
| `propiedades.xlsx` | Tabla concatenada (600 filas) |
| `propiedades.parquet` | Misma tabla en parquet |
| `reporte_ydata_profiling.html` | Reporte de datos |
| `estatus_scraping.json` | Fecha y hora, autores, tiempo por request, tiempo total, número de propiedades, más cara y más barata |

## Estructura del código
- **Funciones**: `extraer_precio`, `buscar_conteo`, `extraer_tamano`, `convertir_a_usd`, `construir_estatus`, `exportar`, etc.
- **Clases**: `ScraperBase` (requests con tiempos, paginación, detección de tarjetas) y una clase hija por sitio: `CorotosScraper`, `SuperCasasScraper`, `PlusvalScraper`.
- **Librerías**: `requests`, `bs4`, `pandas`, `ydata-profiling`, `time`.

## Decisiones importantes
- **Moneda**: los sitios mezclan US$ y RD$. La tabla guarda `Precio` y `Moneda` originales, y `Precio_USD` convertido con `TASA_USD_A_DOP`; la propiedad más cara y la más barata se calculan con `Precio_USD`.
- **Vendedor**: en Plusval todos los anuncios son de la agencia (`Plusval Inmobiliaria`). En Corotos sale del enlace a la tienda del anuncio (o "Particular"). En SuperCasas se busca en la página del anuncio y, si no aparece, queda "No disponible".
- **Baños y parqueos en Corotos**: la lista no los muestra, por eso se abre cada anuncio.
- **SuperCasas** solo guarda anuncios con precio de venta (se descartan alquileres).

## Revisar antes de entregar
1. Correr el script y mirar `valores_nulos_por_columna` en `estatus_scraping.json`. Si una columna (por ejemplo Vendedor o Baños) sale casi toda nula, hay que ajustar la extracción de esa fuente.
2. Revisar el `robots.txt` de cada sitio y no bajar la pausa de 1 segundo entre requests.

## Reparto sugerido (5 personas)
1. `CorotosScraper`
2. `SuperCasasScraper`
3. `PlusvalScraper`
4. Tabla pandas, exportaciones y reporte de ydata-profiling
5. Reporte de estatus (JSON), README, repo de GitHub y edición del video

## Guion del video
1. Objetivo y fuentes (30 s).
2. Estructura: funciones, clase base y clases hijas (2 min).
3. Cómo se extrae cada campo y por qué se abre el detalle en Corotos/SuperCasas (2 min).
4. Ejecución en vivo y archivos generados (2 min).
5. Revisión del reporte de ydata-profiling y del JSON de estatus (1 min).

## Subir a GitHub
```bash
git init
git add .
git commit -m "Scraper de propiedades RD"
git branch -M main
git remote add origin https://github.com/USUARIO/REPOSITORIO.git
git push -u origin main
```
Después de correr el scraper, la carpeta `salida/` con los cuatro archivos resultantes también debe quedar en el repositorio (`git add salida`).
