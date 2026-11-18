import base64
import hashlib
import hmac
import io
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
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
# Sin ella, usa el archivo local acompana.db.
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
ESQUEMA_VERSION = "2"             # versión de la estructura de tablas (la 1 era la de 5 tablas planas)

# ---------- Reglas del servicio ----------
MARGEN_INICIO_MIN = 15      # el acompañante solo puede iniciar de 15 min antes a 15 min después de la hora
MAX_VINCULOS = 3            # adultos mayores que puede tener a cargo un familiar o cuidador
DURACION_MINIMA = 60        # la cita más corta: 1 hora
PASO_DURACION = 30          # la duración sube de media hora en media hora
DURACION_MAXIMA = 480       # la más larga que se puede elegir: 8 horas (o "tiempo indefinido")
EXTRA_MAXIMA = 240          # tiempo máximo que se puede agregar en cada extensión: 4 horas
RESERVA_INDEFINIDA_MIN = 240  # una cita de tiempo indefinido reserva 4 h en la agenda para evitar cruces
CODIGO_DIGITOS = 6          # largo del código de seguridad de cada cita
MAX_INTENTOS_CODIGO = 5     # después de 5 errores el código se bloquea y hay que generar uno nuevo
VERSION_TERMINOS = "1.0"    # si cambia el texto de los términos, súbela y se volverán a pedir

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
ACTIVOS = ("Solicitada", "Asignada", "En curso")
ROLES_PUBLICOS = ("adulto_mayor", "familiar", "acompanante")
ROLES_ADMIN = ("administrador", "superadmin")
ROLES_TODOS = ROLES_PUBLICOS + ROLES_ADMIN
ROLES_NOMBRES = {"adulto_mayor": "Adulto mayor", "familiar": "Familiar / cuidador", "acompanante": "Acompañante",
                 "administrador": "Administrador", "superadmin": "Super administrador"}

# Listas de opciones: se guardan UNA sola vez en tablas de catálogo y el resto de tablas las citan por su código (id)
TIPOS_SERVICIO = ["Cita médica", "Trámite o diligencia", "Compras", "Visita o paseo", "Otro"]
DOCUMENTOS = ["Cédula de ciudadanía", "Cédula de extranjería", "Pasaporte", "Otro documento"]
GENEROS = ["Femenino", "Masculino", "Otro", "Prefiero no decirlo"]
PARENTESCOS = ["Hijo/a", "Nieto/a", "Esposo/a o pareja", "Hermano/a", "Amigo/a o vecino/a", "Otro familiar",
               "Otra persona"]
MOVILIDAD = ["Camina sin ayuda", "Usa bastón", "Usa andador", "Usa silla de ruedas",
             "Necesita que lo ayuden a movilizarse"]
FORMACION = ["Bachiller", "Técnico o tecnólogo", "Auxiliar de enfermería o cuidador certificado", "Profesional",
             "Otra"]
CATALOGOS_FIJOS = {"estados_cita": ESTADOS, "tipos_servicio": TIPOS_SERVICIO, "tipos_documento": DOCUMENTOS,
                   "generos": GENEROS, "parentescos": PARENTESCOS, "niveles_movilidad": MOVILIDAD,
                   "niveles_formacion": FORMACION}

# Correo válido: algo@dominio.ext  (debe tener @ y al menos un punto después)
EMAIL_RE = re.compile(r"^[\w.+-]+@([A-Za-z0-9-]+\.)+[A-Za-z]{2,}$")
MSG_CORREO = "Por favor escriba un correo válido con @ y punto ( . ), por ejemplo: nombre@gmail.com"

# Datos personales que la app pide y edita (la interfaz los maneja "planos"; aquí se reparten en sus tablas)
COLUMNAS_PERFIL = [
    "nombre", "tipo_doc", "num_doc", "fecha_nac", "genero",
    "telefono", "direccion", "barrio", "ciudad",
    "contacto_nombre", "contacto_parentesco", "contacto_tel",
    "eps", "salud_condiciones", "salud_medicamentos", "salud_alergias", "movilidad",
    "parentesco_familiar", "formacion", "experiencia", "zona", "disponibilidad",
]
# dato de la app -> (tabla, columna)
CAMPOS_EN_TABLA = {
    "nombre": ("perfiles", "nombre"), "num_doc": ("perfiles", "num_doc"), "fecha_nac": ("perfiles", "fecha_nac"),
    "telefono": ("perfiles", "telefono"), "direccion": ("perfiles", "direccion"),
    "contacto_nombre": ("contactos_confianza", "nombre"), "contacto_tel": ("contactos_confianza", "telefono"),
    "salud_condiciones": ("datos_salud", "condiciones"), "salud_medicamentos": ("datos_salud", "medicamentos"),
    "salud_alergias": ("datos_salud", "alergias"),
    "experiencia": ("datos_acompanante", "experiencia"), "zona": ("datos_acompanante", "zona"),
    "disponibilidad": ("datos_acompanante", "disponibilidad"),
}
# dato de la app que es una opción de catálogo -> (tabla, columna con el código, tabla de catálogo)
CAMPOS_CATALOGO = {
    "tipo_doc": ("perfiles", "tipo_documento_id", "tipos_documento"),
    "genero": ("perfiles", "genero_id", "generos"),
    "contacto_parentesco": ("contactos_confianza", "parentesco_id", "parentescos"),
    "eps": ("datos_salud", "eps_id", "eps"),
    "movilidad": ("datos_salud", "movilidad_id", "niveles_movilidad"),
    "parentesco_familiar": ("datos_familiar", "parentesco_id", "parentescos"),
    "formacion": ("datos_acompanante", "formacion_id", "niveles_formacion"),
}
CAMPOS_TEXTO = [c for c in COLUMNAS_PERFIL if c != "nombre"] + ["codigo", "consentimiento_version",
                                                                "consentimiento_fecha"]

# Tablas de la base (en orden de creación y de copia: primero las que otras citan)
TABLAS = ["meta", "roles", "estados_cita", "tipos_servicio", "tipos_documento", "generos", "parentescos",
          "niveles_movilidad", "niveles_formacion", "eps", "ciudades", "barrios", "lugares", "tipos_accion",
          "usuarios", "perfiles", "fotos", "contactos_confianza", "datos_salud", "datos_familiar",
          "datos_acompanante", "codigos_familia", "consentimientos", "vinculos", "solicitudes",
          "codigos_seguridad", "ejecuciones", "ampliaciones", "calificaciones", "auditoria"]
TABLAS_CON_ID = {"roles", "estados_cita", "tipos_servicio", "tipos_documento", "generos", "parentescos",
                 "niveles_movilidad", "niveles_formacion", "eps", "ciudades", "barrios", "lugares", "tipos_accion",
                 "usuarios", "consentimientos", "solicitudes", "ampliaciones", "calificaciones", "auditoria"}
TABLAS_ANTIGUAS = ["usuarios", "solicitudes", "vinculos", "calificaciones", "auditoria"]  # las 5 del formato 1
_RE_INSERT_CON_ID = re.compile(r"\s*INSERT INTO (" + "|".join(sorted(TABLAS_CON_ID)) + r")\b", re.I)

