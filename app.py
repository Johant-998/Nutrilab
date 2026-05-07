# =============================================================================
# app.py — VERSIÓN CONSOLIDADA PARA STREAMLIT CLOUD
# Analizador de Etiquetas Nutricionales — NutriLab
# Proyecto Final - Curso de Python
#
# Todo el código está en un solo archivo para compatibilidad con
# Streamlit Cloud, que no puede importar módulos locales externos.
#
# Uso local:   streamlit run app.py
# Uso en nube: subir este archivo + requirements.txt a GitHub
#
# Autor: [Tu nombre]
# Fecha: 2025
# =============================================================================

import os
import re
import requests
from datetime import datetime

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import streamlit as st
from fpdf import FPDF

# Importacion condicional de Supabase
SUPABASE_DISPONIBLE = False
SUPABASE_ERROR      = ""
_sb_client          = None

try:
    import requests as _requests

    _SUPA_URL = ""
    _SUPA_KEY = ""

    if hasattr(st, "secrets"):
        _SUPA_URL = st.secrets.get("SUPABASE_URL", "").rstrip("/")
        _SUPA_KEY = (
            st.secrets.get("SUPABASE_KEY", "") or
            st.secrets.get("SUPABASE_ANON_KEY", "")
        )

    if not _SUPA_URL:
        SUPABASE_ERROR = "SUPABASE_URL no encontrada en Secrets"
    elif not _SUPA_KEY:
        SUPABASE_ERROR = "SUPABASE_KEY no encontrada en Secrets"
    else:
        _project_ref = _SUPA_URL.replace("https://", "").split(".")[0]
        _REST_BASE   = f"https://{_project_ref}.supabase.co/rest/v1"

        # Headers con Accept-Profile para forzar schema public
        _SUPA_HEADERS = {
            "apikey":         _SUPA_KEY,
            "Authorization":  f"Bearer {_SUPA_KEY}",
            "Content-Type":   "application/json",
            "Accept-Profile": "public",
            "Content-Profile":"public",
        }

        # Probar conexion con la tabla
        _test = _requests.get(
            f"{_REST_BASE}/productos?select=id&limit=1",
            headers=_SUPA_HEADERS,
            timeout=8
        )

        if _test.status_code in (200, 206):
            SUPABASE_DISPONIBLE = True
        else:
            # Mostrar respuesta completa para diagnostico
            SUPABASE_ERROR = (
                f"HTTP {_test.status_code} en {_REST_BASE}/productos — "
                f"{_test.text[:150]}"
            )

except Exception as e:
    SUPABASE_ERROR = f"Error de conexion: {e}"

_REST_BASE = _REST_BASE if SUPABASE_DISPONIBLE else ""

# Importacion condicional del lector de codigo de barras
BARCODE_DISPONIBLE = False
BARCODE_ERROR      = ""

try:
    from pyzbar.pyzbar import decode
    from PIL import Image as PILImage
    BARCODE_DISPONIBLE = True
except ImportError as e:
    BARCODE_ERROR = str(e)


# =============================================================================
# LÓGICA DE ANÁLISIS NUTRICIONAL
# =============================================================================

VRD = {
    "calorias":         2000,
    "grasas_totales":     65,
    "grasas_saturadas":   20,
    "sodio":            2300,
    "carbohidratos":     300,
    "azucares":           50,
    "proteinas":          50,
    "fibra":              25,
}

UMBRAL_VERDE    = 5
UMBRAL_AMARILLO = 20

PESOS_NEGATIVOS = {
    "grasas_saturadas": 0.30,
    "sodio":            0.30,
    "azucares":         0.25,
    "grasas_totales":   0.15,
}

PESOS_POSITIVOS = {
    "proteinas": 0.60,
    "fibra":     0.40,
}


def analizar_nutrientes(datos: dict) -> dict:
    """Analiza los nutrientes y retorna resultado completo con semaforo y puntaje."""
    porcentajes   = calcular_porcentajes(datos)
    semaforo      = clasificar_semaforo(porcentajes)
    puntaje       = calcular_puntaje(porcentajes)
    alertas       = generar_alertas(datos, porcentajes)
    recomendacion = generar_recomendacion(puntaje)
    return {
        "nombre_producto":  datos.get("nombre_producto", "Producto sin nombre"),
        "datos_originales": datos,
        "porcentajes":      porcentajes,
        "semaforo":         semaforo,
        "puntaje":          puntaje,
        "alertas":          alertas,
        "recomendacion":    recomendacion,
    }


def calcular_porcentajes(datos: dict) -> dict:
    """Calcula el porcentaje de VRD para cada nutriente ingresado."""
    porcentajes = {}
    for nutriente, valor_ref in VRD.items():
        if nutriente in datos and datos[nutriente] is not None and valor_ref > 0:
            porcentajes[nutriente] = round((datos[nutriente] / valor_ref) * 100, 1)
    return porcentajes


def clasificar_semaforo(porcentajes: dict) -> dict:
    """Clasifica cada nutriente en verde / amarillo / rojo segun su porcentaje VRD."""
    riesgo    = {"sodio", "azucares", "grasas_saturadas", "grasas_totales"}
    positivos = {"proteinas", "fibra"}
    semaforo  = {}
    for nutriente, pct in porcentajes.items():
        if nutriente in riesgo:
            if pct <= UMBRAL_VERDE:
                semaforo[nutriente] = {"color": "VERDE",    "emoji": "green",   "etiqueta": "Bajo"}
            elif pct <= UMBRAL_AMARILLO:
                semaforo[nutriente] = {"color": "AMARILLO", "emoji": "yellow",  "etiqueta": "Medio"}
            else:
                semaforo[nutriente] = {"color": "ROJO",     "emoji": "red",     "etiqueta": "Alto"}
        elif nutriente in positivos:
            if pct >= 15:
                semaforo[nutriente] = {"color": "VERDE",    "emoji": "green",   "etiqueta": "Adecuado"}
            elif pct >= 8:
                semaforo[nutriente] = {"color": "AMARILLO", "emoji": "yellow",  "etiqueta": "Bajo"}
            else:
                semaforo[nutriente] = {"color": "ROJO",     "emoji": "red",     "etiqueta": "Muy bajo"}
        else:
            if pct <= 15:
                semaforo[nutriente] = {"color": "VERDE",    "emoji": "green",   "etiqueta": "Bajo"}
            elif pct <= 30:
                semaforo[nutriente] = {"color": "AMARILLO", "emoji": "yellow",  "etiqueta": "Moderado"}
            else:
                semaforo[nutriente] = {"color": "ROJO",     "emoji": "red",     "etiqueta": "Alto"}
    return semaforo


def calcular_puntaje(porcentajes: dict) -> float:
    """Calcula puntaje de salud 0-100 penalizando riesgos y premiando positivos."""
    puntaje = 100.0
    for nutriente, peso in PESOS_NEGATIVOS.items():
        if nutriente in porcentajes:
            exceso   = max(0, porcentajes[nutriente] - UMBRAL_VERDE)
            puntaje -= min(exceso * peso, 25)
    for nutriente, peso in PESOS_POSITIVOS.items():
        if nutriente in porcentajes:
            aporte   = min(porcentajes[nutriente], 100)
            puntaje += min(aporte * peso * 0.05, 5)
    return round(max(0.0, min(100.0, puntaje)), 1)


def generar_alertas(datos: dict, porcentajes: dict) -> list:
    """Genera alertas textuales sobre riesgos y deficiencias nutricionales."""
    alertas = []
    if porcentajes.get("sodio", 0) > 20:
        alertas.append("Alto en sodio - no recomendado para personas con hipertension.")
    if porcentajes.get("azucares", 0) > 20:
        alertas.append("Alto en azucares - puede contribuir al aumento de peso.")
    if porcentajes.get("grasas_saturadas", 0) > 20:
        alertas.append("Alto en grasas saturadas - riesgo cardiovascular.")
    if porcentajes.get("calorias", 0) > 30:
        alertas.append("Alto en calorias - mas del 30% de la ingesta diaria recomendada.")
    if porcentajes.get("proteinas", 100) < 5:
        alertas.append("Muy bajo en proteinas - no aporta significativamente a la masa muscular.")
    if porcentajes.get("fibra", 100) < 5:
        alertas.append("Muy bajo en fibra - no contribuye a la salud digestiva.")
    if porcentajes.get("calorias", 100) < 10 and porcentajes.get("azucares", 0) > 10:
        alertas.append("Posible uso de edulcorantes - verifique la lista de ingredientes.")
    if not alertas:
        alertas.append("Sin alertas nutricionales destacadas. Producto equilibrado.")
    return alertas


