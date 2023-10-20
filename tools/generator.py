#!/usr/bin/env python3

import argparse
from argparse import RawTextHelpFormatter
from pathlib import Path
from datetime import date
import readline
import os

app_version = "1.0.0"
app_name = "Generator"
app_description = f"""
    {app_name} version {app_version}
        
    This tool generates all the files for an IOR test.

    for each set of parameters, the tool:

        1. Creates the folder where the test files will be placed
        2. Generated the files: nodes, the slurm_start.sh and the launcher.sh

    In the end, it generates the exec_all.sh file

    Note that a template for the slurm_start.sh need to be passed as input. 
    The template needs to have a set of tags. 
    
    Including, the tags related to the SBATCH:

    #{{[job_name]}} -> For the line #SBATCH --job-name=
    #{{[node_name]}} -> for the line #SBATCH --exclusive -C
    
    IOR:
    
    #{{[ior_path]}} 
    #{{[n_tasks_per_node]}} 
    #{{[ior_parameters]}}
    #{{[node_tag]}}
    
    Right now those tags are hard-coded in the Generator. The next updates will change it.
   
    Example of execution:
    

    Authors:     
    Luan Teylo (2021)

    """


def rlinput(prompt, prefill=''):
    readline.set_startup_hook(lambda: readline.insert_text(prefill))
    try:
        return input(prompt)  # or raw_input in Python 2
    finally:
        readline.set_startup_hook()


