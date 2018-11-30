import os
import tarfile
import logging
import re
from tempfile import TemporaryDirectory
from .sanger_qc_extractor import SangerQcMetricsExtractor, set_extractor_logger_level
from . import get_abs_path, check_file_exists
from typing import List, Dict, Tuple, Any

# TODO Change inputs to lists, complain if tumour samples have duplicated names, complain if missing bas files, warning if there're more tumour or normal bas files!
# TODO use tumour sample names as folder names in output, put genotype files in it
# TODO all metrics to one file
# TODO tar the folder and metrics file in one ball!!


# setup logs
logger = logging.getLogger('ppcg_qc_from_sanger')
# create console handler and set level to debug
cha = logging.StreamHandler()
cha.setLevel(logging.DEBUG)
cha.setFormatter(logging.Formatter('%(asctime)s %(levelname)8s - %(message)s',
                                   '%Y-%m-%d %H:%M:%S'))
# add ch to logger
logger.addHandler(cha)
logger.setLevel(logging.DEBUG)

BAS_HEADER = [
    'bam_filename',
    'sample',
    'platform',
    'platform_unit',
    'library',
    'readgroup',
    'read_length_r1',
    'read_length_r2',
    '#_mapped_bases',
    '#_mapped_bases_r1',
    '#_mapped_bases_r2',
    '#_divergent_bases',
    '#_divergent_bases_r1',
    '#_divergent_bases_r2',
    '#_total_reads',
    '#_total_reads_r1',
    '#_total_reads_r2',
    '#_mapped_reads',
    '#_mapped_reads_r1',
    '#_mapped_reads_r2',
    '#_mapped_reads_properly_paired',
    '#_gc_bases_r1',
    '#_gc_bases_r2',
    'mean_insert_size',
    'insert_size_sd',
    'median_insert_size',
    '#_duplicate_reads',
    '#_mapped_pairs',
    '#_inter_chr_pairs']

OUTPUT_HEADER = [
    'Tumour sample name',
    'Tumour ID',
    'Tumour UUID',
    'Tumour sequencing year',
    'Tumour sequencer',
    'Tumour ReadGroup IDs',
    'Tumour depth per RG',
    'Tumour total depth',
    'Tumour fraction of mapped reads per RG',
    'Tumour mean fraction of mapped reads',
    'Tumour insert size per RG',
    'Tumour mean Insert size',
    'Tumour insert size sd per RG',
    'Tumour mean insert size sd',
    'Tumour r1 GC content per RG',
    'Tumour mean r1 GC content',
    'Tumour r2 GC content per RG',
    'Tumour mean r2 GC content',
    'Tumour fraction of duplicated reads per RG',
    'Tumour mean fraction of duplicated reads',
    'Tumour fraction of mis-matched pairs per RG',
    'Tumour mean fraction of mis-matched pairs',
    'Tumour contamination per RG',
    'Tumour mean contamination',
    'Tumour sex',
    'Tumour fraction of matched sex with Normal',
    'Tumour fraction of matched genotype with Normal',
    'Normal contamination in Tumour',
    'Normal sample name',
    'Normal ID',
    'Normal UUID',
    'Normal sequencing year',
    'Normal sequencer',
    'Normal ReadGroup IDs',
    'Normal depth per RG',
    'Normal total depth',
    'Normal fraction of mapped reads per RG',
    'Normal mean fraction of mapped reads',
    'Normal insert size per RG',
    'Normal mean Insert size',
    'Normal insert size sd per RG',
    'Normal mean insert size sd',
    'Normal r1 GC content per RG',
    'Normal mean r1 GC content',
    'Normal r2 GC content per RG',
    'Normal mean r2 GC content',
    'Normal fraction of duplicated reads per RG',
    'Normal mean fraction of duplicated reads',
    'Normal fraction of mis-matched pairs per RG',
    'Normal mean fraction of mis-matched pairs',
    'Normal contamination per RG',
    'Normal mean contamination',
    'Donor ID',
    'Donor UUID',]

VARIANT_COUNT_HEADER = [
    'Number of SNVs (PASS/All)', 'Number of INDELs (PASS/All)', 'Number of SVs (PASS/All)', 'Number of CNVs']


