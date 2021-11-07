import operator
from enum import Flag, auto
from functools import reduce
from typing import List, Union

CompileOptionStr = Union['Compiler.CompileOption', str]


class CompileOption(Flag):
    """
    Describes available compile options
    """
    JAVA = auto()
    JSLIBRARY = auto()
    JSINDIVIDUAL = auto()
    CSHARP = auto()
    CPP = auto()
    PYTHON_BETTER_PROTO = auto()
    PYTHON_MYPY = auto()
    PYTHON_PROTOPLUS = auto()
    PYTHON_BASIC = auto()
    JAVASCRIPT = JSINDIVIDUAL | JSLIBRARY
    PYTHON = PYTHON_MYPY | PYTHON_BETTER_PROTO | PYTHON_PROTOPLUS | PYTHON_BASIC
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
        matching = reduce(operator.and_, [o for o in cls if value in o.arguments])

        if not matching:
            raise ValueError(f"{value} is no valid option.")

        return matching

    @classmethod
    def from_string_list(cls, values):
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

    @property
    def formatted_argument(self):
        return f"[{','.join(self.arguments)}] {self}" if len(self.arguments) == 1 else None

    @property
    def disjunct(self) -> List['CompileOption']:
        """
        Return all options which are not combinations of other options
        Like normal integer flags, individual flags are all powers of 2,
        see https://docs.python.org/3/library/enum.html#flag
        combined flags are not, so we test that with `o.value & (o.value - 1)`
        """
        return [o for o in type(self) if o & self and not o.value & (o.value - 1)]

    @property
    def output_dir(self):
        """
        Return format string. Format with option.output_dir.format(root=you_root_directory)
        """
        if self == self.JSLIBRARY: return f'library=protobuf_library,binary:{self.JAVASCRIPT.output_dir}'
        if self == self.JSINDIVIDUAL: return f'import_style=commonjs,binary:{self.JAVASCRIPT.output_dir}'

        return "{root}"
        # output dirs only make sense for individual options. not combined ones.

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