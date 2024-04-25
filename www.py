import os
import jinja2
import flask
import secrets
from flask_babel import format_datetime, format_date
from functools import partial
from trytond.model import DeactivableMixin, ModelSQL, ModelView, fields
from trytond.pool import Pool
from trytond.transaction import Transaction

def dateformat(value, format='medium'):
    '''Return date time to format

    date|dateformat
    date|dateformat('full')
    date|dateformat('short')
    date|dateformat('dd mm yyyy')
    '''
    if not value:
        return ''
    return format_date(value, format)

# TODO: Move to module galatea_cms
def cms_menu(site, code=None, id=None, levels=9999):
    """
    Return object values menu by code

    HTML usage in template:

    {% set menus=cms_menu(code='code') %}
    {% if menus %}
        {% for menu in menus %}
            <a href="{{ menu.uri }}" alt="{{ menu.name }}">{{ menu.name }}</a>
        {% endfor %}
    {% endif %}
    """
    pool = Pool()
    Menu = pool.get('galatea.cms.menu')

    # Search by code
    if code:
        menus = Menu.search([
                ('code', '=', code),
                ('website', '=', 3),
                #('website', '=', site.id),
                ], limit=1)
        if not menus:
            return []
        menu, = menus
    elif id:
        menu = Menu(id)
    else:
        return []

    #login = session.get('logged_in')
    #manager = session.get('manager')
    path = Transaction().context.get('path')

    def get_menus(menu, levels, level=0):
        childs = []
        activated = False
        if level < levels:
            level += 1
            for m in menu.childs:
                #if m.login and not login:
                #    continue
                #if m.manager and not manager:
                #    continue
                child_vals = get_menus(m, levels, level)
                activated |= child_vals['activated']
                childs.append(child_vals)

        extra_classes = []
        if menu.childs and menu.parent and not menu.parent.parent:
            extra_classes.append('menu-item-has-children')
        if menu.hidden_xs:
            extra_classes.append('hidden-xs')
        if menu.hidden_sm:
            extra_classes.append('hidden-sm')
        if menu.hidden_md:
            extra_classes.append('hidden-md')
        if menu.hidden_lg:
            extra_classes.append('hidden-lg')

        uri = menu.url
        activated |= (path == uri)
        return {
            'id': menu.id,
            'name': menu.name_used,
            'code': menu.code,
            'uri': uri,
            'target_uri': menu.target_uri,
            'childs': childs,
            'activated': activated,
            'active': (path == uri),
            'nofollow': menu.nofollow,
            'icon': menu.icon,
            'css': menu.css,
            'extra_classes': ' '.join(extra_classes),
            }
    menu = get_menus(menu, levels)
    return menu['childs']

def multilang_permalink(uri_id=None):
    pool = Pool()
    Lang = pool.get('ir.lang')

    contact_uris = ['/en/contact', '/es/contacto', '/ca/contacte']

    # TODO: get website languages
    langs = Lang.search([
            ('active', '=', True),
            ('translatable', '=', True),
            ])
    res = []
    for lang in langs:
        lang_code = lang.code
        lang_name = lang.web_name

        # galatea CMS
        if uri_id:
            with Transaction().set_context(language=lang.code):
                uri = Uri(uri_id)
                res.append({
                        'name': uri.name,
                        'uri': uri.uri,
                        'lang_code': lang_code,
                        'lang_name': lang_name,
                        })
        # contact blueprint
        elif flask.request.path in contact_uris:
            for uri in contact_uris:
                if uri.startswith('/%s/' % lang_code):
                    break
            res.append({
                    'name': lang_name,
                    'uri': uri,
                    'lang_code': lang_code,
                    'lang_name': lang_name,
                    })
        else:
            res.append({
                    'name': lang_name,
                    'uri': '/%s/' % lang_code,
                    'lang_code': lang_code,
                    'lang_name': lang_name,
                    })
    return res

