import json
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import pandas as pd
import requests
from bs4 import BeautifulSoup

AUTORES = ["Autor 1", "Autor 2", "Autor 3", "Autor 4", "Autor 5"]
OBJETIVO_POR_FUENTE = 200
PAUSA_ENTRE_REQUESTS = 1.0
MAX_PAGINAS_POR_URL = 60
TASA_USD_A_DOP = 60.0
CARPETA_SALIDA = Path("salida")
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "es-DO,es;q=0.9",
}
COLUMNAS = [
    "Fuente", "Nombre", "Precio", "Moneda", "Ubicación", "Vendedor",
    "Tamaño", "Habitaciones", "Baños", "Parqueos", "Precio_USD", "URL",
]

ET_HAB = r"(?:Habitaci[oó]n(?:es)?|habs?\b)"
ET_BANOS = r"(?:Ba[ñn]os?)"
ET_PARQ = r"(?:Parqueos?|Estacionamientos?)"
RE_PRECIO = re.compile(r"(US\$|RD\$)\s*(\d[\d,]*(?:\.\d+)?)")


def a_numero(valor):
    if valor is None:
        return None
    limpio = str(valor).replace(",", "").strip(" .")
    try:
        return float(limpio)
    except ValueError:
        return None


def extraer_precio(texto, patron_previo=""):
    m = re.search(patron_previo + r"\s*" + RE_PRECIO.pattern, texto)
    if not m:
        return None, None
    moneda = "USD" if m.group(1) == "US$" else "DOP"
    return a_numero(m.group(2)), moneda


def buscar_conteo(texto, etiqueta, modo):
    num = r"(\d+(?:\.\d+)?)"
    patrones = {
        "etiqueta": [etiqueta + r"\s*:?\s*" + num],
        "numero": [num + r"\s*" + etiqueta],
        "auto": [etiqueta + r"\s*:\s*" + num, num + r"\s*" + etiqueta,
                 etiqueta + r"\s+" + num],
    }[modo]
    for patron in patrones:
        m = re.search(patron, texto, re.IGNORECASE)
        if m:
            return a_numero(m.group(1))
    return None


def extraer_tamano(texto):
    patrones = [
        r"Construcci[oó]n\s*:?\s*(\d[\d.,]*)",
        r"(\d[\d.,]*)\s*(?:Mt2|M²|m²|m2)\s*Construcci",
        r"(\d[\d.,]*)\s*(?:Mt2|M²|m²|m2)",
    ]
    for patron in patrones:
        m = re.search(patron, texto, re.IGNORECASE)
        if m:
            return a_numero(m.group(1))
    return None


def humanizar_slug(slug):
    return re.sub(r"\s+", " ", slug.replace("-", " ")).strip().title()


def convertir_a_usd(precio, moneda):
    if precio is None:
        return None
    return precio if moneda == "USD" else round(precio / TASA_USD_A_DOP, 2)


def nuevo_registro(fuente, url):
    registro = {c: None for c in COLUMNAS}
    registro["Fuente"] = fuente
    registro["URL"] = url
    return registro


