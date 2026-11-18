import threading
from datetime import date, datetime, time as dtime

import flet as ft

import db
import google_auth

# ---------- Colores (texto blanco sobre estos colores: contraste >= 4,5:1) ----------
AZUL = "#0B3D91"
VERDE = "#1B5E20"
ROJO = "#B71C1C"
NARANJA = "#9A3F00"
MORADO = "#6A1B9A"
TEAL = "#00695C"
GRIS = "#37474F"
AMBAR = "#8A5A00"  # estrellas
TEXTO = "#1A1A1A"
FONDO = "#F4F6FA"
BLANCO = "#FFFFFF"
BORDE = "#90A4AE"

COLOR_ESTADO = {"Solicitada": NARANJA, "Asignada": AZUL, "En curso": VERDE,
                "Finalizada": GRIS, "Cancelada": ROJO}
ICONO_ESTADO = {"Solicitada": ft.Icons.SCHEDULE, "Asignada": ft.Icons.PERSON_ADD,
                "En curso": ft.Icons.DIRECTIONS_WALK, "Finalizada": ft.Icons.CHECK_CIRCLE,
                "Cancelada": ft.Icons.CANCEL}
ICONO_TIPO = {"Cita médica": ft.Icons.MEDICAL_SERVICES, "Trámite o diligencia": ft.Icons.DESCRIPTION,
              "Compras": ft.Icons.SHOPPING_CART, "Visita o paseo": ft.Icons.PEOPLE,
              "Otro": ft.Icons.MORE_HORIZ}
TIPOS = db.TIPOS_SERVICIO
ROLES = {"adulto_mayor": "Adulto mayor", "familiar": "Familiar / cuidador", "acompanante": "Acompañante"}

NIVELES = [1.0, 1.25, 1.5]  # tamaños de letra: normal, grande, muy grande
NOMBRES_NIVEL = ["Normal", "Grande", "Muy grande"]
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]
MSG_CORREO = db.MSG_CORREO
HORAS = [f"{h:02d}:{m:02d}" for h in range(6, 22) for m in (0, 30)]  # 6:00 a. m. a 9:30 p. m.
ROLES_NOMBRE = {**ROLES, "administrador": "Administrador (asignador)", "superadmin": "Super administrador"}
# CAMBIE este correo por el del proyecto antes de usar la app con personas reales (aparece en los términos)
CONTACTO_DATOS = "acompanaplus@correo.com"

DOCUMENTOS = db.DOCUMENTOS
GENEROS = db.GENEROS
PARENTESCOS = db.PARENTESCOS
MOVILIDAD = db.MOVILIDAD
FORMACION = db.FORMACION

# Cada campo: (columna, tipo, etiqueta, ícono, obligatorio, opciones). Tipos: texto, tel, multi, lista, fecha
SOBRE_USTED = [
    ("nombre", "texto", "Nombre completo", ft.Icons.PERSON, True, None),
    ("tipo_doc", "lista", "Tipo de documento", ft.Icons.BADGE, True, DOCUMENTOS),
    ("num_doc", "texto", "Número de documento", ft.Icons.PIN, True, None),
    ("fecha_nac", "fecha", "Fecha de nacimiento", ft.Icons.CAKE, True, None),
    ("genero", "lista", "Género (opcional)", ft.Icons.PEOPLE, False, GENEROS),
]
UBICACION = [
    ("telefono", "tel", "Teléfono celular", ft.Icons.PHONE, True, None),
    ("direccion", "texto", "Dirección de residencia", ft.Icons.HOME, True, None),
    ("barrio", "texto", "Barrio", ft.Icons.LOCATION_CITY, True, None),
    ("ciudad", "texto", "Ciudad o municipio", ft.Icons.MAP, True, None),
]
CONFIANZA = [
    ("contacto_nombre", "texto", "Nombre de la persona de confianza", ft.Icons.CONTACT_PHONE, True, None),
    ("contacto_parentesco", "lista", "¿Qué es para usted?", ft.Icons.FAMILY_RESTROOM, True, PARENTESCOS),
    ("contacto_tel", "tel", "Teléfono de la persona de confianza", ft.Icons.PHONE, True, None),
]
SALUD = [
    ("eps", "texto", "EPS o seguro médico (opcional)", ft.Icons.LOCAL_HOSPITAL, False, None),
    ("salud_condiciones", "multi", "Condiciones de salud que debamos conocer (opcional)",
     ft.Icons.HEALTH_AND_SAFETY, False, None),
    ("salud_medicamentos", "multi", "Medicamentos que toma (opcional)", ft.Icons.MEDICATION, False, None),
    ("salud_alergias", "multi", "Alergias (opcional)", ft.Icons.WARNING, False, None),
    ("movilidad", "lista", "¿Cómo se moviliza?", ft.Icons.ACCESSIBLE, True, MOVILIDAD),
]
FAMILIAR = [("parentesco_familiar", "lista", "¿Qué es usted del adulto mayor?", ft.Icons.FAMILY_RESTROOM, True,
             PARENTESCOS)]
EXPERIENCIA = [
    ("formacion", "lista", "Formación", ft.Icons.SCHOOL, True, FORMACION),
    ("experiencia", "multi", "Cuéntenos su experiencia cuidando o acompañando personas", ft.Icons.WORK, True, None),
    ("zona", "texto", "Zona donde presta servicios (comuna o barrios)", ft.Icons.MAP, True, None),
    ("disponibilidad", "texto", "Disponibilidad (días y horas)", ft.Icons.SCHEDULE, True, None),
]


def pasos_de(rol):
    """Pasos del registro inicial según el tipo de cuenta."""
    pasos = [
        {"titulo": "Cuéntenos quién es usted", "campos": SOBRE_USTED,
         "intro": "Empecemos por lo básico. Así podremos identificarlo."},
        {"titulo": "¿Cómo lo ubicamos?", "campos": UBICACION,
         "intro": "Estos datos nos sirven para coordinar los servicios."},
        {"titulo": "Una persona de confianza", "campos": CONFIANZA,
         "intro": "Si hay una urgencia, ¿a quién podemos llamar?"},
    ]
    if rol == "adulto_mayor":
        pasos.append({"titulo": "Su salud y su cuidado", "campos": SALUD,
                      "intro": "Casi todo es opcional. Solo la usaremos para que el servicio sea más seguro para usted."})
    elif rol == "familiar":
        pasos.append({"titulo": "Su relación con el adulto mayor", "campos": FAMILIAR,
                      "intro": "Una última pregunta sobre usted."})
    elif rol == "acompanante":
        pasos.append({"titulo": "Su experiencia como acompañante", "campos": EXPERIENCIA,
                      "intro": "Cuéntenos cómo ha trabajado acompañando personas."})
    return pasos


def campos_de(rol):
    """Todos los campos de datos personales que corresponden a un tipo de cuenta."""
    if rol in db.ROLES_PUBLICOS:
        return [c for p in pasos_de(rol) for c in p["campos"]]
    return [SOBRE_USTED[0], UBICACION[0]]  # administradores: solo nombre y teléfono


# Texto modelo del consentimiento informado. Debe ser revisado por la persona responsable del proyecto
# (idealmente con orientación jurídica) antes de usar la app con personas reales.
TERMINOS = [
    ("¿Qué es Acompaña+?",
     "Acompaña+ es una aplicación que coordina acompañamientos para adultos mayores: citas médicas, trámites, "
     "compras y visitas. Es un proyecto académico en desarrollo. No es un servicio de emergencias ni presta "
     "atención médica: los acompañantes no son personal de salud."),
    ("¿Qué datos le pedimos y para qué?",
     "Le pediremos datos de identificación (nombre, documento, fecha de nacimiento), de contacto (teléfono, "
     "dirección, barrio), de una persona de confianza y, según su caso, datos de salud (si es adulto mayor) o de "
     "formación y experiencia (si es acompañante). Los usamos para crear su perfil, asignar y coordinar servicios, "
     "contactarlo y ubicar el lugar del servicio."),
    ("Datos sensibles",
     "Los datos de salud son sensibles. Darlos es voluntario: puede dejar en blanco los campos opcionales. Solo "
     "los usaremos para que el servicio sea más seguro y adecuado para usted."),
    ("¿Quién puede ver sus datos?",
     "El equipo administrador de la plataforma, el acompañante asignado a su servicio (solo lo necesario para "
     "prestarlo) y el familiar o cuidador que usted vincule con su código de familia. No vendemos ni cedemos sus "
     "datos a terceros."),
    ("Sus derechos",
     "Conforme a la Ley 1581 de 2012 de protección de datos personales (Colombia), usted puede conocer, "
     f"actualizar, corregir y pedir que se eliminen sus datos, y retirar esta autorización cuando quiera. Escriba "
     f"a {CONTACTO_DATOS}."),
    ("Consentimiento informado",
     "Al marcar la casilla confirma que leyó y entendió este texto; que acepta de forma libre y voluntaria el "
     "tratamiento de sus datos; que sabe que los acompañantes no son personal médico; y que ante una emergencia "
     f"debe llamar a la línea 123. Versión del texto: {db.VERSION_TERMINOS}."),
]


class Ajustes:
    nivel = 0


def sz(n):
    return round(n * NIVELES[Ajustes.nivel])


def fecha_bonita(f):
    d = date.fromisoformat(f) if isinstance(f, str) else f
    return f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]} de {d.year}"


def hora_bonita(hhmm):
    h, m = map(int, hhmm.split(":"))
    return f"{h % 12 or 12}:{m:02d} {'a. m.' if h < 12 else 'p. m.'}"


def texto_duracion(minutos):
    """60 -> '1 hora', 90 -> '1 hora y media', 30 -> 'media hora', None -> 'Tiempo indefinido'."""
    if minutos is None:
        return "Tiempo indefinido"
    h, m = divmod(int(minutos), 60)
    if h == 0:
        return "media hora"
    return f"{h} hora{'' if h == 1 else 's'}" + (" y media" if m else "")


# Duraciones que se pueden elegir al pedir una cita: de 1 hora en adelante, de media en media hora, o indefinida
DURACIONES = [(str(m), texto_duracion(m)) for m in range(db.DURACION_MINIMA, db.DURACION_MAXIMA + 1, db.PASO_DURACION)] \
    + [("indefinida", "Tiempo indefinido (el acompañante la finaliza)")]
EXTENSIONES = [(str(m), texto_duracion(m)) for m in range(db.PASO_DURACION, db.EXTRA_MAXIMA + 1, db.PASO_DURACION)]


def codigo_bonito(c):
    c = c or ""
    return f"{c[:3]} {c[3:]}" if len(c) == 6 else c

# ---------- Componentes reutilizables ----------
def txt(t, size=20, bold=False, color=TEXTO, **kw):
    return ft.Text(t, size=sz(size), color=color, weight=ft.FontWeight.BOLD if bold else None, **kw)


