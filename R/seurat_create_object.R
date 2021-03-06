## Title ----
##
## Initial steps of the Seurat workflow for single-cell RNA-seq analysis
##
## Description ----
##
## This script performs the initial steps of the Seurat (http://satijalab.org/seurat/)
## workflow for single-cell RNA-seq analysis, including:
## (i) Reading in the data
## (ii) subsetting
## (iii) QC filtering
## (iv) Normalisation and removal of unwanted variation
## (v) Identification of variable genes
## (vi) Dimension reduction (PCA)
##
## The seurat object is saved as the R object "rds" in the output directory

# Libraries ----

stopifnot(
  require(optparse),
  require(Seurat),
  require(sctransform),
  require(ggplot2),
  require(dplyr),
  require(Matrix),
  require(xtable),
  require(tenxutils),
  require(reshape2),
  require(future)
)


# Options ----

option_list <- list(
    make_option(
        c("--tenxdir"),
        help="Location of the input 10x matrix"
    ),
    make_option(
        c("--matrixtype"), default="10X",
        help="either 10X or rds"
    ),

    make_option(
        c("--project"),
        default="SeuratAnalysis",
        help="project name"
        ),
    make_option(
        c("--outdir"),
        default="seurat.out.dir",
        help="Location for outputs files. Must exist."
        ),
    make_option(
        c("--metadata"),
        default="none",
        help=paste(
            "A tab delimited text file containing cell metadata.",
            "A barcode column must be present and must match the barcodes of the 10x matrix"
            )
        ),
    make_option(
        c("--groupby"),
        default="sample_id",
        help=paste(
            "The name of a column in the metadata table by which to group samples",
            "(e.g. sample_id)."
        )),
    make_option(
        c("--mingenes"),
        type="integer",
        default=200,
        help="min.genes"),
    make_option(
        c("--mincells"),
        type="integer",
        default=3,
        help=paste(
            "Include genes with detected expression in at least this many cells.",
            "See Seurat::CreateSeuratObject(min.cells=...)."
        )),
    make_option(
        c("--downsamplecells"),
        default=FALSE,
        help=paste(
            "Whether to randomly downsample cells so that each",
            "group has the sample number of cells."
        )),

    make_option(
        c("--seed"),
        default=NULL,
        help=paste(
            "The seed (an integer) to use when down sampling the cells"
        )),
    make_option(
        c("--qcmingenes"),
        type="integer",
        default=500,
        help=paste(
            "Minimal count of genes detected to retain a cell.",
            "See Seurat::FilterCells(subset.names='nGene', low.thresholds= ...)"
            )
        ),
    make_option(
        c("--qcminpercentmito"),
        type="double",
        default=-Inf,
        help=paste(
            "Minimum percentage of UMI assigned to mitochondrial genes.",
            "See Seurat::FilterCells(subset.names='percent.mito', low.thresholds= ...)"
            )
        ),
    make_option(
        c("--qcmaxpercentmito"),
        type="double",
        default=0.05,
        help=paste(
            "Maximal percentage of UMI assigned to mitochondrial genes.",
            "See Seurat::FilterCells(subset.names='percent.mito', high.thresholds= ...)"
            )
        ),
    make_option(
      c("--qcmaxcount"),
      type="integer",
      default=NULL,
      help="Max nCount_RNA to retain a cell"
      ),
    make_option(
        c("--normalizationmethod"),
        default="log-normalization",
        help="The normlization method to use"
        ),
    make_option(
        c("--latentvars"),
        default="nUMI,percent.mito",
        help=paste(
            "Latent variables to regress out.",
            "See Seurat::ScaleData(vars.to.regress=..., model.use=opt$modeluse)"
            )
        ),
    make_option(
        c("--modeluse"),
        default="linear",
        help=paste(
            "Model used to regress out latent variables.",
            "See Seurat::ScaleData(model.use=opt$modeluse)"
            )
        ),
    make_option(
        c("--vargenesmethod"),
        default="mean.var.plot",
        help=paste(
            "Method for variable gene selection.",
            "Either top.genes or mean.var.plot"
            )
        ),
    make_option(
        c("--topgenes"),
        type="integer",
        default=1000,
        help=paste(
            "Number of highly variable genes to retain"
            )
        ),
    make_option(
        c("--sdcutoff"),
        type="double",
        default=0.5,
        help=paste(
            "Bottom cutoff on y-axis for identifying variable genes.",
            "See Seurat::FindVariableFeatures(y.cutoff=...)"
            )
        ),
    make_option(
        c("--xlowcutoff"),
        type="double",
        default=0.1,
        help=paste(
            "Bottom cutoff on x-axis for identifying variable genes",
            "See Seurat::FindVariableFeatures(x.low.cutoff=...)"
            )
        ),
    make_option(
        c("--xhighcutoff"),
        type="double",
        default=8,
        help=paste(
            "Top cutoff on x-axis for identifying variable genes",
            "See Seurat::FindVariableFeatures(x.low.cutoff=...)"
            )
    ),
        make_option(
        c("--minmean"),
        type="double",
        default=0,
        help=paste(
            "minimum mean of log counts when using trendvar method"
            )
        ),
        make_option(
        c("--vargenespadjust"),
        type="double",
        default=0.05,
        help=paste(
            "significance threshold for trendvar method"
            )
        ),
    make_option(
        c("--subsetcells"),
        default="use.all",
        help=paste(
            "A file containing the list of barcode ids to retain",
            "(no header, 1 per line)."
            )
    ),
    make_option(
        c("--subsetfactor"),
        default=NULL,
        help="A factor specified in metadata.tsv on which to subset"
        ),
    make_option(
        c("--subsetlevel"),
        default="none",
        help="The desired level of the sub-setting factor"),
    make_option(
        c("--blacklist"),
        default=NULL,
        help=paste(
            "A file containing a list of barcode ids to remove (if present)",
            "(no header, 1 per line)."
            )
        ),
    make_option(
        c("--cellcycle"),
        default="none",
        help="type of cell cycle regression to apply (none|all|difference)"
        ),
    make_option(
        c("--sgenes"),
        default="none",
        help=paste(
            "A vector of Ensembl gene ids associated with S phases.",
            "See Seurat::CellCycleScoring(s.genes=...)"
            )
        ),
    make_option(
        c("--g2mgenes"),
        default="none",
        help=paste(
            "A vector of Ensembl gene ids associated with G2M phase.",
            "See Seurat::CellCycleScoring(g2m.genes=...)"
            )
    ),
    make_option(
        c("--jackstraw"),
        action = "store_true",
        default=FALSE,
        help="should the jackstraw analysis be run"
    ),

    make_option(
        c("--jackstrawnumreplicates"),
        type="integer",
        default=100,
        help="Number of replicates for the jackstraw analysis"
    ),
    make_option(
        c("--numcores"),
        type="integer",
        default=12,
        help="Number of cores to be used for the Jackstraw analysis"
    ),
    make_option(
        c("--memory"),
        type="integer",
        default=4000,
        help="Amount of memory (mb) to request"
    ),

    make_option(c("--usesigcomponents"), default=FALSE,
                help="use significant principle component"),
    make_option(c("--components"), type="integer", default=10,
                help="if usesigcomponents is FALSE, the number of principle components to use"),
    make_option(
        c("--plotdirvar"),
        default="sampleDir",
        help="latex var containig plot location"
    )


    )

