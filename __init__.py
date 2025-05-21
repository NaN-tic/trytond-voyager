# This file is part voyager module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.pool import Pool
from . import voyager
from . import i18n
from . import sale
from .tools import slugify

__all__ = ['register', 'slugify']

def register():
    Pool.register(
        voyager.Site,
        voyager.Session,
        voyager.Component,
        i18n.Translation,
        module='voyager', type_='model')
    Pool.register(
        i18n.TranslationSet,
        i18n.TranslationClean,
        i18n.TranslationUpdate,
        module='voyager', type_='wizard')
    Pool.register(
        sale.Site,
        sale.Sale,
        module='voyager', type_='model', depends=['sale', 'web_shop'])
