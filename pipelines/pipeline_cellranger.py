##############################################################################
#
#   Kennedy Institute of Rheumatology
#
#   $Id$
#
#   Copyright (C) 2018 Stephen Sansom
#
#   This program is free software; you can redistribute it and/or
#   modify it under the terms of the GNU General Public License
#   as published by the Free Software Foundation; either version 2
#   of the License, or (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program; if not, write to the Free Software
#   Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
###############################################################################

"""===========================
Pipeline Cellranger
===========================

:Author: Sansom lab
:Release: $Id$
:Date: |today|
:Tags: Python

Overview
========

This pipeline performs the following functions:

* Alignment and quantitation (using cellranger count)
* QC of aligned reads (picard MarkDuplicates)
* Sample aggregation (cellranger aggr)
* Cleaning of aggregated matrices to exclude potential barcode hopping events
* Random down-sampling and arbitrary sub-setting of aggregated count matrices

Usage
=====

See :ref:`PipelineSettingUp` and :ref:`PipelineRunning` on general
information how to use CGAT pipelines.

Configuration
------------

The pipeline requires a configured :file:`pipeline.yml` file.

Default configuration files can be generated by executing:

   python <srcdir>/pipeline_cellranger.py config


Input files
-----------

The pipeline can be run from FASTQ or from the outputs of
existing "cellranger count" runs:

(A) If starting from FASTQ files:

The pipeline expects a file describing each sample to be present
in a "data.dir" subfolder.

The sample file should contain the path(s) to the output(s) of
"cellranger mkfastq". If multiple sequencing runs were performed,
specify one path per line.

The name of the sample file must follow the a four-part syntax:
"sample_name.ncells.batch.sample"

Where:
1. "sample_name" is a user specified sample name;
2. "ncells" is an integer giving the number of expected cells;
3. "batch" is the sample batch. Libraries sequenced on the same lane(s)
should be assigned the same batch. This is used to filter out cells
which may be exposed to index hopping.
4. ".sample" is a required suffix.

e.g.

$ cat data.dir/donor1_butyrate.1000.1.sample
/gfs/work/ssansom/10x/holm_butyrate/cellranger/data.dir/392850_21
/gfs/work/ssansom/10x/holm_butyrate/cellranger/data.dir/397106_21

(B) If starting from the output of cellranger count:

Two files are required:
sample.information.txt: containing "sample_id", "agg_id" and "seq_id" coloumns/
cellranger.aggr.specification.csv: the specification file cellranger aggr.


Dependencies
------------

This pipeline requires:
* cgat-core: https://github.com/cgat-developers/cgat-core
* cellranger: https://support.10xgenomics.com/single-cell-gene-expression/
* picard tools (optional): https://broadinstitute.github.io/picard/
* R & various packages.


Pipeline output
===============

The pipeline returns:
* the output of cellranger count (if run from FASTQs)
* the output of cellranger aggr
* optionally "cleaned" (index hopping issue)
  and random down-sampled count matrices.

The outputs are compatible with pipeline_seurat.py.

Code
====

"""
from ruffus import *
from pathlib import Path
import sys
import os
import glob
import sqlite3
import cgatcore.experiment as E
from cgatcore import pipeline as P
import cgatcore.iotools as IOTools
import pandas as pd

# -------------------------- < parse parameters > --------------------------- #

# load options from the config file
PARAMS = P.get_parameters(
    ["%s/pipeline.yml" % os.path.splitext(__file__)[0],
     "../pipeline.yml",
     "pipeline.yml"])

# set the location of the tenx code directory
if "tenx_dir" not in PARAMS.keys():
    PARAMS["tenx_dir"] = Path(__file__).parents[1]
else:
    raise ValueError("Could not set the location of the tenx code directory")


# ----------------------- < pipeline configuration > ------------------------ #

# handle pipeline configuration
if len(sys.argv) > 1:
        if(sys.argv[1] == "config") and __name__ == "__main__":
                    sys.exit(P.main(sys.argv))


# ########################################################################### #
# ########### Check sample files and prepare Sample table ################### #
# ########################################################################### #


