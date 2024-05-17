import os
import jinja2
import flask
import secrets
from functools import partial
from trytond.model import DeactivableMixin, ModelSQL, ModelView, fields
from trytond.pool import Pool
from trytond.transaction import Transaction

from datetime import datetime, timedelta
from flask_babel import format_date

from werkzeug.routing import Map
from werkzeug.wrappers import Response
from dominate.tags import (div, p)

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
        lang_name = lang.name

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

def component(name):
    """
    Given a component __name__, return the component object
    """
    pool = Pool()

    try:
        Component = pool.get(name)
    except:
        raise ValueError('No component found for name %s' % name)
    return Component

def render_component(name, lazy=False, **kwargs):
    """
    Given a component __name___, return the render, if we set the lazy flag to
    true, we use the lazy render (render_lazy component method) instead of try
    render the component
    """
    pool = Pool()

    Component = pool.get(name)
    component = Component(render=False)

    '''
    try:
        Component = pool.get(name)
        component = Component()
    except Exception as e:
        raise ValueError('No component found for name %s' % name)
    '''

    if lazy:
        return component.render_lazy()
    return component.tag()

class Site(DeactivableMixin, ModelSQL, ModelView):
    'WWW Site'
    __name__ = 'www.site'
    __slots__ = ['map']

    name = fields.Char('Name', required=True)
    url = '0.0.0.0:5000'
    session_lifetime = fields.Integer('Session Lifetime',
        help="The session lifetme in secons")
    session_lifetime_update_frecuency = fields.Integer(
        'Session Lifetime Update Frecuency',
        help="The frecuency to update the session lifetime in secons")
    # Head arguments
    metadescription = fields.Char('Metadescription')
    keywords = fields.Char('Keywords', help="List of keywords separate by comma")
    metatitle = fields.Char('Metatitle')
    canonical = fields.Char('Canonical')
    author = fields.Char('Author')
    title = fields.Char('Title')
    css_min = fields.Boolean('CSS Min')

    # url
    # author
    # description

    @staticmethod
    def default_session_lifetime():
        return 3600

    @staticmethod
    def default_session_lifetime_update_frecuency():
        return 1800

    def path_from_view(self, view):
        pool = Pool()

        if isinstance(view, str):
            View = pool.get('ir.ui.view')
        else:
            View = view
        return View._path

    @classmethod
    def handle(cls, name, path, request):
        pool = Pool()
        Session = pool.get('www.session')

        sites = cls.search([('name', '=', name)], limit=1)
        if not sites:
            raise ValueError('Site "%s" not found' % name)
        site, = sites

        web_map, adapter, endpoint_args = site.get_site_info()

        # Get the component and function to execute
        endpoint, args = adapter.match(path)
        component_model = endpoint.split('/')[0]
        component_function = None

        if len(endpoint.split('/')) > 1:
            component_model = endpoint.split('/')[0]
            component_function = endpoint.split('/')[-1]
        else:
            component_function = 'tag'

        # Handle component errors
        if not component_model:
            raise KeyError('No component found %s' % endpoint)
        try:
            Component = pool.get(component_model)
        except:
            raise ValueError('No component found %s' % component_model)


        print(f'==== ENDPOINT: {endpoint} | ARGS: {args} ====')

        if request.method == 'POST':
            # In case we have a post method, use the request form as args. This
            # means that we have a componet for each form and the form and
            # the componet will need to have the same number of fields.
            args = request.form

        # Check the session
        with Transaction().set_context(site=site):
            session = Session().get(request)

        with Transaction().set_context(site=site, path=path, session=session):
            # Get the component object and function
            try:
                Component = pool.get(component_model)
            except:
                raise ValueError('No component found %s' % component_model)
            try:
                function = getattr(Component, component_function)
            except:
                raise ValueError('No function found %s' % component_function)

            # Get the variables needed to creatne the component and execute the
            # function
            function_variables = {}
            instance_variables = {}
            for arg in args.keys():
                if arg in function.__code__.co_varnames:
                    function_variables[arg] = args[arg]
                else:
                    instance_variables[arg] = args[arg]
            print(f'Function variables: {function_variables} \n Instance variables: {instance_variables}')

            #TODO: make more efficent the way we get the compoent, right
            # now, even if we dont use the compoent we "execute" the render
            # function
            if function_variables:
                instance_variables['render'] = False
                component = Component(**instance_variables)
                res = getattr(component, component_function)(function_variables)
            else:
                component = Component(**instance_variables)
                res = getattr(component, component_function)()

            # Render the content and prepare the response. The DOMinate render
            # can handle the raw() objects and any tag (html_tag) we send any
            # other format will raise a traceback
            #print(f'\nRES: {res} \nTYPE: {type(res)}\n')

            if res and isinstance(res, Response):
                response = res
            elif res:
                #TODO: temporal solution until DOMinate render htmx tags:
                # https://github.com/Knio/dominate/issues/193
                #print(f'---- RES: {res.render()} | {type(res.render())} ----')
                res = res.render().replace('hx_', 'hx-')
                response = flask.make_response(res)
            else:
                response = flask.make_response()

            # Add all the htmx triggers to the header of the response
            if len(Trigger.get_triggers()) > 0:
                response.headers['HX-Trigger'] = ', '.join(
                    list(Trigger.get_triggers()))
            response.set_cookie('session_id', session.session_id)
            return response

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

    def get_site_info(self):
        '''
        This function will return the map of the site, with the rules for all
        the components and the arguments of each endpoint. The endpoints always
        will have the next format:
            - model_name -> This function always return the result of the
                render function of the component)
            - model_name/function -> This function will execute a especific
                function inside the component "model_name". We need the
                endpoint to have the SAME NAME as the function, otherwise, the
                endpoint will fail.
        '''
        pool = Pool()

        web_map = Map()
        endpoint_args = {}
        for _, Model in pool.iterobject():
            if issubclass(Model, Component):
                for url_map in Model.get_url_map():
                    if not url_map.endpoint:
                        # If we dont have an endpoint, we need to set as edpoint
                        # the model name
                        url_map.endpoint = Model.__name__
                    else:
                        # If we have an edpoint, it means we want to execute a
                        # function, we need to set the format:
                        # model_name/function
                        url_map.endpoint = f'{Model.__name__}/{url_map.endpoint}'

                    # Get the "attributes" of the url
                    args = []
                    for segment in str(url_map).split('/'):
                        if segment.startswith('<') and segment.endswith('>'):
                            arg = segment.split(':')[-1].replace('>','')
                            args.append(arg)
                    if (url_map.endpoint in endpoint_args and
                            endpoint_args[url_map.endpoint] != args):
                        raise KeyError('Incorrect args in endpoint %s' % url_map.endpoint)

                    endpoint_args[url_map.endpoint] = args
                    # In booth cases we add the url_map to the web_map variable
                    web_map.add(url_map)

        adapter = web_map.bind(self.url, '/')
        return web_map, adapter, endpoint_args

    def template_filters(self):
        return {
            'dateformat': dateformat,
            }


