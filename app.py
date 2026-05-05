# =============================================================================
# app.py
# Interfaz web con Streamlit — Analizador de Etiquetas Nutricionales
# Proyecto Final - Curso de Python
#
# Uso:
#   streamlit run app.py
#
# Descripción:
#   Convierte el proyecto de consola en una aplicación web interactiva.
#   Reutiliza analisis.py y reporte.py sin modificarlos.
#   Reemplaza entrada.py (formulario web), visualizacion.py (gráficas
#   nativas de Streamlit) y ocr.py (carga de imagen por el navegador).
#
# Autor: [Tu nombre]
# Fecha: 2025
# =============================================================================

import io
import os
import sys

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import streamlit as st

# ── Agregar carpeta del proyecto al path para importar módulos propios ────────
sys.path.insert(0, os.path.dirname(__file__))

from analisis import analizar_nutrientes
from reporte  import exportar_reporte

# Importación condicional de OCR
try:
    import cv2
    import pytesseract
    from PIL import Image
    from ocr import preprocesar_imagen, extraer_texto, parsear_nutrientes
    OCR_DISPONIBLE = True
except ImportError:
    OCR_DISPONIBLE = False


# =============================================================================
# CONFIGURACIÓN GENERAL DE LA APP
# =============================================================================

st.set_page_config(
    page_title = "Analizador Nutricional",
    page_icon  = "🥗",
    layout     = "wide",
    initial_sidebar_state = "expanded",
)

# ── Estilos CSS personalizados ────────────────────────────────────────────────
st.markdown("""
<style>
    /* Fondo de la barra lateral */
    [data-testid="stSidebar"] { background-color: #1a2535; }
    [data-testid="stSidebar"] * { color: #e6edf3 !important; }

    /* Tarjetas de métricas */
    [data-testid="stMetric"] {
        background: #f8f9fa;
        border-radius: 10px;
        padding: 12px;
        border-left: 4px solid #2c3e50;
    }

    /* Botón primario */
    .stButton > button {
        background-color: #2ecc71;
        color: white;
        border-radius: 8px;
        border: none;
        font-weight: 600;
        padding: 8px 24px;
    }
    .stButton > button:hover { background-color: #27ae60; }

    /* Título principal */
    .titulo-app {
        font-size: 2rem;
        font-weight: 800;
        color: #2c3e50;
        margin-bottom: 0;
    }
    .subtitulo-app {
        font-size: 0.9rem;
        color: #7f8c8d;
        margin-top: 0;
    }

    /* Tarjeta de alerta */
    .alerta-rojo    { background:#fdecea; border-left:4px solid #e74c3c;
                      padding:8px 12px; border-radius:6px; margin:4px 0; }
    .alerta-amarillo{ background:#fef9e7; border-left:4px solid #f39c12;
                      padding:8px 12px; border-radius:6px; margin:4px 0; }
    .alerta-verde   { background:#eafaf1; border-left:4px solid #2ecc71;
                      padding:8px 12px; border-radius:6px; margin:4px 0; }
</style>
""", unsafe_allow_html=True)


# =============================================================================
# BARRA LATERAL — formulario de entrada
# =============================================================================

