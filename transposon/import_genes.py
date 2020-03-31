import pandas as pd


def import_genes(genes_input_path, contig_del):
    """Import genes file.

    Args:
        input_dir (command line argument) Specify the input directory of the gene
        annotation data, this is the same as the TE annotation directory

        contig_drop (bool): logical whether to drop rows with a contig as the
        chromosome id
    """

    col_names = ['Chromosome', 'Software', 'Feature', 'Start', 'Stop',
                 'Score', 'Strand', 'Frame', 'FullName']

    col_to_use = ['Chromosome', 'Software', 'Feature', 'Start', 'Stop',
                  'Strand', 'FullName']

    Gene_Data = pd.read_csv(
        genes_input_path,
        sep='\t+',
        header=None,
        engine='python',
        names=col_names,
        usecols=col_to_use)

    Gene_Data = Gene_Data[~Gene_Data.Chromosome.str.contains('#')]  # remove comment
    # rows in annotation
    Gene_Data = Gene_Data[Gene_Data.Feature == 'gene']  # drop non-gene rows

    # clean the names and set as the index (get row wrt name c.f. idx)
    Gene_Data[['Name1', 'Gene_Name']] = \
        Gene_Data.FullName.str.split(';Name=', expand=True)
    Gene_Data.set_index('Gene_Name', inplace=True)
    Gene_Data = Gene_Data.drop(['FullName', 'Name1', 'Software'], axis=1)

    Gene_Data.Strand = Gene_Data.Strand.astype(str)
    Gene_Data.Start = Gene_Data.Start.astype('uint32')
    Gene_Data.Stop = Gene_Data.Stop.astype('uint32')
    Gene_Data['Length'] = Gene_Data.Stop - Gene_Data.Start + 1

    if contig_del:
        Gene_Data = Gene_Data[~Gene_Data.Chromosome.str.contains('contig')]

    # We will not swap Start and Stop for Antisense strands. We will do this
    # post-processing
    # col_condition = Gene_Data['Strand'] == '-'
    # Gene_Data = swap_columns(Gene_Data, col_condition, 'Start', 'Stop')
    return Gene_Data
