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
import re
import setuptools
import os
import distutils.log
import os.path as op
from distutils.errors import DistutilsOptionError
from abc import ABC
from pathlib import Path
from setuptools.command.build_py import build_py
from distutils.cmd import Command
from itertools import chain
from typing import List, Optional

from . import find_proto_files, has_module
from .options import CompileOption
from .compile import Compiler, Rewriter

PathList = Optional[List[Path]]


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
        args = {k: v for k, v in vars(self).items() if k in ['options', 'output', 'includes']}
        compiler.compile(*self.files, **args)

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

    sub_commands = [
        ('generate_inits', None)
    ]

class CompileProtoPlus(CompileBase):
    description = "compile alternative python protobuf modules (protoplus plugin)"
    user_options = CompileBase.user_options[:-1]

    def initialize_options(self) -> None:
        super().initialize_options()
        self.options = 'plus'

    sub_commands = [
        ('generate_inits', None)
    ]


class CompileProto(PathCommand):
    description = "compile protobuf files with [all] available python plugins"

    user_options = [
        ('include-proto', None, 'root dir for proto files'),
        ('proto-package', None, 'parent package that will be enforced for protobuf modules'),
        ('build-lib', None, 'output directory for protobuf library'),
        ('exclude', None, 'exclude compile options [python, mypy, better, plus], e.g. used to skip basic compilation'),
        ('dry-run', None, 'don\'t do anything but show protoc commands')
    ]

    def initialize_options(self) -> None:
        self.include_proto = None
        self.proto_package = None
        self.build_lib = None
        self.exclude = None
        self.dry_run = None

    def finalize_options(self) -> None:
        self.set_undefined_options('build_py',
                                   ('build_lib', 'build_lib'),
                                   ('dry_run', 'dry_run'),
                                   ('include_proto', 'include_proto'))

        self.ensure_path_list('include_proto')
        self.ensure_string('proto_package')
        self.ensure_string_list('exclude')
        if self.exclude is None:
            self.exclude = []

        if self.include_proto:
            self.announce(f"Including *.proto files from path[s] {self.include_proto}", distutils.log.INFO)

    def run(self):
        for command in self.get_sub_commands():
            self.run_command(command)

        proto_package_path = self.proto_package.split('.') if self.proto_package else ()
        compiled_packages = ['.'.join([self.proto_package, p]) for p in setuptools.find_packages(op.join(self.build_lib,
                                                                                               *proto_package_path))]
        self.announce(f"built protobuf packages: {compiled_packages}", distutils.log.INFO)
        missing = [p for p in compiled_packages or () if p not in self.distribution.packages]
        if missing:
            distutils.log.warn(f"protobuf packages {', '.join(missing)} are missing "
                               f"from setup.cfg / setup.py, but have been compiled.")
            self.distribution.packages += missing

    def mypy_rule(self):
        return has_module('mypy', 'mypy_protobuf') and 'mypy' not in self.exclude

    def better_proto_rule(self):
        return has_module('betterproto') and 'better' not in self.exclude

    def proto_plus_rule(self):
        return has_module('codestare.proto') and 'plus' not in self.exclude

    def basic_python_rule(self):
        return 'python' not in self.exclude

    def rewrite_rule(self):
        return self.proto_package is not None

    sub_commands = [
        ('rewrite_proto', rewrite_rule),
        ('compile_python', basic_python_rule),
        ('compile_betterproto', better_proto_rule),
        ('compile_mypy', mypy_rule),
        ('compile_protoplus', proto_plus_rule),
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
        rewriter.root_package = self.proto_package

        for input, output in zip(self.inputs, self.outputs):
            rewriter.read(input)
            rewriter.output_root = output
            rewriter.fix_imports()
            rewriter.fix_packages()
            rewriter.write(dry_run=self.dry_run)


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
    def __getattr__(self, item):
        if item == 'user_options':
            return build_py.user_options + CompileProto.user_options
        
        return build_py.__getattr__(self, item)

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

    def compile_rule(self):
        return bool(self.include_proto)

    sub_commands = [
        ('compile_proto', compile_rule),
    ]
