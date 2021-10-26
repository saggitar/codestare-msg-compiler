import distutils.log
import os
import re
import subprocess
import sys
from warnings import warn
from distutils.spawn import find_executable
from pathlib import Path
from typing import List, Optional, Dict

from . import find_proto_files
from .options import CompileOption


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


def compile_proto():
    fire = check_fire()
    if fire:
        fire.Fire(Compiler)


def rewrite_proto():
    fire = check_fire()
    if fire:
        fire.Fire(Rewriter)