opt <- parse_args(OptionParser(option_list=option_list))

cat("Running with options:\n")
print(opt)

#plan("multiprocess",
#     workers = opt$numcores)

plan("sequential")

#options(future.globals.maxSize = opt$memory * 1024^2)

# Input data ----

## ######################################################################### ##
## ###################### (i) Read in data ################################# ##
## ######################################################################### ##


#' Collect the number of cells through the workflow
#'
#' Initialises a data.frame of appends a new column
#' with a user-defined tag.
#'
#' @param s Seurat object
#' @param cell_numbers data.frame of an earlier call to
#' getCellNumbers, if applicable.
#' @param stage Character value to tag the new entry.
#'
#' @return A data.frame
getCellNumbers <- function(s, cell_numbers="none", stage="input",
	       	  	   groupby=opt$groupby) {
    ## cell_info <- getCellInfo(s)
    counts <- as.data.frame(table(s[[]][,groupby]))
    colnames(counts) <- c(groupby, stage)
    rownames(counts) <- counts[[groupby]]
    counts[[groupby]] <- NULL

    if ( identical(cell_numbers, "none") ) {
        result <- counts
        colnames(counts) <- stage
    } else {
        cnames <- c(colnames(cell_numbers), stage)
        result <- cbind(cell_numbers, counts[[stage]])
        colnames(result) <- cnames
    }
    return(result)
}

