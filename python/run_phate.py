import os
import re
import argparse
import numpy as np
import matplotlib
matplotlib.use('Agg')

from matplotlib import rcParams
from matplotlib.colors import ListedColormap
import matplotlib.pyplot as pl
import seaborn as sns
import pandas as pd
from scipy import sparse
import logging
import sys
import scprep
import phate



# ########################################################################### #
# ###################### Set up the logging ################################# #
# ########################################################################### #

logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
L = logging.getLogger("run_paga")


# ########################################################################### #
# ######################## Parse the arguments ############################## #
# ########################################################################### #

parser = argparse.ArgumentParser()
parser.add_argument("--data", default="data.tsv.gz", type=str,
                    help="File with the data, e.g. scale.data from Seurat")
parser.add_argument("--assay", default="reduced.dimensions", type=str,
                    help="type of assay: scaled.data or dimension.reduction")
parser.add_argument("--barcode_file", default="barcodes.tsv.gz", type=str,
                    help="File with the cell barcodes")
parser.add_argument("--outdir",default=1, type=str,
                    help="path to output directory")
parser.add_argument("--cluster_assignments", default=1, type=str,
                    help="gzipped tsv file with cell cluster assignments")
parser.add_argument("--cluster_colors", default=1, type=str,
                    help="tsv file with the color palette for the clusters")
parser.add_argument("--k", default=5, type=int,
                    help="number of neighbors")
parser.add_argument("--gif", default="No", type=str,
                    help="output a GIF")


args = parser.parse_args()

# ########################################################################### #
# ############## Create outdir and set results file ######################### #
# ########################################################################### #


# Get the color palette
ggplot_palette = [x for x in pd.read_csv(args.cluster_colors,
                      header=None, sep="\t")[0].values]

ggplot_cmap = ListedColormap(sns.color_palette(ggplot_palette).as_hex())


# ########################################################################### #
# ############################## Run PHATE ################################## #
# ########################################################################### #

if args.assay == "reduced.dimensions":
    # Read matrix of reduced dimensions, create anndata and add dimensions
    data = pd.read_csv(args.data, sep="\t", header=0)

if args.assay == "scaled.data":
    # Read matrix of reduced dimensions, create anndata and add dimensions
    data = pd.read_csv(args.data, sep="\t", header=None)

    # we need to transpose the data for PHATE
    data = data.transpose()

# Read and add cluster ids
clusters = pd.read_csv(args.cluster_assignments,sep="\t")

phate_operator = phate.PHATE(n_jobs=-2, knn=args.k)
x2 = phate_operator.fit_transform(data)

# save a 2D plot
scprep.plot.scatter2d(x2, c=clusters["cluster_id"],
                      figsize=(12,8), cmap=ggplot_cmap,
                      ticks=False, label_prefix="PHATE", s=15,
                      filename=os.path.join(args.outdir,"phate.2D.png"),
                      dpi=300)

# save the 2D coordinates
rdims_phate = pd.DataFrame(x2,
                           columns=["PHATE1","PHATE2"])

rdims_phate["barcode"] = pd.read_csv(args.barcode_file, header=None)[0].values

rdims_phate.to_csv(os.path.join(args.outdir,"phate.tsv.gz"),
                   sep="\t")

# save a 3D plot
phate_operator.set_params(n_components=3)
x3 = phate_operator.transform()
scprep.plot.scatter3d(x3, c=clusters["cluster_id"],
                      figsize=(8,6), cmap=ggplot_cmap,
                      ticks=False, label_prefix="PHATE",
                      filename=os.path.join(args.outdir,"phate.3D.png"),
                      dpi=300)

# save the 3D coordinates
rdims_phate = pd.DataFrame(x3,
                           columns=["PHATE1","PHATE2", "PHATE3"])

rdims_phate["barcode"] = pd.read_csv(args.barcode_file, header=None)[0].values

rdims_phate.to_csv(os.path.join(args.outdir,"phate_3D.tsv.gz"),
                   sep="\t")

# save a GIF!
if args.gif.lower() == "yes":
    scprep.plot.rotate_scatter3d(x3, c=clusters["cluster_id"],
                                 figsize=(8,6), cmap=ggplot_cmap,
                                 ticks=False, label_prefix="PHATE",
                                 filename=os.path.join(args.outdir,"phate.3D.gif"),
                                 dpi=300)


L.info("Phate accompli")
