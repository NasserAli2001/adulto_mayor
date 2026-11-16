import asyncio
import base64
import hashlib
import os
import re
import secrets
import smtplib
import sqlite3
import socket
import time

from email.message import EmailMessage
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

import flet as ft

from flet.auth.providers import GoogleOAuthProvider
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"), override=False)


# ==========================================================
# CONFIGURACIÓN
# ==========================================================

DB = Path(os.getenv("ACOMPANA_DB_PATH") or Path(__file__).with_name("acompanaplus.db"))
OTP_DEMO_MODE = os.getenv("OTP_DEMO_MODE", "false").lower() == "true"

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))

GOOGLE_COMPLETE_HTML = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Volver a Acompaña+</title>
<style>body{font-family:Arial,sans-serif;background:#f7f9fc;color:#183b56;
max-width:560px;margin:70px auto;padding:24px;line-height:1.6}
button{font-size:18px;padding:12px 24px;background:#2a9d8f;color:white;border:0;border-radius:8px}</style>
</head><body><h1>Continúa en Acompaña+</h1>
<p>Terminó el paso de acceso con Google. Vuelve a la ventana de Acompaña+ para continuar.</p>
<p>Si eres nuevo, allí podrás completar tu perfil. Si ya tienes una cuenta,
la aplicación te indicará si necesitas verificarla antes de vincularla.</p>
<button onclick="window.close()">Cerrar esta pestaña</button>
<p>Si el botón no cierra la pestaña, puedes cerrarla manualmente.</p>
<script>window.addEventListener('load', () => setTimeout(() => window.close(), 300));</script>
</body></html>"""


async def restore_desktop_window(page):
    # Run after the callback page loads, so the browser does not immediately
    # cover the desktop window again. This never grants or changes a session.
    await asyncio.sleep(0.8)
    try:
        page.window.minimized = False
        await page.window.to_front()
    except Exception:
        pass  # Window focus is optional; authentication must remain unaffected.


# ==========================================================
# BASE DE DATOS
# ==========================================================

@contextmanager
def conn():

    conexion = sqlite3.connect(DB)

    conexion.row_factory = sqlite3.Row

    try:
        with conexion:
            yield conexion
    finally:
        conexion.close()


# ==========================================================
# SEGURIDAD DE CONTRASEÑAS
# ==========================================================

def pwd_hash(password, salt=None):

    salt = salt or secrets.token_bytes(16)

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        salt,
        200_000
    )

    return (
        base64.b64encode(salt).decode(),
        base64.b64encode(digest).decode()
    )


def pwd_ok(password, salt_b64, hash_b64):

    salt = base64.b64decode(salt_b64)

    _, actual = pwd_hash(
        password,
        salt
    )

    return secrets.compare_digest(
        actual,
        hash_b64
    )


# ==========================================================
# CREACIÓN DE BASE DE DATOS
# ==========================================================

def init_db():

    with conn() as c:

        c.executescript(
            """

            CREATE TABLE IF NOT EXISTS users(

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                name TEXT NOT NULL,

                email TEXT NOT NULL UNIQUE,

                phone TEXT NOT NULL,

                caregiver_phone TEXT,

                salt TEXT,

                password_hash TEXT,

                role TEXT NOT NULL,

                whatsapp_permission INTEGER NOT NULL DEFAULT 0

            );


            CREATE TABLE IF NOT EXISTS requests(

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                user_id INTEGER NOT NULL,

                type TEXT NOT NULL,

                date TEXT NOT NULL,

                time TEXT NOT NULL,

                origin TEXT NOT NULL,

                destination TEXT NOT NULL,

                notes TEXT,

                status TEXT NOT NULL DEFAULT 'Solicitada',

                companion_id INTEGER,

                FOREIGN KEY(user_id)
                    REFERENCES users(id),

                FOREIGN KEY(companion_id)
                    REFERENCES users(id)

            );

            """
        )

    with conn() as c:
        columns = {row["name"] for row in c.execute("PRAGMA table_info(users)")}
        if "google_sub" not in columns:
            c.execute("ALTER TABLE users ADD COLUMN google_sub TEXT")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_google_sub ON users(google_sub)")
    # Existing accounts are preserved; new databases never get default passwords.


def seed(
    name,
    email,
    phone,
    password,
    role,
    whatsapp
):

    with conn() as c:

        existe = c.execute(

            """
            SELECT id
            FROM users
            WHERE email=?
            """,

            (email,)

        ).fetchone()

        if existe:

            return

        salt, password_hash = pwd_hash(
            password
        )

        c.execute(

            """

            INSERT INTO users(

                name,
                email,
                phone,
                caregiver_phone,
                salt,
                password_hash,
                role,
                whatsapp_permission

            )

            VALUES(?,?,?,?,?,?,?,?)

            """,

            (

                name,

                email,

                phone,

                None,

                salt,

                password_hash,

                role,

                whatsapp

            )
        )


# ==========================================================
# VALIDACIONES
# ==========================================================

def digits(value):

    return re.sub(
        r"\D",
        "",
        value or ""
    )


def valid_phone(value):

    cantidad = len(
        digits(value)
    )

    return 10 <= cantidad <= 15


def valid_email(value):

    return bool(

        re.fullmatch(

            r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",

            (value or "").strip()

        )
    )


def valid_password(value):

    value = value or ""

    return (

        len(value) >= 8

        and any(
            x.islower()
            for x in value
        )

        and any(
            x.isupper()
            for x in value
        )

        and any(
            x.isdigit()
            for x in value
        )

    )


# ==========================================================
# WHATSAPP
# ==========================================================

def wa_url(
    phone,
    message
):

    phone = digits(
        phone
    )

    # Si es celular colombiano,
    # agregamos código de país +57

    if (
        len(phone) == 10
        and phone.startswith("3")
    ):

        phone = "57" + phone

    return (

        f"https://wa.me/{phone}"

        f"?text={quote(message)}"

    )


# ==========================================================
# DOBLE VERIFICACIÓN
# ==========================================================

def send_otp(
    email,
    code
):

    if (
        not SMTP_USER
        or not SMTP_PASSWORD
    ):

        return False

    mensaje = EmailMessage()

    mensaje["Subject"] = (
        "Código de verificación Acompaña+"
    )

    mensaje["From"] = SMTP_USER

    mensaje["To"] = email

    mensaje.set_content(

        f"""
Tu código de verificación es:

{code}

Vence en 5 minutos.

Acompaña+
"""
    )

    try:

        with smtplib.SMTP(
            SMTP_HOST,
            SMTP_PORT,
            timeout=15
        ) as servidor:

            servidor.starttls()

            servidor.login(
                SMTP_USER,
                SMTP_PASSWORD
            )

            servidor.send_message(
                mensaje
            )

        return True

    except (OSError, smtplib.SMTPException):

        return False


# ==========================================================
# APLICACIÓN
# ==========================================================

PUBLIC_ROLES = ("Adulto mayor", "Familiar", "Acompañante")


def google_identity(user):
    # Only use userinfo retrieved by Flet from Google's authenticated endpoint.
    sub, email = user["sub"], user["email"]
    if user["email_verified"] is not True or not isinstance(sub, str) or not sub or not valid_email(email):
        raise ValueError("Identidad de Google inválida")
    return {"sub": sub, "email": email.strip().lower(), "name": user.get("name", "") or ""}


def create_google_profile(identity, name, role, phone, caregiver, whatsapp):
    name, phone, caregiver = (name or "").strip(), digits(phone), digits(caregiver)
    if len(name) < 3:
        raise ValueError("Escribe tu nombre completo.")
    if role not in PUBLIC_ROLES:
        raise ValueError("Selecciona un tipo de usuario válido.")
    if not valid_phone(phone):
        raise ValueError("El teléfono debe tener entre 10 y 15 dígitos.")
    if (role == "Adulto mayor" or caregiver) and not valid_phone(caregiver):
        raise ValueError("Indica un teléfono válido del cuidador/contacto de confianza.")
    with conn() as c:
        c.execute("BEGIN IMMEDIATE")
        if c.execute("SELECT id FROM users WHERE lower(email)=lower(?)", (identity["email"],)).fetchone():
            raise sqlite3.IntegrityError("Cuenta existente")
        cursor = c.execute("""INSERT INTO users
            (name,email,phone,caregiver_phone,role,whatsapp_permission,google_sub)
            VALUES(?,?,?,?,?,?,?)""", (name, identity["email"], phone, caregiver or None,
                                      role, int(bool(whatsapp)), identity["sub"]))
        return c.execute("SELECT * FROM users WHERE id=?", (cursor.lastrowid,)).fetchone()


def link_google_account(user_id, sub):
    # Called only after the existing account's password and OTP are verified.
    with conn() as c:
        cursor = c.execute("UPDATE users SET google_sub=? WHERE id=? AND google_sub IS NULL", (sub, user_id))
        if cursor.rowcount != 1:
            raise ValueError("Cuenta ya vinculada")
        return c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()


def main(page: ft.Page):

    init_db()

    page.title = "Acompaña+"

    page.theme_mode = (
        ft.ThemeMode.LIGHT
    )

    page.bgcolor = "#F7F9FC"

    # Estado de la sesión

    state = {

        "user": None,

        "otp": None,
        "google_pending": None,
        "google_flow": False

    }


    # ======================================================
    # GOOGLE LOGIN
    # ======================================================

    google = None

    if (
        GOOGLE_CLIENT_ID
        and GOOGLE_CLIENT_SECRET
    ):

        google = GoogleOAuthProvider(

            client_id=GOOGLE_CLIENT_ID,

            client_secret=
                GOOGLE_CLIENT_SECRET,

            redirect_url=
                "http://localhost:8550/oauth_callback"

        )


    # ======================================================
    # MENSAJES
    # ======================================================

    def toast(text):

        page.show_dialog(

            ft.SnackBar(

                ft.Text(text),

                behavior=
                    ft.SnackBarBehavior.FLOATING

            )
        )


    # ======================================================
    # CAMBIO DE PANTALLA + SCROLLING
    # ======================================================

    def screen(*controls):

        page.clean()

        page.add(

            ft.SafeArea(

                expand=True,

                content=ft.Container(

                    width=720,

                    padding=25,

                    expand=True,

                    content=ft.Column(

                        list(controls),

                        spacing=15,

                        # AQUÍ ACTIVAMOS SCROLL
                        scroll=
                            ft.ScrollMode.AUTO,

                        expand=True

                    )

                )

            )
        )

        page.update()


    # ======================================================
    # ENCABEZADOS
    # ======================================================

    def header(
        title,
        subtitle=""
    ):

        return ft.Column(

            [

                ft.Text(

                    title,

                    size=30,

                    weight=
                        ft.FontWeight.BOLD,

                    color="#183B56"

                ),

                ft.Text(

                    subtitle,

                    size=16,

                    color="#52606D"

                )

                if subtitle

                else ft.Container()

            ],

            spacing=5

        )


    # ======================================================
    # CONSULTA DE USUARIOS
    # ======================================================

    def get_user(email):

        with conn() as c:

            return c.execute(

                """

                SELECT *

                FROM users

                WHERE lower(email)
                =
                lower(?)

                """,

                (
                    email.strip(),
                )

            ).fetchone()


    # ======================================================
    # DASHBOARD SEGÚN ROL
    # ======================================================

    def dashboard():

        user = state["user"]

        if user["role"] in (

            "Adulto mayor",
            "Familiar"

        ):

            user_home()

        elif (
            user["role"]
            == "Acompañante"
        ):

            companion_home()

        elif user["role"] == "Administrador":
            admin_home()
        else:
            login()


    # ======================================================
    # BIENVENIDA
    # ======================================================

    def welcome():
        state["otp"] = None
        state["google_pending"] = None
        state["google_flow"] = False

        screen(

            ft.Icon(

                ft.Icons.FAVORITE,

                size=70,

                color="#2A9D8F"

            ),

            ft.Text(

                "Acompaña+",

                size=42,

                weight=
                    ft.FontWeight.BOLD,

                color="#183B56"

            ),

            ft.Text(

                "Una mano confiable para que "
                "la edad nunca sea un "
                "obstáculo para vivir.",

                size=18,

                color="#52606D"

            ),

            ft.Button(

                "Iniciar sesión",

                icon=ft.Icons.LOGIN,

                on_click=
                    lambda e: login()

            ),

            ft.Button(

                "Crear cuenta",

                icon=ft.Icons.PERSON_ADD,

                on_click=
                    lambda e: register()

            )

        )


    # ======================================================
    # REGISTRO
    # ======================================================

    def register():
        state["otp"] = None
        state["google_pending"] = None
        state["google_flow"] = False

        # CAPTCHA sencillo
        # para versión prototipo

        a = secrets.randbelow(8) + 1

        b = secrets.randbelow(8) + 1


        name = ft.TextField(

            label="Nombre completo"

        )


        email = ft.TextField(

            label="Correo electrónico"

        )


        phone = ft.TextField(

            label="Teléfono",

            hint_text=
                "Mínimo 10 dígitos"

        )


        caregiver = ft.TextField(

            label=
                "Teléfono del cuidador/"
                "contacto de confianza",

            hint_text=
                "Obligatorio para "
                "adulto mayor"

        )


        password = ft.TextField(

            label="Contraseña",

            password=True,

            can_reveal_password=True

        )


        confirm = ft.TextField(

            label=
                "Confirmar contraseña",

            password=True,

            can_reveal_password=True

        )


        role = ft.Dropdown(

            label="Tipo de usuario",

            options=[

                ft.DropdownOption(

                    key="Adulto mayor",

                    text="Adulto mayor"

                ),

                ft.DropdownOption(

                    key="Familiar",

                    text=
                        "Familiar / cuidador"

                ),

                ft.DropdownOption(

                    key="Acompañante",

                    text="Acompañante"

                )

            ]

        )


        whatsapp = ft.Checkbox(

            label=(

                "Autorizo contacto por "
                "WhatsApp para coordinar "
                "el servicio."

            ),

            value=False

        )


        captcha = ft.TextField(

            label=(

                "Verificación humana: "
                f"¿cuánto es {a} + {b}?"

            )

        )


        def save(e):

            mail = (
                email.value or ""
            ).strip().lower()

            phone_value = digits(
                phone.value
            )

            caregiver_value = digits(
                caregiver.value
            )

            password_value = (
                password.value or ""
            )

            errors = []


            # Nombre

            if len(
                (
                    name.value or ""
                ).strip()
            ) < 3:

                errors.append(
                    "Nombre inválido."
                )


            # Correo

            if not valid_email(mail):

                errors.append(
                    "Correo inválido."
                )


            # Celular

            if not valid_phone(
                phone_value
            ):

                errors.append(

                    "El celular debe tener "
                    "mínimo 10 dígitos."

                )


            # Cuidador obligatorio
            # para adulto mayor

            if (

                role.value
                == "Adulto mayor"

                and not valid_phone(
                    caregiver_value
                )

            ):

                errors.append(

                    "Falta teléfono válido "
                    "del cuidador."

                )


            elif (

                caregiver_value

                and not valid_phone(
                    caregiver_value
                )

            ):

                errors.append(

                    "Teléfono del cuidador "
                    "inválido."

                )


            # Contraseña robusta

            if not valid_password(
                password_value
            ):

                errors.append(

                    "La contraseña debe tener "
                    "mínimo 8 caracteres, "
                    "una mayúscula, una "
                    "minúscula y un número."

                )


            # Confirmación contraseña

            if (

                password_value

                != (
                    confirm.value or ""
                )

            ):

                errors.append(

                    "Las contraseñas "
                    "no coinciden."

                )


            # Rol

            if role.value not in (

                "Adulto mayor",
                "Familiar",
                "Acompañante"

            ):

                errors.append(

                    "Selecciona tipo "
                    "de usuario."

                )


            # CAPTCHA

            if (

                (
                    captcha.value or ""
                ).strip()

                != str(a + b)

            ):

                errors.append(

                    "Verificación humana "
                    "incorrecta."

                )


            # Correo duplicado

            if get_user(mail):

                errors.append(

                    "Ese correo ya está "
                    "registrado."

                )


            if errors:

                toast(
                    " ".join(errors)
                )

                return


            salt, password_hash = (
                pwd_hash(
                    password_value
                )
            )


            with conn() as c:

                c.execute(

                    """

                    INSERT INTO users(

                        name,
                        email,
                        phone,
                        caregiver_phone,
                        salt,
                        password_hash,
                        role,
                        whatsapp_permission

                    )

                    VALUES(
                        ?,?,?,?,?,?,?,?
                    )

                    """,

                    (

                        (
                            name.value
                            or ""
                        ).strip(),

                        mail,

                        phone_value,

                        caregiver_value
                        or None,

                        salt,

                        password_hash,

                        role.value,

                        int(
                            bool(
                                whatsapp.value
                            )
                        )

                    )

                )


            toast(
                "Cuenta creada correctamente."
            )

            login()


        screen(

            header(

                "Crear cuenta",

                "Validación de campos y "
                "consentimiento de contacto."

            ),

            name,

            email,

            phone,

            caregiver,

            password,

            confirm,

            role,

            whatsapp,

            captcha,

            ft.Button(

                "Crear mi cuenta",

                icon=
                    ft.Icons.PERSON_ADD,

                on_click=save

            ),

            ft.TextButton(

                "Volver",

                on_click=
                    lambda e: welcome()

            )

        )


    # ======================================================
    # DOBLE VERIFICACIÓN
    # ======================================================

    def start_2fa(user, link_sub=None):
        state["otp"] = None
        code = f"{secrets.randbelow(1_000_000):06d}"
        sent = send_otp(user["email"], code)
        if not sent and not OTP_DEMO_MODE:
            toast("No se pudo enviar el código. Revisa la configuración de correo e intenta nuevamente.")
            return
        state["otp"] = {"user": user, "code": code, "expires": time.monotonic() + 300,
                        "sent": sent, "attempts": 0, "link_sub": link_sub}
        otp_screen()

    def otp_screen():
        data = state["otp"]
        field = ft.TextField(label="Código de 6 dígitos", max_length=6)

        def verify(e):
            if state["otp"] is not data:
                return
            if time.monotonic() >= data["expires"] or data["attempts"] >= 5:
                login()
                toast("Código vencido o límite de intentos alcanzado. Inicia sesión nuevamente.")
                return
            data["attempts"] += 1
            entered = (field.value or "").strip()
            if not re.fullmatch(r"[0-9]{6}", entered) or not secrets.compare_digest(entered, data["code"]):
                if data["attempts"] >= 5:
                    login()
                toast("Código incorrecto. Máximo cinco intentos.")
                return
            user = data["user"]
            if data["link_sub"]:
                try:
                    user = link_google_account(user["id"], data["link_sub"])
                except (ValueError, sqlite3.IntegrityError):
                    login()
                    toast("No se pudo vincular esta cuenta. Inicia sesión nuevamente.")
                    return
            state["otp"] = None
            state["google_pending"] = None
            state["user"] = user
            dashboard()

        info = "Código enviado al correo."
        if not data["sent"]:
            info = f"DEMOSTRACIÓN LOCAL: código {data['code']}. Este modo no verifica el correo."
        screen(header("Doble verificación", "El código vence en cinco minutos."), ft.Text(info), field,
               ft.Button("Verificar", on_click=verify),
               ft.TextButton("Cancelar", on_click=lambda e: login()))

    async def google_login(e):
        if not google:
            toast("El acceso con Google no está disponible en este momento. Intenta más tarde.")
            return
        state["user"] = None
        state["otp"] = None
        state["google_pending"] = None
        state["google_flow"] = True
        try:
            await page.login(google, scope=["openid", "email", "profile"],
                             complete_page_html=GOOGLE_COMPLETE_HTML)
        except Exception:
            state["google_flow"] = False
            toast("No se pudo abrir Google. Intenta nuevamente.")

    async def on_google_login(e):
        if not state["google_flow"]:
            return
        state["google_flow"] = False
        state["google_pending"] = None
        if e.error:
            toast("El acceso con Google fue cancelado o no se pudo completar.")
            return
        try:
            identity = google_identity(page.auth.user)
        except (ValueError, TypeError, KeyError, AttributeError):
            page.logout()
            toast("Google no devolvió una identidad con correo verificado.")
            return
        if not page.web:
            page.run_task(restore_desktop_window, page)
            try:
                await page.window.to_front()
            except Exception:
                # Window focus is optional; it must never prevent authentication.
                pass
        with conn() as c:
            user = c.execute("SELECT * FROM users WHERE google_sub=?", (identity["sub"],)).fetchone()
        if user:
            state["user"] = user
            dashboard()
            return
        state["google_pending"] = identity
        existing = get_user(identity["email"])
        if existing:
            link_screen(existing, identity)
        else:
            google_profile(identity)

    def link_screen(user, identity):
        password = ft.TextField(label="Contraseña de tu cuenta Acompaña+", password=True,
                                can_reveal_password=True)

        def verify_password(e):
            if state["google_pending"] is not identity:
                return
            if user["google_sub"] or not user["salt"] or not pwd_ok(password.value or "", user["salt"], user["password_hash"]):
                toast("No se pudo verificar esta cuenta. Usa su método habitual de acceso.")
                return
            start_2fa(user, link_sub=identity["sub"])

        screen(header("Vincular con Google", "Ya existe una cuenta con este correo. Confirma tu contraseña y el código enviado por correo."),
               ft.Text(identity["email"]), password,
               ft.Button("Verificar y vincular", on_click=verify_password),
               ft.TextButton("Cancelar", on_click=logout))

    def google_profile(identity):
        name = ft.TextField(label="Nombre completo", value=identity["name"])
        role = ft.Dropdown(label="Tipo de usuario", options=[ft.DropdownOption(key=r, text=r) for r in PUBLIC_ROLES])
        phone = ft.TextField(label="Teléfono (10 a 15 dígitos)")
        caregiver = ft.TextField(label="Teléfono del cuidador/contacto de confianza",
                                 hint_text="Obligatorio para adulto mayor; opcional para los demás roles")
        whatsapp = ft.Checkbox(label="Autorizo el contacto por WhatsApp para mis acompañamientos", value=False)

        def save(e):
            if state["google_pending"] is not identity:
                return
            try:
                user = create_google_profile(identity, name.value, role.value, phone.value, caregiver.value, whatsapp.value)
            except ValueError as error:
                toast(str(error))
                return
            except sqlite3.IntegrityError:
                login()
                toast("La cuenta ya fue registrada. Inicia sesión nuevamente para continuar.")
                return
            state["google_pending"] = None
            state["user"] = user
            dashboard()

        screen(header("Completa tu perfil de Acompaña+", "Tu identidad ya fue verificada por Google."),
               ft.Text(identity["email"]), name, role, phone, caregiver, whatsapp,
               ft.Button("Guardar perfil y entrar", on_click=save),
               ft.TextButton("Cancelar", on_click=logout))

    page.on_login = on_google_login

    # ======================================================
    # LOGIN
    # ======================================================

    def login():
        state["otp"] = None
        state["google_pending"] = None
        state["google_flow"] = False

        email = ft.TextField(

            label="Correo electrónico"

        )


        password = ft.TextField(

            label="Contraseña",

            password=True,

            can_reveal_password=True

        )


        def sign_in(e):

            user = get_user(

                (
                    email.value or ""
                ).strip().lower()

            )


            if (

                not user

                or not user["salt"]

                or not pwd_ok(

                    password.value or "",

                    user["salt"],

                    user[
                        "password_hash"
                    ]

                )

            ):

                toast(

                    "Correo o contraseña "
                    "incorrectos."

                )

                return


            start_2fa(user)


        screen(

            header(

                "Iniciar sesión",

                "Acceso seguro "
                "a Acompaña+."

            ),

            email,

            password,

            ft.Button(

                "Ingresar",

                icon=ft.Icons.LOGIN,

                on_click=sign_in

            ),

            ft.Button(

                "Continuar con Google",

                icon=
                    ft.Icons.ACCOUNT_CIRCLE,

                on_click=google_login

            ),

            ft.TextButton(

                "Crear cuenta",

                on_click=
                    lambda e: register()

            ),

            ft.TextButton(

                "Volver",

                on_click=
                    lambda e: welcome()

            )

        )


    # ======================================================
    # NUEVA SOLICITUD
    # ======================================================

    def new_request():

        kind = ft.Dropdown(

            label=
                "Tipo de acompañamiento",

            options=[

                ft.DropdownOption(
                    key="Cita médica",
                    text="Cita médica"
                ),

                ft.DropdownOption(
                    key="Diligencia bancaria",
                    text="Diligencia bancaria"
                ),

                ft.DropdownOption(
                    key="Compras",
                    text="Compras"
                ),

                ft.DropdownOption(
                    key="Trámite",
                    text="Trámite"
                ),

                ft.DropdownOption(
                    key="Otro",
                    text="Otro"
                )

            ]

        )


        date = ft.TextField(

            label="Fecha",

            hint_text="30/09/2026"

        )


        hour = ft.TextField(

            label="Hora",

            hint_text="10:30 a. m."

        )


        origin = ft.TextField(

            label="Origen"

        )


        destination = ft.TextField(

            label="Destino"

        )


        notes = ft.TextField(

            label="Observaciones",

            multiline=True,

            min_lines=3,

            max_lines=5

        )


        def save(e):

            if not all(

                [

                    kind.value,

                    date.value,

                    hour.value,

                    origin.value,

                    destination.value

                ]

            ):

                toast(

                    "Completa todos los "
                    "campos obligatorios."

                )

                return


            with conn() as c:

                c.execute(

                    """

                    INSERT INTO requests(

                        user_id,
                        type,
                        date,
                        time,
                        origin,
                        destination,
                        notes,
                        status

                    )

                    VALUES(
                        ?,?,?,?,?,?,?,
                        'Solicitada'
                    )

                    """,

                    (

                        state[
                            "user"
                        ]["id"],

                        kind.value,

                        date.value.strip(),

                        hour.value.strip(),

                        origin.value.strip(),

                        destination.value.strip(),

                        (
                            notes.value
                            or ""
                        ).strip()

                    )

                )


            toast(

                "Solicitud guardada "
                "en base de datos."

            )

            user_home()


        screen(

            header(

                "Nueva solicitud",

                "La información quedará "
                "almacenada."

            ),

            kind,

            date,

            hour,

            origin,

            destination,

            notes,

            ft.Button(

                "Confirmar solicitud",

                icon=ft.Icons.CHECK,

                on_click=save

            ),

            ft.TextButton(

                "Cancelar",

                on_click=
                    lambda e:
                    user_home()

            )

        )


    # ======================================================
    # SOLICITUDES DEL USUARIO
    # ======================================================

    def user_requests():

        user = state["user"]


        with conn() as c:

            rows = c.execute(

                """

                SELECT

                    r.*,

                    a.name
                    companion_name,

                    a.phone
                    companion_phone,

                    a.whatsapp_permission
                    companion_wa

                FROM requests r

                LEFT JOIN users a

                    ON a.id
                    =
                    r.companion_id

                WHERE r.user_id=?

                ORDER BY r.id DESC

                """,

                (
                    user["id"],
                )

            ).fetchall()


        controls = [

            header(

                "Mis acompañamientos",

                "Estado y contacto directo "
                "del acompañante."

            )

        ]


        if not rows:

            controls.append(

                ft.Text(

                    "Todavía no tienes "
                    "solicitudes."

                )

            )


        for request in rows:

            items = [

                ft.Text(

                    f"Servicio "
                    f"#{request['id']}",

                    weight=
                        ft.FontWeight.BOLD

                ),

                ft.Text(

                    f"{request['type']} - "
                    f"{request['date']} "
                    f"{request['time']}"

                ),

                ft.Text(

                    f"Estado: "
                    f"{request['status']}"

                ),

                ft.Text(

                    f"Origen: "
                    f"{request['origin']}"

                ),

                ft.Text(

                    f"Destino: "
                    f"{request['destination']}"

                )

            ]


            # Si ya existe acompañante

            if request[
                "companion_name"
            ]:

                items.extend(

                    [

                        ft.Divider(),

                        ft.Text(

                            "Contacto del "
                            "acompañante",

                            weight=
                                ft.FontWeight.BOLD

                        ),

                        ft.Text(

                            f"Nombre: "
                            f"{request['companion_name']}"

                        ),

                        ft.Text(

                            f"Teléfono: "
                            f"{request['companion_phone']}"

                        )

                    ]

                )


                # Solo mostramos WhatsApp
                # si el acompañante lo autorizó

                if request[
                    "companion_wa"
                ]:

                    items.append(

                        ft.Button(

                            "Contactar por "
                            "WhatsApp",

                            icon=
                                ft.Icons.CHAT,

                            action=ft.OpenUrl(

                                wa_url(

                                    request[
                                        "companion_phone"
                                    ],

                                    (
                                        "Hola, te contacto "
                                        "desde Acompaña+ "
                                        "por el servicio "
                                        f"#{request['id']}."
                                    )

                                )

                            )

                        )

                    )


            else:

                items.append(

                    ft.Text(

                        "Pendiente de "
                        "asignación."

                    )

                )


            controls.append(

                ft.Card(

                    content=ft.Container(

                        padding=18,

                        content=ft.Column(
                            items
                        )

                    )

                )

            )


        controls.append(

            ft.Button(

                "Volver",

                on_click=
                    lambda e:
                    user_home()

            )

        )


        screen(*controls)


    # ======================================================
    # HOME USUARIO
    # ======================================================

    def user_home():

        user = state["user"]

        screen(

            header(

                f"Hola, "
                f"{user['name']}",

                "¿Qué necesitas "
                "hacer hoy?"

            ),

            ft.Button(

                "Nueva solicitud",

                icon=ft.Icons.ADD,

                on_click=
                    lambda e:
                    new_request()

            ),

            ft.Button(

                "Ver mis solicitudes",

                icon=ft.Icons.SEARCH,

                on_click=
                    lambda e:
                    user_requests()

            ),

            ft.Button(

                "Cerrar sesión",

                icon=ft.Icons.LOGOUT,

                on_click=
                    logout

            )

        )


    # ======================================================
    # CERRAR SESIÓN
    # ======================================================

    async def logout(e=None):
        state["user"] = None
        state["otp"] = None
        state["google_pending"] = None
        state["google_flow"] = False
        if page.auth:
            page.logout()
        welcome()

    # ======================================================
    # ADMINISTRADOR
    # ======================================================

    def admin_home():

        with conn() as c:

            requests = c.execute(

                """

                SELECT

                    r.*,

                    u.name requester,

                    u.phone requester_phone,

                    u.caregiver_phone

                FROM requests r

                JOIN users u

                    ON u.id
                    =
                    r.user_id

                ORDER BY r.id DESC

                """

            ).fetchall()


            companions = c.execute(

                """

                SELECT *

                FROM users

                WHERE role='Acompañante'

                ORDER BY name

                """

            ).fetchall()


        controls = [

            header(

                "Panel administrativo",

                "Asigna acompañantes "
                "a las solicitudes."

            )

        ]


        for request in requests:

            selector = ft.Dropdown(

                label="Acompañante",

                options=[

                    ft.DropdownOption(

                        key=str(
                            companion["id"]
                        ),

                        text=(

                            f"{companion['name']} "
                            f"- "
                            f"{companion['phone']}"

                        )

                    )

                    for companion
                    in companions

                ]

            )


            def assign(
                e,
                request_id=
                    request["id"],
                select=selector
            ):

                if not select.value:

                    toast(

                        "Selecciona "
                        "acompañante."

                    )

                    return


                with conn() as c:

                    c.execute(

                        """

                        UPDATE requests

                        SET
                            companion_id=?,
                            status='Asignada'

                        WHERE id=?

                        """,

                        (

                            int(
                                select.value
                            ),

                            request_id

                        )

                    )


                admin_home()


            controls.append(

                ft.Card(

                    content=
                        ft.Container(

                            padding=18,

                            content=
                                ft.Column(

                                    [

                                        ft.Text(

                                            f"Solicitud "
                                            f"#{request['id']} "
                                            f"- "
                                            f"{request['requester']}",

                                            weight=
                                                ft.FontWeight.BOLD

                                        ),

                                        ft.Text(

                                            f"Teléfono: "
                                            f"{request['requester_phone']}"

                                        ),

                                        ft.Text(

                                            "Cuidador: "
                                            f"{request['caregiver_phone'] or 'No registrado'}"

                                        ),

                                        ft.Text(

                                            f"{request['type']} "
                                            f"- "
                                            f"{request['status']}"

                                        ),

                                        selector,

                                        ft.Button(

                                            "Asignar",

                                            icon=
                                                ft.Icons.PERSON_ADD,

                                            on_click=
                                                assign

                                        )

                                    ]

                                )

                        )

                )

            )


        controls.append(

            ft.Button(

                "Cerrar sesión",

                on_click=
                    logout

            )

        )


        screen(*controls)


    # ======================================================
    # ACOMPAÑANTE
    # ======================================================

    def companion_home():

        user = state["user"]


        with conn() as c:

            rows = c.execute(

                """

                SELECT

                    r.*,

                    u.name requester,

                    u.phone requester_phone,

                    u.caregiver_phone,

                    u.whatsapp_permission
                    requester_wa

                FROM requests r

                JOIN users u

                    ON u.id
                    =
                    r.user_id

                WHERE
                    r.companion_id=?

                ORDER BY r.id DESC

                """,

                (
                    user["id"],
                )

            ).fetchall()


        controls = [

            header(

                f"Hola, {user['name']}",

                "Estos son tus "
                "servicios asignados."

            )

        ]


        if not rows:

            controls.append(

                ft.Text(

                    "No tienes servicios "
                    "asignados."

                )

            )


        for request in rows:

            items = [

                ft.Text(

                    f"Servicio "
                    f"#{request['id']}",

                    weight=
                        ft.FontWeight.BOLD

                ),

                ft.Text(

                    f"Solicitante: "
                    f"{request['requester']}"

                ),

                ft.Text(

                    f"{request['type']} "
                    f"- "
                    f"{request['date']} "
                    f"{request['time']}"

                ),

                ft.Text(

                    f"Origen: "
                    f"{request['origin']}"

                ),

                ft.Text(

                    f"Destino: "
                    f"{request['destination']}"

                ),

                ft.Text(

                    f"Estado: "
                    f"{request['status']}"

                ),

                ft.Divider(),

                ft.Text(

                    f"Teléfono solicitante: "
                    f"{request['requester_phone']}"

                ),

                ft.Text(

                    f"Teléfono cuidador: "
                    f"{request['caregiver_phone'] or 'No registrado'}"

                )

            ]


            # WhatsApp únicamente
            # con consentimiento

            if request[
                "requester_wa"
            ]:

                items.append(

                    ft.Button(

                        "WhatsApp "
                        "del solicitante",

                        icon=
                            ft.Icons.CHAT,

                        action=
                            ft.OpenUrl(

                                wa_url(

                                    request[
                                        "requester_phone"
                                    ],

                                    (

                                        "Hola, soy tu "
                                        "acompañante de "
                                        "Acompaña+ para "
                                        "el servicio "
                                        f"#{request['id']}."

                                    )

                                )

                            )

                    )

                )


                if request[
                    "caregiver_phone"
                ]:

                    items.append(

                        ft.Button(

                            "WhatsApp "
                            "del cuidador",

                            icon=
                                ft.Icons.CHAT,

                            action=
                                ft.OpenUrl(

                                    wa_url(

                                        request[
                                            "caregiver_phone"
                                        ],

                                        (

                                            "Hola, soy el "
                                            "acompañante "
                                            "asignado al "
                                            "servicio "
                                            f"#{request['id']} "
                                            "de Acompaña+."

                                        )

                                    )

                                )

                        )

                    )


            else:

                items.append(

                    ft.Text(

                        "El usuario no autorizó "
                        "contacto por WhatsApp."

                    )

                )


            # Iniciar servicio

            if (
                request["status"]
                == "Asignada"
            ):

                def start(
                    e,
                    request_id=
                        request["id"]
                ):

                    with conn() as c:

                        c.execute(

                            """

                            UPDATE requests

                            SET status=
                                'En curso'

                            WHERE id=?

                            """,

                            (
                                request_id,
                            )

                        )


                    companion_home()


                items.append(

                    ft.Button(

                        "Iniciar "
                        "acompañamiento",

                        on_click=start

                    )

                )


            # Finalizar servicio

            elif (
                request["status"]
                == "En curso"
            ):

                def finish(
                    e,
                    request_id=
                        request["id"]
                ):

                    with conn() as c:

                        c.execute(

                            """

                            UPDATE requests

                            SET status=
                                'Finalizada'

                            WHERE id=?

                            """,

                            (
                                request_id,
                            )

                        )


                    companion_home()


                items.append(

                    ft.Button(

                        "Finalizar "
                        "acompañamiento",

                        on_click=finish

                    )

                )


            controls.append(

                ft.Card(

                    content=
                        ft.Container(

                            padding=18,

                            content=
                                ft.Column(
                                    items
                                )

                        )

                )

            )


        controls.append(

            ft.Button(

                "Cerrar sesión",

                on_click=
                    logout

            )

        )


        screen(*controls)


    # ======================================================
    # INICIAR
    # ======================================================

    welcome()


def run_desktop():
    # FLET_APP_WEB opens the native desktop client with the HTTP transport
    # required by /oauth_callback. FLET_APP uses a different socket protocol.
    # This entry point deliberately owns its fixed, loopback-only OAuth port.
    os.environ["FLET_FORCE_WEB_SERVER"] = "false"
    os.environ["FLET_SERVER_PORT"] = "8550"
    os.environ["FLET_SERVER_IP"] = "127.0.0.1"
    try:
        with socket.socket() as probe:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind(("127.0.0.1", 8550))
    except OSError:
        print("Acompaña+ no pudo iniciar: el puerto 8550 está ocupado. "
              "Cierra la otra instancia de Acompaña+ y vuelve a ejecutar main0.1.py.")
        return 1
    ft.run(
        main,
        port=8550,
        host="127.0.0.1",
        view=ft.AppView.FLET_APP_WEB
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run_desktop())

