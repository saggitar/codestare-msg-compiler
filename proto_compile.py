#!/usr/bin/env python

"""
https://github.com/protocolbuffers/protobuf/issues/1491
Googles own python plugin implementation for protoc does not compile files with relative imports, like
e.g. https://github.com/danielgtaylor/python-betterproto which also generates prettier python code.
The problem is, that the implementation from betterproto only works when all sources are compiled
simultaneously (all proto files as arguments to `protoc` invocation, otherwise files might be
overwritten.
This would break the support for build tools like cmake / make and so on, so it's not possible to implement it
this way in the official plugin.

"""
import importlib
import operator
import re

import sys
import os
import subprocess
import distutils.log
from enum import Flag, auto
from functools import reduce
from warnings import warn
from pathlib import Path
from distutils.command.build_py import build_py
from distutils.cmd import Command
from distutils.spawn import find_executable
from itertools import chain
from typing import List, Union, Optional

CompileOptionStr = Union['Compiler.CompileOption', str]
PathList = Optional[List[Path]]

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
    PYTHON = auto()
    JAVASCRIPT = JSINDIVIDUAL | JSLIBRARY
    PYTHON_COMBINED = PYTHON_MYPY | PYTHON_BETTER_PROTO | PYTHON
    ALL = PYTHON | JAVA | JSINDIVIDUAL | JSLIBRARY | CSHARP | CPP | PYTHON_MYPY | PYTHON_BETTER_PROTO

    @property
    def protoc_plugin_name(self):
        if self == self.JAVA: return 'java'
        if self == self.JSLIBRARY: return 'js'
        if self == self.JSINDIVIDUAL: return 'js'
        if self == self.CSHARP: return 'csharp'
        if self == self.CPP: return 'cpp'
        if self == self.PYTHON_BETTER_PROTO: return 'python_betterproto'
        if self == self.PYTHON_MYPY: return 'mypy'
        if self == self.PYTHON: return 'python'
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
        if self & self.PYTHON: arguments += ['py']
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
        if self == self.JSLIBRARY: return 'javascript as library'
        if self == self.JSINDIVIDUAL: return 'javascript individual'
        # other options can just use the name
        return self.name.lower() if self.name else repr(self)


class Compiler:
    """
    Wrapper around protobuf compiler.

    See compile-proto OPTIONS for all possible compilation options.
    See compile-proto (no args) and compile-proto --help for more help
    """

    OPTIONS = [o.formatted_argument for o in CompileOption if o.formatted_argument]

    def __init__(self, protoc=find_executable('protoc')):
        self.protoc = protoc or self._find_protoc()

    def _find_protoc(self):
        """
        Searches for a protoc executable respecting the PROTOC
        environment variable

        :return: path to protoc executable or None
        """
        protoc = os.environ.get('PROTOC', find_executable('protoc'))
        if not protoc:
            warn(f"protoc is not found in $PATH."
                 " Please install it or set the PROTOC environment variable")
        return protoc

    def call(self, *proto_files, dry_run=False, includes: str=None, protohelp=False, **options):
        """
        Just a wrapper around the `protoc` compiler.

        See compile-proto call --help to print help of protoc command
        See compile-proto call -- --help for additonal help with the call command
        See compile-proto protoc for the path of the used protoc compiler executable

        :param includes: Directories to use as includes
        :param protohelp: Use this flag to pass --help to protoc invocation
        :param options: Will be passed as flags to the protoc command (only `--flag` syntax supported, no single dash)
        :param dry_run: If True, don't do anything except printing the command
        """
        if 'help' in options:
            print("To pass `--help` to protoc, use flag `--protohelp`. "
                  "Make sure you use only options with --{option} syntax when calling the protoc compiler "
                  "from `compile-proto call`. i.e. options with single dashes are not supported."
                  " If you want to get more help about the `call` command, use `compile-proto -- --help`")
            return

        if protohelp:
            options['help'] = protohelp

        protoc_command: List[str] = [os.fspath(self.protoc)]  # protoc executable
        protoc_command += [f"-I{os.fspath(include)}" for include in includes or ()]  # includes
        protoc_command += [f'--{k}={v}' for k, v in options.items()]  # protoc arguments
        protoc_command += [os.fspath(f) for f in proto_files]  # .proto files
        result = 0

        distutils.log.debug(" ".join(str(c) for c in protoc_command))
        if not dry_run:
            result = subprocess.call(protoc_command)

        if result != 0:
            sys.exit(result)

    def compile(self, *protoc_files, options=None, output=os.getcwd(), **kwargs):
        """
        Compile for given options, see compile-proto compile --help

        :param output: output directory (default: working directory)
        :param options: one or multiple options see `compile-proto OPTIONS` default: [py]
        :param protoc_files: files to compile, passed through to protoc
        :param kwargs: Passed to protoc invocation, see compile-proto call -- --help.
        """
        if not options:
            warn("No options specified, no compilation will take place.")
            return

        for option in CompileOption.from_string_list(options).disjunct:
            protoc_args = {f'{option.protoc_plugin_name}_out': option.output_dir.format(root=output)}
            double_args = {k: (protoc_args[k], kwargs[k]) for k in protoc_args if k in kwargs}
            if any(double_args):
                warn(f"Argument[s] {double_args} passed multiple times: {['{}: {} | {}'.format(k, *v) for k, v in double_args.items()]}")

            distutils.log.info(f"Building with {protoc_args}")
            self.call(*protoc_files, **kwargs, **protoc_args)


