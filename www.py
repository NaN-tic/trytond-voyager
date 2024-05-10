import os
import jinja2
import flask
import secrets
from datetime import datetime, timedelta
from flask_babel import format_datetime, format_date
from functools import partial
from trytond.model import DeactivableMixin, ModelSQL, ModelView, fields
from trytond.pool import Pool
from trytond.transaction import Transaction

from werkzeug.routing import Map, Rule
from werkzeug.wrappers import Response
from dominate.tags import (div, h1, h2, p, a, form, button, span, table, thead,
    tbody, tr, td)
from dominate.tags import html_tag as html_tag
from dominate.util import raw

###
class tag(html_tag):
    pass

'''
# Agrupar elements sense utilitzar un wrapper
class fragment(html_tag):
    tagname = 'fragment'

    def _render(self):
        x = super()._render()
        elimini el tag pare

'''
###

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
    component = Component()

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

    # url
    # author
    # description
    # metadescription
    # keywords

    @staticmethod
    def default_session_lifetime():
        return 3600

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

        ###
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


        print(f'REQUEST: {request} | DIR: {dir(request)}')
        print(f'==== ENDPOINT: {endpoint} | ARGS: {args} ====')

        # Check the session
        with Transaction().set_context(site=site):
            session = Session().get(request)
            #TODO: add the user to the transaction we use to call the renders

        with Transaction().set_context(site=site, path=path):
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

            if function_variables:
                instance_variables['render'] = False
                component = Component(**instance_variables)
                res = getattr(component, component_function)(function_variables)
            else:
                component = Component(**instance_variables)
                res = getattr(component, component_function)()
            """ try:
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
            except Exception as e:
                raise ValueError(
                    'Error executing function %s: %s' % (component_function, e)) """

            # Render the content and prepare the response. The DOMinate render
            # can handle the raw() objects and any tag (html_tag) we send any
            # other format will raise a traceback
            print(f'\nRES: {res} \n')
            if res:
                res = res.render(pretty=False)
                # Create werkzeug response
                response = flask.make_response(res)
            else:
                response = flask.make_response()

            # Add all the htmx triggers to the header of the response
            print(f'TRIGGERS: {Trigger.get_triggers()}')
            response.headers['HX-Trigger'] = Trigger.get_triggers()
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
        self.expiration_date = (datetime.now() +
            timedelta(seconds=self.site.session_lifetime))
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
        #TODO: prepare the session to set the galatea user if user is logged
        session.save()
        return session


class Component(ModelView):
    _path = None

    @classmethod
    @property
    def context(cls):
        return Transaction().context

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
                    getattr(self, x).name = f"{self.__name__}/{x}"
        if render:
            self.tag()

    @property
    def path(self):
        return self._path

    @classmethod
    def add_trigger(cls, trigger):
        cls.context['site'].add_trigger(trigger)

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
        loading_div = div()
        #TODO: calculate the path using "build_url" method
        loading_div['hx-get'] = self.path
        loading_div['hx-trigger'] = 'load'
        with loading_div:
            self.lazy_content()
        return loading_div

    def tag(self):
        return self.render()

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


class Index(Component):
    'Index'
    __name__ = 'www.index'
    _path = '/'

    def render(self):
        return raw('<html><body>Site: %s</body></html>' % Index.context['site'].name)

###############
# extranet.py #
###############
class ExtranetIndex(Component):
    'Extranet Index'
    __name__ = 'www.extranet.index'
    _path = '/'

    @classmethod
    def get_url_map(cls):
        return [
            Rule('/')
        ]

    def render(self):
        return raw(self.render_template('extranet.html'))


class ExtranetLogin(Component):
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
        return raw(cls.render_template('login.html'))


class ExtranetHeader(Component):
    'Extranet Header'
    __name__ = 'www.extranet.header'
    _path = '/header'

    def render(self):
        super().render()
        return raw('<html><body>Site: %s</body></html>' % ExtranetHeader.context['site'].name)


