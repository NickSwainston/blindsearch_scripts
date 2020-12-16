#!/usr/bin/env python3
import logging
from os import makedirs, symlink, rmdir, unlink, getcwd, chdir, remove
from os.path import exists, join, basename
from shutil import copyfile
from glob import glob

from vcstools.config import load_config_file

comp_config = load_config_file()
logger = logging.getLogger(__name__)


def create_dpp_dir(kwargs):
    dpp_dir = join(comp_config["base_data_dir"], str(kwargs["obsid"]), "dpp")
    makedirs(dpp_dir, exist_ok=True)


def setup_cfg_dirs(cfg):
    """Creates the necessary folders and symlinks for dpp"""
    # Create pulsar directory
    psr_dir = join(dpp_dir, cfg['run_ops']['file_precursor'])
    makedirs(psr_dir, exist_ok=True)
    # Create classify dir
    makedirs(cfg["run_ops"]["classify_dir"], exist_ok=True)
    # Create symlinks to pointing dirs
    for pointing in cfg['folds'].keys():
        real = join(comp_config["base_data_dir"], str(kwargs["obsid"]), "pointings", pointing)
        sym = join(psr_dir, pointing)
        if exists(real):
            if not exists(sym):
                symlink(real, sym)
        else: # Remove the pointing from the dictionary if the real pointing directory isn't found
            logger.warn(f"Expected pointing directory not found: {pointing}. Skipping")
            cfg["folds"].remove(pointing)


def clean_cfg(cfgs):
    """Remove any lists in the cfg that are empty and deletes the directories"""
    dpp_dir = join(comp_config["base_data_dir"], str(kwargs["obsid"]), "dpp")
    if cfg["folds"] == {}:
        logger.warn(f"No pointings available for {cfg['source']['name']}. Removing")
        cfg = None # Delete directory


def remove_old_results(cfg):
    """Removes old results from previous ppp runs"""
    psr_dir = cfg["run_ops"]["psr_dir"]
    for f in glob(join(cfg["run_ops"]["classify_dir"], "*")):
        remove(f)
    for pointing in cfg["folds"].keys():
        stuff = glob(join(psr_dir, pointing, f"*{cfg['run_ops']['file_precursor']}*"))
        for thing in stuff:
            remove(thing)


def file_precursor(kwargs, psr):
    """
    Creates a common precursor string for files and directories
    using kwargs from observation_processing_pipeline.py and a pulsar name
    """
    label = kwargs["label"]
    if label:
        label = f"_{kwargs['label']}"
    return f"{kwargs['obsid']}{label}_{psr}"


def setup_classify(cfg):
    """Creates the required directories and copies files for the lotaas classifier"""
    owd = getcwd()
    chdir(cfg["run_ops"]["psr_dir"])
    makedirs(cfg["run_ops"]["classify_dir"], exist_ok=True) # This should already exist but keep it anyway
    for pointing in cfg["folds"].keys():
        init_bins = list(cfg["folds"][pointing]["init"].keys())[0]
        if int(init_bins) not in (50, 100):
            raise ValueError(f"Initial bins for {cfg['source']['name']} is invalid: {init_bins}")
        try:
            glob_dir = join(pointing, f"*b{init_bins}*.pfd")
            pfd_name = glob(glob_dir)[0]
        except IndexError as e:
            raise IndexError(f"No suitable pfds found: {glob_dir}")
        newfilename=join(cfg["run_ops"]["classify_dir"], basename(pfd_name))
        copyfile(pfd_name, newfilename)
    chdir(owd)


def find_config_files(obsid, label=""):
    """Searches the obsid/dpp directories to find any config (.yaml) files"""
    dpp_dir = join(comp_config["base_data_dir"], str(obsid), "dpp")
    yaml_files = join(dpp_dir, "*", f"{obsid}*{label}.yaml")
    config_pathnames = glob(yaml_files)
    if not config_pathnames:
        raise ValueError(f"No config files found: {yaml_files}")
    return config_pathnames