class Session(ModelSQL, ModelView):
    'Session'
    __name__ = 'www.session'
    site = fields.Many2One('www.site', 'Site', required=True)
    session_id = fields.Char('Session ID', required=True)
    user = fields.Many2One('galatea.user', 'User')
    expiration_date = fields.DateTime('Expiration Date', required=True)
    #TODO: create cron to clean sessions

    @classmethod
    def get(cls, request):
        create_session = False
        if 'session_id' in request.cookies:
            sessions = cls.search([
                ('session_id', '=', request.cookies['session_id']),
            ], limit=1)

            if not sessions:
                create_session = True
                session = None
            else:
                session, = sessions

            if session.expiration_date < datetime.now():
                create_session = True
            else:
                session.update_expiration_date()
        else:
            create_session = True

        if create_session:
            session = cls.new()
        return session

    def update_expiration_date(self):
        if (self.expiration_date + timedelta(
                seconds=self.site.session_lifetime_update_frecuency) <
                datetime.now()):
            self.expiration_date = (datetime.now() +
                timedelta(seconds=self.site.session_lifetime))
            self.save()

    def set_user(self, user):
        self.user = user
        self.save()

    @classmethod
    def new(cls):
        pool = Pool()
        Site = pool.get('www.site')

        site = Site(Transaction().context.get('site'))
        session_id = secrets.token_urlsafe()

        session = cls()
        session.site = site
        session.session_id = session_id
        session.expiration_date = datetime.now() + timedelta(
            seconds=site.session_lifetime)
        session.save()
        return session


