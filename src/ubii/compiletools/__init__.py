import importlib
from itertools import chain


def has_module(*modules):
    try:
        for name in modules:
            importlib.import_module(name)
    except ImportError:
        return False
    return True


def find_proto_files(*paths, recursive=True):
    return list(dict.fromkeys(chain(*[p.glob(f"{'**/' if recursive else ''}*.proto") for p in paths])))
