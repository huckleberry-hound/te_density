#!/usr/bin/env python3

"""
Calculate transposable element density.
"""

__author__ = "Scott Teresi, Michael Teresi"

import pdb
import os
import time
import argparse
import coloredlogs
import logging
from enum import IntEnum, unique
import time

#from multiprocessing import Process
#import multiprocessing
#from threading import Thread

from tqdm import tqdm
import numpy as np
import pandas as pd

from transposon.data import GeneData, TransposonData

# FUTURE enum.Flag is more appropriate but let us delineate first and revisit
# TODO SCOTT is the DensityConditions still required since we moved the numpy stuff?
@unique
class DensityConditions(IntEnum):
    """Enumerate the conditions where density is calculated with respect to.

    Below, inclusive generally can be evaluated as <= or >=
    Exclusive would be < or >

    Conditions deal with the transposable element (TE) position wrt gene/windows.


        IN_GENE_ONLY: The TE is only inside the gene, that includes gene start
        and gene stop (inclusive). The density would be the total number of TE
        bases (TE length) divided by the Gene Length.


        IN_WINDOW_ONLY: The TE is between the window start or stop (inclusive)
        and the gene start or stop (exclusive). The density would be the total
        number of TE bases (TE length) divided by the size of the window.


        IN_WINDOW_AND_GENE: The TE is within the gene (inclusive on gene edges)
        and ends within the window (can end on window edges, inclusive). This
        test is sort of a fusion of IN_GENE_ONLY and IN_WINDOW_ONLY, we would
        need to calculate two values!
        Something that we would call Intra density and either upstream or downstream
        density. The intra value would just come from the portion that is inside,
        divided by the length of the gene. And the window portion would just be
        the portion that is inside the window. Reminder that a TE base that
        overlaps with the gene start or stop is considered inside the gene,
        where a TE base that ends on a window is considered inside the window

        IN_WINDOW_FROM_OUTSIDE: A TE extends into the window, but part of it is
        outside the window. Thus the only relevant part is the part that sits
        inside the window. So imagine a case where the TE extends past the
        WindowStop, the desired amount of TE Bases would be:
        (WindowStop - TE_Start) and then we would divide that by the WindowSize
        to get the density
    """

    IN_GENE_ONLY= 0
    IN_WINDOW_ONLY = 1
    IN_WINDOW_AND_GENE = 2
    IN_WINDOW_NOT_GENE = 3
    IN_WINDOW_AND_GENE_UP_DOWN_STREAM = 4  # TE in window or gene but start or stop is outside window?

def get_head(Data):
    """ Get the heading of the Pandaframe """
    try:
        print(Data.head())
    except AttributeError as e:
        raise AttributeError('Your input data was incorrect, check to make sure it is a Pandaframe')

def save_output(Data, Output_Name):
    """ Save the output of the Pandaframe """
    if Output_Name[-4:] != '.csv':
        raise NameError('Please make sure your filename has .csv in it!')
    global OUTPUT_DIR  # TODO remove global
    Data.to_csv(os.path.join(OUTPUT_DIR, Output_Name),
            header=True,
            sep=',')
    # TODO remove ch_main_path, not sure where this is needed anymore
    #ch_main_path() # change to Code directory

def get_dtypes(my_df):
    print(my_df.dtypes)

def get_nulls(my_df):
    null_columns = my_df.columns[my_df.isnull().any()]
    count_of_null = my_df[null_columns].isnull().sum()
    print('Counts of null values per column: ' '\n', count_of_null, '\n')
    rows_where_null = my_df[my_df.isnull().any(axis=1)][null_columns].head()
    print('Rows where null exist: ', '\n', rows_where_null, '\n')

def drop_nulls(my_df, status=False):
    if status:
        print('DROPPING ROWS WITH AT LEAST ONE NULL VALUE!!!')
    my_df = my_df.dropna(axis = 0, how ='any')
    return my_df

def get_info(my_df):
    print(my_df.info())

def get_counts(my_df_col):
    print(my_df_col.value_counts())

def get_unique(my_df_col):
    return my_df_col.unique()

def swap_columns(df, col_condition, c1, c2):
    df.loc[col_condition, [c1, c2]] = \
    df.loc[col_condition, [c2, c1]].values
    return df

def split(df, group):
    """
    Returns a list of the dataframe with each element being a subset of the df.
    I use this function to split by chromosome so that we may later do
    chromosome element-wise operations.
    """
    gb = df.groupby(group)
    return [gb.get_group(x) for x in gb.groups]