def sample_information(check_only=True):
    '''Check the input samples.

       The sample table is returned as a pandas data frame.
    '''
    sample_files = glob.glob(os.path.join("data.dir", "*.sample"))

    # Check we have input
    if len(sample_files) == 0:
            raise ValueError("No input files detected")

    # User-defined titles for '_'-separated metadata encoded in file name
    name_field_titles = PARAMS["name_field_titles"].split(",")
    # Add required '.'-separated metadata fields encoded in file name
    sample_titles = name_field_titles + ["ncells", "seq_id", "file"]

    samples = {}

    # Process file names
    for sample_file in sample_files:
        # We expect 4 '.'-delimited sections to the sample filename:
        # <name_field_titles>.<ncells>.<seq_batch>.sample
        sample_basename = os.path.basename(sample_file)
        sample_name_sections = sample_basename.split(".")
        if len(sample_name_sections) != 4:
            raise ValueError(
                "%(sample_basename)s does not have the expected"
                " number of dot-separated sections. Format expected is:"
                " sample_name_fields.ncells.seq_batch.sample, e.g. "
                " donor1_stim_R1.2000.1.sample " % locals())
        # The first field encodes '_'-delimited metadata for each sample
        sample_name = sample_name_sections[0]
        if "sample_id" in sample_name:
            raise ValueError('The sample names cannot contain "sample_id"')

        if len(sample_name.split("_")) != len(name_field_titles):
            raise ValueError(
                "%(sample_name)s does not have the expected"
                " number of name fields (%(name_field_titles)s)."
                " Note that name fields must be separated with"
                " underscores" % locals())

        # Combine the metadata as a list
        sample_fields = sample_name.split("_") + \
            sample_name_sections[1:3] + [sample_file]

        # Add the list of metadata to the dictionary of samples
        # under the appropriate key
        samples[sample_name] = dict(zip(sample_titles, sample_fields))

    if check_only:
        return

    sample_table = pd.DataFrame(samples).transpose()
    sample_table["library_id"] = sample_table.index

    if PARAMS["sample_fields"] is None:
        sample_table["sample_id"] = sample_table["library_id"]
    else:
        sample_fields = PARAMS["sample_fields"].split(",")
        sample_table["sample_id"] = ["_".join([str(y) for y in x])
                                     for x in
                                     sample_table[sample_fields].values]

    sample_table["molecule_h5"] = [x + "-count/outs/molecule_info.h5"
                                   for x in sample_table["library_id"].values]

    sample_table["agg_id"] = [str(x) for x in
                              list(range(1, len(sample_table.index)+1))]

    return sample_table


@active_if(PARAMS["input"] == "mkfastq")
@files(None,
       "data.dir/input.check.sentinel")
def checkMkfastqInputs(infile, outfile):
    '''Check mkfastq input .sample files'''

    sample_information()

    IOTools.touch_file(outfile)

# ########################################################################### #
# ######################### cellranger count ################################ #
# ########################################################################### #


@active_if(PARAMS["input"] == "mkfastq")
@follows(checkMkfastqInputs)
@transform("data.dir/*.sample",
           regex(r".*/([^.]*).*.sample"),
           r"\1-count/cellranger.count.sentinel")
def cellrangerCount(infile, outfile):
    '''
    Execute the cell ranger pipleline for all samples.
    '''
    # set key parameters
    transcriptome = PARAMS["cellranger_transcriptome"]

    if transcriptome is None:
        raise ValueError('"cellranger_transcriptome" parameter not set'
                         ' in file "pipeline.yml"')

    if not os.path.exists(transcriptome):
        raise ValueError('The specified "cellranger_transcriptome"'
                         ' file does not exist')

    memory = PARAMS["cellranger_memory"]
    job_threads = PARAMS["cellranger_threads"]
    mem_per_core = int(float(memory) / job_threads)  # round down
    job_memory = str(mem_per_core) + "M"

    # cellranger expects memory in GB
    cellranger_memory = str(int((mem_per_core * job_threads)/1000) - 2)

    # parse the sample name and expected cell number
    library_id, cellnumber, batch, trash = os.path.basename(infile).split(".")

    # build lists of the sample files
    seq_folders = []
    sample_ids = []

    # Parse the list of sequencing runs (i.e., paths) for the sample
    with open(infile, "r") as sample_list:
        for line in sample_list:
            seq_folder_path = line.strip()
            if seq_folder_path != "":
                seq_folders.append(seq_folder_path)
                sample_ids.append(os.path.basename(seq_folder_path))

    input_fastqs = ",".join(seq_folders)
    input_samples = ",".join(sample_ids)

    id_tag = library_id + "-count"

    log_file = id_tag + ".log"

    statement = (
        '''cellranger count
                   --id %(id_tag)s
                   --fastqs %(input_fastqs)s
                   --sample %(input_samples)s
                   --transcriptome %(transcriptome)s
                   --expect-cells %(cellnumber)s
                   --chemistry %(cellranger_chemistry)s
                   --jobmode=local
                   --localcores %(job_threads)s
                   --localmem %(cellranger_memory)s
                   --nopreflight
            &> %(log_file)s
        ''')

    P.run(statement)

    IOTools.touch_file(outfile)


