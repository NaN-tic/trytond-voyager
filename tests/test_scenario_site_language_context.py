import unittest
from unittest.mock import patch

from proteus import Model
from trytond.pool import Pool
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules
from trytond.transaction import Transaction
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request, Response


class TestSiteLanguageContext(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        config = activate_modules('voyager')
        pool = Pool(config.database_name)
        Site = pool.get('www.site')
        Component = pool.get('Component')
        with patch.object(Site.type, 'selection', [('test', 'Test')]):
            site = Model.get('www.site')(
                name='Website', type='test', url='https://example.com')
            site.save()

        def render(component):
            request_language = Transaction().language
            self.assertEqual(component.site._context['language'],
                request_language)
            self.assertEqual(component.site._user, config.user)
            self.assertEqual(component.site.id, site.id)
            return Response(request_language)

        with Transaction().start(
                config.database_name, 0, context={'language': 'en'}):
            with patch.object(Component, 'render', render), \
                    patch.object(Site, 'get_cache', return_value=None):
                for language in ('ca', 'en', 'ca'):
                    request = Request(EnvironBuilder(
                        path='/' + language).get_environ())
                    with patch.object(Site, 'match_request', return_value=(
                                'Component', {}, None, {}, language, None)):
                        response = Site.dispatch(
                            'test', site.id, request, user_id=config.user)
                    self.assertEqual(response.get_data(as_text=True), language)
                    self.assertEqual(Transaction().language, 'en')
                    self.assertEqual(Transaction().user, 0)
