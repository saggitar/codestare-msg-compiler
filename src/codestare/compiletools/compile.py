"""
Protoc compiler wrapper CLI (using `fire`_)

.. _fire:
    https://python-fire.readthedocs.io/en/latest/
"""
from __future__ import annotations

import distutils.log
import distutils.spawn
import functools
import os
import pathlib
import re
import subprocess
import warnings
from typing import List, Optional, Dict

import itertools
import sys

from . import find_proto_files
from .options import CompileOption

package_regex = r'(\w+)((?:\.\w+)*)'
check_packages = functools.partial(re.match, package_regex)


class Compiler:
    """
    Wrapper around protobuf compiler.

    See ``compile-proto OPTIONS`` for all possible compilation options.
    See ``compile-proto`` (no args) and ``compile-proto --help`` for more help
    """

    OPTIONS = [o.formatted_argument for o in CompileOption if o.formatted_argument]
    """
    Supported compile options, multiple options may be specified.
    """

    def __init__(self, protoc=distutils.spawn.find_executable('protoc')):
        self.protoc = protoc or self._find_protoc()

    def _find_protoc(self) -> Optional[str]:
        """
        Searches for a protoc executable respecting the PROTOC
        environment variable

        Returns:
            path to protoc executable or None
        """
        protoc = os.environ.get('PROTOC', distutils.spawn.find_executable('protoc'))
        if not protoc:
            warnings.warn(f"protoc is not found in $PATH."
                          " Please install it or set the PROTOC environment variable")
        return protoc

    def call(self, *proto_files,
             includes: str = None,
             protohelp=False,
             dry_run=False,
             **options):
        """
        Just a wrapper around the `protoc` compiler.

        See ``compile-proto call --help`` to print help of protoc command
        See ``compile-proto call -- --help`` for additonal help with the call command
        See ``compile-proto protoc`` for the path of the used protoc compiler executable

        Args:
            includes: Directories to use as includes
            protohelp: Use this flag to pass ``--help`` to protoc invocation
            options: Will be passed as flags to the protoc command (only ``--flag`` syntax supported, no single dash)
            dry_run: If True, don't do anything except printing the command
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

    def compile(self, *protoc_files,
                options=None,
                quiet=False,
                plugin_params: str = '',
                output=os.getcwd(),
                **kwargs) -> Optional[str]:
        """
        Compile for given options, see ``compile-proto compile -- --help``

        Args:
            quiet: Don't print output from protoc plugin if possible
            output: output directory (default: working directory)
            options: one or multiple options see `compile-proto OPTIONS` default: [py]
            protoc_files: files to compile, passed through to protoc
            plugin_params: mapping of additional parameters for the protoc plugin (not the compiler itself)
            kwargs: Passed to protoc invocation, see compile-proto call -- --help.

        Returns:
            the output path
        """
        params = (plugin_params,) if plugin_params else ()

        if not options:
            warnings.warn("No options specified, no compilation will take place.")
            return

        for option in CompileOption.from_string_list(options).disjunct:
            params += ('quiet',) if quiet else ()

            protoc_args = {
                f'{option.protoc_plugin_name}_out': option.format_out(output, *params)
            }

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
                 root_package: str,
                 output_root: os.PathLike = './'):

        self._contents: Optional[Dict[pathlib.Path, str]] = None
        self._roots: Optional[Dict[pathlib.Path, pathlib.Path]] = None
        self.root_package = root_package
        self.output_root = output_root

    def read(self, *dirs: os.PathLike):
        """
        Reads .proto files from directories, manipulate them with the other commands afterwards.
        """
        dirs = [pathlib.Path(s) for s in dirs]
        found = {s: find_proto_files(s) for s in dirs if s.is_dir()}
        no_proto_dirs = [s for s in dirs if not s in found or not found[s]]
        assert not no_proto_dirs, f"Check path[s] {no_proto_dirs}: Not a directory or does not contain a .proto file."

        # invert dictionary to lookup parents
        self._roots = {path: root for root, paths in found.items() for path in paths}
        self._contents = {path: path.read_text(encoding='utf-8') for path in self._roots}
        return self

    @property
    def root_package(self):
        """
        root package for generated directory structure

        Returns:
            str: root package which is enforced
        """
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
        """
        Root directory of new directory structure.
        """
        return self._out_root

    @output_root.setter
    def output_root(self, value):
        self._out_root = pathlib.Path(value)

    def _get_package(self, path):
        relative_path = path.relative_to(self._roots[path])
        package = self._PACKAGE.search(self._contents[path])
        return self._fix_package(package) if package else '.'.join(relative_path.parts)

    def _fix_package(self, match):
        # replace first part of package with self._package
        # applying fix_package multiple times is ok since it doesn't change the package
        root_pkg, sub_pkgs = match.groups()
        sub_pkgs = sub_pkgs[1:].split('.')  # skip first char, since it's a dot anyways
        pkg_iterator = itertools.dropwhile(lambda p: p in self._root_package, itertools.chain([root_pkg], sub_pkgs))
        return '.'.join(itertools.chain([self._root_package], pkg_iterator))

    @property
    def calculated_packages(self):
        """
        Returns:
            dict: Dictionary mapping file contents to package names
        """
        return {p: self._get_package(p) for p in self._contents or ()}

    def _fix_import(self, root: pathlib.Path, match):
        path, file = match.groups()
        import_package = self.calculated_packages.get(root / path / file)
        return '/'.join(itertools.chain(import_package.split('.'), [file])) if import_package else None

    def _fix_import_declaration(self, root, match):
        return f'import "{self._fix_import(root, match)}";'

    def fix_imports(self):
        """
        Modify internal file content representation to match internal file locations, so that imports are importing
        the right files.

        Returns:
            Rewriter: Reference to self to chain commands with `fire`_

        """
        process_imports = {p: {statement: self._fix_import(self._roots[p], statement)}
                           for p, content in self._contents.items()
                           for statement in self._IMPORT.finditer(content)}

        failed = {p: imports for p, imports in process_imports.items() if any(v is None for v in imports.values())}

        if any(failed):
            warnings.warn('\n'.join("Can't resolve imports {imports} from file {path}".format(
                path=path, imports=[k.group(0) for k, v in imports.items() if v is None]
            ) for path, imports in failed.items()) +
                          " Make sure the respective files are also included for rewriting")
            return self

        self._contents = {f: self._IMPORT.sub(functools.partial(self._fix_import_declaration, self._roots[f]), content)
                          for f, content in self._contents.items()}
        return self

    def fix_packages(self):
        """
        Modify internal content representation such that ``package`` declarations in ``.proto`` source files match the
        internal directory structure

        Returns:
            Rewriter: Reference to self to chain commands with `fire`_
        """
        def make_regex(declared_package):
            root_package = declared_package[1]
            sub_packages = declared_package[2].replace('.', r'\.') if declared_package[2] else ""
            regex_str = r"(?:{}\.)?({})({})".format(self._root_package, root_package, sub_packages)
            return re.compile(regex_str)

        unique_package_regexes = set(map(
            make_regex,
            itertools.chain.from_iterable(
                self._PACKAGE.finditer(content) for content in self._contents.values()
            )
        ))

        for regex in unique_package_regexes:
            self._contents = {
                f: regex.sub(self._fix_package, content) for f, content in self._contents.items()
            }

        return self

    def content(self, filename: os.PathLike) -> str:
        """
        View the internal file representations

        Args:
            filename: Input file path

        Returns:
            str: contents of internal file representation

        """
        return self._contents.get(pathlib.Path(filename), f"File for filename {filename} not found. Available"
                                                          f" filenames: {', '.join(map(str, self._contents))}")

    def write(self, dry_run=True):
        """
        Write internal content representation to :attr:`.output_root` according to
        internal :attr:`package mapping <.calculated_packages>`

        Args:
            dry_run (bool): if True don't actually write outputs.

        Returns:
            Rewriter: Reference to self to chain commands with `fire`_
        """

        for file, content in self._contents.items():
            out_dir = self.output_root / '/'.join(self._get_package(file).split('.'))
            out_dir.mkdir(parents=True, exist_ok=True)

            with open(out_dir / file.name, 'w') as output:
                if dry_run:
                    print(f"Fake writing {file.name} in {out_dir} since dry_run is {dry_run}.")
                    continue

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
    """
    Entry point for CLI.

        `fire`_ :class:`Compiler`

    """

    fire = check_fire()
    if fire:
        fire.Fire(Compiler)


def rewrite_proto():
    """
    Entry point for CLI

        `fire`_ :class:`Rewriter`
    """
    fire = check_fire()
    if fire:
        fire.Fire(Rewriter)
