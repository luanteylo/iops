from setuptools import setup, find_packages

def parse_requirements(filename):
    with open(filename, "r") as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]

def read_version():
    with open("iops/VERSION", "r") as f:
        return f.read().strip()

setup(
    name="iops",
    version=read_version(),
    packages=find_packages(),
    install_requires=parse_requirements("requirements.txt"),
    entry_points={
        "console_scripts": [
            "iops=iops.main:main",
        ],
    },
)