# Consulta que arma el usuario "plano" (la forma que usa la interfaz) uniendo sus tablas
USUARIO_SQL = """
SELECT u.id, u.email, u.pw_hash, u.salt, r.clave AS rol, u.activo, u.debe_cambiar_clave, u.onboarding_completo,
       u.escala, cf.codigo AS codigo,
       p.nombre, td.nombre AS tipo_doc, p.num_doc, p.fecha_nac, g.nombre AS genero, p.telefono, p.direccion,
       b.nombre AS barrio, ci.nombre AS ciudad,
       cc.nombre AS contacto_nombre, pc.nombre AS contacto_parentesco, cc.telefono AS contacto_tel,
       e.nombre AS eps, ds.condiciones AS salud_condiciones, ds.medicamentos AS salud_medicamentos,
       ds.alergias AS salud_alergias, nm.nombre AS movilidad,
       pf.nombre AS parentesco_familiar,
       nf.nombre AS formacion, da.experiencia, da.zona, da.disponibilidad,
       (SELECT k.version FROM consentimientos k WHERE k.usuario_id = u.id ORDER BY k.id DESC LIMIT 1)
           AS consentimiento_version,
       (SELECT k.fecha FROM consentimientos k WHERE k.usuario_id = u.id ORDER BY k.id DESC LIMIT 1)
           AS consentimiento_fecha
FROM usuarios u
JOIN roles r ON r.id = u.rol_id
LEFT JOIN codigos_familia cf ON cf.usuario_id = u.id
LEFT JOIN perfiles p ON p.usuario_id = u.id
LEFT JOIN tipos_documento td ON td.id = p.tipo_documento_id
LEFT JOIN generos g ON g.id = p.genero_id
LEFT JOIN barrios b ON b.id = p.barrio_id
LEFT JOIN ciudades ci ON ci.id = b.ciudad_id
LEFT JOIN contactos_confianza cc ON cc.usuario_id = u.id
LEFT JOIN parentescos pc ON pc.id = cc.parentesco_id
LEFT JOIN datos_salud ds ON ds.usuario_id = u.id
LEFT JOIN eps e ON e.id = ds.eps_id
LEFT JOIN niveles_movilidad nm ON nm.id = ds.movilidad_id
LEFT JOIN datos_familiar df ON df.usuario_id = u.id
LEFT JOIN parentescos pf ON pf.id = df.parentesco_id
LEFT JOIN datos_acompanante da ON da.usuario_id = u.id
LEFT JOIN niveles_formacion nf ON nf.id = da.formacion_id
"""

# Citas con todos sus datos legibles. OJO: aquí NO va el código de seguridad (el acompañante no debe verlo)
BASE_SQL = """
SELECT s.id, s.usuario_id, s.creado_por, s.acompanante_id, s.fecha, s.hora, s.duracion_min,
       s.observaciones, s.obs_final,
       ts.nombre AS tipo, es.nombre AS estado, lo.descripcion AS origen, ld.descripcion AS destino,
       pu.nombre AS solicitante, pu.telefono AS tel_solicitante,
       pa.nombre AS acompanante, pa.telefono AS tel_acompanante, pc.nombre AS creador,
       ej.inicio_real, ej.fin_real,
       COALESCE((SELECT SUM(am.minutos) FROM ampliaciones am WHERE am.solicitud_id = s.id), 0) AS minutos_extra,
       (SELECT ROUND(AVG(ca.puntaje), 1) FROM calificaciones ca WHERE ca.a_id = s.acompanante_id)
           AS prom_acompanante,
       (SELECT ROUND(AVG(ca.puntaje), 1) FROM calificaciones ca WHERE ca.a_id = s.usuario_id)
           AS prom_solicitante,
       (SELECT ca.puntaje FROM calificaciones ca WHERE ca.solicitud_id = s.id AND ca.lado = 'cliente')
           AS puntaje_a_acompanante,
       (SELECT ca.puntaje FROM calificaciones ca WHERE ca.solicitud_id = s.id AND ca.lado = 'acompanante')
           AS puntaje_a_usuario
FROM solicitudes s
JOIN tipos_servicio ts ON ts.id = s.tipo_id
JOIN estados_cita es ON es.id = s.estado_id
JOIN lugares lo ON lo.id = s.origen_id
JOIN lugares ld ON ld.id = s.destino_id
JOIN perfiles pu ON pu.usuario_id = s.usuario_id
LEFT JOIN perfiles pa ON pa.usuario_id = s.acompanante_id
LEFT JOIN perfiles pc ON pc.usuario_id = s.creado_por
LEFT JOIN ejecuciones ej ON ej.solicitud_id = s.id
"""
# Datos mínimos de una cita para validar reglas (estado, horario, duración)
CITA_SQL = """
SELECT s.id, s.usuario_id, s.creado_por, s.acompanante_id, s.fecha, s.hora, s.duracion_min,
       es.nombre AS estado, ts.nombre AS tipo,
       COALESCE((SELECT SUM(am.minutos) FROM ampliaciones am WHERE am.solicitud_id = s.id), 0) AS minutos_extra
FROM solicitudes s
JOIN estados_cita es ON es.id = s.estado_id
JOIN tipos_servicio ts ON ts.id = s.tipo_id
"""
# Solicitudes que un usuario puede ver: las suyas y las de los adultos mayores que tiene vinculados
VISIBLES = ("(s.usuario_id=? OR s.usuario_id IN "
            "(SELECT adulto_id FROM vinculos WHERE familiar_id=?))")


# =====================================================================
#  CONEXIÓN: SQLite local o PostgreSQL (Supabase) con un pool de conexiones
# =====================================================================
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
    c.execute("PRAGMA foreign_keys = ON")  # que SQLite también respete las relaciones entre tablas
    return c


@contextmanager
def _transaccion():
    """Agrupa varias instrucciones: o se guardan todas o no se guarda ninguna."""
    if USAR_PG:
        with _pool().connection() as c:
            yield c
    else:
        c = sqlite3.connect(DB_FILE, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        c.execute("BEGIN")
        try:
            yield c
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            raise
        finally:
            c.close()


def _a_pg(sql):
    return sql.replace("?", "%s")  # el código escribe ? como marcador; PostgreSQL usa %s


def _limpio(fila):
    return {k: (float(v) if isinstance(v, Decimal) else v) for k, v in fila.items()}


def _consultar(sql, args=(), tx=None):
    if USAR_PG:
        if tx is not None:
            cur = tx.execute(_a_pg(sql), list(args))
            filas = cur.fetchall() if cur.description else []
        else:
            with _pool().connection() as c:
                cur = c.execute(_a_pg(sql), list(args))
                filas = cur.fetchall() if cur.description else []
        return [_limpio(f) for f in filas]
    if tx is not None:
        return [dict(r) for r in tx.execute(sql, list(args)).fetchall()]
    with _con() as c:
        return [dict(r) for r in c.execute(sql, list(args)).fetchall()]


def _ejecutar(sql, args=(), tx=None):
    """Ejecuta una instrucción. En INSERT de tablas con código (id) devuelve el id de la fila nueva."""
    if USAR_PG:
        q = _a_pg(sql)
        if _RE_INSERT_CON_ID.match(q):
            q += " RETURNING id"
        if tx is not None:
            cur = tx.execute(q, list(args))
            fila = cur.fetchone() if cur.description else None
        else:
            with _pool().connection() as c:
                cur = c.execute(q, list(args))
                fila = cur.fetchone() if cur.description else None
        return fila.get("id") if fila else None
    if tx is not None:
        return tx.execute(sql, list(args)).lastrowid
    with _con() as c:
        return c.execute(sql, list(args)).lastrowid


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


# =====================================================================
#  CATÁLOGOS: cada texto repetido se guarda una sola vez y se cita por su código
# =====================================================================
def _id_de(tabla, nombre, tx=None, col="nombre"):
    """Código (id) de una opción de catálogo; si no existe todavía, la crea."""
    texto = " ".join((nombre or "").split())
    if not texto:
        return None
    r = _consultar(f"SELECT id FROM {tabla} WHERE LOWER({col})=LOWER(?)", (texto,), tx)
    if r:
        return r[0]["id"]
    _ejecutar(f"INSERT INTO {tabla}({col}) VALUES(?) ON CONFLICT DO NOTHING", (texto,), tx)
    return _consultar(f"SELECT id FROM {tabla} WHERE {col}=?", (texto,), tx)[0]["id"]


def _id_rol(clave, tx=None):
    r = _consultar("SELECT id FROM roles WHERE clave=?", (clave,), tx)
    if not r:
        raise ValueError(f"Tipo de cuenta desconocido: {clave}")
    return r[0]["id"]


def _id_barrio(barrio, ciudad, tx=None):
    barrio = " ".join((barrio or "").split())
    if not barrio:
        return None
    ciudad_id = _id_de("ciudades", ciudad, tx)
    if ciudad_id is None:
        r = _consultar("SELECT id FROM barrios WHERE LOWER(nombre)=LOWER(?) AND ciudad_id IS NULL", (barrio,), tx)
    else:
        r = _consultar("SELECT id FROM barrios WHERE LOWER(nombre)=LOWER(?) AND ciudad_id=?", (barrio, ciudad_id), tx)
    if r:
        return r[0]["id"]
    return _ejecutar("INSERT INTO barrios(nombre, ciudad_id) VALUES(?,?)", (barrio, ciudad_id), tx)


def _upsert(tabla, uid, valores, tx=None):
    """Guarda columnas en una tabla de datos 1 a 1 con el usuario (la crea la primera vez)."""
    if not valores:
        return
    cols = list(valores)
    if tabla == "perfiles" or all(v in (None, "") for v in valores.values()):
        # el perfil siempre existe; y si todo viene vacío no vale la pena crear una fila nueva
        _ejecutar(f"UPDATE {tabla} SET {', '.join(c + '=?' for c in cols)} WHERE usuario_id=?",
                  [valores[c] for c in cols] + [uid], tx)
        return
    _ejecutar(f"INSERT INTO {tabla}(usuario_id, {', '.join(cols)}) VALUES(?, {', '.join('?' for _ in cols)}) "
              f"ON CONFLICT (usuario_id) DO UPDATE SET {', '.join(c + '=excluded.' + c for c in cols)}",
              [uid] + [valores[c] for c in cols], tx)


def _guardar_perfil(uid, datos, tx=None):
    """Reparte los datos personales "planos" de la app entre sus tablas (perfil, contacto, salud, etc.)."""
    por_tabla = {}
    for k, v in datos.items():
        if k in CAMPOS_EN_TABLA:
            t, c = CAMPOS_EN_TABLA[k]
            por_tabla.setdefault(t, {})[c] = v if v is not None else ""
        elif k in CAMPOS_CATALOGO:
            t, c, catalogo = CAMPOS_CATALOGO[k]
            por_tabla.setdefault(t, {})[c] = _id_de(catalogo, v, tx)
    if "barrio" in datos or "ciudad" in datos:
        actual = _consultar("SELECT b.nombre AS barrio, ci.nombre AS ciudad FROM perfiles p "
                            "LEFT JOIN barrios b ON b.id = p.barrio_id LEFT JOIN ciudades ci ON ci.id = b.ciudad_id "
                            "WHERE p.usuario_id=?", (uid,), tx)
        previo = actual[0] if actual else {}
        barrio = datos["barrio"] if "barrio" in datos else previo.get("barrio")
        ciudad = datos["ciudad"] if "ciudad" in datos else previo.get("ciudad")
        por_tabla.setdefault("perfiles", {})["barrio_id"] = _id_barrio(barrio, ciudad, tx)
    for tabla, valores in por_tabla.items():
        _upsert(tabla, uid, valores, tx)


# ---------- Claves y creación de usuarios ----------
def _hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 100_000).hex()


