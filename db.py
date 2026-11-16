import base64
import hashlib
import hmac
import io
import os
import re
import secrets
import sqlite3
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal



def _cargar_env():
    """Lee el archivo .env (junto a este archivo) sin necesitar librerías extra. No pisa variables ya definidas."""
    ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(ruta):
        return
    with open(ruta, encoding="utf-8-sig") as f:
        for linea in f:
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            k, v = linea.split("=", 1)
            k = k.strip().removeprefix("export ").strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


_cargar_env()

# Con DATABASE_URL (la cadena de conexión de Supabase) la app usa la base de datos en la nube.
# Sin ella, usa el archivo local acompana.db, como hasta ahora.
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USAR_PG = bool(DATABASE_URL)
if USAR_PG:
    try:
        import psycopg
    except ImportError:
        raise RuntimeError('Falta instalar el conector de PostgreSQL: pip install "psycopg[binary]" psycopg_pool') from None
    ERROR_INTEGRIDAD = psycopg.IntegrityError
else:
    ERROR_INTEGRIDAD = sqlite3.IntegrityError
COMO = "ILIKE" if USAR_PG else "LIKE"  # búsqueda sin distinguir mayúsculas

ZONA_HORARIA_HORAS = -5  # Colombia (UTC-5, sin horario de verano): así la hora no depende de dónde corra la app


def ahora_local():
    return (datetime.now(timezone.utc) + timedelta(hours=ZONA_HORARIA_HORAS)).replace(tzinfo=None)


def hoy_local():
    return ahora_local().date()


DB_FILE = "acompana.db"
FOTO_MAX_BYTES = 8 * 1024 * 1024  # imagen original: máximo 8 MB (luego se reduce a ~30 KB)
DURACION_MIN = 60         # minutos que "ocupa" un servicio al buscar cruces de horario
MARGEN_INICIO_MIN = 15    # el acompañante solo puede iniciar de 15 min antes a 15 min después de la hora
MAX_VINCULOS = 3          # adultos mayores que puede tener a cargo un familiar o cuidador
VERSION_TERMINOS = "1.0"  # si cambia el texto de los términos, súbela y se volverán a pedir

# Cuentas de administración. Su contraseña inicial sale del .env (SUPERADMIN_CLAVE, ADMIN_CLAVE) o se genera
# al azar y se muestra una sola vez en la terminal. En ambos casos la app obliga a cambiarla al primer ingreso.
EMAIL_SUPER = (os.environ.get("SUPERADMIN_EMAIL") or "superadmin@acompana.com").strip().lower()
EMAIL_ADMIN = (os.environ.get("ADMIN_EMAIL") or "admin@acompana.com").strip().lower()

# Transiciones válidas de estado (RF-11)
PERMITIDAS = {
    "Solicitada": ["Asignada", "Cancelada"],
    "Asignada": ["En curso", "Cancelada"],
    "En curso": ["Finalizada"],
}
ESTADOS = ["Solicitada", "Asignada", "En curso", "Finalizada", "Cancelada"]
ROLES_PUBLICOS = ("adulto_mayor", "familiar", "acompanante")
ROLES_ADMIN = ("administrador", "superadmin")
ROLES_TODOS = ROLES_PUBLICOS + ROLES_ADMIN

# Correo válido: algo@dominio.ext  (debe tener @ y al menos un punto después)
EMAIL_RE = re.compile(r"^[\w.+-]+@([A-Za-z0-9-]+\.)+[A-Za-z]{2,}$")
MSG_CORREO = "Por favor escriba un correo válido con @ y punto ( . ), por ejemplo: nombre@gmail.com"

# Datos personales que se pueden pedir y editar (cada uno es una columna de la tabla usuarios)
COLUMNAS_PERFIL = [
    "nombre", "tipo_doc", "num_doc", "fecha_nac", "genero",
    "telefono", "direccion", "barrio", "ciudad",
    "contacto_nombre", "contacto_parentesco", "contacto_tel",
    "eps", "salud_condiciones", "salud_medicamentos", "salud_alergias", "movilidad",
    "parentesco_familiar", "formacion", "experiencia", "zona", "disponibilidad",
]
COLUMNAS_NUEVAS = {
    "usuarios": {
        **{c: "TEXT DEFAULT ''" for c in COLUMNAS_PERFIL if c != "nombre"},
        "foto": "TEXT DEFAULT ''", "codigo": "TEXT DEFAULT ''",
        "consentimiento_fecha": "TEXT DEFAULT ''", "consentimiento_version": "TEXT DEFAULT ''",
        "escala": "INTEGER DEFAULT 0", "onboarding_completo": "INTEGER DEFAULT 0",
        "activo": "INTEGER DEFAULT 1", "debe_cambiar_clave": "INTEGER DEFAULT 0",
    },
    "solicitudes": {"creado_por": "INTEGER"},
}