def generar_recomendacion(puntaje: float) -> str:
    """Genera recomendacion de consumo segun el puntaje de salud."""
    if puntaje >= 75:
        return "Producto saludable. Apto para consumo regular."
    elif puntaje >= 50:
        return "Producto aceptable. Se recomienda consumo moderado."
    elif puntaje >= 25:
        return "Producto con nutrientes de riesgo. Consumo ocasional."
    else:
        return "Producto poco saludable. Evitar consumo frecuente."


# =============================================================================
# GENERACION DE REPORTE PDF
# =============================================================================

COLOR_AZUL   = (44,  62,  80)
COLOR_BLANCO = (255, 255, 255)
COLOR_GRIS   = (245, 245, 245)
COLOR_BORDE  = (200, 200, 200)

COLORES_SEM_PDF = {
    "VERDE":    (46,  204, 113),
    "AMARILLO": (243, 156,  18),
    "ROJO":     (231,  76,  60),
}

ETIQUETAS_PDF = {
    "calorias":         ("Calorias",         "kcal"),
    "grasas_totales":   ("Grasas totales",   "g"),
    "grasas_saturadas": ("Grasas saturadas", "g"),
    "sodio":            ("Sodio",            "mg"),
    "carbohidratos":    ("Carbohidratos",    "g"),
    "azucares":         ("Azucares",         "g"),
    "proteinas":        ("Proteinas",        "g"),
    "fibra":            ("Fibra dietetica",  "g"),
}


class ReporteNutricional(FPDF):
    """PDF con encabezado y pie de pagina automaticos."""

    def __init__(self, nombre_producto: str):
        super().__init__(orientation="P", unit="mm", format="Letter")
        self.nombre_producto = nombre_producto
        self.set_auto_page_break(auto=True, margin=20)

    def header(self):
        self.set_fill_color(*COLOR_AZUL)
        self.rect(0, 0, 216, 18, style="F")
        self.set_font("Helvetica", "B", 13)
        self.set_text_color(*COLOR_BLANCO)
        self.set_y(4)
        self.cell(0, 8, "REPORTE DE ANALISIS NUTRICIONAL", align="C")
        self.set_font("Helvetica", "", 9)
        self.set_text_color(180, 200, 220)
        self.set_y(11)
        self.cell(0, 5, self.nombre_producto[:60], align="C")
        self.ln(12)

    def footer(self):
        self.set_y(-14)
        self.set_draw_color(*COLOR_BORDE)
        self.line(10, self.get_y(), 206, self.get_y())
        self.ln(1)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(150, 150, 150)
        self.cell(150, 4,
            "* VRD basados en dieta de 2000 kcal (Res. 810/2021 Min. Salud Colombia).",
            align="L")
        self.cell(0, 4,
            f"{datetime.now().strftime('%d/%m/%Y %H:%M')}  |  Pag. {self.page_no()}",
            align="R")


def _limpiar(texto: str) -> str:
    """
    Reemplaza caracteres especiales por equivalentes ASCII
    para compatibilidad con la fuente Helvetica de fpdf2.
    """
    if not texto:
        return ""
    # Reemplazar caracteres Unicode comunes por equivalentes ASCII
    reemplazos = {
        "—": "-",   # em dash —
        "–": "-",   # en dash –
        "‘": "'",   # comilla izquierda
        "’": "'",   # comilla derecha
        "“": '"',   # comilla doble izquierda
        "”": '"',   # comilla doble derecha
        "…": "...", # puntos suspensivos
        "é": "e",   # é
        "á": "a",   # á
        "í": "i",   # í
        "ó": "o",   # ó
        "ú": "u",   # ú
        "ñ": "n",   # ñ
        "É": "E",   # É
        "Á": "A",   # Á
        "Í": "I",   # Í
        "Ó": "O",   # Ó
        "Ú": "U",   # Ú
        "Ñ": "N",   # Ñ
        "ü": "u",   # ü
        "à": "a",   # à
        "è": "e",   # è
    }
    for char, reemplazo in reemplazos.items():
        texto = texto.replace(char, reemplazo)
    # Eliminar cualquier otro caracter no-ASCII restante
    return texto.encode("ascii", errors="ignore").decode("ascii").strip()


def _titulo_seccion(pdf, titulo: str):
    pdf.set_fill_color(*COLOR_AZUL)
    pdf.set_text_color(*COLOR_BLANCO)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_x(10)
    pdf.cell(196, 8, f"  {titulo}", border=0, fill=True, ln=1)
    pdf.ln(3)
    pdf.set_text_color(*COLOR_AZUL)


def generar_pdf_bytes(resultado: dict, ruta_grafica: str = None) -> bytes:
    """Genera el PDF en memoria y retorna los bytes listos para descarga."""
    nombre  = _limpiar(resultado["nombre_producto"])
    pct     = resultado["porcentajes"]
    sem     = resultado["semaforo"]
    datos   = resultado["datos_originales"]
    puntaje = resultado["puntaje"]
    alertas = resultado["alertas"]
    rec     = resultado["recomendacion"]

    pdf = ReporteNutricional(nombre)
    pdf.add_page()

    # Resumen
    _titulo_seccion(pdf, "INFORMACION GENERAL")
    pdf.set_fill_color(*COLOR_GRIS)
    pdf.set_draw_color(*COLOR_BORDE)
    pdf.rect(10, pdf.get_y(), 196, 22, style="FD")
    pdf.set_y(pdf.get_y() + 3)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_x(14)
    pdf.cell(60, 6, "Producto analizado:", ln=0)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, _limpiar(nombre[:60]), ln=1)
    pdf.set_x(14)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(60, 6, "Fecha de analisis:", ln=0)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(80, 6, datetime.now().strftime("%d/%m/%Y"), ln=0)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(20, 6, "Resultado:", ln=0)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, _limpiar(rec), ln=1)
    pdf.ln(6)

    # Tabla
    _titulo_seccion(pdf, "TABLA NUTRICIONAL")
    anchos = [65, 25, 18, 25, 18, 35]
    pdf.set_fill_color(*COLOR_AZUL)
    pdf.set_text_color(*COLOR_BLANCO)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_x(10)
    for i, titulo_col in enumerate(["NUTRIENTE", "VALOR", "UNIDAD", "% VRD", "SEM.", "NIVEL"]):
        pdf.cell(anchos[i], 8, titulo_col, border=1, align="C", fill=True)
    pdf.ln()

    pdf.set_font("Helvetica", "", 9)
    fila_par = True
    for clave, (etiqueta, unidad) in ETIQUETAS_PDF.items():
        if clave not in pct:
            continue
        porcentaje = pct[clave]
        valor      = datos.get(clave, 0)
        info_sem   = sem.get(clave, {})
        color_sem  = info_sem.get("color", "AMARILLO")
        nivel      = info_sem.get("etiqueta", "-")
        rgb        = COLORES_SEM_PDF.get(color_sem, (243, 156, 18))
        fill_c     = COLOR_GRIS if fila_par else COLOR_BLANCO
        pdf.set_fill_color(*fill_c)
        pdf.set_text_color(*COLOR_AZUL)
        fila_par   = not fila_par
        val_str    = f"{valor:.1f}" if isinstance(valor, float) else str(valor)
        pdf.set_x(10)
        pdf.cell(anchos[0], 7, etiqueta,             border=1, align="L", fill=True)
        pdf.cell(anchos[1], 7, val_str,              border=1, align="C", fill=True)
        pdf.cell(anchos[2], 7, unidad,               border=1, align="C", fill=True)
        pdf.cell(anchos[3], 7, f"{porcentaje:.1f}%", border=1, align="C", fill=True)
        x_a = pdf.get_x()
        y_a = pdf.get_y()
        pdf.cell(anchos[4], 7, "", border=1, fill=True)
        pdf.set_fill_color(*rgb)
        pdf.rect(x_a + 5, y_a + 1.5, 8, 4, style="F")
        pdf.set_text_color(*rgb)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(anchos[5], 7, nivel, border=1, align="C", fill=True)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*COLOR_AZUL)
        pdf.ln()
    pdf.ln(6)

    # Barra puntaje
    _titulo_seccion(pdf, "PUNTAJE DE SALUD")
    if puntaje >= 75:
        color_b, nivel_t = (39, 174, 96),  "SALUDABLE"
    elif puntaje >= 50:
        color_b, nivel_t = (230, 126, 34), "ACEPTABLE"
    else:
        color_b, nivel_t = (192,  57, 43), "CON RIESGOS"
    y_b = pdf.get_y()
    pdf.set_fill_color(220, 220, 220)
    pdf.set_draw_color(*COLOR_BORDE)
    pdf.rect(10, y_b, 196, 12, style="FD")
    ancho_prog = (puntaje / 100) * 196
    pdf.set_fill_color(*color_b)
    pdf.rect(10, y_b, ancho_prog, 12, style="F")
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*COLOR_BLANCO)
    pdf.set_xy(10, y_b + 2)
    pdf.cell(ancho_prog, 8, f"  {puntaje:.1f} / 100  -  {nivel_t}", align="L")
    pdf.ln(18)

    # Alertas
    _titulo_seccion(pdf, "ALERTAS Y RECOMENDACION")
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*COLOR_AZUL)
    pdf.set_x(10)
    pdf.cell(0, 7, f"Recomendacion: {_limpiar(rec)}", ln=1)
    pdf.ln(2)
    pdf.set_font("Helvetica", "", 9)
    for alerta in alertas:
        al = _limpiar(alerta).strip()
        if "alto" in al.lower() or "evitar" in al.lower():
            pdf.set_text_color(192, 57, 43)
        elif "bajo" in al.lower():
            pdf.set_text_color(243, 156, 18)
        else:
            pdf.set_text_color(39, 174, 96)
        pdf.set_x(14)
        pdf.cell(5, 6, "-", ln=0)
        pdf.set_text_color(*COLOR_AZUL)
        pdf.multi_cell(185, 6, al)
    pdf.ln(4)

    # Grafica
    if ruta_grafica and os.path.exists(ruta_grafica):
        _titulo_seccion(pdf, "GRAFICA DE NUTRIENTES")
        if pdf.h - pdf.get_y() - 20 < 100:
            pdf.add_page()
        ancho_img = 180
        pdf.image(ruta_grafica, x=(216 - ancho_img) / 2, y=pdf.get_y(), w=ancho_img)

    return bytes(pdf.output())


