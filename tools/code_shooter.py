#!/usr/bin/env python3

import argparse
from argparse import RawTextHelpFormatter
import random
import json
from datetime import date

app_version = "1.0.1"
app_name = "CodeShooter"
app_description = f"""
    {app_name} version {app_version}  

    
    This tool generates and writes a randomized sequence of commands in bash files. 
    Those commands are written according to the baseline command (base_cmd) passed by the user. 
    The baseline command should have a markdown (mkd), for example, #[<name>], to indicate where the code 
    should insert the parameters' values.
    
    Users also need to pass a dictionary of operations (dict_op):
    
    The dictionary of operations has the following structure: {{mkd: [[op1,...],..,[opn,...]]}},
    where mkd is the markdown which parameters will be include and op1 is the first operation name
    and opn is the nth operation. Each operation is sent in a list with the operation values.
    
    Currently, supported operations are:
    
    ['seq', start:int, end:int, step:int] -> generate parameters  [start ... end] by adding  start = start + step   
    ['mul', start:int, end:int, factor:int] -> generate parameters [start...end] by multiply start = start * factor
    ['cp', value:any, N:int] -> copy the 'value' N times. 
    ['div', start:int, end:int, div:float] -> generate parameters [start ... end] by dividing start = start/div 

    Warning: The dict_op is a json string, and the operations are sent as a list of lists!
    
    
    Example of execution:

    code_shooter.py \"mpirun --mca mtl psm2 ior -w  -b #[0]m -o  /beegfs/testFile\" --d '{{\"#[0]\":[[\"seq\", 1, 10, 1]]}}' --verbose
    
    The above command will generate a file with the following content:

        mpirun --mca mtl psm2 ior -w  -b 10m -o  /beegfs/testFile
        mpirun --mca mtl psm2 ior -w  -b 9m -o  /beegfs/testFile
        mpirun --mca mtl psm2 ior -w  -b 8m -o  /beegfs/testFile
        mpirun --mca mtl psm2 ior -w  -b 7m -o  /beegfs/testFile
        mpirun --mca mtl psm2 ior -w  -b 6m -o  /beegfs/testFile
        mpirun --mca mtl psm2 ior -w  -b 5m -o  /beegfs/testFile
        mpirun --mca mtl psm2 ior -w  -b 4m -o  /beegfs/testFile
        mpirun --mca mtl psm2 ior -w  -b 3m -o  /beegfs/testFile
        mpirun --mca mtl psm2 ior -w  -b 2m -o  /beegfs/testFile
        mpirun --mca mtl psm2 ior -w  -b 1m -o  /beegfs/testFile
     
    Authors:     
    Luan Teylo (2021)
    
    """