with st.sidebar:
    st.markdown("## 🥗 Analizador Nutricional")
    st.markdown("*Resolución 810/2021 — Min. Salud Colombia*")
    st.divider()

    # ── Selector de modo ──────────────────────────────────────────────────────
    modo = st.radio(
        "Modo de ingreso",
        options=["✏️  Manual", "📷  Foto (OCR)"],
        help="Manual: digita los valores. Foto: sube una imagen de la etiqueta.",
    )

    st.divider()

    # ── MODO MANUAL ───────────────────────────────────────────────────────────
    if modo == "✏️  Manual":

        st.markdown("### Datos del producto")

        nombre = st.text_input(
            "Nombre del producto",
            placeholder="Ej: Avena Quaker Tradicional",
        )

        porcion = st.number_input(
            "Tamaño de la porción (g o ml)",
            min_value=0.0, max_value=2000.0,
            value=30.0, step=1.0,
        )

        st.markdown("### Información nutricional")

        calorias = st.number_input(
            "Calorías (kcal)", min_value=0.0, max_value=2000.0,
            value=0.0, step=1.0,
        )
        grasas_totales = st.number_input(
            "Grasas totales (g)", min_value=0.0, max_value=200.0,
            value=0.0, step=0.1,
        )
        grasas_saturadas = st.number_input(
            "Grasas saturadas (g)", min_value=0.0, max_value=100.0,
            value=0.0, step=0.1,
        )
        sodio = st.number_input(
            "Sodio (mg)", min_value=0.0, max_value=5000.0,
            value=0.0, step=1.0,
        )
        carbohidratos = st.number_input(
            "Carbohidratos totales (g)", min_value=0.0, max_value=500.0,
            value=0.0, step=0.1,
        )
        azucares = st.number_input(
            "Azúcares (g)", min_value=0.0, max_value=300.0,
            value=0.0, step=0.1,
        )
        proteinas = st.number_input(
            "Proteínas (g)", min_value=0.0, max_value=100.0,
            value=0.0, step=0.1,
        )
        fibra = st.number_input(
            "Fibra dietaria (g)", min_value=0.0, max_value=100.0,
            value=0.0, step=0.1,
        )

        # Botón de análisis
        analizar = st.button("🔍  Analizar producto", use_container_width=True)

        # Empaquetar datos del formulario
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

    # ── MODO OCR ──────────────────────────────────────────────────────────────
    else:
        st.markdown("### Subir foto de etiqueta")

        if not OCR_DISPONIBLE:
            st.warning(
                "⚠️ OCR no disponible.\n\n"
                "Instale: `pytesseract`, `pillow`, `opencv-python`\n"
                "y el motor `tesseract-ocr` en su sistema."
            )
            analizar = False
            datos_formulario = {}

        else:
            st.info(
                "📸 **Consejos para mejor lectura:**\n"
                "- Foto frontal, sin inclinación\n"
                "- Buena iluminación, sin reflejos\n"
                "- Imagen nítida y de alta resolución"
            )

            archivo = st.file_uploader(
                "Seleccione la imagen",
                type=["jpg", "jpeg", "png", "bmp", "webp"],
            )

            nombre_ocr = st.text_input(
                "Nombre del producto (escriba manualmente)",
                placeholder="Ej: Cereal de Maíz",
            )

            analizar = st.button("🔍  Escanear y analizar", use_container_width=True)
            datos_formulario = {"nombre_producto": nombre_ocr or "Producto escaneado"}

            # Procesar imagen si se subió
            if archivo is not None:
                # Guardar imagen temporalmente para que OpenCV pueda leerla
                ruta_temp = f"/tmp/{archivo.name}"
                with open(ruta_temp, "wb") as f:
                    f.write(archivo.read())
                datos_formulario["_ruta_imagen"] = ruta_temp

                # Mostrar previsualización de la imagen subida
                st.image(archivo, caption="Imagen cargada", use_container_width=True)


# =============================================================================
# ÁREA PRINCIPAL — resultados
# =============================================================================

# ── Encabezado principal ──────────────────────────────────────────────────────
st.markdown('<p class="titulo-app">🥗 Analizador de Etiquetas Nutricionales</p>',
            unsafe_allow_html=True)
st.markdown('<p class="subtitulo-app">Evaluación basada en Resolución 810/2021 · Min. Salud Colombia · Dieta 2000 kcal</p>',
            unsafe_allow_html=True)
st.divider()


# ── Pantalla de inicio (cuando aún no se ha analizado nada) ──────────────────
if not analizar:
    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("#### ✏️  Ingreso manual")
        st.markdown(
            "Digita los valores directamente desde la etiqueta "
            "del producto. Funciona sin ninguna dependencia adicional."
        )

    with col2:
        st.markdown("#### 📷  Escaneo OCR")
        st.markdown(
            "Sube una foto de la etiqueta y el programa extrae "
            "los nutrientes automáticamente usando pytesseract."
        )

    with col3:
        st.markdown("#### 📄  Reporte PDF")
        st.markdown(
            "Descarga un reporte profesional con tabla nutricional, "
            "semáforo y gráfica de barras incluida."
        )

    st.info("👈  Complete el formulario en la barra lateral y presione **Analizar producto**.")
    st.stop()


# =============================================================================
# PROCESAMIENTO — obtener y analizar datos
# =============================================================================

resultado = None

