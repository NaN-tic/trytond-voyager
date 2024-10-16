import os
import jinja2
import logging
import markdown
import secrets
from trytond.model import DeactivableMixin, ModelSQL, ModelView, fields
from trytond.cache import Cache, freeze
from trytond.config import config
from trytond.pool import Pool
from trytond.transaction import Transaction

from datetime import datetime, timedelta
from werkzeug.routing import Map
from werkzeug.wrappers import Response
from dominate.tags import (div, p)

CACHE_ENABLED = config.get('voyager', 'cache_enabled', default=True)
CACHE_TIMEOUT = config.get('voyager', 'cache_timeout', default=60 * 60)

logger = logging.getLogger(__name__)


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
    if lazy:
        return component.render_lazy()
    return component.tag()


class VoyagerCache(Cache):
    # Override _key() to remove the session from the context and use the user
    # instead (when there's a user), otherwise keep the session
    pass


class CacheManager:
    caches = {}

    @classmethod
    def get(cls, site_id):
        database = Transaction().database.name
        key = (database, site_id)
        if key not in cls.caches:
            cls.caches[key] = VoyagerCache('voyager.cache',
                duration=CACHE_TIMEOUT)
        return cls.caches[key]


# The reason we inherit from dict is that a VoyagerContext instance will be
# stored in the context which Tryton will try to serialize (convert to json) if
# it needs to execute a function in the worker. Trying to serialize
# VoyagerContext will crash unless it is from a type JSONEncoder understands by
# default
class VoyagerContext(dict):
    def __init__(self, site=None, session=None, cache=None):
        super().__init__()
        self.site = site
        self.session = session
        self.cache = cache


class Site(DeactivableMixin, ModelSQL, ModelView):
    'WWW Site'
    __name__ = 'www.site'
    __slots__ = ['map']

    name = fields.Char('Name', required=True)
    type = fields.Selection([], 'Type', required=True)
    url = fields.Char('URL', required=True)
    session_lifetime = fields.Integer('Session Lifetime',
        help="The session lifetme in secons")
    session_lifetime_update_frequency = fields.Integer(
        'Session Lifetime Update Frecuency',
        help="The frequency to update the session lifetime in seconds")
    # Head arguments
    metadescription = fields.Char('Metadescription')
    keywords = fields.Char('Keywords', help="Comma-separated list of keywords")
    metatitle = fields.Char('Metatitle')
    canonical = fields.Char('Canonical')
    author = fields.Char('Author')
    title = fields.Char('Title')

    @staticmethod
    def default_session_lifetime():
        return 3600

    @staticmethod
    def default_session_lifetime_update_frequency():
        return 1800

    def path_from_view(self, view):
        pool = Pool()

        if isinstance(view, str):
            View = pool.get('ir.ui.view')
        else:
            View = view
        return View._path

    @classmethod
    def dispatch(cls, site_type, site_id, request, user=None):
        pool = Pool()
        Session = pool.get('www.session')
        User = pool.get('res.user')
        if not user:
            user = config.get('voyager', 'user')

        if site_id:
            site = cls(site_id)
        else:
            sites = cls.search([('type', '=', site_type)], limit=1)
            if sites:
                site, = sites
            else:
                site = cls()
                site.name = site_type
                site.type = site_type
                site.url = request.url_root
                site.save()
        web_map, adapter, endpoint_args = site.get_site_info()

        # Get the component and function to execute
        print(f'Request: {request} | Path: {request.path}')
        endpoint, args = adapter.match(request.path)
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
        print(f'Transaction {Transaction().context}')
        if request.method == 'POST':
            # In case we have a post method, use the request form as args. This
            # means that we have a componet for each form and the form and
            # the componet will need to have the same number of fields.
            # If we have any valu in the original args, we add the request
            # forms values to the existent args dictionary, if we dont have any
            # args, replace the original args with the request form values.
            if args:
                for request_key in dict(request.form):
                    args[request_key] = request.form[request_key]
            else:
                args = request.form

        # Check the session
        with Transaction().set_context(site=site):
            session = Session().get(request)

        cache = CacheManager.get(site.id)
        system_user = session.system_user and session.system_user.id
        user = system_user or user
        voyager_context = VoyagerContext(site=site, session=session, cache=cache)
        with Transaction().set_context(voyager_context=voyager_context, path=request.path,
            company=User(user).company.id, user=user):
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
                if arg in function.__code__.co_varnames[:function.__code__.co_argcount]:
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
                #TODO: we need to handle the error pages here
                response = getattr(component, component_function)(function_variables)
            else:
                component = Component(**instance_variables)
                #TODO: we need to handle the error pages here
                response = getattr(component, component_function)()

            # Render the content and prepare the response. The DOMinate render
            # can handle the raw() objects and any tag (html_tag) we send any
            # other format will raise a traceback
            if response and not isinstance(response, Response):
                if not response:
                    response = ''
                #TODO: Temporary solution until DOMinate render htmx tags:
                # https://github.com/Knio/dominate/issues/193
                response = response.render().replace('hx_', 'hx-')
                response = Response(response, content_type='text/html')

            # Add all the htmx triggers to the header of the response
            if Trigger.get_triggers():
                response.headers['HX-Trigger'] = ', '.join(
                    list(Trigger.get_triggers()))
            response.set_cookie('session_id', session.session_id)
            return response

    def template_context(self):
        context = Transaction().context.copy()
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
        for key, Model in pool.iterobject():
            if issubclass(Model, Component):
                for url_map in Model.get_url_map():
                    if not url_map.endpoint:
                        # If we dont have an endpoint, we need to set as endpoint
                        # the model name
                        # TODO: Do we really want a default endpoint?
                        url_map.endpoint = Model.__name__
                    else:
                        # If we have an endpoint, it means we want to execute a
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
            }

    def rendermarkdown(self, text):
        '''Return html text from markdown format'''
        def header_level(text):
            for count in range(5, 0, -1):
                hs = str(count)
                hr = str(count+1)
                text = text.replace(f'<h{hs}', f'<h{hr}').replace(
                    f'</h{hs}>', f'</h{hr}>')
            return text

        if not text:
            return ''
        try:
            text = markdown.markdown(text, output_format='xhtml')
        except Exception as e:
            print(f'Error: {e}')
            return ''
        return text