def _clave(password):
    salt = secrets.token_hex(16)
    return _hash(password, salt), salt


def _codigo_nuevo(tx=None):
    """Código de familia (6 caracteres) de un adulto mayor."""
    while True:
        cod = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6))
        if not _consultar("SELECT 1 FROM codigos_familia WHERE codigo=?", (cod,), tx):
            return cod


def _crear_usuario(nombre, email, pw_hash, salt, rol, tx=None):
    if tx is None:
        with _transaccion() as t:
            return _crear_usuario(nombre, email, pw_hash, salt, rol, t)
    uid = _ejecutar("INSERT INTO usuarios(email, pw_hash, salt, rol_id, creado_en) VALUES(?,?,?,?,?)",
                    (email, pw_hash, salt, _id_rol(rol, tx), ahora_local().strftime("%Y-%m-%d %H:%M:%S")), tx)
    _ejecutar("INSERT INTO perfiles(usuario_id, nombre) VALUES(?,?)", (uid, nombre), tx)
    if rol == "adulto_mayor":
        _ejecutar("INSERT INTO codigos_familia(usuario_id, codigo) VALUES(?,?)", (uid, _codigo_nuevo(tx)), tx)
    return uid


# =====================================================================
#  ESTRUCTURA DE LA BASE DE DATOS (30 tablas relacionadas)
# =====================================================================
def _esquema():
    pk = "SERIAL PRIMARY KEY" if USAR_PG else "INTEGER PRIMARY KEY AUTOINCREMENT"
    uno_a_uno = "usuario_id INTEGER PRIMARY KEY REFERENCES usuarios(id) ON DELETE CASCADE"
    catalogo = "(id {pk}, nombre TEXT NOT NULL UNIQUE)"
    t = [
        "CREATE TABLE IF NOT EXISTS meta(clave TEXT PRIMARY KEY, valor TEXT NOT NULL)",
        f"CREATE TABLE IF NOT EXISTS roles(id {pk}, clave TEXT NOT NULL UNIQUE, nombre TEXT NOT NULL)",
    ]
    for nombre in ("estados_cita", "tipos_servicio", "tipos_documento", "generos", "parentescos",
                   "niveles_movilidad", "niveles_formacion", "eps", "ciudades", "tipos_accion"):
        t.append(f"CREATE TABLE IF NOT EXISTS {nombre}" + catalogo.format(pk=pk))
    t += [
        f"CREATE TABLE IF NOT EXISTS barrios(id {pk}, nombre TEXT NOT NULL, "
        "ciudad_id INTEGER REFERENCES ciudades(id), UNIQUE (nombre, ciudad_id))",
        f"CREATE TABLE IF NOT EXISTS lugares(id {pk}, descripcion TEXT NOT NULL UNIQUE)",
        # --- cuenta y datos de cada persona ---
        f"CREATE TABLE IF NOT EXISTS usuarios(id {pk}, email TEXT NOT NULL UNIQUE, pw_hash TEXT NOT NULL, "
        "salt TEXT NOT NULL, rol_id INTEGER NOT NULL REFERENCES roles(id), activo INTEGER NOT NULL DEFAULT 1, "
        "debe_cambiar_clave INTEGER NOT NULL DEFAULT 0, onboarding_completo INTEGER NOT NULL DEFAULT 0, "
        "escala INTEGER NOT NULL DEFAULT 0, creado_en TEXT NOT NULL DEFAULT '')",
        f"CREATE TABLE IF NOT EXISTS perfiles({uno_a_uno}, nombre TEXT NOT NULL, "
        "tipo_documento_id INTEGER REFERENCES tipos_documento(id), num_doc TEXT NOT NULL DEFAULT '', "
        "fecha_nac TEXT NOT NULL DEFAULT '', genero_id INTEGER REFERENCES generos(id), "
        "telefono TEXT NOT NULL DEFAULT '', direccion TEXT NOT NULL DEFAULT '', "
        "barrio_id INTEGER REFERENCES barrios(id))",
        f"CREATE TABLE IF NOT EXISTS fotos({uno_a_uno}, imagen TEXT NOT NULL)",
        f"CREATE TABLE IF NOT EXISTS contactos_confianza({uno_a_uno}, nombre TEXT NOT NULL DEFAULT '', "
        "parentesco_id INTEGER REFERENCES parentescos(id), telefono TEXT NOT NULL DEFAULT '')",
        f"CREATE TABLE IF NOT EXISTS datos_salud({uno_a_uno}, eps_id INTEGER REFERENCES eps(id), "
        "condiciones TEXT NOT NULL DEFAULT '', medicamentos TEXT NOT NULL DEFAULT '', "
        "alergias TEXT NOT NULL DEFAULT '', movilidad_id INTEGER REFERENCES niveles_movilidad(id))",
        f"CREATE TABLE IF NOT EXISTS datos_familiar({uno_a_uno}, parentesco_id INTEGER REFERENCES parentescos(id))",
        f"CREATE TABLE IF NOT EXISTS datos_acompanante({uno_a_uno}, "
        "formacion_id INTEGER REFERENCES niveles_formacion(id), experiencia TEXT NOT NULL DEFAULT '', "
        "zona TEXT NOT NULL DEFAULT '', disponibilidad TEXT NOT NULL DEFAULT '')",
        f"CREATE TABLE IF NOT EXISTS codigos_familia({uno_a_uno}, codigo TEXT NOT NULL UNIQUE)",
        f"CREATE TABLE IF NOT EXISTS consentimientos(id {pk}, "
        "usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE, "
        "version TEXT NOT NULL, fecha TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS vinculos("
        "familiar_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE, "
        "adulto_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE, "
        "PRIMARY KEY (familiar_id, adulto_id))",
        # --- citas ---
        f"CREATE TABLE IF NOT EXISTS solicitudes(id {pk}, usuario_id INTEGER NOT NULL REFERENCES usuarios(id), "
        "creado_por INTEGER REFERENCES usuarios(id), tipo_id INTEGER NOT NULL REFERENCES tipos_servicio(id), "
        "fecha TEXT NOT NULL, hora TEXT NOT NULL, "
        "duracion_min INTEGER CHECK (duracion_min IS NULL OR duracion_min >= 60), "
        "origen_id INTEGER NOT NULL REFERENCES lugares(id), destino_id INTEGER NOT NULL REFERENCES lugares(id), "
        "observaciones TEXT NOT NULL DEFAULT '', estado_id INTEGER NOT NULL REFERENCES estados_cita(id), "
        "acompanante_id INTEGER REFERENCES usuarios(id), obs_final TEXT NOT NULL DEFAULT '')",
        "CREATE TABLE IF NOT EXISTS codigos_seguridad("
        "solicitud_id INTEGER PRIMARY KEY REFERENCES solicitudes(id) ON DELETE CASCADE, "
        "codigo TEXT NOT NULL, intentos INTEGER NOT NULL DEFAULT 0, generado_en TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS ejecuciones("
        "solicitud_id INTEGER PRIMARY KEY REFERENCES solicitudes(id) ON DELETE CASCADE, "
        "inicio_real TEXT, fin_real TEXT)",
        f"CREATE TABLE IF NOT EXISTS ampliaciones(id {pk}, "
        "solicitud_id INTEGER NOT NULL REFERENCES solicitudes(id) ON DELETE CASCADE, "
        "minutos INTEGER NOT NULL CHECK (minutos > 0), pedida_por INTEGER REFERENCES usuarios(id), "
        "fecha TEXT NOT NULL)",
        f"CREATE TABLE IF NOT EXISTS calificaciones(id {pk}, "
        "solicitud_id INTEGER NOT NULL REFERENCES solicitudes(id) ON DELETE CASCADE, "
        "lado TEXT NOT NULL CHECK (lado IN ('cliente', 'acompanante')), "
        "de_id INTEGER NOT NULL REFERENCES usuarios(id), a_id INTEGER NOT NULL REFERENCES usuarios(id), "
        "puntaje INTEGER NOT NULL CHECK (puntaje BETWEEN 0 AND 5), UNIQUE (solicitud_id, lado))",
        f"CREATE TABLE IF NOT EXISTS auditoria(id {pk}, fecha TEXT NOT NULL, "
        "actor_id INTEGER NOT NULL REFERENCES usuarios(id), accion_id INTEGER NOT NULL REFERENCES tipos_accion(id), "
        "objetivo_id INTEGER REFERENCES usuarios(id), detalle TEXT NOT NULL DEFAULT '')",
    ]
    return t


