#!/usr/bin/env python
# This file is part galatea app for Flask.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
import configparser
import os
import pytz
import socket
import json
import sys
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header
from trytond.sendmail import sendmail
from flask import Flask, current_app
from cachelib import FileSystemCache
from werkzeug.debug import DebuggedApplication
from werkzeug.middleware.proxy_fix import ProxyFix

PATH = os.path.dirname(os.path.realpath(__file__))
TO_ADDR = 'juanjo.garcia@nan-tic.com'

class TrytonSMTPHandler(logging.Handler):

    def emit(self, record):
        try:
            from_addr = os.environ.get('TRYTOND_EMAIL__FROM')

            msg = MIMEMultipart('alternative')
            msg['From'] = from_addr
            msg['To'] = TO_ADDR
            msg['Subject'] = Header("Flask Failed %s" % current_app.config['TITLE'], 'utf-8')
            part = MIMEText(self.format(record), 'plain', _charset='utf-8')
            msg.attach(part)

            sendmail(from_addr, [TO_ADDR], msg)
        except (KeyboardInterrupt, SystemExit):
            raise
        except:
            self.handleError(record)


def configure_logging(app):
    if not app.debug:
        if os.environ.get('TRYTOND_EMAIL__URI'):
            mail_handler = TrytonSMTPHandler()
            mail_handler.setLevel(logging.ERROR)
            app.logger.addHandler(mail_handler)

        stream_handler = logging.StreamHandler()
        app.logger.addHandler(stream_handler)
    else:
        # Set app.testing = True in debug mode because this makes recaptcha
        # fields to be always valid
        app.testing = True

    logging_level = int(os.environ.get('TRYTOND_LOGGING_LEVEL',
            default=logging.INFO))
    logformat = ('%(process)s %(thread)s [%(asctime)s] '
        '%(levelname)s %(name)s %(message)s')
    level = max(logging_level, logging.NOTSET)
    logging.basicConfig(level=level, format=logformat)

def get_flask_config():
    '''Get Flask configuration from ini file'''
    conf_file = '{}/config.ini'.format(PATH)
    config = configparser.ConfigParser()
    config.read(conf_file)

    results = {}
    for section in config.sections():
        results[section] = {}
        for option in config.options(section):
            results[section][option] = config.get(section, option)
    return results

def create_app(configs):
    '''Create Flask APP'''
    cfg = get_flask_config()
    #app_name = cfg['flask']['app_name']
    app_name = 'TEST'
    app = Flask(app_name)
    for config in configs:
        app.config.from_pyfile(config)
    if 'FLASK_CONFIG' in os.environ:
        d = json.loads(os.environ['FLASK_CONFIG'])
        for key, value in d.items():
           app.config[key] = value
    # TODO fix nginx or uwsgi to allow CSRF valiation
    app.config['WTF_CSRF_ENABLED'] = False
    app.jinja_env.add_extension('jinja2.ext.loopcontrols')
    app.jinja_env.add_extension('jinja2.ext.do')
    app.jinja_env.trim_blocks = True
    # app.jinja_env.lstrip_blocks = True
    app.jinja_env.auto_reload = True

    #app.cache = FileSystemCache(cache_dir=app.config['CACHE_DIR'],
    #    default_timeout=app.config['CACHE_TIMEOUT'])

    app.cache = FileSystemCache(cache_dir='/tmp/flask-cimbis',
        default_timeout=3600)

    if app.config.get('DEBUG'):
        app.wsgi_app = DebuggedApplication(app.wsgi_app, True)
    app.wsgi_app = ProxyFix(app.wsgi_app)
    configure_logging(app)
    return app
