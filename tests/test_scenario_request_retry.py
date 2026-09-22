import os
import unittest
from unittest.mock import patch

from proteus import Model
from trytond import backend
from trytond.pool import Pool
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules
from trytond.transaction import Transaction
from werkzeug import Response
from werkzeug.test import Client


class TestRequestRetry(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        with patch('trytond.config.get', return_value=''), patch.dict(
                os.environ, {'TRYTOND_DATABASE_NAMES': ''}):
            from trytond.modules.voyager.app import VoyagerWSGI

        config = activate_modules('voyager')
        test_user = Model.get('res.user')(
            name='Retry Test', login='voyager-retry-test')
        test_user.save()
        pool = Pool(config.database_name)
        User = pool.get('res.user')
        app = VoyagerWSGI()
        app.database = config.database_name
        app.user_id = config.user
        app.Site = pool.get('www.site')
        client = Client(app)
        original_commit = Transaction.commit

        for failure_stage in ['dispatch', 'commit', 'persistent', 'other']:
            with self.subTest(failure_stage=failure_stage):
                original_name = Model.get('res.user')(test_user.id).name
                attempts = []
                commit_attempts = []

                def dispatch(site_type, site_id, request, user_id):
                    transaction = Transaction()
                    attempts.append(transaction.started_at)
                    user = User(test_user.id)
                    # Failed attempts must not leave this write behind.
                    self.assertEqual(user.name, original_name)
                    self.assertEqual(request.form['name'], 'Updated')
                    User.write([user], {'name': original_name + ' Updated'})
                    if failure_stage == 'other':
                        raise ValueError('Application failure')
                    if (failure_stage == 'persistent'
                            or (failure_stage == 'dispatch'
                                and len(attempts) == 1)):
                        transaction.tasks.append(-1)
                        raise backend.DatabaseOperationalError('Conflict')
                    self.assertNotIn(-1, transaction.tasks)
                    return Response('Saved')

                def commit(transaction):
                    commit_attempts.append(transaction.started_at)
                    if failure_stage == 'commit' and len(commit_attempts) == 1:
                        raise backend.DatabaseOperationalError('Conflict')
                    return original_commit(transaction)

                with patch.object(app.Site, 'dispatch', side_effect=dispatch), \
                        patch.object(Transaction, 'commit', commit), \
                        patch('trytond.modules.voyager.app.config.getint',
                            return_value=2), \
                        patch('trytond.modules.voyager.app.time.sleep'):
                    if failure_stage == 'persistent':
                        with self.assertRaises(backend.DatabaseOperationalError):
                            client.post('/save', data={'name': 'Updated'})
                        self.assertEqual(len(attempts), 3)
                    elif failure_stage == 'other':
                        with self.assertRaises(ValueError):
                            client.post('/save', data={'name': 'Updated'})
                        self.assertEqual(len(attempts), 1)
                    else:
                        response = client.post('/save', data={'name': 'Updated'})
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(response.data, b'Saved')
                        self.assertEqual(len(attempts), 2)

                self.assertEqual(len(set(attempts)), len(attempts))
                expected_name = original_name
                if failure_stage in {'dispatch', 'commit'}:
                    expected_name += ' Updated'
                self.assertEqual(
                    Model.get('res.user')(test_user.id).name, expected_name)