class ScraperBase:

    NOMBRE = "base"
    URLS_INICIO = []
    PARAM_PAGINA = "page"
    DETALLE = False

    def __init__(self, objetivo=OBJETIVO_POR_FUENTE):
        self.objetivo = objetivo
        self.sesion = requests.Session()
        self.sesion.headers.update(HEADERS)
        self.tiempos = []

    def pedir(self, url, tipo="listado"):
        soup, status, error = None, None, None
        inicio = time.perf_counter()
        for intento in range(2):
            try:
                resp = self.sesion.get(url, timeout=25)
                status = resp.status_code
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")
                error = None
                break
            except requests.RequestException as e:
                error = str(e)
                time.sleep(1.5)
        duracion = time.perf_counter() - inicio
        self.tiempos.append({
            "fuente": self.NOMBRE, "tipo": tipo, "url": url,
            "duracion_segundos": round(duracion, 3),
            "status_code": status, "error": error,
        })
        if error:
            print(f"[{self.NOMBRE}] ERROR {url}: {error}")
        return soup

    def valor_pagina(self, n):
        return n

    def url_con_pagina(self, url_inicio, n):
        p = urlparse(url_inicio)
        q = parse_qs(p.query)
        q[self.PARAM_PAGINA] = [str(self.valor_pagina(n))]
        return urlunparse(p._replace(query=urlencode(q, doseq=True)))

    def siguiente_url(self, soup, url_actual, url_inicio, n):
        if soup is not None:
            for a in soup.find_all("a", href=True):
                texto = a.get_text(" ", strip=True).lower()
                rel = a.get("rel") or []
                if "next" in rel or texto.startswith("siguiente"):
                    href = a["href"]
                    if href.startswith(("#", "javascript")):
                        continue
                    destino = urljoin(url_actual, href)
                    if destino != url_actual:
                        return destino
        return self.url_con_pagina(url_inicio, n)

    def es_anuncio(self, href):
        raise NotImplementedError

    def tarjetas(self, soup, url_base):
        filtro = lambda h: bool(h) and self.es_anuncio(h)
        primeros = {}
        for a in soup.find_all("a", href=filtro):
            primeros.setdefault(urljoin(url_base, a["href"].split("#")[0]), a)
        resultado = []
        for href, a in primeros.items():
            cont = a
            while cont.parent is not None and cont.parent.name not in ("body", "html", "[document]"):
                hrefs = {
                    urljoin(url_base, x["href"].split("#")[0])
                    for x in cont.parent.find_all("a", href=filtro)
                }
                if len(hrefs) > 1:
                    break
                cont = cont.parent
            resultado.append((href, cont))
        return resultado

    def parsear(self, href, tarjeta):
        raise NotImplementedError

    def completar_detalle(self, registro):
        pass

    def scrapear(self):
        registros, vistos = [], set()
        for i, inicio in enumerate(self.URLS_INICIO):
            es_ultima = i == len(self.URLS_INICIO) - 1
            cuota = (self.objetivo - len(registros)) if es_ultima else self.objetivo // len(self.URLS_INICIO)
            meta = len(registros) + cuota
            url, pagina, sin_nuevos = inicio, 1, 0

            while len(registros) < meta and pagina <= MAX_PAGINAS_POR_URL and sin_nuevos < 2:
                soup = self.pedir(url)
                nuevos = 0
                if soup is not None:
                    for href, cont in self.tarjetas(soup, url):
                        if href in vistos:
                            continue
                        reg = self.parsear(href, cont)
                        if reg is None:
                            continue
                        vistos.add(href)
                        if self.DETALLE:
                            self.completar_detalle(reg)
                            time.sleep(PAUSA_ENTRE_REQUESTS)
                        registros.append(reg)
                        nuevos += 1
                        if len(registros) >= meta:
                            break
                sin_nuevos = 0 if nuevos else sin_nuevos + 1
                print(f"[{self.NOMBRE}] página {pagina}: {len(registros)}/{self.objetivo}")
                pagina += 1
                if len(registros) >= meta:
                    break
                url = self.siguiente_url(soup, url, inicio, pagina)
                time.sleep(PAUSA_ENTRE_REQUESTS)
        return registros


class PlusvalScraper(ScraperBase):
    NOMBRE = "Plusval"
    URLS_INICIO = ["https://plusval.com.do/buscar?action=1"]
    PARAM_PAGINA = "page"

    def es_anuncio(self, href):
        return re.search(r"/propiedad(?!es)", href) is not None

    def parsear(self, href, tarjeta):
        txt = tarjeta.get_text(" ", strip=True)
        if "Baños" not in txt:
            return None
        precio, moneda = extraer_precio(txt)
        if precio is None:
            return None
        cola = txt[RE_PRECIO.search(txt).start():]

        reg = nuevo_registro(self.NOMBRE, href)
        m = re.search(r"DESTACADA\s+(.*?)\s+(?:US\$|RD\$)", txt)
        if m:
            reg["Nombre"] = m.group(1).rstrip(". ")
            idx = txt.find(reg["Nombre"][:25])
            if idx > 0:
                ubic = txt[:idx].replace("DESTACADA", "")
                ubic = re.sub(r"(\s\d{5,7})+\s*$", "", ubic.strip())
                reg["Ubicación"] = ubic or None
        if not reg["Nombre"]:
            slug = urlparse(href).path.rstrip("/").split("/")[-1]
            reg["Nombre"] = humanizar_slug(re.sub(r"-?\d+$", "", slug))

        reg["Precio"], reg["Moneda"] = precio, moneda
        reg["Vendedor"] = "Plusval Inmobiliaria"
        reg["Tamaño"] = extraer_tamano(cola)
        reg["Habitaciones"] = buscar_conteo(cola, ET_HAB, "etiqueta")
        reg["Baños"] = buscar_conteo(cola, ET_BANOS, "etiqueta")
        reg["Parqueos"] = buscar_conteo(cola, ET_PARQ, "etiqueta")
        reg["Precio_USD"] = convertir_a_usd(precio, moneda)
        return reg