INDICES = [
    "CREATE INDEX IF NOT EXISTS idx_solicitudes_usuario ON solicitudes(usuario_id)",
    "CREATE INDEX IF NOT EXISTS idx_solicitudes_acompanante ON solicitudes(acompanante_id)",
    "CREATE INDEX IF NOT EXISTS idx_solicitudes_fecha ON solicitudes(fecha)",
    "CREATE INDEX IF NOT EXISTS idx_calificaciones_a ON calificaciones(a_id)",
    "CREATE INDEX IF NOT EXISTS idx_auditoria_actor ON auditoria(actor_id)",
    "CREATE INDEX IF NOT EXISTS idx_vinculos_adulto ON vinculos(adulto_id)",
    "CREATE INDEX IF NOT EXISTS idx_usuarios_rol ON usuarios(rol_id)",
]


def _tabla_existe(nombre, tx=None):
    if USAR_PG:
        r = _consultar("SELECT 1 AS x FROM information_schema.tables WHERE table_schema='public' "
                       "AND table_name=?", (nombre,), tx)
    else:
        r = _consultar("SELECT 1 AS x FROM sqlite_master WHERE type='table' AND name=?", (nombre,), tx)
    return bool(r)


def _columnas(tabla, tx=None):
    if USAR_PG:
        filas = _consultar("SELECT column_name AS name FROM information_schema.columns "
                           "WHERE table_schema='public' AND table_name=?", (tabla,), tx)
    else:
        filas = _consultar(f"PRAGMA table_info({tabla})", (), tx)
    return {f["name"] for f in filas}


def _crear_tablas(tx=None):
    for sentencia in _esquema() + INDICES:
        _ejecutar(sentencia, tx=tx)


def _sembrar_catalogos(tx=None):
    for clave, nombre in ROLES_NOMBRES.items():
        if not _consultar("SELECT 1 FROM roles WHERE clave=?", (clave,), tx):
            _ejecutar("INSERT INTO roles(clave, nombre) VALUES(?,?)", (clave, nombre), tx)
    for tabla, items in CATALOGOS_FIJOS.items():
        for item in items:
            _id_de(tabla, item, tx)


def sembrar_catalogos():
    _sembrar_catalogos()


def _asegurar_rls(tx=None):
    """Candado de Supabase: la API pública no puede leer ni escribir ninguna de nuestras tablas."""
    if not USAR_PG:
        return
    nombres = TABLAS + [t + "_v1" for t in TABLAS_ANTIGUAS]
    sin = _consultar("SELECT c.relname AS nombre FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                     "WHERE n.nspname='public' AND c.relkind='r' AND NOT c.relrowsecurity "
                     "AND c.relname = ANY(?)", (nombres,), tx)
    for fila in sin:
        _ejecutar(f'ALTER TABLE "{fila["nombre"]}" ENABLE ROW LEVEL SECURITY', tx=tx)


def _marcar_version(tx=None):
    _ejecutar("INSERT INTO meta(clave, valor) VALUES('esquema', ?) "
              "ON CONFLICT (clave) DO UPDATE SET valor=excluded.valor", (ESQUEMA_VERSION,), tx)


def _reajustar_secuencias(tx):
    """En PostgreSQL: que los números automáticos sigan después del último id copiado."""
    if not USAR_PG:
        return
    for t in sorted(TABLAS_CON_ID):
        _consultar(f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), COALESCE((SELECT MAX(id) FROM {t}), 1), "
                   f"(SELECT COUNT(*) > 0 FROM {t}))", (), tx)


# =====================================================================
#  CONVERSIÓN desde el formato anterior (5 tablas planas) al normalizado
# =====================================================================
def _convertir_formato_antiguo():
    print("\nConvirtiendo la base de datos a la estructura normalizada (30 tablas)...\n"
          "Se conserva una copia de seguridad de las 5 tablas anteriores con el sufijo _v1.")
    with _transaccion() as tx:
        for t in TABLAS_ANTIGUAS:
            if _tabla_existe(t, tx):
                _ejecutar(f"ALTER TABLE {t} RENAME TO {t}_v1", tx=tx)
        _crear_tablas(tx)
        _sembrar_catalogos(tx)
        resumen = _copiar_desde_v1(tx)
        _marcar_version(tx)
        _reajustar_secuencias(tx)
        _asegurar_rls(tx)
    print("Conversión terminada: " + ", ".join(f"{k}: {v}" for k, v in resumen.items()) + ".\n"
          "Cuando compruebe que todo está bien, puede borrar la copia con: python migrar_a_supabase.py --borrar-respaldo\n")