BASE_SQL = """
SELECT s.*, u.nombre AS solicitante, u.telefono AS tel_solicitante,
       a.nombre AS acompanante, a.telefono AS tel_acompanante,
       c.nombre AS creador,
       (SELECT ROUND(AVG(puntaje), 1) FROM calificaciones WHERE a_id = a.id) AS prom_acompanante,
       (SELECT ROUND(AVG(puntaje), 1) FROM calificaciones WHERE a_id = u.id) AS prom_solicitante,
       (SELECT puntaje FROM calificaciones WHERE solicitud_id = s.id AND lado = 'cliente') AS puntaje_a_acompanante,
       (SELECT puntaje FROM calificaciones WHERE solicitud_id = s.id AND lado = 'acompanante') AS puntaje_a_usuario
FROM solicitudes s
JOIN usuarios u ON u.id = s.usuario_id
LEFT JOIN usuarios a ON a.id = s.acompanante_id
LEFT JOIN usuarios c ON c.id = s.creado_por
"""
# Solicitudes que un usuario puede ver: las suyas y las de los adultos mayores que tiene vinculados
VISIBLES = ("(s.usuario_id=? OR s.usuario_id IN "
            "(SELECT adulto_id FROM vinculos WHERE familiar_id=?))")


_POOL = None


def _pool():
    global _POOL
    if _POOL is None:
        import psycopg_pool
        from psycopg.rows import dict_row
        url = DATABASE_URL
        if "sslmode=" not in url:
            url += ("&" if "?" in url else "?") + "sslmode=require"
        _POOL = psycopg_pool.ConnectionPool(
            url, min_size=1, max_size=5, timeout=20, open=False,
            kwargs={"row_factory": dict_row, "prepare_threshold": None})  # compatible con el pooler de Supabase
        _POOL.open(wait=True, timeout=20)
    return _POOL


def _con():
    c = sqlite3.connect(DB_FILE)
    c.row_factory = sqlite3.Row
    return c


def _a_pg(sql):
    return sql.replace("?", "%s")  # el código escribe ? como marcador; PostgreSQL usa %s


def _consultar(sql, args=()):
    if USAR_PG:
        with _pool().connection() as c:
            cur = c.execute(_a_pg(sql), list(args))
            filas = cur.fetchall() if cur.description else []
        return [{k: (float(v) if isinstance(v, Decimal) else v) for k, v in f.items()} for f in filas]
    with _con() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def _ejecutar(sql, args=()):
    """Ejecuta una instrucción. En INSERT devuelve el id de la fila nueva."""
    if USAR_PG:
        q = _a_pg(sql)
        if re.match(r"\s*INSERT INTO (usuarios|solicitudes|calificaciones|auditoria)\b", q, re.I):
            q += " RETURNING id"
        with _pool().connection() as c:
            cur = c.execute(q, list(args))
            fila = cur.fetchone() if cur.description else None
        return fila.get("id") if fila else None
    with _con() as c:
        return c.execute(sql, args).lastrowid


# ---------- Validaciones ----------
def email_valido(email):
    return bool(EMAIL_RE.match((email or "").strip()))


def solo_digitos(t):
    return re.sub(r"\D", "", t or "")


def telefono_valido(t):
    t = (t or "").strip()
    return bool(re.fullmatch(r"[\d\s+\-()]+", t)) and 7 <= len(solo_digitos(t)) <= 15


def doc_valido(tipo, num):
    num = (num or "").strip()
    if tipo in ("Pasaporte", "Otro documento"):
        return bool(re.fullmatch(r"[A-Za-z0-9]{5,20}", num))
    return bool(re.fullmatch(r"\d{5,15}", num))


def edad_de(iso):
    """Edad en años a partir de 'AAAA-MM-DD', o None si la fecha no es válida."""
    try:
        n = date.fromisoformat(iso)
    except (TypeError, ValueError):
        return None
    hoy = hoy_local()
    return hoy.year - n.year - ((hoy.month, hoy.day) < (n.month, n.day))


def validar_formatos(datos):
    """Devuelve un mensaje de error si algún dato tiene mal el formato, o None si todo está bien."""
    for k in ("telefono", "contacto_tel"):
        if datos.get(k) and not telefono_valido(datos[k]):
            return "Revise el teléfono: solo números, entre 7 y 15 dígitos."
    if datos.get("num_doc") and not doc_valido(datos.get("tipo_doc"), datos["num_doc"]):
        return "Revise el número de documento: sin puntos ni espacios (pasaporte: letras y números)."
    if datos.get("fecha_nac"):
        e = edad_de(datos["fecha_nac"])
        if e is None:
            return "Revise la fecha de nacimiento: elija día, mes y año."
        if e < 18 or e > 120:
            return "La fecha de nacimiento no es válida: debe ser mayor de edad."
    return None


# ---------- Claves y creación de usuarios ----------
def _hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 100_000).hex()


def _clave(password):
    salt = secrets.token_hex(16)
    return _hash(password, salt), salt


def _codigo_nuevo():
    while True:
        cod = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6))
        if not _consultar("SELECT 1 FROM usuarios WHERE codigo=?", (cod,)):
            return cod