class SuperCasasScraper(ScraperBase):
    NOMBRE = "SuperCasas"
    URLS_INICIO = [
        "https://www.supercasas.com/apartamentos/",
        "https://www.supercasas.com/casas/",
    ]
    PARAM_PAGINA = "PagingPageSkip"
    DETALLE = True

    def valor_pagina(self, n):
        return n - 1

    def es_anuncio(self, href):
        ruta = urlparse(href).path
        return re.fullmatch(r"/(?!tv/)[a-z0-9\-]+/\d{6,8}/?", ruta) is not None

    def parsear(self, href, tarjeta):
        txt = tarjeta.get_text(" ", strip=True)
        precio, moneda = extraer_precio(txt, r"Venta:")
        if precio is None and re.search(r"/\s*Venta", txt):
            precio, moneda = extraer_precio(txt)
        if precio is None:
            return None

        reg = nuevo_registro(self.NOMBRE, href)
        slug = urlparse(href).path.strip("/").split("/")[0]
        m = re.match(r"(?P<tipo>[a-z0-9\-]+?)-(?:venta-y-alquiler|venta|alquiler|precio)-(?P<sector>.+)$", slug)
        tipo = humanizar_slug(m.group("tipo")) if m else "Propiedad"

        ubic = None
        m1 = re.search(r"/\s*Venta(?: y Alquiler)?\s+(.*?)\s+(?:US\$|RD\$)", txt)
        if m1:
            ubic = m1.group(1)
        else:
            finales = list(re.finditer(r"Ba[ñn]os:\s*[\d.]+", txt))
            if finales:
                cola = txt[finales[-1].end():]
                candidato = re.split(r"\s(?:US\$|RD\$)", cola)[0].strip()
                if candidato and ":" not in candidato:
                    ubic = candidato
        if not ubic and m:
            ubic = humanizar_slug(m.group("sector"))

        reg["Nombre"] = f"{tipo} en venta en {ubic}" if ubic else tipo
        reg["Ubicación"] = ubic
        reg["Precio"], reg["Moneda"] = precio, moneda
        reg["Tamaño"] = extraer_tamano(txt)
        reg["Habitaciones"] = buscar_conteo(txt, ET_HAB, "auto")
        reg["Baños"] = buscar_conteo(txt, ET_BANOS, "auto")
        reg["Parqueos"] = buscar_conteo(txt, ET_PARQ, "auto")
        reg["Precio_USD"] = convertir_a_usd(precio, moneda)
        reg["Vendedor"] = "No disponible"
        return reg

    def completar_detalle(self, registro):
        soup = self.pedir(registro["URL"], "detalle")
        if soup is None:
            return
        for a in soup.find_all("a", href=True):
            href, texto = a["href"], a.get_text(" ", strip=True)
            if len(texto) > 2 and re.search(r"/Propiedades/|/Directorio/(?:Agentes|Inmobiliarias)/", href, re.I):
                if texto.lower() not in ("directorio", "agentes", "inmobiliarias", "ver más"):
                    registro["Vendedor"] = texto
                    return
        m = re.search(
            r"(?:Anunciante|Vendedor|Agente)\s*:?\s*([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ.&\- ]{2,50}?)"
            r"(?=\s+(?:Tel|Cel|Whats|Email|Correo|\d)|$)",
            soup.get_text(" ", strip=True),
        )
        if m:
            registro["Vendedor"] = m.group(1).strip()


class CorotosScraper(ScraperBase):
    NOMBRE = "Corotos"
    URLS_INICIO = [
        "https://www.corotos.com.do/sc/inmuebles-en-venta/apartamentos",
        "https://www.corotos.com.do/sc/inmuebles-en-venta/casas",
    ]
    PARAM_PAGINA = "page"
    DETALLE = True

    def es_anuncio(self, href):
        return "/anuncio/inmuebles-en-venta/" in href

    def parsear(self, href, tarjeta):
        txt = tarjeta.get_text(" ", strip=True)
        precio, moneda = extraer_precio(txt)
        if precio is None:
            return None

        reg = nuevo_registro(self.NOMBRE, href)
        candidatos, linea = [], ""
        for a in tarjeta.find_all("a", href=lambda h: bool(h) and self.es_anuncio(h)):
            t = a.get_text(" ", strip=True)
            if not t:
                continue
            if t.startswith("Venta "):
                linea = t
            elif not RE_PRECIO.search(t) and "verificada" not in t.lower() and not t.isdigit():
                candidatos.append(t)
        if candidatos:
            reg["Nombre"] = max(candidatos, key=len)
        else:
            slug = urlparse(href).path.rstrip("/").split("/")[-1]
            reg["Nombre"] = humanizar_slug(re.sub(r"-[a-z0-9]{7}$", "", slug))

        m = re.match(r"Venta\s+(.*?)(?:\s+\d+\s*habs?\b|\s+\d[\d.,]*\s*m²|$)", linea)
        if m:
            reg["Ubicación"] = m.group(1).strip(" ·") or None

        tienda = tarjeta.find("a", href=re.compile(r"/shops/"))
        if tienda:
            reg["Vendedor"] = humanizar_slug(tienda["href"].rstrip("/").split("/")[-1])

        reg["Precio"], reg["Moneda"] = precio, moneda
        reg["Tamaño"] = extraer_tamano(linea or txt)
        reg["Habitaciones"] = buscar_conteo(linea or txt, ET_HAB, "numero")
        reg["Precio_USD"] = convertir_a_usd(precio, moneda)
        return reg

    def completar_detalle(self, registro):
        soup = self.pedir(registro["URL"], "detalle")
        if soup is None:
            return
        txt = soup.get_text(" ", strip=True)
        if registro["Baños"] is None:
            registro["Baños"] = buscar_conteo(txt, ET_BANOS, "auto")
        if registro["Parqueos"] is None:
            registro["Parqueos"] = buscar_conteo(txt, ET_PARQ, "auto")
        if registro["Tamaño"] is None:
            registro["Tamaño"] = extraer_tamano(txt)
        if registro["Vendedor"] is None:
            tienda = soup.find("a", href=re.compile(r"/shops/"))
            registro["Vendedor"] = (
                humanizar_slug(tienda["href"].rstrip("/").split("/")[-1]) if tienda else "Particular"
            )