def _copiar_desde_v1(tx):
    n = {}
    usuarios = _consultar("SELECT * FROM usuarios_v1 ORDER BY id", (), tx) if _tabla_existe("usuarios_v1", tx) else []
    ids = {u["id"] for u in usuarios}
    for u in usuarios:
        _ejecutar("INSERT INTO usuarios(id, email, pw_hash, salt, rol_id, activo, debe_cambiar_clave, "
                  "onboarding_completo, escala, creado_en) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (u["id"], u["email"], u["pw_hash"], u["salt"], _id_rol(u["rol"], tx), u.get("activo", 1) or 0,
                   u.get("debe_cambiar_clave") or 0, u.get("onboarding_completo") or 0, u.get("escala") or 0, ""), tx)
        _ejecutar("INSERT INTO perfiles(usuario_id, nombre) VALUES(?,?)", (u["id"], u["nombre"]), tx)
        _guardar_perfil(u["id"], {k: (u.get(k) or "") for k in COLUMNAS_PERFIL if k != "nombre"}, tx)
        if u.get("codigo"):
            _ejecutar("INSERT INTO codigos_familia(usuario_id, codigo) VALUES(?,?)", (u["id"], u["codigo"]), tx)
        foto = u.get("foto") or ""
        if foto and len(foto) < 500 and os.path.exists(foto):  # foto guardada como archivo en la versión vieja
            foto = _foto_base64(foto)[0] or ""
        if foto:
            _ejecutar("INSERT INTO fotos(usuario_id, imagen) VALUES(?,?)", (u["id"], foto), tx)
        if u.get("consentimiento_version"):
            _ejecutar("INSERT INTO consentimientos(usuario_id, version, fecha) VALUES(?,?,?)",
                      (u["id"], u["consentimiento_version"], u.get("consentimiento_fecha") or ""), tx)
    n["usuarios"] = len(usuarios)
    if _tabla_existe("vinculos_v1", tx):
        vinculos = _consultar("SELECT * FROM vinculos_v1", (), tx)
        for v in vinculos:
            if v["familiar_id"] in ids and v["adulto_id"] in ids:
                _ejecutar("INSERT INTO vinculos(familiar_id, adulto_id) VALUES(?,?)",
                          (v["familiar_id"], v["adulto_id"]), tx)
        n["vínculos"] = len(vinculos)
    citas = _consultar("SELECT * FROM solicitudes_v1 ORDER BY id", (), tx) if _tabla_existe("solicitudes_v1", tx) else []
    citas = [c for c in citas if c["usuario_id"] in ids]
    cita_ids = {c["id"] for c in citas}
    for s in citas:
        _ejecutar("INSERT INTO solicitudes(id, usuario_id, creado_por, tipo_id, fecha, hora, duracion_min, origen_id, "
                  "destino_id, observaciones, estado_id, acompanante_id, obs_final) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (s["id"], s["usuario_id"], s.get("creado_por") if s.get("creado_por") in ids else s["usuario_id"],
                   _id_de("tipos_servicio", s["tipo"], tx), s["fecha"], s["hora"], DURACION_MINIMA,
                   _id_de("lugares", s["origen"], tx, "descripcion"), _id_de("lugares", s["destino"], tx, "descripcion"),
                   s.get("observaciones") or "", _id_de("estados_cita", s["estado"], tx),
                   s.get("acompanante_id") if s.get("acompanante_id") in ids else None, s.get("obs_final") or ""), tx)
        if s["estado"] in ACTIVOS:  # las citas que seguían abiertas reciben su código de seguridad
            _ejecutar("INSERT INTO codigos_seguridad(solicitud_id, codigo, generado_en) VALUES(?,?,?)",
                      (s["id"], _nuevo_codigo_cita(), ahora_local().strftime("%Y-%m-%d %H:%M:%S")), tx)
    n["citas"] = len(citas)
    if _tabla_existe("calificaciones_v1", tx):
        cals = [c for c in _consultar("SELECT * FROM calificaciones_v1 ORDER BY id", (), tx)
                if c["solicitud_id"] in cita_ids and c["de_id"] in ids and c["a_id"] in ids]
        for c in cals:
            _ejecutar("INSERT INTO calificaciones(id, solicitud_id, lado, de_id, a_id, puntaje) VALUES(?,?,?,?,?,?)",
                      (c["id"], c["solicitud_id"], c["lado"], c["de_id"], c["a_id"], c["puntaje"]), tx)
        n["calificaciones"] = len(cals)
    if _tabla_existe("auditoria_v1", tx):
        aud = [a for a in _consultar("SELECT * FROM auditoria_v1 ORDER BY id", (), tx) if a["actor_id"] in ids]
        for a in aud:
            _ejecutar("INSERT INTO auditoria(id, fecha, actor_id, accion_id, objetivo_id, detalle) VALUES(?,?,?,?,?,?)",
                      (a["id"], a["fecha"], a["actor_id"], _id_de("tipos_accion", a["accion"], tx),
                       a.get("objetivo_id") if a.get("objetivo_id") in ids else None, a.get("detalle") or ""), tx)
        n["auditoría"] = len(aud)
    return n


def borrar_respaldo_v1():
    """Borra las copias *_v1 que quedaron tras convertir la base. Hágalo solo cuando todo esté verificado."""
    borradas = []
    with _transaccion() as tx:
        for t in TABLAS_ANTIGUAS:
            if _tabla_existe(t + "_v1", tx):
                _ejecutar(f"DROP TABLE {t}_v1", tx=tx)
                borradas.append(t + "_v1")
    return borradas


def crear_esquema(sembrar=True):
    """Crea (o actualiza) la estructura de tablas. No crea cuentas."""
    try:
        if _tabla_existe("meta") and _consultar("SELECT valor FROM meta WHERE clave='esquema'") == [
                {"valor": ESQUEMA_VERSION}]:
            _asegurar_rls()
            return
        if _tabla_existe("usuarios") and "nombre" in _columnas("usuarios"):
            _convertir_formato_antiguo()
            return
        with _transaccion() as tx:
            _crear_tablas(tx)
            if sembrar:
                _sembrar_catalogos(tx)
            _marcar_version(tx)
            _asegurar_rls(tx)
    except Exception as ex:
        if USAR_PG and isinstance(ex, psycopg.OperationalError):
            raise RuntimeError("No se pudo conectar con la base de datos en la nube. Revise la línea DATABASE_URL "
                               "del archivo .env (usuario, contraseña y servidor) y que el proyecto de Supabase "
                               "esté activo (los gratuitos se pausan tras una semana sin uso).") from None
        raise


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
    _ejecutar("UPDATE usuarios SET debe_cambiar_clave=1, onboarding_completo=1 WHERE id=?", (uid,))
    if generada:
        print(f"\n=== Cuenta creada: {nombre} ===\n    Correo: {email}\n    Contraseña inicial: {clave}\n"
              "    Anótela ahora: no se vuelve a mostrar. Se le pedirá cambiarla al ingresar.\n")


def _rol_de(uid):
    r = _consultar("SELECT r.clave FROM usuarios u JOIN roles r ON r.id = u.rol_id WHERE u.id=?", (uid,))
    return r[0]["clave"] if r else None


def _hay_rol(clave):
    return bool(_consultar("SELECT 1 FROM usuarios u JOIN roles r ON r.id = u.rol_id WHERE r.clave=?", (clave,)))


def init_db():
    crear_esquema()
    # adultos mayores que todavía no tienen código de familia (por ejemplo, cuentas antiguas)
    for u in _consultar("SELECT u.id FROM usuarios u JOIN roles r ON r.id = u.rol_id "
                        "LEFT JOIN codigos_familia cf ON cf.usuario_id = u.id "
                        "WHERE r.clave='adulto_mayor' AND cf.usuario_id IS NULL"):
        _ejecutar("INSERT INTO codigos_familia(usuario_id, codigo) VALUES(?,?)", (u["id"], _codigo_nuevo()))
    if not _hay_rol("administrador"):
        _crear_cuenta_admin("Administrador", EMAIL_ADMIN, "administrador", "ADMIN_CLAVE")
    if not _hay_rol("superadmin"):
        _crear_cuenta_admin("Super administrador", EMAIL_SUPER, "superadmin", "SUPERADMIN_CLAVE")
    _ejecutar("UPDATE usuarios SET onboarding_completo=1 WHERE rol_id IN "
              "(SELECT id FROM roles WHERE clave IN ('administrador', 'superadmin'))")


# =====================================================================
#  USUARIOS (RF-01, RF-02, RF-03)
# =====================================================================
def _publico(u):
    p = {k: v for k, v in u.items() if k not in ("pw_hash", "salt")}
    for k in CAMPOS_TEXTO:
        if p.get(k) is None:
            p[k] = ""
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
    r = _consultar(USUARIO_SQL + " WHERE u.email=?", ((email or "").strip().lower(),))
    if r and hmac.compare_digest(_hash(password or "", r[0]["salt"]), r[0]["pw_hash"]):
        return _publico(r[0])
    return None


def obtener_usuario(uid):
    r = _consultar(USUARIO_SQL + " WHERE u.id=?", (uid,))
    return _publico(r[0]) if r else None


