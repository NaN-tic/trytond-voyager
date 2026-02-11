import logging
import os
import secrets
from datetime import datetime, timedelta

import jinja2
import markdown
from dominate.tags import div, p
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
from trytond.cache import Cache, freeze
from trytond.config import config
from trytond.model import (DeactivableMixin, ModelSQL, ModelView, fields,
    dualmethod)
from trytond.pool import Pool
from trytond.wizard import Button, StateTransition, StateView, Wizard
from trytond.transaction import Transaction
from trytond.tools import grouped_slice
from werkzeug.routing import Map, Rule
from werkzeug.wrappers import Response
from werkzeug.exceptions import HTTPException
from werkzeug.utils import redirect

CACHE_ENABLED = config.getboolean('voyager', 'cache_enabled', default=True)
CACHE_TIMEOUT = config.getint('voyager', 'cache_timeout', default=60 * 60)

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
        if not CACHE_ENABLED:
            return None
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
    def __init__(self, site=None, session=None, cache=None, request=None,
            adapter=None, endpoint_args=None, web_prefix=None):
        super().__init__()
        self.site = site
        self.session = session
        self.cache = cache
        self.request = request
        self.adapter = adapter
        self.endpoint_args = endpoint_args
        self.web_prefix = web_prefix


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
    route_method = fields.Selection([
        ('endpoint', 'Endpoint'),
        ('uri', 'URI')], 'Route Method')

    @staticmethod
    def default_session_lifetime():
        return 3600

    @staticmethod
    def default_session_lifetime_update_frequency():
        return 1800

    @staticmethod
    def default_route_method():
        return 'endpoint'

    def path_from_view(self, view):
        pool = Pool()

        if isinstance(view, str):
            View = pool.get('ir.ui.view')
        else:
            View = view
        return View._path

    def get_cache(self, session, request):
        return CacheManager.get(self.id)

    def _get_context(self, session, component_model, args):
        '''
        Return the specific context for the site
        '''
        return {}

    def from_url_prefix(self, endpoint=None):
        '''
        Return the specific prefixes on the site
        '''
        return ''

    def to_url_prefix(self, endpoint, values={}):
        '''
        Return the specific data for the site prefixes on the site
        '''
        return {}


    def match_request(self, request, web_prefix=None):
        '''
        Given a request and site, check if the request uses any of the site
        endpoints and return the endpoint, args, adapter and endpoint_args
        '''
        pool = Pool()
        VoyagerURI = pool.get('www.uri')

        web_map, adapter, endpoint_args, error_handlers = self.get_site_info(
            web_prefix)

        # Get the component and function to execute
        try:
            language = None
            request_path = request.path
            if web_prefix:
                request_path = request.path.replace(
                    web_prefix, '', 1)

            if self.route_method == 'uri':
                voyager_uri = VoyagerURI.search([
                    ('site', '=', self.id),
                    ('uri', '=', request_path)], limit=1)

                if voyager_uri:
                    voyager_uri = voyager_uri[0]
                    endpoint = voyager_uri.endpoint.name
                    resource = voyager_uri.resource
                    resource_model = getattr(resource, '__name__', None)
                    args = {}

                    if not resource_model:
                        resource_model = str(resource).split(',')[0]
                    try:
                        EndpointModel = pool.get(endpoint)
                    except Exception:
                        EndpointModel = None
                    if EndpointModel:
                        for field_name, field in EndpointModel._fields.items():
                            if (isinstance(field, fields.Many2One)
                                    and field.model_name == resource_model):
                                args[field_name] = resource.id
                    if voyager_uri.language:
                        language = voyager_uri.language.code
                else:
                    if request.method:
                        endpoint, args = adapter.match(request.path,
                            request.method)
                    else:
                        endpoint, args = adapter.match(request.path)
            elif self.route_method == 'endpoint':
                if request.method:
                    endpoint, args = adapter.match(request.path,
                        request.method)
                else:
                    endpoint, args = adapter.match(request.path)
        except HTTPException as e:
            # HTTPException is the mixin used for all the http erros from
            # werkzeug, in the base class we have always the code, name and
            # description attributes
            if e.code in error_handlers:
                endpoint = error_handlers[e.code]
                #TODO: we need to decide here what we sent to the exception
                # defaults functions
                return (None, None, None, None, None,
                    adapter.build(endpoint.__name__, None))
                # We cant use the url function because we dont have the
                # adapter at this point
            else:
                raise e
        return endpoint, args, adapter, endpoint_args, language, None

    @classmethod
    def dispatch(cls, site_type, site_id, request, user_id=None,
            web_prefix=None):
        pool = Pool()
        Session = pool.get('www.session')
        User = pool.get('res.user')

        if not user_id:
            user_id = config.get('voyager', 'user')

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

        (endpoint, args, adapter, endpoint_args, language,
            error) = site.match_request(request, web_prefix)

        if not language:
            language = Transaction().context.get('language')

        if error:
            return redirect(error)

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

        cache = site.get_cache(session, request)
        voyager_context = VoyagerContext(site=site, session=session,
            cache=cache, request=request, adapter=adapter,
            endpoint_args=endpoint_args, web_prefix=web_prefix)
        system_user_id = session.system_user and session.system_user.id
        user_id = system_user_id or user_id
        if cache:
            context = cache.get('user-preferences-%d' % user_id)
        else:
            context = None
        if not context:
            user = User(user_id)
            context = User._get_preferences(user, context_only=True)
            if cache:
                cache.set('user-preferences-%d' % user_id, context)
            context['language'] = language

        context.update(site._get_context(session, component_model, args ))
        with Transaction().set_context(voyager_context=voyager_context,
                path=request.path, **context):
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
                if arg not in Component._fields.keys():
                    continue
                value = args[arg]
                if hasattr(Component, arg):
                    if getattr(Component, arg) and hasattr(
                            getattr(Component, arg), 'model_name'):
                        Model = pool.get(getattr(Component, arg).model_name)
                        if hasattr(Model, 'from_request'):
                            value = Model.from_request(site, args[arg],
                                Component.__name__)
                        else:
                            # If we found a model and we dont use "from_request",
                            # check if the id exists, if not exists, set value
                            # to None
                            if not Model.search([('id', '=', args[arg])]):
                                value = None
                            else:
                                value = int(args[arg])
                if arg in function.__code__.co_varnames[:function.__code__.co_argcount]:
                    function_variables[arg] = value
                else:
                    instance_variables[arg] = value

            # TODO: make more efficent the way we get the component, right
            # now, even if we don't use the compoent we "execute" the render
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
            if response:
                response.set_cookie('session_id', session.session_id)
            return response

    def template_context(self):
        context = Transaction().context.copy()
        return context

    def get_site_info(self, web_prefix):
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
        error_handlers = {}
        for key, Model in pool.iterobject():
            if issubclass(Model, Endpoint):
                if not Model._type:
                    raise KeyError('Missing type in model %s' % Model.__name__)

                types = Model._type
                if isinstance(Model._type, str):
                    types = [Model._type]

                if self.type not in types:
                    continue

                methods = Model._method
                if isinstance(Model._method, str):
                    methods = [Model._method]

                url_map = Rule(
                    f'{web_prefix or ""}{self.from_url_prefix(Model)}{Model._url}',
                    endpoint = Model.__name__,
                    methods=methods)

                status = Model._status
                if Model._status and isinstance(Model._status, int):
                    status = [Model._status]

                if status:
                    for status in status:
                        error_handlers[status] = Model

                args = []
                for segment in str(url_map).split('/'):
                    if segment.startswith('<') and segment.endswith('>'):
                        arg = segment.split(':')[-1].replace('>','')
                        args.append(arg)
                if (url_map.endpoint in endpoint_args and
                        endpoint_args[url_map.endpoint] != args):
                    raise KeyError('Incorrect args in endpoint %s' % url_map.endpoint)

                endpoint_args[url_map.endpoint] = args
                web_map.add(url_map)
        adapter = web_map.bind(self.url, '/')
        return web_map, adapter, endpoint_args, error_handlers

    def template_filters(self):
        return {
            }

    def rendermarkdown(self, text, start_header=1):
        '''Return html text from markdown format'''
        if not text:
            return ''

        try:
            text = markdown.markdown(text, output_format='xhtml',
                extensions=['tables'])
        except Exception as e:
            print(f'Error: {e}')
            return ''

        if start_header > 1:
            MAX_HEADER = 6

            # Because we cannot replace h6 with a lower one, we need to start replacing from h5 to h1
            for level in range(MAX_HEADER - 1, 0, -1):
                replc = level + (start_header - 1)

                if replc > MAX_HEADER:
                    replc = MAX_HEADER

                text = text.replace(f'<h{level}', f'<h{replc}').replace(f'</h{level}>', f'</h{replc}>')

        return text


