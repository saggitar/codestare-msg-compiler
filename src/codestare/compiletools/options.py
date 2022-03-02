"""
Options for compilation are represented using :class:`.CompileOption`
"""
import operator
from enum import Flag, auto
from functools import reduce
from itertools import chain
from typing import List, Union

CompileOptionStr = Union['Compiler.CompileOption', str]


class CompileOption(Flag):
    """
    Describes available compile options
    """
    # empty docstrings for enum values to include them in documentation
    #:
    JAVA = auto()
    #:
    JSLIBRARY = auto()
    #:
    JSINDIVIDUAL = auto()
    #:
    CSHARP = auto()
    #:
    CPP = auto()
    #:
    PYTHON_BETTER_PROTO = auto()
    #:
    PYTHON_MYPY = auto()
    #:
    PYTHON_PROTOPLUS = auto()
    #:
    PYTHON_BASIC = auto()
    #:
    JAVASCRIPT = JSINDIVIDUAL | JSLIBRARY
    #:
    PYTHON = PYTHON_MYPY | PYTHON_BETTER_PROTO | PYTHON_PROTOPLUS | PYTHON_BASIC
    #:
    ALL = JAVA | JAVASCRIPT | CSHARP | CPP | PYTHON

    @property
    def protoc_plugin_name(self):
        if self == self.JAVA: return 'java'
        if self == self.JSLIBRARY: return 'js'
        if self == self.JSINDIVIDUAL: return 'js'
        if self == self.CSHARP: return 'csharp'
        if self == self.CPP: return 'cpp'
        if self == self.PYTHON_BETTER_PROTO: return 'python_betterproto'
        if self == self.PYTHON_MYPY: return 'mypy'
        if self == self.PYTHON_BASIC: return 'python'
        if self == self.PYTHON_PROTOPLUS: return 'proto-plus'
        # combined options don't have plugins

    @classmethod
    def from_str(cls, value) -> 'CompileOption':
        """
        Convert a string to an enum value

        Args:
            value (str): valid values are defined by :attr:`.arguments`

        Returns:
            CompileOption: Enum flag
        """
        matching = reduce(operator.and_, [o for o in cls if value in o.arguments])

        if not matching:
            raise ValueError(f"{value} is no valid option.")

        return matching

    @classmethod
    def from_string_list(cls, values):
        """
        Convert a string list to an enum value (combined flag for all values in list)

        Args:
            values (List[str]): list of values according to :attr:`.arguments`

        Returns:
            CompileOption: combined flag

        """
        return reduce(operator.and_, [cls.from_str(v) for v in values])

    @property
    def arguments(self) -> List:
        """
        Arguments that can be used to trigger this compilation
        """
        arguments = []
        if self & self.JAVA: arguments += ['java']
        if self & self.CSHARP: arguments += ['cs']
        if self & self.CPP: arguments += ['cpp']
        if self & self.PYTHON_MYPY: arguments += ['mypy']
        if self & self.PYTHON_BETTER_PROTO: arguments += ['better']
        if self & self.PYTHON_PROTOPLUS: arguments += ['plus']
        if self & self.PYTHON_BASIC: arguments += ['py']
        # other options have no associated arguments

        # combined options with special arguments:
        if self == self.ALL:
            return ['all']
        if self == self.JAVASCRIPT:
            return ['js']

        return arguments

    def format_out(self, output, *params, **kw_params):
        return ':'.join(filter(None, (self.parameters(*params, **kw_params), output)))

    @property
    def formatted_argument(self):
        return f"[{','.join(self.arguments)}] {self}" if len(self.arguments) == 1 else None

    @property
    def disjunct(self) -> List['CompileOption']:
        """
        Return all options which are not combinations of other options
        """
        return [o for o in type(self) if o & self and not o.is_composite]

    @property
    def is_composite(self):
        """
        Like normal integer flags, individual flags are all powers of 2,
        see https://docs.python.org/3/library/enum.html#flag
        combined flags are not, so we test that with ``o.value & (o.value - 1)``
        """
        return self.value & (self.value - 1)

    def parameters(self, *args, **kwargs):
        """
        some options can use request parameters for the plugin, this is e.g.
        how the javascript plugin implements "library / binary" compilation.

        - :attr:`.JSLIBRARY` adds ``library='protobuf_library',binary``
        - :attr:`.JSINDIVIDUAL` adds ``import_style='commonjs',binary``
        - :attr:`.PYTHON_PROTOPLUS` adds ``readable_imports``
        """
        args = set(args)

        if self.is_composite:
            raise ValueError("parameters only make sense for individual options.")

        if self == self.JSLIBRARY:
            kwargs['library'] = 'protobuf_library'
            args.add('binary')

        if self == self.JSINDIVIDUAL:
            kwargs['import_style'] = 'commonjs'
            args.add('binary')

        return ','.join(chain((f'{k}={v}' for k, v in kwargs.items()), args))

    def __str__(self):
        if len(self.disjunct) > 1:
            return " | ".join(str(o) for o in self.disjunct)

        if self == self.PYTHON_BETTER_PROTO: return 'python with `better_proto` plugin'
        if self == self.PYTHON_MYPY: return 'mypy python stubs'
        if self == self.PYTHON_MYPY: return 'python with `proto-plus` plugin'
        if self == self.PYTHON_BASIC: return 'python'
        if self == self.JSLIBRARY: return 'javascript as library'
        if self == self.JSINDIVIDUAL: return 'javascript individual'
        # other options can just use the name
        return self.name.lower() if self.name else repr(self)