def usuario_por_email(email):
    r = _consultar(USUARIO_SQL + " WHERE u.email=?", (email.strip().lower(),))
    return _publico(r[0]) if r else None


def acompanantes():
    return _consultar("SELECT u.id, p.nombre FROM usuarios u JOIN roles r ON r.id = u.rol_id "
                      "JOIN perfiles p ON p.usuario_id = u.id WHERE r.clave='acompanante' AND u.activo=1 "
                      "ORDER BY p.nombre")


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
    if datos:
        with _transaccion() as tx:
            _guardar_perfil(uid, datos, tx)
    return True, "Datos guardados."


def aceptar_terminos(uid):
    _ejecutar("INSERT INTO consentimientos(usuario_id, version, fecha) VALUES(?,?,?)",
              (uid, VERSION_TERMINOS, ahora_local().strftime("%Y-%m-%d %H:%M:%S")))


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
    """Guarda la foto (reducida) en su propia tabla, para que viaje con la cuenta y no pese en cada consulta."""
    b64, error = _foto_base64(origen)
    if error:
        return False, error
    _upsert("fotos", uid, {"imagen": b64})
    return True, "Foto actualizada."


def foto_de(uid):
    r = _consultar("SELECT imagen FROM fotos WHERE usuario_id=?", (uid,))
    if not r:
        return None
    try:
        return base64.b64decode(r[0]["imagen"], validate=True)
    except Exception:
        return None


# ---------- Familiar <-> adultos mayores (hasta MAX_VINCULOS) ----------
def adultos_de(familiar_id):
    return _consultar(
        "SELECT u.id, p.nombre FROM vinculos v JOIN usuarios u ON u.id = v.adulto_id "
        "JOIN perfiles p ON p.usuario_id = u.id WHERE v.familiar_id=? ORDER BY p.nombre", (familiar_id,))


def familiares_de(adulto_id):
    return _consultar(
        "SELECT u.id, p.nombre FROM vinculos v JOIN usuarios u ON u.id = v.familiar_id "
        "JOIN perfiles p ON p.usuario_id = u.id WHERE v.adulto_id=? ORDER BY p.nombre", (adulto_id,))


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
    if _rol_de(familiar_id) != "familiar":
        return False, "Solo las cuentas de familiar o cuidador pueden vincularse."
    codigo = (codigo or "").strip().upper()
    a = _consultar("SELECT u.id, p.nombre FROM codigos_familia cf JOIN usuarios u ON u.id = cf.usuario_id "
                   "JOIN roles r ON r.id = u.rol_id JOIN perfiles p ON p.usuario_id = u.id "
                   "WHERE cf.codigo=? AND r.clave='adulto_mayor' AND u.activo=1", (codigo,))
    if not codigo or not a:
        return False, "No encontramos ese código. Pídaselo de nuevo al adulto mayor."
    return _unir(familiar_id, a[0]["id"], a[0]["nombre"])


def desvincular(familiar_id, adulto_id):
    _ejecutar("DELETE FROM vinculos WHERE familiar_id=? AND adulto_id=?", (familiar_id, adulto_id))
    return True


# =====================================================================
#  CITAS: horarios, duración y cruces
# =====================================================================
def _h12(hhmm):
    h, m = map(int, hhmm.split(":"))
    return f"{h % 12 or 12}:{m:02d} {'a. m.' if h < 12 else 'p. m.'}"


def _inicio_de(c):
    return datetime.strptime(f"{c['fecha']} {c['hora']}", "%Y-%m-%d %H:%M")


def _minutos_previstos(c):
    base = c["duracion_min"] if c["duracion_min"] is not None else RESERVA_INDEFINIDA_MIN
    return base + (c.get("minutos_extra") or 0)


def _fin_previsto(c):
    return _inicio_de(c) + timedelta(minutes=_minutos_previstos(c))


def fin_estimado(c):
    """Hora prevista de fin (datetime), o None si la cita es de tiempo indefinido."""
    return None if c["duracion_min"] is None else _fin_previsto(c)


def _punto(texto):
    return texto if texto.endswith(".") else texto + "."


def _rango_txt(c):
    ini = _h12(_inicio_de(c).strftime("%H:%M"))
    if c["duracion_min"] is None:
        return f"desde las {ini} (tiempo indefinido: se reservan {RESERVA_INDEFINIDA_MIN // 60} horas)"
    return f"de {ini} a {_h12(_fin_previsto(c).strftime('%H:%M'))}"


def _cita(sid, tx=None):
    r = _consultar(CITA_SQL + " WHERE s.id=?", (sid,), tx)
    return r[0] if r else None


def _choque(campo, valor, inicio, fin, estados, excluir=None):
    """Cita de 'campo'=valor (usuario_id o acompanante_id) que se cruza con el intervalo [inicio, fin)."""
    marcas = ",".join("?" for _ in estados)
    filas = _consultar(CITA_SQL + f" WHERE s.{campo}=? AND es.nombre IN ({marcas}) AND s.fecha BETWEEN ? AND ?",
                       [valor, *estados, (inicio.date() - timedelta(days=1)).isoformat(), fin.date().isoformat()])
    for o in filas:
        if o["id"] == excluir:
            continue
        if inicio < _fin_previsto(o) and _inicio_de(o) < fin:
            return o
    return None


def _duracion_valida(minutos):
    if minutos is None:
        return True
    return (isinstance(minutos, int) and DURACION_MINIMA <= minutos <= DURACION_MAXIMA
            and minutos % PASO_DURACION == 0)


def _nuevo_codigo_cita():
    return str(secrets.randbelow(10 ** CODIGO_DIGITOS)).zfill(CODIGO_DIGITOS)


def crear_solicitud(creador_id, beneficiario_id, tipo, fecha, hora, origen, destino, obs,
                    duracion_min=DURACION_MINIMA):
    """Devuelve (id, mensaje). duracion_min: 60, 90, 120... o None para tiempo indefinido.
    Si no se pudo guardar, id es None y el mensaje explica por qué."""
    if beneficiario_id != creador_id and not _consultar(
            "SELECT 1 FROM vinculos WHERE familiar_id=? AND adulto_id=?", (creador_id, beneficiario_id)):
        return None, "No tiene permiso para pedir citas por esta persona."
    if not _duracion_valida(duracion_min):
        return None, "Elija una duración válida: desde 1 hora, de media en media hora, o tiempo indefinido."
    nueva = {"fecha": fecha, "hora": hora, "duracion_min": duracion_min, "minutos_extra": 0}
    inicio, fin = _inicio_de(nueva), _fin_previsto(nueva)
    c = _choque("usuario_id", beneficiario_id, inicio, fin, ACTIVOS)
    if c:
        return None, (f"Ya existe una cita ({c['tipo']}) {_rango_txt(c)} que se cruza con esta. "
                      "Elija otra hora o duración, o cancele la anterior.")
    with _transaccion() as tx:
        nuevo = _ejecutar(
            "INSERT INTO solicitudes(usuario_id, creado_por, tipo_id, fecha, hora, duracion_min, origen_id, "
            "destino_id, observaciones, estado_id) VALUES(?,?,?,?,?,?,?,?,?,"
            "(SELECT id FROM estados_cita WHERE nombre='Solicitada'))",
            (beneficiario_id, creador_id, _id_de("tipos_servicio", tipo, tx), fecha, hora, duracion_min,
             _id_de("lugares", origen, tx, "descripcion"), _id_de("lugares", destino, tx, "descripcion"),
             obs.strip()), tx)
        _ejecutar("INSERT INTO codigos_seguridad(solicitud_id, codigo, generado_en) VALUES(?,?,?)",
                  (nuevo, _nuevo_codigo_cita(), ahora_local().strftime("%Y-%m-%d %H:%M:%S")), tx)
    return nuevo, "Solicitud guardada."