class Session(ModelSQL, ModelView):
    'Session'
    __name__ = 'www.session'
    site = fields.Many2One('www.site', 'Site', required=True)
    session_id = fields.Char('Session ID', required=True)
    user = fields.Many2One('web.user', 'User')
    system_user = fields.Many2One('res.user', 'System User')
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
        last_update = self.write_date or self.create_date
        if (last_update + timedelta(
                seconds=self.site.session_lifetime_update_frequency) <
                datetime.now()):
            self.expiration_date = (datetime.now() +
                timedelta(seconds=self.site.session_lifetime))
            self.save()

    def set_user(self, user):
        self.user = user
        self.save()

    def set_system_user(self, user):
        self.system_user = user
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

    @property
    def context(self):
        return Transaction().context

    @property
    def site(self):
        if hasattr(Transaction().context.get('voyager_context'), 'site'):
            return Transaction().context.get('voyager_context').site

    @property
    def session(self):
        if hasattr(Transaction().context.get('voyager_context'), 'session'):
            return Transaction().context.get('voyager_context').session

    @classmethod
    def web_prefix(cls):
        if hasattr(Transaction().context.get('voyager_context'), 'web_prefix'):
            return Transaction().context.get('voyager_context').web_prefix

    @classmethod
    def adapter(cls):
        if hasattr(Transaction().context.get('voyager_context'), 'adapter'):
            return Transaction().context.get('voyager_context').adapter

    @classmethod
    def endpoint_args(cls):
        if hasattr(Transaction().context.get('voyager_context'), 'endpoint_args'):
            return Transaction().context.get('voyager_context').endpoint_args

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
        raise NotImplementedError('Method lazy_content not implemented')

    def render_lazy(self):
        raise NotImplementedError('Method render_lazy not implemented')

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
        use_cache = CACHE_ENABLED and self.cached and self.cache
        if use_cache:
            key = self.get_cache_key()
            if key and self.cache.get(key):
                self._tag = self.cache.get(key)
                return
        self._tag = self.render()
        if use_cache and key:
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
        adapter = self.adapter()
        endpoint_args = self.endpoint_args()

        #TODO: set context here to set language in url
        if not endpoint:
            endpoint = self.__class__.__name__
        else:
            endpoint = f'{self.__class__.__name__}/{endpoint}'

        # Always expect the elment here
        for arg in endpoint_args[endpoint]:
            value = getattr(self, arg)
            if hasattr(value, '__name__'):
                if hasattr(value, 'to_request'):
                    value = value.to_request(self.site, self.__name__)
                else:
                    value = value.id
            kwargs[arg] = value
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


