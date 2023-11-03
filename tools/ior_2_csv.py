#!/usr/bin/env python3

import argparse
import os
from argparse import RawTextHelpFormatter
from datetime import date
from pathlib import Path
import csv


app_version = "2.0.0"
app_name = "ior_2_csv"
app_description = f"""
    {app_name} version {app_version}

    
    This tool reads all IOR benchmark's batch files in a folder and generate a CSV file. 
    
    
    The following information are get from the IOR files:    
        access
        bw
        iops
        latency
        block:
        xfer
        open
        wr/rd
        close
        total
        iter



    History:
    v1.0: may 2021
    v2.0: oct 2021
    
    Authors: 
    Luan Teylo (2021)    
    
    """


class Loader:
    info_pos = {
        'access': 0,
        'bw': 1,
        'iops': 2,
        'latency': 3,
        'block': 4,
        'xfer': 5,
        'open': 6,
        'wr/rd': 7,
        'close': 8,
        'total': 9,
        'iter': 10
    }

    timestamp_start = 'start'
    timestamp_end = 'end'
    nodes_name = 'nodes'
    tasks_name = 'tasks'
    clients_per_node_name = 'clients_per_node'
    blocksize_name  = 'blocksize'
    aggregate_filesize_name  = 'aggregate_filesize'

    def __init__(self, files, verbose):
        self.files = files
        self.verbose = verbose

        self.data = self.__build_data_dictionary()
     
    def __convert_to_bytes(self, size_str):
        # Define conversion factors
        size_units = {"B": 1, "KiB": 2**10, "MiB": 2**20, "GiB": 2**30, "TiB": 2**40}

        # Split input string into numeric and unit parts
        size, unit = [x.strip() for x in size_str.split()]

        # Convert the size to bytes
        size_in_bytes = float(size) * size_units[unit]
        
        return int(size_in_bytes)

    # Aggregate data by block_size
    def __build_data_dictionary(self):
        # For each file we will extract and aggregate the info we want
        data_by_block = {}

        for file in self.files:
            if self.verbose:
                print(f"Processing file {file}...")

            startTime = None
            finishedTime = None
            current_block = None

            
            nodes = None
            tasks = None
            clients_per_node = None            
            blocksize  = None
            aggregate_filesize  = None
            


            with open(file) as fp:
                second_time = False

                for line in fp:
                    # Firstly we search by the 'StartTime' Tag
                    if line.startswith('StartTime'):
                        startTime = "".join(line.split()[2:])                  
                    elif line.startswith('nodes'):
                        nodes =  "".join(line.split(':')[-1]).strip()
                    elif line.startswith('tasks'):
                        tasks =  "".join(line.split(':')[-1]).strip()
                    elif line.startswith('clients per node'):
                        clients_per_node =  "".join(line.split(':')[-1]).strip()
                    elif line.startswith('blocksize'):
                        blocksize =  self.__convert_to_bytes("".join(line.split(':')[-1]).strip())
                    elif line.startswith('aggregate filesize'):
                        aggregate_filesize = self.__convert_to_bytes("".join(line.split(':')[-1]).strip())
                    # Then we find the line we want to get the information
                    # Since IOR already put a <TaG> on the beggining of the write line
                    # We can use it to find the line
                    elif line.startswith('write'):
                        if not second_time:
                            # then we split the info and
                            # aggregate it in a dictionary where the key is the blockSize parameter
                            splitted = line.split()

                            current_block = block = int(float(splitted[self.info_pos['block']]))  # block size

                            for key in self.info_pos.keys():
                                # check if the block already exist
                                if block not in data_by_block:
                                    data_by_block[block] = {}
                                # check if the list for the key feature of the block was already create
                                if key not in data_by_block[block]:
                                    data_by_block[block][key] = []

                                # ADD the key feature of the block to the list
                                data_by_block[block][key].append(splitted[self.info_pos[key]])

                            second_time = True
                        else:
                            second_time = False

                    elif line.startswith('Finished'):
                        finishedTime = " ".join(line.split()[2:])

                        # print(f"Start: {startTime}, End: {finishedTime}")

                        # update data_by_block
                        if self.timestamp_start not in data_by_block[current_block]:
                            data_by_block[current_block][self.timestamp_start] = []

                        if self.timestamp_end not in data_by_block[current_block]:
                            data_by_block[current_block][self.timestamp_end] = []
                        
                        if self.nodes_name not in data_by_block[current_block]:
                            data_by_block[current_block][self.nodes_name] = []
                        
                        if self.tasks_name not in data_by_block[current_block]:
                            data_by_block[current_block][self.tasks_name] = []
                        
                        if self.clients_per_node_name not in data_by_block[current_block]:
                            data_by_block[current_block][self.clients_per_node_name] = []

                        if self.blocksize_name not in data_by_block[current_block]:
                            data_by_block[current_block][self.blocksize_name] = []
                        
                        if self.aggregate_filesize_name not in data_by_block[current_block]:
                            data_by_block[current_block][self.aggregate_filesize_name] = []

                        data_by_block[current_block][self.timestamp_start].append(startTime)
                        data_by_block[current_block][self.timestamp_end].append(finishedTime)
                        data_by_block[current_block][self.nodes_name].append(nodes)
                        data_by_block[current_block][self.tasks_name].append(tasks)
                        data_by_block[current_block][self.clients_per_node_name].append(clients_per_node)
                        data_by_block[current_block][self.blocksize_name].append(blocksize)
                        data_by_block[current_block][self.aggregate_filesize_name].append(aggregate_filesize)


        return data_by_block

    

    def write_csv_by_tag(self, keys, tag, output_file, write_mode='w'):

        first_line = [tag, 'timestamp_start', 'timestamp_end', 'blocksize']

        with open(output_file, write_mode) as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(first_line)

            # building the list of features by key
            for key in keys:
                rows = zip(self.data[key][tag],
                           self.data[key][self.timestamp_start],
                           self.data[key][self.timestamp_end])

                for row in rows:
                    # Add key to the csv Row
                    row = row + (f"{int(key / 1024.0)}MiB",)
                    writer.writerow(row)

    # write_csv_all

    def write_csv_all(self, keys, output_file, write_mode='w'):

        first_line = ['access', 'bw', 'iops', 'latency', 'block', 
                      'xfer', 'open', 'wr/rd', 'close', 'total', 
                      'iter', 'start', 'end', 
                      'nodes', 'tasks', 'clients_per_node', 
                      'blocksize_bytes', 'aggregate_filesize' ]
     
        all_rows = []

        # building the list of features by key
        for key in keys:
            rows = zip(self.data[key]['access'],
                       self.data[key]['bw'],
                       self.data[key]['iops'],
                       self.data[key]['latency'],
                       self.data[key]['block'],
                       self.data[key]['xfer'],
                       self.data[key]['open'],
                       self.data[key]['wr/rd'],
                       self.data[key]['close'],
                       self.data[key]['total'],
                       self.data[key]['iter'],
                       self.data[key][self.timestamp_start],
                       self.data[key][self.timestamp_end],
                       self.data[key][self.nodes_name],
                       self.data[key][self.tasks_name],
                       self.data[key][self.clients_per_node_name],
                       self.data[key][self.blocksize_name],
                       self.data[key][self.aggregate_filesize_name])
            all_rows.extend(rows)

        all_rows.sort(key=lambda x: x[-1], reverse=False)

        # Check if the folder exist
        output_path = Path(output_file).parent
        if not output_path.exists():
            output_path.mkdir(parents=True)

        with open(output_file, write_mode) as csv_file:
            writer = csv.writer(csv_file)

            writer.writerow(first_line)

            for row in all_rows:
                # Add key to the csv Row
                writer.writerow(row)


