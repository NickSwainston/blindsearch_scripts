#!/usr/bin/env python3

import logging
import argparse
import sys
import os
from os.path import join as ospj
from os.path import isfile as isfile
import numpy as np
import glob
from config_vcs import load_config_file
import psrqpy

from job_submit import submit_slurm
import data_processing_pipeline as dpp
import plotting_toolkit
import binfinder
import rm_synthesis

logger = logging.getLogger(__name__)

#get ATNF db location
try:
    ATNF_LOC = os.environ['PSRCAT_FILE']
except:
    logger.warn("ATNF database could not be loaded on disk. This may lead to a connection failure")
    ATNF_LOC = None

comp_config = load_config_file()

#---------------------------------------------------------------
class NotFoundError(Exception):
    """Raise when a value is not found in a file"""
    pass

def plot_everything(run_params):
    """
    Plots polarimetry, RVM fits, chi map and stacked profiles

    Parameters:
    -----------
    run_params: object
        The run_params object from data_processing_pipeline.py
    """
    os.chdir(run_params.pointing_dir)
    filenames_dict = create_filenames(run_params)
    if not isfile(filenames_dict["ascii"]):
        logger.error("Cannot plot without ascii archive")
        return

    #get RM
    if isfile(filenames_dict["rmsynth"]):
        rm_dict     = rm_synthesis.read_rmsynth_out(filenames_dict["rmsynth"])
        rm          = rm_dict["0"]["rm"]
        rm_e        = rm_dict["0"]["rm_e"]
    elif isfile(filenames_dict["rmfit"]):
        rm, rm_e    = find_RM_from_file(filenames_dict["rmfit"])
    if not rm:
        rm, rm_e    = find_RM_from_cat(run_params.pulsar)

    logger.info("Plotting dspsr archive {0} in {1}".format(filenames_dict["ascii"], run_params.pointing_dir))

    logger.info("Plotting polarimetry profile without RVM fit")
    plotting_toolkit.plot_archive_stokes(filenames_dict["ascii"],\
        obsid=run_params.obsid, pulsar=run_params.pulsar, freq=run_params.freq, out_dir=run_params.pointing_dir, rm=rm, rm_e=rm_e)

    #Try too get RVM dictionary + chi map
    try:
        rvm_dict    = read_rvm_fit_file(filenames_dict["rvmfit"])
        chi_map     = read_chi_map(filenames_dict["chimap"])
    except NotFoundError as e:
        rvm_dict    = None
        chi_map     = None

    if rvm_dict: #plot rvm
        if rvm_dict["nbins"]>=5:
            logger.info("Plotting polarimetry profile with RVM fit")
            plotting_toolkit.plot_archive_stokes(filenames_dict["ascii"],\
                obsid=run_params.obsid, pulsar=run_params.pulsar, freq=run_params.freq, out_dir=run_params.pointing_dir,\
                rm=rm, rm_e=rm_e, rvm_fit=rvm_dict)
        else:
            logger.info("Not enough PA points to plot RVM fit")

    if chi_map and rvm_dict: #plot chi_map
        logger.info("Plotting RVM fit chi squared map")
        dof = rvm_dict["dof"]
        chis = np.copy(chi_map["chis"])
        chi_map_name = "{}_RVM_reduced_chi_map.png".format(run_params.file_prefix)
        plotting_toolkit.plot_rvm_chi_map(chi_map["chis"][:], chi_map["alphas"][:], chi_map["betas"][:],\
            name=chi_map_name, my_chi=rvm_dict["redchisq"], my_beta=rvm_dict["beta"], my_alpha=rvm_dict["alpha"])

    #retrieve epn data
    try:
        logger.info("Plotting stacked archival profiles")
        pulsar_dict = plotting_toolkit.get_data_from_epndb(run_params.pulsar)
        #read my data
        pulsar_dict, my_lin_pol = plotting_toolkit.add_ascii_to_dict(pulsar_dict, filenames_dict["ascii"], run_params.freq)
        #ignore any frequencies > 15 000 MHz
        ignore_freqs = []

        for f in pulsar_dict["freq"]:
            if f>15000:
                ignore_freqs.append(f)
        #plot intensity stack
        plotting_toolkit.plot_stack(pulsar_dict["freq"][:], pulsar_dict["Iy"][:], run_params.pulsar,\
                out_dir=run_params.pointing_dir, special_freqs=[run_params.freq], ignore_freqs=ignore_freqs)
        #clip anything without stokes
        pulsar_dict = plotting_toolkit.clip_nopol_epn_data(pulsar_dict)
        #get lin pol - but don't change ours because it could have been generated from psrchive
        lin = plotting_toolkit.lin_pol_from_dict(pulsar_dict)
        for i, f in enumerate(pulsar_dict["freq"]):
            if f==run_params.freq:
                lin[i]=my_lin_pol
        #plot the polarimetry stack
        plotting_toolkit.plot_stack_pol(pulsar_dict["freq"], pulsar_dict["Iy"], lin, pulsar_dict["Vy"], run_params.pulsar,\
                out_dir=run_params.pointing_dir, ignore_freqs=ignore_freqs)
    except plotting_toolkit.NoEPNDBError:
        logger.info("Pulsar not on the EPN database")