class Endpoint(Component):
    'Endpoint'

    _url = None
    _method = 'GET'
    _status = None
    _type = None

    def __init__(self, *args, **kwargs):
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

    def lazy_content(self):
        '''
        The alternative content to show while the component is loading
        '''
        return p('Loading...')

    def render_lazy(self):
        '''
        The loading div that we show when the component is loading.
        '''
        loading_div = div(hx_get=self.url(), hx_trigger='load')
        with loading_div:
            self.lazy_content()
        return loading_div

    @dualmethod
    def url(cls, **kwargs):
        pool = Pool()
        VoyagerURI = pool.get('www.uri')

        values = {}
        uri_values = {}
        voyager_uri = None

        site = None
        context = Transaction().context.get('voyager_context')
        if hasattr(context, 'site'):
            site = context.site

        for key, raw in kwargs.items():
            if not hasattr(cls, key):
                # Key not found
                value = raw
            else:
                # Key found, check if it is a model
                field = getattr(cls, key)
                if hasattr(field, 'model_name'):
                    value = raw

                    Model = pool.get(field.model_name)
                    if hasattr(Model, 'to_request'):
                        if Model.search([('id', '=', raw)]):
                            model = Model(raw)
                            value = model.to_request(cls.site, cls.__name__)
                else:
                    value = raw
            values[key] = value

            if site and site.route_method == 'uri':
                if (key in cls._fields.keys() and
                        isinstance(cls._fields.get(key), fields.Many2One)):
                    if isinstance(raw, ModelSQL):
                        resource = raw
                    else:
                        Model = pool.get(cls._fields.get(key).model_name)
                        resource = Model(raw)

                    if not voyager_uri:
                        voyager_uris = VoyagerURI.search([
                            ('site', '=', site.id),
                            ('endpoint.model', '=', cls.__name__),
                            ('resource', '=', str(resource)),
                        ], limit=1)

                        if voyager_uris:
                            voyager_uri = voyager_uris[0]
                    else:
                        uri_values[key] = raw
                else:
                    uri_values[key] = raw

        if site:
            values.update(site.to_url_prefix(cls, values))

        if voyager_uri:
            parsed = urlparse(voyager_uri.uri)
            query = dict(parse_qsl(parsed.query))
            query.update(uri_values)
            return f'{cls.web_prefix()}{urlunparse(parsed._replace(query=urlencode(query)))}'

        #Minimum required to handle the url building
        adapter = cls.adapter()
        builder = adapter.build(cls.__name__, values)
        return f'{builder}'


class VoyagerURL():

    def to_request(self, site, component):
        raise NotImplementedError('Method to_request not implemented')

    @classmethod
    def from_request(cls, site, value, component):
        raise NotImplementedError('Method to_request not implemented')


