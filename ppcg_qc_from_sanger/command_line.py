"""
Handle the command line parsing and select the correct sub process.
"""

import argparse
import sys
import pkg_resources  # part of setuptools
import os.path

from ppcg_qc_from_sanger.extract_qc import extract_from_sanger

version = pkg_resources.require("ppcg-qc-from-sanger")[0].version


def main():
    """
    Sets up the parser and handles triggereing of correct sub-command
    """
    common_parser = argparse.ArgumentParser('parent', add_help=False)
    common_parser.add_argument('-v', '--version', action='version', version='%(prog)s ' + version)

    parser = argparse.ArgumentParser(prog='ppcg-qc-from-sanger', parents=[common_parser])

    parser.add_argument(
        '-tb', '--tumour_bas',
        dest='tumour_bas',
        metavar='FILE',
        help='Tumour sample BAS file (.bam.bas) from cgpmap pipeline.',
        required=True)
    parser.add_argument(
        '-nb', '--normal_bas',
        dest='normal_bas',
        metavar='FILE',
        help='Normal sample BAS file (.bam.bas) from cgpmap pipeline.',
        required=True)
    parser.add_argument(
        '-rt', '--variant_call_tar',
        dest='variant_call_tar',
        metavar='FILE',
        help='The compressed tar result file from cgpwgs variant calling pipeline of the two samples, requires ".tar.gz" extension.',
        required=True)
    parser.add_argument(
        '-o', '--output_tar',
        dest='output_tar',
        metavar='STRING',
        type=str,
        help='the file name of the compressed tar result, requires ".tar.gz" extension.',
        required=True)
    parser.add_argument(
        '-gs', '--genome_size',
        dest='genome_size',
        type=int,
        help='The genome size, default to GRCh37 size, which is 3,137,454,505.',
        default=3137454505)
    parser.add_argument(
        '-d', '--debug',
        action='store_true', help='print more info for debug.')
    parser.set_defaults(func=extract_from_sanger)

    args = parser.parse_args()
    if len(sys.argv) > 1:
        args.func(args)
    else:
        sys.exit('\nERROR Arguments required\n\tPlease run: ppcg-qc-from-sanger --help\n')
