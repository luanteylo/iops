from setuptools import setup, find_packages

with open('requirements.txt') as f:
    required_packages = f.read().splitlines()

setup(
    name='iops_env',
    version='1.0',
    author='Luan Teylo',
    author_email='luan.teylo@inria.fr',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    url='https://gitlab.inria.fr/lgouveia/iops',
    packages=find_packages(),
    install_requires=required_packages,
    python_requires='>=3.8',
)