class Generator:
    # bash_first_line = "#!/usr/bin/env bash\n"

    def __init__(self, full_path: str, slurm_template, careful):
        self.full_path = full_path
        self.careful = careful
        self.slurm_template = slurm_template

        # used to replace info in the template
        self.dict_template = {
            'job_name': str(full_path).replace('/', '.'),
            'run_time': "0-5:00:00",
            'ior_path': "/beegfs/lgouveia/ior_8",
            'ior_parameters': "'-w -t 1m -b 512m -k'",
            'n_task_per_node': "8",
            'cmd_hourglass': "hourglass.py "
                             " --cmd_list 'sbatch -W slurm_start.sh' -r 10 -s 1 -e 10 -u min -o {folder}/launcher.sh --v"
        }

        self.output_msg = f"\n# This test was generated using {app_name} {app_version}\n" \
                          f"# Date: {date.today()}\n" \
                          f"# The following parameters were used:\n" \
                          f"#\t./test_manager.py \"{self.full_path}\"\n\n\n"

    # define launcher file
    def __define_launcher_file(self, folder):

        cmd = self.dict_template['cmd_hourglass'].replace("{folder}", str(folder))
        cmd = rlinput("\t#> Enter hourglass command: ", cmd)
        os.system(cmd)

    # define slurm file
    def __define_slurm_file(self, folder, node_dict):
        # Read template
        with open(self.slurm_template) as fp:
            template = fp.read()

        while True:
            job_name = rlinput(f"\t#> Enter job name: ", self.dict_template['job_name'])
            run_time = rlinput(f"\t#> Enter job runtime d-h:mm:ss: ", self.dict_template['run_time'])
            ior_path = rlinput(f"\t#> Enter IOR path: ", self.dict_template['ior_path'])
            ior_parameters = rlinput("\t#> Enter IOR parameters: ", self.dict_template['ior_parameters'])
            n_task_per_node = int(
                rlinput(f"\t#> Enter number of tasks per node: ", self.dict_template['n_task_per_node']))

            # check careful mode
            if self.__check_careful_mode(info={'job_name': job_name,
                                               'run_time': run_time,
                                               'ior_path': ior_path,
                                               'ior_parameters': ior_parameters,
                                               'n_task_per_node:': n_task_per_node}):
                break

        # update dict
        self.dict_template['job_name'] = job_name
        self.dict_template['ior_path'] = ior_path
        self.dict_template['ior_parameters'] = ior_parameters
        self.dict_template['n_task_per_node'] = str(n_task_per_node)

        n_nodes = len(node_dict['list_nodes'])
        n_tasks = n_nodes * n_task_per_node

        template = template.replace('#{[job_name]}', job_name)
        template = template.replace('#{[run_time]}', run_time)
        template = template.replace('#{[ior_path]}', ior_path)
        template = template.replace('#{[ior_parameters]}', ior_parameters)
        template = template.replace('#{[node_name]}', node_dict['node_name'])
        template = template.replace('#{[n_nodes]}', str(n_nodes))
        template = template.replace('#{[n_tasks]}', str(n_tasks))
        template = template.replace('#{[n_tasks_per_node]}', str(n_task_per_node))
        template = template.replace('#{[node_tag]}', f"'{node_dict['node_tag']}'")

        # Write slurm file
        with open(f"{folder}/slurm_start.sh", 'w+') as fp:
            fp.write(template)

    # Create the node file inside folder
    # Return a list with the name of the nodes (to be used on slurm file)
    def __define_node_file(self, folder, node_tag):

        while True:

            if node_tag is None:
                node_tag = rlinput("\t#> Enter with the node tag: ", "bora[001-010]")
            else:
                node_tag = rlinput(f"\t#> Enter with the node tag: ", f"{node_tag}")

            if self.__check_careful_mode(info=node_tag):
                break

        node_name = node_tag.split('[')[0]
        ids = node_tag.split('[')[1]

        # first, lets remove the '[]'
        ids = ids.replace('[', '')
        ids = ids.replace(']', '')

        list_nodes = []
        # Foreach node_id generate the list of nodes
        for node_id in ids.split(','):
            if node_id.find('-') > 0:
                id_start = int(node_id.split('-')[0])
                id_end = int(node_id.split('-')[-1])

                while id_start <= id_end:
                    list_nodes.append(f"{node_name}00{id_start}\n" if id_start < 10 else f"{node_name}0{id_start}\n")
                    id_start += 1
            else:
                node = int(node_id)
                list_nodes.append(f"{node_name}00{node}\n" if node < 10 else f"{node_name}0{node}\n")

        # Write the File
        with open(f"{folder}/nodes", 'w') as fp:
            for node in list_nodes:
                fp.write(node)

        return {"node_tag": node_tag,
                "node_name": node_name,
                "list_nodes": list_nodes}

    # Define the folder structure for the tests.
    # All folders will be created inside full_path
    # Return a list with all create folders
    def __create_structure(self):
        print(f"{5 * '#'} Defining Folder Structure for the Tests {5 * '#'}\n")

        full_path = Path(self.full_path)
        test_folders = []

        while True:
            op = rlinput('Enter with the operation: ', 'seq')
            # op = input("Enter with the operation (default 'seq'): ") or 'seq'
            start = int(rlinput("Enter with the start value: ", '1'))
            end = int(rlinput("Enter with the end value: ", '10'))
            base_value = int(rlinput("Enter with the step/factor value: ", '1'))

            print("\n")
            if self.__check_careful_mode(info=[op, start, end, base_value]):
                break

        parameters = self.__execute_operation(op=op, start=start, end=end, base_value=base_value)

        # Creating all folders
        for id in parameters:
            # Generate test folder
            test_folder = full_path.joinpath(Path(f"0{id}/" if id < 10 else f"{id}/"))
            # Create the folder
            print(f"Creating {test_folder}...")
            test_folder.mkdir(parents=True, exist_ok=True)

            # Put it a list to be used in the next round
            test_folders.append(test_folder)

        return test_folders

    # Create all test files and structure
    def create_test(self):
        # Firstly, create all folders
        test_folders = self.__create_structure()

        # Next, we create all test files
        print(f"\n{5 * '#'} Creating Files {5 * '#'}\n")

        node_tag = None
        for folder in test_folders:
            print(f"\nFolder: {folder}")
            # generating node file
            node_dict = self.__define_node_file(folder, node_tag)
            node_tag = node_dict['node_tag']
            # generating slurm file
            self.__define_slurm_file(folder, node_dict)
            # generating launcher file
            self.__define_launcher_file(folder)

        # Define/update exec_all.sh
        with open(f"{self.full_path}/exec_all.sh", "w+") as fp:
            for folder in test_folders:
                fp.write(f'(echo "running {folder.name}... "; cd {folder.name}/ || exit; sh launcher.sh)\n')

    # Check Careful execution mode
    def __check_careful_mode(self, info):
        if self.careful:
            print(f"Info: {info}")
            answer = rlinput(f"Confirm y/Any (Default: yes)?: ", 'y')

            print("\n")
            if answer.upper() == 'Y':
                print("Confirmed\n")
                return True
            else:
                print("Enter with the new information\n")
                return False

        return True

    # Generate a list of parameters according with the operations (op) parameters
    # Input:  operation(op:str), start, end and base_value (determines the range of the op
    # Output: a list with all values generated according with the operation.
    # Supported operations:
    # ['seq', start:int, end:int, step:int] -> generate parameters  [start ... end] by adding  start = start + step
    # ['mul', start:int, end:int, factor:int] -> generate parameters [start...end] by multiply start = start * factor
    def __execute_operation(self, op, start, end, base_value):
        parameters = []

        # sequence operation (seq)
        if op == 'seq':
            step = base_value

            if start > end or step <= 0:
                print("ERROR: seq operation. "
                      "Start value need to be greater then END and step need to be greater then zero")
                exit(1)
            while start <= end:
                parameters.append(start)
                start += step
        # multiplication operation (mul)
        elif op == 'mul':
            factor = base_value

            while start <= end:
                parameters.append(start)
                start *= factor

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

    def __str__(self):
        return self.output_msg


def main():
    parser = argparse.ArgumentParser(formatter_class=RawTextHelpFormatter, description=app_description)

    parser.add_argument('full_path', help="full path to the parent test folder [#required]", type=str)
    parser.add_argument('--slurm_template', help="full path to the slurm template used for the test",
                        type=str, default=None, required=False)
    parser.add_argument('--careful', help="careful mode. Ask confirmation to all operations", action='store_true')

    args = parser.parse_args()

    # Check if user pass a slurm_template in the command line
    if args.slurm_template is None:
        # get from ENV VAR GENERATOR_TEMPLATE
        args.slurm_template = os.getenv('GENERATOR_SLURM_TEMPLATE')

    if args.slurm_template is None:
        # Abort! There is no template to  the slurm file
        print("\n\t#~> Error: the full path for a slurm template need to be passed at the command line "
              "or in the ENV VAR GENERATOR_SLURM_TEMPLATE\n")
        exit(1)

    manager = Generator(full_path=args.full_path,
                        slurm_template=args.slurm_template,
                        careful=args.careful)

    manager.create_test()

    # print(manager)


if __name__ == "__main__":
    main()