with st.spinner("Analizando nutrientes..."):

    # ── Modo manual ───────────────────────────────────────────────────────────
    if modo == "✏️  Manual":

        # Validar que al menos los campos principales tengan valores
        campos_principales = ["calorias", "grasas_totales", "sodio",
                              "carbohidratos", "proteinas"]
        campos_vacios = [
            c for c in campos_principales
            if datos_formulario.get(c, 0) == 0
        ]

        if len(campos_vacios) >= 4:
            st.error(
                "⚠️ Por favor ingrese al menos los valores principales: "
                "calorías, grasas totales, sodio, carbohidratos y proteínas."
            )
            st.stop()

        resultado = analizar_nutrientes(datos_formulario)

    # ── Modo OCR ──────────────────────────────────────────────────────────────
    else:
        ruta_imagen = datos_formulario.get("_ruta_imagen")

        if not ruta_imagen:
            st.error("⚠️ Por favor suba una imagen de la etiqueta nutricional.")
            st.stop()

        try:
            # Pipeline OCR reutilizando funciones de ocr.py
            imagen_procesada = preprocesar_imagen(ruta_imagen)
            texto_crudo      = extraer_texto(imagen_procesada)
            datos_ocr        = parsear_nutrientes(texto_crudo)
            datos_ocr["nombre_producto"] = datos_formulario["nombre_producto"]

            # Mostrar texto crudo detectado en un expander
            with st.expander("🔍 Ver texto crudo detectado por el OCR"):
                st.code(texto_crudo, language=None)

            # Confianza del OCR
            total_campos    = 8
            campos_ok       = len([k for k in datos_ocr if k != "nombre_producto"])
            confianza       = round((campos_ok / total_campos) * 100)

            st.info(
                f"📊 Campos detectados por OCR: **{campos_ok} / {total_campos}** "
                f"(confianza: {confianza}%)"
            )

            if confianza < 50:
                st.warning(
                    "⚠️ La confianza del OCR es baja. "
                    "Verifique que la imagen sea nítida y bien iluminada."
                )

            resultado = analizar_nutrientes(datos_ocr)

        except Exception as e:
            st.error(f"❌ Error durante el escaneo OCR: {e}")
            st.stop()


# =============================================================================
# VISUALIZACIÓN DE RESULTADOS
# =============================================================================

if resultado is None:
    st.stop()

nombre_producto = resultado["nombre_producto"]
porcentajes     = resultado["porcentajes"]
semaforo        = resultado["semaforo"]
puntaje         = resultado["puntaje"]
alertas         = resultado["alertas"]
recomendacion   = resultado["recomendacion"]

# ── Encabezado del resultado ──────────────────────────────────────────────────
st.markdown(f"## 📦 {nombre_producto}")

# ── Métricas rápidas en la parte superior ─────────────────────────────────────
col_p, col_r, col_c, col_s = st.columns(4)

with col_p:
    # Color del delta según puntaje
    delta_color = "normal" if puntaje >= 50 else "inverse"
    st.metric(
        label  = "🏅 Puntaje de salud",
        value  = f"{puntaje:.1f} / 100",
        delta  = "Saludable" if puntaje >= 75 else "Moderado" if puntaje >= 50 else "Riesgo",
        delta_color = delta_color,
    )

with col_c:
    cal = resultado["datos_originales"].get("calorias", 0)
    pct_cal = porcentajes.get("calorias", 0)
    st.metric("🔥 Calorías", f"{cal:.0f} kcal", f"{pct_cal:.1f}% VRD")

with col_r:
    sod = resultado["datos_originales"].get("sodio", 0)
    pct_sod = porcentajes.get("sodio", 0)
    st.metric("🧂 Sodio", f"{sod:.0f} mg", f"{pct_sod:.1f}% VRD")

with col_s:
    azu = resultado["datos_originales"].get("azucares", 0)
    pct_azu = porcentajes.get("azucares", 0)
    st.metric("🍬 Azúcares", f"{azu:.1f} g", f"{pct_azu:.1f}% VRD")

st.divider()

# ── Columnas: tabla semáforo | gráfica de barras ──────────────────────────────
col_tabla, col_grafica = st.columns([1, 1.4], gap="large")

