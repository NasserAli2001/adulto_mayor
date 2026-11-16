# Acompaña+: inicio local y Google

La aplicación principal es `main0.1.py`. `main.py` es únicamente un lanzador de ese mismo archivo. Conserva solicitudes, asignación por administrador, atención por acompañante y SQLite de `main0.1.py`. La versión anterior y la base de datos se respaldan en `backups/` antes de instalar el cambio. No se crean nuevas cuentas con contraseñas predeterminadas. Las cuentas que ya existían permanecen.

## Ejecutar

Desde la terminal de VS Code en esta carpeta:

```powershell
.\venv\Scripts\python.exe main0.1.py
```

Se abre la ventana de escritorio de Acompaña+. Flet usa `FLET_APP_WEB`: ventana nativa con conexión HTTP local para recibir `/oauth_callback`. El navegador se utiliza únicamente durante el inicio con Google. El servidor escucha solo en 127.0.0.1:8550. Si ya hay una instancia usando ese puerto, se muestra un aviso claro en la terminal; cierra la instancia anterior antes de repetir.

## Activar Google (pendiente de crear credenciales)

1. En https://console.cloud.google.com/ crea o selecciona el proyecto Acompaña+.
2. Configura Google Auth Platform con nombre de aplicación y correo de soporte/contacto. Elige audiencia externa para cuentas fuera de una organización.
3. Crea un cliente de tipo **Aplicación web**. Registra exactamente esta URI de redirección: `http://localhost:8550/oauth_callback`.
4. Configura únicamente los permisos básicos `openid`, `email` y `profile`. Si mantienes la aplicación en pruebas, añade las cuentas de prueba que corresponda en Audience.
5. Como desarrollador, abre `.env` localmente y completa `GOOGLE_CLIENT_ID` y `GOOGLE_CLIENT_SECRET` con los valores de Google. No los pegues en el chat, en capturas ni en archivos Python.
6. Reinicia la aplicación y pulsa **Continuar con Google**.

Google autentica la identidad; Acompaña+ pide nombre, rol, teléfono, contacto del cuidador y autorización opcional de WhatsApp. El cuidador es obligatorio para adulto mayor. El perfil se guarda sin contraseña local y queda asociado al identificador estable de Google. No se guardan tokens en SQLite.

Si el correo ya existe, se requiere contraseña de Acompaña+ y OTP antes de vincular Google. Se conserva el rol y la contraseña existentes. No se puede elegir Administrador en el registro público.

## Correo y OTP

Completa `SMTP_USER` y `SMTP_PASSWORD` en `.env` con la cuenta de envío Gmail y su contraseña de aplicación. Se conserva el envío por SMTP de Gmail con TLS. El código vence en cinco minutos, tiene cinco intentos y se invalida al cancelar o cerrar sesión. Si falla el envío, no se permite entrar ni se muestra el código.

Solo para una demostración local sin correo puede usarse `OTP_DEMO_MODE=true`: el código aparecerá en pantalla, claramente marcado como demostración. Esto **no verifica posesión del correo**. El valor predeterminado es `false`.

Las variables del entorno tienen prioridad sobre `.env`. El archivo se carga desde la carpeta de `main0.1.py`, independientemente de dónde se ejecute.

## Archivos privados y GitHub

`.gitignore` excluye `.env`, credenciales JSON, bases de datos, respaldos y el entorno virtual. `.env.example` contiene únicamente campos vacíos y sí puede compartirse. No se ha creado un repositorio ni publicado ningún cambio. Si en el futuro algún secreto ya estuviera versionado, `.gitignore` no lo elimina del historial: habría que retirarlo y rotarlo.

## Comprobación

```powershell
.\venv\Scripts\python.exe -m unittest test_auth -v
```

Las pruebas usan una base temporal y simulan la respuesta autenticada de Google y el envío de correo. La prueba real de Google y SMTP requiere configurar sus credenciales.

Referencias: https://flet.dev/docs/cookbook/authentication/ y https://developers.google.com/identity/openid-connect/reference


