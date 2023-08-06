import os
import sys
from setuptools import setup

install_requires = [
    'mysql-python>=1.2.3', 
    'psycopg2>=2.4.2',
    'pyyaml>=3.10.0',
    'pytz',
]

if os.name == 'posix':
    install_requires.append('termcolor>=1.1.0')

version = sys.version_info[:2]

if version < (2,7) or (3,0) <= version <= (3,1):
    install_requires += ['argparse']

setup(
    name='py-mysql2pgsql',
    version='0.1.6',
    description='Tool for migrating/converting from mysql to postgresql.',
    long_description=open('README.rst').read(),
    license='MIT License',
    author='Philip Southam',
    author_email='philipsoutham@gmail.com',
    url='https://github.com/philipsoutham/py-mysql2pgsql',
    zip_safe=False,
    packages=['mysql2pgsql', 'mysql2pgsql.lib'],
    scripts=['bin/py-mysql2pgsql'],
    platforms='any',
    install_requires=install_requires,
    classifiers=[
        'License :: OSI Approved :: MIT License',
        'Development Status :: 3 - Alpha',
        'Environment :: Console',
        'Intended Audience :: System Administrators',
        'Intended Audience :: Developers',
        'Natural Language :: English',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 2.7',
        'Topic :: Database',
        'Topic :: Utilities'
        ],
    keywords = 'mysql postgres postgresql pgsql psql migration',
    )
