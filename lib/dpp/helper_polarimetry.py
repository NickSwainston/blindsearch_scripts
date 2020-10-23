import logging
import numpy as np

from dpp.helper_yaml import from_yaml, dump_to_yaml
from prof_utils import auto_gfit
from config_vcs import load_config_file


logger = logging.getLogger(__name__)

comp_config = load_config_file()


#Command file labels:
fold_fits_w_dspsr_label     = "dspsr_fold"
archive_to_fits_label       = "to_fits"
remove_baseline_label       = "debase"
rmsynthesis_initial_label   = "initial_rm_synthesis"
rmsynthesis_final_label     = "final_rm_synthesis"
defarad_label               = "defarad"
rvmfit_initial_label        = "initial_rvmfit"
rvmfit_final_label          = "final_rvmfit"

def rm_limit(freq_obs_mhz, freq_res_khz=10, division_factor=100):
    """
    Decides on the maximum detectable rotation measure using:
    RM <= (PI/100c^2) * (V0^3) * (delV^-1)
    """
    const = np.pi/(3e8)**2
    const = const/division_factor
    const = const * 1e15
    rm_max = const * (freq_obs_mhz**3) / freq_res_khz
    return rm_max


def read_rmtable(rmtable):
    """Reads an RMtable output from rmsynth and returns RM and error"""
    rm, rm_e = np.genfromtxt(rmtable)
    return rm, rm_e


def read_rvm_output(rvmfit):
    """Reads a stdout file generated by ppolFit"""
    with open(rvmfit, "r") as f:
        lines = f.readlines()
    alpha = None
    beta = None
    l0 = None
    pa0 = None
    chi = None
    for line in lines:
        if "alpha =" in line:
            alpha = float(line.split()[2])
            break
    for line in lines:
        if "beta  =" in line:
            beta = float(line.split()[2])
            break
    for line in lines:
        if "l0    =" in line:
            l0 = float(line.split()[2])
            break
    for line in lines:
        if "pa0   =" in line:
            pa0 = float(line.split()[2])
            break
    for line in lines:
        if "chi^2=" in line:
            chi = float(split()[1].split("=")[1])
            break
    if None in (alpha, beta, l0, pa0, chi):
        raise ValueError(f"""
                        None value in file: {rvmfit}
                        alpha:  {alpha}
                        beta:   {beta}
                        l0:     {l0}
                        pa0:    {pa0}
                        chi:    {chi}
                        """)
    return (alpha, beta, l0, pa0, chi)


def tofile_fold_fits_w_dspsr(pipe, fits):
    """Creates a file containing a command to fold a fits file using dspsr"""
    myfile = f"{pipe['run_ops']['file_precursor']}_{fold_fits_w_dspsr_label}_cmds.sh"
    cmd = "dspsr -A -K -cont"
    cmd += " -U 4000" # 4GB RAM
    cmd += f" -S {pipe['source']['seek']}" # Where to begin fold
    cmd += f" -T {pipe['source']['total']}" # Total fold time
    cmd += f" -L {pipe['source']['total']}" # Single sub integration
    cmd += f" -b {pipe['folds']['best']['nbins']}" # Number of bins
    cmd += f" -c {pipe['folds']['best']['period'] * 1000}" # DSPSR needs period in seconds
    cmd += f" -D {pipe['folds']['best']['dm']}" #dm
    cmd += f" -O {pipe['run_ops']['file_percursor']}.ar" #output archive name
    cmd += f" {fits}"
    with open(myfile, "w+") as f:
        f.write(cmd)


def tofile_archive_to_fits(pipe):
    """Creates a file containing a command to revert an archive back to a fits file using pam"""
    myfile = f"{pipe['run_ops']['file_precursor']}_{archive_to_fits_label}_cmds.sh"
    cmd = "pam -a PSRFITS -T -e newfits"
    cmd += f" {pipe['run_ops']['file_percursor']}.ar"
    move_cmd = f"mv *.newfits {pipe['run_ops']['file_percursor']}.newfits"
    with open(myfile, "w+") as f:
        f.write(f"{cmd}\n\n")
        f.write(move_cmd)


def tofile_remove_baseline(pipe):
    """Removes baseline RFI from a fits file"""
    myfile = f"{pipe['run_ops']['file_precursor']}_{remove_baseline_label}_cmds.sh"
    on_pulse = pipe["folds"]["best"]["gfit"]["comp_idx"]["0"]
    cmd = "pmod -debase"
    cmd += f" -onpulsef '{min(on_pulse)} {max(on_pulse)}'"
    cmd += f" -device {pipe['run_ops']['file_precursor']}_debase.ps/cps" # is a useless line plot but needs to be here
    with open(myfile, "w+") as f:
        f.write(cmd)


