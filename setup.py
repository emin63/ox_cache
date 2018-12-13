"""A setuptools based setup module for ox_cache
"""

# see also setup.cfg

from os import path

from setuptools import setup, find_packages
from ox_cache import VERSION


def get_readme():
    'Get the long description from the README file'

    here = path.abspath(path.dirname(__file__))
    # README.rst is autogenerated from README.md via something like
    # pandoc --from=markdown --to=rst --output=README.rst README.md
    with open(path.join(here, 'README.rst'), encoding='utf-8') as my_fd:
        result = my_fd.read()

    return result

setup(
    name='ox_cache',
    version=VERSION,
    description='Tools for caching and memoization in python.',
    long_description=get_readme(),
    url='http://github.com/aocks/ox_cache',
    author='Emin Martinian',
    author_email='emin.martinian@gmail.com',
    license='MIT',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'Programming Language :: Python :: 3',
    ],


    keywords='cache caching memoization', 
    packages=find_packages(exclude=['contrib', 'docs', 'tests']),
    include_package_data=True,
    install_requires=[],
    # If there are data files included in your packages that need to be
    # installed, specify them here.
    package_data={
        'sample': ['package_data.dat'],
    },
    # To provide executable scripts, use entry points in preference to the
    # "scripts" keyword. Entry points provide cross-platform support and allow
    # pip to create the appropriate form of executable for the target platform.
    entry_points={
        'console_scripts': [
            'sample=sample:main',
        ],
    },
)