@active_if(PARAMS["input"] == "mkfastq")
@transform(cellrangerCount,
           regex(r"(.*)-count/cellranger.count.sentinel"),
           r"\1-count/cellranger_metrics_summary.txt")
def reformatCellrangerCountMetrics(infile, outfile):
    '''
    Parse the cellranger count summary metrics into a tabular format.
    '''

    summary = os.path.join(os.path.dirname(outfile),
                           "outs/metrics_summary.csv")

    # read in csv taking care of comma separated thousands
    data = pd.read_csv(summary, thousands=',')

    data.columns = [x.replace(" ", "_") for x in data.columns]

    # deal with percentages
    new_col_names = []
    for col in data.columns:
        tmp = data.ix[0][col]
        if isinstance(tmp, str):
            if tmp.endswith("%"):
                new_col_names.append(col + "_pct")
                data.set_value(0, col, tmp[:-1])
        else:
            new_col_names.append(col)

    data.columns = new_col_names

    data.to_csv(outfile, sep="\t", index=False)


@active_if(PARAMS["input"] == "mkfastq")
@merge(reformatCellrangerCountMetrics,
       "count_stats.load")
def loadCellrangerCountMetrics(infiles, outfile):
    '''
    load the summary statistics for each run into a csvdb file
    '''

    P.concatenate_and_load(
        infiles, outfile,
        regex_filename="(.*)-count/.*.txt",
        has_titles=True,
        options="",
        cat="sample")


@active_if(PARAMS["input"] == "mkfastq")
@transform(cellrangerCount,
           regex(r"(.*)-count/cellranger.count.sentinel"),
           r"\1-count/callCells.txt.gz")
def callCells(infile, outfile):
    '''
    Call cells using a range of methods for each 10x sample separately.
    '''

    transcriptome = PARAMS["cellranger_transcriptome"]

    genome = os.path.basename(transcriptome).split("-")[2]
    matrixpath = os.path.join(os.path.dirname(outfile), "outs", "raw_gene_bc_matrices", genome)

    cellcalling_methods = ",".join(PARAMS["cellcalling_methods"])

    emptydropslower = PARAMS["cellcalling_emptydropslower"]
    emptydropsniters = PARAMS["cellcalling_emptydropsniters"]

    if PARAMS["cellcalling_emptydropsambient"]:
        emptydropsambient = "--emptydropsambient"
    else:
        emptydropsambient = ""

    if PARAMS["cellcalling_emptydropsignore"] == "None":
        emptydropsignore = ""
    else:
        emptydropsignore = "--emptydropsignore=%s" % (PARAMS["cellcalling_emptydropsignore"])

    if PARAMS["cellcalling_emptydropsretain"] == "None":
        emptydropsretain = ""
    else:
        emptydropsretain = "--emptydropsretain=%s" % (PARAMS["cellcalling_emptydropsretain"])

    emptydropsfdr = PARAMS["cellcalling_emptydropsfdr"]
    job_threads = PARAMS["cellcalling_threads"]

    # Build the path to the log file
    log_file = P.snip(outfile, ".txt.gz") + ".log"

    statement = '''Rscript %(tenx_dir)s/R/cellranger_callCells.R
                   --matrixpath=%(matrixpath)s
                   --methods=%(cellcalling_methods)s
                   --outfile=%(outfile)s
                   --emptydropslower=%(emptydropslower)s
                   --emptydropsniters=%(emptydropsniters)s
                   %(emptydropsambient)s
                   %(emptydropsignore)s
                   %(emptydropsretain)s
                   --emptydropsfdr=%(emptydropsfdr)s
                   --threads=%(job_threads)s
                   &> %(log_file)s
                '''

    P.run(statement)