def linea(icono, texto, size=19, color=TEXTO, icono_color=AZUL):
    return ft.Row([ft.Icon(icono, color=icono_color, size=sz(26)), txt(texto, size, color=color, expand=True)],
                  vertical_alignment=ft.CrossAxisAlignment.START, spacing=10)


def n_calif(n):
    return f"{n} calificación" if n == 1 else f"{n} calificaciones"


def _contenido_boton(t, icono, color_txt):
    return ft.Row([ft.Icon(icono, color=color_txt, size=sz(28)),
                   txt(t, 20, True, color_txt, expand=True, text_align=ft.TextAlign.CENTER)],
                  alignment=ft.MainAxisAlignment.CENTER, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                  spacing=10)


def boton(t, icono, on_click, color=AZUL):
    return ft.Button(
        content=_contenido_boton(t, icono, BLANCO), on_click=on_click,
        style=ft.ButtonStyle(bgcolor=color, elevation=4, shadow_color="#40000000",
                             shape=ft.RoundedRectangleBorder(radius=16),
                             padding=ft.Padding.symmetric(vertical=sz(16), horizontal=sz(16))))


def boton_borde(t, icono, on_click, color=AZUL):
    return ft.OutlinedButton(
        content=_contenido_boton(t, icono, color), on_click=on_click,
        style=ft.ButtonStyle(side=ft.BorderSide(2, color), shape=ft.RoundedRectangleBorder(radius=16),
                             padding=ft.Padding.symmetric(vertical=sz(14), horizontal=sz(16))))


def tile(titulo, sub, icono, color, on_click):
    """Botón grande para el menú principal."""
    textos = [txt(titulo, 22, True, BLANCO)] + ([txt(sub, 18, color=BLANCO)] if sub else [])
    return ft.Container(
        ft.Row([ft.Container(ft.Icon(icono, color=BLANCO, size=sz(40)), padding=sz(12),
                             bgcolor="#33FFFFFF", border_radius=40),
                ft.Column(textos, spacing=2, expand=True),
                ft.Icon(ft.Icons.CHEVRON_RIGHT, color=BLANCO, size=sz(32))],
               vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=14),
        bgcolor=color, border_radius=20, padding=ft.Padding.all(16), on_click=on_click, ink=True,
        shadow=ft.BoxShadow(blur_radius=8, color="#33000000", offset=ft.Offset(0, 3)))


def campo(label, **kw):
    return ft.TextField(label=label, text_size=sz(20), label_style=ft.TextStyle(size=sz(18), color=GRIS),
                        border_color=AZUL, border_width=2, border_radius=12, bgcolor=BLANCO,
                        color=TEXTO, error_style=ft.TextStyle(size=sz(17), color=ROJO),
                        error_max_lines=3, **kw)


def desplegable(label, opciones, value=None):
    # Cada opción lleva su propio texto negro: así se lee aunque el sistema esté en modo oscuro
    return ft.Dropdown(label=label, text_size=sz(20), label_style=ft.TextStyle(size=sz(18), color=GRIS),
                       text_style=ft.TextStyle(size=sz(20), color=TEXTO), border_color=AZUL,
                       border_width=2, border_radius=12, bgcolor=BLANCO, color=TEXTO, value=value,
                       options=[ft.DropdownOption(key=k, text=t, content=txt(t, 20, color=TEXTO))
                                for k, t in opciones])


def selector_estrellas(actualizar, inicial=None):
    """Devuelve (control, estado). estado['n'] vale None hasta que se elige de 0 a 5."""
    estado = {"n": inicial}
    etiqueta = txt("Toque una estrella (de 0 a 5)", 18, True, GRIS)
    estrellas = []

    def elegir(n):
        estado["n"] = n
        for k, b in enumerate(estrellas, start=1):
            b.icon = ft.Icons.STAR if k <= n else ft.Icons.STAR_BORDER
        etiqueta.value = f"{n} de 5"
        actualizar()

    cero = ft.TextButton(content=txt("0", 26, True, AZUL), tooltip="0 estrellas", on_click=lambda e: elegir(0))
    for k in range(1, 6):
        estrellas.append(ft.IconButton(ft.Icons.STAR_BORDER, icon_color=AMBAR, icon_size=sz(38),
                                       tooltip=f"{k} estrellas", on_click=lambda e, k=k: elegir(k)))
    return ft.Column([ft.Row([cero] + estrellas, wrap=True, spacing=0, alignment=ft.MainAxisAlignment.CENTER),
                      ft.Row([etiqueta], alignment=ft.MainAxisAlignment.CENTER)], spacing=4), estado


def selector_fecha(etiqueta, valor=""):
    """Tres listas (día, mes, año). Devuelve (control, leer); leer() da 'AAAA-MM-DD', '' si falta algo."""
    try:
        a0, m0, d0 = (int(x) for x in (valor or "").split("-"))
    except ValueError:
        a0 = m0 = d0 = None
    ultimo = db.hoy_local().year - 18
    dia = desplegable("Día", [(str(d), str(d)) for d in range(1, 32)], str(d0) if d0 else None)
    mes = desplegable("Mes", [(str(i + 1), n.capitalize()) for i, n in enumerate(MESES)], str(m0) if m0 else None)
    anio = desplegable("Año", [(str(a), str(a)) for a in range(ultimo, 1909, -1)],
                       str(a0) if a0 and 1910 <= a0 <= ultimo else None)

    def leer():
        if not (dia.value and mes.value and anio.value):
            return ""
        try:
            return date(int(anio.value), int(mes.value), int(dia.value)).isoformat()
        except ValueError:
            return "invalida"

    return ft.Column([txt(etiqueta, 18, True, GRIS), dia, mes, anio], spacing=8), leer

def caja(*controles, color=BLANCO):
    return ft.Container(ft.Column(list(controles), spacing=10), padding=16, bgcolor=color,
                        border_radius=16, border=ft.Border.all(1, BORDE))


def chip(estado):
    return ft.Row([ft.Container(
        ft.Row([ft.Icon(ICONO_ESTADO[estado], color=BLANCO, size=sz(22)), txt(estado, 18, True, BLANCO)],
               tight=True, spacing=6),
        bgcolor=COLOR_ESTADO[estado], border_radius=20,
        padding=ft.Padding.symmetric(vertical=6, horizontal=14))])


def avatar(foto, nombre, tam=44, on_click=None):
    ini = "".join(p[0] for p in nombre.split()[:2]).upper() or "?"
    contenido = (ft.Image(src=foto, width=tam, height=tam, fit=ft.BoxFit.COVER) if foto
                 else ft.Text(ini, size=tam * 0.42, weight=ft.FontWeight.BOLD, color=AZUL))
    return ft.Container(contenido, width=tam, height=tam, border_radius=tam / 2, bgcolor=BLANCO,
                        alignment=ft.Alignment.CENTER, clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                        border=ft.Border.all(2, BLANCO), on_click=on_click, tooltip="Mi perfil")


def vista(fn):
    """Recuerda la pantalla actual para poder redibujarla (por ejemplo al cambiar el tamaño de letra)."""
    def envoltura(self, *a, **k):
        self._actual = lambda: fn(self, *a, **k)
        return fn(self, *a, **k)
    return envoltura


