from setuptools import setup, find_packages

setup(
    name='iops_env',
    version='1.0',
    author='Luan Teylo',
    author_email='luan.teylo@inria.fr',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    url='https://gitlab.inria.fr/lgouveia/iops',    
    packages=find_packages(),
    install_requires=[
        'matplotlib>=3.0',
        'numpy>=1.18',
        'pandas>=1.0',
        'scipy>=1.4',
        'seaborn>=0.10',
        'readline>=6.2',
        'python-dotenv>=0.10',
        'paramiko>=2.7',
    ],
    python_requires='>=3.8',
)
