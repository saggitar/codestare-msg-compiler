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
import contextlib
import filecmp
import fnmatch
import re
import sys
import tempfile
from enum import Enum
from functools import wraps

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
from importlib.resources import read_text
from setuptools.command.egg_info import egg_info
from setuptools.config import ConfigHandler

from . import find_proto_files, has_module
from .options import CompileOption
from .compile import Compiler, Rewriter

PathList = Optional[List[Path]]


@contextlib.contextmanager
def compare_files():
    import distutils.file_util as fu
    orig = fu.copy_file

    @wraps(orig)
    def wrapper(src, dst, *args, verbose=1, **kwargs):
        if Path(dst).exists() and filecmp.cmp(src, dst):
            if verbose >= 1:
                distutils.log.debug("not copying %s (output up-to-date)", src)
            return dst, 0

        return orig(src, dst, *args, verbose=verbose, **kwargs)

    fu.copy_file = wrapper
    yield
    fu.copy_file = orig


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
        ('force', 'f', "forcibly build everything (ignore file timestamps)"),
        ('files=', None, 'Protobuf source files to compile'),
        ('plugin_params=', None, 'parameters passed to protoc plugin'),
        ('options=', 'o', f"Options for compilation, possible values are "
                          f"{CompileOption.ALL.disjunct}"
                          f" (default)")
    ]

    @contextlib.contextmanager
    def redirect_build_dir(self):
        original = self.output
        tf = None
        if not self.force:
            executable = Path(sys.executable)
            suffix = '_'.join(p.replace('.', '_') for p in executable.parts if not p == executable.anchor)
            tf = tempfile.TemporaryDirectory(suffix=suffix,
                                             prefix=__name__.replace('.', '_'))
            self.output = tf.name

        yield original, self.output
        if tf is not None:
            tf.cleanup()

        self.output = original

    def run(self):
        compiler = Compiler(protoc=self.protoc)

        with self.redirect_build_dir() as (old, temp):
            args = {k: v for k, v in vars(self).items() if k in ['options', 'output', 'includes', 'plugin_params']}
            args['quiet'] = not self.distribution.verbose
            compiler.compile(*self.files, **args)

            with compare_files():
                self.copy_tree(temp, old)

        for command in self.get_sub_commands():
            self.run_command(command)

    def finalize_options(self) -> None:
        self.set_undefined_options('rewrite_proto',
                                   ('outputs', 'includes'))

        self.set_undefined_options('compile_proto',
                                   ('build_lib', 'output'),
                                   ('include_proto', 'includes'),
                                   ('proto_package', 'proto_package'),
                                   ('force', 'force'),
                                   ('dry_run', 'dry_run')
                                   )

        self.ensure_dir_list('includes')
        self.ensure_dirname('output')
        self.ensure_string_list('options')
        self.ensure_filename('protoc')
        self.ensure_string('plugin_params')

        if self.files is not None:
            self.ensure_path_list('files')
        elif self.proto_package:
            self.files = find_proto_files(*[include / '/'.join(self.proto_package.split('.'))
                                            for include in self.includes])
        else:
            self.files = find_proto_files(*self.includes)

    def initialize_options(self) -> None:
        self.protoc = None
        self.output = None
        self.includes: PathList = None
        self.files: PathList = None
        self.dry_run = None
        self.options = None
        self.force = None
        self.proto_package = None
        self.plugin_params = None