stats <- list()

cat("Importing matrix from: ", opt$tenxdir, " ... ")
if(opt$matrixtype=="10X")
{
    data <- Read10X(opt$tenxdir)

    ## Seurat discards the Ensembl IDs and makes it's own identifiers (!)
    ## From https://github.com/satijalab/seurat/blob/master/R/preprocessing.R:
    ##
    ## rownames(data) <- make.unique(
    ##    names=as.character(
    ##        x=sapply(
    ##            X=gene.names,
    ##            FUN=ExtractField,
    ##            field=2,
    ##            delim="\\t"
    ##
    ## We need to track the seurat id -> Ensembl id mapping, e.g. for downstream GO analysis
    ## (and to guarentee reproducibility, e.g. between annotations versions)

    inFile <- file.path(opt$tenxdir, "features.tsv.gz")
    cat("Importing gene information from: ", inFile, " ... ")
    genes <- read.table(gzfile(inFile), as.is=TRUE)
    cat("Done.\n")

    colnames(genes) <- c("gene_id", "gene_name")
    ## TODO: consider scater::uniquifyFeatureNames()
    genes$seurat_id <- as.character(make.unique(genes$gene_name))
    rownames(genes) <- genes$seurat_id

    write.table(
        genes, file.path(opt$outdir, "annotation.txt"),
        sep="\t", col.names=TRUE, row.names=FALSE, quote=FALSE
    )

} else if(opt$matrixtype=="rds")
{
    data <- readRDS(file.path(opt$tenxdir, "matrix.rds"))
}


## Initialize the Seurat object with the raw (non-normalized data)
## Note that this is slightly different than the older Seurat workflow,
## where log-normalized values were passed in directly.
## You can continue to pass in log-normalized values,
## just set do.logNormalize=F in the next step.
#s <- new("seurat", raw.data=data)

## Keep all genes expressed in >= 3 cells,
## keep all cells with >= 200 genes
## Perform log-normalization, first scaling each cell
## to a total of 1e4 molecules (as in Macosko et al. Cell 2015)
cat("Creating Seurat object ... ")
s <- CreateSeuratObject(counts=data,
                        min.cells=opt$mincells,
                        min.features=opt$mingenes,
                        project=opt$project
    )
cat("Done.\n")

# remove the data
rm(data)
gc()

if(opt$matrixtype=="10X")
{
    s@misc <- genes
}

## Read in the metadata
if ( identical(opt$metadata, "none") ) {
    stop("No metadata file given")
}

cat("Importing metadata ... ")
metadata <- read.table(gzfile(opt$metadata),
                       sep="\t", header=TRUE, as.is=TRUE)
cat("Done.\n")

# ensure that the barcode column is present in the metadata
if (!"barcode" %in% colnames(metadata)) {
    stop('Mandatory "barcode" column missing from the metadata')
}

rownames(metadata) <- metadata$barcode
metadata$barcode <- NULL

metadata <- metadata[colnames(x = s), ]