def _crear_usuario(nombre, email, pw_hash, salt, rol):
    codigo = _codigo_nuevo() if rol == "adulto_mayor" else ""
    return _ejecutar(
        "INSERT INTO usuarios(nombre,email,pw_hash,salt,rol,codigo) VALUES(?,?,?,?,?,?)",
        (nombre, email, pw_hash, salt, rol, codigo),
    )


TABLAS = ["usuarios", "solicitudes", "vinculos", "calificaciones", "auditoria"]


def _esquema():
    pk = "SERIAL PRIMARY KEY" if USAR_PG else "INTEGER PRIMARY KEY AUTOINCREMENT"
    return [
        f"CREATE TABLE IF NOT EXISTS usuarios(id {pk}, nombre TEXT NOT NULL, email TEXT NOT NULL UNIQUE, "
        "pw_hash TEXT NOT NULL, salt TEXT NOT NULL, rol TEXT NOT NULL)",
        f"CREATE TABLE IF NOT EXISTS solicitudes(id {pk}, usuario_id INTEGER NOT NULL, tipo TEXT NOT NULL, "
        "fecha TEXT NOT NULL, hora TEXT NOT NULL, origen TEXT NOT NULL, destino TEXT NOT NULL, "
        "observaciones TEXT DEFAULT '', estado TEXT NOT NULL DEFAULT 'Solicitada', acompanante_id INTEGER, "
        "obs_final TEXT DEFAULT '')",
        "CREATE TABLE IF NOT EXISTS vinculos(familiar_id INTEGER NOT NULL, adulto_id INTEGER NOT NULL, "
        "PRIMARY KEY (familiar_id, adulto_id))",
        f"CREATE TABLE IF NOT EXISTS calificaciones(id {pk}, solicitud_id INTEGER NOT NULL, lado TEXT NOT NULL, "
        "de_id INTEGER NOT NULL, a_id INTEGER NOT NULL, puntaje INTEGER NOT NULL CHECK (puntaje BETWEEN 0 AND 5), "
        "UNIQUE (solicitud_id, lado))",
        f"CREATE TABLE IF NOT EXISTS auditoria(id {pk}, fecha TEXT NOT NULL, actor_id INTEGER NOT NULL, "
        "accion TEXT NOT NULL, objetivo_id INTEGER, detalle TEXT DEFAULT '')",
    ]


def _columnas(tabla):
    if USAR_PG:
        filas = _consultar("SELECT column_name AS name FROM information_schema.columns "
                           "WHERE table_schema='public' AND table_name=?", (tabla,))
    else:
        filas = _consultar(f"PRAGMA table_info({tabla})")
    return {f["name"] for f in filas}


def _crear_cuenta_admin(nombre, email, rol, variable_clave):
    clave = os.environ.get(variable_clave, "").strip()
    generada = not clave
    if generada:
        clave = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789") for _ in range(12))
    h, s = _clave(clave)
    try:
        uid = _crear_usuario(nombre, email, h, s, rol)
    except ERROR_INTEGRIDAD:
        return
    _ejecutar("UPDATE usuarios SET debe_cambiar_clave=1 WHERE id=?", (uid,))
    if generada:
        print(f"\n=== Cuenta creada: {nombre} ===\n    Correo: {email}\n    Contraseña inicial: {clave}\n"
              "    Anótela ahora: no se vuelve a mostrar. Se le pedirá cambiarla al ingresar.\n")