def find_RM_from_cat(pulsar):
    """
    Gets rotation measure from prscat query. Returns None if not on catalogue

    Parameters:
    -----------
    pulsar: str
        The J-name of the pulsar

    Returns:
    --------
    rm: float
        The rotation measure
    rm_err: float
        The uncertainty in the rotation measure
    """

    query = psrqpy.QueryATNF(params=["RM"], psrs=[pulsar], loadfromdb=ATNF_LOC).pandas
    rm = query["RM"][0]
    rm_err = query["RM_ERR"][0]

    if np.isnan(rm):
        return None, None
    elif np.isnan(rm_err):
        rm_err = 0.15*rm
    return rm, rm_err

def read_rmfit(fname):
    """
    Finds the rotation measure from an input filename as generated by rmfit.
    Returns Nones if rm cold not be generates.
    """
    f = open(fname)
    lines=f.readlines()
    f.close()
    rm=None
    rm_err=None
    for line in lines:
        line = line.split()
        if line[0] == "Best" and line[1] == "RM":
            rm=float(line[3])
            if len(line) >= 5:
                rm_err=float(line[5])
            else:
                logger.warn("Uncertainty for RM not available")
                rm_err=None
            break
    if not rm:
        logger.warn("RM could not be generated from archive file")
    return rm, rm_err

def read_rvm_fit_file(filename):
    """
    Reads a file with the output from psrmodel and returns a dictionary of the results.
    Raises NotFoundError if an expected value is not present in the file

    Parameters:
    -----------
    filename: str
        The pathname of the file with the rvm fit

    Returns:
    --------
    rvm_dict: dictionary
        contains keys:
            nbins: int
                The number of bins used in the rvm fit
            psi_0: float
                The derived psi_0 parameter
            psi_0_e: float
                The uncertainty in psi_0
            beta: float
                The derived beta parameter
            beta_e: float
                The uncertainty in beta
            alpha: float
                The derived alpha parameter
            alpha_e:
                The uncertainty in alpha
            phi_0: float
                The derived phi_0 parameter
            phi_0_e: float
                The uncertainty in phi_0
            redchisq: float
                The reduced chi square of the best fit
            dof: int
                The degrees of freedom of the fit
    """
    keylist = ("nbins", "redchisq", "dof", "psi_0", "psi_0_e", "beta", "beta_e",\
                "alpha", "alpha_e", "phi_0",  "phi_0_e")
    rvm_dict={}
    for key in keylist:
        rvm_dict[key]=None
    f = open(filename)
    lines = f.readlines()
    f.close()
    n_elements = 0
    for i, line in enumerate(lines):
        if line.endswith("bins\n"):
            rvm_dict["nbins"] = int(line.split()[-2])
        elif line[0:6] == "chisq=":
            rvm_dict["redchisq"] = float(line.split()[-1])
            rvm_dict["dof"] = int(line.split()[0].split("=")[-1])
        elif line[0:7] == "psi_0=(":
            psi_0_str = line.split()[0].split("=")[-1].split("(")[-1].split(")")[0].split("+")
            rvm_dict["psi_0"] = float(psi_0_str[0])
            rvm_dict["psi_0_e"] = abs(float(psi_0_str[-1]))
        elif line[0:7] == "beta =(":
            beta_str = line.split()[1].split("(")[-1].split(")")[0].split("+")
            rvm_dict["beta"]  = float(beta_str[0])
        elif line[0:7] == "alpha=(":
            alpha_str = line.split()[0].split("(")[-1].split(")")[0].split("+")
            rvm_dict["alpha"]  = float(alpha_str[0])
        elif line[0:7] == "phi_0=(":
            phi_0_str = line.split()[0].split("(")[-1].split(")")[0].split("+")
            rvm_dict["phi_0"]  = float(phi_0_str[0])
            rvm_dict["phi_0_e"]  = abs(float(phi_0_str[-1]))
        elif line[0:6] == "alpha=":
            n_elements += 1

    rvm_dict["alpha_e"]  = 180/np.sqrt(n_elements)/2
    rvm_dict["beta_e"]  = 180/np.sqrt(n_elements)/2

    for key in keylist:
        if rvm_dict[key] is None:
            raise NotFoundError("{0} not found in file: {1}".format(key, filename))

    return rvm_dict

