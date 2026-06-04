from trytond.model import (DeactivableMixin, ModelSQL, ModelView, fields,
    sequence_ordered)
from trytond.pyson import Eval
from trytond.exceptions import UserError
from trytond.i18n import gettext


class Menu(sequence_ordered(), DeactivableMixin, ModelSQL, ModelView):
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
            'required': Eval('type') == 'internal',
        },
        depends=['type'],
    )
    url = fields.Char(
        'URL',
        states={
            'invisible': Eval('type') != 'external',
            'required': Eval('type') == 'external',
        },
        depends=['type'],
    )
    sequence = fields.Integer('Sequence')
    parent = fields.Many2One('www.menu', 'Parent')
    menus = fields.One2Many('www.menu', 'parent', 'Menus')

    @classmethod
    def validate(cls, menus):
        for menu in menus:
            menu.check_site()

    def check_site(self):
        if self.parent and self.site != self.parent.site:
            raise UserError(gettext('voyager.msg_menu_site_mismatch'))
        if self.menus:
            for menu in self.menus:
                if self.site != menu.site:
                    raise UserError(gettext('voyager.msg_menu_site_mismatch'))

    def get_rec_name(self, name):
        return self.name or ''

    def get_href(self):
        match self.type:
            case 'external':
                return self.url
            case 'internal':
                return self.uri.get_href()