# TODO: probably a more elegant way to show/handle this
if (!identical(rownames(metadata), colnames(x = s))) {
    ## print out some debugging information
    cat("Count of rownames in metadata: ", length(rownames(metadata)), "\n")
    cat("Count of cell.names in Seurat object: ", length(colnames(x = s)), "\n")
    cat("--\n")
    cat("First rownames in metadata:\n")
    print(head(rownames(metadata)))
    cat("First cell.names in Seurat object:\n")
    print(head(colnames(x = s)))
    cat("--\n")
    cat("Last rownames in metadata:\n")
    print(tail(rownames(metadata)))
    cat("Last cell.names in Seurat object:\n")
    print(tail(colnames(x = s)))

    stop("Metadata barcode field does not match cell.names")
}

cat("Adding meta data ... ")
for(meta_col in colnames(metadata))
{
    s[[meta_col]] <- metadata[[meta_col]]
                                        }
cat("Done.\n")

# ensure that the grouping factor is present in the metadata
if (!opt$groupby %in% colnames(s[[]])) {
    stop(paste("The specified grouping factor:",
               opt$groupby,
               "was not found in the metadata",
               sep=" "))
}


## ######################################################################### ##
## ####################### (ii) Subsetting ################################# ##
## ######################################################################### ##

getSubset <- function(seurat_object, cells_to_retain)
{
        if ( identical(length(cells_to_retain), 0L) ) {
            stop("No cells present in subset")
        }

        message("Number of cells before subsetting:")
        print(length(colnames(x = s)))

        s <- SubsetData(s,
                        cells=cells_to_retain)

        message("Number of cells after subsetting:")
        print(length(colnames(x = s)))

        s
}

if (opt$subsetcells!="use.all") {

    message("subsetting to whitelisted cells")
    cells_to_retain <- scan(opt$subsetcells, "character")
    s <- getSubset(s, cells_to_retain)

} else {
    if (!is.null(opt$subsetfactor)) {
        if(!opt$subsetfactor %in% colnames(s[[]])) {
            stop("The given subsetting factor must match a column in the metadata")
        }

        if (!opt$subsetlevel %in% s[[]][,opt$subsetfactor]) {
            stop("The specified level of the subsetting factor does not exist")
        }

        message("subsetting by factor")
        cells_to_retain <- rownames(s[[]])[
            s[[]][, opt$subsetfactor] == opt$subsetlevel
            ]

        s <- getSubset(s, cells_to_retain)

    }
}

# Remove blacklisted cells.
if(!is.null(opt$blacklist))
{
    message("removing blacklisted cells")

    blacklist <- scan(opt$blacklist, "character")

    cells_to_retain <- colnames(x = s)[!colnames(x = s) %in% blacklist]

    s <- getSubset(s, cells_to_retain)
    }

## ######################################################################### ##
## ##################### (iii) QC filtering ################################ ##
## ######################################################################### ##

## The number of genes and UMIs (nGene and nUMI) are
## automatically calculated for every object by Seurat.
## For non-UMI data, nUMI represents the sum of the
## non-normalized values within a cell
## We calculate the percentage of mitochondrial genes here
## and store it in percent.mito using the AddMetaData.
## The % of UMI mapping to MT-genes is a common scRNA-seq QC metric.
## NOTE: You must have the Matrix package loaded to calculate the percent.mito values.
## In humans the pattern is ^MT-, in mouse it is ^mt-: to accomodate both
## we simply ignore the case (specificity is still maintained).
mito.genes <- grep("^MT-", rownames(x = s), value=TRUE, ignore.case=TRUE)

## NOTE: unlike in the Seurat vignette, our data is not yet log transformed.
# TODO: is Matrix:: required here?
percent.mito <- Matrix::colSums(GetAssayData(object = s)[mito.genes, ]) / Matrix::colSums(GetAssayData(object = s))

## AddMetaData adds columns to object@data.info,
## and is a great place to stash QC stats
s$percent.mito <- percent.mito

