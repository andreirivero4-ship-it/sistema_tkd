import streamlit as st
import psycopg2
import pandas as pd
import re
import io
import os
from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

# --- 1. CONFIGURACIÓN DE CONEXIÓN ---
def conectar_db():
    try:
        cfg = st.secrets["database"]
        conn = psycopg2.connect(
            host=cfg["host"],
            database=cfg["database"],
            user=cfg["user"],
            password=cfg["password"],
            port=cfg["port"],
            sslmode='require'
        )
        return conn
    except Exception as e:
        st.error(f"Error de conexión: {e}")
        return None

# --- MIGRACIÓN AUTOMÁTICA DE COLUMNAS NUEVAS ---
def migrar_columnas():
    """Agrega las columnas nuevas si no existen en la tabla."""
    db = conectar_db()
    if db:
        try:
            cursor = db.cursor()
            cursor.execute("""
                ALTER TABLE alumnos_tkd 
                ADD COLUMN IF NOT EXISTS foto BYTEA DEFAULT NULL,
                ADD COLUMN IF NOT EXISTS modalidad VARCHAR(10) DEFAULT 'FORMAS'
            """)
            db.commit()
            db.close()
        except Exception as e:
            st.warning(f"Aviso migración: {e}")

# --- 2. FUNCIONES DE LÓGICA ---
def validar_y_formatear(key):
    if key in st.session_state:
        valor = st.session_state[key]
        st.session_state[key] = re.sub(r'[^A-ZÑÁÉÍÓÚ\s]', '', valor.upper())

def registrar_competidor():
    comp      = st.session_state.get('comp', '').strip()
    esc       = st.session_state.get('esc', '').strip()
    prof      = st.session_state.get('prof', '').strip()
    edad      = st.session_state.get('edad_val', 3)
    cinta     = st.session_state.get('cinta_val', 'BLANCA')
    modalidad = st.session_state.get('modalidad_val', 'FORMAS')
    foto_file = st.session_state.get('foto_upload', None)
    acepta    = st.session_state.get('acepta_riesgos', False)

    formas  = modalidad == 'FORMAS'
    combate = modalidad == 'COMBATE'

    foto_bytes = None
    if foto_file is not None:
        foto_bytes = foto_file.read()

    if not acepta:
        st.error('⚠️ Debes aceptar la declaración de riesgos para registrar al competidor.')
        return

    if comp and esc and prof:
        db = conectar_db()
        if db:
            try:
                cursor = db.cursor()
                check_query = "SELECT id FROM alumnos_tkd WHERE nombre_completo = %s AND escuela = %s AND profesor = %s"
                cursor.execute(check_query, (comp, esc, prof))
                if cursor.fetchone():
                    st.error(f"⚠️ El competidor '{comp}' ya existe en esta escuela.")
                else:
                    query = """INSERT INTO alumnos_tkd
                               (nombre_completo, escuela, profesor, edad, cinta, formas, combate, modalidad, foto)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"""
                    cursor.execute(query, (comp, esc, prof, edad, cinta, formas, combate, modalidad, foto_bytes))
                    db.commit()
                    for k in ['comp', 'esc', 'prof']:
                        st.session_state[k] = ""
                    st.session_state['acepta_riesgos'] = False
                    st.toast(f"✅ REGISTRADO: {comp}")
                db.close()
            except Exception as e:
                st.error(f"Error: {e}")
    else:
        st.warning('⚠️ Completa los campos obligatorios.')

def actualizar_competidor(id_reg, nombre, escuela, profesor, edad, cinta, modalidad, foto_bytes=None):
    formas  = modalidad == 'FORMAS'
    combate = modalidad == 'COMBATE'
    db = conectar_db()
    if db:
        try:
            cursor = db.cursor()
            if foto_bytes is not None:
                query = """UPDATE alumnos_tkd SET nombre_completo=%s, escuela=%s, profesor=%s,
                           edad=%s, cinta=%s, formas=%s, combate=%s, modalidad=%s, foto=%s
                           WHERE id=%s"""
                cursor.execute(query, (nombre.upper(), escuela.upper(), profesor.upper(),
                                       edad, cinta, formas, combate, modalidad, foto_bytes, id_reg))
            else:
                query = """UPDATE alumnos_tkd SET nombre_completo=%s, escuela=%s, profesor=%s,
                           edad=%s, cinta=%s, formas=%s, combate=%s, modalidad=%s
                           WHERE id=%s"""
                cursor.execute(query, (nombre.upper(), escuela.upper(), profesor.upper(),
                                       edad, cinta, formas, combate, modalidad, id_reg))
            db.commit()
            db.close()
            st.success(f"🔄 Datos de '{nombre}' actualizados correctamente.")
            st.rerun()
        except Exception as e:
            st.error(f"Error al actualizar: {e}")

