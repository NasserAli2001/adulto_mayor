import asyncio
import inspect
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock

import importlib.util

app_path = Path(__file__).with_name('main0.1.py')
if not app_path.exists():
    app_path = Path(__file__).with_name('main.py')
spec = importlib.util.spec_from_file_location('acompana_app', app_path)
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


class FakePage:
    def __init__(self):
        self.controls = []
        self.auth = None
        self.messages = []
        self.web = False
        self.window = SimpleNamespace(to_front=AsyncMock())

    def clean(self):
        self.controls = []

    def add(self, *controls):
        self.controls.extend(controls)

    def update(self):
        pass

    def run_task(self, handler, *args):
        self.background_task = (handler, args)

    def show_dialog(self, dialog):
        self.messages.append(dialog.content.value)

    async def login(self, provider, **kwargs):
        self.provider = provider
        self.login_options = kwargs

    def logout(self):
        self.auth = None

    def all_controls(self):
        def walk(control):
            yield control
            for child in getattr(control, 'controls', []) or []:
                yield from walk(child)
            child = getattr(control, 'content', None)
            if child is not None and not isinstance(child, str):
                yield from walk(child)
        return [c for top in self.controls for c in walk(top)]

    def field(self, label):
        return next(c for c in self.all_controls() if getattr(c, 'label', None) == label)

    def click(self, text):
        control = next(c for c in self.all_controls() if getattr(c, 'content', None) == text)
        result = control.on_click(SimpleNamespace(control=control))
        if asyncio.iscoroutine(result):
            asyncio.run(result)


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db = app.DB
        app.DB = Path(self.temp.name) / 'test.db'
        app.init_db()
        self.identity = {'sub': 'google-123', 'email': 'person@example.com', 'name': 'Persona Prueba'}

    def tearDown(self):
        app.DB = self.old_db
        self.temp.cleanup()

    def create(self, **kwargs):
        args = dict(identity=self.identity, name='Persona Prueba', role='Familiar',
                    phone='3001234567', caregiver='', whatsapp=False)
        args.update(kwargs)
        return app.create_google_profile(**args)

    def page(self):
        page = FakePage()
        with patch.object(app, 'GOOGLE_CLIENT_ID', 'test.apps.googleusercontent.com'), patch.object(app, 'GOOGLE_CLIENT_SECRET', 'test-only'):
            app.main(page)
        return page

    def google(self, page, **claims):
        page.click('Iniciar sesión')
        page.click('Continuar con Google')
        page.auth = SimpleNamespace(user=dict(self.identity, email_verified=True, **claims))
        asyncio.run(page.on_login(SimpleNamespace(error='')))

    def test_identity_requires_verified_email_and_stable_id(self):
        self.assertEqual(app.google_identity(dict(self.identity, email_verified=True))['sub'], 'google-123')
        for verified in (False, 'true', None):
            with self.assertRaises(ValueError):
                app.google_identity(dict(self.identity, email_verified=verified))

    def test_login_has_no_developer_configuration(self):
        page = self.page()
        page.click('Iniciar sesión')
        texts = [str(getattr(c, 'content', '') or '') + str(getattr(c, 'value', '') or '') for c in page.all_controls()]
        self.assertTrue(any('Continuar con Google' in text for text in texts))
        self.assertFalse(any(word in text for text in texts for word in ('Configurar accesos', 'credenciales', 'SMTP', 'OTP', 'Client Secret')))

    def test_logout_matches_installed_flet_and_clears_google_session(self):
        self.assertFalse(inspect.iscoroutinefunction(app.ft.Page.logout))
        self.create()
        page = self.page()
        self.google(page)
        page.window.to_front.assert_awaited_once()
        self.assertIn('Continúa en Acompaña+', page.login_options['complete_page_html'])
        self.assertEqual(page.background_task[0], app.restore_desktop_window)
        page.click('Cerrar sesión')
        self.assertIsNone(page.auth)
        self.assertTrue(any(getattr(c, 'content', None) == 'Iniciar sesión' for c in page.all_controls()))

    def test_return_to_desktop_restores_minimized_window(self):
        page = FakePage()
        page.window.minimized = True
        with patch.object(app.asyncio, 'sleep', new_callable=AsyncMock):
            asyncio.run(app.restore_desktop_window(page))
        self.assertFalse(page.window.minimized)
        page.window.to_front.assert_awaited_once()

    def test_invalid_google_response_logs_out_without_await_error(self):
        page = self.page()
        page.click('Iniciar sesión')
        page.click('Continuar con Google')
        page.auth = SimpleNamespace(user=dict(self.identity, email_verified=False))
        asyncio.run(page.on_login(SimpleNamespace(error='')))
        self.assertIsNone(page.auth)
        self.assertIn('correo verificado', page.messages[-1])

    def test_desktop_uses_http_transport_and_reports_busy_port(self):
        with patch.dict(os.environ, {}, clear=False), patch.object(app.socket, 'socket') as sock, patch.object(app.ft, 'run') as run:
            self.assertEqual(app.run_desktop(), 0)
            self.assertEqual(run.call_args.kwargs['view'], app.ft.AppView.FLET_APP_WEB)
            self.assertEqual(run.call_args.kwargs['host'], '127.0.0.1')
            self.assertEqual(run.call_args.kwargs['port'], 8550)
            self.assertEqual(os.environ['FLET_FORCE_WEB_SERVER'], 'false')
            run.reset_mock()
            sock.return_value.__enter__.return_value.bind.side_effect = OSError('busy')
            with patch('builtins.print'):
                self.assertEqual(app.run_desktop(), 1)
            run.assert_not_called()

    def test_profile_persistence_no_password_and_duplicate_rejection(self):
        user = self.create()
        self.assertIsNone(user['password_hash'])
        self.assertEqual(user['whatsapp_permission'], 0)
        app.init_db()
        with app.conn() as c:
            self.assertEqual(c.execute('SELECT google_sub FROM users WHERE id=?', (user['id'],)).fetchone()[0], 'google-123')
        with self.assertRaises(sqlite3.IntegrityError):
            self.create()

    def test_profile_validates_role_phone_caregiver(self):
        for values in ({'role': 'Administrador'}, {'phone': '123'}, {'role': 'Adulto mayor'}, {'caregiver': '123'}):
            with self.assertRaises(ValueError):
                self.create(**values)
        self.assertEqual(self.create(role='Adulto mayor', caregiver='3002223333', whatsapp=True)['whatsapp_permission'], 1)

    def test_migration_preserves_old_data(self):
        with app.conn() as c:
            c.execute('DROP INDEX users_google_sub')
            c.execute('ALTER TABLE users DROP COLUMN google_sub')
        app.seed('Prueba', 'old@example.com', '3001234567', 'Example123', 'Familiar', 0)
        app.init_db()
        app.init_db()
        with app.conn() as c:
            user = c.execute('SELECT * FROM users').fetchone()
            self.assertTrue(app.pwd_ok('Example123', user['salt'], user['password_hash']))
            self.assertIsNone(user['google_sub'])

    def test_first_google_login_profile_and_returning_login(self):
        page = self.page()
        self.google(page)
        page.field('Tipo de usuario').value = 'Familiar'
        page.field('Teléfono (10 a 15 dígitos)').value = '3001234567'
        page.click('Guardar perfil y entrar')
        page.click('Cerrar sesión')
        self.assertIsNone(page.auth)
        self.google(page)
        self.assertTrue(any(getattr(c, 'content', None) == 'Cerrar sesión' for c in page.all_controls()))

    def test_password_otp_and_link_preserve_role(self):
        app.seed('Prueba', self.identity['email'], '3001234567', 'Example123', 'Familiar', 0)
        page = self.page()
        self.google(page)
        page.field('Contraseña de tu cuenta Acompaña+').value = 'Example123'
        with patch.object(app, 'send_otp', return_value=True) as sender:
            page.click('Verificar y vincular')
            code = sender.call_args.args[1]
        with app.conn() as c:
            self.assertIsNone(c.execute('SELECT google_sub FROM users').fetchone()[0])
        page.field('Código de 6 dígitos').value = code
        page.click('Verificar')
        with app.conn() as c:
            user = c.execute('SELECT * FROM users').fetchone()
            self.assertEqual(user['role'], 'Familiar')
            self.assertEqual(user['google_sub'], self.identity['sub'])
        page.click('Cerrar sesión')
        page.click('Iniciar sesión')
        page.field('Correo electrónico').value = self.identity['email']
        page.field('Contraseña').value = 'Example123'
        with patch.object(app, 'send_otp', return_value=True) as sender:
            page.click('Ingresar')
            code = sender.call_args.args[1]
        page.field('Código de 6 dígitos').value = code
        page.click('Verificar')
        page.click('Cerrar sesión')

    def test_otp_failures_expiration_and_cancel(self):
        app.seed('Prueba', self.identity['email'], '3001234567', 'Example123', 'Familiar', 0)
        page = self.page()
        def start():
            page.click('Iniciar sesión') if any(getattr(c, 'content', None) == 'Iniciar sesión' for c in page.all_controls()) else None
            page.field('Correo electrónico').value = self.identity['email']
            page.field('Contraseña').value = 'Example123'
            with patch.object(app, 'send_otp', return_value=True) as sender:
                page.click('Ingresar')
                return sender.call_args.args[1]
        code = start()
        wrong = '000000' if code != '000000' else '111111'
        for _ in range(5):
            page.field('Código de 6 dígitos').value = wrong
            page.click('Verificar')
        self.assertIsNotNone(page.field('Contraseña'))
        start()
        with patch.object(app.time, 'monotonic', return_value=float('inf')):
            page.click('Verificar')
        self.assertIsNotNone(page.field('Contraseña'))
        start()
        page.click('Cancelar')
        with patch.object(app, 'send_otp', return_value=False), patch.object(app, 'OTP_DEMO_MODE', False):
            page.field('Correo electrónico').value = self.identity['email']
            page.field('Contraseña').value = 'Example123'
            page.click('Ingresar')
        self.assertIn('No se pudo enviar', page.messages[-1])

    def test_existing_service_screens_all_roles(self):
        for role, email in [('Familiar', 'family@example.com'), ('Acompañante', 'companion@example.com'), ('Administrador', 'admin@example.com')]:
            app.seed('Persona Prueba', email, '3001234567', 'Example123', role, 1)
        with app.conn() as c:
            c.execute("""INSERT INTO requests(user_id,type,date,time,origin,destination,notes,status,companion_id)
                      VALUES(1,'Cita médica','01/10/2026','10:00','Origen','Destino','','Asignada',2)""")
        for email in ('family@example.com', 'companion@example.com', 'admin@example.com'):
            page = self.page()
            page.click('Iniciar sesión')
            page.field('Correo electrónico').value = email
            page.field('Contraseña').value = 'Example123'
            with patch.object(app, 'send_otp', return_value=True) as sender:
                page.click('Ingresar')
                code = sender.call_args.args[1]
            page.field('Código de 6 dígitos').value = code
            # A client URL action requires a live Flet page; do not open WhatsApp in tests.
            with patch.object(app.ft, 'OpenUrl', return_value=None):
                page.click('Verificar')
                self.assertTrue(any(getattr(c, 'content', None) == 'Cerrar sesión' for c in page.all_controls()))
                if email == 'family@example.com':
                    page.click('Ver mis solicitudes')


if __name__ == '__main__':
    unittest.main()

