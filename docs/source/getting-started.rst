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


CLI Usage
---------

If installed with extra ``[cli]`` the package provides two command line entry points:

    - :func:`compile-proto <codestare.compiletools.compile.compile_proto>`
    - :func:`rewrite-proto <codestare.compiletools.compile.rewrite_proto>`

Available options for compilation / rewriting files and respective arguments can be found using the ``--help`` flag of the
cli tools and in the :mod:`API documentation <codestare.compiletools.compile>`

.. highlight:: console

For example:::

    >>> compile-proto --help

.. program-output:: compile-proto --help 2>&1 | sed 's/\x1b\[[0-9;]*m//g'
   :shell:

You can then show the available options:::

    >>> compile-proto OPTIONS

.. program-output:: compile-proto OPTIONS 2>&1 | sed 's/\x1b\[[0-9;]*m//g'
   :shell:


``setup.cfg``
-------------

The package installs ``setuptools`` commands.

.. command-output:: python ../../setup.py --help-commands
   :ellipsis: 0, -13
