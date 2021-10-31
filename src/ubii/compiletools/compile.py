import distutils.log
import os
import pathlib
import re
import subprocess
from itertools import chain, dropwhile, islice, takewhile

import sys
from functools import partial
from warnings import warn
from distutils.spawn import find_executable
from pathlib import Path
from typing import List, Optional, Dict, Callable

from . import find_proto_files
from .options import CompileOption

package_regex = r'(\w+)((?:\.\w+)*)'
check_packages = partial(re.match, package_regex)


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

        for option in CompileOption.from_string_list(options).disjunct:
            protoc_args = {f'{option.protoc_plugin_name}_out': option.output_dir.format(root=output)}
            distutils.log.info(f"Compiling with {protoc_args}")
            self.call(*protoc_files, **kwargs, **protoc_args)


class Rewriter:
    """
    Rewrite proto files to force python package structure
    which mirrors protobuf package declarations.
    """

    _IMPORT = re.compile(r'^import "((?:\w+/)*)(\w+\.proto)";$', flags=re.MULTILINE)
    _PACKAGE = re.compile(r'^package {pkg};$'.format(pkg=package_regex), flags=re.MULTILINE)

    def __init__(self,
                 root_package: str = None,
                 output_root: os.PathLike = './'):

        self._contents: Optional[Dict[Path, str]] = None
        self._roots: Optional[Dict[Path, Path]] = None
        self.root_package = root_package
        self.output_root = output_root

    def read(self, *sources: os.PathLike):
        """
        Reads .proto files from a directory, manipulate them with the other commands afterwards.
        """
        sources = [Path(s) for s in sources]
        found = {s: find_proto_files(s) for s in sources if s.is_dir()}
        no_proto_dirs = [s for s in sources if not s in found or not found[s]]
        assert not no_proto_dirs, f"Check path[s] {no_proto_dirs}: Not a directory or does not contain a .proto file."

        # invert dictionary to lookup parents
        self._roots = {path: root for root, paths in found.items() for path in paths}
        self._contents = {path: path.read_text(encoding='utf-8') for path in self._roots}
        return self

    @property
    def root_package(self):
        return self._root_package

    @root_package.setter
    def root_package(self, value):
        if value is None:
            return

        valid = check_packages(value)
        assert valid, f"{value} not a valid package name, please use only .-separated package names"

        self._root_package = value

    @property
    def output_root(self):
        return self._out_root

    @output_root.setter
    def output_root(self, value):
        self._out_root = Path(value)

    def _get_package(self, path):
        relative_path = path.relative_to(self._roots[path])
        package = self._PACKAGE.search(self._contents[path])
        return self._fix_package(package) if package else '.'.join(relative_path.parts)

    def _fix_package(self, match):
        # replace first part of package with self._package
        # applying fix_package multiple times is ok since it doesn't change the package
        root_pkg, sub_pkgs = match.groups()
        sub_pkgs = sub_pkgs[1:].split('.')  # skip first char, since it's a dot anyways
        pkg_iterator = dropwhile(lambda p: p in self._root_package, chain([root_pkg], sub_pkgs))
        return '.'.join(chain([self._root_package], pkg_iterator))

    def _fix_package_declaration(self,  match):
        return f"package {self._fix_package(match)};"

    @property
    def calculated_packages(self):
        return {p: self._get_package(p) for p in self._contents}

    def _fix_import(self, root: Path, match):
        path, file = match.groups()
        import_package = self.calculated_packages.get(root / path / file)
        return '/'.join(chain(import_package.split('.'), [file])) if import_package else None

    def _fix_import_declaration(self, root, match):
        return f'import "{self._fix_import(root, match)}";'

    def fix_imports(self):
        process_imports = {p: {statement: self._fix_import(self._roots[p], statement)}
                           for p, content in self._contents.items()
                           for statement in self._IMPORT.finditer(content)}

        failed = {p: imports for p, imports in process_imports.items() if any(v is None for v in imports.values())}

        if any(failed):
            warn('\n'.join("Can't resolve imports {imports} from file {path}".format(
                path=path, imports=[k.group(0) for k, v in imports.items() if v is None]
            ) for path, imports in failed.items()) +
                 " Make sure the respective files are also included for rewriting")
            return self

        self._contents = {f: self._IMPORT.sub(partial(self._fix_import_declaration, self._roots[f]), content)
                          for f, content in self._contents.items()}
        return self

    def fix_packages(self):
        package_declarations = chain.from_iterable(self._PACKAGE.finditer(content) for content in self._contents.values())
        for declared_package in package_declarations:
            root_package = declared_package[1]
            sub_packages = declared_package[2].replace('.', r'\.') if declared_package[2] else ""
            package_regex = re.compile("({})({})".format(root_package, sub_packages))
            self._contents = {f: package_regex.sub(self._fix_package, content) for f, content in self._contents.items()}

        return self

    def write(self, dry_run=True):
        if dry_run:
            return


        for file, content in self._contents.items():
            out_dir = self.output_root / '/'.join(self._get_package(file).split('.'))
            out_dir.mkdir(parents=True, exist_ok=True)

            with open(out_dir / file.name, 'w') as output:
                output.write(content)


def check_fire():
    try:
        import fire
    except ImportError:
        distutils.log.error("Can't use CLI for compiler if python-fire is not installed!"
                            "Did you install the package with [cli]?")
    else:
        return fire


def compile_proto():
    fire = check_fire()
    if fire:
        fire.Fire(Compiler)


def rewrite_proto():
    fire = check_fire()
    if fire:
        fire.Fire(Rewriter)