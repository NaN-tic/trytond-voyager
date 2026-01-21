from trytond.model import ModelSQL, ModelView, fields
from trytond.pyson import Eval


class Menu(ModelSQL, ModelView):
    'WWW Menu'
    __name__ = 'www.menu'

    name = fields.Char('Name', required=True, translate=True)
    site = fields.Many2One('www.site', 'Site', required=True)
    type = fields.Selection([
        (None, ''),
        ('internal', 'Internal'),
        ('external', 'External'),
    ], 'Type')
    uri = fields.Many2One(
        'www.uri', 'URI',
        domain=[('main_uri', '=', None)],
        states={
            'invisible': Eval('type') != 'internal',
        },
        depends=['type'],
    )
    url = fields.Char(
        'URL',
        states={
            'invisible': Eval('type') != 'external',
        },
        depends=['type'],
    )
    sequence = fields.Integer('Sequence')
    parent = fields.Many2One('www.menu', 'Parent')
    menus = fields.One2Many('www.menu', 'parent', 'Menus')

    def get_rec_name(self, name):
        return self.name or ''