def import_genes(input_dir):
    """ Import Genes File """

    # TODO remove MAGIC NUMBER (perhaps just search by extension (gtf)?)
    gtf_filename = 'camarosa_gtf_data.gtf' # DECLARE YOUR DATA NAME
    #ch_input_data_path()

    col_names = ['Chromosome', 'Software', 'Feature', 'Start', 'Stop', \
                 'Score', 'Strand', 'Frame', 'FullName']

    col_to_use = ['Chromosome', 'Software', 'Feature', 'Start', 'Stop', \
                  'Strand', 'FullName' ]

    Gene_Data = pd.read_csv(
            os.path.join(input_dir, gtf_filename),
            sep='\t+',
            header=None,
            engine='python',
            names = col_names,
            usecols = col_to_use)

    Gene_Data = Gene_Data[Gene_Data.Feature == 'gene']  # drop non-gene rows

    # clean the names and set as the index (get row wrt name c.f. idx)
    Gene_Data[['Name1', 'Gene_Name']] = Gene_Data.FullName.str.split(';Name=', expand=True)
    Gene_Data.set_index('Gene_Name', inplace=True)
    Gene_Data = Gene_Data.drop(['FullName', 'Name1', 'Software'], axis = 1)

    Gene_Data.Strand = Gene_Data.Strand.astype(str)
    # NOTE Scott, this astype(int) defaulted to int64, can you use uint32?
    # SEE numpy.iinfo
    # probably not a big deal but could help out
    # the first sub gene frame 169,792 bytes (int64) vs 133,408 bytes (uint32)
    # are you going to have negative indices?
    # are you going to have indices greater than 4,294,967,295?
    Gene_Data.Start = Gene_Data.Start.astype('uint32')
    Gene_Data.Stop = Gene_Data.Stop.astype('uint32')
    # NOTE is the gene index a closed | open interval?
    # Scott thinks we should delete the + 1 for length
    Gene_Data['Length'] = Gene_Data.Stop - Gene_Data.Start

    # We will not swap Start and Stop for Antisense strands. We will do this
    # post-processing
    #col_condition = Gene_Data['Strand'] == '-'
    #Gene_Data = swap_columns(Gene_Data, col_condition, 'Start', 'Stop')
    return Gene_Data

def import_transposons(input_dir):
    """ Import the TEs """

    # TODO remove MAGIC NUMBER (perhaps just search by extension (gtf)?)
    gff_filename = 'camarosa_gff_data.gff' # DECLARE YOUR DATA NAME

    col_names = ['Chromosome', 'Software', 'Feature', 'Start', 'Stop', \
        'Score', 'Strand', 'Frame', 'Attribute']

    col_to_use = ['Chromosome', 'Software', 'Feature', 'Start', 'Stop', \
                 'Strand']

    TE_Data = pd.read_csv(
            os.path.join(input_dir, gff_filename),
            sep='\t+',
            header=None,
            engine='python',
            names = col_names,
            usecols = col_to_use)

    TE_Data[['Family', 'SubFamily']] = TE_Data.Feature.str.split('/', expand=True)
    TE_Data.SubFamily.fillna(value='Unknown_SubFam', inplace=True) # replace None w U
        # step to fix TE names

    TE_Data = TE_Data.drop(['Feature', 'Software'], axis=1)

    TE_Data = drop_nulls(TE_Data) # Dropping nulls because I checked
    TE_Data.Strand = TE_Data.Strand.astype(str)
    # NOTE see same comment on gene data types
    TE_Data.Start = TE_Data.Start.astype('uint32')
    TE_Data.Stop = TE_Data.Stop.astype('uint32')
    # NOTE see same comment on gene intervals / off-by-one
    TE_Data['Length'] = TE_Data.Stop - TE_Data.Start
    TE_Data = TE_Data[TE_Data.Family != 'Simple_repeat'] # drop s repeat
    TE_Data = replace_names(TE_Data)
    return TE_Data

def replace_names(my_TEs):
    U = 'Unknown'
    master_family = {
        'RC?':'DNA',
        'RC':'DNA',
        'SINE?':U,
        'tandem':'Tandem',
        'No_hits':U
    }

    U = 'Unknown_SubFam'
    master_subfamily = {
        'Uknown':U,
        'MuDr':'MULE',
        'MULE-MuDR':'MULE',
        'Mutator|cleanup':'MULE',
        'TcMar':U,
        'Pao':U,
        'Caulimovirus':U,
        'hAT-Tag1':'hAT',
        'hAT-Tip100':'hAT',
        'hAT-Charlie':'hAT',
        'Helitron':U,
        'unknown':U,
        'Maverick':U,
        'Harbinger':'PIF-Harbinger',
        'TcMar-Pogo':U,
        'CR1':'LINE',
        'hAT-Ac':'hAT',
        'L2':'LINE',
        'L1':'LINE',
        'Jockey':'LINE',
        'MuLE-MuDR':'MULE',
        'MuDR':'MULE',
        'Mutator':'MULE',
        'Micro_like':U,
        'Micro-like-sequence':U,
        'Micro-like-sequence|cleanup':U,
        'Unclassified':U,
        'L1-Tx1':'Line',
        'CRE':'Line',
        'CACTA':'CMC-EnSpm',
        'Tad1':U,
        'hAT|cleanup':'hAT',
        '':U,
        'Line':'LINE'

    }

    my_TEs.Family.replace(master_family, inplace=True)
    my_TEs.SubFamily.replace(master_subfamily, inplace=True)
    return my_TEs