@active_if(PARAMS["input"] == "mkfastq")
@merge(callCells,
       "cellranger_cellcalling.load")
def loadCellCalls(infiles, outfile):
    '''
    Load cell calls into the database.
    '''

    P.concatenate_and_load(
        infiles, outfile,
        regex_filename="(.*)-count/.*.txt.gz",
        has_titles=True,
        options="--add-index=sample",
        cat="sample")


@active_if(PARAMS["input"] == "mkfastq")
@transform(loadCellCalls,
           regex(r"(.+).load"),
           r"\1.pdf")
def plotCellCalls(infile, outfile):
    '''
    Plot count of cells called by each method.
    '''

    tablename = P.snip(infile, ".load")

    cellcalling_methods = ",".join(PARAMS["cellcalling_methods"])

    # Build the path to the log file
    log_file = P.snip(outfile, ".pdf") + ".log"

    statement = '''Rscript %(tenx_dir)s/R/cellranger_plotCellCalls.R
                   --tablename=%(tablename)s
                   --methods=%(cellcalling_methods)s
                   --outfile=%(outfile)s
                   &> %(log_file)s
                '''

    P.run(statement)


@active_if(PARAMS["input"] == "mkfastq")
@files(loadCellCalls,
           r"whitelist.txt.gz")
def whiteListCells(infile, outfile):
    '''
    White list cells called by one or more methods.
    '''

    tablename = P.snip(infile, ".load")

    cellcalling_methods = ",".join(PARAMS["cellcalling_methods"])

    # Build the path to the log file
    log_file = P.snip(outfile, ".txt.gz") + ".log"

    statement = '''Rscript %(tenx_dir)s/R/cellranger_whiteListCells.R
                   --tablename=%(tablename)s
                   --methods=%(cellcalling_methods)s
                   --outfile=%(outfile)s
                   &> %(log_file)s
                '''

    P.run(statement)


@active_if(PARAMS["input"] == "mkfastq")
@transform(cellrangerCount,
           regex(r"(.*)-count/cellranger.count.sentinel"),
           r"\1-count/cellranger.raw.qc.txt")
def rawQcMetricsPerBarcode(infile, outfile):
    '''
    Compute the total UMI, rank, mitochondrial UMI for each barcode.
    Write the metrics to a text file later uploaded to the sqlite database.
    '''

    transcriptome = PARAMS["cellranger_transcriptome"]

    # Build the path to the raw UMI count matrix
    genome = os.path.basename(transcriptome).split("-")[2]
    matrixpath = os.path.join(os.path.dirname(outfile), "outs", "raw_gene_bc_matrices", genome)

    # Build the path to the GTF file used by CellRanger
    gtf = os.path.join(transcriptome, "genes", "genes.gtf")

    # Build the path to the log file
    log_file = P.snip(outfile, ".txt") + ".log"

    statement = '''Rscript %(tenx_dir)s/R/cellranger_rawQcMetrics.R
                   --matrixpath=%(matrixpath)s
                   --gtf=%(gtf)s
                   --outfile=%(outfile)s
                   &> %(log_file)s
                '''

    P.run(statement)


@active_if(PARAMS["input"] == "mkfastq")
@files(rawQcMetricsPerBarcode,
       "cellranger_raw_barcode_metrics.load")
def loadRawQcMetricsPerBarcode(infiles, outfile):
    '''
    load the total UMI and barcode rank into a sqlite database
    '''

    P.concatenate_and_load(
        infiles, outfile,
        regex_filename="(.*)-count/.*.txt",
        has_titles=True,
        options="",
        cat="sample")


@active_if(PARAMS["input"] == "mkfastq")
@follows(mkdir("qc.dir"))
@transform(loadRawQcMetricsPerBarcode,
       regex(r"(.*).load"),
       r"qc.dir/\1.umi_rank.pdf")