class VoyagerURI(DeactivableMixin, ModelSQL, ModelView):
    'Voyager URI'
    __name__ = 'www.uri'

    site = fields.Many2One('www.site', 'Site', required=True)
    uri = fields.Char('URI', required=True)
    main_uri = fields.Many2One(
        'www.uri', 'Main URI',
        domain=[
            ('main_uri', '=', None),
        ])
    related_uris = fields.One2Many(
        'www.uri', 'main_uri', 'Related URIs')
    canonical_uri = fields.Function(
        fields.Many2One('www.uri', 'Canonical URI'),
        'get_canonical_uri',
    )
    language = fields.Many2One('ir.lang', 'Language')
    endpoint = fields.Many2One('ir.model', 'Endpoint', required=True)
    resource = fields.Reference('Resource', selection='get_resources',
        readonly=True)

    def get_rec_name(self, name):
        return self.uri or ''

    def _get_canonical_uri(self):
        URI = self.__class__

        language = Transaction().context.get('language')
        related = URI.search([
            ('main_uri', '=', self.id),
            ('language.code', '=', language)])
        return related and related[0] or None

    @classmethod
    def get_canonical_uri(cls, uris, name):
        result = {}

        for uri in uris:
            if uri.main_uri:
                result[uri.id] = uri.main_uri._get_canonical_uri()
            elif uri.related_uris:
                result[uri.id] = uri._get_canonical_uri()
            else:
                result[uri.id] = None
        return result

    @classmethod
    def _get_resources(cls):
        return []

    @classmethod
    def get_resources(cls):
        Model = Pool().get('ir.model')
        models = Model.search([('name', 'in', cls._get_resources())])
        return [(None, '')] + [
            (model.model, model.name)
            for model in models
        ]

    @classmethod
    def compute_uris(cls, dictionary):
        if not dictionary:
            return
        records, sites = zip(*dictionary.keys())
        old_uris = {
            ((str(uri.site.id), str(uri.resource)) , uri.uri) : uri
            for uri in cls.search([
                ('resource', 'in', list(set(records))),
                ('site', 'in', list(set(sites))),
            ])
        }

        to_save = []
        to_deactivate = old_uris.copy()
        for uris in dictionary.values():
            for uri in uris:
                key = (str(uri.site.id), str(uri.resource),uri.uri)
                if key not in old_uris:
                    to_save.append(uri)
                else:
                    to_deactivate.pop(key, None)
        cls.write(list(to_deactivate.values()), {'active': False})
        cls.save(to_save)

#TODO: validate unique uri per site and language


class VoyagerUriBuilderAsk(ModelView):
    'Voyager URI Builder Ask'
    __name__ = 'www.uri.builder.ask'

    sites = fields.MultiSelection(string="Sites", selection="get_sites")
    models = fields.MultiSelection(string="Models", selection="get_models")

    @staticmethod
    def default_models():
        pool = Pool()
        URI = pool.get('www.uri')
        return URI._get_resources()

    @staticmethod
    def default_sites():
        pool = Pool()
        Site = pool.get('www.site')
        return [str(site.id) for site in Site.search([])]

    @classmethod
    def get_sites(cls):
        pool = Pool()
        Site = pool.get('www.site')

        return [
            (str(site.id), site.name)
            for site in Site.search([])
        ]

    @classmethod
    def get_models(cls):
        pool = Pool()
        URI = pool.get('www.uri')

        return [
            (model, name)
            for model, name in URI.get_resources()
            if model and getattr(pool.get(model), "generate_uri", False)
        ]


class VoyagerUriBuilderResult(ModelView):
    'Voyager URI Builder Result'
    __name__ = 'www.uri.builder.result'

    result = fields.Text('Result', readonly=True)


class VoyagerUriBuilder(Wizard):
    'Voyager URI Builder'
    __name__ = 'www.uri.builder'

    start_state = 'ask'

    ask = StateView('www.uri.builder.ask',
        'voyager.uri_builder_ask_form_view', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Build URIs', 'build_uris', 'tryton-ok', default=True),
        ])
    build_uris = StateTransition()
    result = StateView('www.uri.builder.result',
        'voyager.uri_builder_result_form_view', [
            Button('Close', 'end', 'tryton-ok'),
        ]
    )

    def transition_build_uris(self):
        pool = Pool()
        Site = pool.get('www.site')

        sites = [Site(int(site_id)) for site_id in self.ask.sites]

        for model_name in self.ask.models:
            Model = pool.get(model_name)
            if not hasattr(Model, 'generate_uri'):
                continue
            for records in grouped_slice(Model.search([])):
                Model.generate_uri(list(records), sites=sites)

        self.result.result = 'URIs generated for models: %s' % ', '.join(
            self.ask.models)
        return 'result'

    def default_result(self, fields):
        return {
            'result': self.result.result or '',
        }
