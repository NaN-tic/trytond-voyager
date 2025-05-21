from trytond.tools import slugify as _slugify

def slugify(text):
    if not text:
        return ''
    return _slugify(text)