# =============================================================================
# MODULO LECTOR DE CODIGO DE BARRAS + OPEN FOOD FACTS
# =============================================================================

# URL base de la API Open Food Facts (gratuita, sin API key)
OFF_API_URL = "https://world.openfoodfacts.org/api/v0/product/{codigo}.json"
OFF_HEADERS = {"User-Agent": "NutriLab/1.0 (proyecto educativo)"}


def barcode_leer_imagen(imagen_bytes: bytes) -> str:
    """
    Decodifica el codigo de barras de una imagen usando pyzbar.
    Intenta con la imagen original y luego con variantes de contraste
    si no detecta ningun codigo en el primer intento.

    Parametros:
        imagen_bytes (bytes): Contenido de la imagen en bytes.

    Retorna:
        str: Numero del codigo de barras (EAN-13, UPC-A, etc.)

    Lanza:
        ValueError: Si no se detecta ningun codigo de barras.
    """
    imagen_pil = PILImage.open(__import__('io').BytesIO(imagen_bytes))

    # Intentar decodificar en imagen original
    codigos = decode(imagen_pil)

    # Si no encuentra, intentar con escala de grises
    if not codigos:
        imagen_gris = imagen_pil.convert("L")
        codigos = decode(imagen_gris)

    # Si tampoco, aumentar contraste
    if not codigos:
        from PIL import ImageEnhance
        imagen_contraste = ImageEnhance.Contrast(imagen_pil).enhance(2.0)
        codigos = decode(imagen_contraste)

    if not codigos:
        raise ValueError(
            "No se detecto ningun codigo de barras en la imagen. "
            "Asegurese de que el codigo de barras sea visible, "
            "este bien iluminado y no este borroso."
        )

    # Retornar el primer codigo detectado
    codigo = codigos[0].data.decode("utf-8").strip()
    tipo   = codigos[0].type
    return codigo, tipo


def barcode_consultar_api(codigo: str) -> dict:
    """
    Consulta la API de Open Food Facts con el codigo de barras
    y extrae los nutrientes del producto encontrado.

    Parametros:
        codigo (str): Numero EAN/UPC del producto.

    Retorna:
        dict: Datos del producto con nutrientes listos para analizar.

    Lanza:
        ValueError: Si el producto no existe en la base de datos.
        ConnectionError: Si no hay conexion a internet.
    """
    url = OFF_API_URL.format(codigo=codigo)

    # Reintentar hasta 3 veces con timeout creciente
    _ultimo_error = ""
    for _intento, _timeout in enumerate([12, 20, 30], start=1):
        try:
            respuesta = requests.get(
                url, headers=OFF_HEADERS,
                timeout=_timeout
            )
            respuesta.raise_for_status()
            data = respuesta.json()
            break  # exito — salir del loop
        except requests.exceptions.Timeout:
            _ultimo_error = f"Timeout en intento {_intento} ({_timeout}s)"
            if _intento == 3:
                raise ConnectionError(
                    "Open Food Facts no respondio en 30 segundos. "
                    "Ingrese los datos manualmente."
                )
            continue
        except requests.exceptions.ConnectionError:
            raise ConnectionError("Sin conexion a internet.")
        except Exception as e:
            raise ConnectionError(f"Error de conexion: {e}")

    # Verificar si el producto existe en la base de datos
    if data.get("status") != 1:
        raise ValueError(
            f"Producto con codigo {codigo} no encontrado en Open Food Facts. "
            "Puede ingresar los datos manualmente en la pestana Manual."
        )

    producto    = data["product"]
    nutriments  = producto.get("nutriments", {})
    nombre_prod = producto.get("product_name", "") or producto.get("product_name_es", "")
    marca       = producto.get("brands", "")
    pais        = producto.get("countries", "")

    # Extraer porcion — intentar varias claves
    porcion_g = (
        producto.get("serving_size") or
        nutriments.get("serving_size") or
        "100g"
    )
    # Convertir porcion a numero
    try:
        porcion_num = float(re.search(r"[\d.]+", str(porcion_g)).group())
    except Exception:
        porcion_num = 100.0

    # ── Extraer nutrientes ────────────────────────────────────────────────────
    # Open Food Facts guarda valores por 100g (_100g) y por porcion (_serving)
    # Preferimos por porcion si existe, sino usamos por 100g

    def get_nutriente(*claves, factor=1.0):
        """
        Busca el valor del nutriente probando multiples claves.
        Primero por porcion (_serving), luego por 100g calculando proporcion.
        Cubre variantes de nomenclatura de productos latinoamericanos.
        """
        for clave in claves:
            val = nutriments.get(clave)
            if val is not None:
                if "_100g" in clave and porcion_num != 100:
                    val = float(val) * (porcion_num / 100)
                return round(float(val) * factor, 2)
        return None

    datos = {
        "nombre_producto": (
            f"{nombre_prod} — {marca}".strip(" —") or "Producto escaneado"
        ),
        "porcion_g":  porcion_num,
        "calorias":   get_nutriente(
            "energy-kcal_serving", "energy-kcal_100g",
            "energy_kcal_serving", "energy_kcal_100g",
        ),
        "grasas_totales":   get_nutriente("fat_serving",           "fat_100g"),
        "grasas_saturadas": get_nutriente(
            "saturated-fat_serving", "saturated-fat_100g",
            "saturated_fat_serving", "saturated_fat_100g",
        ),
        "sodio":        get_nutriente("sodium_serving",        "sodium_100g",        factor=1000),
        "carbohidratos":get_nutriente("carbohydrates_serving", "carbohydrates_100g",
                                      "carbohydrate_serving",  "carbohydrate_100g"),
        "azucares":     get_nutriente("sugars_serving",  "sugars_100g"),
        "proteinas":    get_nutriente("proteins_serving", "proteins_100g",
                                      "protein_serving",  "protein_100g"),
        "fibra":        get_nutriente("fiber_serving",   "fiber_100g",
                                      "fibers_serving",  "fibers_100g"),
        # Metadata extra para mostrar en la UI
        "_codigo":          codigo,
        "_marca":           marca,
        "_pais":            pais,
        "_imagen_url":      producto.get("image_front_url", ""),
        "_nutriscore":      producto.get("nutriscore_grade", "").upper(),
        "_nova":            producto.get("nova_group", ""),
    }

    # Remover campos None para no romper el analisis
    datos = {k: v for k, v in datos.items() if v is not None or k.startswith("_")}

    return datos

# =============================================================================
# MODULO BASE DE DATOS LOCAL — SUPABASE
# =============================================================================

CAMPOS_NUTRIENTES = [
    "calorias", "grasas_totales", "grasas_saturadas",
    "sodio", "carbohidratos", "azucares", "proteinas", "fibra",
]


