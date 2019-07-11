#!/usr/bin/env python3

import os
import glob
import logging
import argparse
import sys
import logging
import data_process_pipeline
from job_submit import submit_slurm

logger = logging.getLogger(__name__)


class run_params_class:
       
    def __init__(self, pointing_dir, cal_id,
                prevbins=None, pulsar=None, obsid=None,
                threshold=10.0, launch_next=False, best_bins=None,
                force_initial=False, loglvl="INFO", mode=None):
        
        self.pointing_dir       = pointing_dir
        self.cal_id             = cal_id
        self.prevbins           = prevbins
        self.pulsar             = pulsar
        self.obsid              = obsid
        self.threshold          = threshold
        self.launch_next        = launch_next
        self.force_initial      = force_initial
        self.loglvl             = loglvl
        self.best_bins          = best_bins        
        self.mode               = mode


        if self.obsid==None or self.pulsar==None:
            mydict = data_process_pipeline.info_from_dir(self.pointing_dir)
        if self.obsid==None:
            self.obsid = mydict["obsid"]
        if self.pulsar==None:
            self.pulsar = mydict["pulsar"]
        

    def set_prevbins(self, prevbins):
        self.prevbins = prevbins
    def set_best_bins(self, bins):
        self.best_bins = bins
    def single_pointing(self):
        #This allows us to handle a single pointing directory easily
        self.pointind_dir=pointing_dir[0] 

#----------------------------------------------------------------------
def bestprof_info(prevbins=None, filename=None):
    #returns a dictionary that includes the relevant information from the .bestprof file
    if filename is not None:
        bestprof_path = filename
    #elif prevbins == None:
    #    bestprof_path = glob.glob("*PSR**bestprof")[0]
    else:
        bestprof_path = glob.glob("*{0}*bestprof".format(prevbins))[0]

    #open the file and read the info into a dictionary
    info_dict = {}
    f = open(bestprof_path, "r")
    lines = f.read()
    lines = lines.split("\n")
    #info:
    info_dict["obsid"] = lines[0].split()[4].split("_")[0]
    info_dict["pulsar"] = lines[1].split()[3].split("_")[1]
    info_dict["nbins"] = lines[9].split()[4]
    info_dict["chi"] = lines[12].split()[4]
    info_dict["sn"] = lines[13].split()[4][2:]
    info_dict["dm"] = lines[14].split()[4]
    info_dict["period"] = lines[15].split()[4] #in ms
    info_dict["period_error"] = lines[15].split()[6]
    f.close()
    return info_dict

#----------------------------------------------------------------------
def submit_to_db(run_params, prof_name):


    mydict = bestprof_info(filename = prof_name)
    ppps = glob.glob("*{0}*.pfd.ps".format(mydict["nbins"]))[0]

    commands = []
    commands.append('submit_to_database.py -o {0} --cal_id {1} -p {2} --bestprof {3} --ppps {4}'.format(run_params.obsid, run_params.cal_id, run_params.pulsar, prof_name, ppps))
    commands.append('echo "submitted profile to database: {0}"'.format(prof_name))

    if run_params.launch_next==True:
        commands.append("data_processing_pipeline.py -d {0} -O {1} -p {2} -o {3} -b {4} -L {5} -m stokes_fold".format(run_params.pointing_dir, run_params.cal_id, run_params.pulsar, run_params.obsid, run_params.best_bins, run_params.loglvl))

    commands.append('echo "Searching for pulsar using the pipeline to test the pipelines effectivness"')
    commands.append('mwa_search_pipeline.py -o {0} -a --search --pulsar {1} -O {2} --code_comment "Known pulsar auto test"'.format(run_params.obsid, run_params.pulsar, run_params.cal_id))

  
    name = "Submit_{0}_{1}".format(run_params.pulsar, run_params.obsid)
    batch_dir = "/group/mwaops/vcs/{0}/batch/".format(run_params.obsid)

    submit_slurm(name, commands,
                 batch_dir=batch_dir,
                 slurm_kwargs={"time": "2:00:00",
                               "nice":"90"},
                 module_list=['mwa_search/{0}'.format("master")],
                 submit=True, vcstools_version="multi-pixel_beamform")