def crear_esquema():
    """Crea las tablas y columnas que falten (y activa el candado RLS en la nube). No crea cuentas."""
    try:
        for sentencia in _esquema():
            _ejecutar(sentencia)
        # Agrega las columnas que falten (sirve para bases nuevas y para las creadas con versiones anteriores)
        for tabla, columnas in COLUMNAS_NUEVAS.items():
            existentes = _columnas(tabla)
            for nombre, tipo in columnas.items():
                if nombre not in existentes:
                    _ejecutar(f"ALTER TABLE {tabla} ADD COLUMN {nombre} {tipo}")
        if USAR_PG:  # candado: la API pública de Supabase no puede leer ni escribir estas tablas
            for t in TABLAS:
                _ejecutar(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
    except Exception as ex:
        if USAR_PG and isinstance(ex, psycopg.OperationalError):
            raise RuntimeError("No se pudo conectar con la base de datos en la nube. Revise la línea DATABASE_URL "
                               "del archivo .env (usuario, contraseña y servidor) y que el proyecto de Supabase "
                               "esté activo (los gratuitos se pausan tras una semana sin uso).") from None
        raise


def init_db():
    crear_esquema()
    _ejecutar("UPDATE solicitudes SET creado_por=usuario_id WHERE creado_por IS NULL")
    for u in _consultar("SELECT id FROM usuarios WHERE rol='adulto_mayor' AND (codigo IS NULL OR codigo='')"):
        _ejecutar("UPDATE usuarios SET codigo=? WHERE id=?", (_codigo_nuevo(), u["id"]))
    if not _consultar("SELECT id FROM usuarios WHERE rol='administrador'"):
        _crear_cuenta_admin("Administrador", EMAIL_ADMIN, "administrador", "ADMIN_CLAVE")
    if not _consultar("SELECT id FROM usuarios WHERE rol='superadmin'"):
        _crear_cuenta_admin("Super administrador", EMAIL_SUPER, "superadmin", "SUPERADMIN_CLAVE")
    _ejecutar("UPDATE usuarios SET onboarding_completo=1 WHERE rol IN ('administrador','superadmin')")


# ---------- Usuarios (RF-01, RF-02, RF-03) ----------
def _publico(u):
    p = {k: v for k, v in u.items() if k not in ("pw_hash", "salt")}
    p["es_google"] = u.get("pw_hash") == "GOOGLE"
    return p


def registrar(nombre, email, password, rol):
    nombre, email = (nombre or "").strip(), (email or "").strip().lower()
    if len(nombre) < 3:
        return False, "Escriba su nombre completo."
    if not email_valido(email):
        return False, MSG_CORREO
    if len(password or "") < 6:
        return False, "La contraseña debe tener mínimo 6 caracteres."
    if rol not in ROLES_PUBLICOS:
        return False, "Elija quién es usted."
    h, s = _clave(password)
    try:
        _crear_usuario(nombre, email, h, s, rol)
    except ERROR_INTEGRIDAD:
        return False, "Ese correo ya está registrado."
    return True, "Cuenta creada. Ya puede iniciar sesión."


def registrar_google(nombre, email, rol):
    if rol not in ROLES_PUBLICOS:
        rol = "adulto_mayor"
    email = email.strip().lower()
    _crear_usuario((nombre or "").strip() or email, email, "GOOGLE", "00", rol)


def login(email, password):
    r = _consultar("SELECT * FROM usuarios WHERE email=?", ((email or "").strip().lower(),))
    if r and hmac.compare_digest(_hash(password or "", r[0]["salt"]), r[0]["pw_hash"]):
        return _publico(r[0])
    return None


def obtener_usuario(uid):
    r = _consultar("SELECT * FROM usuarios WHERE id=?", (uid,))
    return _publico(r[0]) if r else None


def usuario_por_email(email):
    r = _consultar("SELECT * FROM usuarios WHERE email=?", (email.strip().lower(),))
    return _publico(r[0]) if r else None


def acompanantes():
    return _consultar("SELECT id, nombre FROM usuarios WHERE rol='acompanante' AND activo=1 ORDER BY nombre")


def cambiar_clave(uid, nueva, actual=None):
    """Si se pasa 'actual', la comprueba (cambio voluntario). Sin 'actual' es el cambio obligatorio del primer ingreso."""
    r = _consultar("SELECT pw_hash, salt FROM usuarios WHERE id=?", (uid,))
    if not r:
        return False, "No se encontró la cuenta."
    if len(nueva or "") < 6:
        return False, "La contraseña nueva debe tener mínimo 6 caracteres."
    if actual is not None and not hmac.compare_digest(_hash(actual, r[0]["salt"]), r[0]["pw_hash"]):
        return False, "La contraseña actual no es correcta."
    h, s = _clave(nueva)
    _ejecutar("UPDATE usuarios SET pw_hash=?, salt=?, debe_cambiar_clave=0 WHERE id=?", (h, s, uid))
    return True, "Contraseña cambiada."


# ---------- Datos personales, consentimiento y registro en pasos ----------
def guardar_datos(uid, datos):
    datos = {k: (v or "").strip() for k, v in datos.items() if k in COLUMNAS_PERFIL}
    if "nombre" in datos and len(datos["nombre"]) < 3:
        return False, "Escriba su nombre completo."
    err = validar_formatos(datos)
    if err:
        return False, err
    if datos:  # los nombres de columna salen de la lista COLUMNAS_PERFIL, nunca del usuario
        _ejecutar(f"UPDATE usuarios SET {', '.join(k + '=?' for k in datos)} WHERE id=?", (*datos.values(), uid))
    return True, "Datos guardados."


def aceptar_terminos(uid):
    _ejecutar("UPDATE usuarios SET consentimiento_fecha=?, consentimiento_version=? WHERE id=?",
              (ahora_local().strftime("%Y-%m-%d %H:%M:%S"), VERSION_TERMINOS, uid))


def terminos_aceptados(u):
    return u.get("consentimiento_version") == VERSION_TERMINOS


def completar_onboarding(uid):
    _ejecutar("UPDATE usuarios SET onboarding_completo=1 WHERE id=?", (uid,))


def guardar_escala(uid, nivel):
    _ejecutar("UPDATE usuarios SET escala=? WHERE id=?", (nivel, uid))


def _foto_base64(origen):
    """Devuelve (base64, None) con la imagen reducida a 300 px (JPEG), o (None, motivo del error)."""
    if os.path.splitext(origen)[1].lower() not in (".png", ".jpg", ".jpeg"):
        return None, "Elija una imagen PNG o JPG."
    if os.path.getsize(origen) > FOTO_MAX_BYTES:
        return None, "La imagen pesa mucho (máximo 8 MB)."
    try:
        from PIL import Image
    except ImportError:
        return None, "Falta instalar Pillow: pip install pillow"
    try:
        with Image.open(origen) as img:
            img = img.convert("RGB")
            img.thumbnail((300, 300))
            salida = io.BytesIO()
            img.save(salida, "JPEG", quality=85)
    except Exception:
        return None, "No se pudo leer la imagen. Pruebe con otra."
    return base64.b64encode(salida.getvalue()).decode(), None


def guardar_foto(uid, origen):
    """Guarda la foto dentro de la base de datos, para que viaje con la cuenta."""
    b64, error = _foto_base64(origen)
    if error:
        return False, error
    _ejecutar("UPDATE usuarios SET foto=? WHERE id=?", (b64, uid))
    return True, "Foto actualizada."


def leer_foto(valor):
    """La columna 'foto' guarda la imagen en base64 (o, en cuentas antiguas, la ruta de un archivo local)."""
    if not valor:
        return None
    if len(valor) < 500 and os.path.exists(valor):
        with open(valor, "rb") as f:
            return f.read()
    try:
        return base64.b64decode(valor, validate=True)
    except Exception:
        return None


# ---------- Familiar <-> adultos mayores (hasta MAX_VINCULOS) ----------
def adultos_de(familiar_id):
    return _consultar(
        "SELECT u.id, u.nombre FROM vinculos v JOIN usuarios u ON u.id=v.adulto_id "
        "WHERE v.familiar_id=? ORDER BY u.nombre", (familiar_id,))


def familiares_de(adulto_id):
    return _consultar(
        "SELECT u.id, u.nombre FROM vinculos v JOIN usuarios u ON u.id=v.familiar_id "
        "WHERE v.adulto_id=? ORDER BY u.nombre", (adulto_id,))


def _unir(familiar_id, adulto_id, nombre_adulto):
    previos = adultos_de(familiar_id)
    if any(p["id"] == adulto_id for p in previos):
        return False, f"Ya está vinculado con {nombre_adulto}."
    if len(previos) >= MAX_VINCULOS:
        return False, (f"Ya tiene {MAX_VINCULOS} adultos mayores vinculados, que es el máximo permitido. "
                       "Para vincular a otro, primero quite uno de sus vínculos.")
    _ejecutar("INSERT INTO vinculos(familiar_id, adulto_id) VALUES(?,?)", (familiar_id, adulto_id))
    return True, f"Listo: ahora está vinculado con {nombre_adulto}."


def vincular(familiar_id, codigo):
    f = obtener_usuario(familiar_id)
    if not f or f["rol"] != "familiar":
        return False, "Solo las cuentas de familiar o cuidador pueden vincularse."
    codigo = (codigo or "").strip().upper()
    a = _consultar("SELECT id, nombre FROM usuarios WHERE codigo=? AND rol='adulto_mayor' AND activo=1", (codigo,))
    if not codigo or not a:
        return False, "No encontramos ese código. Pídaselo de nuevo al adulto mayor."
    return _unir(familiar_id, a[0]["id"], a[0]["nombre"])


def desvincular(familiar_id, adulto_id):
    _ejecutar("DELETE FROM vinculos WHERE familiar_id=? AND adulto_id=?", (familiar_id, adulto_id))
    return True


# ---------- Solicitudes (RF-04 a RF-12) ----------
def _h12(hhmm):
    h, m = map(int, hhmm.split(":"))
    return f"{h % 12 or 12}:{m:02d} {'a. m.' if h < 12 else 'p. m.'}"


def _minutos(fecha, hora):
    return int(datetime.strptime(f"{fecha} {hora}", "%Y-%m-%d %H:%M").timestamp() // 60)


def _cruce_adulto(adulto_id, fecha, hora):
    """Cita activa del mismo adulto mayor que se cruza con la fecha y hora pedidas (o None)."""
    t = _minutos(fecha, hora)
    for o in _consultar("SELECT tipo, hora FROM solicitudes WHERE usuario_id=? AND fecha=? "
                        "AND estado IN ('Solicitada','Asignada','En curso')", (adulto_id, fecha)):
        if abs(_minutos(fecha, o["hora"]) - t) < DURACION_MIN:
            return o
    return None


def crear_solicitud(creador_id, beneficiario_id, tipo, fecha, hora, origen, destino, obs):
    """Devuelve (id, mensaje). Si no se pudo guardar, id es None y el mensaje explica por qué."""
    if beneficiario_id != creador_id and not _consultar(
            "SELECT 1 FROM vinculos WHERE familiar_id=? AND adulto_id=?", (creador_id, beneficiario_id)):
        return None, "No tiene permiso para pedir citas por esta persona."
    c = _cruce_adulto(beneficiario_id, fecha, hora)
    if c:
        return None, (f"Ya existe una cita ({c['tipo']}) a las {_h12(c['hora'])} ese mismo día. "
                      f"Cada cita ocupa {DURACION_MIN} minutos. Elija otra hora o cancele la anterior.")
    nuevo = _ejecutar(
        "INSERT INTO solicitudes(usuario_id,creado_por,tipo,fecha,hora,origen,destino,observaciones)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (beneficiario_id, creador_id, tipo, fecha, hora, origen.strip(), destino.strip(), obs.strip()),
    )
    return nuevo, "Solicitud guardada."


def solicitudes_de(uid, historial=False):
    cond = "IN ('Finalizada','Cancelada')" if historial else "NOT IN ('Finalizada','Cancelada')"
    return _consultar(
        f"{BASE_SQL} WHERE {VISIBLES} AND s.estado {cond} ORDER BY s.fecha DESC, s.hora DESC",
        (uid, uid))


def todas():
    return _consultar(f"{BASE_SQL} ORDER BY s.id DESC")


def servicios_de(acomp_id):
    return _consultar(f"{BASE_SQL} WHERE s.acompanante_id=? ORDER BY s.fecha, s.hora", (acomp_id,))


def cambiar_estado(sid, nuevo, obs_final=None):
    r = _consultar("SELECT estado FROM solicitudes WHERE id=?", (sid,))
    if not r or nuevo not in PERMITIDAS.get(r[0]["estado"], []):
        return False
    if obs_final is not None:
        _ejecutar("UPDATE solicitudes SET estado=?, obs_final=? WHERE id=?", (nuevo, obs_final, sid))
    else:
        _ejecutar("UPDATE solicitudes SET estado=? WHERE id=?", (nuevo, sid))
    return True


def cancelar(sid, uid):
    permitido = _consultar(f"SELECT 1 FROM solicitudes s WHERE s.id=? AND {VISIBLES}", (sid, uid, uid))
    return bool(permitido) and cambiar_estado(sid, "Cancelada")


# ---------- Inicio del servicio: solo en su hora, con margen de MARGEN_INICIO_MIN ----------
def ventana_inicio(fecha, hora):
    """(desde, hasta) como datetime: la hora de la cita menos y más el margen."""
    t = datetime.strptime(f"{fecha} {hora}", "%Y-%m-%d %H:%M")
    m = timedelta(minutes=MARGEN_INICIO_MIN)
    return t - m, t + m


def iniciar_servicio(sid, acomp_id, ahora=None):
    r = _consultar("SELECT fecha, hora, estado, acompanante_id FROM solicitudes WHERE id=?", (sid,))
    if not r or r[0]["acompanante_id"] != acomp_id:
        return False, "Este servicio no está asignado a usted."
    s = r[0]
    if s["estado"] != "Asignada":
        return False, "Este servicio ya no se puede iniciar."
    desde, hasta = ventana_inicio(s["fecha"], s["hora"])
    ahora = ahora or ahora_local()
    hora_desde, hora_hasta = _h12(desde.strftime("%H:%M")), _h12(hasta.strftime("%H:%M"))
    if ahora < desde:
        return False, (f"Todavía no es la hora. Podrá iniciar este servicio el {desde.strftime('%d/%m/%Y')} "
                       f"entre las {hora_desde} y las {hora_hasta}")
    if ahora > hasta:
        return False, (f"El tiempo para iniciar este servicio terminó a las {hora_hasta} "
                       "Comuníquese con el administrador.")
    cambiar_estado(sid, "En curso")
    return True, "Servicio en curso."


# ---------- Asignación sin cruces de horario ----------
def conflicto(acomp_id, sid):
    """Devuelve el servicio del acompañante que se cruza con la solicitud sid (o None)."""
    r = _consultar("SELECT fecha, hora FROM solicitudes WHERE id=?", (sid,))
    if not r:
        return None
    t = _minutos(r[0]["fecha"], r[0]["hora"])
    otros = _consultar(
        "SELECT tipo, fecha, hora FROM solicitudes WHERE acompanante_id=? AND id<>? AND fecha=? "
        "AND estado IN ('Asignada','En curso')", (acomp_id, sid, r[0]["fecha"]))
    for o in otros:
        if abs(_minutos(o["fecha"], o["hora"]) - t) < DURACION_MIN:
            return o
    return None


def _msg_cruce(c):
    return (f"Ese acompañante ya tiene un servicio ({c['tipo']}) a las {_h12(c['hora'])} "
            f"ese mismo día. Cada servicio ocupa {DURACION_MIN} minutos. "
            "Elija otro acompañante u otro horario.")


def asignar(sid, acomp_id):
    r = _consultar("SELECT estado FROM solicitudes WHERE id=?", (sid,))
    if not r or r[0]["estado"] != "Solicitada":
        return False, "Esta solicitud ya no se puede asignar."
    c = conflicto(acomp_id, sid)
    if c:
        return False, _msg_cruce(c)
    if cambiar_estado(sid, "Asignada"):
        _ejecutar("UPDATE solicitudes SET acompanante_id=? WHERE id=?", (acomp_id, sid))
        return True, "Acompañante asignado."
    return False, "Esta solicitud ya no se puede asignar."


# ---------- Calificaciones (de 0 a 5 estrellas, en los dos sentidos) ----------
def calificar(sid, de_id, puntaje):
    """El acompañante califica al adulto mayor; el adulto mayor o su familiar vinculado califican al acompañante."""
    try:
        puntaje = int(puntaje)
    except (TypeError, ValueError):
        return False, "Elija de 0 a 5 estrellas."
    if not 0 <= puntaje <= 5:
        return False, "Elija de 0 a 5 estrellas."
    r = _consultar("SELECT usuario_id, acompanante_id, estado FROM solicitudes WHERE id=?", (sid,))
    if not r or r[0]["estado"] != "Finalizada":
        return False, "Solo se puede calificar un servicio finalizado."
    s = r[0]
    if de_id == s["acompanante_id"]:
        lado, a_id = "acompanante", s["usuario_id"]
    elif _consultar(f"SELECT 1 FROM solicitudes s WHERE s.id=? AND {VISIBLES}", (sid, de_id, de_id)):
        lado, a_id = "cliente", s["acompanante_id"]
    else:
        return False, "No puede calificar este servicio."
    try:
        _ejecutar("INSERT INTO calificaciones(solicitud_id,lado,de_id,a_id,puntaje) VALUES(?,?,?,?,?)",
                  (sid, lado, de_id, a_id, puntaje))
    except ERROR_INTEGRIDAD:
        return False, "Este servicio ya fue calificado."
    return True, "¡Gracias por su calificación!"


def promedio(uid):
    """(promedio, cantidad) de las calificaciones que ha recibido un usuario."""
    r = _consultar("SELECT ROUND(AVG(puntaje), 1) AS p, COUNT(*) AS n FROM calificaciones WHERE a_id=?", (uid,))[0]
    return r["p"], r["n"]


# ======================================================================
#  SUPER ADMINISTRADOR: todas estas funciones verifican que quien las
#  llama sea realmente un superadmin y dejan huella en la auditoría.
# ======================================================================
def _exigir_super(actor_id):
    u = obtener_usuario(actor_id)
    if not u or u["rol"] != "superadmin":
        raise PermissionError("Solo el super administrador puede hacer esto.")
    return u


def auditar(actor_id, accion, objetivo_id=None, detalle=""):
    _ejecutar("INSERT INTO auditoria(fecha, actor_id, accion, objetivo_id, detalle) VALUES(?,?,?,?,?)",
              (ahora_local().strftime("%Y-%m-%d %H:%M:%S"), actor_id, accion, objetivo_id, detalle))


def ultimas_auditorias(actor_id, n=100):
    _exigir_super(actor_id)
    return _consultar(
        "SELECT a.fecha, a.accion, a.detalle, u.nombre AS actor, o.nombre AS objetivo FROM auditoria a "
        "LEFT JOIN usuarios u ON u.id=a.actor_id LEFT JOIN usuarios o ON o.id=a.objetivo_id "
        "ORDER BY a.id DESC LIMIT ?", (n,))


def estadisticas(actor_id):
    _exigir_super(actor_id)
    por_rol = {r["rol"]: r["n"] for r in _consultar("SELECT rol, COUNT(*) AS n FROM usuarios GROUP BY rol")}
    por_estado = {r["estado"]: r["n"] for r in _consultar("SELECT estado, COUNT(*) AS n FROM solicitudes GROUP BY estado")}
    suspendidas = _consultar("SELECT COUNT(*) AS n FROM usuarios WHERE activo=0")[0]["n"]
    prom = _consultar("SELECT ROUND(AVG(puntaje), 1) AS p FROM calificaciones")[0]["p"]
    return {"por_rol": por_rol, "por_estado": por_estado, "suspendidas": suspendidas, "promedio": prom}


def listar_usuarios(actor_id, texto="", rol=""):
    _exigir_super(actor_id)
    sql, args = "SELECT id, nombre, email, rol, activo FROM usuarios WHERE 1=1", []
    if (texto or "").strip():
        like = f"%{texto.strip()}%"
        sql += f" AND (nombre {COMO} ? OR email {COMO} ?)"
        args += [like, like]
    if rol in ROLES_TODOS:
        sql += " AND rol=?"
        args.append(rol)
    return _consultar(sql + " ORDER BY nombre LIMIT 100", args)


def editar_usuario(actor_id, uid, datos=None, email=None, rol=None):
    _exigir_super(actor_id)
    u = obtener_usuario(uid)
    if not u:
        return False, "No se encontró la cuenta."
    datos = {k: (v or "").strip() for k, v in (datos or {}).items() if k in COLUMNAS_PERFIL}
    if "nombre" in datos and len(datos["nombre"]) < 3:
        return False, "Escriba el nombre completo."
    err = validar_formatos(datos)
    if err:
        return False, err
    cambios = []
    if email is not None and email.strip().lower() != u["email"]:
        email = email.strip().lower()
        if not email_valido(email):
            return False, MSG_CORREO
        try:
            _ejecutar("UPDATE usuarios SET email=? WHERE id=?", (email, uid))
        except ERROR_INTEGRIDAD:
            return False, "Ese correo ya pertenece a otra cuenta."
        cambios.append("correo")
    if rol is not None and rol != u["rol"]:
        if rol not in ROLES_TODOS:
            return False, "Tipo de cuenta no válido."
        quedan = _consultar("SELECT COUNT(*) AS n FROM usuarios WHERE rol='superadmin' AND activo=1")[0]["n"]
        if u["rol"] == "superadmin" and quedan <= 1:
            return False, "Debe existir al menos un super administrador activo."
        _ejecutar("UPDATE usuarios SET rol=? WHERE id=?", (rol, uid))
        if rol == "adulto_mayor" and not u.get("codigo"):
            _ejecutar("UPDATE usuarios SET codigo=? WHERE id=?", (_codigo_nuevo(), uid))
        if rol in ROLES_ADMIN:
            _ejecutar("UPDATE usuarios SET onboarding_completo=1 WHERE id=?", (uid,))
        cambios.append(f"tipo de cuenta {u['rol']} -> {rol}")
    if datos:
        _, _ = guardar_datos(uid, datos)
        tocados = sorted(k for k, v in datos.items() if v != (u.get(k) or ""))
        if tocados:  # en la auditoría se anotan los campos, nunca su contenido
            cambios.append("campos: " + ", ".join(tocados))
    auditar(actor_id, "editar_usuario", uid, "; ".join(cambios) or "sin cambios")
    return True, "Cambios guardados."


def cambiar_activo(actor_id, uid, activo):
    _exigir_super(actor_id)
    if uid == actor_id:
        return False, "No puede suspender su propia cuenta."
    if not obtener_usuario(uid):
        return False, "No se encontró la cuenta."
    _ejecutar("UPDATE usuarios SET activo=? WHERE id=?", (1 if activo else 0, uid))
    auditar(actor_id, "reactivar_cuenta" if activo else "suspender_cuenta", uid)
    return True, "Cuenta reactivada." if activo else "Cuenta suspendida."


def resetear_clave(actor_id, uid):
    """Devuelve (True, contraseña_temporal) o (False, motivo). La persona deberá cambiarla al ingresar."""
    _exigir_super(actor_id)
    r = _consultar("SELECT pw_hash FROM usuarios WHERE id=?", (uid,))
    if not r:
        return False, "No se encontró la cuenta."
    if r[0]["pw_hash"] == "GOOGLE":
        return False, "Esta cuenta ingresa con Google y no tiene contraseña."
    temporal = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789") for _ in range(8))
    h, s = _clave(temporal)
    _ejecutar("UPDATE usuarios SET pw_hash=?, salt=?, debe_cambiar_clave=1 WHERE id=?", (h, s, uid))
    auditar(actor_id, "restablecer_clave", uid)
    return True, temporal


def vincular_admin(actor_id, familiar_id, adulto_id):
    _exigir_super(actor_id)
    f, a = obtener_usuario(familiar_id), obtener_usuario(adulto_id)
    if not f or f["rol"] != "familiar" or not a or a["rol"] != "adulto_mayor":
        return False, "El vínculo debe ser entre un familiar y un adulto mayor."
    ok, msg = _unir(familiar_id, adulto_id, a["nombre"])
    if ok:
        auditar(actor_id, "vincular", familiar_id, f"con {a['nombre']}")
    return ok, msg


def desvincular_admin(actor_id, familiar_id, adulto_id):
    _exigir_super(actor_id)
    a = obtener_usuario(adulto_id)
    desvincular(familiar_id, adulto_id)
    auditar(actor_id, "desvincular", familiar_id, f"de {a['nombre'] if a else adulto_id}")
    return True, "Vínculo quitado."


def editar_solicitud_admin(actor_id, sid, estado, acomp_id):
    """El super administrador puede corregir el estado y el acompañante de cualquier cita."""
    _exigir_super(actor_id)
    r = _consultar("SELECT usuario_id, acompanante_id FROM solicitudes WHERE id=?", (sid,))
    if not r:
        return False, "No se encontró la cita."
    if estado not in ESTADOS:
        return False, "Estado no válido."
    if estado == "Solicitada":
        acomp_id = None
    elif estado == "Cancelada":
        acomp_id = acomp_id or r[0]["acompanante_id"]
    elif not acomp_id:
        return False, "Elija un acompañante para ese estado."
    if acomp_id and estado in ("Asignada", "En curso"):
        c = conflicto(acomp_id, sid)
        if c:
            return False, _msg_cruce(c)
    _ejecutar("UPDATE solicitudes SET estado=?, acompanante_id=? WHERE id=?", (estado, acomp_id, sid))
    auditar(actor_id, "editar_cita", r[0]["usuario_id"], f"cita {sid}: estado {estado}, acompañante {acomp_id or 'ninguno'}")
    return True, "Cita actualizada."