message("Drawing violin plots")
gp <- VlnPlot(s,
              features = c("nFeature_RNA", "nCount_RNA", "percent.mito"),
              # size.title.use=14,
              # size.x.use=12,
              group.by=opt$groupby,
              pt.size = 0,
              # x.lab.rot=TRUE,
              # point.size.use=0.1,
              ncol=3
    )


save_ggplots(file.path(opt$outdir, "qc.vlnPlot"),
             gp,
             width=7,
             height=4)

## GenePlot is typically used to visualize gene-gene relationships,
## but can be used for anything calculated by the object, i.e. columns
## in object@data.info, PC scores etc.
## Since there is a rare subset of cells with an outlier level of
## high mitochondrial percentage, and also low UMI content, we filter these as well

message("Drawing scatter plots")
plot_fn <- function() {
    par(mfrow=c(1, 2))
    FeatureScatter(s, "nCount_RNA", "percent.mito", pt.size=1)
    FeatureScatter(s, "nCount_RNA", "nFeature_RNA", pt.size=1)
    par(mfrow=c(1, 1))
}

save_plots(
    file.path(opt$outdir, "qc.genePlot"), plot_fn=plot_fn,
    width=8, height=4
    )

cell_numbers <- getCellNumbers(s, groupby=opt$groupby)

## We filter out cells that have unique gene counts over 2,500
## Note that accept.high and accept.low can be used to define a 'gate',
## and can filter cells not only based on nFeature_RNA but on anything in the
## object (as in GenePlot above)

stats$no_cells <- ncol(GetAssayData(object = s))
stats$qc_min_gene_threshold <- opt$qcmingenes
stats$qc_min_percent_mito_threshold <- opt$qcminpercentmito
stats$qc_max_percent_mito_threshold <- opt$qcmaxpercentmito

if (! is.null(opt$qcmaxcount)) {
  s <- subset(s, subset = nFeature_RNA > opt$qcmingenes &
                   percent.mito > opt$qcminpercentmito &
                   percent.mito < opt$qcmaxpercentmito &
                   nCount_RNA < opt$qcmaxcount)
  stats$qc_max_count_threshold <- opt$qcmaxcount
  } else {
    s <- subset(s, subset = nFeature_RNA > opt$qcmingenes &
                     percent.mito > opt$qcminpercentmito &
                     percent.mito < opt$qcmaxpercentmito)
    }


stats$no_cells_after_qc <- ncol(GetAssayData(object = s))

cell_numbers <- getCellNumbers(s,
                               cell_numbers=cell_numbers,
                               stage="after_qc_filters",
	     		       groupby=opt$groupby)

cat("Data dimensions after subsetting:\n")
print(dim(GetAssayData(object = s)))

# Optionally downsample cell numbers ----

if(is.null(opt$seed))
{
    seed <- sample(1:2^15,1)
    set.seed(seed)
    message("Seed set to: ", seed)
} else {
    seed <- opt$seed
}


if (as.logical(opt$downsamplecells)) {

    mincells <- min(table(s[[]][,opt$groupby]))

    cat(paste0("Downsampling to ", mincells, " per sample\n"))
    cells.to.use <- c()
    for (group in unique(s[[]][,opt$groupby])) {
        print(group)
        temp <- rownames(s[[]])[s[[]][,opt$groupby] == group]
        print(head(temp))

        cells.to.use <- c(cells.to.use, sample(temp, mincells))
        print(length(cells.to.use))
    }

    s <- SubsetData(s,
                    cells=cells.to.use)

    cell_numbers <- getCellNumbers(s, cell_numbers=cell_numbers,
    		    		   stage="after_downsampling", groupby=opt$groupby)

    cat("Numbers of cells per sample after down-sampling:\n")
    print(cell_numbers)
}

print(
    xtable(cell_numbers, caption="Numbers of cells"),
    file=file.path(opt$outdir, "cell_numbers.tex")
    )


## ######################################################################### ##
## # (iv) Initial normalisation, variable gene identification and scaling ## ##
## ######################################################################### ##


