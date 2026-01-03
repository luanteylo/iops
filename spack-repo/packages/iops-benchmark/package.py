# Copyright 2013-2024 Lawrence Livermore National Security, LLC and other
# Spack Project Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

from spack.package import *


class IopsBenchmark(PythonPackage):
    """A generic benchmark orchestration framework for automated parametric experiments.

    IOPS automates the generation, execution, and analysis of benchmark experiments.
    Instead of writing custom scripts for each benchmark study, you define a YAML
    configuration describing what to vary, what to run, and what to measure.
    """

    homepage = "https://gitlab.inria.fr/lgouveia/iops"
    git = "https://gitlab.inria.fr/lgouveia/iops.git"
    # pypi = "iops-benchmark/iops-benchmark-3.1.2.tar.gz"  # uncomment once on PyPI

    maintainers("lgouveia")

    license("BSD-3-Clause")

    version("main", branch="main")
    version("dev-3.0", branch="dev-3.0")
    version("3.1.2", tag="v3.1.2")

    depends_on("python@3.10:", type=("build", "run"))
    depends_on("py-setuptools@61:", type="build")
    depends_on("py-wheel", type="build")

    # Runtime dependencies (from pyproject.toml)
    depends_on("py-pyyaml", type=("build", "run"))
    depends_on("py-ruamel-yaml", type=("build", "run"))
    depends_on("py-psutil", type=("build", "run"))
    depends_on("py-sqlmodel", type=("build", "run"))
    depends_on("py-smt", type=("build", "run"))
    depends_on("py-scikit-optimize", type=("build", "run"))
    depends_on("py-pandas@2.1:", type=("build", "run"))
    depends_on("py-jinja2@3:", type=("build", "run"))
    depends_on("py-plotly", type=("build", "run"))
    depends_on("py-pyarrow", type=("build", "run"))
    depends_on("py-fastparquet", type=("build", "run"))