def tofile_rmsynthesis(pipe):
    """Runs RM synthesis"""
    on_pulse = pipe["folds"]["best"]["gfit"]["comp_idx"]["0"]
    if pipe["source"]["synth_rm"] is None: #first synthesis trial
        myfile = f"{pipe['run_ops']['file_precursor']}_{rmsynthesis_initial_label}_cmds.sh"
        move_cmd = f"mv *.RMtable {pipe['run_ops']['file_precursor']}_{rmsynthesis_initial_label}.RMtable" # rename the rmtable
        rm_minmax = rm_max(pipe["obs"]["freq"], freq_res_khz=10, division_factor=100) #assuming freq res is 10khz
        rm_min = -rm_minmax
        rm_max = rm_minmax
    else:   #second synthesis trial
        myfile = f"{pipe['run_ops']['file_precursor']}_{rmsynthesis_final_label}_cmds.sh"
        move_cmd = f"mv *.RMtable {pipe['run_ops']['file_precursor']}_{rmsynthesis_final_label}.RMtable" # rename the rmtable
        rm_min = pipe["source"]["synth_rm"] - 10
        rm_min = pipe["source"]["synth_rm"] + 10
    cmd = "rmsynth -ascii"
    cmd += f" -rm '{min(rm_min)} {max(rm_max)} 500'" # 500 trials
    cmd += f" -onpulsef '{min(on_pulse)} {max(on_pulse)}'" # for only the on pulse signal
    cmd += f" -onpulsef2 '{min(on_pulse)} {max(on_pulse)}'" # is noise calculation only
    cmd += f" -device {pipe['run_ops']['file_precursor']}_rmsynth_plot.ps/cps" # is the final rm plot
    cmd += f" -device2 {pipe['run_ops']['file_precursor']}_rmsynth_map.ps/cps" # is the rm synthesis map
    cmd += f" -device3 {pipe['run_ops']['file_precursor']}_profile.ps/cps" # is the profile
    with open(myfile, "w+") as f:
        f.write(f"{cmd}\n")
        f.write(f"{move_cmd}\n")


def tofile_defarad(pipe):
    """Defaraday rotates the fits file using RM"""
    myfile = f"{pipe['run_ops']['file_precursor']}_{defarad_label}_cmds.sh"
    cmd = "ppol -TSCR -FSCR"
    cmd += f" -onpulse {min(on_pulse)} {max(on_pulse)}"
    cmd += f" -header 'rm {pipe['source']['rm_synth']}''"
    cmd += " -ext paswing"
    cmd += f" -device {pipe['run_ops']['file_precursor']}_profile.ps/cps" # is the profile
    cmd += f" -device2 {pipe['run_ops']['file_precursor']}_polarimetry_profile.ps/cps" # is the polarimetry profile
    cmd += f" *.debase.gg"
    with open(myfile, "w+") as f:
        f.write(cmd)


def tofile_rvm(pipe):
    """Performs an RVM fit"""
    alpha = pipe["pol"]["alpha"]
    beta = pipe["pol"]["beta"]
    if alpha is None and beta is None: # initial
        trials = 200
        alpha_range = np.array((0, 180))
        beta_range = np.array((-30, 30))
        #Decide the longitude range to fit
        component_min = min(pipe["folds"]["best"]["gfit"]["comp_idx"]["0"]) * 360/pipe["folds"]["best"]["bestprof"]["nbins"]
        component_max = max(pipe["folds"]["best"]["gfit"]["comp_idx"]["0"]) * 360/pipe["folds"]["best"]["bestprof"]["nbins"]
        l_cmd = f" -l {component_min} 1"
        maxdl_cmd = f" -maxdl {component_max - component_min}"
        outfile = f"{pipe['run_ops']['file_precursor']}_{rvmfit_initial_label}.out"
        myfile = f"{pipe['run_ops']['file_precursor']}_{rvmfit_initial_label}_cmds.sh"
    else: #Final
        trials = 400
        alpha_range = np.array((alpha - 20, alpha + 20))
        beta_range = np.array((beta - 10, beta + 10))
        alpha_range.clip(0, 180)
        beta_range.clip(-30, 30) # forcing the range to reasonable values
        l_cmd = f" -l {pipe['pipe']['l0'] - 10}"
        maxdl_cmd = " -maxdl 20"
        outfile = f"{pipe['run_ops']['file_precursor']}_{rvmfit_final_label}.out"
        myfile = f"{pipe['run_ops']['file_precursor']}_{rvmfit_final_label}_cmds.sh"
    cmd = "ppolFit -showwedge"
    cmd += f" -g '{trials} {trials}'"
    cmd += f" -A '{alpha_range[0]} {alpha_range[1]}'" # Alpha range
    cmd += f" -B '{beta_range[0]} {beta_range[1]}'" # Beta range
    cmd += l_cmd # longitude start and step size
    cmd += maxdl_cmd #longitude search range
    cmd += " -best" # return the best fit values
    cmd += f" -device1 {pipe['run_ops']['file_precursor']}_chigrid.ps/cps"
    cmd += f" -device2 {pipe['run_ops']['file_precursor']}_paswing.ps/cps"
    cmd += f" -device1res '900 900'"
    cmd += f" *.paswing"
    cmd += f" > {outfile}" #write to stdout
    with open(myfile, "w+") as f:
        f.write(cmd)