## No cell cycle correction is applied at this stage.

if(opt$latentvars == "none") {
    latent.vars = NULL
    message("no latent vars specified")
} else {
    latent.vars <- strsplit(opt$latentvars, ",")[[1]]
    message("latent vars: ", latent.vars)
}

## Currently, we need to log-normlize and scale the RNA assay
## for gene-level analyses even if we use sctransform
## for characterisation of the cells/subpopulations.
##
## see e.g. https://github.com/satijalab/seurat/issues/1717
## and  https://github.com/satijalab/seurat/issues/1421

message("Performing initial log-normalization")

## Perform log-normalization of the RNA assay
s <- NormalizeData(object=s,
                   normalization.method="LogNormalize",
                   scale.factor=10E3)

message("log-normalisation completed")

gc()

message("scaling the data")
## Initial scaling of the RNA assay data
all.genes <- rownames(s)
ncells <- ncol(GetAssayData(s))
if(ncells > 200000)
{
    block.size=250
} else if (ncells > 100000) {
    block.size=500
} else { block.size=1000 }



s <- ScaleData(object=s,
               features = all.genes,
               vars.to.regress=latent.vars,
               block.size=block.size,
               model.use=opt$modeluse)

## Normalisation specific options.
message("scaling complete")

gc()

if(opt$normalizationmethod=="log-normalization")
{

    ## variable gene identification

    message("Finding variable features")
    ## We need to run FindVariableFeatures to set HVFInfo(object = s)
    ## even if "trendvar" method is specified...
    if(opt$vargenesmethod=="trendvar")
    {
        fvg_method="mean.var.plot"
    } else {
        fvg_method=opt$vargenesmethod
    }

    s <- FindVariableFeatures(s,
                              selection.method=fvg_method,
                              nfeatures=opt$topgenes,
                              mean.cutoff = c(opt$xlowcutoff,
                                              opt$xhighcutoff),
                              dispersion.cutoff=c(opt$sdcutoff, Inf))

    xthreshold <- opt$xlowcutoff

    if(opt$vargenesmethod=="trendvar")
    {
        message("setting variable genes using the trendvar method")

        ## get highly variable genes using the getHVG function in tenxutils (Matrix.R)
        ## that wraps the trendVar method from scran.
        hvg.out <- getHVG(s,
                          min_mean=opt$minmean,
                          p_adjust_threshold=opt$vargenespadjust)

        ## overwrite the slot
        VariableFeatures(object = s) <- row.names(hvg.out)

        xthreshold <- opt$minmean
    }


} else if(opt$normalizationmethod=="sctransform")
{
    message("Performing initial SCTransform normalization")

    s <- SCTransform(object=s,
                     assay="RNA",
                     new.assay.name="SCT",
                     do.correct.umi=TRUE,
                     variable.features.n=3000,
                     vars.to.regress=latent.vars,
                     do.scale=FALSE,
                     do.center=TRUE,
                     return.only.var.genes=FALSE)

    ## Note that the SCT slot will now be set as default.

} else {
    stop("Invalid normalization method specified")
}


## make a plot that shows the variable genes.

xx <- HVFInfo(object = s)

xx$var.gene = FALSE
xx$var.gene[rownames(xx) %in% VariableFeatures(object = s)] <- TRUE

if(opt$normalizationmethod=="log-normalization")
{
    xvar = "mean"
    yvar = "dispersion"

} else if(opt$normalizationmethod=="sctransform")
{
    xvar = "gmean"
    yvar = "residual_variance"
}

xxm <- melt(xx[, c(xvar,yvar,"var.gene")],
            id.vars=c("var.gene",xvar))

gp <- ggplot(xxm, aes_string(xvar, "value", color="var.gene"))


gp <- gp + scale_color_manual(values=c("black","red"))
gp <- gp + geom_point(alpha = 1, size=0.5)
gp <- gp + facet_wrap(~variable, scales="free")
gp <- gp + theme_classic()