def plotUmiRankPerBarcodePerSample(infile, outfile):
    '''
    plot the total UMI and barcode for all samples in the experiment
    '''

    tablename = P.snip(infile, ".load")

    # Build the path to the log file
    log_file = P.snip(outfile, ".pdf") + ".log"

    statement = '''Rscript %(tenx_dir)s/R/cellranger_plotUmiRank.R
                   --tablename=%(tablename)s
                   --outfile=%(outfile)s
                   &> %(log_file)s
                '''

    P.run(statement)


@active_if(PARAMS["input"] == "mkfastq")
@follows(mkdir("qc.dir"))
@transform(loadRawQcMetricsPerBarcode,
       regex(r"(.*).load"),
       r"qc.dir/\1.umi_frequency.pdf")
def plotUmiFrequencyPerSample(infile, outfile):
    '''
    plot the total UMI and barcode for all samples in the experiment
    '''

    tablename = P.snip(infile, ".load")

    # Build the path to the log file
    log_file = P.snip(outfile, ".pdf") + ".log"

    statement = '''Rscript %(tenx_dir)s/R/cellranger_PlotUmiFrequency.R
                   --tablename=%(tablename)s
                   --outfile=%(outfile)s
                   &> %(log_file)s
                '''

    P.run(statement)


@active_if(PARAMS["input"] == "mkfastq")
@follows(mkdir("qc.dir"))
@transform(loadRawQcMetricsPerBarcode,
       regex(r"(.*).load"),
       r"qc.dir/\1.umi_mitochondrial.pdf")
def plotUmiMitochondrialPerSample(infile, outfile):
    '''
    plot the total UMI and barcode for all samples in the experiment
    '''

    tablename = P.snip(infile, ".load")

    # Build the path to the log file
    log_file = P.snip(outfile, ".pdf") + ".log"

    statement = '''Rscript %(tenx_dir)s/R/cellranger_plotUmiMitochondrial.R
                   --tablename=%(tablename)s
                   --outfile=%(outfile)s
                   &> %(log_file)s
                '''

    P.run(statement)


# ########################################################################### #
# ############## calculate duplication metrics (picard) ##################### #
# ########################################################################### #

PICARD_THREADS = PARAMS["picard_threads"]
PICARD_MEMORY = str(
    int(PARAMS["picard_total_mb_memory"]) // int(PICARD_THREADS)
    ) + "M"


@active_if(PARAMS["input"] == "mkfastq")
@transform(cellrangerCount,
           regex(r"(.*)-count/cellranger.count.sentinel"),
           r"\1-count/picard_duplication_metrics.txt")
def picardMarkDuplicates(infile, outfile):
    '''
    Yield duplication metrics using Picard Tools.
    '''

    out_dir = os.path.dirname(outfile)

    bam_in = os.path.join(os.path.dirname(outfile),
                          "outs/possorted_genome_bam.bam")

    base_bam = 'marked_duplicates.bam'
    base_metrics = os.path.basename(outfile)

    picard_options = PARAMS["picard_markduplicate_options"]
    barcode_tag = PARAMS["picard_barcode_tag"]
    read_one_barcode_tag = PARAMS["picard_read_one_barcode_tag"]
    read_two_barcode_tag = PARAMS["picard_read_two_barcode_tag"]
    validation_stringency = PARAMS["picard_validation_stringency"]

    job_threads = PICARD_THREADS
    job_memory = PICARD_MEMORY

    local_tmpdir = P.get_temp_dir()

    statement = '''picard_out=`mktemp -d -p %(local_tmpdir)s`;
                   MarkDuplicates
                   I=%(bam_in)s
                   O=${picard_out}/%(base_bam)s
                   M=${picard_out}/%(base_metrics)s
                   BARCODE_TAG=%(barcode_tag)s
                   READ_ONE_BARCODE_TAG=%(read_one_barcode_tag)s
                   READ_TWO_BARCODE_TAG=%(read_two_barcode_tag)s
                   VALIDATION_STRINGENCY=%(validation_stringency)s
                   %(picard_options)s;
                   grep . ${picard_out}/%(base_metrics)s
                   | grep -v "#"
                   | head -n2
                   > %(outfile)s;
                   rm -rv ${picard_out}
                '''

    P.run(statement)