class Site(DeactivableMixin, ModelSQL, ModelView):
    'WWW Site'
    __name__ = 'www.site'
    name = fields.Char('Name', required=True)

    # url
    # author
    # description
    # metadescription
    # keywords

    def view_from_path(self, path):
        pool = Pool()

        assert path, 'Path is empty'

        # Iterate
        for _, Model in pool.iterobject():
            if not issubclass(Model, WebView):
                continue
            if Model._path == path:
                return Model
        raise ValueError('No view found for path %s' % path)

    def path_from_view(self, view):
        pool = Pool()

        if isinstance(view, str):
            View = pool.get('ir.ui.view')
        else:
            View = view
        return View._path

    @classmethod
    def handle(cls, name, path, request):
        sites = cls.search([('name', '=', name)], limit=1)
        if not sites:
            raise ValueError('Site "%s" not found' % name)
        site, = sites

        View = site.view_from_path(path)
        if not View:
            raise ValueError('View "%s" not found' % path)

        if request.method == 'POST':
            record = View()
            form = request.form
            for field in record._fields:
                setattr(record, field, form.get(field))

            with Transaction().set_context(site=site, path=path):
                return record.render_single()

        # This transaction should use the language of the browser/URL
        with Transaction().set_context(site=site, path=path):
            content = View.render()
        return content

    def template_context(self):
        from flask_login import current_user
        from flask_babel import gettext as _

        context = Transaction().context.copy()
        context['g'] = flask.g
        context['url_for'] = flask.url_for
        context['get_flashed_messages'] = flask.get_flashed_messages
        context['current_user'] = current_user
        context['_'] = _
        context['config'] = flask.current_app.config

        # This should be added by inheriting
        context['cms_menu'] = partial(cms_menu, site=self)
        context['multilang_permalink'] = multilang_permalink
        return context

    def template_filters(self):
        return {
            'dateformat': dateformat,
            }


class Session(ModelSQL, ModelView):
    'Session'
    __name__ = 'www.session'
    site = fields.Many2One('www.site', 'Site', required=True)
    session_id = fields.Char('Session ID', required=True)
    #TODO: expired boolean field? know that sessions is expired or not

    def create(self):
        pool = Pool()
        Site = pool.get('www.site')

        secrets.token_urlsafe()

        site = Site(Transaction().context.get('site'))
        session_id = str(uuid.uuid4())
        session = self(session_id=session_id, site=site)
        session.save()
        return session

    # TODO: Implement an expiration mechanism


class WebView(ModelView):
    _path = None

    @classmethod
    @property
    def context(cls):
        return Transaction().context

    @classmethod
    def load_template(cls, name):
        if '/' in name:
            module, name = name.split('/', 1)
            path = os.path.join(os.path.dirname(__file__), path, '..', module)
            path = os.path.abspath(path)
        else:
            path = os.path.abspath(os.path.dirname(__file__))
        path = os.path.join(path, 'www', name)
        with open(path) as f:
            return f.read()

    @classmethod
    def template_context(cls):
        return cls.context['site'].template_context()

    @classmethod
    def render_template(cls, template, **kwargs):
        template = cls.load_template(template)
        context = cls.template_context().copy()
        context.update(kwargs)
        env = cls.get_environment()
        template = env.from_string(template)
        return template.render(context)

    @classmethod
    def get_template_paths(cls):
        return [os.path.abspath(os.path.join(os.path.dirname(__file__), 'www'))]

    @classmethod
    def get_environment(cls):
        """
        Create and return a jinja environment to render templates

        Downstream modules can override this method to easily make changes
        to environment
        """
        loader = jinja2.FileSystemLoader(cls.get_template_paths())
        env = jinja2.Environment(loader=loader)
        env.filters.update(cls.context['site'].template_filters())
        return env

    @classmethod
    def render(cls):
        raise NotImplementedError('Method render not implemented')


class Index(WebView):
    'Index'
    __name__ = 'www.index'
    _path = '/'

    @classmethod
    def render(cls):
        return '<html><body>Site: %s</body></html>' % cls.context['site'].name


class ExtranetIndex(WebView):
    'Extranet Index'
    __name__ = 'www.extranet.index'
    _path = '/'

    @classmethod
    def render(cls):
        return cls.render_template('extranet.html')


class ExtranetLogin(WebView):
    'Extranet Login'
    __name__ = 'www.extranet.login'
    _path = '/login'
    email = fields.Char('E-mail')
    password = fields.Char('Password')

    def successful(self, user):
        import flask_login
        flask_login.login_user(user)
        return self.render_template('extranet.html')

    def failed(self):
        flask.flash('Invalid credentials')
        return self.render_template('extranet.html')

    def render_single(self):
        pool = Pool()
        User = pool.get('galatea.user')

        if not self.email or not self.password:
            return self.failed()

        users = User.search([
                ('active', '=', True),
                ('email', '=', self.email),
                # TODO: Remove hardcoded website
                ('websites', 'in', [3]),
                ], limit=1)
        if not users:
            return self.failed()
        user, = users

        import hashlib
        # TODO: This code should be moved to galatea module
        password = self.password.encode('utf-8')
        salt = user.salt.encode('utf-8') if user.salt else ''
        if salt:
            password += salt
        digest = hashlib.sha1(password).hexdigest()
        if digest != user.password:
            return self.failed()

        return self.successful(user)

    @classmethod
    def render(cls):
        return cls.render_template('login.html')


class ExtranetHeader(WebView):
    'Extranet Header'
    __name__ = 'www.extranet.header'
    _path = '/header'

    @classmethod
    def render(cls):
        return '<html><body>Site: %s</body></html>' % cls.context['site'].name