def extract_from_sanger(args):
    '''
    the main function for handling the whole QC metrics extraction process
    '''
    if not args.debug:
        logger.setLevel(logging.INFO)
        set_extractor_logger_level(logging.INFO)

    genome_size = args.genome_size
    if not isinstance(genome_size, int):
        logger.critical('genome_size is not int')
        raise RuntimeError('genome_size is not int')

    output_tar = get_abs_path(args.output_tar)
    # if tar file has '.tar.gz' extension
    SangerQcMetricsExtractor.validate_tar_name(output_tar)

    # test if output is writable
    if not os.path.exists(output_tar):
        try:
            with open(output_tar, 'w') as out:
                out.write('place holder\n')
        except OSError as exc:
            logger.critical('output is not writable: %s.', str(exc))
            raise RuntimeError('output is not writable: %s.' % str(exc))
        finally:
            os.remove(output_tar)
    else:
        logger.critical('existing output file: %s.', output_tar)
        raise RuntimeError('existing output file: %s.' % output_tar)

    tumour_bas = get_all_bas(args.tumour_bas)
    normal_bas = get_all_bas(args.normal_bas)
    variant_call_tars = get_all_variant_call_tar(args.variant_call_tar)

    t_n_pair_tar, t_name_bas, n_name_bas = \
        get_validated_tn_pair_and_bas_lists(tumour_bas, normal_bas, variant_call_tars)
    if args.metadata:
        metadata_list = get_all_meta(args.metadata)
        t_n_pair_meta = get_t_n_pair_meta(metadata_list, t_n_pair_tar.keys())

    count_variants = args.count_variants
    # print('count_variants', count_variants)

    # create a temp dir to store extracted files
    with TemporaryDirectory() as temp_dir:
        # print(temp_dir)
        # metadata = {
        #     'tumour_id': 't_sample',
        #     'tumour_uuid': 't_uuid_uuid',
        #     'tumour_sequencing_year': '1910',
        #     'tumour_sequencer': 'sanger',
        #     'normal_sequencing_year': 2018,
        #     'normal_sequencer': 'novoseq',
        #     'normal_id': 'n_sample',
        #     'normal_uuid': 'n_uuid_uuid',
        #     'donor_uuid': 'd_uuid-uuid'
        # }

        output_metrics_file = os.path.join(temp_dir, 'ppcg_sanger_metrics.txt')
        genotyping_files = []

        with open(output_metrics_file, 'w') as o:
            header = OUTPUT_HEADER
            if count_variants:
                header += VARIANT_COUNT_HEADER
            o.write('\t'.join(header) + '\n')

            for t_n_pair, v_tar in t_n_pair_tar.items():
                print('meta:', t_n_pair_meta[t_n_pair])
                extractor = SangerQcMetricsExtractor(t_name_bas[t_n_pair[0]], n_name_bas[t_n_pair[1]], genome_size, v_tar, temp_dir, count_variants, t_n_pair_meta[t_n_pair])
                o.write('\t'.join(extractor.get_metrics()) + '\n')
                genotyping_files.extend(extractor.get_genotyping_files())
                extractor.clean_output_dir()

        # tar all files in temp_dir to the ourput_tar
        try:
            with tarfile.open(output_tar, 'w:gz') as tar:
                tar.add(output_metrics_file, arcname=os.path.basename(output_metrics_file))
                for a_file in genotyping_files:
                    tar.add(a_file, arcname=os.path.basename(a_file))
        except Exception as exc:
            logger.critical('failed to create the final output: %s', str(exc))
            raise RuntimeError('failed to create the final output: %s' % str(exc))
    logger.info('completed')


def get_all_bas(input_abs: List[str]):
    to_return = []
    for path in input_abs:
        check_file_exists(path)
        if os.path.isdir(path):
            logger.debug('%s is a directory, will take all BAS files in the folder, but not any file in a sub directory.', path)
            for a_file in os.listdir(path):
                if not os.path.isdir(a_file) and re.match(r'.+\.bam\.bas$', a_file):
                    SangerQcMetricsExtractor.validate_bas(a_file)
                    to_return.append(get_abs_path(a_file))
        else:
            SangerQcMetricsExtractor.validate_bas(path)
            to_return.append(get_abs_path(path))
    return to_return


