# This file is part voyager module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.pool import Pool
from . import voyager

def register():
    Pool.register(
        voyager.Site,
        voyager.Session,
        voyager.Component,
        module='voyager', type_='model')