def check_shape(transposon_data):
    """Checks to make sure the columns of the TE data are the same size.

    If the shapes don't match then there are records that are incomplete,
        as in an entry (row) does have all the expected fields (column).
    """

    start = transposon_data.starts.shape
    stop = transposon_data.stops.shape
    if start != stop:
        msg = (" input TE missing fields: starts.shape {}  != stops.shape {}"
               .format(start, stop))
        raise ValueError(msg)

    length = transposon_data.lengths.shape
    if start != length:
        msg = (" input TE missing fields: starts.shape {}  != lengths.shape {}"
               .format(start, stop))
        raise ValueError(msg)

def check_density_shape(densities, transposon_data):
    """ Checks to make sure the density output and the TE column are jiving well"""

    # SCOTT, rather than try / assert / catch AssertionError / raise,
    # just do an if / raise.  -MT
    if densities.shape != transposon_data.starts.shape:
        msg = ("Density dataframe shape not the same size as the TE dataframe")
        raise ValueError(msg)

def gene_names(sub_gene_data):
    """Return unique gene names for the input gene data (e.g. one chromosome)."""

    # MAGIC_NUMBER the gene name column is 'Gene_Name'
    gene_name_id = 'Gene_Name'
    names = sub_gene_data[gene_name_id].unique()
    return names

def rho_intra(gene_data, gene_name, transposon_data):
    """Intra density for one gene wrt transposable elements.

    The relevant ares is the gene for intra density.

    Args:
        gene_data (transponson.data.GeneData): gene container
        gene_name (hashable): name of gene to use
        transposon_data (transponson.data.TransposonData): transposon container
    """

    g0, g1, gL = gene_data.start_stop_len(gene_name)
    # SCOTT pls replace asserts with `raise ValueError`
    # this is so the worker can fail gracefully rather than crashing
    # at the very least there should be a custom string for what was wrong
    # a better solution could be to subclass ValueError for the particular problem
    #assert transposon_data.starts.shape == transposon_data.stops.shape
    #assert transposon_data.starts.shape == transposon_data.lengths.shape
    check_shape(transposon_data)




    # SOTT shouldn't the lower be the start and the upper use the stops?
    lower = np.minimum(g1, transposon_data.stops)
    upper = np.maximum(g0, transposon_data.starts)
    # TODO SCOTT, check in/exclusive stop indices, check zero based indices
    # NOTE we are using 0 indexing, need to double check
    # NOTE is the stop value inclusive or exclusive? the length values imply inclusive
    # and this code works for exclusive...
    te_overlaps =  np.maximum(0, lower - upper)
    genes_length = gene_data.length

    print(type(te_overlaps))
    print(type(genes_length))
    densities = np.divide(
        te_overlaps,
        genes_length,
        out=np.zeros_like(te_overlaps, dtype='float'),
        where=genes_length!=0
    )

    # SCOTT pls replace asserts with `raise ValueError`
    # this is so the worker can fail gracefully rather than crashing
    #assert densities.shape == transposon_data.starts.shape
    check_density_shape(densities,transposon_data)
    return densities

def validate_window(window_start, g0, window):
    if window_start == 0:
        window = g0 - window_start
    return window


