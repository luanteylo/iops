#!/usr/bin/env python3

import csv
import argparse
import os
from datetime import date
from argparse import RawTextHelpFormatter
import json

app_version = "1.0.0"
app_name = "ifstat_2_csv"
app_description = f"""
    {app_name} version {app_version}

    This tool read the output file of the ifstat_loop.sh and generate a .csv file.

    The following information are get from the ifstat_loop file:    

    timestamp, rx_packets, rx_bytes, tx_packets, tx_bytes 

    Authors: 
    Luan Teylo (2021)
    """


def get_interfaces(input_file):
    # open ifstat file and get the network interfaces info from the first line
    with open(input_file) as f:
        line = f.readline()
        return json.loads(",".join(line.split(",")[1:]))['kernel'].keys()


#
def generate_csv(input_file, output_csv, interfaces):
    # firstly lets create the CSV's header
    header = ['timestamp']
    for it in interfaces:
        header.extend([f"{it}_rx_packets",
                       f"{it}_rx_bytes",
                       f"{it}_tx_packets",
                       f"{it}_tx_bytes"])

    # then, lets open the csv file in the write mode
    f_csv = open(output_csv, 'w')
    writer = csv.writer(f_csv)

    # and write the header
    writer.writerow(header)

    with open(input_file) as f:
        # For each line of ifstate_loop file lets get the timestamp following by the json ifstat output
        for line in f.readlines():
            timestamp = line.split(",")[0]
            info = json.loads(",".join(line.split(",")[1:]))
            # then, we create the row_data by getting each interface info
            row_data = [timestamp]
            for it in interfaces:
                row_data.extend([info['kernel'][it]['rx_packets'],
                                 info['kernel'][it]['rx_bytes'],
                                 info['kernel'][it]['tx_packets'],
                                 info['kernel'][it]['tx_bytes']])

            # and write it on the csv file
            writer.writerow(row_data)

    f_csv.close()


def main():
    parser = argparse.ArgumentParser(formatter_class=RawTextHelpFormatter, description=app_description)

    parser.add_argument('input_file', help='Full path to ifstat_loop file', type=str)
    parser.add_argument('-o', '--output',
                        help="full name for the output file  (default: ./output.csv)",
                        type=str,
                        default="ifstat.csv")

    args = parser.parse_args()

    hello_msg = f'''
    # {60 * '#'}
    # Processing IFSTAT_loop File
    # Date: {date.today()}
    # Used Parameters:
    #./{app_name}  {args.input_file} --o {args.output}
    # {60 * '#'}\n\n\n'''

    print(hello_msg)

    # Load the data
    interfaces = get_interfaces(args.input_file)
    generate_csv(input_file=args.input_file, output_csv=args.output, interfaces=interfaces)


if __name__ == "__main__":
    main()
