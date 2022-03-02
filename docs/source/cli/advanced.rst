Advanced Usage
==============
.. _fire:
    https://python-fire.readthedocs.io/en/latest/

.. _fire guide:
   https://python-fire.readthedocs.io/en/latest/guide.html

-   This section covers advanced usage of the CLI tools :func:`compile-proto <codestare.compiletools.compile.compile_proto>`
    and :func:`rewrite-proto <codestare.compiletools.compile.rewrite_proto>` you need to install the ``[cli]`` extra to use
    them.

-   The CLI tools are build using *fire*. Refer to the `fire`_ documentation, especially
    the `fire guide`_ section about chaining commands for more information.

-   The examples on this page use the same example project as the :ref:`setup` tutorial.

.. only:: builder_html

    .. note::
           The example project is available for :download:`download <../example_project.zip>`.
           You might want to test the behaviour of the build commands on some files that
           you don't care about ;)

.. command-output:: tree ./example_project

.. literalinclude:: ../example_project/src/proto/general/error.proto
   :language: proto
   :caption: example_project/src/proto/general/error.proto

As you can see, the example project ``.proto`` files use package
declaration starting with "namespace". Since they are located inside
the ``src/proto`` directory compiling them with ``protoc`` and the
default python plugin would produce a python package named "proto" or
"src.proto", since the default python plugin does not care about the
package declaration in the ``.proto`` files and instead creates packages
according to the directory structure.

rewrite-proto
-------------

Root Package
............

You need to set a root package. The package can be any string that
is a valid python package name (`related PEP <https://www.python.org/dev/peps/pep-0423/#overview>`_).
In our :ref:`setup` tutorial we wanted the package to be "namespace.proto.v1".
If you don't set a root package, you will get an error:

.. command-output:: rewrite-proto - read ./example_project/src/proto
   :extraargs: 2>&1 | sed 's/\x1b\[[0-9;]*m//g'
   :shell:

You can inspect how the rewrite command would process the packages like so:

.. command-output:: rewrite-proto --root_package "foo.bar"
    - read ./example_project/src/proto
    - calculated_packages

Here `fire`_ allows us to chain the commands. We first :meth:`~codestare.compiletools.compile.Rewriter.read`
the ``.proto`` files from the ``src/proto`` directory, and then inspect the
:attr:`~codestare.compiletools.compile.Rewriter.calculated_packages` attribute.

.. note::

    As you can see, the new root package gets prepended, the ``namespace`` package is retained.
    If your root package ends with some prefix of the protobuf package declaration **only the excessive part** is
    prepended, as you can see here:

    .. command-output:: rewrite-proto --root_package "foo.namespace"
        - read ./example_project/src/proto
        - calculated_packages

Reading Files
.............

The :meth:`~codestare.compiletools.compile.Rewriter.read` method recursively searches
passed directories for ``*.proto`` files. It will raise an error if you pass a directory that does not
contain ``*.proto`` files. You can pass multiple directories

.. command-output:: rewrite-proto --root_package "foo"
    - read ./example_project/src/proto/general ./example_project/src/proto/services/request
    - calculated_packages


Fixing Imports and Packages
...........................

The purpose of the :func:`rewrite-proto <codestare.compiletools.compile.rewrite_proto>` tool is to
process the input ``.proto`` files so that the declared packages match the enforced directory structure and
imports are preserved. For this and internal mapping of imports and filenames is created once files are
:meth:`~codestare.compiletools.compile.Rewriter.read`. After calling
:meth:`~codestare.compiletools.compile.Rewriter.fix_imports` or
:meth:`~codestare.compiletools.compile.Rewriter.fix_packages` you may inspect the internal representation via
:meth:`~codestare.compiletools.compile.Rewriter.content`.

.. command-output:: rewrite-proto --root_package "foo"
    - read ./example_project/src/proto
    - fix_packages
    - content example_project/src/proto/services/request/subscription.proto

As you can see, the package has been changed.

.. command-output:: rewrite-proto --root_package "foo"
    - read ./example_project/src/proto
    - fix_packages
    - content example_project/src/proto/services/request.proto

Here the package of the imported message types has been changed to match the changed package in their ``.proto``
declaration, but the ``import`` statement is now wrong. Since the processed
``example_project/src/proto/services/request/subscription.proto`` file will be put into a directory
``[...]/foo/namespace/services/request`` to create a python package ``foo.namespace.services.request``
at the same location (recall that the python package output is only determined by the directory structure
of the ``.proto`` sources), the import will not find it. To fix this, one also needs to call
:meth:`~codestare.compiletools.compile.Rewriter.fix_imports`

.. command-output:: rewrite-proto --root_package "foo"
    - read ./example_project/src/proto
    - fix_packages
    - fix_imports
    - content example_project/src/proto/services/request.proto

Now the imports match the new directory structure.

Writing new directory structure
...............................

You can set the :attr:`~codestare.compiletools.compile.Rewriter.output_root`, by default the new directory structure
will be created in the current working directory.

.. command-output:: rewrite-proto --root_package "foo" - write --help
   :extraargs: 2>&1 | sed 's/\x1b\[[0-9;]*m//g'
   :shell:

.. note::
    As you can see ``--dry-run`` is the default. If you actually want to write your files, pass ``--nodry-run``
    according to `fire documentation <https://python-fire.readthedocs.io/en/latest/guide.html#boolean-arguments>`_

.. command-output:: rewrite-proto --root_package foo --output_root ./example_project/build/
    - read ./example_project/src/proto
    - fix_packages
    - fix_imports
    - write --nodry-run

.. command-output:: tree ./example_project/build


compile-proto
-------------

This tool is basically just a wrapper around the ``protoc`` compiler (which needs to be installed in your ``$PATH``
or be passed as a parameter) with nicely defined "compile options" for compilation with different plugins and plugin
parameters.

.. command-output:: compile-proto compile -- --help
   :shell:
   :extraargs: 2>&1 | sed 's/\x1b\[[0-9;]*m//g'

The options are defined in the :class:`~codestare.compiletools.options.CompileOption` enum. The enum class
implements some properties such that every enum value or combination of enum values (the
:class:`~codestare.compiletools.options.CompileOption` enum is a :class:`enum.IntFlag`, i.e. multiple values can be
combined) can be mapped to ``protoc`` plugins, parameters, and so on. You can explore this using the
`interactive mode <https://python-fire.readthedocs.io/en/latest/using-cli.html#-interactive-interactive-mode>`_ of the
tool.

Each :class:`~codestare.compiletools.options.CompileOption` which is not
:attr:`"composite" <codestare.compiletools.options.CompileOption.is_composite>` has an associated plugin.
Refer to the source code of the :class:`~codestare.compiletools.options.CompileOption` enum for more info.