def _supa_get(endpoint: str, params: dict = None) -> list:
    """Ejecuta GET contra la REST API de Supabase."""
    url = f"{_REST_BASE}/{endpoint}"
    r   = _requests.get(url, headers=_SUPA_HEADERS, params=params, timeout=8)
    if r.status_code in (200, 206):
        return r.json()
    return []


def _supa_upsert(tabla: str, datos: dict) -> tuple:
    """Ejecuta UPSERT contra la REST API de Supabase."""
    url     = f"{_REST_BASE}/{tabla}"
    headers = {**_SUPA_HEADERS, "Prefer": "resolution=merge-duplicates,return=representation"}
    r = _requests.post(url, headers=headers, json=datos, timeout=8)
    if r.status_code in (200, 201):
        return True, ""
    return False, f"HTTP {r.status_code}: {r.text[:200]}"


def db_buscar_producto(codigo: str) -> dict | None:
    """
    Busca un producto en la base de datos NutriLab por codigo de barras.
    Retorna dict con los datos del producto, o None si no existe.
    """
    if not SUPABASE_DISPONIBLE:
        return None
    try:
        rows = _supa_get("productos", {
            "select":         "*",
            "codigo_barras":  f"eq.{codigo}",
            "limit":          "1"
        })
        return rows[0] if rows else None
    except Exception:
        return None


def db_guardar_producto(datos: dict, codigo: str, contribuidor: str = "anonimo"):
    """
    Guarda o actualiza un producto en la base de datos NutriLab via REST API.
    Retorna (True, "") si exitoso, o (False, mensaje_error) si fallo.
    """
    if not SUPABASE_DISPONIBLE:
        return False, "Supabase no disponible"
    try:
        registro = {
            "codigo_barras":   codigo,
            "nombre_producto": datos.get("nombre_producto", "Producto sin nombre"),
            "marca":           datos.get("_marca", "") or "",
            "pais":            datos.get("_pais", "Colombia") or "Colombia",
            "contribuidor":    contribuidor or "anonimo",
            "actualizado_en":  datetime.utcnow().isoformat(),
        }
        if datos.get("porcion_g"):
            registro["porcion_g"] = float(datos["porcion_g"])
        for campo in CAMPOS_NUTRIENTES:
            val = datos.get(campo)
            if val is not None and val != "":
                try:
                    registro[campo] = float(val)
                except (ValueError, TypeError):
                    pass
        return _supa_upsert("productos", registro)
    except Exception as e:
        return False, str(e)


def db_estadisticas() -> dict:
    """
    Retorna estadisticas generales de la base de datos NutriLab via REST API.
    """
    if not SUPABASE_DISPONIBLE:
        return {"total": 0, "verificados": 0}
    try:
        # Usar HEAD con Prefer: count=exact para obtener el total sin datos
        url = f"{_REST_BASE}/productos"
        r   = _requests.get(
            url,
            headers={**_SUPA_HEADERS, "Prefer": "count=exact"},
            params={"select": "id"},
            timeout=5
        )
        total = int(r.headers.get("content-range", "0/0").split("/")[-1] or 0)
        return {"total": total, "verificados": 0}
    except Exception:
        return {"total": 0, "verificados": 0}


# =============================================================================
# INTERFAZ STREAMLIT
# =============================================================================

