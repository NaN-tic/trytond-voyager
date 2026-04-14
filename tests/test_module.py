# This file is part voyager module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from trytond.modules.voyager.voyager import VoyagerURI
from trytond.tests.test_tryton import ModuleTestCase, activate_module


class VoyagerTestCase(ModuleTestCase):
    'Test Voyager module'
    module = 'voyager'

    @classmethod
    def setUpClass(cls):
        super(VoyagerTestCase, cls).setUpClass()
        activate_module('sale')
        activate_module('web_shop')

    def test_sitemap_groups_related_uris(self):
        site = SimpleNamespace(url='https://example.com')
        write_date = datetime(2026, 4, 14, 8, 30, tzinfo=timezone.utc)
        rows = [
            {
                'id': 2,
                'uri': '/ca/about',
                'main_uri': 1,
                'write_date': None,
                'resource': None,
                'language_code': 'ca',
            },
            {
                'id': 3,
                'uri': '/es/about',
                'main_uri': 1,
                'write_date': None,
                'resource': None,
                'language_code': 'es',
            },
            {
                'id': 1,
                'uri': '/about',
                'main_uri': None,
                'write_date': write_date,
                'resource': None,
                'language_code': 'en',
            },
        ]
        with patch.object(VoyagerURI, '_sitemap_rows', return_value=rows):
            entries = VoyagerURI.sitemap(site)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['loc'], 'https://example.com/about')
        self.assertEqual(entries[0]['lastmod'], '2026-04-14T08:30:00+00:00')
        self.assertEqual(entries[0]['changefreq'], 'monthly')
        self.assertEqual(entries[0]['priority'], '0.5')
        self.assertEqual(entries[0]['alternates'], [
                {'hreflang': 'en', 'href': 'https://example.com/about'},
                {'hreflang': 'ca', 'href': 'https://example.com/ca/about'},
                {'hreflang': 'es', 'href': 'https://example.com/es/about'},
                ])

    def test_sitemap_xml_escapes_values(self):
        site = SimpleNamespace(url='https://example.com')
        with patch.object(VoyagerURI, 'sitemap', return_value=[{
                    'loc': 'https://example.com/search?q=foo&lang=en',
                    'lastmod': '2026-04-15T09:45:00+00:00',
                    'changefreq': 'monthly',
                    'priority': '0.5',
                    'alternates': [{
                            'hreflang': 'en',
                            'href': 'https://example.com/search?q=foo&lang=en',
                            }],
                    }]):
            xml = VoyagerURI.sitemap_xml(site)

        self.assertIn(
            '<loc>https://example.com/search?q=foo&amp;lang=en</loc>', xml)
        self.assertIn(
            'href="https://example.com/search?q=foo&amp;lang=en"/>', xml)
        self.assertIn('<xhtml:link rel="alternate" hreflang="en"', xml)

del ModuleTestCase