class App:
    def __init__(self, page: ft.Page):
        self.page = page
        self.user = None
        self.foto = None
        self._actual = None
        self.guardia = None
        self.real = None  # super administrador que está viendo la cuenta de otra persona
        self.onb = {"paso": 0}
        self.filtro = {"texto": "", "rol": ""}
        page.title = "Acompaña+"
        page.bgcolor = FONDO
        page.theme_mode = ft.ThemeMode.LIGHT  # siempre claro: evita letra blanca sobre fondo blanco
        page.theme = ft.Theme(color_scheme_seed=AZUL)
        page.padding = 16
        page.window.width = 440
        page.window.height = 820
        try:  # calendario en español
            page.locale_configuration = ft.LocaleConfiguration(
                supported_locales=[ft.Locale("es", "CO")], current_locale=ft.Locale("es", "CO"))
        except Exception:
            pass
        self.selector = ft.FilePicker()
        self.web = ft.UrlLauncher()
        page.services.extend([self.selector, self.web])
        self.login()

    # ---------- Utilidades ----------
    def render(self, titulo, *controles, volver=None, guardia=None, sin_menu=False):
        p = self.page
        p.clean()
        self.guardia = guardia
        acciones = [ft.IconButton(ft.Icons.FORMAT_SIZE, icon_color=BLANCO, icon_size=30,
                                  tooltip="Cambiar tamaño de letra (Tt)", on_click=self.ciclar_escala)]
        if self.user and not sin_menu:
            if self.user["rol"] in db.ROLES_PUBLICOS:
                acciones.append(ft.IconButton(ft.Icons.HELP, icon_color=BLANCO, icon_size=30,
                                              tooltip="Ayuda", on_click=self.ayuda))
            acciones.append(avatar(self.foto, self.user["nombre"], 44, lambda e: self.ir(self.perfil)))
        acciones.append(ft.Container(width=8))
        atras = ft.TextButton(
            content=ft.Row([ft.Icon(ft.Icons.ARROW_BACK, color=BLANCO, size=28),
                            ft.Text("Atrás", size=20, weight=ft.FontWeight.BOLD, color=BLANCO)],
                           tight=True, spacing=4),
            on_click=lambda e: self.ir(volver)) if volver else None
        p.appbar = ft.AppBar(
            leading=atras, leading_width=120 if volver else None, bgcolor=AZUL, color=BLANCO,
            toolbar_height=64, actions=acciones,
            title=ft.Text(titulo, size=22, weight=ft.FontWeight.BOLD, color=BLANCO, max_lines=1,
                          overflow=ft.TextOverflow.ELLIPSIS))
        arriba = [self.banner_suplantacion()] if self.real else []
        p.add(ft.Column(arriba + list(controles), scroll=ft.ScrollMode.AUTO, expand=True, spacing=16,
                        horizontal_alignment=ft.CrossAxisAlignment.STRETCH))
        p.update()

    def banner_suplantacion(self):
        u = self.user
        return ft.Container(
            ft.Column([linea(ft.Icons.VISIBILITY,
                             f"Está viendo la cuenta de {u['nombre']} ({ROLES_NOMBRE.get(u['rol'], u['rol'])}).",
                             icono_color=TEXTO),
                       boton("Volver a mi cuenta de super administrador", ft.Icons.ARROW_BACK,
                             self.salir_suplantacion, MORADO)], spacing=10),
            padding=12, bgcolor="#FFE082", border_radius=14, border=ft.Border.all(2, AMBAR))

    def aviso(self, mensaje):
        self.page.show_dialog(ft.SnackBar(txt(mensaje, 18, color=BLANCO), bgcolor=AZUL, duration=4000))

    def ir(self, destino):
        """Va a 'destino'; si hay una cita a medio escribir, pide confirmación antes de salir."""
        if self.guardia and self.guardia():
            def salir_ya(ev):
                self.cerrar()
                destino()

            self.dialogo("¿Salir sin guardar?",
                         txt("Si sale ahora, perderá los datos de la cita que está escribiendo.", 19),
                         boton("Sí, salir", ft.Icons.EXIT_TO_APP, salir_ya, ROJO),
                         boton("No, seguir con mi cita", ft.Icons.EDIT, self.cerrar, VERDE),
                         icono=ft.Icons.WARNING, color=ROJO)
        else:
            destino()

    def revisar_correo(self, c):
        c.error = MSG_CORREO if (c.value or "").strip() and not db.email_valido(c.value) else None
        self.page.update()

    def cerrar(self, e=None):
        self.page.pop_dialog()

    def dialogo(self, titulo, *contenido, icono=None, color=AZUL):
        cab = ([ft.Icon(icono, color=color, size=sz(34))] if icono else []) + [txt(titulo, 22, True, color, expand=True)]
        self.page.show_dialog(ft.AlertDialog(
            title=ft.Row(cab, spacing=10),
            content=ft.Container(ft.Column(list(contenido), spacing=12, scroll=ft.ScrollMode.AUTO), width=330),
            bgcolor=BLANCO))

    def alerta(self, titulo, mensaje):
        self.dialogo(titulo, txt(mensaje, 19), boton("Entendido", ft.Icons.CHECK, self.cerrar),
                     icono=ft.Icons.WARNING, color=ROJO)

    def abrir_url(self, url):
        self.page.run_task(self.web.launch_url, url)

    def whatsapp(self, telefono):
        num = db.solo_digitos(telefono)
        if len(num) == 10:
            num = "57" + num  # Colombia
        self.abrir_url(f"https://wa.me/{num}")

    def ciclar_escala(self, e=None):
        self.ir(lambda: self.fijar_escala((Ajustes.nivel + 1) % len(NIVELES)))

    def fijar_escala(self, n):
        Ajustes.nivel = n
        if self.user and not self.real:
            db.guardar_escala(self.user["id"], n)
            self.user["escala"] = n
        if self._actual:
            self._actual()

    def entrar(self, u):
        if u.get("activo", 1) == 0:
            self.login()
            self.aviso("Su cuenta está suspendida. Comuníquese con el administrador.")
            return
        self.user = u
        Ajustes.nivel = u.get("escala") or 0
        self.foto = db.foto_de(u["id"])
        self.continuar()

    def continuar(self):
        """Después de ingresar: cambio de clave obligatorio, registro en pasos o la pantalla principal."""
        u = self.user
        if u.get("debe_cambiar_clave"):
            self.cambiar_clave(forzado=True)
        elif u["rol"] in db.ROLES_PUBLICOS and not u.get("onboarding_completo"):
            self.iniciar_onboarding()
        else:
            self.inicio()

    def entrar_como(self, uid):
        objetivo = db.obtener_usuario(uid)
        if not objetivo or objetivo["rol"] == "superadmin":
            self.aviso("No se puede entrar a esa cuenta.")
            return
        db.auditar(self.user["id"], "entrar_a_cuenta", uid, f"tipo {objetivo['rol']}")
        self.real, self.user = self.user, objetivo
        Ajustes.nivel = objetivo.get("escala") or 0
        self.foto = db.foto_de(objetivo["id"])
        self.inicio()

    def salir_suplantacion(self, e=None):
        db.auditar(self.real["id"], "salir_de_cuenta", self.user["id"])
        self.user, self.real = self.real, None
        Ajustes.nivel = self.user.get("escala") or 0
        self.foto = db.foto_de(self.user["id"])
        self.inicio()

    def salir(self, e=None):
        self.user, self.real, self.foto, Ajustes.nivel = None, None, None, 0
        self.login()

    # ---------- Ayuda (siempre visible en la esquina) ----------
    def ayuda(self, e=None):
        pasos = [linea(ft.Icons.ADD_CIRCLE, "Para pedir un acompañamiento, pulse «Pedir acompañamiento»."),
                 linea(ft.Icons.EVENT, "Para ver sus citas, pulse «Mis citas»."),
                 linea(ft.Icons.FORMAT_SIZE, "Para agrandar la letra, pulse el botón «Tt» de arriba."),
                 linea(ft.Icons.ACCOUNT_CIRCLE, "Su foto, sus datos y su historial están en el círculo de arriba.")]
        u = self.user
        if u.get("contacto_tel"):
            pasos.append(boton(f"WhatsApp a {u.get('contacto_nombre') or 'mi contacto'}", ft.Icons.CHAT,
                               lambda ev: self.whatsapp(u["contacto_tel"]), VERDE))
        else:
            pasos.append(txt("Agregue un contacto de confianza en su perfil para escribirle desde aquí.", 18))
        pasos.append(boton("Cerrar", ft.Icons.CLOSE, self.cerrar, GRIS))
        self.dialogo("¿Necesita ayuda?", *pasos, icono=ft.Icons.HELP)

    # ---------- Autenticación (CU-01, CU-02) ----------
    @vista
    def login(self, e=None):
        email = campo("Correo electrónico", keyboard_type=ft.KeyboardType.EMAIL, prefix_icon=ft.Icons.EMAIL,
                      on_blur=lambda ev: self.revisar_correo(email))
        pw = campo("Contraseña", password=True, can_reveal_password=True, prefix_icon=ft.Icons.LOCK)
        err = txt("", 18, color=ROJO)

        def entrar(ev):
            if not db.email_valido(email.value or ""):
                email.error = MSG_CORREO
                self.page.update()
                return
            u = db.login(email.value or "", pw.value or "")
            if not u:
                err.value = "Correo o contraseña incorrectos."
                self.page.update()
                return
            self.entrar(u)

        self.render(
            "Acompaña+",
            ft.Row([ft.Icon(ft.Icons.FAVORITE, color=ROJO, size=sz(40)), txt("Bienvenido", 32, True, AZUL)]),
            txt("Inicie sesión para continuar."), email, pw, err,
            boton("Iniciar sesión", ft.Icons.LOGIN, entrar),
            boton("Continuar con Google", ft.Icons.LANGUAGE, self.google, GRIS),
            boton_borde("Crear una cuenta nueva", ft.Icons.PERSON_ADD, self.registro),
        )

    @vista
    def registro(self, e=None):
        nombre = campo("Nombre completo", prefix_icon=ft.Icons.PERSON)
        email = campo("Correo electrónico (ejemplo: nombre@gmail.com)",
                      keyboard_type=ft.KeyboardType.EMAIL, prefix_icon=ft.Icons.EMAIL,
                      on_blur=lambda ev: self.revisar_correo(email))
        pw = campo("Contraseña (mínimo 6 caracteres)", password=True, can_reveal_password=True,
                   prefix_icon=ft.Icons.LOCK)
        rol = desplegable("¿Quién es usted?", list(ROLES.items()), "adulto_mayor")
        err = txt("", 18, color=ROJO)

        def crear(ev):
            if not db.email_valido(email.value or ""):
                email.error = MSG_CORREO
                self.page.update()
                return
            ok, msg = db.registrar(nombre.value or "", email.value or "", pw.value or "", rol.value)
            if ok:
                self.login()
                self.aviso(msg)
            else:
                err.value = msg
                self.page.update()

        self.render("Crear cuenta", nombre, email, pw, rol, err,
                    boton("Registrarme", ft.Icons.CHECK_CIRCLE, crear, VERDE),
                    boton("Registrarme con Google", ft.Icons.LANGUAGE, self.google, GRIS),
                    volver=self.login)

    def inicio(self, e=None):
        {"administrador": self.admin, "superadmin": self.superadmin, "acompanante": self.acomp}.get(self.user["rol"], self.cliente)()

    # ---------- Tarjeta y detalle ----------
    def tarjeta(self, s, acciones=(), extra=()):
        rol = self.user["rol"]
        cab = ft.Row([ft.Container(ft.Icon(ICONO_TIPO.get(s["tipo"], ft.Icons.EVENT), color=BLANCO,
                                           size=sz(30)), bgcolor=AZUL, padding=sz(10), border_radius=14),
                      txt(s["tipo"], 22, True, expand=True)],
                     spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        filas = [cab, chip(s["estado"]),
                 linea(ft.Icons.CALENDAR_MONTH, fecha_bonita(s["fecha"])),
                 linea(ft.Icons.ACCESS_TIME, hora_bonita(s["hora"])),
                 linea(ft.Icons.PLACE, f"Desde: {s['origen']}"),
                 linea(ft.Icons.FLAG, f"Hasta: {s['destino']}")]
        filas += self.lineas_tiempo(s)
        filas += self.lineas_codigo(s)
        if rol != "adulto_mayor":
            filas.append(linea(ft.Icons.PERSON, f"Para: {s['solicitante']}"))
            if rol in ("acompanante", *db.ROLES_ADMIN) and s.get("prom_solicitante") is not None:
                filas.append(linea(ft.Icons.STAR, f"Calificación del usuario: {s['prom_solicitante']} de 5",
                                   icono_color=AMBAR))
        if s.get("creador") and s.get("creado_por") != s["usuario_id"]:
            filas.append(linea(ft.Icons.FAMILY_RESTROOM, f"Pedida por: {s['creador']}"))
        if s["acompanante"]:
            filas.append(linea(ft.Icons.SUPPORT_AGENT, f"Acompañante: {s['acompanante']}"))
            if rol != "acompanante" and s.get("prom_acompanante") is not None:
                filas.append(linea(ft.Icons.STAR, f"Calificación del acompañante: {s['prom_acompanante']} de 5",
                                   icono_color=AMBAR))
        filas += self.calif_lineas(s)
        filas += list(extra)
        if acciones:
            filas.append(ft.Column(list(acciones), spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH))
        return ft.Container(ft.Column(filas, spacing=10), padding=16, bgcolor=BLANCO, border_radius=18,
                            border=ft.Border.all(2, COLOR_ESTADO[s["estado"]]))

    def detalle(self, s):
        lineas = [linea(ICONO_ESTADO[s["estado"]], f"Estado: {s['estado']}"),
                  linea(ft.Icons.CALENDAR_MONTH, fecha_bonita(s["fecha"])),
                  linea(ft.Icons.ACCESS_TIME, hora_bonita(s["hora"])),
                  linea(ft.Icons.PLACE, f"Desde: {s['origen']}"),
                  linea(ft.Icons.FLAG, f"Hasta: {s['destino']}"),
                  linea(ft.Icons.NOTES, f"Observaciones: {s['observaciones'] or 'Ninguna'}"),
                  linea(ft.Icons.SUPPORT_AGENT, f"Acompañante: {s['acompanante'] or 'Aún sin asignar'}")]
        lineas += self.lineas_tiempo(s)
        lineas += self.lineas_codigo(s)
        if s["obs_final"]:
            lineas.append(linea(ft.Icons.RATE_REVIEW, f"Observaciones finales: {s['obs_final']}"))
        lineas += self.calif_lineas(s)
        if self.puede_calificar(s):
            def ir_a_calificar(ev):
                self.cerrar()
                self.calificar(s)

            lineas.append(boton(self.texto_calificar(), ft.Icons.STAR, ir_a_calificar, AMBAR))
        if self.user["rol"] == "acompanante" and s.get("tel_solicitante"):
            lineas.append(boton("WhatsApp al solicitante", ft.Icons.CHAT,
                                lambda ev: self.whatsapp(s["tel_solicitante"]), VERDE))
        elif self.user["rol"] != "acompanante" and s.get("tel_acompanante"):
            lineas.append(boton("WhatsApp al acompañante", ft.Icons.CHAT,
                                lambda ev: self.whatsapp(s["tel_acompanante"]), VERDE))
        lineas.append(boton("Cerrar", ft.Icons.CLOSE, self.cerrar, GRIS))
        self.dialogo(s["tipo"], *lineas, icono=ICONO_TIPO.get(s["tipo"], ft.Icons.EVENT))

    # ---------- Duración, código de seguridad y extensión del servicio ----------
    def lineas_tiempo(self, s):
        base, extra = s.get("duracion_min"), s.get("minutos_extra") or 0
        if base is None:
            filas = [linea(ft.Icons.TIMER, "Tiempo indefinido: el acompañante la finaliza cuando termine")]
        else:
            texto = f"Duración: {texto_duracion(base + extra)}"
            if extra:
                texto += f" (incluye {texto_duracion(extra)} adicional)"
            fin = db.fin_estimado(s)
            if fin:
                texto += f", hasta las {hora_bonita(fin.strftime('%H:%M'))}"
            filas = [linea(ft.Icons.TIMER, texto)]
            if (s["estado"] == "En curso" and fin and db.ahora_local() > fin
                    and self.user["rol"] in ("adulto_mayor", "familiar")):
                filas.append(linea(ft.Icons.INFO, "Ya pasó la hora prevista de fin. Si el acompañante sigue con "
                                                  "usted, puede extender el tiempo."))
        if s.get("inicio_real"):
            filas.append(linea(ft.Icons.PLAY_ARROW, f"Iniciada a las {hora_bonita(s['inicio_real'][11:16])}"))
        if s.get("fin_real"):
            filas.append(linea(ft.Icons.STOP_CIRCLE, f"Finalizada a las {hora_bonita(s['fin_real'][11:16])}"))
        return filas

    def lineas_codigo(self, s):
        """El código solo lo ve quien pidió la cita (adulto mayor o familiar); el acompañante debe pedírselo."""
        if self.user["rol"] not in ("adulto_mayor", "familiar") or not s.get("codigo_seguridad"):
            return []
        filas = [ft.Row([ft.Icon(ft.Icons.KEY, color=MORADO, size=sz(30)),
                         txt("Código de seguridad", 18, True, GRIS)], spacing=8),
                 ft.Text(codigo_bonito(s["codigo_seguridad"]), size=sz(38), weight=ft.FontWeight.BOLD,
                         color=MORADO, selectable=True),
                 txt("Entréguelo al acompañante solo cuando llegue. Sin este código no puede iniciar el servicio.", 17)]
        if s.get("codigo_bloqueado"):
            filas.append(txt("Este código se bloqueó por intentos fallidos. Genere uno nuevo.", 17, True, ROJO))
        return [ft.Container(ft.Column(filas, spacing=4), padding=12, bgcolor="#F3E5F5", border_radius=12)]

    def mostrar_codigo(self, sid):
        codigo = db.codigo_de(sid, self.user["id"])
        if not codigo:
            return
        self.dialogo("Cita guardada",
                     txt("Este es el código de seguridad de su cita:", 19),
                     ft.Text(codigo_bonito(codigo), size=sz(44), weight=ft.FontWeight.BOLD, color=MORADO,
                             selectable=True, text_align=ft.TextAlign.CENTER),
                     txt("Sin este código el acompañante no puede iniciar el servicio. Entréguelo solo cuando "
                         "llegue. Lo verá siempre en «Mis citas».", 18),
                     boton("Entendido", ft.Icons.CHECK, self.cerrar, VERDE), icono=ft.Icons.KEY, color=MORADO)

    def nuevo_codigo(self, s):
        def hacer():
            ok, res = db.regenerar_codigo(s["id"], self.user["id"])
            (self._actual or self.inicio)()
            if ok:
                self.mostrar_codigo(s["id"])
            else:
                self.alerta("No se pudo generar el código", res)

        self.confirmar("¿Generar un código nuevo?", "El código anterior dejará de servir. Úselo si se bloqueó o "
                       "si se lo dio a la persona equivocada.", "Sí, generar uno nuevo", hacer, MORADO, ft.Icons.KEY)

    def extender_servicio(self, s):
        """El acompañante extiende el servicio con el código de seguridad (lo autoriza el adulto mayor)."""
        codigo = campo("Código de seguridad", keyboard_type=ft.KeyboardType.NUMBER, prefix_icon=ft.Icons.KEY)
        mas = desplegable("Tiempo adicional", EXTENSIONES, "60")
        err = txt("", 18, color=ROJO)

        def ok(ev):
            exito, msg = db.ampliar_con_codigo(s["id"], self.user["id"], codigo.value or "", int(mas.value or 60))
            if exito:
                self.cerrar()
                self.acomp()
                self.aviso(msg)
            else:
                err.value = msg
                self.page.update()

        self.dialogo("Extender el servicio",
                     txt("Pídale el código de seguridad al adulto mayor: él autoriza el tiempo extra.", 18),
                     codigo, mas, err, boton("Extender", ft.Icons.MORE_TIME, ok, VERDE),
                     boton("Cancelar", ft.Icons.CLOSE, self.cerrar, GRIS), icono=ft.Icons.MORE_TIME)

    def extender_cliente(self, s):
        """El adulto mayor (o su familiar) extiende el tiempo desde su propia cuenta."""
        mas = desplegable("Tiempo adicional", EXTENSIONES, "60")
        err = txt("", 18, color=ROJO)

        def ok(ev):
            exito, msg = db.ampliar_cliente(s["id"], self.user["id"], int(mas.value or 60))
            if exito:
                self.cerrar()
                (self._actual or self.inicio)()
                self.aviso(msg)
            else:
                err.value = msg
                self.page.update()

        self.dialogo("Extender el tiempo", txt("¿Cuánto tiempo más necesita al acompañante?", 19), mas, err,
                     boton("Extender", ft.Icons.MORE_TIME, ok, VERDE),
                     boton("Cancelar", ft.Icons.CLOSE, self.cerrar, GRIS), icono=ft.Icons.MORE_TIME)

    # ---------- Calificaciones (0 a 5 estrellas, en los dos sentidos) ----------
    def texto_calificar(self):
        return "Calificar al usuario" if self.user["rol"] == "acompanante" else "Calificar al acompañante"

    def puede_calificar(self, s):
        if s["estado"] != "Finalizada" or self.real or self.user["rol"] in db.ROLES_ADMIN:
            return False
        ya = s.get("puntaje_a_usuario") if self.user["rol"] == "acompanante" else s.get("puntaje_a_acompanante")
        return ya is None

    def calif_lineas(self, s):
        if s["estado"] != "Finalizada":
            return []
        rol = self.user["rol"]
        al_acomp, al_usuario = s.get("puntaje_a_acompanante"), s.get("puntaje_a_usuario")

        def fila(etiqueta, n, vacio):
            texto = f"{etiqueta}: {n} de 5" if n is not None else vacio
            return linea(ft.Icons.STAR if n is not None else ft.Icons.STAR_BORDER, texto, icono_color=AMBAR)

        if rol == "acompanante":
            return [fila("Usted calificó al usuario", al_usuario, "Aún no ha calificado al usuario"),
                    fila("El usuario le calificó", al_acomp, "El usuario aún no le ha calificado")]
        if rol in db.ROLES_ADMIN:
            return [fila("Puntaje al acompañante", al_acomp, "Acompañante sin calificar"),
                    fila("Puntaje al usuario", al_usuario, "Usuario sin calificar")]
        return [fila("Usted calificó al acompañante", al_acomp, "Aún no ha calificado al acompañante"),
                fila("El acompañante calificó al usuario", al_usuario, "El acompañante aún no ha calificado")]

    def calificar(self, s):
        a_quien = s["solicitante"] if self.user["rol"] == "acompanante" else s["acompanante"]
        sel, estado = selector_estrellas(self.page.update)
        err = txt("", 18, color=ROJO)

        def enviar(ev):
            if estado["n"] is None:
                err.value = "Elija de 0 a 5 estrellas."
                self.page.update()
                return
            ok, msg = db.calificar(s["id"], self.user["id"], estado["n"])
            self.cerrar()
            (self._actual or self.inicio)()
            self.aviso(msg)

        self.dialogo(f"Calificar a {a_quien}",
                     txt("¿Cómo fue el servicio? 0 es muy malo y 5 es excelente.", 19), sel, err,
                     boton("Enviar calificación", ft.Icons.STAR, enviar, VERDE),
                     boton("Ahora no", ft.Icons.CLOSE, self.cerrar, GRIS), icono=ft.Icons.STAR, color=AMBAR)

    # ---------- Adulto mayor / familiar (CU-03, CU-04, CU-09, CU-10) ----------
    @vista
    def cliente(self, e=None):
        es_fam = self.user["rol"] == "familiar"
        adultos = db.adultos_de(self.user["id"]) if es_fam else []
        bloques = [txt("¿Qué desea hacer?", 26, True)]
        if es_fam:
            if adultos:
                bloques.append(caja(txt(f"Personas a su cargo ({len(adultos)} de {db.MAX_VINCULOS})", 20, True),
                                    *[linea(ft.Icons.PERSON, a["nombre"]) for a in adultos]))
            else:
                bloques.append(caja(linea(ft.Icons.INFO, "Aún no está vinculado a ningún adulto mayor. "
                                          "Pídale su código de familia y úselo en «Vincular adulto mayor».")))
        bloques += [tile("Pedir acompañamiento", "Cita, compras, trámites…", ft.Icons.ADD_CIRCLE, AZUL, self.nueva),
                    tile("Mis citas", "Las que están pendientes", ft.Icons.EVENT, TEAL,
                         lambda e: self.lista(False)),
                    tile("Historial", "Citas anteriores", ft.Icons.HISTORY, GRIS, lambda e: self.lista(True))]
        if es_fam and len(adultos) < db.MAX_VINCULOS:
            bloques.append(tile("Vincular adulto mayor", f"Puede vincular hasta {db.MAX_VINCULOS} personas",
                                ft.Icons.LINK, MORADO, self.vincular))
        self.render(f"Hola, {self.user['nombre'].split()[0]}", *bloques)

    def vincular(self, e=None):
        if len(db.adultos_de(self.user["id"])) >= db.MAX_VINCULOS:
            self.alerta("Máximo alcanzado", f"Ya tiene {db.MAX_VINCULOS} adultos mayores vinculados, que es el "
                        "máximo permitido. Para vincular a otro, primero quite un vínculo desde su perfil.")
            return
        cod = campo("Código de familia (6 letras o números)", prefix_icon=ft.Icons.KEY)
        err = txt("", 18, color=ROJO)

        def ok(ev):
            exito, msg = db.vincular(self.user["id"], cod.value or "")
            if exito:
                self.cerrar()
                self.aviso(msg)
                (self._actual or self.inicio)()
            else:
                err.value = msg
                self.page.update()

        self.dialogo("Vincular adulto mayor",
                     txt("Pídale al adulto mayor su código de familia. Lo encuentra en su perfil.", 18),
                     cod, err, boton("Vincular", ft.Icons.LINK, ok, MORADO),
                     boton("Cancelar", ft.Icons.CLOSE, self.cerrar, GRIS), icono=ft.Icons.LINK)

    def confirmar(self, titulo, mensaje, texto_si, accion, color=ROJO, icono=ft.Icons.WARNING):
        def si(ev):
            self.cerrar()
            accion()

        self.dialogo(titulo, txt(mensaje, 19), boton(texto_si, ft.Icons.CHECK, si, color),
                     boton("No, volver", ft.Icons.CLOSE, self.cerrar, GRIS), icono=icono, color=color)

    @vista
    def nueva(self, e=None):
        es_fam = self.user["rol"] == "familiar"
        adultos = db.adultos_de(self.user["id"]) if es_fam else []
        if es_fam and not adultos:
            self.render("Pedir acompañamiento",
                        caja(linea(ft.Icons.INFO, "Primero vincule al adulto mayor con su código de familia.")),
                        boton("Vincular adulto mayor", ft.Icons.LINK, self.vincular, MORADO),
                        volver=self.inicio)
            return
        para = desplegable("¿Para quién es?", [(str(a["id"]), a["nombre"]) for a in adultos],
                           str(adultos[0]["id"]) if len(adultos) == 1 else None) if es_fam else None
        tipo = desplegable("¿Qué necesita?", [(t, t) for t in TIPOS])
        hora = desplegable("Hora de inicio", [(h, hora_bonita(h)) for h in HORAS])
        duracion = desplegable("¿Cuánto tiempo necesita al acompañante?", DURACIONES, "60")
        origen = campo("¿Desde dónde sale?", prefix_icon=ft.Icons.PLACE)
        destino = campo("¿A dónde va?", prefix_icon=ft.Icons.FLAG)
        obs = campo("Observaciones (opcional)", multiline=True, min_lines=2)
        err = txt("", 18, color=ROJO)
        elegida = {"fecha": None}
        t_fecha = txt("Toque aquí para elegir", 20, True, AZUL, expand=True)

        def al_elegir(ev):
            v = ev.control.value
            if v:
                elegida["fecha"] = date(v.year, v.month, v.day)
                t_fecha.value = fecha_bonita(elegida["fecha"])
                self.page.update()

        def abrir_fecha(ev):
            self.page.show_dialog(ft.DatePicker(
                first_date=datetime.combine(db.hoy_local(), dtime.min),
                last_date=datetime(db.hoy_local().year + 2, 12, 31),
                help_text="Elija la fecha", cancel_text="Cancelar", confirm_text="Aceptar",
                on_change=al_elegir))

        caja_fecha = ft.Container(
            ft.Row([ft.Icon(ft.Icons.CALENDAR_MONTH, color=AZUL, size=sz(36)),
                    ft.Column([txt("Fecha", 18, color=GRIS), t_fecha], spacing=2, expand=True),
                    ft.Icon(ft.Icons.ARROW_DROP_DOWN, color=AZUL, size=sz(32))], spacing=12),
            padding=14, bgcolor=BLANCO, border=ft.Border.all(2, AZUL), border_radius=12,
            on_click=abrir_fecha, ink=True)

        def revisar(ev):
            if (es_fam and not para.value) or not all([tipo.value, hora.value, elegida["fecha"],
                                                       (origen.value or "").strip(), (destino.value or "").strip()]):
                err.value = "Por favor complete todos los datos obligatorios."
                self.page.update()
                return
            h, m = map(int, hora.value.split(":"))
            if datetime.combine(elegida["fecha"], dtime(h, m)) <= db.ahora_local():
                err.value = "La fecha y la hora deben ser posteriores a este momento."
                self.page.update()
                return
            err.value = ""

            def confirmar(e2):
                benef = int(para.value) if es_fam else self.user["id"]
                minutos = None if duracion.value == "indefinida" else int(duracion.value or 60)
                nuevo, msg = db.crear_solicitud(self.user["id"], benef, tipo.value, elegida["fecha"].isoformat(),
                                                hora.value, origen.value, destino.value, obs.value or "", minutos)
                self.cerrar()
                if nuevo is None:
                    self.alerta("No se pudo guardar la cita", msg)
                    return
                self.lista(False)
                self.mostrar_codigo(nuevo)

            self.dialogo("Revise su solicitud",
                         linea(ICONO_TIPO[tipo.value], tipo.value),
                         linea(ft.Icons.CALENDAR_MONTH, fecha_bonita(elegida["fecha"])),
                         linea(ft.Icons.ACCESS_TIME, hora_bonita(hora.value)),
                         linea(ft.Icons.TIMER, "Duración: " + dict(DURACIONES).get(duracion.value or "60", "")),
                         linea(ft.Icons.PLACE, f"Desde: {origen.value}"),
                         linea(ft.Icons.FLAG, f"Hasta: {destino.value}"),
                         boton("Confirmar", ft.Icons.CHECK_CIRCLE, confirmar, VERDE),
                         boton("Corregir", ft.Icons.EDIT, self.cerrar, GRIS), icono=ft.Icons.FACT_CHECK)

        self.render("Pedir acompañamiento", *([para] if para else []), tipo, caja_fecha, hora, duracion,
                    origen, destino, obs, err, boton("Revisar y confirmar", ft.Icons.FACT_CHECK, revisar),
                    volver=self.inicio,
                    guardia=lambda: any([tipo.value, hora.value, elegida["fecha"], (origen.value or "").strip(),
                                         (destino.value or "").strip(), (obs.value or "").strip()]))

    @vista
    def lista(self, historial=False, volver=None):
        tarjetas = []
        for s in db.solicitudes_de(self.user["id"], historial):
            acc = [boton("Ver detalle", ft.Icons.VISIBILITY, lambda e, s=s: self.detalle(s))]
            if s["estado"] == "En curso" and s.get("duracion_min") is not None:
                acc.append(boton("Extender el tiempo", ft.Icons.MORE_TIME, lambda e, s=s: self.extender_cliente(s), TEAL))
            if s["estado"] in db.ACTIVOS and s.get("codigo_seguridad"):
                acc.append(boton_borde("Generar código nuevo", ft.Icons.AUTORENEW, lambda e, s=s: self.nuevo_codigo(s),
                                       MORADO))
            if s["estado"] in ("Solicitada", "Asignada"):
                acc.append(boton("Cancelar cita", ft.Icons.CANCEL, lambda e, s=s: self.cancelar(s), ROJO))
            if self.puede_calificar(s):
                acc.append(boton(self.texto_calificar(), ft.Icons.STAR, lambda e, s=s: self.calificar(s), AMBAR))
            tarjetas.append(self.tarjeta(s, acc))
        if not tarjetas:
            tarjetas = [caja(linea(ft.Icons.INFO, "No hay citas para mostrar."))]
        self.render("Historial de citas" if historial else "Mis citas", *tarjetas,
                    volver=volver or self.inicio)

    def cancelar(self, s):
        def si(ev):
            db.cancelar(s["id"], self.user["id"])
            self.cerrar()
            (self._actual or self.inicio)()
            self.aviso("La cita fue cancelada.")

        self.dialogo("¿Cancelar esta cita?", linea(ICONO_TIPO.get(s["tipo"], ft.Icons.EVENT), s["tipo"]),
                     linea(ft.Icons.CALENDAR_MONTH, f"{fecha_bonita(s['fecha'])}, {hora_bonita(s['hora'])}"),
                     boton("Sí, cancelar la cita", ft.Icons.CANCEL, si, ROJO),
                     boton("No, mantenerla", ft.Icons.CHECK_CIRCLE, self.cerrar, VERDE),
                     icono=ft.Icons.CANCEL, color=ROJO)

    # ---------- Perfil (foto, datos, familia, historial, tamaño de letra) ----------
    @vista
    def perfil(self, e=None):
        u = self.user
        publico = u["rol"] in db.ROLES_PUBLICOS
        specs = campos_de(u["rol"])
        controles, leer = self.formulario(specs, u)
        err = txt("", 18, color=ROJO)

        async def elegir_foto(ev):
            try:
                archivos = await self.selector.pick_files(dialog_title="Elija su foto",
                                                          file_type=ft.FilePickerFileType.IMAGE)
            except Exception as ex:
                self.aviso(f"No se pudo abrir el selector: {ex}")
                return
            if not archivos or not archivos[0].path:
                return
            ok, msg = db.guardar_foto(u["id"], archivos[0].path)
            if ok:
                self.user = db.obtener_usuario(u["id"])
                self.foto = db.foto_de(self.user["id"])
                self.perfil()
            self.aviso(msg)

        def guardar(ev):
            datos = leer()
            msg = self.revisar(specs, datos, estricto=publico)
            if msg:
                err.value = msg
                self.page.update()
                return
            ok, m = db.guardar_datos(u["id"], datos)
            if ok:
                self.user = db.obtener_usuario(u["id"])
                self.perfil()
                self.aviso(m)
            else:
                err.value = m
                self.page.update()

        niveles = ft.Column([
            boton(n, ft.Icons.FORMAT_SIZE, lambda ev, i=i: self.fijar_escala(i), AZUL if i == Ajustes.nivel else GRIS)
            for i, n in enumerate(NOMBRES_NIVEL)], spacing=8, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

        bloques = [ft.Row([avatar(self.foto, u["nombre"], sz(120))], alignment=ft.MainAxisAlignment.CENTER),
                   boton("Cambiar mi foto", ft.Icons.CAMERA_ALT, elegir_foto, TEAL),
                   caja(linea(ft.Icons.BADGE, f"Soy: {ROLES_NOMBRE.get(u['rol'], u['rol'])}"),
                        linea(ft.Icons.EMAIL, u["email"]))]
        if publico:
            prom, n = db.promedio(u["id"])
            bloques.append(caja(txt("Mi calificación", 20, True),
                                linea(ft.Icons.STAR, f"{prom} de 5 ({n_calif(n)})" if prom is not None
                                      else "Aún no tiene calificaciones", icono_color=AMBAR)))
        if u["rol"] == "adulto_mayor":
            fam = db.familiares_de(u["id"])
            bloques.append(caja(
                txt("Mi código de familia", 20, True),
                ft.Text(u.get("codigo") or "—", size=sz(38), weight=ft.FontWeight.BOLD, color=MORADO,
                        selectable=True),
                txt("Entregue este código a su familiar para que pueda pedir citas por usted.", 18),
                *([txt("Familiares vinculados:", 18, True)] + [linea(ft.Icons.FAMILY_RESTROOM, f["nombre"])
                                                              for f in fam] if fam else [])))
        if u["rol"] == "familiar":
            adultos = db.adultos_de(u["id"])
            filas = [txt(f"Adultos mayores a mi cargo ({len(adultos)} de {db.MAX_VINCULOS})", 20, True)]
            for a in adultos:
                def quitar(a=a):
                    db.desvincular(u["id"], a["id"])
                    self.perfil()
                    self.aviso("Vínculo quitado.")

                filas += [linea(ft.Icons.PERSON, a["nombre"]),
                          boton_borde(f"Quitar a {a['nombre'].split()[0]}", ft.Icons.PERSON_REMOVE,
                                      lambda ev, a=a, quitar=quitar: self.confirmar(
                                          "¿Quitar este vínculo?",
                                          f"Dejará de ver y de pedir citas por {a['nombre']}. "
                                          "Podrá volver a vincularlo con su código.", "Sí, quitar vínculo", quitar),
                                      ROJO)]
            if not adultos:
                filas.append(txt("Ninguno todavía.", 18))
            filas.append(boton("Vincular adulto mayor", ft.Icons.LINK, self.vincular, MORADO)
                         if len(adultos) < db.MAX_VINCULOS
                         else txt(f"Llegó al máximo de {db.MAX_VINCULOS} personas.", 18, True, GRIS))
            bloques.append(caja(*filas))
        if publico:
            i = 0
            for p in pasos_de(u["rol"]):
                bloques.append(txt(p["titulo"], 22, True))
                bloques += controles[i:i + len(p["campos"])]
                i += len(p["campos"])
        else:
            bloques += [txt("Mis datos", 22, True)] + controles
        bloques += [err, boton("Guardar mis datos", ft.Icons.SAVE, guardar, VERDE)]
        if u["rol"] == "acompanante":
            bloques.append(boton("Ver mi historial de servicios", ft.Icons.HISTORY,
                                 lambda ev: self.historial_acomp(volver=self.perfil), TEAL))
        elif publico:
            bloques.append(boton("Ver mi historial de citas", ft.Icons.HISTORY,
                                 lambda ev: self.lista(True, volver=self.perfil), TEAL))
        if not self.real and not u.get("es_google"):
            bloques.append(boton("Cambiar mi contraseña", ft.Icons.LOCK_RESET, self.cambiar_clave, AZUL))
        bloques += [txt("Tamaño de letra", 22, True), niveles]
        if not self.real:
            bloques.append(boton("Cerrar sesión", ft.Icons.LOGOUT, self.salir, ROJO))
        self.render("Mi perfil", *bloques, volver=self.inicio)

    # ---------- Acompañante (CU-06, CU-07, CU-08) ----------
    def resumen_acomp(self, servicios):
        fin = sum(1 for x in servicios if x["estado"] == "Finalizada")
        can = sum(1 for x in servicios if x["estado"] == "Cancelada")
        pen = sum(1 for x in servicios if x["estado"] in ("Asignada", "En curso"))
        prom, n = db.promedio(self.user["id"])
        return caja(txt("Mi resumen", 22, True),
                    linea(ft.Icons.CHECK_CIRCLE, f"Servicios prestados (finalizados): {fin}"),
                    linea(ft.Icons.CANCEL, f"Servicios cancelados: {can}"),
                    linea(ft.Icons.SCHEDULE, f"Servicios pendientes: {pen}"),
                    linea(ft.Icons.STAR, f"Mi calificación: {prom} de 5 ({n_calif(n)})" if prom is not None
                          else "Aún no tiene calificaciones", icono_color=AMBAR))

    @vista
    def acomp(self, e=None):
        servicios = db.servicios_de(self.user["id"])
        activos = []
        for s in servicios:
            det = boton("Ver detalle", ft.Icons.VISIBILITY, lambda e, s=s: self.detalle(s), GRIS)
            if s["estado"] == "Asignada":
                desde, hasta = db.ventana_inicio(s["fecha"], s["hora"])
                ventana = linea(ft.Icons.TIMER, f"Podrá iniciarlo de {hora_bonita(desde.strftime('%H:%M'))} "
                                                f"a {hora_bonita(hasta.strftime('%H:%M'))}")
                activos.append(self.tarjeta(s, [boton("Iniciar servicio", ft.Icons.PLAY_ARROW,
                                                      lambda e, s=s: self.iniciar(s), VERDE), det],
                                            extra=[ventana]))
            elif s["estado"] == "En curso":
                acc = [boton("Finalizar servicio", ft.Icons.STOP_CIRCLE, lambda e, s=s: self.finalizar(s), ROJO)]
                if s.get("duracion_min") is not None:
                    acc.insert(0, boton("Extender el tiempo", ft.Icons.MORE_TIME,
                                        lambda e, s=s: self.extender_servicio(s), TEAL))
                activos.append(self.tarjeta(s, acc + [det]))
        self.render(f"Hola, {self.user['nombre'].split()[0]}", self.resumen_acomp(servicios),
                    txt("Servicios pendientes", 24, True),
                    *(activos or [caja(linea(ft.Icons.INFO, "No tiene servicios pendientes."))]),
                    tile("Mi historial de servicios", "Prestados, finalizados y cancelados", ft.Icons.HISTORY,
                         GRIS, lambda e: self.historial_acomp()))

    @vista
    def historial_acomp(self, e=None, volver=None):
        servicios = db.servicios_de(self.user["id"])

        def tarjetas(estado, vacio):
            out = []
            for s in (x for x in servicios if x["estado"] == estado):
                acc = [boton("Ver detalle", ft.Icons.VISIBILITY, lambda e, s=s: self.detalle(s), GRIS)]
                if self.puede_calificar(s):
                    acc.append(boton(self.texto_calificar(), ft.Icons.STAR, lambda e, s=s: self.calificar(s), AMBAR))
                out.append(self.tarjeta(s, acc))
            return out or [caja(linea(ft.Icons.INFO, vacio))]

        self.render("Mi historial", self.resumen_acomp(servicios),
                    txt("Servicios finalizados", 24, True), *tarjetas("Finalizada", "Aún no hay servicios finalizados."),
                    txt("Servicios cancelados", 24, True), *tarjetas("Cancelada", "No hay servicios cancelados."),
                    volver=volver or self.inicio)

    def iniciar(self, s):
        ok, msg = db.revisar_inicio(s["id"], self.user["id"])
        if not ok:
            self.alerta("No se puede iniciar el servicio", msg)
            return
        codigo = campo("Código de seguridad", keyboard_type=ft.KeyboardType.NUMBER, prefix_icon=ft.Icons.KEY)
        err = txt("", 18, color=ROJO)

        def entrar(ev):
            exito, m = db.iniciar_servicio(s["id"], self.user["id"], codigo.value or "")
            if exito:
                self.cerrar()
                self.acomp()
                self.aviso(m)
            else:
                err.value = m
                self.page.update()

        self.dialogo("Iniciar el servicio",
                     txt("Pídale al adulto mayor (o a su familiar) el código de seguridad de la cita. "
                         "Sin él no se puede iniciar.", 18),
                     codigo, err, boton("Iniciar", ft.Icons.PLAY_ARROW, entrar, VERDE),
                     boton("Cancelar", ft.Icons.CLOSE, self.cerrar, GRIS), icono=ft.Icons.KEY, color=MORADO)

    def finalizar(self, s):
        obs = campo("Observaciones finales (opcional)", multiline=True, min_lines=2)
        sel, estado = selector_estrellas(self.page.update)

        def fin(ev):
            db.cambiar_estado(s["id"], "Finalizada", obs.value or "")
            msg = "Servicio finalizado."
            if estado["n"] is not None and not self.real:
                ok, extra = db.calificar(s["id"], self.user["id"], estado["n"])
                msg += f" {extra}" if ok else ""
            self.cerrar()
            self.acomp()
            self.aviso(msg)

        self.dialogo("Finalizar servicio", obs, txt("Califique al usuario (opcional)", 20, True), sel,
                     boton("Finalizar", ft.Icons.CHECK_CIRCLE, fin, VERDE),
                     boton("Volver", ft.Icons.ARROW_BACK, self.cerrar, GRIS), icono=ft.Icons.STOP_CIRCLE)

    # ---------- Administrador (CU-05) ----------
    @vista
    def admin(self, e=None):
        es_super = self.user["rol"] == "superadmin"
        acomps = db.acompanantes()
        tarjetas = []
        for s in db.todas():
            extra = []
            if s["estado"] == "Solicitada":
                dd = desplegable("Elegir acompañante", [(str(a["id"]), a["nombre"]) for a in acomps])

                def asignar(ev, s=s, dd=dd):
                    if not dd.value:
                        self.aviso("Seleccione un acompañante.")
                        return
                    ok, msg = db.asignar(s["id"], int(dd.value))
                    if ok:
                        self.admin()
                        self.aviso(msg)
                    else:
                        self.alerta("Cruce de horarios", msg)

                extra = [dd if acomps else txt("No hay acompañantes registrados.", 18, color=ROJO),
                         boton("Asignar acompañante", ft.Icons.PERSON_ADD, asignar)]
            if es_super:
                extra.append(boton("Corregir estado o acompañante", ft.Icons.EDIT,
                                   lambda ev, s=s: self.editar_cita(s), MORADO))
            tarjetas.append(self.tarjeta(s, extra=extra))
        self.render("Citas y asignaciones" if es_super else "Panel del administrador",
                    txt("Todas las solicitudes", 24, True),
                    *(tarjetas or [caja(linea(ft.Icons.INFO, "Aún no hay solicitudes."))]),
                    volver=self.inicio if es_super else None)

    # ---------- Formularios reutilizables ----------
    def formulario(self, specs, valores):
        """Crea los controles de una lista de campos. Devuelve (controles, leer) donde leer() da un dict."""
        controles, lectores = [], {}
        for clave, tipo, etiqueta, icono, _obligatorio, opciones in specs:
            v = valores.get(clave) or ""
            if tipo == "fecha":
                c, lectores[clave] = selector_fecha(etiqueta, v)
            elif tipo == "lista":
                c = desplegable(etiqueta, [(o, o) for o in opciones], v if v in opciones else None)
                lectores[clave] = lambda c=c: c.value or ""
            else:
                extra = {"keyboard_type": ft.KeyboardType.PHONE} if tipo == "tel" else {}
                if tipo == "multi":
                    extra.update(multiline=True, min_lines=2)
                c = campo(etiqueta, value=v, prefix_icon=icono, **extra)
                lectores[clave] = lambda c=c: (c.value or "").strip()
            controles.append(c)
        return controles, lambda: {k: f() for k, f in lectores.items()}

    def revisar(self, specs, datos, estricto=True):
        """Mensaje de error si faltan datos obligatorios o tienen mal formato; None si todo está bien."""
        if estricto:
            faltan = [s[2] for s in specs if s[4] and not datos.get(s[0])]
            if faltan:
                return "Por favor complete: " + ", ".join(faltan) + "."
        return db.validar_formatos(datos)

    # ---------- Registro inicial en pasos (con consentimiento informado) ----------
    def iniciar_onboarding(self):
        self.onb = {"paso": 1 if db.terminos_aceptados(self.user) else 0}
        self.onboarding()

    @vista
    def onboarding(self, e=None):
        u = db.obtener_usuario(self.user["id"])
        self.user = u
        pasos = pasos_de(u["rol"])
        n = len(pasos)
        i = self.onb["paso"]
        total = n + 2
        barra = ft.Column([txt(f"Paso {i + 1} de {total}", 18, True, GRIS),
                           ft.ProgressBar(value=(i + 1) / total, color=AZUL, bgcolor="#CFD8DC", bar_height=12,
                                          border_radius=6)], spacing=6)
        err = txt("", 18, color=ROJO)

        def ir_a(paso):
            self.onb["paso"] = paso
            self.onboarding()

        if i == 0:  # términos y consentimiento informado
            texto = ft.Container(
                ft.Column([x for t, c in TERMINOS for x in (txt(t, 20, True, AZUL), txt(c, 18))],
                          scroll=ft.ScrollMode.AUTO, spacing=8),
                height=330, padding=14, bgcolor=BLANCO, border_radius=14, border=ft.Border.all(2, AZUL))
            acepto = ft.Checkbox(label="He leído y acepto el consentimiento informado y el tratamiento de mis datos.",
                                 label_style=ft.TextStyle(size=sz(19), color=TEXTO), active_color=AZUL)

            def seguir(ev):
                if not acepto.value:
                    err.value = "Para continuar, marque la casilla de aceptación."
                    self.page.update()
                    return
                db.aceptar_terminos(u["id"])
                ir_a(1)

            def no_acepto(ev):
                def salir_ya(ev2):
                    self.cerrar()
                    self.salir()

                self.dialogo("¿No desea aceptar?",
                             txt("Sin su aceptación no podemos crear su perfil ni prestarle el servicio. "
                                 "Puede volver cuando quiera.", 19),
                             boton("Salir", ft.Icons.LOGOUT, salir_ya, ROJO),
                             boton("Volver a leer", ft.Icons.ARROW_BACK, self.cerrar, VERDE), icono=ft.Icons.WARNING,
                             color=ROJO)

            self.render("Bienvenido(a)", barra, txt("Antes de empezar", 26, True, AZUL),
                        txt("Lea con calma. Si tiene dudas, puede pedir ayuda a una persona de su confianza.", 19),
                        texto, acepto, err, boton("Acepto y continuar", ft.Icons.CHECK_CIRCLE, seguir, VERDE),
                        boton_borde("No acepto", ft.Icons.CLOSE, no_acepto, ROJO), sin_menu=True)
        elif i <= n:  # preguntas
            paso = pasos[i - 1]
            controles, leer = self.formulario(paso["campos"], u)

            def siguiente(ev):
                datos = leer()
                msg = self.revisar(paso["campos"], datos)
                if not msg:
                    ok, msg = db.guardar_datos(u["id"], datos)
                    msg = None if ok else msg
                if msg:
                    err.value = msg
                    self.page.update()
                    return
                ir_a(i + 1)

            botones = [boton("Siguiente", ft.Icons.ARROW_FORWARD, siguiente)]
            if i > 1:
                botones.append(boton("Atrás", ft.Icons.ARROW_BACK, lambda ev: ir_a(i - 1), GRIS))
            self.render(paso["titulo"], barra, txt(paso["titulo"], 26, True, AZUL), txt(paso["intro"], 19),
                        *controles, err, *botones, sin_menu=True)
        else:  # resumen
            def terminar(ev):
                db.completar_onboarding(u["id"])
                self.user = db.obtener_usuario(u["id"])
                self.inicio()
                self.aviso("¡Listo! Su perfil está completo.")

            nac = fecha_bonita(u["fecha_nac"]) if db.edad_de(u["fecha_nac"]) is not None else "—"
            resumen = caja(txt("Esto es lo que nos contó", 22, True),
                           linea(ft.Icons.PERSON, u["nombre"]),
                           linea(ft.Icons.BADGE, f"{u['tipo_doc']} {u['num_doc']}"),
                           linea(ft.Icons.CAKE, nac),
                           linea(ft.Icons.PHONE, u["telefono"]),
                           linea(ft.Icons.HOME, f"{u['direccion']}, {u['barrio']}, {u['ciudad']}"),
                           linea(ft.Icons.CONTACT_PHONE, f"Persona de confianza: {u['contacto_nombre']} "
                                                         f"({u['contacto_parentesco']}) {u['contacto_tel']}"))
            self.render("Revise y finalice", barra, txt("Casi terminamos", 26, True, AZUL),
                        txt("Podrá cambiar estos datos cuando quiera en «Mi perfil».", 19), resumen,
                        boton("Finalizar", ft.Icons.CHECK_CIRCLE, terminar, VERDE),
                        boton("Atrás", ft.Icons.ARROW_BACK, lambda ev: ir_a(n), GRIS), sin_menu=True)

    # ---------- Cambio de contraseña (voluntario u obligatorio) ----------
    @vista
    def cambiar_clave(self, e=None, forzado=False):
        actual = None if forzado else campo("Contraseña actual", password=True, can_reveal_password=True,
                                            prefix_icon=ft.Icons.LOCK)
        nueva = campo("Contraseña nueva (mínimo 6 caracteres)", password=True, can_reveal_password=True,
                      prefix_icon=ft.Icons.LOCK_RESET)
        repetir = campo("Repita la contraseña nueva", password=True, can_reveal_password=True,
                        prefix_icon=ft.Icons.LOCK_RESET)
        err = txt("", 18, color=ROJO)

        def guardar(ev):
            if (nueva.value or "") != (repetir.value or ""):
                err.value = "Las contraseñas no coinciden."
                self.page.update()
                return
            ok, msg = db.cambiar_clave(self.user["id"], nueva.value or "", (actual.value or "") if actual else None)
            if not ok:
                err.value = msg
                self.page.update()
                return
            self.user = db.obtener_usuario(self.user["id"])
            if forzado:
                self.continuar()
            else:
                self.perfil()
            self.aviso(msg)

        intro = ("Por seguridad, debe crear una contraseña propia antes de continuar." if forzado
                 else "Escriba su contraseña actual y la nueva.")
        self.render("Cambiar contraseña", txt(intro, 19), *[c for c in (actual, nueva, repetir) if c], err,
                    boton("Guardar contraseña", ft.Icons.SAVE, guardar, VERDE),
                    volver=None if forzado else self.perfil, sin_menu=forzado)

    # ---------- Super administrador ----------
    @vista
    def superadmin(self, e=None):
        est = db.estadisticas(self.user["id"])
        r, c = est["por_rol"], est["por_estado"]
        prom = est["promedio"]
        resumen = caja(
            txt("Resumen de la plataforma", 22, True),
            linea(ft.Icons.PEOPLE, f"Adultos mayores: {r.get('adulto_mayor', 0)}"),
            linea(ft.Icons.FAMILY_RESTROOM, f"Familiares y cuidadores: {r.get('familiar', 0)}"),
            linea(ft.Icons.SUPPORT_AGENT, f"Acompañantes: {r.get('acompanante', 0)}"),
            linea(ft.Icons.BLOCK, f"Cuentas suspendidas: {est['suspendidas']}"),
            linea(ft.Icons.EVENT, "Citas: " + " · ".join(f"{k}: {c.get(k, 0)}" for k in db.ESTADOS)),
            linea(ft.Icons.STAR, f"Calificación promedio: {prom} de 5" if prom is not None
                  else "Aún sin calificaciones", icono_color=AMBAR))
        self.render("Super administrador", resumen,
                    tile("Usuarios", "Ver, editar y entrar a cuentas", ft.Icons.PEOPLE, AZUL,
                         lambda ev: self.usuarios_lista()),
                    tile("Citas y asignaciones", "Asignar y corregir citas", ft.Icons.EVENT, TEAL,
                         lambda ev: self.admin()),
                    tile("Registro de actividad", "Quién hizo qué y cuándo", ft.Icons.FACT_CHECK, GRIS,
                         lambda ev: self.auditoria()))

    @vista
    def usuarios_lista(self, e=None):
        f = self.filtro
        buscar = campo("Buscar por nombre o correo", value=f["texto"], prefix_icon=ft.Icons.SEARCH)
        tipo = desplegable("Tipo de cuenta", [("todos", "Todas")] + list(ROLES_NOMBRE.items()), f["rol"] or "todos")

        def aplicar(ev):
            self.filtro = {"texto": buscar.value or "", "rol": "" if tipo.value in (None, "todos") else tipo.value}
            self.usuarios_lista()

        tarjetas = []
        for u in db.listar_usuarios(self.user["id"], f["texto"], f["rol"]):
            filas = [ft.Row([avatar(None, u["nombre"], sz(48)),
                             ft.Column([txt(u["nombre"], 20, True), txt(ROLES_NOMBRE.get(u["rol"], u["rol"]), 18),
                                        txt(u["email"], 17, color=GRIS)], spacing=2, expand=True)], spacing=12)]
            if not u["activo"]:
                filas.append(ft.Row([ft.Container(txt("Cuenta suspendida", 17, True, BLANCO), bgcolor=ROJO,
                                                  border_radius=20,
                                                  padding=ft.Padding.symmetric(vertical=4, horizontal=12))]))
            filas.append(boton("Ver y editar", ft.Icons.EDIT, lambda ev, uid=u["id"]: self.usuario_detalle(uid)))
            if u["rol"] != "superadmin":
                filas.append(boton("Entrar a su cuenta", ft.Icons.LOGIN, lambda ev, uid=u["id"]: self.entrar_como(uid),
                                   MORADO))
            tarjetas.append(caja(*filas))
        self.render("Usuarios", buscar, tipo, boton("Buscar", ft.Icons.SEARCH, aplicar),
                    *(tarjetas or [caja(linea(ft.Icons.INFO, "No hay cuentas con esos datos."))]),
                    volver=self.inicio)

    @vista
    def usuario_detalle(self, uid, e=None):
        yo = self.user["id"]
        u = db.obtener_usuario(uid)
        if not u:
            self.usuarios_lista()
            return
        specs = campos_de(u["rol"])
        controles, leer = self.formulario(specs, u)
        email = campo("Correo electrónico", value=u["email"], prefix_icon=ft.Icons.EMAIL)
        rol = desplegable("Tipo de cuenta", list(ROLES_NOMBRE.items()), u["rol"])
        err = txt("", 18, color=ROJO)
        activo = bool(u.get("activo", 1))
        prom, n = db.promedio(uid)

        def guardar(ev):
            datos = leer()
            msg = self.revisar(specs, datos, estricto=False)
            if msg:
                err.value = msg
                self.page.update()
                return
            ok, m = db.editar_usuario(yo, uid, datos, email.value or "", rol.value)
            if ok:
                self.usuario_detalle(uid)
                self.aviso(m)
            else:
                err.value = m
                self.page.update()

        def cambiar_estado_cuenta():
            _, m = db.cambiar_activo(yo, uid, not activo)
            self.usuario_detalle(uid)
            self.aviso(m)

        def restablecer():
            ok, res = db.resetear_clave(yo, uid)
            if not ok:
                self.alerta("No se pudo restablecer", res)
                return
            self.dialogo("Contraseña temporal", txt("Entréguesela a la persona. Al ingresar tendrá que crear una "
                                                    "nueva. No se volverá a mostrar.", 18),
                         ft.Text(res, size=sz(36), weight=ft.FontWeight.BOLD, color=MORADO, selectable=True),
                         boton("Entendido", ft.Icons.CHECK, self.cerrar), icono=ft.Icons.LOCK_RESET, color=MORADO)

        estado_txt = [linea(ft.Icons.VERIFIED_USER, "Aceptó los términos: " + (u["consentimiento_fecha"] or "todavía no")),
                      linea(ft.Icons.FACT_CHECK, "Registro inicial completo: " + ("sí" if u["onboarding_completo"] else "no"))]
        if u["rol"] in db.ROLES_PUBLICOS:
            estado_txt.append(linea(ft.Icons.STAR, f"Calificación: {prom} de 5 ({n_calif(n)})" if prom is not None
                                    else "Sin calificaciones", icono_color=AMBAR))
        cabecera = caja(ft.Row([avatar(db.foto_de(u["id"]), u["nombre"], sz(56)),
                                ft.Column([txt(u["nombre"], 22, True), txt(ROLES_NOMBRE.get(u["rol"], u["rol"]), 18),
                                           txt(u["email"], 17, color=GRIS)], spacing=2, expand=True)], spacing=12),
                        *estado_txt)
        acciones = []
        if uid != yo:
            if u["rol"] != "superadmin":
                acciones.append(boton("Entrar a su cuenta", ft.Icons.LOGIN, lambda ev: self.entrar_como(uid), MORADO))
            acciones.append(boton("Restablecer contraseña", ft.Icons.LOCK_RESET, lambda ev: self.confirmar(
                "¿Restablecer la contraseña?", "Se creará una contraseña temporal. La anterior dejará de servir.",
                "Sí, restablecer", restablecer, MORADO, ft.Icons.LOCK_RESET)))
            acciones.append(boton("Reactivar cuenta" if not activo else "Suspender cuenta",
                                  ft.Icons.CHECK_CIRCLE if not activo else ft.Icons.BLOCK,
                                  lambda ev: self.confirmar(
                                      "¿Reactivar esta cuenta?" if not activo else "¿Suspender esta cuenta?",
                                      "La persona podrá volver a ingresar." if not activo else
                                      "La persona no podrá ingresar hasta que usted la reactive.",
                                      "Sí, reactivar" if not activo else "Sí, suspender", cambiar_estado_cuenta,
                                      VERDE if not activo else ROJO),
                                  VERDE if not activo else ROJO))
        vinculos = []
        if u["rol"] == "familiar":
            ad = db.adultos_de(uid)
            vinculos.append(txt(f"Adultos mayores a su cargo ({len(ad)} de {db.MAX_VINCULOS})", 20, True))
            for a in ad:
                vinculos += [linea(ft.Icons.PERSON, a["nombre"]),
                             boton_borde(f"Quitar a {a['nombre'].split()[0]}", ft.Icons.PERSON_REMOVE,
                                         lambda ev, a=a: self.confirmar(
                                             "¿Quitar este vínculo?", f"Se quitará el vínculo con {a['nombre']}.",
                                             "Sí, quitar", lambda: (db.desvincular_admin(yo, uid, a["id"]),
                                                                    self.usuario_detalle(uid))), ROJO)]
            if len(ad) < db.MAX_VINCULOS:
                ya = {a["id"] for a in ad}
                libres = [x for x in db.listar_usuarios(yo, "", "adulto_mayor") if x["id"] not in ya]
                dd = desplegable("Vincular a un adulto mayor", [(str(x["id"]), x["nombre"]) for x in libres])

                def vincular_a(ev, dd=dd):
                    if not dd.value:
                        self.aviso("Elija un adulto mayor.")
                        return
                    ok, m = db.vincular_admin(yo, uid, int(dd.value))
                    self.usuario_detalle(uid)
                    self.aviso(m)

                vinculos += [dd, boton("Vincular", ft.Icons.LINK, vincular_a, MORADO)]
        elif u["rol"] == "adulto_mayor":
            fam = db.familiares_de(uid)
            vinculos.append(txt(f"Código de familia: {u.get('codigo') or '—'}", 20, True))
            for f_ in fam:
                vinculos += [linea(ft.Icons.FAMILY_RESTROOM, f_["nombre"]),
                             boton_borde(f"Quitar a {f_['nombre'].split()[0]}", ft.Icons.PERSON_REMOVE,
                                         lambda ev, f_=f_: self.confirmar(
                                             "¿Quitar este vínculo?", f"Se quitará el vínculo con {f_['nombre']}.",
                                             "Sí, quitar", lambda: (db.desvincular_admin(yo, f_["id"], uid),
                                                                    self.usuario_detalle(uid))), ROJO)]
            if not fam:
                vinculos.append(txt("Sin familiares vinculados.", 18))
        datos = []
        if u["rol"] in db.ROLES_PUBLICOS:
            i = 0
            for p in pasos_de(u["rol"]):
                datos.append(txt(p["titulo"], 22, True))
                datos += controles[i:i + len(p["campos"])]
                i += len(p["campos"])
        else:
            datos = [txt("Datos", 22, True)] + controles
        self.render(f"Cuenta de {u['nombre'].split()[0]}", cabecera, *acciones,
                    *([caja(*vinculos)] if vinculos else []), txt("Datos de la cuenta", 24, True), email, rol,
                    *datos, err, boton("Guardar cambios", ft.Icons.SAVE, guardar, VERDE), volver=self.usuarios_lista)

    @vista
    def auditoria(self, e=None):
        filas = db.ultimas_auditorias(self.user["id"])
        tarjetas = [caja(txt(a["accion"].replace("_", " ").capitalize(), 20, True), txt(a["fecha"], 17, color=GRIS),
                         linea(ft.Icons.PERSON, f"Lo hizo: {a['actor'] or '—'}"),
                         linea(ft.Icons.ARROW_FORWARD, f"Sobre: {a['objetivo'] or '—'}"),
                         *([txt(a["detalle"], 17)] if a["detalle"] else [])) for a in filas]
        self.render("Registro de actividad",
                    txt("Las últimas 100 acciones del super administrador.", 19),
                    *(tarjetas or [caja(linea(ft.Icons.INFO, "Todavía no hay actividad registrada."))]),
                    volver=self.inicio)

    def editar_cita(self, s):
        acomps = db.acompanantes()
        estado = desplegable("Estado", [(x, x) for x in db.ESTADOS], s["estado"])
        acomp = desplegable("Acompañante", [("0", "Ninguno")] + [(str(a["id"]), a["nombre"]) for a in acomps],
                            str(s["acompanante_id"] or 0))
        err = txt("", 18, color=ROJO)

        def guardar(ev):
            elegido = int(acomp.value) if acomp.value and acomp.value != "0" else None
            ok, msg = db.editar_solicitud_admin(self.user["id"], s["id"], estado.value, elegido)
            if ok:
                self.cerrar()
                self.admin()
                self.aviso(msg)
            else:
                err.value = msg
                self.page.update()

        self.dialogo("Corregir cita", txt(f"{s['tipo']} · {fecha_bonita(s['fecha'])}, {hora_bonita(s['hora'])}", 18),
                     estado, acomp, err, boton("Guardar", ft.Icons.SAVE, guardar, VERDE),
                     boton("Cancelar", ft.Icons.CLOSE, self.cerrar, GRIS), icono=ft.Icons.EDIT, color=MORADO)

    # ---------- Registro / acceso con Google ----------
    def google(self, e=None):
        self.aviso("Se abrirá su navegador para iniciar sesión con Google…")
        threading.Thread(target=self._google_hilo, daemon=True).start()

    def _google_hilo(self):
        try:
            email, nombre = google_auth.iniciar_sesion_google()
        except Exception as ex:
            self.aviso(f"No se pudo iniciar con Google: {ex}")
            return
        u = db.usuario_por_email(email)
        if u:
            self.entrar(u)
        else:
            self.elegir_rol_google(email, nombre)

    def elegir_rol_google(self, email, nombre):
        rol = desplegable("¿Quién es usted?", list(ROLES.items()), "adulto_mayor")

        def crear(ev):
            db.registrar_google(nombre, email, rol.value)
            self.entrar(db.usuario_por_email(email))

        self.render("Casi listo", txt(f"Hola, {nombre or email}", 26, True, AZUL),
                    txt(f"Cuenta de Google verificada: {email}", 18), rol,
                    boton("Crear mi cuenta", ft.Icons.CHECK_CIRCLE, crear, VERDE), volver=self.login)