#----------------------------------------------------------------------
def check_conditions(threshold, prevbins):
    
    #returns a dictionary of a bunch of stuff that decides if and how to run prepfold
    info_dict = bestprof_info(prevbins=prevbins)
    condition_dict = {}
    if float(info_dict["sn"]) < threshold:
        condition_dict["sn_good"] = False
        logger.info("Signal to noise ratio of the previous run was below the threshold")
    else:
        condition_dict["sn_good"] = True

    if float(info_dict["chi"]) < 4.0:
        condition_dict["chi_good"] = False
        logger.info("Chi value of the previous run was below 4")
    else:
        condition_dict["chi_good"] = True

    if int(float(info_dict["sn"])) == 0:
        condition_dict["sn_nonzero"] = False
        logger.info("The singal to noise ratio for this file is zero. Using chi for evalutation")
    else:
        condition_dict["sn_nonzero"] = True
    
    if int(info_dict["nbins"]) > int(float(info_dict["period"]))/1000 * 10000: #the 10k is the 10khz time res of MWA
        condition_dict["sampling_good"] = False
        logger.info("The maximum sampling frequency for this pulsar has been reached")
    else:
        condition_dict["sampling_good"] = True


    return condition_dict

#----------------------------------------------------------------------
def get_best_profile(pointing_dir, threshold):

    #find all of the bestprof profiles in the pointing directory
    bestprof_names = glob.glob("*.bestprof")
    if len(bestprof_names)==0:
        logger.error("No bestprofs found in directory! Exiting")
        sys.exit(1)

    #throw all of the information from each bestprof into an array   
    bin_order = []
    sn_order = []
    chi_order = []
    for prof in bestprof_names: 
        prof_info = bestprof_info(filename=prof)
        bin_order.append(prof_info["nbins"])
        sn_order.append(prof_info["sn"])
        chi_order.append(prof_info["chi"])
    bin_order, sn_order, chi_order = zip(*sorted(zip(bin_order, sn_order, chi_order)))
    bin_order = bin_order[::-1]
    sn_order = sn_order[::-1]
    chi_order = chi_order[::-1]

    #now find the one with the most bins that meet the sn and chi conditions
    best_i = None    
    for i,bins in enumerate(bin_order):
        if float(sn_order[i])>=threshold and float(chi_order[i])>=4.0:
            best_i = i
            break
    if best_i is None: 
        logger.info("No profiles fit the threshold parameter")
    
   
    logger.info("Adequate profile found with {0} bins".format(bin_order[best_i])) 
    prof_name = glob.glob("*{0}*.bestprof".format(bin_order[best_i]))[0]
    return prof_name

#----------------------------------------------------------------------
def submit_multifold(run_params, nbins=64):

    for pointing in run_params.pointing_dir:
        #create slurm job:
        commands = []
        #load presto module here because it uses python 2
        commands.append('echo "Folding on known pulsar"'.format(run_params.pulsar))
        commands.append('psrcat -e {0} > {0}.eph'.format(run_params.pulsar))
        commands.append("sed -i '/UNITS           TCB/d' {0}.eph".format(run_params.pulsar))
        commands.append("prepfold -o {0}_{2}_bins -noxwin -nosearch -runavg -noclip -timing {1}.eph -nsub 256 1*fits -n {2}".format(run_params.obsid, run_params.pulsar, nbins))
        commands.append('errorcode=$?')
        commands.append('pulsar={}'.format(run_params.pulsar[1:]))
        pulsar_bash_string = '${pulsar}'
        #Some old ephems don't have the correct ra and dec formating and
        #causes an error with -timing but not -psr
        commands.append('if [ "$errorcode" != "0" ]; then')
        commands.append('   echo "Folding using the -psr option"')
        commands.append('   prepfold -o {0}_{2}_bins -noxwin -nosearch -runavg -noclip -psr {1} -nsub 256 1*fits -n {2}'.format(run_params.obsid, run_params.pulsar, nbins))
        commands.append('   pulsar={}'.format(run_params.pulsar))
        commands.append('fi')
        commands.append('rm {0}.eph'.format(run_params.pulsar))

        #TODO: finish this
        commands.append('')


        name = "binfinder_{0}_{1}".format(run_params.pulsar, nbins)
        batch_dir = "/group/mwaops/vcs/{0}/batch/".format(run_params.obsid)
        submit_slurm(name, commands,
                    batch_dir=batch_dir,
                    slurm_kwargs={"time": "2:00:00"},
                    module_list=['mwa_search/k_smith',
                                'presto/no-python'],
                    submit=True, vcstools_version="multi-pixel_beamform")