def rho_left_window(gene_data, gene_name, transposon_data, window):
    """Density to the left (downstream) of a gene.
    When TE is between gene and window

    Relevant things: No. TE bases / window
    GeneStart so that we may calculate the WindowStart
    WindowStart is unique to each gene. Calculated via Gstart - Window
    WindowStart is the leftmost window

    Args:
        window (int): integer value of the current window
    """
    # TODO make sure the edge cases work when the window should be negative and
    # reset to 0 for that instance
    # so far I can reset the window start for that instance, but I cannot fix
    # the window for the sake of division later when you try to check values.

    g0, g1, gL = gene_data.start_stop_len(gene_name)
    # SCOTT pls replace asserts with `raise ValueError`
    # this is so the worker can fail gracefully rather than crashing
    # at the very least there should be a custom string for what was wrong
    # a better solution could be to subclass ValueError for the particular problem
    #assert transposon_data.starts.shape == transposon_data.stops.shape
    #assert transposon_data.starts.shape == transposon_data.lengths.shape
    check_shape(transposon_data)

    window_start = np.subtract(g0, window)
    window_start = np.clip(window_start, 0, None)  # clamp to [0...inf)
    window = validate_window(window_start, g0, window)

    lower_bound = np.maximum(window_start, transposon_data.starts)
    upper_bound = np.minimum(g0, transposon_data.stops)
    te_overlaps =  np.maximum(0, upper_bound - lower_bound)
    densities = np.divide(
        te_overlaps,
        window,
        out=np.zeros_like(te_overlaps, dtype='float')
    )
    check_density_shape(densities,transposon_data)
    #print(densities)
    #assert densities.shape == transpons_data.starts.shape # misspelled, wrote
    #check
    return densities

def rho_right_window(gene_data, gene_name, transposon_data, window):

    """Density to the right (upstream) of a gene.
    When TE is between gene and window

    Relevant things: No. TE bases / window
    GeneStop so that we may calculate the WindowStop
    WindowStop is unique to each gene. Calculated via Gstop + Window
    WindowStop is the rightmost window

    Args:

    """

    g0, g1, gL = gene_data.start_stop_len(gene_name)
    # SCOTT pls replace asserts with `raise ValueError`
    # this is so the worker can fail gracefully rather than crashing
    # at the very least there should be a custom string for what was wrong
    # a better solution could be to subclass ValueError for the particular problem
    assert g0.shape == ()  # NOTE it's one np.uint32, is there a better way to check?
    check_shape(transposon_data)
    #assert transposon_data.starts.shape == transposon_data.stops.shape
    #assert transposon_data.starts.shape == transposon_data.lengths.shape

    window_stop = np.add(g1, window)
    lower_bound = np.maximum(g1, transposon_data.starts)
    # lower bound gets TE starts to the right of gene stops
    upper_bound = np.minimum(window_stop, transposon_data.stops)
    # upper bound gets TE stops to the left of window stops
    te_overlaps =  np.maximum(0, upper_bound - lower_bound)
    # NOTE it isn't necessary to divide here, right?
    # the relevant area is constant, keep track of it
    # sum the overlaps *then* calculate using the division
    densities = np.divide(
        te_overlaps,
        window,
        out=np.zeros_like(te_overlaps, dtype='float')
    )

    #assert densities.shape == transposon_data.starts.shape

    check_density_shape(densities,transposon_data)
    return densities


def density_algorithm(genes, tes, window, increment, max_window):
    """
    te data frame has columns: SEE import_transposons
    te data frame has rows: each row is a temp


    """
    # NOTE create 2 structs to hold files / param & result

    try:
        get_unique(genes.Chromosome) == get_unique(tes.Chromosome)
    except:
        raise ValueError("You do not have the same chromosomes in your files")


    windows = list(range(window, max_window, increment))
    logging.info(" windows are {}:{}:{}  -->  {}"
                 .format(window, increment, max_window, windows))

    # Use the subsets in main?
    while window <= max_window:
        logging.debug(" Gene df shape:  {}".format(genes.values.shape))
        logging.debug(" TE df shape:  {}".format(tes.values.shape))
        # Perform the windowing operations
        # Multiple tests need to be done here for each window
        # All the tests must be run for that window and then rerun for the
        # next window
        # I foresee that for each gene file we will have an output wiht all
        # of the original gene data and the output will be 500_LTR_Upstream
        # The TE types (LTR) are given by the TE_Dataframe.Family and
        # TE_Dataframe.SubFamily columns

        # The init_empty_densities function was to add the appropriate
        # columns, we may not need to worry about that for now


        # All the commented code below are my attempts to do the work
        #-----------------------------
        get_head(genes)
        save_output(genes, 'Test_Output.csv')
        window += increment

def init_empty_densities(my_genes, my_tes, window):
    """Initializes all of the empty columns we need in the gene file. """

    Family_List = my_tes.Family.unique()
    SubFamily_List = my_tes.SubFamily.unique()
    Directions = ['_downstream', '_intra', '_upstream']
    # left, center, right

    for family in Family_List:
        for direction in Directions:
            col_name = (str(window) + '_' + family + direction)
            my_genes[col_name] = np.nan

    for subfamily in SubFamily_List:
        for direction in Directions:
            col_name = (str(window) + '_' + family + direction)
            my_genes[col_name] = np.nan
    my_genes['TEs_inside'] = np.nan
    return my_genes

