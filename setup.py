from setuptools import setup, find_packages
from pathlib import Path

def parse_requirements(filename):
    with open(filename, "r") as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]

def read_version():
    with open("iops/VERSION", "r") as f:
        return f.read().strip()

def read_long_description():
    readme_path = Path(__file__).parent / "README.md"
    with open(readme_path, "r", encoding="utf-8") as f:
        return f.read()

setup(
    name="iops-benchmark",
    version=read_version(),
    author="TADAAM - INRIA Bordeaux",
    author_email="luan.teylo@inria.fr",
    description="A generic benchmark orchestration framework for automated parametric experiments",
    long_description=read_long_description(),
    long_description_content_type="text/markdown",
    license="BSD-3-Clause",
    url="https://gitlab.inria.fr/lgouveia/iops",
    project_urls={
        "Documentation": "https://gitlab.inria.fr/lgouveia/iops",
        "Source": "https://gitlab.inria.fr/lgouveia/iops",
        "Bug Reports": "https://gitlab.inria.fr/lgouveia/iops/-/issues",
    },
    packages=find_packages(),
    package_data={
        "iops": ["VERSION", "**/*.yaml", "**/*.yml"],
    },
    include_package_data=True,
    install_requires=parse_requirements("requirements.txt"),
    python_requires=">=3.10",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Science/Research",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Testing",
        "Topic :: System :: Benchmark",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Operating System :: POSIX :: Linux",
        "Operating System :: MacOS",
    ],
    keywords="benchmark, performance, testing, parametric, sweep, hpc, slurm",
    entry_points={
        "console_scripts": [
            "iops=iops.main:main",
        ],
    },
)
