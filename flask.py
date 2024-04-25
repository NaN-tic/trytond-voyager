import os
import click
import socket
from datetime import datetime
from flask import Flask, request, g
from flask_tryton import Tryton
from flask_babel import Babel
from flask_login import (LoginManager, login_required, user_logged_in,
    user_logged_out)

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

@login_manager.user_loader
def user_loader(user_id):
    LOGIN_EXTRA_FIELDS = app.config.get('LOGIN_EXTRA_FIELDS', [])

    user = User()
    user.id = user_id
    user.party = session['party'] if session.get('party') else None
    user.display_name = (session['display_name']
        if session.get('display_name') else None)
    user.email = session['email'] if session.get('email') else None
    for field in LOGIN_EXTRA_FIELDS:
        setattr(user, field, session.get(field, None))
    user.manager = session['manager'] if session.get('manager') else None
    return user

@main.command()
@click.argument('database')
@click.argument('site')
@click.option('--user', default=1)
@click.option('--host', default='0.0.0.0', help='IP to listen on')
@click.option('--port', default=5000, help='Port to listen on')
def run(database, site, user, host, port):
    import common
    # TODO: Allow configuration filename
    app = common.create_app(site, get_configs(site, filename=None))
    #app = Flask(site)
    app.config['TRYTON_DATABASE'] = 'nantic-local'
    app.config['TRYTON_USER'] = user
    # TODO: Pick environment variables with WWW_ prefix
    app.config['SECRET_KEY'] = 'secret'
    tryton = Tryton(app)
    babel = Babel(app)
    login_manager = LoginManager()
    login_manager.init_app(app)

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
        return Site.handle(site, '/', request)

    @app.route('/<path:path>', methods=['GET', 'POST'])
    @tryton.transaction(readonly=False)
    def handle(path):
        return Site.handle(site, f'/{path}', request)

    # TODO: Configure logging (see common.py)

    # TODO: Accept environment variables
    app.run(host=host, port=port, debug=True)

if __name__ == '__main__':
    main()
