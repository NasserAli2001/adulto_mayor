import os

# Evita el error "Scope has changed" si Google devuelve los permisos en otro orden
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

from google.auth.transport import requests as g_requests
from google.oauth2 import id_token
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]
CLIENT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "client_secret.json")


def iniciar_sesion_google():
    """Abre el navegador, el usuario elige su cuenta de Google y devuelve (correo, nombre)."""
    if not os.path.exists(CLIENT_FILE):
        raise RuntimeError("Falta el archivo client_secret.json en la carpeta del proyecto.")
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_FILE, SCOPES)
    creds = flow.run_local_server(
        port=0,
        prompt="select_account",
        timeout_seconds=180,
        success_message="Listo. Ya puede cerrar esta pestaña y volver a Acompaña+.",
    )
    info = id_token.verify_oauth2_token(
        creds.id_token, g_requests.Request(), flow.client_config["client_id"],
        clock_skew_in_seconds=10,
    )
    if not info.get("email_verified"):
        raise RuntimeError("Google indica que ese correo no está verificado.")
    return info["email"], info.get("name", "")