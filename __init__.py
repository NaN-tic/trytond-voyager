# This file is part www module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.pool import Pool
from . import www

def register():
    Pool.register(
        www.Site,
        www.Session,
        #www.Index,
        www.ExtranetIndex,
        www.ExtranetLogin,
        module='www', type_='model')