def submit_prepfold(run_params, nbins=32, finish=False, no_repeat=False):

    if nbins is not int:
        nbins = int(float(nbins))

    logger.info("Submitting job for {0} bins".format(nbins))
    #create slurm job:
    commands = []
    #load presto module here because it uses python 2
    commands.append('echo "Folding on known pulsar"'.format(run_params.pulsar))
    commands.append('psrcat -e {0} > {0}.eph'.format(run_params.pulsar))
    commands.append("sed -i '/UNITS           TCB/d' {0}.eph".format(run_params.pulsar))
    commands.append("prepfold -o {0}_{2}_bins -noxwin -nosearch -runavg -noclip -timing {1}.eph -nsub 256 1*fits -n {2}".format(run_params.obsid, run_params.pulsar, nbins))
    commands.append('errorcode=$?')
    commands.append('pulsar={}'.format(run_params.pulsar[1:]))
    pulsar_bash_string = '${pulsar}'
    #Some old ephems don't have the correct ra and dec formating and
    #causes an error with -timing but not -psr
    commands.append('if [ "$errorcode" != "0" ]; then')
    commands.append('   echo "Folding using the -psr option"')
    commands.append('   prepfold -o {0}_{2}_bins -noxwin -nosearch -runavg -noclip -psr {1} -nsub 256 1*fits -n {2}'.format(run_params.obsid, run_params.pulsar, nbins))
    commands.append('   pulsar={}'.format(run_params.pulsar))
    commands.append('fi')
    commands.append('rm {0}.eph'.format(run_params.pulsar))

    if finish==False:
        #Rerun this script
        commands.append('echo "Running script again. Passing prevbins = {0}"'.format(nbins))
        commands.append('binfinder.py -d {0} -t {1} -O {2} -L {3} --prevbins {4} -m f'.format(run_params.pointing_dir, run_params.threshold, run_params.cal_id, run_params.loglvl, nbins))
    elif no_repeat==True:
        #This is used by the 'check' or 'multi' mode
        if run_params.launch_next==True:
            commands.append("data_processing_pipeline.py -m b -d {0} -o {1} -O {2} -p {3} -t {4} -L {5}".format(run_params.pointing_dir, run_params.obsid, ru_params.cal_id, run_params.pulsar, run_params.threshold, run_params.loglvl))
    else:
        #Run again only once and without prepfold
        commands.append('echo "Running script again without folding. Passing prevbins = {0}"'.format(nbins))
        commands.append('binfinder.py -d {0} -t {1} -O {2} -L {3} --prevbins {4} -m e'.format(run_params.pointing_dir, run_params.threshold, run_params.cal_id, run_params.loglvl, nbins))
    


    name = "binfinder_{0}_{1}".format(run_params.pulsar, nbins)
    batch_dir = "/group/mwaops/vcs/{0}/batch/".format(run_params.obsid)
    submit_slurm(name, commands,
                batch_dir=batch_dir,
                slurm_kwargs={"time": "2:00:00"},
                module_list=['mwa_search/k_smith',
                            'presto/no-python'],
                submit=True, vcstools_version="multi-pixel_beamform")
    logger.info("Job successfully submitted")

#----------------------------------------------------------------------
def iterate_bins(run_params):

    #If this is not the first run:
    if run_params.prevbins is not None:
        #Ensuring prevbins is in the correct int format
        run_params.set_prevbins(int(float(run_params.prevbins)))
        #get information of the previous run
        info_dict = bestprof_info(prevbins=run_params.prevbins)
    
        #Check to see if SN and chi are above threshold
        #If continue == True, prepfold will run again
        cont = False
        condition_dict = check_conditions(run_params.threshold, run_params.prevbins)
        if condition_dict["sn_nonzero"]==False:
            if condition_dict["sn_good"]==False:
                cont = True
        elif condition_dict["chi_good"]==False:
            cont = True    


        finish=False
        if cont==True:
            #Choosing the number of bins to use
            nbins = int(float(info_dict["nbins"]))/2
            while nbins>int(float(info_dict["period"])/1000 * 10000):
                logger.info("Time sampling limit reached. Bins will be reduced")
                nbins = nbins/2
                if nbins<=32:
                    break
            if nbins<=32:
                logger.warn("Minimum number of bins hit. Script will run once more") 
                finish=True

            #create slurm job:
            submit_prepfold(run_params, nbins=nbins, finish=finish)

        else:
            #Threshold reached, find the best profile and submit it to DB
            logger.info("Signal to noise or Chi above threshold at {0} bins".format(info_dict["nbins"]))
            logger.info("Finding best profile in directory and submitting to database")
            bestprof = get_best_profile(run_params.pointing_dir, run_params.threshold)
            if bestprof==None:
                logger.info("No profiles found with threshold parameters. Attempting threshold=5.0")
                bestprof = get_best_profile(run_params.pointing_dir, 5.0)
                if bestprof==None:
                    logger.info("Non-detection on pulsar {0}".format(run_params.pulsar))
                    logger.info("Exiting....")
                    sys.exit(0)
                    
            run_params.set_best_bins(int(float(info_dict["nbins"])))
            submit_to_db(run_params, bestprof)

    else:
        #This is the first run
        submit_prepfold(run_params, nbins=1024)        
            

