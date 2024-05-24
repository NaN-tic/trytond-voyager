from trytond.pool import Pool, PoolMeta
from trytond.model import fields

class Site(metaclass=PoolMeta):
    __name__ = 'www.site'

    web_shop = fields.Many2One('web.shop', "Web Shop")


class Sale(metaclass=PoolMeta):
    __name__ = 'sale.sale'

    session = fields.Many2One('www.session', "Session")