st.set_page_config(
    page_title="NutriLab - Analizador Nutricional",
    page_icon="🥗",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    /* ── Sidebar base ── */
    [data-testid="stSidebar"] {
        background-color: #1a2535 !important;
    }

    /* ── Todos los textos de la sidebar ── */
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] span:not(.st-emotion-cache-x78sv8),
    [data-testid="stSidebar"] div:not([data-baseweb]),
    [data-testid="stSidebar"] h1,
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3 {
        color: #e6edf3 !important;
    }

    /* ── Pestanas (tabs) dentro de sidebar ── */
    [data-testid="stSidebar"] [data-baseweb="tab-list"] {
        background-color: #0f1923 !important;
        border-radius: 8px !important;
        padding: 3px !important;
        gap: 3px !important;
    }
    [data-testid="stSidebar"] [data-baseweb="tab"] {
        background-color: transparent !important;
        color: #8fa8bf !important;
        border-radius: 6px !important;
        font-weight: 600 !important;
        font-size: 0.85rem !important;
        padding: 6px 12px !important;
        border: none !important;
    }
    [data-testid="stSidebar"] [aria-selected="true"] {
        background-color: #2ecc71 !important;
        color: #ffffff !important;
    }
    [data-testid="stSidebar"] [data-baseweb="tab-highlight"] {
        display: none !important;
    }
    [data-testid="stSidebar"] [data-baseweb="tab-border"] {
        display: none !important;
    }

    /* ── Inputs de texto ── */
    [data-testid="stSidebar"] input[type="text"],
    [data-testid="stSidebar"] input[type="number"] {
        background-color: #243447 !important;
        color: #ffffff !important;
        border: 1.5px solid #3d5a73 !important;
        border-radius: 8px !important;
        caret-color: #2ecc71 !important;
        padding: 6px 10px !important;
    }
    [data-testid="stSidebar"] input[type="text"]:focus,
    [data-testid="stSidebar"] input[type="number"]:focus {
        border-color: #2ecc71 !important;
        box-shadow: 0 0 0 2px rgba(46,204,113,0.2) !important;
    }

    /* ── Placeholder ── */
    [data-testid="stSidebar"] input::placeholder {
        color: #6b8ba4 !important;
        opacity: 1 !important;
    }

    /* ── Flechas del number input ── */
    [data-testid="stSidebar"] [data-testid="stNumberInput"] button {
        background-color: #2c4159 !important;
        color: #e6edf3 !important;
        border: none !important;
        border-radius: 4px !important;
    }
    [data-testid="stSidebar"] [data-testid="stNumberInput"] button:hover {
        background-color: #2ecc71 !important;
        color: #fff !important;
    }

    /* ── Zona de carga de imagen (file uploader) ── */
    [data-testid="stSidebar"] [data-testid="stFileUploader"] {
        background-color: #162030 !important;
        border: 2px dashed #4a7a96 !important;
        border-radius: 12px !important;
        padding: 8px !important;
        transition: border-color 0.2s !important;
    }
    [data-testid="stSidebar"] [data-testid="stFileUploader"]:hover {
        border-color: #2ecc71 !important;
    }

    /* Todos los textos internos del uploader */
    [data-testid="stSidebar"] [data-testid="stFileUploader"] *,
    [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] *,
    [data-testid="stSidebar"] [data-testid="stFileUploaderDropzoneInstructions"] *,
    [data-testid="stSidebar"] [data-testid="stFileUploaderDropzoneInstructions"] span,
    [data-testid="stSidebar"] [data-testid="stFileUploaderDropzoneInstructions"] small,
    [data-testid="stSidebar"] section[data-testid="stFileUploaderDropzone"] span,
    [data-testid="stSidebar"] section[data-testid="stFileUploaderDropzone"] small {
        color: #c8dcea !important;
        opacity: 1 !important;
    }

    /* Texto "200MB per file • JPG, PNG..." */
    [data-testid="stSidebar"] [data-testid="stFileUploader"] small,
    [data-testid="stSidebar"] [data-testid="stFileUploader"] .uploadInstructions,
    [data-testid="stSidebar"] [data-testid="stFileUploader"] span[class*="instruc"],
    [data-testid="stSidebar"] [class*="fileUploaderDropzoneInstructions"] span {
        color: #c8dcea !important;
        font-size: 0.78rem !important;
        opacity: 1 !important;
    }

    /* Icono de subida */
    [data-testid="stSidebar"] [data-testid="stFileUploader"] svg {
        fill: #4a9ebe !important;
        opacity: 1 !important;
    }

    /* Boton Browse files */
    [data-testid="stSidebar"] [data-testid="stFileUploader"] button,
    [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button {
        background-color: #1e3a52 !important;
        color: #2ecc71 !important;
        border: 1.5px solid #2ecc71 !important;
        border-radius: 6px !important;
        font-weight: 700 !important;
        font-size: 0.82rem !important;
        padding: 5px 14px !important;
        opacity: 1 !important;
    }
    [data-testid="stSidebar"] [data-testid="stFileUploader"] button:hover,
    [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button:hover {
        background-color: #2ecc71 !important;
        color: #ffffff !important;
    }

    /* Nombre del archivo una vez cargado */
    [data-testid="stSidebar"] [data-testid="stFileUploader"] [data-testid="stFileUploaderFileName"],
    [data-testid="stSidebar"] [data-testid="stFileUploader"] li span,
    [data-testid="stSidebar"] [data-testid="stFileUploader"] li,
    [data-testid="stSidebar"] [data-testid="stFileUploader"] li p,
    [data-testid="stSidebar"] [data-testid="stFileUploader"] [class*="uploadedFile"] span,
    [data-testid="stSidebar"] [data-testid="stFileUploader"] [class*="uploadedFile"] p,
    [data-testid="stSidebar"] [data-testid="stFileUploader"] [class*="fileName"],
    [data-testid="stSidebar"] [data-testid="stFileUploader"] [class*="fileSize"] {
        color: #ffffff !important;
        font-weight: 600 !important;
        opacity: 1 !important;
    }

    /* Contenedor del archivo cargado */
    [data-testid="stSidebar"] [data-testid="stFileUploader"] [class*="uploadedFile"],
    [data-testid="stSidebar"] [data-testid="stFileUploader"] li {
        background-color: #1e3a52 !important;
        border-radius: 8px !important;
        padding: 6px 10px !important;
        border: 1px solid #3d5a73 !important;
        margin-top: 6px !important;
    }

    /* Icono de previa del archivo */
    [data-testid="stSidebar"] [data-testid="stFileUploader"] [class*="uploadedFile"] img,
    [data-testid="stSidebar"] [data-testid="stFileUploader"] [class*="fileIcon"] {
        opacity: 1 !important;
        border-radius: 4px !important;
    }

    /* Boton X para eliminar archivo */
    [data-testid="stSidebar"] [data-testid="stFileUploader"] [class*="deleteBtn"],
    [data-testid="stSidebar"] [data-testid="stFileUploader"] button[title="Delete file"] {
        color: #e74c3c !important;
        opacity: 1 !important;
        background: transparent !important;
        border: none !important;
    }
    [data-testid="stSidebar"] [data-testid="stFileUploader"] button[title="Delete file"]:hover {
        color: #ffffff !important;
        background: #e74c3c !important;
        border-radius: 4px !important;
    }

    /* ── Previa de imagen subida ── */
    [data-testid="stSidebar"] img {
        border-radius: 10px !important;
        border: 2px solid #3d5a73 !important;
        margin-top: 8px !important;
    }

    /* ── Cajas info/warning/error en sidebar ── */
    [data-testid="stSidebar"] [data-testid="stAlert"] {
        background-color: #1a2f45 !important;
        border-radius: 8px !important;
    }
    [data-testid="stSidebar"] [data-testid="stAlert"] * {
        color: #c8dcea !important;
    }

    /* ── Divider sidebar ── */
    [data-testid="stSidebar"] hr {
        border-color: #243447 !important;
        margin: 8px 0 !important;
    }

    /* ── Boton principal Analizar ── */
    [data-testid="stSidebar"] .stButton > button {
        background: linear-gradient(135deg, #2ecc71, #27ae60) !important;
        color: white !important;
        border-radius: 10px !important;
        border: none !important;
        font-weight: 700 !important;
        font-size: 0.95rem !important;
        padding: 10px 24px !important;
        width: 100% !important;
        margin-top: 8px !important;
        box-shadow: 0 4px 12px rgba(46,204,113,0.3) !important;
        transition: all 0.2s !important;
    }
    [data-testid="stSidebar"] .stButton > button:hover {
        transform: translateY(-1px) !important;
        box-shadow: 0 6px 16px rgba(46,204,113,0.4) !important;
    }

    /* ── Alertas en area principal ── */
    .alerta-rojo {
        background: #3d1a1a !important;
        border-left: 4px solid #e74c3c !important;
        padding: 10px 14px !important;
        border-radius: 8px !important;
        margin: 4px 0 !important;
        font-size: 0.9rem !important;
        color: #f5c6c6 !important;
    }
    .alerta-amarillo {
        background: #3d2e0a !important;
        border-left: 4px solid #f39c12 !important;
        padding: 10px 14px !important;
        border-radius: 8px !important;
        margin: 4px 0 !important;
        font-size: 0.9rem !important;
        color: #f5dfa0 !important;
    }
    .alerta-verde {
        background: #0d2e1a !important;
        border-left: 4px solid #2ecc71 !important;
        padding: 10px 14px !important;
        border-radius: 8px !important;
        margin: 4px 0 !important;
        font-size: 0.9rem !important;
        color: #a8f0c6 !important;
    }

    /* ── Ocultar borde inferior de tabs en sidebar ── */
    [data-testid="stSidebar"] .stTabs [data-baseweb="tab-panel"] {
        padding-top: 12px !important;
    }

    /* ── Respaldo global: fuerza visibilidad en todos los spans del sidebar ── */
    /* Cubre clases dinámicas que Streamlit genera en runtime */
    [data-testid="stSidebar"] section[data-testid="stFileUploaderDropzone"] {
        background-color: #162030 !important;
        border-radius: 10px !important;
    }
    [data-testid="stSidebar"] section[data-testid="stFileUploaderDropzone"] span {
        color: #c8dcea !important;
        opacity: 1 !important;
        visibility: visible !important;
    }
    [data-testid="stSidebar"] section[data-testid="stFileUploaderDropzone"] small {
        color: #8fb8d0 !important;
        opacity: 1 !important;
        font-size: 0.75rem !important;
    }
    [data-testid="stSidebar"] section[data-testid="stFileUploaderDropzone"] p {
        color: #c8dcea !important;
    }

    /* Forzar color en cualquier texto claro sobre fondo oscuro */
    [data-testid="stSidebar"] [class*="overflowMenuButton"],
    [data-testid="stSidebar"] [class*="uploadInstruction"],
    [data-testid="stSidebar"] [class*="fileDropInstructions"] {
        color: #c8dcea !important;
        opacity: 1 !important;
    }
</style>
""", unsafe_allow_html=True)

# ─── Sidebar ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🥗 NutriLab")
    st.markdown("*Res. 810/2021 · Min. Salud Colombia*")
    st.divider()

    # Pestanas: Manual / Foto OCR
    tab_manual, tab_ocr = st.tabs(["✏️  Manual", "📷  Foto OCR"])

    # ── PESTAÑA MANUAL ────────────────────────────────────────────────────────
    with tab_manual:
        st.markdown("**Producto**")
        nombre  = st.text_input("Nombre", placeholder="Ej: Avena Quaker",
                                label_visibility="collapsed",
                                key="nombre_manual")
        porcion = st.number_input("Porcion (g/ml)", 0.0, 2000.0, 30.0, 1.0,
                                  key="porcion_manual")

        st.markdown("**Valores nutricionales**")
        st.caption(f"Todos los valores son **por porcion** ({porcion:.0f} g/ml)")
        calorias         = st.number_input("Calorias (kcal)",      0.0, 2000.0, 0.0, 1.0)
        grasas_totales   = st.number_input("Grasas totales (g)",   0.0,  200.0, 0.0, 0.1)
        grasas_saturadas = st.number_input("Grasas saturadas (g)", 0.0,  100.0, 0.0, 0.1)
        sodio            = st.number_input("Sodio (mg)",           0.0, 5000.0, 0.0, 1.0)
        carbohidratos    = st.number_input("Carbohidratos (g)",    0.0,  500.0, 0.0, 0.1)
        azucares         = st.number_input("Azucares (g)",         0.0,  300.0, 0.0, 0.1)
        proteinas        = st.number_input("Proteinas (g)",        0.0,  100.0, 0.0, 0.1)
        fibra            = st.number_input("Fibra dietaria (g)",   0.0,  100.0, 0.0, 0.1)

        analizar_manual = st.button("🔍  Analizar producto",
                                    use_container_width=True,
                                    key="btn_manual")
        datos_formulario = {
            "nombre_producto":  nombre or "Producto sin nombre",
            "porcion_g":        porcion,
            "calorias":         calorias,
            "grasas_totales":   grasas_totales,
            "grasas_saturadas": grasas_saturadas,
            "sodio":            sodio,
            "carbohidratos":    carbohidratos,
            "azucares":         azucares,
            "proteinas":        proteinas,
            "fibra":            fibra,
        }
        modo    = "Manual"
        analizar = analizar_manual

    # ── PESTAÑA CODIGO DE BARRAS ─────────────────────────────────────────────
    with tab_ocr:
        if not BARCODE_DISPONIBLE:
            st.error(f"Libreria no disponible: `{BARCODE_ERROR}`\n\n"
                     "Agregue `pyzbar` a requirements.txt y haga Reboot app.")
        else:
            st.markdown("""
<div style='background:#162030;border-radius:10px;padding:10px 12px;
            border:1px solid #3d5a73;margin-bottom:10px;font-size:0.8rem;
            color:#a8c4d8;line-height:1.6'>
📦 <b style="color:#2ecc71">Como tomar la foto</b><br>
• Enfoca solo el codigo de barras<br>
• Iluminacion uniforme, sin sombras<br>
• Foto horizontal, codigo centrado<br>
• Base de datos: Open Food Facts
</div>
""", unsafe_allow_html=True)

            archivo_bc = st.file_uploader(
                "Foto del codigo de barras",
                type=["jpg", "jpeg", "png", "bmp", "webp"],
                help="EAN-13, EAN-8, UPC-A, UPC-E",
                key="file_barcode",
            )

            if archivo_bc:
                st.image(archivo_bc, caption="Imagen cargada",
                         use_container_width=True)

            analizar_bc = st.button(
                "🔍  Escanear codigo",
                use_container_width=True,
                disabled=(not BARCODE_DISPONIBLE or archivo_bc is None),
                key="btn_barcode",
            )

        datos_formulario_bc = {}
        if BARCODE_DISPONIBLE and archivo_bc:
            img_bytes = archivo_bc.read()
            datos_formulario_bc["_imagen_bytes_bc"] = img_bytes
            # Marcar imagen nueva para forzar re-escaneo
            img_hash = hash(img_bytes)
            if st.session_state.get("bc_img_hash") != img_hash:
                st.session_state["bc_img_hash"]     = img_hash
                st.session_state["bc_imagen_nueva"] = True

        if analizar_bc:
            modo             = "Barcode"
            analizar         = True
            datos_formulario = datos_formulario_bc
        else:
            if not analizar_manual:
                modo             = "Barcode"
                analizar         = False
                datos_formulario = datos_formulario_bc




# ─── Area principal ───────────────────────────────────────────────────────────
col_titulo, col_stats = st.columns([3, 1])
with col_titulo:
    st.markdown("# NutriLab")
    st.markdown("**Analizador de Etiquetas Nutricionales** - Resolucion 810/2021 - Min. Salud Colombia")
with col_stats:
    if SUPABASE_DISPONIBLE:
        stats = db_estadisticas()
        st.markdown(
            f"<div style='background:#1a2535;border-radius:10px;padding:12px;"
            f"text-align:center;border:1px solid #2c3e50'>"
            f"<div style='color:#2ecc71;font-size:1.6rem;font-weight:800'>"
            f"{stats['total']}</div>"
            f"<div style='color:#8fa8bf;font-size:0.72rem'>productos en</div>"
            f"<div style='color:#e6edf3;font-size:0.78rem;font-weight:600'>"
            f"NutriLab DB</div></div>",
            unsafe_allow_html=True
        )
    else:
        with st.expander("BD no conectada", expanded=False):
            st.error("**Supabase no conectado**")
            st.code(SUPABASE_ERROR or "Error desconocido")
            _project_ref_diag = _SUPA_URL.replace("https://","").split(".")[0] if _SUPA_URL else "???"
            st.markdown("**URLs probadas:**")
            for _u in [
                f"{_SUPA_URL}/rest/v1/productos",
                f"https://{_project_ref_diag}.supabase.co/rest/v1/productos",
            ]:
                st.code(_u)
            st.markdown(
                "**Verifique en Streamlit Secrets:**\n"
                "```toml\n"
                "SUPABASE_URL = \"https://ukvzayirmznuxclbfoaf.supabase.co\"\n"
                "SUPABASE_KEY = \"eyJ...\"\n"
                "```"
            )

# Panel de diagnostico Barcode (visible solo cuando falla)
if not BARCODE_DISPONIBLE:
    with st.expander("Diagnostico — Lector de codigo de barras", expanded=False):
        st.code(f"Error: {BARCODE_ERROR}")
        st.info(
            "Asegurese de que `pyzbar` este en requirements.txt\n"
            "y haga **Reboot app** en Streamlit Cloud."
        )

st.divider()

# Si hay datos de barcode en session_state con formulario pendiente, continuar
if not analizar and "bc_datos" in st.session_state:
    analizar = True
    modo = "Barcode"

if not analizar:
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("#### Ingreso manual")
        st.markdown("Digita los valores de la etiqueta campo por campo con validacion automatica.")
    with c2:
        st.markdown("#### Escaneo OCR")
        st.markdown("Escanea el codigo de barras del producto y obtiene los nutrientes automaticamente desde Open Food Facts.")
    with c3:
        st.markdown("#### Reporte PDF")
        st.markdown("Descarga un reporte con tabla, semaforo, grafica y alertas.")
    st.info("Complete el formulario en la barra lateral y presione Analizar producto.")
    st.stop()


# ─── Procesamiento ────────────────────────────────────────────────────────────
resultado = None

if modo == "Manual":
    with st.spinner("Analizando nutrientes..."):
        campos_principales = ["calorias", "grasas_totales", "sodio",
                              "carbohidratos", "proteinas"]
        vacios = [c for c in campos_principales if datos_formulario.get(c, 0) == 0]
        if len(vacios) >= 4:
            st.error("Por favor ingrese al menos calorias, grasas totales, "
                     "sodio, carbohidratos y proteinas.")
            st.stop()
        resultado = analizar_nutrientes(datos_formulario)

else:
    imagen_bytes_bc = datos_formulario.get("_imagen_bytes_bc")

    # Si no hay imagen pero hay datos en session_state, continuar con esos datos
    # (esto ocurre cuando el usuario presiona submit en el formulario)
    tiene_session = "bc_datos" in st.session_state and not st.session_state.get("bc_imagen_nueva")

    if not imagen_bytes_bc and not tiene_session:
        st.error("Suba una imagen con el codigo de barras del producto.")
        st.stop()

    try:
        if "bc_datos" not in st.session_state or st.session_state.get("bc_imagen_nueva"):

            with st.status("Leyendo codigo de barras...", expanded=True) as status:

                # Paso 1: decodificar
                st.write("Detectando codigo de barras en la imagen...")
                codigo, tipo_bc = barcode_leer_imagen(imagen_bytes_bc)
                st.write(f"Codigo detectado: **{codigo}** ({tipo_bc})")

                # Paso 2: buscar en NutriLab primero
                datos_bc     = None
                fuente_datos = ""

                if SUPABASE_DISPONIBLE:
                    st.write("Buscando en base de datos NutriLab...")
                    registro_local = db_buscar_producto(codigo)
                    if registro_local:
                        datos_bc = {k: registro_local.get(k)
                                    for k in ["nombre_producto","porcion_g"] + CAMPOS_NUTRIENTES
                                    if registro_local.get(k) is not None}
                        datos_bc["_marca"]      = registro_local.get("marca", "")
                        datos_bc["_pais"]       = registro_local.get("pais", "")
                        datos_bc["_imagen_url"] = ""
                        datos_bc["_nutriscore"] = ""
                        fuente_datos = "nutrilab"
                        st.write(f"Encontrado en NutriLab: **{datos_bc['nombre_producto']}**")

                # Paso 3: Open Food Facts si no está en NutriLab
                if datos_bc is None:
                    st.write("Consultando Open Food Facts...")
                    try:
                        datos_bc     = barcode_consultar_api(codigo)
                        fuente_datos = "openfoodfacts"
                    except (ValueError, ConnectionError):
                        # No encontrado o timeout — crear entrada nueva
                        datos_bc = {
                            "nombre_producto": f"Producto {codigo}",
                            "_marca": "", "_pais": "Colombia",
                            "_imagen_url": "", "_nutriscore": "",
                        }
                        fuente_datos = "nuevo"

                nombre_encontrado = datos_bc.get("nombre_producto", "Desconocido")
                marca_encontrada  = datos_bc.get("_marca", "")
                nutriscore        = datos_bc.get("_nutriscore", "")
                imagen_url        = datos_bc.get("_imagen_url", "")

                status.update(
                    label=f"Producto encontrado: {nombre_encontrado}",
                    state="complete"
                )

            # Guardar en session_state para no re-escanear en cada rerun
            st.session_state["bc_datos"]        = datos_bc
            st.session_state["bc_codigo"]       = codigo
            st.session_state["bc_fuente"]       = fuente_datos
            st.session_state["bc_imagen_nueva"] = False

        else:
            # Recuperar datos del session_state
            datos_bc          = st.session_state["bc_datos"]
            codigo            = st.session_state["bc_codigo"]
            fuente_datos      = st.session_state["bc_fuente"]
            nombre_encontrado = datos_bc.get("nombre_producto", "Desconocido")
            marca_encontrada  = datos_bc.get("_marca", "")
            nutriscore        = datos_bc.get("_nutriscore", "")
            imagen_url        = datos_bc.get("_imagen_url", "")

        # Mostrar tarjeta del producto encontrado
        col_img, col_info = st.columns([1, 2])
        with col_img:
            if imagen_url:
                st.image(imagen_url, width=120)
            else:
                st.markdown(
                    "<div style='background:#1a2535;border-radius:10px;"
                    "height:80px;display:flex;align-items:center;"
                    "justify-content:center;font-size:2rem'>📦</div>",
                    unsafe_allow_html=True
                )
        with col_info:
            st.markdown(f"**{nombre_encontrado}**")
            if marca_encontrada:
                st.caption(f"Marca: {marca_encontrada}")

            # Badge de fuente de datos
            if fuente_datos == "nutrilab":
                st.markdown(
                    "<span style='background:#2ecc71;color:white;padding:2px 10px;"
                    "border-radius:6px;font-size:0.75rem;font-weight:700'>"
                    "NutriLab DB</span>",
                    unsafe_allow_html=True
                )
            elif fuente_datos == "openfoodfacts":
                st.markdown(
                    "<span style='background:#3498db;color:white;padding:2px 10px;"
                    "border-radius:6px;font-size:0.75rem;font-weight:700'>"
                    "Open Food Facts</span>",
                    unsafe_allow_html=True
                )
            else:
                st.markdown(
                    "<span style='background:#e67e22;color:white;padding:2px 10px;"
                    "border-radius:6px;font-size:0.75rem;font-weight:700'>"
                    "Nuevo producto</span>",
                    unsafe_allow_html=True
                )

            if nutriscore:
                colores_ns = {"A":"#2ecc71","B":"#82c341","C":"#f9c74f",
                              "D":"#f39c12","E":"#e74c3c"}
                color_ns = colores_ns.get(nutriscore, "#888")
                st.markdown(
                    f"<span style='background:{color_ns};color:white;"
                    f"padding:2px 10px;border-radius:6px;font-weight:700;"
                    f"font-size:0.85rem'>Nutri-Score {nutriscore}</span>",
                    unsafe_allow_html=True
                )
            st.caption(f"Codigo: {codigo}")

        # Limpiar metadata antes de analizar
        datos_limpios = {k: v for k, v in datos_bc.items()
                         if not k.startswith("_")}

        # ── Detectar nutrientes faltantes y manejar formulario ─────────
        CAMPOS_REQUERIDOS = {
            "calorias":         "Calorias (kcal)",
            "grasas_totales":   "Grasas totales (g)",
            "grasas_saturadas": "Grasas saturadas (g)",
            "sodio":            "Sodio (mg)",
            "carbohidratos":    "Carbohidratos (g)",
            "azucares":         "Azucares (g)",
            "proteinas":        "Proteinas (g)",
            "fibra":            "Fibra (g)",
        }
        LIMITES = {
            "calorias":         (0.0, 2000.0, 1.0),
            "grasas_totales":   (0.0,  200.0, 0.1),
            "grasas_saturadas": (0.0,  100.0, 0.1),
            "sodio":            (0.0, 5000.0, 1.0),
            "carbohidratos":    (0.0,  500.0, 0.1),
            "azucares":         (0.0,  300.0, 0.1),
            "proteinas":        (0.0,  100.0, 0.1),
            "fibra":            (0.0,  100.0, 0.1),
        }

        faltantes   = [c for c in CAMPOS_REQUERIDOS
                       if c not in datos_limpios or datos_limpios.get(c) is None]
        encontrados = len(CAMPOS_REQUERIDOS) - len(faltantes)

        if faltantes:
            msg = (
                f"Producto no encontrado en ninguna base de datos. "
                f"Ingrese los {len(faltantes)} valores nutricionales:"
                if fuente_datos == "nuevo"
                else f"**{encontrados} de 8 nutrientes encontrados.** "
                     f"Complete los {len(faltantes)} campos faltantes:"
            )
            st.warning(msg)

            # Formulario con claves ss_ que persisten en session_state
            with st.form("form_completar_bc", clear_on_submit=False):
                st.markdown("#### Completar nutrientes faltantes")
                _porcion_bc = (datos_limpios.get("porcion_g") or
                               datos_bc.get("porcion_g") or 100)
                st.info(
                    f"Ingrese los valores **por porcion** ({_porcion_bc:.0f} g/ml) "
                    "tal como aparecen en la etiqueta del producto."
                )

                if fuente_datos == "nuevo":
                    st.text_input("Nombre del producto",
                                  value=nombre_encontrado,
                                  key="ss_nombre")

                cols = st.columns(2)
                for i, campo in enumerate(faltantes):
                    mn, mx, step = LIMITES[campo]
                    with cols[i % 2]:
                        st.number_input(
                            CAMPOS_REQUERIDOS[campo],
                            min_value=mn, max_value=mx,
                            value=0.0, step=step,
                            key=f"ss_{campo}"
                        )

                st.divider()
                st.text_input("Tu nombre o alias (opcional)",
                              placeholder="Ej: Johan",
                              key="ss_contribuidor")
                st.checkbox(
                    "Guardar en NutriLab DB para ayudar a otros usuarios",
                    value=True,
                    disabled=not SUPABASE_DISPONIBLE,
                    key="ss_guardar"
                )
                submit_btn = st.form_submit_button(
                    "Analizar y guardar",
                    use_container_width=True
                )

            if not submit_btn:
                st.stop()

            # Leer valores desde session_state (persisten tras el rerun)
            if fuente_datos == "nuevo":
                datos_limpios["nombre_producto"] = (
                    st.session_state.get("ss_nombre") or nombre_encontrado
                )

            for campo in faltantes:
                val = st.session_state.get(f"ss_{campo}", 0.0)
                if val and float(val) > 0:
                    datos_limpios[campo] = float(val)

            guardar_bd   = st.session_state.get("ss_guardar", True)
            contribuidor = st.session_state.get("ss_contribuidor", "") or "anonimo"

            if guardar_bd and SUPABASE_DISPONIBLE:
                datos_para_guardar = {**datos_bc, **datos_limpios}
                exito, error_msg = db_guardar_producto(
                    datos_para_guardar,
                    codigo,
                    contribuidor.strip()
                )
                if exito:
                    st.success(
                        "Gracias por contribuir a NutriLab. "
                        "Este producto ya estara disponible para otros usuarios."
                    )
                    st.balloons()
                    for k in ["bc_datos","bc_codigo","bc_fuente","bc_imagen_nueva"]:
                        st.session_state.pop(k, None)
                else:
                    st.error(f"Error al guardar: {error_msg}")

        resultado = analizar_nutrientes(datos_limpios)

    except ValueError as e:
        st.error(str(e))
        st.info("Puede ingresar los datos manualmente en la pestana **Manual**.")
        st.stop()
    except ConnectionError as e:
        st.error(str(e))
        st.stop()
    except Exception as e:
        st.error(f"Error inesperado: {e}")
        st.stop()


# ─── Resultados ───────────────────────────────────────────────────────────────
nombre_producto = resultado["nombre_producto"]
porcentajes     = resultado["porcentajes"]
semaforo        = resultado["semaforo"]
puntaje         = resultado["puntaje"]
alertas         = resultado["alertas"]
recomendacion   = resultado["recomendacion"]

st.markdown(f"## {nombre_producto}")

cm1, cm2, cm3, cm4 = st.columns(4)
with cm1:
    st.metric("Puntaje de salud", f"{puntaje:.1f} / 100",
              "Saludable" if puntaje >= 75 else "Moderado" if puntaje >= 50 else "Riesgo",
              delta_color="normal" if puntaje >= 50 else "inverse")
with cm2:
    cal = resultado["datos_originales"].get("calorias", 0)
    st.metric("Calorias", f"{cal:.0f} kcal",
              f"{porcentajes.get('calorias', 0):.1f}% VRD")
with cm3:
    sod = resultado["datos_originales"].get("sodio", 0)
    st.metric("Sodio", f"{sod:.0f} mg",
              f"{porcentajes.get('sodio', 0):.1f}% VRD")
with cm4:
    azu = resultado["datos_originales"].get("azucares", 0)
    st.metric("Azucares", f"{azu:.1f} g",
              f"{porcentajes.get('azucares', 0):.1f}% VRD")

st.divider()

# Tabla + Grafica
ETIQUETAS_UI = {
    "calorias":         ("Calorias",         "kcal"),
    "grasas_totales":   ("Grasas totales",   "g"),
    "grasas_saturadas": ("Grasas saturadas", "g"),
    "sodio":            ("Sodio",            "mg"),
    "carbohidratos":    ("Carbohidratos",    "g"),
    "azucares":         ("Azucares",         "g"),
    "proteinas":        ("Proteinas",        "g"),
    "fibra":            ("Fibra",            "g"),
}

COLOR_HEX_UI  = {"VERDE": "#2ecc71", "AMARILLO": "#f39c12", "ROJO": "#e74c3c"}
COLOR_MPL     = {"VERDE": "#2ecc71", "AMARILLO": "#f39c12", "ROJO": "#e74c3c"}

col_tabla, col_graf = st.columns([1, 1.4], gap="large")

with col_tabla:
    porcion_mostrar = resultado["datos_originales"].get("porcion_g", 0)
    if porcion_mostrar and porcion_mostrar > 0:
        st.markdown(f"### Semaforo nutricional  "
                    f"<span style='font-size:0.75rem;color:#8fa8bf;font-weight:400'>"
                    f"valores por porcion ({porcion_mostrar:.0f} g/ml)</span>",
                    unsafe_allow_html=True)
    else:
        st.markdown("### Semaforo nutricional")
    filas = ""
    for clave, (etiqueta, unidad) in ETIQUETAS_UI.items():
        if clave not in porcentajes:
            continue
        pct_v    = porcentajes[clave]
        valor    = resultado["datos_originales"].get(clave, 0)
        info_sem = semaforo.get(clave, {})
        color    = COLOR_HEX_UI.get(info_sem.get("color", "AMARILLO"), "#f39c12")
        nivel    = info_sem.get("etiqueta", "-")
        val_str  = f"{valor:.1f}" if isinstance(valor, float) else str(valor)
        filas += f"""
        <tr>
          <td style='padding:6px 8px;font-size:.85rem'>{etiqueta}</td>
          <td style='padding:6px 8px;text-align:center;font-size:.85rem'>
              {val_str} {unidad}</td>
          <td style='padding:6px 8px;text-align:center;font-size:.85rem'>
              {pct_v:.1f}%</td>
          <td style='padding:6px 8px;text-align:center'>
              <span style='background:{color};color:white;padding:2px 10px;
              border-radius:12px;font-size:.75rem;font-weight:700'>
              {nivel}</span></td>
        </tr>"""

    st.markdown(f"""
    <table style='width:100%;border-collapse:collapse'>
      <thead><tr style='background:#2c3e50;color:white'>
        <th style='padding:8px;text-align:left;font-size:.8rem'>Nutriente</th>
        <th style='padding:8px;text-align:center;font-size:.8rem'>Valor</th>
        <th style='padding:8px;text-align:center;font-size:.8rem'>% VRD</th>
        <th style='padding:8px;text-align:center;font-size:.8rem'>Nivel</th>
      </tr></thead>
      <tbody>{filas}</tbody>
    </table>""", unsafe_allow_html=True)

with col_graf:
    porcion_graf = resultado["datos_originales"].get("porcion_g", 0)
    etiqueta_porcion = f" (por porcion {porcion_graf:.0f} g/ml)" if porcion_graf else ""
    st.markdown(f"### Porcentajes VRD{etiqueta_porcion}")
    etiq_g, vals_g, cols_g = [], [], []
    for clave, (etiqueta, _) in ETIQUETAS_UI.items():
        if clave in porcentajes:
            etiq_g.append(etiqueta)
            vals_g.append(porcentajes[clave])
            cols_g.append(COLOR_MPL.get(
                semaforo.get(clave, {}).get("color", "AMARILLO"), "#f39c12"))

    fig, ax = plt.subplots(figsize=(7, 4.5))
    fig.patch.set_facecolor("#f8f9fa")
    ax.set_facecolor("#ffffff")
    pos    = np.arange(len(etiq_g))
    barras = ax.barh(pos, vals_g, color=cols_g, height=0.6,
                     edgecolor="white", linewidth=1)
    ax.axvline(x=100, color="#c0392b", linestyle="--", linewidth=1.5, alpha=0.7)
    for barra, val in zip(barras, vals_g):
        ax.text(val + 1, barra.get_y() + barra.get_height() / 2,
                f"{val:.1f}%", va="center", ha="left",
                fontsize=8, color="#2c3e50", fontweight="bold")
    ax.set_yticks(pos)
    ax.set_yticklabels(etiq_g, fontsize=9)
    ax.set_xlabel("% del Valor de Referencia Diario", fontsize=9)
    ax.set_xlim(0, max(max(vals_g) * 1.3, 115) if vals_g else 115)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.xaxis.grid(True, linestyle="--", alpha=0.3)
    ax.set_axisbelow(True)
    p1 = mpatches.Patch(color="#2ecc71", label="Bajo / Adecuado")
    p2 = mpatches.Patch(color="#f39c12", label="Medio / Bajo")
    p3 = mpatches.Patch(color="#e74c3c", label="Alto / Muy bajo")
    ax.legend(handles=[p1, p2, p3], loc="lower right", fontsize=8, framealpha=0.9)
    plt.tight_layout()
    st.pyplot(fig, use_container_width=True)
    plt.close(fig)

st.divider()

# Barra puntaje
st.markdown("### Puntaje de salud general")
color_b = "#2ecc71" if puntaje >= 75 else "#f39c12" if puntaje >= 50 else "#e74c3c"
st.markdown(f"""
<div style='background:#e0e0e0;border-radius:20px;height:28px;width:100%;margin-bottom:8px'>
  <div style='background:{color_b};width:{puntaje}%;height:28px;border-radius:20px;
              display:flex;align-items:center;padding-left:12px'>
    <span style='color:white;font-weight:700;font-size:.9rem'>{puntaje:.1f} / 100</span>
  </div>
</div>""", unsafe_allow_html=True)
st.markdown(f"**{recomendacion}**")
st.divider()

# Alertas
st.markdown("### Alertas nutricionales")
for alerta in alertas:
    al = alerta.lower()
    if "alto" in al or "evitar" in al:
        bg, borde, color = "#3d1a1a", "#e74c3c", "#f5c6c6"
        icono = "⚠️"
    elif "bajo" in al or "posible" in al:
        bg, borde, color = "#3d2e0a", "#f39c12", "#f5dfa0"
        icono = "ℹ️"
    else:
        bg, borde, color = "#0d2e1a", "#2ecc71", "#a8f0c6"
        icono = "✅"
    st.markdown(
        f'''<div style="background:{bg};border-left:4px solid {borde};
        padding:10px 14px;border-radius:8px;margin:4px 0;
        font-size:0.9rem;color:{color};line-height:1.5">
        {icono} {alerta}</div>''',
        unsafe_allow_html=True
    )

st.divider()

# Descarga PDF
st.markdown("### Exportar reporte")
ruta_tmp_png = "/tmp/grafica_nutrilab.png"
fig2, ax2 = plt.subplots(figsize=(10, 5))
fig2.patch.set_facecolor("#f8f9fa")
ax2.set_facecolor("#ffffff")
ax2.barh(pos, vals_g, color=cols_g, height=0.6, edgecolor="white")
ax2.axvline(x=100, color="#c0392b", linestyle="--", linewidth=1.5, alpha=0.7)
for barra, val in zip(ax2.patches, vals_g):
    ax2.text(val + 1, barra.get_y() + barra.get_height() / 2,
             f"{val:.1f}%", va="center", ha="left", fontsize=8)
ax2.set_yticks(pos)
ax2.set_yticklabels(etiq_g, fontsize=9)
ax2.set_xlabel("% VRD", fontsize=9)
ax2.set_xlim(0, max(max(vals_g) * 1.3, 115) if vals_g else 115)
ax2.spines["top"].set_visible(False)
ax2.spines["right"].set_visible(False)
plt.tight_layout()
plt.savefig(ruta_tmp_png, dpi=150, bbox_inches="tight", facecolor="#f8f9fa")
plt.close(fig2)

try:
    pdf_bytes = generar_pdf_bytes(resultado, ruta_tmp_png)
    nombre_safe = (_limpiar(nombre_producto)[:30]
                   .replace(" ", "_").replace("/", "_")
                   .replace("-", "_"))
    st.download_button(
        label               = "Descargar reporte PDF",
        data                = pdf_bytes,
        file_name           = f"reporte_{nombre_safe}.pdf",
        mime                = "application/pdf",
        use_container_width = True,
    )
except Exception as e:
    st.error(f"No se pudo generar el PDF: {e}")

st.caption(
    "* VRD basados en una dieta de 2000 kcal segun Resolucion 810 de 2021 "
    "del Ministerio de Salud de Colombia. Este analisis es informativo "
    "y no reemplaza asesoria medica o nutricional profesional."
)
