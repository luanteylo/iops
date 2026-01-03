# Copyright 2013-2024 Lawrence Livermore National Security, LLC and other
# Spack Project Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

from spack.package import *


class PyFastparquet(PythonPackage):
    """fastparquet is a Python implementation of the Parquet format,
    aiming to integrate into Python-based big data workflows."""

    homepage = "https://fastparquet.readthedocs.io/"
    pypi = "fastparquet/fastparquet-2024.11.0.tar.gz"

    license("Apache-2.0")

    version("2024.11.0", sha256="e3b93e35b186e0d27708660f65ea3d4cd7f4f94770c83b176a85c851b1132a81")

    depends_on("python@3.9:", type=("build", "run"))
    depends_on("py-setuptools", type="build")
    depends_on("py-setuptools-scm", type="build")
    depends_on("py-cython", type="build")
    depends_on("py-numpy", type=("build", "run"))
    depends_on("py-pandas@1.5:", type=("build", "run"))
    depends_on("py-cramjam@2.3:", type=("build", "run"))
    depends_on("py-fsspec", type=("build", "run"))
    depends_on("py-packaging", type=("build", "run"))