class Session(ModelSQL, ModelView):
    'Session'
    __name__ = 'www.session'
    site = fields.Many2One('www.site', 'Site', required=True)
    session_id = fields.Char('Session ID', required=True)
    user = fields.Many2One('web.user', 'User')
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
                seconds=self.site.session_lifetime_update_frequency) <
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
    __slots__ = ['_tag', 'cached']
    _path = None
    _cached = True

    def __init__(self, *args, **kwargs):
        render = True
        if 'render' in kwargs:
            render = kwargs['render']
            kwargs.pop('render')
        self.cached = self._cached
        if 'cached' in kwargs:
            self.cached = self.cached and kwargs['cached']
            kwargs.pop('cached')
        super().__init__(*args, **kwargs)
        for x in dir(self):
            # TODO: This function is "hardcoded" by now, we need to search a
            # method to get only the triggers from the class
            if x == 'updated':
                if isinstance(getattr(self, x), Trigger):
                    getattr(self, x).name = f"{self.__name__.replace('.','-')}_{x}"

        self._tag = None
        if render:
            self.create_tag()

    @classmethod
    @property
    def context(cls):
        return Transaction().context

    @classmethod
    @property
    def site(cls):
        if hasattr(Transaction().context.get('voyager_context'), 'site'):
            return Transaction().context.get('voyager_context').site

    @classmethod
    @property
    def session(cls):
        if hasattr(Transaction().context.get('voyager_context'), 'session'):
            return Transaction().context.get('voyager_context').session

    @property
    def path(self):
        return self._path

    @classmethod
    def load_template(cls, name):
        if '/' in name:
            module, name = name.split('/', 1)
            path = os.path.join(os.path.dirname(__file__), '..', module)
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

    def get_cache_key(self):
        if self._fields:
            key = freeze([getattr(self, x, None) for x in self._fields])
        else:
            key = freeze(tuple())
        return (self.__name__,) + key

    @property
    def cache(self):
        if hasattr(self.context.get('voyager_context'), 'cache'):
            return self.context.get('voyager_context').cache

    def create_tag(self):
        if CACHE_ENABLED and self.cached:
            key = self.get_cache_key()
            if key and self.cache.get(key):
                self._tag = self.cache.get(key)
                return
        self._tag = self.render()
        if CACHE_ENABLED and self.cached and key:
            try:
                self.cache.set(key, self._tag)
            except RecursionError:
                logger.warning('RecursionError setting cache key: %s', key)

    def tag(self):
        if not self._tag:
            self.create_tag()
        return self._tag

    @classmethod
    def get_url_map(cls):
        """
        Return a list with all the new rules this component add to the site.
        This function needs to be modified in every component
        """
        return []

    def url(self, endpoint=None, **kwargs):
        """
        Given an endpoint and a set of arguments, render and return an url.
        """
        web_map, adapter, endpoint_args = self.site.get_site_info()

        #TODO: set context here to set language in url
        if not endpoint:
            endpoint = self.__class__.__name__
        else:
            endpoint = f'{self.__class__.__name__}/{endpoint}'

        # Always expect the elment here
        # TODO: we need to accept a same endpoint with multiples rules with differents args
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
