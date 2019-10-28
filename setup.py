#! /usr/bin/env python3
"""
Setup for mwa_search
"""
import os
import sys
from setuptools import setup
from subprocess import check_output

def read(fname):
    """Read a file"""
    return open(os.path.join(os.path.dirname(__file__), fname)).read()

#The following two functions were taken from the repo: https://github.com/pyfidelity/setuptools-git-version/blob/master/setuptools_git_version.py
def format_version(version, fmt='{tag}.{commitcount}_{gitsha}'):
    parts = version.split('-')
    if len(parts) < 4:
        return parts[0]
    assert len(parts) in (3, 4)
    dirty = len(parts) == 4
    tag, count, sha = parts[:3]
    if count == '0' and not dirty:
        return tag
    return fmt.format(tag=tag, commitcount=count, gitsha=sha.lstrip('g'))

def get_git_version():
    git_version = check_output('git describe --tags --long --dirty --always'.split()).decode('utf-8').strip()
    return format_version(version=git_version)

mwa_search_version = get_git_version()

# Since we mostly run this on supercomputers it probably isn't correct to 
# pip install all these modules
reqs = ['python>=3.6.3',
        'argparse>=1.4.0',
        'numpy>=1.13.3',
        'matplotlib>=2.1.0',
        'astropy>=2.0.2']

#make a temporary version file to be installed then delete it
with open('version.py', 'a') as the_file:
    the_file.write('__version__ = "{}"\n'.format(mwa_search_version))

setup(name="mwa_search",
      version=mwa_search_version,
      description="Scripts used to search for pulsars with the Murchison Widefield Array's Voltage Capture System data",
      url="https://github.com/NickSwainston/mwa_search",
      long_description=read('README.md'),
      #install_requires=reqs,
      scripts=['scripts/ACCEL_sift.py', 'scripts/binfinder.py', 'scripts/check_known_pulsars.py',
               'scripts/data_process_pipeline.py', 'scripts/grid.py', 'scripts/lfDDplan.py',
               'scripts/mwa_search_pipeline.py', 'scripts/search_epndb.py',
               'scripts/splice_wrapper.py', 'scripts/stokes_fold.py',
               'database/init_search_database.py', 'database/search_database.py',
               'database/cold_storage_mover.py',
               'plotting/plot_obs_pulsar.py', 'plotting/plotting_toolkit.py',
               'plotting/position_sn_heatmap_fwhm.py',
               'version.py'],
      #data_files=[('AegeanTools', [os.path.join(data_dir, 'MOC.fits')]) ],
      setup_requires=['pytest-runner'],
      tests_require=['pytest']#, 'nose']
)

os.remove('version.py')