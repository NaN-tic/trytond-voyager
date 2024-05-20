from babel.messages import extract
from trytond.pool import Pool, PoolMeta
from trytond.transaction import Transaction
from trytond.modules import get_module_info
from trytond.tools import cursor_dict

INTERNAL_LANG = 'en'

# Key cannot be an empty string otherwise Tryton wizards will ignore it
# but at the same time we want it as small as possible (no need to spend bytes
# with useless data)
KEY = 'v'

def _(message):
    Translation = Pool().get('ir.translation')
    lang = Transaction().context.get('language', INTERNAL_LANG)
    translation = Translation.get_source(KEY, 'voyager', lang, message)
    if translation is None:
        return message
    return translation


class Translation(metaclass=PoolMeta):
    __name__ = 'ir.translation'

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls.type.selection.append(('voyager', 'Voyager'))


class TranslationSet(metaclass=PoolMeta):
    __name__ = "ir.translation.set"

    def set_voyager(self):
        pool = Pool()
        Module = pool.get('ir.module')
        Translation = pool.get('ir.translation')

        cursor = Transaction().connection.cursor()

        translation = Translation.__table__()
        for module in Module.search([('state', '=', 'activated')]):
            dependencies = [x.name for x in module.dependencies if x.name == 'voyager']
            if not 'voyager' in dependencies:
                continue
            cursor.execute(*translation.select(
                    translation.id, translation.name, translation.src,
                    where=(translation.lang == INTERNAL_LANG)
                    & (translation.type == 'voyager')
                    & (translation.module == module.name)))
            existing = {x['src']: x for x in cursor_dict(cursor)}

            # TODO: Add 'voyager' translations from other modules this module
            # depends on

            method_map = [
                ('**.py', extract.extract_python),
                ]
            # Scan the module for translations
            strings = set()
            module_dir = get_module_info(module.name)['directory']
            for item in extract.extract_from_dir(module_dir, method_map, keywords={'_': None}):
                filename, lineno, message, comments, context = item
                strings.add(message)
                if message in existing:
                    continue
                #name = f'{filename}:{lineno}'
                name = KEY
                cursor.execute(*translation.insert([
                        translation.name, translation.lang,
                        translation.type, translation.src,
                        translation.value, translation.module,
                        translation.fuzzy, translation.res_id
                        ], [[
                        name, INTERNAL_LANG,
                        'voyager', message,
                        '', module.name,
                        False, -1,
                        ]]))
            if strings:
                cursor.execute(*translation.delete(
                        where=(translation.name == KEY)
                        & (translation.type == 'voyager')
                        & (translation.module == module.name)
                        & ~translation.src.in_(list(strings))))

    def transition_set_(self):
        self.set_voyager()
        return super().transition_set_()


class TranslationClean(metaclass=PoolMeta):
    __name__ = 'ir.translation.clean'

    @staticmethod
    def _clean_voyager(translation):
        return False


class TranslationUpdate(metaclass=PoolMeta):
    __name__ = 'ir.translation.update'

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._source_types.append('voyager')