def eliminar_registro(id_registro, nombre):
    db = conectar_db()
    if db:
        try:
            cursor = db.cursor()
            cursor.execute("DELETE FROM alumnos_tkd WHERE id = %s", (id_registro,))
            db.commit()
            db.close()
            st.success(f"🗑️ Registro eliminado correctamente.")
            st.rerun()
        except Exception as e:
            st.error(f"Error al eliminar: {e}")

# --- 3. GENERADOR DE PDF ---
def dibujar_palomita(c, x_box, y_box):
    c.setStrokeColor(colors.black)
    c.setLineWidth(3)
    c.line(x_box + 0.08 * inch, y_box + 0.18 * inch, x_box + 0.18 * inch, y_box + 0.08 * inch)
    c.line(x_box + 0.18 * inch, y_box + 0.08 * inch, x_box + 0.35 * inch, y_box + 0.32 * inch)

def generar_pdf_graficas(alumno_up, alumno_down=None):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    ruta_banner = 'banner_torneo.png'

    def dibujar_tarjeta(y_offset, datos):
        if not datos:
            return
        c.setLineWidth(2)
        c.setStrokeColor(colors.black)
        c.rect(0.5 * inch, y_offset, 7.5 * inch, 5 * inch)

        # Banner
        if os.path.exists(ruta_banner):
            c.drawImage(ruta_banner, 0.5 * inch, y_offset + 3.8 * inch,
                        width=7.5 * inch, height=1.2 * inch, mask='auto')

        # Foto del competidor (si existe)
        foto_raw = datos.get('foto')
        if foto_raw:
            try:
                foto_stream = io.BytesIO(bytes(foto_raw))
                img = Image.open(foto_stream).convert("RGB")
                img_resized = img.resize((int(1.1 * 72), int(1.3 * 72)))
                img_buf = io.BytesIO()
                img_resized.save(img_buf, format='JPEG')
                img_buf.seek(0)
                from reportlab.lib.utils import ImageReader
                c.drawImage(ImageReader(img_buf),
                            6.3 * inch, y_offset + 2.05 * inch,
                            width=1.1 * inch, height=1.3 * inch)
                c.setStrokeColor(colors.grey)
                c.setLineWidth(1)
                c.rect(6.3 * inch, y_offset + 2.05 * inch, 1.1 * inch, 1.3 * inch)
            except Exception:
                pass  # Si falla la foto, continúa sin ella

        # Campos de texto
        c.setFillColor(colors.black)
        y_text = y_offset + 3.2 * inch
        for etiqueta, valor in [
            ("COMPETIDOR:", datos['nombre_completo']),
            ("ESCUELA:",    datos['escuela']),
            ("PROFESOR:",   datos['profesor'])
        ]:
            c.setFont("Helvetica-Bold", 14)
            c.drawString(0.8 * inch, y_text, etiqueta)
            c.setFont("Helvetica", 14)
            c.drawString(2.3 * inch, y_text, str(valor))
            c.line(2.2 * inch, y_text - 4, 5.9 * inch, y_text - 4)
            y_text -= 0.6 * inch

        # ── Fila: EDAD / CINTA / MODALIDAD ──────────────────────────────────
        c.setFont("Helvetica-Bold", 13)
        c.drawString(0.8 * inch,  y_offset + 1.55 * inch, "EDAD:")
        c.setFont("Helvetica", 13)
        c.drawString(1.65 * inch, y_offset + 1.55 * inch, str(datos['edad']))

        c.setFont("Helvetica-Bold", 13)
        c.drawString(3.0 * inch,  y_offset + 1.55 * inch, "CINTA:")
        c.setFont("Helvetica", 13)
        c.drawString(3.9 * inch,  y_offset + 1.55 * inch, datos['cinta'])

        c.setFont("Helvetica-Bold", 13)
        c.drawString(5.4 * inch,  y_offset + 1.55 * inch, "MODALIDAD:")
        c.setFont("Helvetica-Bold", 13)
        c.setFillColor(colors.HexColor("#B22222"))
        c.drawString(6.65 * inch, y_offset + 1.55 * inch, str(datos.get('modalidad', '')))
        c.setFillColor(colors.black)

        # ── Línea separadora ─────────────────────────────────────────────────
        c.setStrokeColor(colors.HexColor("#AAAAAA"))
        c.setLineWidth(0.5)
        c.line(0.65 * inch, y_offset + 1.3 * inch, 7.85 * inch, y_offset + 1.3 * inch)

        # ── Bloque declaración de riesgos ────────────────────────────────────
        # Fondo gris muy suave
        c.setFillColor(colors.HexColor("#F5F5F5"))
        c.setStrokeColor(colors.HexColor("#CCCCCC"))
        c.setLineWidth(0.5)
        c.roundRect(0.65 * inch, y_offset + 0.18 * inch, 7.2 * inch, 1.05 * inch, 4, fill=1, stroke=1)

        # Título de la declaración
        c.setFillColor(colors.HexColor("#1a1a2e"))
        c.setFont("Helvetica-Bold", 8)
        c.drawString(0.85 * inch, y_offset + 1.08 * inch, "DECLARACIONES Y ACEPTACIÓN DE RIESGOS")

        # Texto de la declaración — dividido en líneas para que quepa
        nombre_comp = datos['nombre_completo']
        declaracion_lineas = [
            f"Yo, en mi calidad de padre, madre o tutor del competidor {nombre_comp}, declaro estar",
            "consciente de que el taekwondo es un deporte de contacto, por lo que autorizo la participación",
            "de mi hijo(a) en el torneo, después de haber leído y autorizado la declaración y aceptación de",
            'riesgo en el registro al "4to Torneo Regional la Perla del Sur".',
        ]
        c.setFont("Helvetica", 7.5)
        c.setFillColor(colors.HexColor("#333333"))
        y_decl = y_offset + 0.88 * inch
        for linea in declaracion_lineas:
            c.drawString(0.85 * inch, y_decl, linea)
            y_decl -= 0.165 * inch

    dibujar_tarjeta(5.5 * inch, alumno_up)
    if alumno_down:
        dibujar_tarjeta(0.25 * inch, alumno_down)
    c.save()
    return buffer.getvalue()

