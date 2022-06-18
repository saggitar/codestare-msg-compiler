import importlib
import pathlib
import typing

from itertools import chain


def has_module(*modules: str):
    """
    Try importing module, catch ImportError

    Args:
        *modules: module names

    Returns: True if module is importable else False
    """

    try:
        for name in modules:
            importlib.import_module(name)
    except ImportError:
        return False
    return True


def find_proto_files(*paths: pathlib.Path, recursive: bool = True) -> typing.List[pathlib.Path]:
    """
    Return relative paths of .proto files in paths

    Args:
        *paths: We :func:`~pathlib.Path.glob` the files in the paths
        recursive: check recursively in all paths if True

    Returns:
       List of unique paths of found .proto files, relative to search path
    """
    searcher = chain.from_iterable(
        p.glob(f"{'**/' if recursive else ''}*.proto") for p in paths
    )
    found = list(dict.fromkeys(searcher))
    return found
