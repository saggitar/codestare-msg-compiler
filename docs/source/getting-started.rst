Getting Started
===============


Installation
------------

-  required: python >= 3.7
-  install from PyPi via ``pip install codestare-msg-compiler`` or check out source and install locally.
-  Set the plugin as a build dependency in your ``pyproject.toml`` e.g.

.. code-block::
   :caption: pyproject.toml

   [build-system]
   requires = [
       "setuptools>=42",
       "wheel",
       "codestare-msg-compiler[protoplus] >= 0.0.4",
   ]
   ...


There are extras defined for the different supported :py:class:`flavors <codestare.compiletools.cmd.CompileProto.Flavor>`
of python protobuf messages, to easily install all required dependencies (e.g. third party ``protoc`` plugins).
The available extras for python-package flavors are:

- ``[mypy]`` (depends on / installs ``mypy``, ``mypy-protobuf``)
- ``[betterproto]`` (depends on / installs ``betterproto[compiler]``)
- ``[protoplus]`` (depends on / installs ``codestare-proto-plus``)

CLI Usage
---------

If installed with extra ``[cli]`` the package provides two command line entry points:

    - :func:`compile-proto <codestare.compiletools.compile.compile_proto>`
    - :func:`rewrite-proto <codestare.compiletools.compile.rewrite_proto>`

Available options for compilation / rewriting files and respective arguments can be found using the ``--help`` flag of the
cli tools and in the :mod:`API documentation <codestare.compiletools.compile>`

.. highlight:: console

For example:

.. command-output:: compile-proto --help
   :shell:
   :extraargs: 2>&1 | sed 's/\x1b\[[0-9;]*m//g'

You can then show the available options:

.. command-output:: compile-proto OPTIONS
   :shell:
   :extraargs: 2>&1 | sed 's/\x1b\[[0-9;]*m//g'


.. _setup:

Setup
-------------

The package installs ``setuptools`` commands.::

    $ python setup.py --help-commands

.. program-output:: python ../../setup.py --help-commands
   :ellipsis: 0, -13

To build your project with the extra build steps, use a custom
``setup.py`` file, e.g.

.. literalinclude:: ./example_project/setup.py
   :language: python

.. only:: builder_html

   .. note::

       The example project is available for :download:`download <example_project.zip>`.
       You might want to test the behaviour of the build commands on some files that
       you don't care about ;)

You can then configure the build steps via your ``setup.cfg`` file.
Let's say your project has the following structure:



.. command-output:: tree ./example_project


.. note::

    To make things more interesting the ``.proto`` files are not included in the
    python package yet (notice the ``package_dir`` option in the `setup.cfg`_).
    Maybe they are shared between different projects, some of which
    are not even written in python -- ``src/proto`` could just be a git submodule

    Also, the protobuf package should be built to ``src/py/namespace/proto/v1``.
    You want to import all message types from there in the ``__init.py__`` of your ``namespace.proto`` package,
    to create a simpler ("flat") API for your users and to make it easy to manage several
    versions of the protobuf schema -- by simply importing from a different subpackage, if needed.


To achieve this, configure your build steps like this (this setup uses the ``proto-plus`` flavor,
so you need to install the ``[protoplus]`` extra):

.. _setup.cfg:
.. literalinclude:: ./example_project/setup.cfg
   :language: cfg

.. highlight:: console

Now build your project...::

    $ cd example_project/
    $ python setup.py build

.. program-output:: sh -c "cd ./example_project/ && python setup.py build"
   :shell:
   :ellipsis: 6

What has been generated?

.. command-output:: tree ./example_project/src/py


.. warning::

   The compiler tools have copied the "fixed" version of the ``.proto`` files to
   the python package, so you can inspect what was changed. When you set the
   :attr:`~codestare.compiletools.cmd.RewriteProto.inplace` option (e.g. in your
   ``setup.cfg``) the proto files will not be copied to the python package,
   and instead be overwritten. Only use this feature if your ``.proto`` sources
   are under version control and you can correct possible errors easily!

.. highlight:: console

For example the original ``.proto`` file looked like this ...

.. command-output:: cat ./example_project/src/proto/general/error.proto

... but the package and import name has been adjusted to match the python directory structure

.. command-output:: cat ./example_project/src/py/namespace/proto/v1/general/error.proto

.. note::

    The CLI tools and *setuptools* commands can be used to quickly adjust ``.proto`` files
    to generate more complex python package structures primarily during development, when the structure is not yet fixed.
    To avoid using different versions of ``.proto`` sources just generate your ``.proto`` files once when
    you are ready. The *codestare-msg-compiler* package only touches ``package`` and ``import``
    statements in your ``.proto`` sources.