def main():
    parser = argparse.ArgumentParser(formatter_class=RawTextHelpFormatter, description=app_description)

    parser.add_argument('fullpath', help=f"The path for raw files.")   
    parser.add_argument('output', help="file name of the output CSV file.")
    parser.add_argument('-e', '--extension', type=str, default='.out', help='File extension to filter by.')        
    parser.add_argument('-v', '--verbose', help="Verbose - print the dictionary with all arguments.", action='store_true')

    args = parser.parse_args()

    hello_msg = f'''
       # {60 * '#'}
       # Processing IOR output Files
       # Date: {date.today()}
       # Used Parameters:
       #./{app_name}   {args.fullpath}    --e {args.extension} --o {args.output} --v {args.verbose}
       # {60 * '#'}\n\n\n'''

    if args.verbose:
        print(hello_msg)
    
    fullpath = Path(args.fullpath)
    search_by = args.extension   

    # Use rglob to search recursively
    files = set(fullpath.rglob('*' + search_by))

    # Load the data
    ld = Loader(files=files, verbose=args.verbose)

    keys = [key for key in ld.data.keys()]
    keys.sort()

    output_file = Path(args.output)

    if args.verbose:
        print(f"Output: {output_file}...")

    ld.write_csv_all(keys=keys,
                     output_file=output_file,
                     write_mode='w')


if __name__ == "__main__":
    main()
