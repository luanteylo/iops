#!/usr/bin/env python3

import argparse
from argparse import RawTextHelpFormatter
import random
from datetime import date

app_version = "1.0.0"
app_name = "hourglass"
app_description = f"""
    {app_name} version {app_version}
    
    
    This tool repeats the execution of the given command '--r' times with random time intervals between them. 
    
    
    The user needs to given the command, the number of time it will be repeated (--r), 
    the time interval and the time unit
    
    For example:
    
    {app_name} --cmd_list 'echo "hello world"' -r 10 -s 1 -e 10 -u hr

    The {app_name} will create a script were the command 'echo "hello world"' will be executed 10 times and, 
    between the command executions, it will select a wait time between 1 and 10 hours (h). 
    
    For reproducibility purposes, the sequence of commands added with sleep executions
    is written in an output script file.
    
    
    Authors: 
    Luan Teylo (2021)
    """


class Hourglass:
    bash_first_line = "#!/usr/bin/env bash\n"

    # Functions Calls
    function_call = 'run {} "{}" "{}" {}\n'

    # MailMe
    mailMe_call = "mailMe.py " \
                  "'finished' --s 'execution - plafrim'  -d luanteylo@gmail.com -u luanteylo@gmail.com -p \"$MAIL_PWD\""

    # Bash Function
    function = f''' 
    run () {{
        start_time="$(date -u +%s)"
        echo "Starting Execution ${{1}}...$(date)"
        eval ${{2}}
        end_time="$(date -u +%s)"
        elapsed="$(($end_time-$start_time))"
        echo "Execution ${{1}} finished at $(date). Elapsed time ${{elapsed}}"                
        echo "Sleep time for next execution:  ${{3}}"
        sleep "${{4}}"
        echo 
    }}\n\n\n'''

    def __init__(self, cmd_list, cmd_file, repeat, start, end, output, unit, mailme, verbose):

        self.cmd_list = cmd_list
        self.cmd_file = cmd_file
        self.repeat = repeat
        self.output = output
        self.unit = unit
        self.start = self.__to_seconds(start)
        self.end = self.__to_seconds(end)
        self.mailme = mailme
        self.verbose = verbose

        # the command list are created and shuffled
        self.commands = []
        for cmd in self.cmd_list:
            self.commands.extend(self.repeat * [cmd])

        random.shuffle(self.commands)

    def __str__(self):
        return f'''
        # {60 * '#'}
        # This script was generated using {app_name} {app_version}
        # Date: {date.today()}
        # Used Parameters:
        #./{app_name}  {'--cmd_file' if self.cmd_file is not None else '--cmd_list'} \'{self.cmd_file if self.cmd_file is not None else self.cmd_list}\' 
        #\t--r {str(self.repeat)} --s {self.__seconds_to_unit(self.start)} --e {self.__seconds_to_unit(self.end)} 
        #\t--o {self.output} --u {self.unit}
        #\t--m {self.mailme} --v {self.verbose}
        # {60 * '#'}\n\n'''

    # Convert the time according with the unit to seconds
    # Input:  the time to be converted
    # Output: the time in seconds
    def __to_seconds(self, time):
        if self.unit == 'sec':
            return time
        elif self.unit == 'hr':
            return time * 60 * 60
        elif self.unit == 'min':
            return time * 60
        else:
            raise Exception(f"Error: Unit {self.unit} is not valid")

    # Convert the time according with the self.unit
    # Input:  the time to be converted in seconds
    # Output: the time converted according with the unit
    def __seconds_to_unit(self, time):
        if self.unit == 'sec':
            return time
        elif self.unit == 'hr':
            return time / 3600
        elif self.unit == 'min':
            return time / 60
        else:
            raise Exception(f"Error: Unit {self.unit} is not valid")

    # Turn IT!
    # Start the execution by randomly turning the hourglass (injection of waiting times)
    def turn_it(self):
        # Open the script that will contain the commands
        total_wait = 0.0  # used on verbose mode

        if self.verbose:
            print(self)

        with open(self.output, 'w') as f:

            # First we write the fixed file information:
            # 1. bash head line;
            # 2. Hourglass output info; and
            # 3. The Execution function
            # 4. The mailMe Function
            f.write(self.bash_first_line)
            f.write(self.__str__())
            f.write(self.function)

            i = 0
            for cmd in self.commands:
                # Generate the wait time between repetitions
                wait_time_seconds = random.randint(self.start, self.end)

                # remove wait time from the last repetition
                if i + 1 == self.repeat:
                    wait_time_seconds = 0.0

                wait_time_msg = f"{self.__seconds_to_unit(wait_time_seconds):.1f} {self.unit}"

                # Write the Function
                f.write(self.function_call.format(i, cmd, wait_time_msg, wait_time_seconds))
                i += 1

                if self.verbose:
                    print(f"\tExecution {i}: command: {cmd} Sleep time - {wait_time_msg}")
                    total_wait += wait_time_seconds
            # if mailMe, write mailMe call
            if self.mailme:
                f.write("\n\n")
                f.write(self.mailMe_call)

        if self.verbose:
            print(f"\t{10 * '----'}")
            print(f"\tUpper-bound time: {self.__seconds_to_unit(total_wait):.1f} {self.unit}\n\n")


def main():
    parser = argparse.ArgumentParser(formatter_class=RawTextHelpFormatter, description=app_description)

    parser.add_argument('--cmd_list', nargs='+', help="A list of commands", default=None)
    parser.add_argument('--cmd_file', type=str, help="A file with the commands separated by new line", default=None)

    parser.add_argument('-r', '--repeat',
                        help="number of times the command will be executed",
                        type=int,
                        required=True)

    parser.add_argument('-s', '--start',
                        help="Start of the range of time",
                        type=int,
                        required=True)

    parser.add_argument('-e', '--end',
                        help="End of the range of time",
                        type=int,
                        required=True)

    parser.add_argument('-o', '--output',
                        help="full name for the output script  (default: ./launcher.sh)",
                        type=str,
                        default="launcher.sh")

    parser.add_argument('-u', '--unit', help="unit of time used to generate the wait time",
                        choices=('hr', 'min', 'sec'), default='hr')

    parser.add_argument('-m', '--mailMe', help="Send an email to the end of the test. "
                                               "Note: You have to setup the email line on hourglass.py",
                        action='store_true')

    parser.add_argument('-v', '--verbose', help="Verbose - print the waiting times.", action='store_true')

    args = parser.parse_args()

    # check what was the input method selected

    #  if both methods are none, error
    if args.cmd_list is None and args.cmd_file is None:
        parser.error('Error: both cmd_list and cmd_file are empty. An input method need to be defined.')

    cmd_list = []
    # read the file and build the list of commands
    if args.cmd_file is not None:
        with open(args.cmd_file) as f:
            for line in f.readlines():
                cmd_list.append(line.rstrip())

    else:
        cmd_list = args.cmd_list

    launcher = Hourglass(cmd_list=cmd_list,
                         cmd_file=args.cmd_file,
                         repeat=args.repeat,
                         output=args.output,
                         start=args.start,
                         end=args.end,
                         unit=args.unit,
                         mailme=args.mailMe,
                         verbose=args.verbose)

    launcher.turn_it()


if __name__ == "__main__":
    main()
