import importlib
from itertools import chain


def has_module(*modules):
    def inner(*args):
        try:
            for name in modules:
                importlib.import_module(name)
        except ImportError:
            return False
        return True
    return inner


def find_proto_files(*paths):
    return list(dict.fromkeys(chain(*[p.glob('**/*.proto') for p in paths])))