def read_chi_map(map):
    """
    Reads a chi map of an RVM fit output by psrmodel

    Parameters:
    -----------
    map: str
        The pathname of the map to read

    Returns:
    --------
    chi_map: dictionary
        contains keys:
            alphas: list
                The alpha values in degrees
            betas: list
                The beta values in degrees
            chis: list x list
                The chi values corresponding to the alpha/beta pairs
    """
    f = open(map)
    lines = f.readlines()
    f.close()
    alphas = []
    betas = []
    chis = []
    for i, line in enumerate(lines):
        if not line == "\n":
            chis.append(float(line.split()[2]))
            if len(alphas)==0:
                betas.append(float(line.split()[1]))
        else:
            alphas.append(float(lines[i-1].split()[0]))
    f.close()
    chis = np.reshape(chis, (len(alphas), len(betas)))
    chis = np.transpose(chis)
    chi_map = {"alphas":alphas, "betas":betas, "chis":chis}

    return chi_map

def analytic_pa(phi, alpha, beta, psi_0, phi_0):
    #Inputs should be in radians
    numerator = np.sin(alpha) * np.sin(phi - phi_0)
    denominator = np.sin(beta + alpha) * np.cos(alpha) - np.cos(beta + alpha) * np.sin(alpha) * np.cos(phi - phi_0)
    return np.arctan2(numerator,denominator) + psi_0

def add_rvm_to_commands(run_dir, archive_name, rvmfile="RVM_fit.txt", chimap="chimap.txt", commands=None, res=90):
    """
    Adds the RVM fitting commands to a list

    run_dir: str
        The directory to run the commands in
    archive_name: str
        The name of the archive file to fit
    rvmfile: str
        OPTIONAL - The name of the output RVM fit text file. Default: 'RVM_fit.txt'
    chimap: str
        OPTIONAL - The name of the output chi map file. Default: 'chimap.txt'
    commands: list
        OPTIONAL - A list to append the commands to. Default: None
    res: int
        OPTIONAL - The number of solutions to trial for both alpha and beta. Default: 90

    Returns:
    --------
    commands: list
        A list of commands with the RVM fitting commands appended
    """
    if not commands:
        commands = []
    commands.append("cd {}".format(run_dir))
    commands.append("echo 'Fitting RVM'")
    modelcom = "psrmodel {} -resid -psi-resid -x -use_beta -beta -45:45".format(archive_name)
    modelcom += " -s {0}X{0}".format(res)
    modelcom += " &> {}".format(rvmfile)
    modelcom += " > {}".format(chimap)
    commands.append(modelcom)

    return commands

