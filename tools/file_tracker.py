#!/usr/bin/env python3

import argparse
from argparse import RawTextHelpFormatter
from pathlib import Path
import csv
import uuid
import os
import glob

from datetime import datetime, timezone

app_version = "1.0.0"
app_name = "FileTracker"
app_description = f"""
    {app_name} version {app_version}

    The {app_name} looks at all files in the --path and gets information about them.  That information is 
    appended to a given file in CSV format.

    Currently information are:
    tracker_id, file, size, ctime, mtime, targets 

    tracker_id, timestamp, file_name, file_size, data, targets

    Note the same tracker_id is given for all files tracked in a current call of the app.


    Example of execution:

    python file_tracker /beegfs/lgouveia/ior_2 --append_to ./tracker_file.csv --v


    Authors: 

    Luan Teylo (2021)

    """


class FileTracker:

    def __init__(self, path, append_to, delete, verbose):
        self.path = Path(path)
        self.append_to = append_to

        self.tracker_id = str(uuid.uuid4())[:8]
        self.tracker_timestamp = datetime.now().timestamp()

        self.delete = delete
        self.verbose = verbose

    def __get_targets(self, file):
        # BeeGFS Targets Info
        cmd = f"beegfs-ctl --getentryinfo {file}"
        stream = os.popen(cmd)
        output = stream.readlines()

        targets = []

        pos = None
        for i in range(len(output)):
            if output[i].find('+ Storage') == 0:
                pos = i
        if pos is None:
            raise Exception("ERROR: + Storage not Found")

        for target in output[pos + 1:]:
            targets.append(str(int(target.split("@")[0].replace('+', ''))))

        return " ".join(targets)

    def track_it(self):
        # Sort files per creation date
        f = sorted([it for it in self.path.glob('*')], key=os.path.getctime, reverse=True)

        first_line = ["tracker_id", "tracker_timestamp", "file", "size", "ctime", "mtime", "storage_targets"]

        full_rows = []

        # For each file, get size, creation_date and last_modified
        for file in f:

            if self.verbose:
                print(f"Tracking {file}...")

            if file.is_file():
                stats = file.stat()

                # size = stats.st_size
                # ctime = datetime.fromtimestamp(stats.st_ctime).strftime('%Y-%m-%d %H:%M:%S')
                # mtime = datetime.fromtimestamp(stats.st_mtime).strftime('%Y-%m-%d %H:%M:%S')

                try:
                    targets = self.__get_targets(file)
                except Exception as e:
                    print(f"Error when getting targets information.")
                    targets = []

                full_rows.append([self.tracker_id,
                                  self.tracker_timestamp,
                                  file, stats.st_size, stats.st_ctime, stats.st_mtime, targets])

                if self.delete:
                    os.remove(file)

        # Check if csv already exist
        file_exist = os.path.exists(self.append_to)

        if self.verbose:
            print(f"\n\n\nWriting tracked information to {self.append_to}...")

        with open(self.append_to, 'a') as csv_file:
            writer = csv.writer(csv_file)

            if not file_exist:
                writer.writerow(first_line)

            for row in full_rows:
                # Add key to the csv Row
                writer.writerow(row)






def main():
    parser = argparse.ArgumentParser(formatter_class=RawTextHelpFormatter, description=app_description)

    parser.add_argument('path', help="Path where files are", type=str)
    parser.add_argument('-v', '--verbose', help="Verbose. Print the tracker operations", action='store_true')
    parser.add_argument('-a', '--append_to',
                        help="Full name for the file where tracker information will be appended.\n"
                             "Default: tracker.csv",
                        type=str,
                        default='tracker.csv')
    parser.add_argument('-d', '--delete', help="Delete the tracked file", action='store_true')

    args = parser.parse_args()

    tracker = FileTracker(path=args.path,
                          append_to=args.append_to,
                          delete=args.delete,
                          verbose=args.verbose)

    tracker.track_it()


if __name__ == "__main__":
    main()