# ── Tabla de nutrientes ───────────────────────────────────────────────────────
with col_tabla:
    st.markdown("### 🚦 Semáforo nutricional")

    ETIQUETAS = {
        "calorias":         ("Calorías",          "kcal"),
        "grasas_totales":   ("Grasas totales",    "g"),
        "grasas_saturadas": ("Grasas saturadas",  "g"),
        "sodio":            ("Sodio",             "mg"),
        "carbohidratos":    ("Carbohidratos",     "g"),
        "azucares":         ("Azúcares",          "g"),
        "proteinas":        ("Proteínas",         "g"),
        "fibra":            ("Fibra",             "g"),
    }

    COLOR_HEX = {
        "VERDE":    "#2ecc71",
        "AMARILLO": "#f39c12",
        "ROJO":     "#e74c3c",
    }

    # Construir filas de la tabla como HTML para poder colorear
    filas_html = ""
    for clave, (etiqueta, unidad) in ETIQUETAS.items():
        if clave not in porcentajes:
            continue

        pct      = porcentajes[clave]
        valor    = resultado["datos_originales"].get(clave, 0)
        info_sem = semaforo.get(clave, {})
        color    = COLOR_HEX.get(info_sem.get("color", "AMARILLO"), "#f39c12")
        emoji    = info_sem.get("emoji", "⚪")
        nivel    = info_sem.get("etiqueta", "—")
        valor_str = f"{valor:.1f}" if isinstance(valor, float) else str(valor)

        filas_html += f"""
        <tr>
            <td style='padding:6px 8px; font-size:0.85rem;'>{etiqueta}</td>
            <td style='padding:6px 8px; text-align:center; font-size:0.85rem;'>
                {valor_str} {unidad}</td>
            <td style='padding:6px 8px; text-align:center; font-size:0.85rem;'>
                {pct:.1f}%</td>
            <td style='padding:6px 8px; text-align:center;'>
                <span style='background:{color}; color:white; padding:2px 10px;
                border-radius:12px; font-size:0.75rem; font-weight:700;'>
                {emoji} {nivel}</span>
            </td>
        </tr>
        """

    tabla_html = f"""
    <table style='width:100%; border-collapse:collapse;'>
        <thead>
            <tr style='background:#2c3e50; color:white;'>
                <th style='padding:8px; text-align:left; font-size:0.8rem;'>
                    Nutriente</th>
                <th style='padding:8px; text-align:center; font-size:0.8rem;'>
                    Valor</th>
                <th style='padding:8px; text-align:center; font-size:0.8rem;'>
                    % VRD</th>
                <th style='padding:8px; text-align:center; font-size:0.8rem;'>
                    Nivel</th>
            </tr>
        </thead>
        <tbody>{filas_html}</tbody>
    </table>
    """
    st.markdown(tabla_html, unsafe_allow_html=True)

# ── Gráfica de barras ─────────────────────────────────────────────────────────
with col_grafica:
    st.markdown("### 📊 Porcentajes VRD")

    etiquetas_graf = []
    valores_graf   = []
    colores_graf   = []

    COLOR_MPL = {
        "VERDE":    "#2ecc71",
        "AMARILLO": "#f39c12",
        "ROJO":     "#e74c3c",
    }

    for clave, (etiqueta, _) in ETIQUETAS.items():
        if clave in porcentajes:
            etiquetas_graf.append(etiqueta)
            valores_graf.append(porcentajes[clave])
            color_sem = semaforo.get(clave, {}).get("color", "AMARILLO")
            colores_graf.append(COLOR_MPL.get(color_sem, "#f39c12"))

    fig, ax = plt.subplots(figsize=(7, 4.5))
    fig.patch.set_facecolor("#f8f9fa")
    ax.set_facecolor("#ffffff")

    posiciones = np.arange(len(etiquetas_graf))
    barras = ax.barh(posiciones, valores_graf, color=colores_graf,
                     height=0.6, edgecolor="white", linewidth=1)

    # Línea de referencia 100% VRD
    ax.axvline(x=100, color="#c0392b", linestyle="--",
               linewidth=1.5, alpha=0.7, label="100% VRD")

    # Valores al final de cada barra
    for barra, valor in zip(barras, valores_graf):
        ax.text(valor + 1, barra.get_y() + barra.get_height() / 2,
                f"{valor:.1f}%", va="center", ha="left",
                fontsize=8, color="#2c3e50", fontweight="bold")

    ax.set_yticks(posiciones)
    ax.set_yticklabels(etiquetas_graf, fontsize=9)
    ax.set_xlabel("% del Valor de Referencia Diario", fontsize=9)
    valor_max = max(valores_graf) if valores_graf else 100
    ax.set_xlim(0, max(valor_max * 1.3, 115))
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.xaxis.grid(True, linestyle="--", alpha=0.3)
    ax.set_axisbelow(True)

    # Leyenda
    p1 = mpatches.Patch(color="#2ecc71", label="Bajo / Adecuado")
    p2 = mpatches.Patch(color="#f39c12", label="Medio / Bajo")
    p3 = mpatches.Patch(color="#e74c3c", label="Alto / Muy bajo")
    ax.legend(handles=[p1, p2, p3], loc="lower right",
              fontsize=8, framealpha=0.9)

    plt.tight_layout()
    st.pyplot(fig, use_container_width=True)
    plt.close(fig)

