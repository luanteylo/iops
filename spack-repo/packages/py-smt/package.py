# Copyright 2013-2024 Lawrence Livermore National Security, LLC and other
# Spack Project Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

from spack.package import *


class PySmt(PythonPackage):
    """SMT: Surrogate Modeling Toolbox. A Python library for surrogate modeling
    and design space exploration."""

    homepage = "https://smt.readthedocs.io/"
    pypi = "smt/smt-2.10.1.tar.gz"

    license("BSD-3-Clause")

    version("2.10.1", sha256="3e56df1c46d4b1dd0c21a5c6efd0dc219797cfd8b4f9ebfddc3f000a94a8de63")

    depends_on("python@3.9:", type=("build", "run"))
    depends_on("py-setuptools", type="build")
    depends_on("py-packaging", type=("build", "run"))
    depends_on("py-scikit-learn", type=("build", "run"))
    depends_on("py-pydoe3@1.5:", type=("build", "run"))
    depends_on("py-scipy", type=("build", "run"))
    depends_on("py-jenn@2:2", type=("build", "run"))