# --- 4. INTERFAZ ---
migrar_columnas()  # Asegura que las columnas existan

st.set_page_config(page_title="Sistema TKD", layout="wide")
st.title("🥋 REGISTRO AL 4TO TORNEO REGIONAL LA PERLA DEL SUR")

MODALIDADES = ["FORMAS", "COMBATE"]
CINTAS      = ["BLANCA", "NARANJA", "AMARILLA", "VERDE", "AZUL", "ROJA", "NEGRA"]

tab1, tab2 = st.tabs(["📝 REGISTRO", "📋 PANEL DE CONTROL"])

# ===================== TAB 1: REGISTRO =====================
with tab1:
    col1, col2 = st.columns(2)

    with col1:
        st.text_input("NOMBRE COMPLETO *", key="comp", on_change=validar_y_formatear, args=("comp",))
        st.text_input("ESCUELA *",          key="esc",  on_change=validar_y_formatear, args=("esc",))
        st.text_input("PROFESOR *",         key="prof", on_change=validar_y_formatear, args=("prof",))
        st.number_input("EDAD", min_value=3, max_value=99, key="edad_val")
        st.selectbox("CINTA", CINTAS, key="cinta_val")
        st.selectbox("MODALIDAD", MODALIDADES, key="modalidad_val")

    with col2:
        st.markdown("**FOTO DEL COMPETIDOR**")
        foto_upload = st.file_uploader(
            "Sube una imagen (JPG / PNG)",
            type=["jpg", "jpeg", "png"],
            key="foto_upload",
            label_visibility="collapsed"
        )
        if foto_upload:
            st.image(foto_upload, caption="Vista previa", width=160)

    st.divider()
    st.markdown("""
    <div style='background:linear-gradient(135deg,#1a1a2e 0%,#16213e 100%);
                border:1px solid #c9a84c;border-radius:10px;overflow:hidden;margin-top:8px;'>
        <div style='background:linear-gradient(90deg,#c9a84c,#f0d080,#c9a84c);
                    padding:10px 20px;text-align:center;'>
            <span style='font-size:13px;font-weight:800;color:#1a1a2e;letter-spacing:2px;'>
                &#9878;&nbsp;&nbsp;DECLARACIÓN Y ACEPTACIÓN DE RIESGOS&nbsp;&nbsp;&#9878;
            </span>
        </div>
        <div style='padding:18px 24px;color:#e8e8e8;font-size:13.5px;line-height:1.75;'>
            <p style='margin:0 0 10px 0;text-align:justify;'>
                Yo, en mi calidad de <b style='color:#f0d080;'>padre, madre o tutor legal</b> del competidor
                registrado, declaro haber sido informado(a) de que el
                <b style='color:#f0d080;'>Taekwondo es una disciplina de contacto físico</b>,
                que conlleva riesgos inherentes a su práctica, incluyendo contusiones,
                lesiones musculares u otras afecciones físicas.
            </p>
            <p style='margin:0 0 10px 0;text-align:justify;'>
                Mediante el presente acto, <b style='color:#f0d080;'>autorizo expresamente</b> la
                participación de mi hijo(a) en todas las actividades del torneo, reconociendo que el
                Comité Organizador adoptará las medidas de seguridad pertinentes; sin embargo,
                <b style='color:#f0d080;'>asumo plena responsabilidad</b> sobre los riesgos propios
                de la actividad deportiva.
            </p>
            <p style='margin:0;text-align:justify;'>
                En consecuencia, <b style='color:#f0d080;'>libero al Comité Organizador, árbitros,
                entrenadores y personal del evento</b> de toda responsabilidad civil por accidentes
                o lesiones que pudieran ocurrir durante el desarrollo del torneo, siempre que
                no medie negligencia grave o dolo por parte de los organizadores.
            </p>
        </div>
        <div style='background:rgba(201,168,76,0.12);border-top:1px solid rgba(201,168,76,0.3);
                    padding:8px 24px;font-size:11px;color:#aaa;text-align:center;'>
            Este documento tiene validez legal. Léalo detenidamente antes de aceptar.
        </div>
    </div>
    """, unsafe_allow_html=True)
    st.checkbox(
        '✅  He leído íntegramente la declaración anterior y ACEPTO sus términos. '
        'Autorizo la participación de mi hijo(a) en el torneo.',
        key='acepta_riesgos'
    )
    acepta_actual = st.session_state.get('acepta_riesgos', False)
    st.button(
        '💾 GUARDAR REGISTRO',
        on_click=registrar_competidor,
        use_container_width=True,
        disabled=not acepta_actual
    )