if(opt$normalizationmethod=="sctransform")
{
    gp <- gp + scale_y_continuous(trans="log10", labels = function(x) format(x, digits=3, scientific = TRUE))
    gp <- gp + scale_x_continuous(trans="log10", labels = function(x) format(x, digits=3, scientific = TRUE))
}

gp <- gp + ylab(yvar)

if(exists("xthreshold"))
{
    if(xthreshold > 0)
    {
        gp <- gp + geom_vline(xintercept=xthreshold, linetype="dashed", color="blue")
    }
}

save_ggplots(file.path(opt$outdir, "varGenesPlot"),
             gp=gp,
             width=8,
             height=5)



cat("no. variable genes: ", length(VariableFeatures(object = s)), "\n")
stats$no_variable_genes <- length(VariableFeatures(object = s))

print(stats)

# write out some statistics into a latex table.
print(
    xtable(t(data.frame(stats)), caption="Run statistics"),
    file=file.path(opt$outdir, "stats.tex")
    )


## ######################################################################### ##
## ###### (v) Removal of unwanted variation/cell cycle correction ########## ##
## ######################################################################### ##


## initialise the text snippet
tex = ""

## start building figure latex...
subsectionTitle <- getSubsectionTex("Visualisation of cell cycle effects")
tex <- c(tex, subsectionTitle)


## If cell cycle genes are given, make a PCA of the cells based
## on expression of cell cycle genes

cell_cycle_genes <- FALSE

if (!(is.null(opt$sgenes) | opt$sgenes=="none")
    & !(is.null(opt$g2mgenes) | opt$g2mgenes=="none"))
{

  cell_cycle_genes <- TRUE
  cat("There are cell cycle genes")

  # get the genes representing the cell cycle phases
  sgenes_ensembl <- read.table(opt$sgenes, header=F, as.is=T)$V1
  sgenes <- s@misc$seurat_id[s@misc$gene_id %in% sgenes_ensembl]

  g2mgenes_ensembl <- read.table(opt$g2mgenes, header=F, as.is=T)$V1
  g2mgenes <- s@misc$seurat_id[s@misc$gene_id %in% g2mgenes_ensembl]

  # score the cell cycle phases
    s <- CellCycleScoring(object=s,
                          s.features=sgenes,
                          g2m.features=g2mgenes,
                          set.ident=TRUE)

    s <- RunPCA(object = s,
                features = c(sgenes, g2mgenes),
                do.print = FALSE)

  ## PCA plot on cell cycle genes without regression
  gp <- PCAPlot(object = s)

  cc_plot_fn <- "cellcycle.without.regression.pca"
  cc_plot_path <- file.path(opt$outdir, cc_plot_fn)

  save_ggplots(cc_plot_path, gp, width=7, height=4)

  pcaCaption <- paste0("PCA analysis of cells based on expression of cell cycle genes ",
                       "(without regression of cell-cyle effects)")

  tex <- c(tex, getFigureTex(cc_plot_fn,
                             pcaCaption,
                             plot_dir_var=opt$plotdirvar))

} else {
    tex <- c(tex, "Cell cycle genelists not supplied.")
}