def resumen_propiedad(fila):
    return {
        "fuente": fila["Fuente"], "nombre": fila["Nombre"],
        "precio": float(fila["Precio"]), "moneda": fila["Moneda"],
        "precio_usd": float(fila["Precio_USD"]), "ubicacion": fila["Ubicación"],
        "url": fila["URL"],
    }


def construir_estatus(df, tiempos, t_inicio, fecha_inicio):
    duracion_total = time.perf_counter() - t_inicio
    con_precio = df[df["Precio_USD"] > 0]
    tiempos_df = pd.DataFrame(tiempos)
    por_fuente = {}
    for fuente, g in tiempos_df.groupby("fuente"):
        por_fuente[fuente] = {
            "numero_requests": int(len(g)),
            "tiempo_total_segundos": round(float(g["duracion_segundos"].sum()), 3),
            "tiempo_promedio_por_request": round(float(g["duracion_segundos"].mean()), 3),
        }
    return {
        "fecha_hora": fecha_inicio.strftime("%Y-%m-%d %H:%M:%S"),
        "autores": AUTORES,
        "duracion_total_segundos": round(duracion_total, 3),
        "numero_propiedades_scrapeadas": int(len(df)),
        "propiedades_por_fuente": {k: int(v) for k, v in df["Fuente"].value_counts().items()},
        "tasa_usd_a_dop_usada": TASA_USD_A_DOP,
        "propiedad_mas_cara": resumen_propiedad(con_precio.loc[con_precio["Precio_USD"].idxmax()]) if len(con_precio) else None,
        "propiedad_mas_barata": resumen_propiedad(con_precio.loc[con_precio["Precio_USD"].idxmin()]) if len(con_precio) else None,
        "resumen_por_fuente": por_fuente,
        "valores_nulos_por_columna": {c: int(v) for c, v in df.isna().sum().items()},
        "duracion_por_request": tiempos,
    }


def generar_reporte_profiling(df, ruta):
    try:
        from ydata_profiling import ProfileReport
    except ImportError:
        print("Instala ydata-profiling:  pip install ydata-profiling")
        return
    ProfileReport(df, title="Propiedades en República Dominicana", minimal=True).to_file(ruta)


def exportar(df, estatus):
    CARPETA_SALIDA.mkdir(exist_ok=True)
    df.to_excel(CARPETA_SALIDA / "propiedades.xlsx", index=False)
    df.to_parquet(CARPETA_SALIDA / "propiedades.parquet", index=False)
    with open(CARPETA_SALIDA / "estatus_scraping.json", "w", encoding="utf-8") as f:
        json.dump(estatus, f, ensure_ascii=False, indent=4)


def armar_tabla(listas_de_registros):
    df = pd.concat([pd.DataFrame(r, columns=COLUMNAS) for r in listas_de_registros], ignore_index=True)
    for col in ["Precio", "Tamaño", "Habitaciones", "Baños", "Parqueos", "Precio_USD"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def main():
    fecha_inicio = datetime.now()
    t_inicio = time.perf_counter()

    scrapers = [CorotosScraper(), SuperCasasScraper(), PlusvalScraper()]
    resultados, tiempos = [], []
    for scraper in scrapers:
        print(f"\n=== {scraper.NOMBRE} ===")
        resultados.append(scraper.scrapear())
        tiempos.extend(scraper.tiempos)

    df = armar_tabla(resultados)
    print(f"\nTotal de propiedades: {len(df)}")
    print(df.groupby("Fuente").size())

    estatus = construir_estatus(df, tiempos, t_inicio, fecha_inicio)
    exportar(df, estatus)
    generar_reporte_profiling(df, CARPETA_SALIDA / "reporte_ydata_profiling.html")
    print(f"\nListo. Archivos en: {CARPETA_SALIDA.resolve()}")


if __name__ == "__main__":
    main()