def pulsar_polarimetry_one(pipe):
    """Creates files containing files needed to do an initial RM synthesis run"""
    pipe["folds"]["best"]["gfit"] = auto_gfit(pipe["folds"]["best"]["bestprof"]["profile"]) #gaussian fit the best fold
    tofile_fold_fits_w_dspsr(pipe, kwargs["fits"], f) # Fold using dspsr
    tofile_archive_to_fits(pipe) # Convert from archive to fits file (this needs to be done to get header information)
    tofile_remove_baseline(pipe) # Remove baseline RFI/noise
    tofile_rmsynthesis(pipe) # Run RM synthesis for the first time


def pulsar_polarimetry_two(pipe):
    """Creates files containing files needed to do an initial RM synthesis run"""
    RM, RM_e = read_rmtable(f"mv *.RMtable {pipe['run_ops']['file_precursor']}_{rmsynthesis_initial_label}.RMtable")
    pipe["source"]["synth_rm"] = RM
    pipe["source"]["synth_rm_e"] = RM_e
    tofile_rmsynthesis(pipe)


def puslar_polarimetry_three(pipe):
    """Performs an faraday correction"""
    RM, RM_e = read_rmtable(f"mv *.RMtable {pipe['run_ops']['file_precursor']}_{rmsynthesis_final_label}.RMtable")
    pipe["source"]["synth_rm"] = RM
    pipe["source"]["synth_rm_e"] = RM_e
    tofile_defarad(pipe)


def pulsar_polarimetry_four(pipe):
    """Performs and initial RVM fit"""
    tofile_rvm(pipe)


def pulsar_polarimetry_five(pipe):
    """Performs a final RVM fit"""
    pol = read_rvmfit(f"{pipe['run_ops']['file_precursor']}_{rvmfit_initial_label}.out")
    pipe["pol"]["alpha"] = pol[0]
    pipe["pol"]["beta"] = pol[1]
    pipe["pol"]["l0"] = pol[2]
    pipe["pol"]["pa0"] = pol[3]
    pipe["pol"]["chi"] = pol[4]
    tofile_rvm(pipe)

def pulsar_polarimetry_six(pipe):
    """Reads the final RVM fit file and updates pipe"""
    pol = read_rvmfit(f"{pipe['run_ops']['file_precursor']}_{rvmfit_final_label}.out")
    pipe["pol"]["alpha"] = pol[0]
    pipe["pol"]["beta"] = pol[1]
    pipe["pol"]["l0"] = pol[2]
    pipe["pol"]["pa0"] = pol[3]
    pipe["pol"]["chi"] = pol[4]


def pulsar_polarimetry_main(kwargs):
    pipe = from_yaml(kwags["yaml"])
    if not pipe["completed"]["polarimetry_1"]: #A bunch of stuff + initial RM synthesis
        pulsar_polarimetry_one(pipe)
        pipe["completed"]["polarimetry_1"] = True
    elif not pipe["completed"]["polarimetry_2"]: # Final RM synthesis
        pulsar_polarimetry_two(pipe)
        pipe["completed"]["polarimetry_2"] = True
    elif not pipe["completed"]["polarimetry_3"]: # Defaraday rotation
        pulsar_polarimetry_three(pipe)
        pipe["completed"]["polarimetry_3"] = True
    elif not pipe["completed"]["polarimetry_4"]: # Initial RVM fitting
        pulsar_polarimetry_four(pipe)
        pipe["completed"]["polarimetry_4"] = True
    elif not pipe["completed"]["polarimetry_5"]: # Final RVM fitting
        pulsar_polarimetry_five(pipe)
        pipe["completed"]["polarimetry_5"] = True
    elif not pipe["completed"]["polarimetry_6"]: # Read the final fit
        pulsar_polarimetry_six(pipe)
        pipe["completed"]["polarimetry_6"] = True
    else:
        raise ValueError(f"""Polarimetry has already been completed for this pulsar: {pipe['source']['name']}""")
    dump_to_yaml(pipe, label=kwargs["label"])