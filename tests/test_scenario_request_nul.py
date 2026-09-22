import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from proteus import Model
from trytond.pool import Pool
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules
from trytond.transaction import Transaction
from werkzeug.exceptions import NotFound
from werkzeug.middleware.shared_data import SharedDataMiddleware
from werkzeug.test import Client


class TestRequestNUL(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        # Import the WSGI entry point without starting a configured server.
        with patch('trytond.config.get', return_value=''), patch.dict(
                os.environ, {'TRYTOND_DATABASE_NAMES': ''}):
            from trytond.modules.voyager.app import VoyagerWSGI

        config = activate_modules('voyager')
        self.assertIn('uri', Model.get('www.uri')._fields)
        pool = Pool(config.database_name)
        Site = pool.get('www.site')
        URI = pool.get('www.uri')
        app = VoyagerWSGI()

        def dispatch(request):
            self.assertNotIn('\x00', request.path)
            self.assertNotIn('\x00', request.script_root)
            with Transaction().start(config.database_name, config.user,
                    context=config.context):
                site = Site(id=-1, url='localhost', route_method='uri')
                with patch.object(URI, 'search', wraps=URI.search) as search:
                    with self.assertRaises(NotFound) as error:
                        site.match_request(request)
                    search.assert_called_once_with([
                            ('site', '=', -1),
                            ('uri', '=', request.path)], limit=1)
                return error.exception

        with TemporaryDirectory() as directory:
            Path(directory, 'hello.txt').write_text('Hello')
            app.wsgi_app = SharedDataMiddleware(app.wsgi_app, {
                    '/static': directory})
            client = Client(app)
            with patch.object(app, 'dispatch_request', side_effect=dispatch
                    ) as dispatch_request:
                for path, expected in [
                        ('/%00admin/%00sys_phpinfo.php',
                            '/admin/sys_phpinfo.php'),
                        ('/admin/sys_phpinfo.php', '/admin/sys_phpinfo.php'),
                        ('/%00%00missing%00', '/missing'),
                        ('/caf%C3%A8', '/cafè'),
                        ('/%2500missing', '/%00missing')]:
                    with self.subTest(path=path):
                        response = client.get(path, environ_overrides={
                                'SCRIPT_NAME': '/\x00shop'})
                        self.assertEqual(response.status_code, 404)
                        request = dispatch_request.call_args.args[0]
                        self.assertEqual(request.path, expected)
                        self.assertEqual(request.script_root, '/shop')

                dispatch_request.reset_mock()
                response = client.get('/static/%00hello.txt')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data, b'Hello')
                dispatch_request.assert_not_called()

                for path in ['/static/images/ico/favicon.ico', '/static',
                        '/static/missing.css']:
                    with self.subTest(path=path):
                        response = client.get(path)
                        self.assertEqual(response.status_code, 404)
                        self.assertNotIn('Set-Cookie', response.headers)
                        dispatch_request.assert_not_called()
