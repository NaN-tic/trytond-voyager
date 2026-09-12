import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from proteus import Model

from trytond.modules.voyager.tests.tools import (
    activate_modules as activate_web_modules)
from trytond.tests.test_tryton import DB_NAME, drop_db
from trytond.tests.tools import activate_modules


class TestWebDatabaseIsolation(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        for original_uri in (None, DB_NAME):
            with self.subTest(uri=original_uri), patch.dict(os.environ):
                if original_uri is None:
                    os.environ.pop('TRYTOND_DATABASE_URI', None)
                else:
                    os.environ['TRYTOND_DATABASE_URI'] = original_uri
                database = f'test_web_{uuid4().hex}'
                self.addCleanup(drop_db, database)
                web_config = activate_web_modules('company', database)
                self.assertEqual(web_config.database_name, database)
                self.assertTrue(Model.get('res.user', config=web_config).find(
                    [('login', '=', 'admin')]))
                drop_db(database)

                # The next scenario must use its own database after the web
                # test has removed its temporary database.
                scenario_config = activate_modules('company')
                self.assertEqual(scenario_config.database_name, DB_NAME)
                self.assertTrue(Model.get('res.user').find(
                    [('login', '=', 'admin')]))
                self.assertEqual(
                    os.environ.get('TRYTOND_DATABASE_URI'), original_uri)
                drop_db()