def check_groupings(grouped_genes, grouped_TEs, logger):
    """Validates the gene / TE pairs.

    This is just to make sure that each pair of chromosomes are right.
    Correct subsetting would be managed by the custom split command.

    Args:
        grouped_genes (list of pandaframes): Gene dataframes separated by chromosome
        grouped_TEs (list of pandaframes): TE dataframes separated by chromosome
    """

    try:  # TODO SCOTT, pls replace with an if / raise as it is much more concise, -M
        for g_element, t_element in zip(grouped_genes, grouped_TEs):
            assert g_element.Chromosome.iloc[0:10].values[0] == \
            t_element.Chromosome.iloc[0:10].values[0]
    except AssertionError as error:
        msg = 'Chromosomes do not match for the grouped_genes or grouped_TEs'
        logger.critical(msg)
        raise ValueError(msg)

def validate_args(args, logger):
    """Raise if an input argument is invalid."""

    if not os.path.isdir(args.input_dir):
        logger.critical("argument 'input_dir' is not a directory")
        raise ValueError("%s is not a directory"%(abs_path))
    if not os.path.isdir(args.output_dir):
        logger.critical("argument 'output_dir' is not a directory")
        raise ValueError("%s is not a directory"%(abs_path))

if __name__ == '__main__':
    """Command line interface to calculate density."""

    parser = argparse.ArgumentParser(description="calculate TE density")
    path_main = os.path.abspath(__file__)
    parser.add_argument('input_dir', type=str,
                        help='parent directory of gene & transposon files')
    parser.add_argument('--output_dir', '-o', type=str,
                        default=os.path.join(path_main, '../..', 'results'),
                        help='parent directory to output results')
    parser.add_argument('-v', '--verbose',
                        action='store_true',
                        help='set debugging level to DEBUG')
    args = parser.parse_args()
    args.output_dir = os.path.abspath(args.output_dir)
    args.input_dir = os.path.abspath(args.input_dir)
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logger = logging.getLogger(__name__)
    coloredlogs.install(level=log_level)
    logger.info("start processing directory '%s'"%(args.input_dir))
    for argname, argval in vars(args).items():
        logger.debug("%-12s: %s"%(argname, argval))
    validate_args(args, logger)

    # FUTURE move this preprocessing to it's object
    logger.info("importing genes, this may take a moment...")
    Gene_Data = import_genes(args.input_dir)
    print("\ngene data...")
    get_head(Gene_Data)
    # NOTE grouped_genes is a list of all the data frames
    grouped_genes = split(Gene_Data, 'Chromosome') # check docstring for my split func

    logger.info("importing transposons, this may take a moment...")
    TE_Data = import_transposons(args.input_dir)
    print("\nTE data...")
    get_head(TE_Data)
    grouped_TEs = split(TE_Data, 'Chromosome') # check docstring for my split func

    check_groupings(grouped_genes, grouped_TEs, logger)
    # Think of the 7 main "chromosomes" as "meta-chromosomes" in reality there
    # are 4 actual chromosomes per "meta-chromosome" label. So Fvb1 is
    # meta-chromosome 1, and within that Fvb1-1 of genes should only be
    # matching with Fvb1-1 of TEs, not Fvb1-2. The first number, what I am
    # calling the "meta-chromosome" is just denoting that it is the first
    # chromosome, where the second number is the actual physical chromosome,
    # and we use the number to denote which subgenome it is assigned to.

    gene_progress = tqdm(total=len(grouped_genes), desc="sub genes", position=0)
    for sub_gene, sub_te in zip(grouped_genes, grouped_TEs):
        gene_data = GeneData(sub_gene)
        te_data = TransposonData(sub_te)
        # TODO validate the gene / te pair

        # This subset if genes is on a chromosome by chromosome basis
        # I will perform my windowing operations on this subset

        # FUTURE multiprocess starting here
        # create workers
        # create accumulators
        window_it = lambda : range(100, 1000, 100)  # TODO remove magic numbers, parametrize
        window_progress = tqdm(total=len(window_it()), desc="windows", position=1)
        for window in range(100, 4000, 100):
            # create density request, push

            # density_algorithm(
            #                 Gene_Data,
            #                 TE_Data,
            #                 window=1000,
            #                 increment=500,
            #                 max_window=10000
            #                 )

            time.sleep(0.025)
            window_progress.update(1)
            gene_progress.refresh()
        # collapse accumulated results (i.e. do the division)
        # combine all the results
        # write to disk
        gene_progress.update(1)
