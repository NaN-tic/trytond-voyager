# This file is part voyager module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.tests.test_tryton import ModuleTestCase, activate_module


class VoyagerTestCase(ModuleTestCase):
    'Test Voyager module'
    module = 'voyager'

    @classmethod
    def setUpClass(cls):
        super(VoyagerTestCase, cls).setUpClass()
        activate_module('sale')
        activate_module('web_shop')

del ModuleTestCase