###########
# cart.py #
###########
class CartComponent(Component):
    'Cart Component'
    __name__ = 'www.cart.widget'
    _path = '/cart/widget'

    updated = Trigger()

    #TODO: to delete
    """ def __init__(self):
        super().__init__()
        for x in dir(self):
            if isinstance(x, Trigger):
                x.name == f"{self.__name__}/{x.__name__}"

        CartComponent.updated """

    @classmethod
    def get_url_map(cls):
        return [
            Rule('/cart/widget')
        ]

    def render(self):
        pool = Pool()
        SaleLine = pool.get('sale.line')
        CCart = pool.get('www.cart.widget')

        domain = [
            ('sale', '=', None),
            #('shop', '=', SHOP),
            ('type', '=', 'line'),
            ]

        #TODO: Session

        lines = SaleLine.search(domain, limit=10)

        cart_div = div()
        cart_div['hx-trigger'] = CCart.updated
        cart_div['hx-get'] = self.url()
        with cart_div:
            with table():
                with thead():
                    head = tr()
                    head+= td("SALE LINE ID")
                    head+= td("PRODUCT ID")
                    head+= td("PRODUCT NAME ID")
                    head+= td("PRODUCT QUANTITY ID")
                    head+= td("PRODUCT PRICE")
                with tbody():
                    if lines:
                        for line in lines:
                            row=tr()
                            row+=td(line.id)
                            row+=td(line.product.id)
                            row+=td(line.product.name)
                            row+=td(line.quantity)
                            row+=td(line.unit_price)
                    else:
                        tr(td("No products in cart", colspan=5, syle="text-align:center"))
        return cart_div
        #return raw(self.render_template('cart-widget.html', lines=lines))

    def add_product(self, product, quantity = None):
        pool = Pool()
        SaleLine = pool.get('sale.line')
        Product = pool.get('product.product')
        Party = pool.get('party.party')
        Shop = pool.get('sale.shop')

        shop = Shop.search([
            ('id', '=', 1)
        ])

        with Transaction().set_context(company=shop[0].company.id):

            products = Product.search([
                ('id', '=', product)
            ])

            if not products:
                raise

            print(f'Context: {self.context}')

            #Temporal sale line to testig
            party = Party.search([
                ('id', '=', 5295)
            ])

            product = products[0]


            line = SaleLine()
            #line.sale =
            line.party = party[0]
            line.product = product
            line.on_change_product()
            print(f'TAXES2: {line.taxes}')
            line.width = 10
            line.length = 10
            line.quantity = 1
            line.on_change_quantity()
            #line.on_change_unit_price()
            #line.shop =
            SaleLine.create([line._save_values])
        Trigger.add_trigger(self.updated)
        #self.updated.trigger()
        # Create new sale line with the product
        # Reload the lines in the cart
        # Reload all the others components
        #TODO: how we know wich functions of which components we need to trigger?
        #raise
        #self.updated.trigger()

##############
# catalog.py #
##############
class CatalogComponent(Component):
    'Catalog Component'
    __name__ = 'www.catalog.component'
    _path = '/catalog'


    def render(self):
        pool = Pool()
        Product = pool.get('product.product')
        CatalogProduct = pool.get('www.catalog.product')

        products = Product.search([
            ('id', 'in', [923, 1507, 156])
        ])

        catalog_div = div()
        # In this case WE NEED ALWAYS the str() attribute
        #for product in products:
        #    catalog_div.add(CatalogProduct(product=product.id))

        with catalog_div:
            for product in products:
                CatalogProduct(product=product.id)
        #print(f'CATALOG DIV:\n{catalog_div}')
        return catalog_div

    def product_cart():
        '''
        TODO: given a product id and action manage the action of the product in a cart:
            - add: add the product to the cart
            - increment: add quantity to a specific product in a cart
            - decrement: remove quantity in a specific product in a cart

            with all the action, reload the cart (TODO: reload_cart event)
        '''

        pass

class CatalogProduct(Component):
    'Catalog Product'
    __name__ = 'www.catalog.product'
    _path = '/catalog/product'

    #product = fields.Many2One('product.product', 'Product')
    product = fields.Char('Product')

    @classmethod
    def get_url_map(cls):
        return [
            Rule('/catalog/product/<int:product>'),
            Rule('/catalog/product/<int:product>', endpoint='increase'),
            Rule('/catalog/product/add/<int:product>/', endpoint='add_cart'),
            Rule('/catalog/product/in_cart/<int:product>', endpoint='product_in_cart'),
        ]

    def render(self):
        pool = Pool()
        Product = pool.get('product.product')
        # Components
        ProductC = pool.get('www.product')
        Catalog = pool.get('www.cart.widget')

        products = Product.search([
            ('id', '=', self.product)
        ])

        if not products:
            raise
        product = products[0]

        product_div = div()
        product_div['hx-trigger'] = Catalog.updated
        product_div['hx-get'] = self.url()
        with product_div:
            a(href=ProductC(product=product.id, render=False).url()).add(h2(product.name))
            p(10)
            # TODO: hide button if product is in cart
            add_to_cart = a(id='product-%s' % product.id, href="#").add(p('Add to cart'))
            add_to_cart['hx-swap'] = 'none'
            add_to_cart['hx-get'] = self.url('add_cart')
            #add_to_cart = a(id='product-%s' % product.id, href="#").add(p('Add to cart'))
        return product_div

    def product_in_cart(self):
        # Return a mark to the specific product showing is in the cart
        return raw('Producto en el carrito!')

    def add_cart(self):
        pool = Pool()
        CCart = pool.get('www.cart.widget')
        CCart(render=False).add_product(self.product, 1)
        print('=== ADD CART ===')
        #raise


class Product(Component):
    'Product'
    __name__ = 'www.product'
    _path = '/product'

    product = fields.Char('Product')

    @classmethod
    def get_url_map(cls):
        return [
            Rule('/product/<int:product>'),
        ]

    def render(self):
        pool = Pool()
        Product = pool.get('product.product')
        # Components
        Index = pool.get('www.extranet.index')

        products = Product.search([
            ('id', '=', self.product)
        ])

        if not products:
            raise
        product = products[0]

        product_div = div()
        with product_div:
            a(href=Index(render=False).url()).add(p('Home'))
            with div():
                h1(product.name)
                span('10 €')
            with div():
                p(product.description)
        return product_div

#############
# portal.py #
#############
class Login(Component):
    'Login'
    __name__ = 'www.portal.login'
    _path = '/login'

    email = fields.Char('E-mail')
    password = fields.Char('Password')

    @classmethod
    def get_url_map(cls):
        return [

        ]

    def render(self):
        pool = Pool()
        User = pool.get('')

        with form():
            input(id='email', type='email', placeholder='E-mail')