def get_all_variant_call_tar(input_call_tars: List[str]):
    to_return = []
    for path in input_call_tars:
        check_file_exists(path)
        if os.path.isdir(path):
            logger.debug('%s is a directory, will take all tar.gz files in the folder, but not any file in a sub directory.', path)
            for a_file in os.listdir(path):
                if not os.path.isdir(a_file) and re.match(r'\.tar.gz$', a_file):
                    to_return.append(get_abs_path(a_file))
        else:
            SangerQcMetricsExtractor.validate_tar_name(path)
            to_return.append(get_abs_path(path))
    return to_return


def get_validated_tn_pair_and_bas_lists(tumour_bas: List[str], normal_bas: List[str], variant_call_tars: List[str]) -> Tuple[Dict[Tuple[str, str], str], Dict[str, str], Dict[str, str]]:
    t_n_pair_tar: Dict[Tuple[str, str], str] = get_all_t_n_pairs(variant_call_tars)
    expected_tumours = [a_pair[0] for a_pair in t_n_pair_tar.keys()]
    expected_normals = [a_pair[1] for a_pair in t_n_pair_tar.keys()]
    t_name_bas: Dict[str, str] = get_sample_names_bas_file_dict(tumour_bas)
    n_name_bas: Dict[str, str] = get_sample_names_bas_file_dict(normal_bas)

    # if all expected tumour have bas
    not_found = sorted(set(expected_tumours) - set(t_name_bas.keys()))
    if not_found:
        logger.critical('Missing BAS files for tumour samples: %s', ', '.join(not_found))
        raise RuntimeError('Missing BAS files for tumour samples: %s' % ', '.join(not_found))
    # if all expected normal have bas
    not_found = sorted(set(expected_normals) - set(n_name_bas.keys()))
    if not_found:
        logger.critical('Missing BAS files for normal samples: %s', ', '.join(not_found))
        raise RuntimeError('Missing BAS files for normal samples: %s' % ', '.join(not_found))

    return t_n_pair_tar, t_name_bas, n_name_bas


def get_all_t_n_pairs(variant_call_tars) -> Dict[Tuple[str, str], str]:
    t_n_pair_tar = {}
    for a_tar in variant_call_tars:
        t_name = n_name = None
        with tarfile.open(a_tar, 'r:gz') as tar:
            logger.info('getting file list info from tar file %s', a_tar)
            all_files = tar.getmembers()
            for a_file in all_files:
                matches = re.match(r'^WGS_([\w\-]+)_vs_([\w\-]+)$', a_file.name)
                if matches:
                    t_name = matches.group(1)
                    n_name = matches.group(2)
                    break
        if not t_name:
            logger.critical(f'Not a valid Sanger Variant Call result archive: {a_tar}')
            raise RuntimeError(f'Not a valid Sanger Variant Call result archive: {a_tar}')
        t_n_pair_tar[(t_name, n_name)] = a_tar
    return t_n_pair_tar


def get_sample_names_bas_file_dict(bas_list):
    return {
        SangerQcMetricsExtractor.get_sample_name_from_bas(SangerQcMetricsExtractor.get_bas_content(bas)): bas
        for bas in bas_list
    }


def get_all_meta(metadata_paths): 
    to_return = []
    for path in metadata_paths:
        check_file_exists(path)
        if os.path.isdir(path):
            logger.debug('%s is a directory, will take all tsv files in the folder, but not any file in a sub directory.', path)
            for a_file in os.listdir(path):
                if not os.path.isdir(a_file) and re.match(r'.+\.tsv$', a_file):
                    to_return.append(get_abs_path(a_file))
        else:
            to_return.append(get_abs_path(path))
    return to_return


def get_t_n_pair_meta(meta_files, t_n_pairs: List[str]) -> Tuple[Dict[str, dict], Dict[str, dict]]:
    # sample_id_meta = {}
    # sample_uuid_meta = {}
    # for meta_file in meta_files:
    #     with open(meta_file, 'r') as meta:
    #         # TODO use pandas
    #         # concatecate all meta into one big dataframe.
    return (1,2)
