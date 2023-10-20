#!/usr/bin/env python3

import argparse
import os
from argparse import RawTextHelpFormatter
from datetime import date
from pathlib import Path
import csv
import glob
import paramiko
from stat import S_ISDIR as isdir

app_version = "2.0.0"
app_name = "ior_2_csv"
app_description = f"""
    {app_name} version {app_version}

    
    This tool reads all IOR benchmark's batch files in a folder and generate a CSV file. 
    
    Since Version 2.0.0 the option --get_files added the function of downloaded the files from the remote host 
    before generate the CSV.  
    
    
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

class GetFiles:
    """
    A class able to connect to a server and download files using sftp
    """

    def __init__(self, host_name, remote_dir: str, local_dir: str, verbose: bool = False):
        self.host_name = host_name
        self.remote_dir = remote_dir
        self.local_dir = local_dir
        self.verbose = verbose

        try:

            self.client = self.__connect()
            self.sftp = self.client.open_sftp()

            # Set the cipher to use
            self.sftp.get_channel().get_transport().get_security_options().ciphers = ['aes256-cbc']


            if self.verbose:
                print(f"Connected to {self.host_name}")
        except Exception as e:
            print(e)
            raise

    def __get_files(self, checker_function):
        """
        get files testing a condition defined in the checker_function
        :param checker_function: a function that receives the file name and return True or False.
        Used to determine if a file will be or not downloaded
        :return:
        """
        # Create the local dir, if it does not exist
        Path(self.local_dir).mkdir(parents=True, exist_ok=True)

        # for each element in the remote_dir, check if it is a valid file
        try:
            for remote_file_name in self.sftp.listdir(self.remote_dir):
                # check if is a file
                if not isdir(self.sftp.stat(os.path.join(self.remote_dir, remote_file_name)).st_mode):
                    # considers a function pass as argument
                    if checker_function(remote_file_name):
                        if self.verbose:
                            print(f"Downloading file {remote_file_name}...")
                        self.sftp.get(os.path.join(self.remote_dir, remote_file_name),
                                      os.path.join(self.local_dir, remote_file_name))
                    elif self.verbose:
                        print(f"File {remote_file_name} will not be downloaded.")
        except FileNotFoundError:
            print("File not Found!")
            exit(1)

    def get_all_files(self):
        """
        download all remote files from the remote_dir
        :return:
        """
        try:
            # ALl files condition is all true
            def checker_funtion(file_name):
                return True

            self.__get_files(checker_funtion)

        except Exception as e:
            print(e)
            raise

    def get_files_per_extension(self, exts):
        """
        download remote files from remote_dir considering its extension.
        :param exts: list of file extension (ex: [.txt, .out, .bin]).
        If extensions is empty all files will be transferred
        :return:
        """

        # define a function that checks if file extension is in the exts list
        def checker_funtion(file_name): return Path(file_name).suffix in exts

        self.__get_files(checker_funtion)

    def get_a_file(self, file):
        """
        download file_name from remote_dir.
        :param file: the file that will be downloaded
        :return:
        """

        # define a function that checks if file extension is in the exts list
        def checker_funtion(file_name): return file_name == file

        self.__get_files(checker_funtion)

    def __connect(self):
        """
        connects to the server considering the .ssh/config file
        :return: paramiko client
        """
        conf = paramiko.SSHConfig()
        conf.parse(open(os.path.expanduser('~/.ssh/config')))
        host = conf.lookup(self.host_name)

        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        # print(host)
        client.connect(
            host['hostname'], username=host['user'],
            # if you have a key file
            # key_filename=host['identityfile'],
            # password='yourpassword',
            sock=paramiko.ProxyCommand(host.get('proxycommand'))
        )

        return client



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

    def __init__(self, files, verbose):
        self.files = files
        self.verbose = verbose

        self.data = self.__build_data_dictionary()

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

            with open(file) as fp:
                second_time = False

                for line in fp:
                    # Firstly we search by the 'StartTime' Tag
                    if line.startswith('StartTime'):

                        startTime = " ".join(line.split()[2:])

                    # Second we find the line we want to get the information
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

                        data_by_block[current_block][self.timestamp_start].append(startTime)
                        data_by_block[current_block][self.timestamp_end].append(finishedTime)

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

        first_line = ['access', 'bw', 'iops', 'latency', 'block', 'xfer', 'open', 'wr/rd', 'close', 'total', 'iter',
                      'start', 'end']
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
                       self.data[key][self.timestamp_end])
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

    parser.add_argument('path', help=f"""the path for raw files.
                        Warning: The full path is given considering vars $WORKDIR_LOCAL/path and 
                        $WORKDIR_REMOTE/path""")

    parser.add_argument('--get_files',
                        help=f"""Uses scp to transfer the raw files generated during the test from the cluster 
                        to the local machine.  Warning: This option requires $HOST_REMOTE""",
                        action='store_true')

    parser.add_argument('--subdir', type=str, default='', help=f'a subdir where files from remote host will be placed')

    parser.add_argument('-e', '--extension', type=str, default='.out', help='File extension to filter by.')
    parser.add_argument('-f', '--file_name', type=str, default=None,
                        help='If this parameter is used with --get_files, the tool will search only for the specified file on the remote host')

    parser.add_argument('-o', '--output',
                        help="file name of the output CSV file  (default: output.csv). "
                             "It can includes a subdir. The csv file will be writen in the path",
                        type=str,
                        default="output.csv")
    parser.add_argument('-v', '--verbose',
                        help="Verbose - print the dictionary with all arguments.", action='store_true')

    args = parser.parse_args()

    hello_msg = f'''
       # {60 * '#'}
       # Processing IOR output Files
       # Date: {date.today()}
       # Used Parameters:
       #./{app_name}   {args.path}   {'--get_files' if args.get_files else ''} --e {args.extension} --o {args.output} --v {args.verbose}
       # {60 * '#'}\n\n\n'''

    print(hello_msg)

    # First, prepare the local and remote dir
    local_dir = os.environ.get('WORKDIR_LOCAL')
    remote_dir = os.environ.get('WORKDIR_REMOTE')
    host_name = os.environ.get('HOST_REMOTE')

    if local_dir is None or remote_dir is None or host_name is None:
        print("Error: set env vars WORKDIR_LOCAL WORKDIR_REMOTE and HOST_REMOTE")
        exit(1)

    local_dir = os.path.join(local_dir, args.path)

    if args.verbose:
        print(f"Local Dir: {local_dir}")

    if args.get_files:
        remote_dir = os.path.join(remote_dir, args.path)
        if args.verbose:
            print(f"Remote dir: {remote_dir}")

        # first, check if we need to get the files from the remote server
        # connect to the server and get the files
        getter = GetFiles(host_name=host_name,
                          remote_dir=remote_dir,
                          local_dir=os.path.join(local_dir, args.subdir),
                          verbose=args.verbose)
        if args.file_name is None:
            # get all files considering the extension given by the user
            # by default we look for bash.err, bash.out and csv files
            extensions = ['.err', '.out', '.csv', args.extension]
            getter.get_files_per_extension(exts=extensions)
        else:
            # if the parameter --f (file_name) is used we will get only one file of the server
            if args.verbose:
                print(f"Getting file {args.file_name} from the remote host")

            getter.get_a_file(args.file_name)

    # In the sequence build the CSV files

    search_by = args.extension
    if args.file_name:
        search_by = args.file_name

    files = set(glob.glob(os.path.join(local_dir, args.subdir) + '/*' + search_by))

    # Load the data
    ld = Loader(files=files, verbose=args.verbose)

    keys = [key for key in ld.data.keys()]
    keys.sort()

    output_file = os.path.join(local_dir, args.output)

    if args.verbose:
        print(f"Output: {output_file}...")

    ld.write_csv_all(keys=keys,
                     output_file=output_file,
                     write_mode='w')


if __name__ == "__main__":
    main()