def submit_rmcor(pipe, dep_id=None, dep_type="afterany"):
    """Reads the RM value and Submits the correction job to the queue"""
    pipe["source"]["my_RM"] = pipe["source"]["ATNF"]["RM"][0]
    pipe["source"]["my_RM_e"] = pipe["source"]["ATNF"]["RM"][0]
    pipe["source"]["RM_method"] = "ATNF"
    pipe["source"]["fit_RM"], pipe["source"]["fit_RM_e"] = read_rmfit(pipe["pol"]["rmfit"])
    if ["source"]["fit_RM"]:
        pipe["source"]["my_RM"] = pipe["source"]["fit_RM"]
        pipe["source"]["my_RM_e"] = pipe["source"]["fit_RM_e"]
        pipe["source"]["RM_method"] = "RM_fit"
    synth_dict = rm_synthesis.read_rmsynth_out(pipe["pol"]["rmsynth"])
    if "rm" in synth_dict.keys():
        pipe["source"]["synth_RM"], pipe["source"]["synth_RM_e"] = read_rmfit(pipe["pol"]["rmfit"])
        pipe["source"]["my_RM"] = pipe["source"]["synth_RM"]
        pipe["source"]["my_RM_e"] = pipe["source"]["synth_RM_e"]
        pipe["source"]["RM_method"] = "RM_synthesis"
    if not pipe["source"]["my_RM"]:
        raise NotFoundError("Rotation measure could not be calculated and is not on ATNF database")
    else:
        logger.info(f"Rotation measure found: {pipe['source']['my_RM']} +/- {pipe['source']['my_RM_e']}")
        logger.info(f"using method: {pipe['pipe']['RM_method']}")
    #Submit the correction job
    ar_name = f"{pipe['obs']['id']}_{pipe['source']['name']}_b{[pipe['source']['my_bins']]}_rm_corrected"
    pipe['pol']['archive2'] = ospj(pipe['run_ops']['my_dir'], f"{ar_name}.ar2")
    commands = [f"cd {pipe['run_ops']['my_dir']}"]
    commands.append(f"pam -e ar2 -R {pipe['source']['my_RM']} {pipe['pol']['archive1']}")
    commands.append(f"pdv -FTtlZ {pipe['pol']['archive2']} > {ar_name}.txt")
    job_name = f"rm_correction_{pipe['obs']['id']}_{pipe['source']['name']"
    batch_dir = os.path.join(
        comp_config['base_data_dir'], pipe['obs']['id'], "batch")
    job_id = submit_slurm(job_name, commands,
                           batch_dir=batch_dir,
                           slurm_kwargs={"time": "01:00:00"},
                           module_list=["psrchive/master"],
                           submit=True, depend=dep_id, dep_type=dep_type)
    return job_id


def submit_rmsynth(pipe, dep_id=None, dep_type="afterany"):
    """Submits an rm synthesis job to the queue"""
    label = f"{pipe['obs']['id']}_{pipe['source']['name']}_rms"
    rms_com = "rm_synthesis.py"
    rms_com += f" -f {pipe['pol']['archive1']}".format(archive_name)
    rms_com += f" --label {label}")
    rms_com += " --write"
    rms_com += " --plot"
    rms_com += " --keep_QUV"
    rms_com += " --force_single"
    commands = [f"cd {pipe['run_ops']['my_dir']}"]
    commands.append(rms_coms)
    pipe["pol"]["rmsynth"] = ospj(pipe['run_ops']['my_dir'], f"{label}_RMsynthesis.txt")
    job_name = f"rmsynth_{pipe['obs']['id']}_{pipe['source']['name']"
    batch_dir = os.path.join(
        comp_config['base_data_dir'], pipe['obs']['id'], "batch")
    job_id = submit_slurm(job_name, commands,
                           batch_dir=batch_dir,
                           slurm_kwargs={"time": "01:00:00"},
                           module_list=[f"vcstools/{pipe['run_ops']['vcstools']}"],
                           submit=True, depend=dep_id, dep_type=dep_type)
    return job_id