@active_if(PARAMS["input"] == "mkfastq")
@merge(picardMarkDuplicates,
       "duplication_metrics.load")
def loadDuplicationMetrics(infiles, outfile):
    '''
    Import duplication metrics into project database.
    '''

    P.concatenate_and_load(
        infiles, outfile,
        regex_filename="(.*)-count/.*.txt",
        has_titles=True,
        options="",
        cat="sample")


# --------------------- < optional metrics target > ------------------------ #

@active_if(PARAMS["input"] == "mkfastq")
@merge([loadCellrangerCountMetrics,
        loadDuplicationMetrics,
        loadRawQcMetricsPerBarcode],
        "metrics.sentinel")
def metrics(infiles, outfile):
    '''
    Intermediate target to run metrics tasks.
    '''

    IOTools.touch_file(outfile)


@active_if(PARAMS["input"] == "mkfastq")
@merge([plotUmiRankPerBarcodePerSample,
        plotUmiFrequencyPerSample,
        plotUmiMitochondrialPerSample],
        "plotMetrics.sentinel")
def plotMetrics(infile, outfile):
    '''
    Intermediate target to plot metrics.
    '''

    IOTools.touch_file(outfile)


@follows(cellrangerCount)
@files(None, "sample.information.txt")
def writeSampleInformation(infile, outfile):
    '''
    Write out the sample information table.
    '''

    sample_table = sample_information(check_only=False)

    sample_table.to_csv(outfile, sep="\t", index=False)


# ########################################################################### #
# ###################### Collect sample information  ######################## #
# ########################################################################### #

if PARAMS["input"] == "mkfastq":
    collectSampleInformation = writeSampleInformation

elif PARAMS["input"] == "count":
    collectSampleInformation = "sample.information.txt"

else:
    raise ValueError('Input type must be either "mkfastq"'
                     'or "count"')


# ########################################################################### #
# ######################### cellranger aggr ################################# #
# ########################################################################### #

@files(collectSampleInformation,
       "aggr.specification.csv")
def cellrangerAggrCsv(infile, outfile):
    '''
    Generate the specification file for cellranger aggr

    Writes a csv files specifying the list of "cellranger count"
    output files to aggregate.
    '''

    out_dir = os.path.dirname(outfile)
    sample_table = pd.read_csv(infile, sep="\t")
    aggr_spec = sample_table[["library_id", "molecule_h5"]]

    aggr_spec.to_csv(outfile, index=False)


@files(cellrangerAggrCsv,
       "all-aggr/cellranger.aggr.sentinel")
def cellrangerAggr(infile, outfile):
    '''
    Run cellranger aggr to combine samples.

    The normalization mode can be specified in the pipeline.yml file.
    '''

    id_tag = os.path.dirname(outfile)

    if PARAMS["aggr_options"] is None:
        options = ""
    else:
        options = "--options=" + PARAMS["aggr_options"]

    memory = PARAMS["cellranger_memory"]
    job_threads = PARAMS["cellranger_threads"]
    mem_per_core = int(float(memory) / job_threads)
    job_memory = str(mem_per_core) + "M"

    # cellranger expects memory in GB
    cellranger_memory = str(int((mem_per_core * job_threads) / 1000) - 2)

    log_file = id_tag + ".log"

    statement = '''cellranger aggr
                   --id=%(id_tag)s
                   --csv=%(infile)s
                   --jobmode=local
                   --normalize=%(aggr_normalize)s
                   %(options)s
                   --localcores=%(job_threads)s
                   --localmem=%(cellranger_memory)s
                   &> %(log_file)s
                '''

    P.run(statement)

    IOTools.touch_file(outfile)


# ########################################################################### #
# ################### post-process cellranger matrices  ##################### #
# ########################################################################### #

@follows(mkdir("all-processed.dir"))
@transform(cellrangerAggr,
           regex(r"all-aggr/.*"),
           add_inputs(collectSampleInformation),
           r"all-processed.dir/postprocess.sentinel")
