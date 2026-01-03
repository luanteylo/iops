# Copyright 2013-2024 Lawrence Livermore National Security, LLC and other
# Spack Project Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

from spack.package import *


class PyJenn(PythonPackage):
    """JENN: Jacobian-Enhanced Neural Networks.

    A Python library for neural networks with Jacobian enhancement,
    useful for surrogate modeling with gradient information.
    """

    homepage = "https://github.com/nasa/JENN"
    pypi = "jenn/jenn-2.0.0.tar.gz"

    license("Apache-2.0")

    version("2.0.0", sha256="d4e6f8299e49018e5c1b5c4a2ef2c0db5fc42bf73c71f31ef182b3def0b51fe4")

    depends_on("python@3.8:", type=("build", "run"))
    depends_on("py-setuptools", type="build")
    depends_on("py-numpy", type=("build", "run"))
    depends_on("py-matplotlib", type=("build", "run"))
    depends_on("py-jsonpointer", type=("build", "run"))
    depends_on("py-jsonschema", type=("build", "run"))
    depends_on("py-orjson", type=("build", "run"))