#----------------------------------------------------------------------
if __name__ == '__main__':
    #dictionary for choosing log-levels
    loglevels = dict(DEBUG=logging.DEBUG,
                    INFO=logging.INFO,
                    WARNING=logging.WARNING,
                    ERROR = logging.ERROR)

    #Arguments
    parser = argparse.ArgumentParser(description="A script that handles pulsar folding operations")

    required = parser.add_argument_group("Required Inputs:")
    required.add_argument("-d", "--pointing_dir", nargs="+", help="Pointing directory(s) that contains\
                            the spliced fits files. If mode='m', more than one argument may be supplied.")
    required.add_argument("-O", "--cal_id", type=str, help="The Obs ID of the calibrator")
    required.add_argument("-m", "--mode", type=str, help="""The mode in which to run binfinder\n\
                            'c' - Run on a small number of bins. Intended as an initial check\n\
                            'f' - Finds an adequate number of bins to fold on\n\
                            'e' - Folds once on the default number of bins and submits the result to\
                            the database. NOT RECOMMENDED FOR MANUAL INPUT\n\
                            'm' - Use this mode if this is part of a multi-beam observation. This will\
                            find the best detection, if any, out of many pointings\n\
                            'b' - Finds the best detection out of a set of pointing directories""")
    required.add_argument("-p", "--pulsar", type=str, default=None, help="The name of the pulsar. eg. J2241-5236")
 

    other = parser.add_argument_group("Other Options:")
    other.add_argument("-t", "--threshold", type=float, default=10.0, help="The signal to noise threshold to stop at. Default = 10.0")
    other.add_argument("-o", "--obsid", type=str, default=None, help="The observation ID")
    other.add_argument("-L", "--loglvl", type=str, default="INFO", help="Logger verbosity level. Default: INFO", choices=loglevels.keys())
    other.add_argument("--force_initial", action="store_true", help="Use this tag to force the script to treat this as the first run.")
    other.add_argument("--launch_next", action="store_false", help="Use this tag to tell binfinder to launch the next step in the data processing pipleline when finished")

    non_user = parser.add_argument_group("Non-User input Options:")
    non_user.add_argument("--prevbins", type=int, default=None, help="The number of bins used in prepfold on the previous run. Not necessary for initial runs")

    args = parser.parse_args()

    logger.setLevel(loglevels[args.loglvl])
    ch = logging.StreamHandler()
    ch.setLevel(loglevels[args.loglvl])
    formatter = logging.Formatter('%(asctime)s  %(filename)s  %(name)s  %(lineno)-4d  %(levelname)-9s :: %(message)s')
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    #Checking required inputs
    if args.pointing_dir == None:
        logger.error("No pointing directory supplied. Please specify the pointing directory path and rerun")
        sys.exit(1)
    elif args.cal_id == None:
        logger.error("No calibrator ID supplied. Please input a cal ID and rerun")
        sys.exit(1)
    elif args.pulsar == None:
        logger.error("No pulsar name supplied. Please input a pulsar and rerun")
        sys.exit(1)
    elif args.mode == None:
        logger.error("Mode not supplied. Please input a mode from the list of modes and rerun")
    """
    NOTE: for some reason, you need to run prepfold from the directory it outputs to if you want it to properly make an image. The script will make this work regardless by using os.chdir
    """
    os.chdir(args.pointing_dir)
    
    run_params = run_params_class(args.pointing_dir, args.cal_id,
                    prevbins=args.prevbins, pulsar=args.pulsar,
                    obsid=args.obsid, threshold=args.threshold, 
                    launch_next=args.launch_next,
                    force_initial=args.force_initial, mode=args.mode,
                    loglvl=args.loglvl)

    if run_params.mode is not 'm' and run_params.mode is not 'b':
        #convert array to str
        run_params.single_pointing()



    if run_params.mode=="e":
        logger.info("Submitting to database")
        prof_name = get_best_profile(run_params.pointing_dir, run_params.threshold)
        if prof_name==None:
            logger.info("No profile found for input threshold. Trying again with Threshold=5.0")
            prof_name = get_best_profile(run_params.pointing_dir, 5.0)
        if prof_name==None:
            logger.info("Non detection - no adequate profiles. Exiting....")
            sys.exit(0)
        mydict = bestprof_info(filename=prof_name)
        run_params.set_best_bins(int(float(mydict["nbins"])))
        submit_to_db(run_params, prof_name)
        exit(0)
    elif run_params.mode=="f":
        iterate_bins(run_params) 
    elif run_params.mode=="c" or run_params.mode=="m":
        submit_prepfold(run_params, nbins=64, no_repeat=True)
    else:
        logger.error("Unreognized mode. Please run again with a proper mode selected.")
