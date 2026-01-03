# Copyright 2013-2024 Lawrence Livermore National Security, LLC and other
# Spack Project Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

from spack.package import *


class PySqlmodel(PythonPackage):
    """SQLModel is a library for interacting with SQL databases from Python code,
    with Python objects. It is designed to be intuitive, easy to use, highly
    compatible, and robust."""

    homepage = "https://sqlmodel.tiangolo.com/"
    pypi = "sqlmodel/sqlmodel-0.0.31.tar.gz"

    license("MIT")

    version("0.0.31", sha256="2d41a8a9ee05e40736e2f9db8ea28cbfe9b5d4e5a18dd139e80605025e0c516c")

    depends_on("python@3.7:", type=("build", "run"))
    depends_on("py-pdm-backend", type="build")
    depends_on("py-sqlalchemy@2.0.14:2.0", type=("build", "run"))
    depends_on("py-pydantic@2.7:", type=("build", "run"))
