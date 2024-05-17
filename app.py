import os
import click
import socket
from trytond.config import config as CONFIG
from datetime import datetime
from flask import Flask, request, g
from flask_tryton import Tryton
from flask_babel import Babel

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

def get_configs(site, filename):
    path = os.path.dirname(os.path.realpath(__file__))
    configs = []
    app_config = '%s/%s.cfg' % (path, site)
    if os.path.exists(app_config):
        configs.append(app_config)

    if filename == 2:
        configs.append(filename)
    else:
        conf_file = '%s/%s-%s.cfg' % (path,
            os.path.basename(__file__).split('.')[0], socket.gethostname())
        if os.path.exists(conf_file):
            configs.append(conf_file)
    return configs

@main.command()
@click.argument('database')
@click.argument('site')
@click.option('--user', default=15)
@click.option('--host', default='0.0.0.0', help='IP to listen on')
@click.option('--port', default=5000, help='Port to listen on')
@click.option('--config-file', default='trytond.conf')
def run(database, site, user, host, port, config_file):
    import common
    CONFIG.update_etc(config_file)
    # TODO: Allow configuration filename
    app = common.create_app(get_configs(site, filename=None))
    #app = Flask(site)
    app.config['TRYTON_DATABASE'] = 'vegio-beta68_250424'
    app.config['TRYTON_USER'] = user
    # TODO: Pick environment variables with WWW_ prefix
    app.config['SECRET_KEY'] = 'secret'
    tryton = Tryton(app)
    babel = Babel(app)

    Site = tryton.pool.get('www.site')

    # TODO: Pick TIMEZONE from common.py
    TIMEZONE = None

    # TODO: Could register handlers automatically from all routes found for the
    # site

    @app.before_request
    def func():
        #g.babel = babel
        g.language = get_locale()
        # TODO: We should not add this to the global context
        g.today = datetime.now(TIMEZONE).date()
        #g.now = datetime.now(common.TIMEZONE)
        #g.is_desktop = common.is_desktop
        #g.is_web_crawler = common.is_web_crawler

    @app.route('/', methods=['GET', 'POST'])
    @tryton.transaction(readonly=False)
    def handle_root():
        print('HANDLE 2')
        return Site.handle(site, '/', request)

    @app.route('/<path:path>', methods=['GET', 'POST'])
    @tryton.transaction(readonly=False)
    def handle(path):
        print('HANDLE 1')
        return Site.handle(site, f'/{path}', request)

    # TODO: Configure logging (see common.py)

    # TODO: Accept environment variables
    app.run(host=host, port=port, debug=True)

if __name__ == '__main__':
    main()