class CodeShooter:
    bash_first_line = "#!/usr/bin/env bash\n"

    def __init__(self, base_cmd: str, output, dict_op, block_size, mkd_format, verbose):
        self.base_cmd = base_cmd
        self.output = output
        self.dict_op = dict_op
        self.mkd_format = mkd_format
        self.block_size = block_size
        self.verbose = verbose

        self.output_msg = f"\n# This script was generated using {app_name} {app_version}\n" \
                          f"# Date: {date.today()}\n" \
                          f"# The following parameters were used:\n" \
                          f"#\t./code_shooter.py \"{self.base_cmd}\"\n" \
                          f"#\t--d \'{str(self.dict_op)}\'\n" \
                          f"#\t--output {self.output}\n" \
                          f"#\t--block {self.block_size} --mkd_format \"{self.mkd_format}\"\n\n\n"

    # Validate markdowns. Check if the markdown is on the text
    # Output: If not, return False
    #         Otherwise return True
    def __validate_mkd(self, markdown):
        if self.base_cmd.find(markdown) == -1:
            return False
        return True

    # Generate a list of valid Markdowns
    # Output: a List with all markdowns
    def __generate_markdowns(self):
        n_mkd = self.base_cmd.count("#[")  # count the number of markdown on the baseline command
        list_mkd = []
        # generate the markdowns
        for mkd_i in range(n_mkd):
            markdown = self.mkd_format.format(mkd_i)
            if not self.__validate_mkd(markdown):
                error_msg = "\nError: Markdown {} was not found in the text.\n\n" \
                            "\tAttention: all markdowns need to be sequential and repetitions is not allowed \n\n" \
                            "\tExample: mpirun --mca mtl psm2 /home/lgouveia/ior/bin/ior" \
                            " -w  -b #[0]m -o  #[1]".format(markdown)
                print(error_msg)
                exit(1)
            list_mkd.append(markdown)

        return list_mkd

    # Generate a list of parameters according with the operations (op) parameters
    # Input:  operation(op:str) and the dict_op input list (input_op: list)
    # Output: a list with all values generated according with the operation.
    def __execute_operation(self, op, input_op):
        parameters = []

        # sequence operation (seq)
        if op == 'seq':
            start = input_op[1]
            end = input_op[2]
            step = input_op[3]

            if start > end or step <= 0:
                print("ERROR: seq operation. "
                      "Start value need to be greater then END and step need to be greater then zero")
                exit(1)
            while start <= end:
                parameters.append(start)
                start += step
        # multiplication operation (mul)
        elif op == 'mul':
            start = input_op[1]
            end = input_op[2]
            factor = input_op[3]

            while start <= end:
                parameters.append(start)
                start *= factor
        # copy operation (cp)
        elif op == 'cp':
            value = input_op[1]
            n = input_op[2]

            for i in range(n):
                parameters.append(value)
        elif op == 'div':
            start = input_op[1]
            end = input_op[2]
            div = input_op[3]

            while start >= end:
                parameters.append(int(start))
                start = start / div

        else:
            error_msg = "\nError: It was not possible to execute the operation " + op + "\n\n"
            error_msg += "\tAttention: Check the operation format and if it is supported\n\n" \
                         "\tExample: " \
                         "code_shooter.py" \
                         " \"mpirun --mca mtl psm2 /home/lgouveia/ior/bin/ior -w  -b #[0]m " \
                         "-o  /beegfs/lgouveia/testFile\" --d '{\"#[0]\":[\"seq\", 1, 10, 1]}'"

            print(error_msg)
            raise

        return parameters

    # For each markdown we generate the list of parameters
    # Input: list_mkd -> the markdown list
    # Output: A dictionary composed by the List of parameters
    def __generate_list_of_parameters(self, list_mkd):
        dict_parameters = {}
        try:
            for markdown in list_mkd:
                dict_parameters[markdown] = []

                # get list of operation
                for operation_list in self.dict_op[markdown]:
                    op = operation_list[0]
                    dict_parameters[markdown].extend(self.__execute_operation(op, operation_list))

        except Exception as e:
            error_msg = f"Error: It was not possible to generate the list of parameters. Please check the dict_op.\n" \
                        f"For a execution example use --help option."
            print(error_msg)
            raise e

        return dict_parameters

    # Shoot the CODE!
    # Generate a random sequence of commands line according with the input parameters
    def shoot(self):
        list_mkd = self.__generate_markdowns()
        dict_parameters = self.__generate_list_of_parameters(list_mkd)

        loop_flag = True

        code_shoots = []
        while loop_flag:

            command = self.base_cmd

            for mkd in list_mkd:
                if len(dict_parameters[mkd]) > 0:
                    parameter = dict_parameters[mkd].pop()
                    command = command.replace(mkd, str(parameter))
                else:
                    # if there is at least one empty list of parameters we should stop to generate commands
                    loop_flag = False
            if loop_flag:
                code_shoots.append(command)

        if self.verbose:
            for cmd in code_shoots:
                print(cmd)

        for i in range(self.block_size):
            output_file = self.output + "_" + str(i)

            # randomizing the shoots inside a block
            random.shuffle(code_shoots)

            with open(output_file, 'w') as f:
                f.write(self.bash_first_line)
                # write the command line parameters used to generate the file

                f.write(self.output_msg)

                for cmd in code_shoots:
                    f.write(cmd + "\n")


def main():
    parser = argparse.ArgumentParser(formatter_class=RawTextHelpFormatter, description=app_description)

    parser.add_argument('base_cmd', help="baseline command [#required]", type=str)
    parser.add_argument('-b', '--block', help="number of blocks of commands - sequence of files (default: 1). "
                                              "Note: Commands in a block are also randomized. "
                                              "So, two blocks have different command sequences",
                        type=int,
                        default=1)
    parser.add_argument('-o', '--output', help="full name for the output script  (default: ./run.sh)", type=str,
                        default="run.sh")
    parser.add_argument('-m', '--mkd_format',
                        help="markdown format. Note: the markdown should include {} (default: '#[{}]')",
                        default='#[{}]')
    parser.add_argument('-d', '--dict_op', help="dictionary of operations", type=json.loads, required=True)
    parser.add_argument('-v', '--verbose', help="Verbose - print the generated code shoots.\n"
                                                "Note: the verbose mode does not print the shoots (commands) "
                                                "randomized since it is used to debug purposes.", action='store_true')

    args = parser.parse_args()

    shooter = CodeShooter(base_cmd=args.base_cmd,
                          output=args.output,
                          dict_op=args.dict_op,
                          block_size=args.block,
                          mkd_format=args.mkd_format,
                          verbose=args.verbose)

    shooter.shoot()


if __name__ == "__main__":
    main()