def solicitudes_de(uid, historial=False):
    cond = "IN ('Finalizada','Cancelada')" if historial else "NOT IN ('Finalizada','Cancelada')"
    filas = _consultar(f"{BASE_SQL} WHERE {VISIBLES} AND es.nombre {cond} ORDER BY s.fecha DESC, s.hora DESC",
                       (uid, uid))
    activas = [f["id"] for f in filas if f["estado"] in ACTIVOS]
    codigos = {}
    if activas:  # el código solo viaja a quien pidió la cita (adulto mayor o familiar), nunca al acompañante
        marcas = ",".join("?" for _ in activas)
        codigos = {r["solicitud_id"]: r for r in _consultar(
            f"SELECT solicitud_id, codigo, intentos FROM codigos_seguridad WHERE solicitud_id IN ({marcas})", activas)}
    for f in filas:
        c = codigos.get(f["id"])
        f["codigo_seguridad"] = c["codigo"] if c else None
        f["codigo_bloqueado"] = bool(c and c["intentos"] >= MAX_INTENTOS_CODIGO)
    return filas


def todas():
    return _consultar(f"{BASE_SQL} ORDER BY s.id DESC")


def servicios_de(acomp_id):
    return _consultar(f"{BASE_SQL} WHERE s.acompanante_id=? ORDER BY s.fecha, s.hora", (acomp_id,))


def _marcar_tiempo(sid, columna, tx=None):
    ahora = ahora_local().strftime("%Y-%m-%d %H:%M:%S")
    _ejecutar(f"INSERT INTO ejecuciones(solicitud_id, {columna}) VALUES(?,?) "
              f"ON CONFLICT (solicitud_id) DO UPDATE SET {columna}=excluded.{columna}", (sid, ahora), tx)


def cambiar_estado(sid, nuevo, obs_final=None):
    c = _cita(sid)
    if not c or nuevo not in PERMITIDAS.get(c["estado"], []):
        return False
    with _transaccion() as tx:
        _ejecutar("UPDATE solicitudes SET estado_id=(SELECT id FROM estados_cita WHERE nombre=?) WHERE id=?",
                  (nuevo, sid), tx)
        if obs_final is not None:
            _ejecutar("UPDATE solicitudes SET obs_final=? WHERE id=?", (obs_final, sid), tx)
        if nuevo == "En curso":
            _marcar_tiempo(sid, "inicio_real", tx)
        elif nuevo == "Finalizada":  # la finaliza manualmente el acompañante: nunca se cierra sola
            _marcar_tiempo(sid, "fin_real", tx)
    return True


def cancelar(sid, uid):
    permitido = _consultar(f"SELECT 1 FROM solicitudes s WHERE s.id=? AND {VISIBLES}", (sid, uid, uid))
    return bool(permitido) and cambiar_estado(sid, "Cancelada")


# =====================================================================
#  CÓDIGO DE SEGURIDAD: sin él no se inicia el servicio, y con él se puede extender
# =====================================================================
def codigo_de(sid, uid):
    """El código de una cita, solo para quien la puede ver como adulto mayor o familiar vinculado."""
    r = _consultar(f"SELECT cs.codigo FROM solicitudes s JOIN codigos_seguridad cs ON cs.solicitud_id = s.id "
                   f"WHERE s.id=? AND {VISIBLES}", (sid, uid, uid))
    return r[0]["codigo"] if r else None


def regenerar_codigo(sid, uid):
    """Genera un código nuevo (por ejemplo, si se bloqueó o se lo dieron a quien no debía). Devuelve (ok, código|motivo)."""
    c = _cita(sid)
    if not c or not _consultar(f"SELECT 1 FROM solicitudes s WHERE s.id=? AND {VISIBLES}", (sid, uid, uid)):
        return False, "No puede generar el código de esta cita."
    if c["estado"] not in ACTIVOS:
        return False, "Esta cita ya terminó."
    nuevo = _nuevo_codigo_cita()
    _ejecutar("INSERT INTO codigos_seguridad(solicitud_id, codigo, generado_en) VALUES(?,?,?) "
              "ON CONFLICT (solicitud_id) DO UPDATE SET codigo=excluded.codigo, intentos=0, "
              "generado_en=excluded.generado_en", (sid, nuevo, ahora_local().strftime("%Y-%m-%d %H:%M:%S")))
    return True, nuevo


def _verificar_codigo(sid, codigo):
    r = _consultar("SELECT codigo, intentos FROM codigos_seguridad WHERE solicitud_id=?", (sid,))
    bloqueo = ("El código se bloqueó por demasiados intentos. Pídale al adulto mayor o a su familiar que genere "
               "un código nuevo desde su cita.")
    if not r:
        return False, "Esta cita no tiene código de seguridad. Pídale a quien la pidió que genere uno nuevo."
    if r[0]["intentos"] >= MAX_INTENTOS_CODIGO:
        return False, bloqueo
    if hmac.compare_digest(solo_digitos(codigo), r[0]["codigo"]):
        if r[0]["intentos"]:
            _ejecutar("UPDATE codigos_seguridad SET intentos=0 WHERE solicitud_id=?", (sid,))
        return True, ""
    _ejecutar("UPDATE codigos_seguridad SET intentos=intentos+1 WHERE solicitud_id=?", (sid,))
    quedan = MAX_INTENTOS_CODIGO - (r[0]["intentos"] + 1)
    if quedan <= 0:
        return False, bloqueo
    return False, f"Código incorrecto. Le {'quedan' if quedan > 1 else 'queda'} {quedan} intento{'s' if quedan > 1 else ''}."


# ---------- Inicio del servicio: en su hora (±MARGEN_INICIO_MIN) y con el código ----------
def ventana_inicio(fecha, hora):
    """(desde, hasta) como datetime: la hora de la cita menos y más el margen."""
    t = datetime.strptime(f"{fecha} {hora}", "%Y-%m-%d %H:%M")
    m = timedelta(minutes=MARGEN_INICIO_MIN)
    return t - m, t + m


def revisar_inicio(sid, acomp_id, ahora=None):
    """Comprueba asignación, estado y horario (sin pedir todavía el código). Devuelve (ok, mensaje)."""
    s = _cita(sid)
    if not s or s["acompanante_id"] != acomp_id:
        return False, "Este servicio no está asignado a usted."
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
    return True, ""


def iniciar_servicio(sid, acomp_id, codigo, ahora=None):
    ok, msg = revisar_inicio(sid, acomp_id, ahora)
    if not ok:
        return False, msg
    ok, msg = _verificar_codigo(sid, codigo)
    if not ok:
        return False, msg
    cambiar_estado(sid, "En curso")
    return True, "Servicio en curso."


# ---------- Extender el tiempo de un servicio en curso ----------
def _ampliar(sid, minutos, por_id):
    c = _cita(sid)
    if not c or c["estado"] != "En curso":
        return False, "Solo se puede extender un servicio que está en curso."
    if c["duracion_min"] is None:
        return False, ("Esta cita es de tiempo indefinido: no necesita extensión. "
                       "El acompañante la finaliza cuando termine.")
    if not (isinstance(minutos, int) and PASO_DURACION <= minutos <= EXTRA_MAXIMA and minutos % PASO_DURACION == 0):
        return False, "Elija un tiempo adicional válido: de media en media hora, hasta 4 horas."
    nuevo_fin = _fin_previsto(c) + timedelta(minutes=minutos)
    for campo, quien, estados in (("acompanante_id", "el acompañante", ("Asignada", "En curso")),
                                  ("usuario_id", "el adulto mayor", ACTIVOS)):
        o = _choque(campo, c[campo], _inicio_de(c), nuevo_fin, estados, excluir=sid)
        if o:
            return False, f"No se puede extender tanto: {quien} tiene otra cita ({o['tipo']}) {_punto(_rango_txt(o))}"
    _ejecutar("INSERT INTO ampliaciones(solicitud_id, minutos, pedida_por, fecha) VALUES(?,?,?,?)",
              (sid, minutos, por_id, ahora_local().strftime("%Y-%m-%d %H:%M:%S")))
    return True, f"Tiempo extendido. Nueva hora prevista de fin: {_punto(_h12(nuevo_fin.strftime('%H:%M')))}"


def ampliar_con_codigo(sid, acomp_id, codigo, minutos):
    """El acompañante extiende el servicio escribiendo el código de seguridad (lo autoriza el adulto mayor)."""
    c = _cita(sid)
    if not c or c["acompanante_id"] != acomp_id:
        return False, "Este servicio no está asignado a usted."
    if c["estado"] != "En curso":
        return False, "Solo se puede extender un servicio que está en curso."
    ok, msg = _verificar_codigo(sid, codigo)
    if not ok:
        return False, msg
    return _ampliar(sid, minutos, acomp_id)


