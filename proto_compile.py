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
import fnmatch
import warnings

import tempfile

from distutils.errors import DistutilsOptionError
from glob import glob

import importlib
import operator
import re
import setuptools

import sys
import os
import subprocess
import distutils.log
import os.path as op
from abc import ABC
from enum import Flag, auto
from functools import reduce
from warnings import warn
from pathlib import Path
from distutils.command.build_py import build_py
from distutils.cmd import Command
from distutils.spawn import find_executable
from itertools import chain
from typing import List, Union, Optional, Dict

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


class Compiler:
    """
    Wrapper around protobuf compiler.

    See compile-proto OPTIONS for all possible compilation options.
    See compile-proto (no args) and compile-proto --help for more help
    """

    OPTIONS = [o.formatted_argument for o in CompileOption if o.formatted_argument]

    def __init__(self, protoc=find_executable('protoc')):
        self.protoc = protoc or self._find_protoc()
        self.tmp_dirs = {}

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

    def call(self, *proto_files,
             includes: str=None,
             protohelp=False,
             dry_run=False,
             **options):
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
        :param force: if True compile directly to output directory. If false, use tempdir and check for overwrites
        :param kwargs: Passed to protoc invocation, see compile-proto call -- --help.
        """
        if not options:
            warn("No options specified, no compilation will take place.")
            return

        force = kwargs.pop('force', None)

        for option in CompileOption.from_string_list(options).disjunct:
            tmp = self.tmp_dirs.setdefault(option, tempfile.TemporaryDirectory(suffix=option.name))
            out_dir = output if force else tmp.name

            plugin_out = f'{option.protoc_plugin_name}_out'
            protoc_args = {plugin_out: option.output_dir.format(root=out_dir)}

            double_args = {k: (protoc_args[k], kwargs[k]) for k in protoc_args if k in kwargs}
            if any(double_args):
                warn(f"Argument[s] {double_args} passed multiple times: {['{}: {} | {}'.format(k, *v) for k, v in double_args.items()]}")

            distutils.log.info(f"Compiling with {protoc_args}")
            self.call(*protoc_files, **kwargs, **protoc_args)
            if force:
                continue

            outputs = [generated.relative_to(out_dir) for generated in Path(out_dir).glob('**/*') if generated.is_file()]
            existing = [o for o in outputs if (output / o).exists()]
            if any(existing) and not force:
                info = f"File[s] {', '.join(p.name for p in existing)}" if len(existing) < len(outputs) else "All files"
                distutils.log.info(f"{info} already exist.")
                return

            protoc_args[plugin_out] = option.output_dir.format(root=output)
            distutils.log.info(f"No files generated by compilation exist in {output}, "
                               f"compiling again, this time using {protoc_args}")

            self.call(*protoc_files, **kwargs, **protoc_args)

    def __del__(self):
        for _, tmp in self.tmp_dirs.items():
            tmp.cleanup()


class Rewriter:
    IMPORT = re.compile(r'^(import ")(.+)(")', flags=re.MULTILINE)
    PACKAGE = re.compile(r'^([a-z]+\.?)*([a-z])$')

    def __init__(self):
        self.proto_imports = None
        self.contents: Optional[Dict[Path, str]] = None
        self.parents = None
        self._outdir = None
        self._prefix = ""

    def read(self, *sources: Path):
        found = {s: find_proto_files(s) for s in sources if s.is_dir()}
        no_proto_dirs = [s for s in sources if not s in found]
        assert not no_proto_dirs, f"Some path[s] from {no_proto_dirs} are no directories or don't contain .proto files."

        # invert dictionary to lookup parents
        self.parents = {path: parent for parent, paths in found.items() for path in paths}
        self.contents = {path: path.read_text(encoding='utf-8') for path in self.parents}
        return self

    def prefix(self, value):
        if value is None:
            return

        valid = self.PACKAGE.match(value)
        assert valid, f"{value} does not seem to be a valid package name. It can only contain lowercase letters and dots."

        self._prefix = '/'.join(value.split('.')) + '/'
        return self

    def output_dir(self, path):
        self._outdir = Path(path)
        return self

    def _replace(self, match):
        return self.IMPORT.sub(r'\1{pre}\2\3'.format(pre=self._prefix), ''.join(match.groups()))

    def replace(self, dry_run=False):
        for f in self.contents:
            self.contents[f] = self.IMPORT.sub(self._replace, self.contents[f])
            if dry_run:
                continue

            if self._outdir:
                output = self._outdir / self._prefix / f.relative_to(self.parents[f])
            else:
                output = f

            output.parent.mkdir(parents=True, exist_ok=True)

            with output.open('w', encoding='utf-8') as stream:
                stream.write(self.contents[f])


def check_fire():
    try:
        import fire
    except ImportError:
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


class PathCommand(Command, ABC):
    def ensure_path_list(self, option):
        val = getattr(self, option)
        if val is None:
            return

        if not isinstance(val, list) or not all(isinstance(o, Path) for o in val):
            self.ensure_string_list(option)
            val = [Path(s) for s in getattr(self, option)]

        not_exist = [p for p in val if not p.exists()]
        if any(not_exist):
            raise DistutilsOptionError(f"Paths {', '.join(str(o.absolute()) for o in not_exist)} don't exist.")

        setattr(self, option, val)

    def ensure_dir_list(self, option):
        self.ensure_path_list(option)
        val = getattr(self, option)
        if val is None:
            return

        not_dir = [p for p in val if not p.is_dir()]
        if any(not_dir):
            raise DistutilsOptionError(f"Paths {', '.join(str(o.absolute()) for o in not_dir)} are not directories.")


class CompileBase(PathCommand):

    description = "Compile proto files"
    user_options = [
        ('protoc=', None, 'protoc compiler location'),
        ('output=', None, 'Output directory for compiled files'),
        ('includes=', None, 'Include directories for .proto files'),
        ('files=', None, 'Protobuf source files to compile'),
        ('options=', 'o', f"Options for compilation, possible values are "
                          f"{CompileOption.ALL.disjunct}"
                          f" (default)")
    ]

    def run(self):
        compiler = Compiler(protoc=self.protoc)
        args = {k: v for k, v in vars(self).items() if k in ['options', 'output', 'includes', 'force']}
        compiler.compile(*self.files, **args)
        for option, tmpdir in compiler.tmp_dirs.items():
            self.copy_tree(tmpdir.name, self.output)


    def finalize_options(self) -> None:
        self.set_undefined_options('rewrite_proto',
                                   ('outputs', 'includes'))

        self.set_undefined_options('compile_proto',
                                   ('build_lib', 'output'),
                                   ('dry_run', 'dry_run')
                                   )

        self.ensure_dirname('output')
        self.ensure_dir_list('includes')
        self.ensure_string_list('options')
        self.ensure_filename('protoc')

        if self.files is not None:
            self.ensure_path_list('files')
        else:
            self.files = find_proto_files(*self.includes)

    def initialize_options(self) -> None:
        self.protoc = None
        self.output = None
        self.includes: PathList = None
        self.files: PathList = None
        self.dry_run = None
        self.options = None


class CompileProtoPython(CompileBase):
    description = "compile python protobuf modules (google plugin)"
    user_options = CompileBase.user_options[:-1]

    def initialize_options(self) -> None:
        super().initialize_options()
        self.options = 'py'

    def run(self):
        super().run()
        for command in self.get_sub_commands():
            self.run_command(command)

    sub_commands = [
        ('generate_inits', None)
    ]

class CompileProtoMypy(CompileBase):
    description = "compile stub files for python protobuf modules (mypy plugin)"
    user_options = CompileBase.user_options[:-1]

    def initialize_options(self) -> None:
        super().initialize_options()
        self.options = 'mypy'


class CompileBetterproto(CompileBase):
    description = "compile alternative python protobuf modules (betterproto plugin)"
    user_options = CompileBase.user_options[:-1]

    def initialize_options(self) -> None:
        super().initialize_options()
        self.options = 'better'


class CompileProto(PathCommand):
    description = "compile protobuf files with [all] available python plugins"

    user_options = [
        ('include-proto=', None, 'root dir for proto files'),
        ('proto-package=', None, 'parent package that will be enforced for protobuf modules'),
        ('build_lib', None, 'output directory for protobuf library'),
        ('dry_run', None, 'don\'t do anything but show protoc commands')
    ]

    def initialize_options(self) -> None:
        self.include_proto = None
        self.proto_package = None
        self.build_lib = None
        self.dry_run = None

    def finalize_options(self) -> None:
        self.set_undefined_options('build_py',
                                   ('build_lib', 'build_lib'),
                                   ('dry_run', 'dry_run'),
                                   ('include_proto', 'include_proto'))

        self.ensure_path_list('include_proto')
        self.ensure_string('proto_package')
        if self.include_proto:
            self.announce(f"Including *.proto files from path[s] {self.include_proto}", distutils.log.INFO)

    def run(self):
        for command in self.get_sub_commands():
            self.run_command(command)

        protobuf_packages = setuptools.find_namespace_packages(self.build_lib)
        self.announce(f"built protobuf packages: {protobuf_packages}", distutils.log.INFO)
        with Path('./.py_protobuf_packages').open('w') as stream:
            stream.write('\n'.join(protobuf_packages))

    has_mypy = has_module('mypy', 'mypy_protobuf')
    has_betterproto = has_module('betterproto')

    sub_commands = [
        ('rewrite_proto', lambda self: self.proto_package is not None),
        ('compile_python', None),
        ('compile_betterproto', has_betterproto),
        ('compile_mypy', has_mypy),
    ]


class RewriteProto(PathCommand):
    description = "rewrite protobuf inputs to fake specific package structure (experimental)"

    user_options = [
        ('proto-package=', None, 'parent package that will be enforced for protobuf modules'),
        ('inplace', None, 'write output to compile_proto include directory'),
        ('use-build', None, 'write output to build_lib directory [default]'),
    ]

    boolean_options = ['inplace']
    negative_opt = {'use-build': 'inplace'}

    def initialize_options(self) -> None:
        self.proto_package = None
        self.inplace = 0
        self.dry_run = None
        self.inputs = None
        self.outputs = None

    def finalize_options(self) -> None:
        self.set_undefined_options('compile_proto',
                                   ('dry_run', 'dry_run'),
                                   ('build_lib', 'outputs'),
                                   ('proto_package', 'proto_package'),
                                   ('include_proto', 'inputs'),
                                   )

        if self.inplace:
            self.outputs = self.inputs

        self.ensure_string('proto_package')
        self.ensure_dir_list('inputs')
        self.ensure_dir_list('outputs')

        if len(self.inputs) != len(self.outputs):
            raise DistutilsOptionError(f"can't rewrite proto files from {self.inputs}: "
                                       f"wrong number of outputs ({len(self.outputs)})")

        self.announce(f"Enforcing python package {self.proto_package} for compiled modules.", distutils.log.INFO)

    def run(self) -> None:
        rewriter = Rewriter()
        rewriter.prefix(self.proto_package)

        for input, output in zip(self.inputs, self.outputs):
            rewriter.read(input)
            rewriter.output_dir(output)
            rewriter.replace(dry_run=self.dry_run)


class GenerateInits(PathCommand):
    description = "generate (better) __init__.py files for protobuf modules"

    user_options = [
        ('packages', None, 'generate for these packages only'),
        ('recursive', None, 'if set, you only need to specify parent packages, all subpackages will also be considered'),
        ('no-recursive', None, 'only the exact packages specified in `packages` are considered. [default]'),
        ('use-wildcards', None, 'if set, init files will fildcard import everything from all submodules (experimental)'),
        ('no-use-wildcards', None, 'if set init files will be empty'),
    ]

    boolean_options = ['recursive', 'use-wildcards']
    negative_opt = {'no-recursive': 'recursive',
                    'no-use-wildcards': 'use-wildcards'}

    def initialize_options(self) -> None:
        self.recursive = 0
        self.use_wildcards = 0
        self.package_root = None
        self.packages = None

    def finalize_options(self) -> None:
        self.set_undefined_options('compile_python',
                                   ('output', 'package_root'))

        self.ensure_string_list('packages')
        self.ensure_dirname('package_root')

    def run(self) -> None:
        """
        Generate recursive init files with wildcard imports for a package.
        """

        search_dirs = [Path(self.package_root) / op.join(*package.split('.')) for package in self.packages or ()]
        searches = [p.glob(f"{'**' if self.recursive else '*'}/") for p in search_dirs]

        for package in chain(*searches):
            package = Path(package)
            modules = (p.stem for p in package.glob('*.py') if not p.stem.startswith('_'))
            packages = (p.stem for p in package.glob('*') if not p.stem.startswith('_') and p.is_dir())
            with (package / '__init__.py').open('w') as f:
                if self.use_wildcards:
                    f.write('\n'.join(f"from .{s} import *" for s in chain(modules, packages)))

        self.announce(f"Generated __init__.py files for "
                      f"python packages {self.packages}{' recursively' if self.recursive else ''}", distutils.log.INFO)


class UbiiBuildPy(build_py):
    user_options = build_py.user_options + CompileProto.user_options

    def initialize_options(self) -> None:
        super().initialize_options()
        self.include_proto = None

    def finalize_options(self) -> None:
        super().finalize_options()

        if self.include_proto is None:
            # if .proto files are included in data files
            proto_dirs = [self.get_package_dir(package) for package, _, _, filenames in self.data_files
                          if any(re.match(fnmatch.translate('*.proto'), f) for f in filenames)]
            parent_paths = op.commonprefix(proto_dirs)
            if parent_paths:
                self.include_proto = [os.fspath(p) for p in parent_paths]

    def run(self):
        for command in self.get_sub_commands():
            self.run_command(command)

        super().run()

    sub_commands = [
        ('compile_proto', None),
    ]
