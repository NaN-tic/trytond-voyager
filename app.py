import os
import click
import socket
import logging
from datetime import datetime
from werkzeug import Request
from werkzeug.exceptions import HTTPException
from werkzeug.routing import BaseConverter, Map, Rule
from trytond.config import config
from trytond.pool import Pool
from trytond.transaction import Transaction

@click.group()
def main():
    'WWW'
    pass

def get_best_language():
    lang = request.accept_languages.best_match(get_languages())
    if lang:
        return lang
    return get_default_lang()

def get_default_lang():
    # TODO: Make it configurable
    return 'ca'

def get_languages():
    # TODO: Make it configurable
    languages = ['ca_ES', 'es_ES', 'en_US']
    if not languages:
        return []
    return [x.split('_')[0] for x in languages]

def get_locale():
    lang = request.path[1:].split('/', 1)[0]
    if lang in get_languages():
        return lang
    else:
        return get_default_lang()


class VoyagerWSGI(object):
    def __init__(self):
        self.pool = None
        self.database = config.get('database', 'database')
        self.site_type = config.get('voyager', 'site_type')
        self.site_id = config.get('voyager', 'site_id')
        self.user = config.get('voyager', 'user')
        self.Site = None

    def start(self):
        Pool.start()
        self.pool = Pool(self.database)
        self.pool.init()
        self.Site = self.pool.get('www.site')

    def dispatch_request(self, request):
        # TODO: Would be great if we found a way to define which transactions
        # are readonly and which are not
        with Transaction().start(self.database, self.user, readonly=False):
            return self.Site.dispatch(self.site_type, self.site_id, request)

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
@click.option('--user', default=1)
@click.option('--host', default='0.0.0.0', help='IP to listen on')
@click.option('--port', default=5000, help='Port to listen on')
@click.option('--dev', is_flag=True, help='Development mode')
@click.option('--config-file', default='trytond.conf')
def run(database, site_type, site_id, user, host, port, dev, config_file):
    from werkzeug.serving import run_simple

    config.update_etc(config_file)
    app.database = database
    app.site_type = site_type
    app.site_id = site_id
    app.user = user
    app.start()

    run_simple(host, port, app, use_debugger=True, use_reloader=dev)

if __name__ == '__main__':
    main()
