# This file is part voyager module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.pool import Pool
from . import voyager
from . import sale
from . import utils
from .tools import slugify

__all__ = ['register', 'slugify']


def register():
    Pool.register(
        voyager.Site,
        voyager.Session,
        voyager.Component,
        voyager.VoyagerURI,
        voyager.User,
        utils.Menu,
        voyager.VoyagerUriBuilderAsk,
        voyager.VoyagerUriBuilderResult,
        module='voyager', type_='model')
    Pool.register(
        voyager.VoyagerUriBuilder,
        module='voyager', type_='wizard')
    Pool.register(
        sale.Site,
        sale.Sale,
        module='voyager', type_='model', depends=['sale', 'web_shop'])