## Perform regression (with or without cell cycle correction)
if ( identical(opt$cellcycle, "none") ) {

    cat("Data was scaled without correcting for cell cycle")

} else {

    if (!cell_cycle_genes){
        stop("Please provide lists of cell cycle sgenes and g2mgenes")
        }

    if ( identical(opt$cellcycle, "all") ){

        message("Cell cycle correction for S and G2M scores will be applied\n")
        vars.to.regress <- c(latent.vars, "S.Score", "G2M.Score")

    } else if ( identical(opt$cellcycle, "difference") ) {

      message("Cell cycle correction for the difference between G2M and S phase scores will be applied\n")
        s$CC.Difference <- s$S.Score - s$G2M.Score
        vars.to.regress <- c(latent.vars, "CC.Difference")

    } else {
      stop("Cell cycle regression type not recognised")
    }

    ## Apply the cell cycle correction.

    ## Always scale the RNA slot
    s <- ScaleData(object=s,
                   features = all.genes,
                   vars.to.regress=vars.to.regress,
                   block.size=block.size,
                   model.use=opt$modeluse,
                   assay="RNA")

    ## Optionally run sctransorm
    if(opt$normalizationmethod=="sctransform")
    {
        s <- SCTransform(object=s,
                         assay="RNA",
                         new.assay.name="SCT",
                         do.correct.umi=TRUE,
                         variable.features.n=3000,
                         vars.to.regress=vars.to.regress,
                         do.scale=FALSE,
                         do.center=TRUE,
                         return.only.var.genes=FALSE)

        ## Note that the SCT assay will now be the default.
    }

    ## visualise the cells by PCA of cell cycle genes after regression
    s <- RunPCA(object = s, features = c(sgenes, g2mgenes), do.print = FALSE)
    gp <- PCAPlot(object = s)

    cc_plot_fn <- paste("cellcycle.regressed", opt$cellcycle, "pca", sep=".")
    cc_plot_path <- file.path(opt$outdir, cc_plot_fn)

    save_ggplots(cc_plot_path, gp, width=7, height=4)

    pcaCaption <- paste0("PCA analysis of cells based on expression of cell cycle genes ",
                         "after regression of cell-cyle effects ",
                         "(regression type: ", opt$cellcycle, ")")

    tex <- c(tex, getFigureTex(cc_plot_fn,
                               pcaCaption,
                               plot_dir_var=opt$plotdirvar))

}


tex_file <- file.path(opt$outdir, "cell.cycle.tex")

writeTex(tex_file, tex)


## ######################################################################### ##
## ################### (vi) Dimension reduction (PCA) ###################### ##
## ######################################################################### ##

# perform PCA using the variable genes
s <- RunPCA(s,
            features=VariableFeatures(object = s),
            npcs=100,
            do.print=FALSE)

n_cells_pca <- min(1000, length(colnames(x = s)))

# Write out heatmaps showing the genes loading the first 12 components
plot_fn <- function() {
    DimHeatmap(s, dims=1:12,
               # cells.use=n_cells_pca,
               reduction="pca",
               balanced=TRUE,
               # label.columns=FALSE,
               # cexRow=0.8,
               # use.full=FALSE
        )
}

save_plots(file.path(opt$outdir, "pcaComponents"), plot_fn=plot_fn,
           width=8, height=12)

print("----")
print(dim(Embeddings(object=s, reduction="pca")))

nPCs <- min(dim(Embeddings(object =s, reduction="pca"))[2],50)

print(nPCs)

# Write out the PCA elbow (scree) plot
png(file.path(opt$outdir, "pcaElbow.png"),
    width=5, height=4, units="in",
    res=300)

ElbowPlot(s,
          ndims=nPCs)

dev.off()

## In Macosko et al, we implemented a resampling test inspired by the jackStraw procedure.
## We randomly permute a subset of the data (1% by default) and rerun PCA,
## constructing a 'null distribution' of gene scores, and repeat this procedure. We identify
## 'significant' PCs as those who have a strong enrichment of low p-value genes.

if(opt$normalizationmethod!="sctransform" & opt$jackstraw)
{
    s <- JackStraw(s,
                   reduction="pca",
                   num.replicate=opt$jackstrawnumreplicates,
                   dims = nPCs)

    s <- ScoreJackStraw(s, dims = 1:nPCs)

    ##               do.par=TRUE,
    ##               num.cores=opt$numcores)

    gp <- JackStrawPlot(s, dims= 1:nPCs,
                     reduction="pca")

    save_ggplots(paste0(opt$outdir,"/pcaJackStraw"),
                 gp,
                 width=8,
                 height=12)
}
message("seurat_begin.R object final default assay: ", DefaultAssay(s))

# Save the R object
saveRDS(s, file=file.path(opt$outdir, "begin.rds"))

message("Completed")