# ===================== TAB 2: PANEL DE CONTROL =====================
with tab2:
    st.subheader("🔍 Filtros y Búsqueda")
    f1, f2, f3, f4, f5 = st.columns(5)
    bus_nom = f1.text_input("Nombre")
    bus_esc = f2.text_input("Escuela")
    bus_pro = f3.text_input("Profesor")
    bus_eda = f4.text_input("Edad")
    bus_cin = f5.selectbox("Cinta", ["TODAS"] + CINTAS)

    db = conectar_db()
    if db:
        query  = "SELECT * FROM alumnos_tkd WHERE 1=1"
        params = []
        if bus_nom: query += " AND nombre_completo LIKE %s"; params.append(f'%{bus_nom.upper()}%')
        if bus_esc: query += " AND escuela LIKE %s";         params.append(f'%{bus_esc.upper()}%')
        if bus_pro: query += " AND profesor LIKE %s";        params.append(f'%{bus_pro.upper()}%')
        if bus_eda: query += " AND edad = %s";               params.append(int(bus_eda))
        if bus_cin != "TODAS": query += " AND cinta = %s";   params.append(bus_cin)

        df = pd.read_sql(query, db, params=params)
        db.close()

        if not df.empty:
            with st.expander("📥 EXPORTAR DATOS PARA MIGRACIÓN"):
                col_exp1, col_exp2 = st.columns(2)
                
                # Opción 1: CSV (Para Excel o Google Sheets)
                csv = df.to_csv(index=False).encode('utf-8')
                col_exp1.download_button(
                    label="Descargar tabla en CSV",
                    data=csv,
                    file_name='respaldo_competidores_tkd.csv',
                    mime='text/csv',
                    use_container_width=True
                )
            # Mostrar tabla sin columnas binarias/id
            cols_ocultar = ('id', 'foto', 'formas', 'combate', 'complexion')
            cols_mostrar = [c for c in df.columns if c not in cols_ocultar]
            st.dataframe(df[cols_mostrar], use_container_width=True, hide_index=True)
            st.divider()

            col_acc1, col_acc2 = st.columns(2)

            # ---------- IMPRESIÓN DE GRÁFICAS ----------
            with col_acc1:
                st.subheader("🖨️ Impresión de Gráficas")
                sel_up = st.selectbox("Posición Superior", df['nombre_completo'], key="s1")
                sel_dw = st.selectbox("Posición Inferior", ["VACÍO"] + list(df['nombre_completo']), key="s2")
                al_up  = df[df['nombre_completo'] == sel_up].iloc[0].to_dict()
                al_dw  = df[df['nombre_completo'] == sel_dw].iloc[0].to_dict() if sel_dw != "VACÍO" else None
                pdf    = generar_pdf_graficas(al_up, al_dw)
                st.download_button("🚀 DESCARGAR PDF", data=pdf,
                                   file_name="graficas.pdf", use_container_width=True)

            # ---------- ADMINISTRACIÓN ----------
            with col_acc2:
                st.subheader("⚙️ Administración")

                # EDITAR
                with st.expander("✏️ EDITAR DATOS DEL COMPETIDOR"):
                    edit_sel = st.selectbox("Alumno a editar:", df['nombre_completo'], key="edit_sel")
                    d = df[df['nombre_completo'] == edit_sel].iloc[0]

                    e_nom = st.text_input("Nuevo Nombre",   value=d['nombre_completo'])
                    e_esc = st.text_input("Nueva Escuela",  value=d['escuela'])
                    e_pro = st.text_input("Nuevo Profesor", value=d['profesor'])

                    col_e1, col_e2 = st.columns(2)
                    e_eda = col_e1.number_input("Nueva Edad", value=int(d['edad']), min_value=3)
                    e_cin = col_e2.selectbox(
                        "Nueva Cinta", CINTAS,
                        index=CINTAS.index(d['cinta']) if d['cinta'] in CINTAS else 0
                    )

                    modalidad_actual = d['modalidad'] if 'modalidad' in d and d['modalidad'] in MODALIDADES else 'FORMAS'
                    e_mod = st.selectbox(
                        'Modalidad', MODALIDADES,
                        index=MODALIDADES.index(modalidad_actual)
                    )

                    # Foto actual
                    if d.get('foto') is not None:
                        st.markdown('**Foto actual:**')
                        st.image(bytes(d['foto']), width=120)

                    nueva_foto = st.file_uploader(
                        'Cambiar foto (opcional)', type=['jpg', 'jpeg', 'png'],
                        key='edit_foto'
                    )
                    nueva_foto_bytes = nueva_foto.read() if nueva_foto else None

                    if st.button('💾 ACTUALIZAR DATOS', use_container_width=True):
                        actualizar_competidor(
                            int(d['id']), e_nom, e_esc, e_pro,
                            e_eda, e_cin, e_mod, nueva_foto_bytes
                        )

                # ELIMINAR
                with st.popover("🗑️ ELIMINAR REGISTRO", use_container_width=True):
                    elim_sel = st.selectbox("Seleccionar para eliminar:", df['nombre_completo'], key="del")
                    id_elim  = df[df['nombre_completo'] == elim_sel].iloc[0]['id']
                    st.warning(f"¿Eliminar a {elim_sel}?")
                    if st.button("SÍ, ELIMINAR AHORA", type="primary", use_container_width=True):
                        eliminar_registro(int(id_elim), elim_sel)

                if st.button("🔄 ACTUALIZAR LISTA", use_container_width=True):
                    st.rerun()
        else:
            st.info("No hay registros.")
            if st.button("🔄 RECARGAR"):
                st.rerun()
