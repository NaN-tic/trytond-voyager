import logging
import os
import time

import click
import trytond.config as config
from trytond import backend
from trytond.modules.voyager import voyager
from trytond.pool import Pool
from trytond.transaction import Transaction, TransactionError
from trytond.worker import run_task
from werkzeug import Request
from werkzeug.middleware.shared_data import SharedDataMiddleware

MODULES_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
logger = logging.getLogger(__name__)

@click.group()
def main():
    'Voyager'
    pass


class VoyagerWSGI(object):
    def __init__(self):
        self.pool = None
        self.database = config.get('database', 'database')
        self.site_type = config.get('voyager', 'site_type')
        self.site_id = config.getint('voyager', 'site_id')
        self.user_id = config.getint('voyager', 'user_id')
        self.Site = None

    def start(self):
        Pool.start()
        self.pool = Pool(self.database)
        self.pool.init()
        self.Site = self.pool.get('www.site')

    def dispatch_request(self, request):
        # TODO: Would be great if we found a way to define which transactions
        # are readonly and which are not
        # NOTE: Same code seen on @with_transaction
        retry = config.getint('database', 'retry')
        count = 0
        context = { '_request': request.context }
        transaction_extras = {}
        while True:
            if count:
                time.sleep(0.02 * count)
            with Transaction().start(
                    self.database, self.user_id, readonly=False,
                    context=context, **transaction_extras) as transaction:
                try:
                    response = self.Site.dispatch(
                        self.site_type, self.site_id, request, self.user_id)
                except TransactionError as e:
                    transaction.rollback()
                    transaction.tasks.clear()
                    e.fix(transaction_extras)
                    continue
                except backend.DatabaseOperationalError:
                    if count < retry:
                        transaction.rollback()
                        transaction.tasks.clear()
                        count += 1
                        logger.debug("Retry: %i", count)
                        continue
                    raise
                # Need to commit to unlock SQLite database
                transaction.commit()
            while transaction.tasks:
                task_id = transaction.tasks.pop()
                run_task(self.pool, task_id)
            return response

    def wsgi_app(self, environ, start_response):
        request = Request(environ)
        response = self.dispatch_request(request)
        return response(environ, start_response)

    def __call__(self, environ, start_response):
        return self.wsgi_app(environ, start_response)


static_folder = config.get('voyager', 'static_folder')
app = VoyagerWSGI()
app.wsgi_app = SharedDataMiddleware(app.wsgi_app, {
    '/static': os.path.join(MODULES_PATH, static_folder)})

app.database = config.get('voyager', 'database')
if not app.database:
    app.database = os.environ.get('TRYTOND_DATABASE_NAMES')
if app.database:
    app.start()

@main.command()
@click.argument('database')
@click.argument('site_type')
@click.option('--site-id', default=None)
@click.option('--user-id', default=1)
@click.option('--host', default='0.0.0.0', help='IP to listen on')
@click.option('--port', default=5000, help='Port to listen on')
@click.option('--dev', is_flag=True, help='Development mode')
@click.option('--disable-cache', is_flag=True, help='Disable cache')
@click.option('--static-folder', default="static", help="Path to static folder, need to be relative to the voyager module. (../module/static_folder)")
@click.option('--config-file', default=None)
def run(database, site_type, site_id, user_id, host, port, dev, disable_cache,
        static_folder, config_file):
    from werkzeug.serving import run_simple

    if config_file:
        config.update_etc(config_file)
    if disable_cache:
        voyager.CACHE_ENABLED = False
    if database:
        app.database = database
    if site_type:
        app.site_type = site_type
    if site_id:
        app.site_id = site_id
    if user_id:
        app.user_id = user_id
    app.start()

    run_simple(host, port, SharedDataMiddleware(app, {
        '/static': os.path.join(os.path.dirname(__file__), static_folder)}),
        use_debugger=True, use_reloader=dev)

if __name__ == '__main__':
    main()