def ampliar_cliente(sid, uid, minutos):
    """El adulto mayor (o su familiar vinculado) extiende el servicio desde su propia cuenta."""
    if not _consultar(f"SELECT 1 FROM solicitudes s WHERE s.id=? AND {VISIBLES}", (sid, uid, uid)):
        return False, "No puede extender esta cita."
    return _ampliar(sid, minutos, uid)


# ---------- Asignación sin cruces de horario ----------
def conflicto(acomp_id, sid):
    """Devuelve el servicio del acompañante que se cruza con la solicitud sid (o None)."""
    c = _cita(sid)
    if not c:
        return None
    return _choque("acompanante_id", acomp_id, _inicio_de(c), _fin_previsto(c), ("Asignada", "En curso"),
                   excluir=sid)


def _msg_cruce(c):
    return (f"Ese acompañante ya tiene un servicio ({c['tipo']}) {_rango_txt(c)} que se cruza con este. "
            "Elija otro acompañante u otro horario.")


def asignar(sid, acomp_id):
    c = _cita(sid)
    if not c or c["estado"] != "Solicitada":
        return False, "Esta solicitud ya no se puede asignar."
    o = conflicto(acomp_id, sid)
    if o:
        return False, _msg_cruce(o)
    with _transaccion() as tx:
        _ejecutar("UPDATE solicitudes SET estado_id=(SELECT id FROM estados_cita WHERE nombre='Asignada'), "
                  "acompanante_id=? WHERE id=?", (acomp_id, sid), tx)
    return True, "Acompañante asignado."


# =====================================================================
#  CALIFICACIONES (de 0 a 5 estrellas, en los dos sentidos)
# =====================================================================
def calificar(sid, de_id, puntaje):
    """El acompañante califica al adulto mayor; el adulto mayor o su familiar vinculado califican al acompañante."""
    try:
        puntaje = int(puntaje)
    except (TypeError, ValueError):
        return False, "Elija de 0 a 5 estrellas."
    if not 0 <= puntaje <= 5:
        return False, "Elija de 0 a 5 estrellas."
    s = _cita(sid)
    if not s or s["estado"] != "Finalizada":
        return False, "Solo se puede calificar un servicio finalizado."
    if de_id == s["acompanante_id"]:
        lado, a_id = "acompanante", s["usuario_id"]
    elif _consultar(f"SELECT 1 FROM solicitudes s WHERE s.id=? AND {VISIBLES}", (sid, de_id, de_id)):
        lado, a_id = "cliente", s["acompanante_id"]
    else:
        return False, "No puede calificar este servicio."
    try:
        _ejecutar("INSERT INTO calificaciones(solicitud_id, lado, de_id, a_id, puntaje) VALUES(?,?,?,?,?)",
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
    if _rol_de(actor_id) != "superadmin":
        raise PermissionError("Solo el super administrador puede hacer esto.")


def auditar(actor_id, accion, objetivo_id=None, detalle=""):
    _ejecutar("INSERT INTO auditoria(fecha, actor_id, accion_id, objetivo_id, detalle) VALUES(?,?,?,?,?)",
              (ahora_local().strftime("%Y-%m-%d %H:%M:%S"), actor_id, _id_de("tipos_accion", accion), objetivo_id,
               detalle))


def ultimas_auditorias(actor_id, n=100):
    _exigir_super(actor_id)
    return _consultar(
        "SELECT a.fecha, ta.nombre AS accion, a.detalle, pa.nombre AS actor, po.nombre AS objetivo "
        "FROM auditoria a JOIN tipos_accion ta ON ta.id = a.accion_id "
        "LEFT JOIN perfiles pa ON pa.usuario_id = a.actor_id LEFT JOIN perfiles po ON po.usuario_id = a.objetivo_id "
        "ORDER BY a.id DESC LIMIT ?", (n,))


def estadisticas(actor_id):
    _exigir_super(actor_id)
    por_rol = {r["clave"]: r["n"] for r in _consultar(
        "SELECT r.clave, COUNT(*) AS n FROM usuarios u JOIN roles r ON r.id = u.rol_id GROUP BY r.clave")}
    por_estado = {r["nombre"]: r["n"] for r in _consultar(
        "SELECT es.nombre, COUNT(*) AS n FROM solicitudes s JOIN estados_cita es ON es.id = s.estado_id "
        "GROUP BY es.nombre")}
    suspendidas = _consultar("SELECT COUNT(*) AS n FROM usuarios WHERE activo=0")[0]["n"]
    prom = _consultar("SELECT ROUND(AVG(puntaje), 1) AS p FROM calificaciones")[0]["p"]
    return {"por_rol": por_rol, "por_estado": por_estado, "suspendidas": suspendidas, "promedio": prom}


def listar_usuarios(actor_id, texto="", rol=""):
    _exigir_super(actor_id)
    sql = ("SELECT u.id, p.nombre, u.email, r.clave AS rol, u.activo FROM usuarios u "
           "JOIN roles r ON r.id = u.rol_id JOIN perfiles p ON p.usuario_id = u.id WHERE 1=1")
    args = []
    if (texto or "").strip():
        like = f"%{texto.strip()}%"
        sql += f" AND (p.nombre {COMO} ? OR u.email {COMO} ?)"
        args += [like, like]
    if rol in ROLES_TODOS:
        sql += " AND r.clave=?"
        args.append(rol)
    return _consultar(sql + " ORDER BY p.nombre LIMIT 100", args)


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
        quedan = _consultar("SELECT COUNT(*) AS n FROM usuarios x JOIN roles r ON r.id = x.rol_id "
                            "WHERE r.clave='superadmin' AND x.activo=1")[0]["n"]
        if u["rol"] == "superadmin" and quedan <= 1:
            return False, "Debe existir al menos un super administrador activo."
        with _transaccion() as tx:
            _ejecutar("UPDATE usuarios SET rol_id=? WHERE id=?", (_id_rol(rol, tx), uid), tx)
            if rol == "adulto_mayor" and not u.get("codigo"):
                _ejecutar("INSERT INTO codigos_familia(usuario_id, codigo) VALUES(?,?)", (uid, _codigo_nuevo(tx)), tx)
            if rol in ROLES_ADMIN:
                _ejecutar("UPDATE usuarios SET onboarding_completo=1 WHERE id=?", (uid,), tx)
        cambios.append(f"tipo de cuenta {u['rol']} -> {rol}")
    if datos:
        with _transaccion() as tx:
            _guardar_perfil(uid, datos, tx)
        tocados = sorted(k for k, v in datos.items() if v != (u.get(k) or ""))
        if tocados:  # en la auditoría se anotan los campos, nunca su contenido
            cambios.append("campos: " + ", ".join(tocados))
    auditar(actor_id, "editar_usuario", uid, "; ".join(cambios) or "sin cambios")
    return True, "Cambios guardados."


def cambiar_activo(actor_id, uid, activo):
    _exigir_super(actor_id)
    if uid == actor_id:
        return False, "No puede suspender su propia cuenta."
    if _rol_de(uid) is None:
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
    c = _cita(sid)
    if not c:
        return False, "No se encontró la cita."
    if estado not in ESTADOS:
        return False, "Estado no válido."
    if estado == "Solicitada":
        acomp_id = None
    elif estado == "Cancelada":
        acomp_id = acomp_id or c["acompanante_id"]
    elif not acomp_id:
        return False, "Elija un acompañante para ese estado."
    if acomp_id and estado in ("Asignada", "En curso"):
        o = _choque("acompanante_id", acomp_id, _inicio_de(c), _fin_previsto(c), ("Asignada", "En curso"),
                    excluir=sid)
        if o:
            return False, _msg_cruce(o)
    _ejecutar("UPDATE solicitudes SET estado_id=(SELECT id FROM estados_cita WHERE nombre=?), acompanante_id=? "
              "WHERE id=?", (estado, acomp_id, sid))
    auditar(actor_id, "editar_cita", c["usuario_id"],
            f"cita {sid}: estado {estado}, acompañante {acomp_id or 'ninguno'}")
    return True, "Cita actualizada."