def submit_rmfit(pipe, dep_id=None, dep_type="afterany"):
    """Submits an rmfit job to the queue"""
    rmfit_name = ospj(pipe["run_ops"]["my_dir"], f"{pipe['obs']['id']}_{pipe['source']['name']}_rmfit.txt")

    commands.append(f"rmfit {pipe['pol']['archive1']} -t > {rmfit_name}")
    pipe["pol"]["rmfit"] = rmfit_name
    job_name = f"rmfit_{pipe['obs']['id']}_{pipe['source']['name']"
    batch_dir = os.path.join(
        comp_config['base_data_dir'], pipe['obs']['id'], "batch")
    job_id = submit_slurm(job_name, commands,
                           batch_dir=batch_dir,
                           slurm_kwargs={"time": "01:00:00"},
                           module_list=["psrchive/master"],
                           submit=True, depend=dep_id, dep_type=dep_type)
    return job_id


def submit_dspsr(pipe, dep_id=None, dep_type="afterany"):
    """Submits the dspsr fold command to the queue"""
    commands = [f"cd {pipe['run_ops']['my_dir']}"]
    ar_name = f"{pipe['obs']['id']}_{pipe['source']['name']}_b{[pipe['source']['my_bins']]}"
    pipe["folds"]["dspsr"]["archive1"] = ospj(pipe['run_ops']['my_dir'], f"{ar_name}.ar")
    dspsr_com = "dspsr -U 4000 -A -K -cont"
    dspsr_com += f" -b {pipe['source']['my_bins']}"
    dspsr_com += f" -c {pipe['source']['my_period']*1000}" #*1000 because dspsr takes seconds
    dspsr_com += f" -D {pipe['source']['my_dm']}"
    dspsr_com += f" -S {pipe['source']['seek']}"
    dspsr_com += f" -T {pipe['source']['total']}"
    dspsr_com += f" -L {pipe['source']['total']}" #timscrunch the whole obs
    if pipe["run_ops"]["vdif"] == True: #fold on vdif files
        psradd_coms = f"psradd -R -m time *ar -o {ar_name}"
        commands.append("j=0")
        commands.append("for i in *.hdr;")
        commands.append(f"   do {dspsr_coms} -O ipfb_$j $i ;")
        commands.append("   j=$((j+1))")
        commands.append("done;")
        commands.append(psradd_coms)
    else: #fold on fits files
        dspsr_com += f" -O {ar_name}"
        dspsr_com += " *.fits"
        commands.append(dspsr_com)
    job_name = f"dspsr_fold_{ar_name}"
    batch_dir = os.path.join(
        comp_config['base_data_dir'], pipe['obs']['id'], "batch")
    job_id = submit_slurm(job_name, commands,
                           batch_dir=batch_dir,
                           slurm_kwargs={"time": "06:00:00"},
                           module_list=["dspsr/master", "psrchive/master"],
                           submit=True, depend=dep_id, dep_type=dep_type)
    logger.info(f"DSPSR fold script submitted for pointing directory: {pipe['run_ops']['my_dir']}")
    logger.info(f"Job name: {job_name}")
    logger.info(f"Job ID: {job_id}")
    return job_id


def pol_main(pipe):
        """A logic structure that decides what to do next"""
    if not pipe["completed"]["polarimetry"]:
        if not pipe["completed"]["init_pol"]:
            dep_ids = submit_dspsr(pipe)
            dep_ids = [submit_rmfit(pipe, dep_ids=dep_ids, dep_type="afterok")]
            dep_ids.append(submit_rmsynth(pipe))
            pipe["completed"]["init_dspsr"] = True
            dpp.resubmit_self(pipe, dep_ids=dep_ids, dep_type="afterok")
        elif not pipe["completed"]["post_pol"]:
            dep_ids = submit_rmcor(pipe)
            dep_ids.append(submit_rvmfit(pipe, dep_ids=dep_ids, dep_type="afterok"))
            dpp.resubmit_self(pipe, dep_ids=dep_ids, dep_type="afterok")
        elif not pipe["completed"]["pol_plot"]:
            plot_pol(pipe)
    else:
        logger.info("The polarimetry pipeline has already been completed")