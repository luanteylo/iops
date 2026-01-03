# Copyright 2013-2024 Lawrence Livermore National Security, LLC and other
# Spack Project Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

from spack.package import *


class PyPydoe3(PythonPackage):
    """pyDOE3: Design of Experiments for Python.

    A fork of pyDOE2 that provides various design of experiments algorithms
    including factorial designs, response surface designs, and more.
    """

    homepage = "https://github.com/relf/pyDOE3"
    pypi = "pyDOE3/pyDOE3-1.6.1.tar.gz"

    license("BSD-3-Clause")

    version("1.6.1", sha256="33923da2aa04ce0381a8fe9db678cba0c4b9906290a0c38dbf9cf316845ec98e")

    depends_on("python@3.8:", type=("build", "run"))
    depends_on("py-setuptools", type="build")
    depends_on("py-numpy", type=("build", "run"))
    depends_on("py-scipy", type=("build", "run"))
