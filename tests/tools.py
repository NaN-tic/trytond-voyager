import os
import threading
import unittest
import logging
from datetime import datetime
from functools import wraps
from secrets import token_hex

from playwright.sync_api import Page, sync_playwright
from proteus import Model, Wizard
from proteus import config as pconfig
from trytond import wsgi
from trytond.tests.test_tryton import drop_create, drop_db
from werkzeug.serving import make_server
from trytond.config import config
from trytond.transaction import Transaction
from trytond.backend import name

logger = logging.getLogger(__name__)

# HINT: You need to install package 'playwright', and then execute the command 'playwright install'
# SEE: https://playwright.dev/python/docs/library

# CAUTION: If you want to execute this test locally or on a new server, please define the 'root' variable with the value 'sao', on TRYTOND.conf
# HINT: You can temporarily define it with the command 'export TRYTOND_WEB__ROOT=sao'

# CAUTION: Also you need to define DATABASE__PATH.
# HINT: You can temporarily define it with the command 'export TRYTOND_DATABASE__PATH=/tmp'


class ServerThread(threading.Thread):
    "Class that creates and manages a Tryton server in a new thread."
    def __init__(self, app):
        threading.Thread.__init__(self)

        # When the system gets a '0' on the socket, it automatically finds a not-used port.
        # SEE: https://stackoverflow.com/questions/1365265/on-localhost-how-do-i-pick-a-free-port-number
        self.port = 0
        self.host = 'localhost'

        # Threaded is put to TRUE to ensure that the server is stopped.
        # Werkzeug says: shutdown() must be called while serve_forever() is running in another thread, or it will deadlock.
        self.server = make_server(self.host, self.port, app, threaded=True)

        # Retrieve the port selected by the system
        self.port = self.server.socket.getsockname()[1]

    def run(self):
        self.server.serve_forever()

    def stop(self):
        if self.is_alive():
            logger.info('Stopping server...')
            self.server.shutdown()

def get_random_password(length=None):
    return token_hex(length)

def activate_modules(modules, database_name):
    if isinstance(modules, str):
        modules = [modules]
    drop_create(name=database_name)

    cfg = pconfig.set_trytond(database=database_name)
    Module = Model.get('ir.module', config=cfg)
    records = Module.find([
        ('name', 'in', modules),
    ])
    assert len(records) == len(modules)

    # Activate extensions for PostgreSQL (pgvector)
    if name == 'postgresql':
        transaction = Transaction()
        with transaction.start(database_name, 0) as transaction:
            cursor = transaction.connection.cursor()
            cursor.execute('CREATE EXTENSION vector;')

    Module.click(records, 'activate')
    Wizard('ir.module.activate_upgrade').execute('upgrade')
    return cfg

def browser():
    """
    Decorator that wraps a function (normally tests)
    to offer Playwright's tests system.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            with sync_playwright() as playwright:
                error = None
                try:
                    headless = (config.getboolean('nantic_connection',
                        'test_headless', default=False) or
                            'DISPLAY' not in os.environ)
                    want_trace = config.getboolean(
                        'nantic_connection', 'test_trace', default=False)

                    browser = playwright.firefox.launch(headless=headless)
                    context = browser.new_context(locale='en-US')
                    if want_trace:
                        context.tracing.start(
                            screenshots=True, snapshots=True, sources=True)

                    page = context.new_page()
                    return func(*args, page=page, **kwargs)
                except Exception as e:
                    error = e
                    args[0].server.stop()
                finally:
                    if 'context' in locals():
                        if want_trace:
                            path = '/tmp/' + '_'.join([
                                func.__name__,
                                datetime.now().strftime('%Y_%m_%d__%H_%M_%S'),
                                f'{get_random_password(3)}.zip'])
                            context.tracing.stop(path=path)
                        context.clear_cookies()
                        context.clear_permissions()
                        context.close()
                        browser.close()
                    if error:
                        raise error
        return wrapper
    return decorator

class WebTestCase(unittest.TestCase):
    app = wsgi.app
    modules = None
    database = f"test_{datetime.timestamp(datetime.now())}".replace('.', '')
    config = None
    user = 'admin'
    password = get_random_password()
    user_name = None
    timeout = 5000

    @classmethod
    def setUpClass(self):
        "Method that executes only once, at the very first and before any test."
        database_path = config.get('database', 'path')
        web_root = config.get('web', 'root')

        # In order to avoid permission issues or trying to write on an
        # inexistent path, we set /tmp as the temporary path for the database.
        # If we do not do this, tests may fail in line '493' of file
        # 'trytond/backend/sqlite.py', when trying to open the database file.
        if not database_path or not os.path.exists(database_path):
            logger.warning("Setting TRYTOND_DATABASE__PATH=/tmp...")
            config.set('database', 'path', '/tmp')

        # In order to be able to run web tests, we need to set the web root to 'sao' folder,
        # but we cannot set it with 'config.set()', because the variable was already readed.
        if not web_root or not os.path.exists(web_root):
            raise Exception(
                "Execute 'export TRYTOND_WEB__ROOT=sao' to run web tests. "
                "If not defined or improperly set, web page will not load."
            )

        self.timeout_in_secs = self.timeout / 1000
        self.config = activate_modules(self.modules, self.database)

        User = Model.get('res.user')
        user = User(1)

        self.user = user.login
        self.user_name = user.name
        user.password = self.password
        user.save()

    def setUp(self):
        "Before each test, execute this method."
        self.server = ServerThread(self.app)
        self.server.start()

    @classmethod
    def tearDownClass(self):
        "Method that executes only once, at the very end and after all tests."
        drop_db(name=self.database)

    def tearDown(self):
        "After each test, execute this method."
        self.server.stop()

    # Helpers
    @property
    def base_url(self):
        return f'http://{self.server.host}:{self.server.port}'

    def go_tryton(self, page: Page):
        page.goto(self.base_url)
        page.wait_for_load_state('load')
