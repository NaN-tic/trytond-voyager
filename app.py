import click
from werkzeug import Request
from trytond.config import config
from trytond.pool import Pool
from trytond.transaction import Transaction
from trytond.modules.voyager import voyager

import os
from werkzeug.middleware.shared_data import SharedDataMiddleware

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
        with Transaction().start(self.database, self.user_id, readonly=False):
            return self.Site.dispatch(self.site_type, self.site_id, request,
                self.user_id)

    def wsgi_app(self, environ, start_response):
        request = Request(environ)
        response = self.dispatch_request(request)
        return response(environ, start_response)

    def __call__(self, environ, start_response):
        return self.wsgi_app(environ, start_response)

app = VoyagerWSGI()

app.database = config.get('voyager', 'database')
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