st.divider()

# ── Puntaje con barra de progreso y recomendación ─────────────────────────────
st.markdown("### 🏅 Puntaje de salud general")

color_barra = (
    "#2ecc71" if puntaje >= 75 else
    "#f39c12" if puntaje >= 50 else
    "#e74c3c"
)

barra_html = f"""
<div style='background:#e0e0e0; border-radius:20px; height:28px;
            width:100%; margin-bottom:8px;'>
  <div style='background:{color_barra}; width:{puntaje}%; height:28px;
              border-radius:20px; display:flex; align-items:center;
              padding-left:12px;'>
    <span style='color:white; font-weight:700; font-size:0.9rem;'>
      {puntaje:.1f} / 100
    </span>
  </div>
</div>
"""
st.markdown(barra_html, unsafe_allow_html=True)
st.markdown(f"**{recomendacion}**")

st.divider()

# ── Alertas nutricionales ─────────────────────────────────────────────────────
st.markdown("### 📋 Alertas nutricionales")

for alerta in alertas:
    alerta_lower = alerta.lower()
    if "alto" in alerta_lower or "evitar" in alerta_lower:
        clase = "alerta-rojo"
    elif "bajo" in alerta_lower or "posible" in alerta_lower:
        clase = "alerta-amarillo"
    else:
        clase = "alerta-verde"

    st.markdown(
        f'<div class="{clase}">{alerta}</div>',
        unsafe_allow_html=True,
    )

st.divider()

# ── Exportar PDF ──────────────────────────────────────────────────────────────
st.markdown("### 📄 Exportar reporte")

# Guardar la gráfica como PNG para incrustarla en el PDF
ruta_grafica_temp = "/tmp/analisis_nutricional.png"
fig2, ax2 = plt.subplots(figsize=(10, 5))
fig2.patch.set_facecolor("#f8f9fa")
ax2.set_facecolor("#ffffff")
ax2.barh(posiciones, valores_graf, color=colores_graf,
         height=0.6, edgecolor="white")
ax2.axvline(x=100, color="#c0392b", linestyle="--", linewidth=1.5, alpha=0.7)
for barra, valor in zip(ax2.patches, valores_graf):
    ax2.text(valor + 1, barra.get_y() + barra.get_height() / 2,
             f"{valor:.1f}%", va="center", ha="left", fontsize=8)
ax2.set_yticks(posiciones)
ax2.set_yticklabels(etiquetas_graf, fontsize=9)
ax2.set_xlabel("% VRD", fontsize=9)
ax2.set_xlim(0, max(max(valores_graf) * 1.3 if valores_graf else 100, 115))
ax2.spines["top"].set_visible(False)
ax2.spines["right"].set_visible(False)
plt.tight_layout()
plt.savefig(ruta_grafica_temp, dpi=150, bbox_inches="tight",
            facecolor="#f8f9fa")
plt.close(fig2)

# Generar PDF en memoria
ruta_pdf_temp = f"/tmp/reporte_{nombre_producto[:20].replace(' ','_')}.pdf"

# Cambiar directorio de trabajo para que reporte.py encuentre la gráfica
os.chdir("/tmp")

try:
    exportar_reporte(resultado, ruta_pdf_temp)

    with open(ruta_pdf_temp, "rb") as f:
        pdf_bytes = f.read()

    st.download_button(
        label     = "⬇️  Descargar reporte PDF",
        data      = pdf_bytes,
        file_name = f"reporte_{nombre_producto[:30].replace(' ','_')}.pdf",
        mime      = "application/pdf",
        use_container_width = True,
    )
except Exception as e:
    st.error(f"No se pudo generar el PDF: {e}")

# ── Nota legal ────────────────────────────────────────────────────────────────
st.caption(
    "* VRD basados en una dieta de 2000 kcal según Resolución 810 de 2021 "
    "del Ministerio de Salud de Colombia. Este análisis es informativo "
    "y no reemplaza asesoría médica o nutricional profesional."
)