class CompileProtoPython(CompileBase):
    description = "compile python protobuf modules (google plugin)"
    user_options = CompileBase.user_options[:-1]

    def initialize_options(self) -> None:
        super().initialize_options()
        self.options = 'py'

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

    class Flavor(Enum):
        MYPY = 'mypy'
        BASIC = 'python'
        BETTER = 'better'
        PLUS = 'plus'

    flavors = {s.value: s for s in Flavor}

    user_options = [
        ('include-proto', None, 'root dir for proto files'),
        ('proto-package', None, 'parent package that will be enforced for protobuf modules'),
        ('build-lib', None, 'output directory for protobuf library'),
        ('flavor', None, f'flavor of compiled code, one of {",".join(flavors)}'),
        ('force', 'f', "forcibly build everything (ignore file timestamps)"),
        ('dry-run', None, 'don\'t do anything but show protoc commands')
    ]

    def initialize_options(self) -> None:
        self.include_proto = None
        self.proto_package = None
        self.build_lib = None
        self.flavor = None
        self.force = None
        self.dry_run = None

    def finalize_options(self) -> None:
        self.set_undefined_options('build_py_proto',
                                   ('build_lib', 'build_lib'),
                                   ('dry_run', 'dry_run'),
                                   ('force', 'force'),
                                   ('include_proto', 'include_proto'))

        self.ensure_path_list('include_proto')
        self.ensure_string('proto_package')
        self.ensure_string('flavor')
        if self.flavor is not None:
            if self.flavor not in self.flavors:
                raise DistutilsOptionError(f"Only possible options for flavor are {','.join(self.flavors)}")
            self.flavor = self.flavors[self.flavor]

    def run(self):
        if self.include_proto is not None:
            self.announce(f"Including *.proto files from path[s] {self.include_proto}", distutils.log.INFO)
        else:
            self.announce(f"No *.proto files specified, not compiling.", distutils.log.INFO)

        for command in self.get_sub_commands():
            self.run_command(command)

        proto_package_path = self.proto_package.split('.') if self.proto_package else ()
        compiled_packages = ['.'.join([self.proto_package, p])
                             for p in setuptools.find_packages(op.join(self.build_lib, *proto_package_path))]

        if compiled_packages:
            self.announce(f"built protobuf packages: {compiled_packages}", distutils.log.INFO)

        missing = [p for p in compiled_packages or () if p not in self.distribution.packages]
        if missing:
            distutils.log.warn(f"protobuf packages {', '.join(missing)} are missing "
                               f"from setup.cfg / setup.py, but have been compiled.")
            self.distribution.packages += missing

    def mypy_rule(self):
        return (has_module('mypy', 'mypy_protobuf')
                and self.flavor == self.Flavor.MYPY
                and self.include_proto)

    def better_proto_rule(self):
        return (has_module('betterproto')
                and self.flavor == self.Flavor.BETTER
                and self.include_proto)

    def proto_plus_rule(self):
        return (has_module('codestare.proto')
                and self.flavor == self.Flavor.PLUS
                and self.include_proto)

    def basic_python_rule(self):
        return (self.flavor == self.Flavor.BASIC
                and self.include_proto)

    def rewrite_rule(self):
        return (self.proto_package is not None
                and self.include_proto)

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

        if self.inputs is None:
            raise DistutilsOptionError(f"Can't rewrite proto files without inputs")

        if self.outputs is None:
            raise DistutilsOptionError(f"Can't rewrite proto files without outputs")

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
    class _Styles(Enum):
        FANCY = 'fancy'
        WILDCARD = 'wildcard'
        EMPTY = 'empty'

    styles = {s.value: s for s in _Styles}
    description = "generate (better) __init__.py files for protobuf modules"

    user_options = [
        ('packages', None, 'generate for these packages only'),
        ('recursive', None, 'if set, you only need to specify parent packages, all subpackages will also be considered'),
        ('no-recursive', None, 'only the exact packages specified in `packages` are considered. [default]'),
        ('import_style', None, f'One of: {", ".join(styles)}. See documentation for details about generated inits'),
    ]

    boolean_options = ['recursive']
    negative_opt = {'no-recursive': 'recursive'}

    def initialize_options(self) -> None:
        self.recursive = 0
        self.import_style = None
        self.package_root = None
        self.packages = None
        self.force = None

    def finalize_options(self) -> None:
        self.set_undefined_options('compile_python',
                                   ('force', 'force'),
                                   ('output', 'package_root'))

        self.ensure_string_list('packages')
        self.ensure_dirname('package_root')
        self.ensure_string('import_style')

        if self.package_root is None:
            raise DistutilsOptionError(f"Can't generate inits without "
                                       f"package root (no output from `compile_python`?)")

        if self.import_style is not None:
            if self.import_style not in self.styles:
                raise DistutilsOptionError(f"Only supported values for import_style are: {', '.join(self.styles)}")
            else:
                self.import_style = self.styles[self.import_style]

    def run(self) -> None:
        """
        Generate recursive init files with wildcard imports for a package.
        """
        def is_package(path: Path):
            return path.is_dir() and list(path.glob('**/__init__.py'))

        if self.packages is None:
            root = Path(self.package_root)
            available = (f"'{p.name}'" for p in filter(is_package, filter(Path.is_dir, root.glob('*'))))
            self.announce(f"no packages specified -> skipping. "
                          f"(possible packages found in {self.package_root}: "
                          f"{', '.join(available) or 'No packages found'})", distutils.log.INFO)

            return

        search_dirs = (
            Path(self.package_root) / op.join(*package.split('.'))
            for package in self.packages or ()
        )

        searches = (
            p.glob(f"{'**' if self.recursive else '*'}/")
            for p in search_dirs
        )

        skipped = []

        for package in chain(*searches):
            init: Path = package / '__init__.py'
            name = '.'.join(package.relative_to(self.package_root).parts)
            if init.exists() and not self.force:
                skipped += [name]
                distutils.log.debug(f"Not generating {init}, already existing. Use --force")
                continue

            with init.open('w', encoding='utf-8') as f:
                if self.import_style == self._Styles.FANCY:
                    f.write(read_text(__package__, 'init_template'))
                if self.import_style == self._Styles.WILDCARD:
                    modules = [p for p in init.parent.glob('*.py') if not p.name.startswith('_')]
                    f.write('\n'.join(f"from .{m.stem} import *" for m in modules))
                if self.import_style == self._Styles.EMPTY:
                    pass

        created = [p for p in self.packages or () if p not in skipped]
        if created:
            self.announce(f"Generated __init__.py files for "
                          f"python packages {created}"
                          f"{' recursively' if self.recursive else ''}", distutils.log.INFO)
        elif self.packages:
            self.announce(f"__init__.py files in {self.packages} already present, not generated", distutils.log.INFO)
        else:
            self.announce(f"No init files generated for {self.package_root}", distutils.log.INFO)


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

        if self.include_proto == "included":
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
        ('compile_proto', None),
    ]


def write_package(cmd: egg_info, basename, filename, force=False):
    compile_command = cmd.get_finalized_command('compile_proto')
    proto_plus_cmd = (cmd.get_finalized_command('compile_protoplus')
                      if 'compile_protoplus' in compile_command.get_sub_commands()
                      else None)

    value = getattr(compile_command, 'proto_package', None)
    params = getattr(proto_plus_cmd, 'plugin_params', None)
    if params is not None:
        value = params.replace('package', value)

    if value:
        cmd.write_or_delete_file('proto package name', filename, value, force)