class Component(ModelView):
    'Component'
    __slots__ = ['_tag']
    _path = None
    #_tag = None

    @classmethod
    @property
    def context(cls):
        return Transaction().context

    @property
    def site(cls):
        return Transaction().context.get('site')

    @property
    def session(cls):
        return Transaction().context.get('session')

    def __init__(self, *args, **kwargs):
        render = True
        if 'render' in kwargs:
            render = kwargs['render']
            kwargs.pop('render')
        super().__init__(*args, **kwargs)
        for x in dir(self):
            #TODO: This function is "hardcoded" by now, we need to search a
            # method to get only the triggers from the clas
            if x == 'updated':
                if isinstance(getattr(self, x), Trigger):
                    getattr(self, x).name = f"{self.__name__.replace('.','-')}_{x}"

        self._tag = None
        if render:
            self.create_tag()
            self.tag()

    @property
    def path(self):
        return self._path

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
    def get_global_functions(cls):
        return {
            'component': component,
            'render_component': render_component,
        }

    @classmethod
    def render_template(cls, template, **kwargs):
        template = cls.load_template(template)
        context = cls.template_context().copy()
        context.update(kwargs)
        env = cls.get_environment()
        template = env.from_string(template)
        template.globals.update(cls.get_global_functions())
        return template.render(context)

    @classmethod
    def get_template_paths(cls):
        return [os.path.abspath(os.path.join(os.path.dirname(__file__), 'voyager'))]

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

    def render(self):
        raise NotImplementedError('Method render not implemented')

    def lazy_content(self):
        '''
        The alternative content to show while the component is loading
        '''
        return p('Loading...')

    def render_lazy(self):
        '''
        The loading div that we show when the component is loading.
        '''
        #TODO: calculate the path using "build_url" method
        loading_div = div(hx_get=self.path, hx_trigger='load')
        with loading_div:
            self.lazy_content()
        return loading_div

    def create_tag(self):
        self._tag = self.render()

    def tag(self):
        return self._tag

    @classmethod
    def get_url_map(cls):
        """
        Return a list with all the new rules this component add to the site.
        TODO: this function needs to be modified in every module
        """
        return []

    def url(self, endpoint=None, **kwargs):
        """
        Given an endpoint and a set of arguments, render and return an url.
        """
        web_map, adapter, endpoint_args =self.context['site'].get_site_info()

        #TODO: set context here to set language in url
        if not endpoint:
            endpoint = self.__class__.__name__
        else:
            endpoint = f'{self.__class__.__name__}/{endpoint}'

        # Always expect the elment here
        for arg in endpoint_args[endpoint]:
            kwargs[arg] = getattr(self, arg)
        return adapter.build(endpoint, kwargs)


class Trigger():
    def __init__(self, name=None):
        self.name = name

    def __repr__(self):
        return self.name

    @staticmethod
    def add_trigger(trigger):
        triggers = Transaction().context.get('triggers', set([]))
        triggers.add(trigger.name)
        Transaction().set_context(triggers=triggers)

    @staticmethod
    def get_triggers():
        return Transaction().context.get('triggers', set([]))