class Rewriter:
    IMPORT = re.compile(r'^import .+', flags=re.MULTILINE)

    def __init__(self):
        self.proto_imports = None

    def analyze(self, *sources):
        contents = {s: Path(s).read_text(encoding='utf-8') for s in sources}
        self.proto_imports = {s: self.IMPORT.match(content) for s, content in contents.items()}
        self.proto_imports = {s: match.string for s, match in self.proto_imports.items() if match}
        print(self.proto_imports)


def check_fire():
    try:
        import fire
    except ImportError as e:
        distutils.log.error("Can't use CLI for compiler if python-fire is not installed!"
                            "Did you install the package with [cli]?")
    else:
        return fire

def cli():
    fire = check_fire()
    if fire:
        fire.Fire(Compiler)

def rewrite():
    fire = check_fire()
    if fire:
        fire.Fire(Rewriter)

class UbiiCompileProto(Command):

    description = "Compile proto files"
    user_options = [
        ('protoc=', None, 'protoc compiler location'),
        ('output=', None, 'Output directory for compiled files'),
        ('proto_package=', None, '(experimental) try to rewrite imports to generate a different package structure'),
        ('includes=', None, 'Include directories for .proto files'),
        ('protofiles=', None, 'Protobuf source files to compile'),
        ('options=', 'o', f"Options for compilation, possible values are "
                          f"{CompileOption.ALL.disjunct}"
                          f" (default)")
    ]

    def run(self):
        compiler = Compiler(protoc=self.protoc)
        args = {k: v for k, v in vars(self).items() if k in ['options', 'output', 'includes', 'sources']}
        compiler.compile(*self.protofiles, **args)

    def finalize_options(self) -> None:
        self.set_undefined_options('build_py',
                                   ('include_proto', 'includes'))

        self.set_undefined_options('build_py',
                                   ('build_lib', 'output'))

        self.set_undefined_options('build_py',
                                   ('proto_package', 'proto_package'))

        self.ensure_string('proto_package')
        self.ensure_dirname('output')
        self.ensure_dir_list('includes')
        self.ensure_string_list('options')
        self.ensure_filename('protoc')

        if self.protofiles is not None:
            self.ensure_path_list('protofiles')
        else:
            self.protofiles = list(dict.fromkeys(chain(*[p.glob('**/*.proto') for p in self.includes])))

    def initialize_options(self) -> None:
        self.protoc = None
        self.output = None
        self.proto_package = None
        self.includes: PathList = None
        self.protofiles: PathList = None
        self.options = None

    def ensure_path_list(self, name):
        self.ensure_string_list(name)
        option = [Path(s) for s in getattr(self, name)]
        not_exist = [p for p in option if not p.exists()]
        assert not any(not_exist), f"Paths {', '.join(str(o.absolute()) for o in not_exist)} don't exist."
        setattr(self, name, option)

    def ensure_dir_list(self, name):
        self.ensure_path_list(name)
        option = getattr(self, name)
        not_dir = [p for p in option if not p.is_dir()]
        assert not any(not_dir), f"Paths {', '.join(str(o.absolute()) for o in not_dir)} are not directories."
        setattr(self, name, option)


class UbiiCompilePython(UbiiCompileProto):
    user_options = UbiiCompileProto.user_options[:-1]

    def initialize_options(self) -> None:
        super().initialize_options()
        self.options = 'py'


class UbiiCompileMypy(UbiiCompileProto):
    user_options = UbiiCompileProto.user_options[:-1]

    def initialize_options(self) -> None:
        super().initialize_options()
        self.options = 'mypy'

class UbiiCompileBetterproto(UbiiCompileProto):
    user_options = UbiiCompileProto.user_options[:-1]

    def initialize_options(self) -> None:
        super().initialize_options()
        self.options = 'better'


class UbiiBuildPy(build_py):
    user_options = build_py.user_options + [
        ('include-proto=', None, 'Root dir for proto files'),
        ('proto-package=', None, '(experimental) try to rewrite imports to fake different package structure')
    ]

    def initialize_options(self) -> None:
        super().initialize_options()
        self.include_proto = None
        self.proto_package = None

    def finalize_options(self) -> None:
        super().finalize_options()
        if self.include_proto is None:
            package_dirs = [Path(self.get_package_dir(p)) for p in self.packages or ()]
            proto_dirs: PathList = [p for p in package_dirs if any(p.glob('**/*.proto'))]
            parent_paths = [p for p in proto_dirs if all(p in other.parents for other in proto_dirs if other != p)]
            if parent_paths:
                self.include_proto = [os.fspath(p) for p in parent_paths]

        self.ensure_string('proto_package')
        self.announce(f"Including *.proto files from path[s] {self.include_proto}", distutils.log.INFO)

    def run(self):
        super().run()
        for command in self.get_sub_commands():
            self.run_command(command)


    @staticmethod
    def has_module(*modules):
        try:
            for name in modules:
                importlib.import_module(name)
        except ImportError:
            return False
        return True

    def has_mypy(self):
        return self.has_module('mypy', 'mypy_protobuf')


    def has_betterproto(self):
        return self.has_module('betterproto')


    sub_commands = [('compile_python', None),
                    ('compile_mypy', has_mypy),
                    ('compile_betterproto', has_betterproto)]