def postprocessAggrMatrix(infiles, outfile):
    '''
    Post-process the cellranger aggr count matrix.

    Batch, sample_name and aggregation ID metadata are added.

    Optionally cells with barcodes shared (within sequencing batch)
    between samples can be removed (known index hopping on Illumina 4000).
    '''

    infile = infiles[0]

    sample_table = infiles[1]

    agg_dir = os.path.dirname(infile)
    out_dir = os.path.dirname(outfile)

    # Clean barcode hopping
    if PARAMS["postprocess_barcodes"]:
        hopping = "--hopping"
    else:
        hopping = ""

    # Additional options
    options = PARAMS["postprocess_options"]

    mexdir = PARAMS["postprocess_mexdir"]

    if mexdir is None:
        raise ValueError('"postprocess_mexdir" parameter not set'
                         ' in file "pipeline.yml"')

    tenxdir = os.path.join(agg_dir, mexdir)
    if not os.path.exists(tenxdir):
        raise ValueError('The specified "postprocess_mexdir"'
                         ' directory does not exist in directory ' + agg_dir)

    job_memory = PARAMS["postprocess_memory"]

    blacklist = PARAMS["postprocess_blacklist"]

    log_file = outfile.replace(".sentinel", ".log")

    statement = '''Rscript %(tenx_dir)s/R/cellranger_postprocessAggrMatrix.R
                   --tenxdir=%(tenxdir)s
                   --sampletable=%(sample_table)s
                   --samplenamefields=%(name_field_titles)s
                   --downsample=no
                   %(hopping)s
                   --blacklist=%(blacklist)s
                   %(options)s
                   --outdir=%(out_dir)s
                   &> %(log_file)s
                '''

    P.run(statement)

    IOTools.touch_file(outfile)


@follows(mkdir("datasets.dir"))
@transform(postprocessAggrMatrix,
           regex(r".*/postprocess.sentinel"),
           add_inputs(collectSampleInformation),
           "datasets.dir/subsetAndDownsample.sentinel")
def subsetAndDownsample(infiles, outfile):
    '''
    Generate datasets that include subsets of the 10x samples.

    Optionally downsample UMI counts to normalise between samples.
    '''

    agg_matrix_dir = os.path.join(os.path.dirname(infiles[0]),
                                  "agg.processed.dir")

    sample_table = pd.read_csv(infiles[1], sep="\t")

    subsets = [k.split("_", 1)[1] for k in PARAMS.keys()
               if k.startswith("datasets_")]

    # Titles of fields encoded in filenames
    name_field_titles = PARAMS["name_field_titles"]

    if PARAMS["downsampling_enabled"]:
        downsampling_function = PARAMS['downsampling_function']
    else:
        downsampling_function = "no"

    downsampling_apply = PARAMS["downsampling_apply"]

    statements = []

    for subset in subsets:

        if subset == "all":
            if not PARAMS["datasets_all"]:
                continue

            sample_ids = set(sample_table["sample_id"].values)
            sample_ids_str = ",".join(sample_ids)

        else:

            sample_ids = PARAMS["datasets" + "_" + subset]

            sample_ids_str = ",".join([x.strip() for x in
                                       sample_ids.split(",")])

        out_dir = os.path.join(os.path.dirname(outfile),
                               subset)

        tenx_dir = PARAMS["tenx_dir"]

        log_file = outfile.replace(".sentinel",
                                   "." + subset + ".log")

        statement = '''Rscript %(tenx_dir)s/R/cellranger_subsetAndDownsample.R
                       --tenxdir=%(agg_matrix_dir)s
                       --sampleids=%(sample_ids_str)s
                       --downsample=%(downsampling_function)s
                       --apply=%(downsampling_apply)s
                       --samplenamefields=%(name_field_titles)s
                       --outdir=%(out_dir)s
                       &> %(log_file)s
                    ''' % locals()

        statements.append(statement)

    P.run(statements)

    IOTools.touch_file(outfile)


# ---------------------------------------------------
# Generic pipeline tasks

@follows(subsetAndDownsample, metrics, plotMetrics)
def full():
    '''
    Run the full pipeline.
    '''
    pass


if __name__ == "__main__":
    sys.exit(P.main(sys.argv))
