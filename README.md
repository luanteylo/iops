# I/O Performance Evaluation benchmark Suite (IOPS)

The I/O Performance Evaluation Suite, or IOPS, is a tool that aims to answer one and only one question: **What parameters do you need to reach the peak I/O performance of your Parallel File System (PFS)?**

The true is, IOPS is not a benchmark tool (or a suite, whatever that means we only need a word starting in S to have a nice name). IOPS utilizes open-source benchmarks, like IOR, and performs a parameter search considering the following factors:

- Number of compute nodes and processes performing I/O
- Data volume
- Access pattern
- Striping parameters

And the most important part is that it conducts this search, processes the results, generates nice graphs, and does it all automatically! No more bash scripts to perform multiple IOR experiments. No sir! Not on my watch!


## Where Do We Stand in the Sum?

You may be asking, why would I need to know this? Who cares about the parameters required to achieve maximum bandwidth for my PFS? Well, my friend, you need to know for at least three reasons:

1. To fine-tune your application and extract the maximum performance from your parallel file system.
2. To ensure that your system is delivering the expected I/O performance.
3. To identify possible bottlenecks.


The inspiration for IOPS came from this paper: [Attention, PDF!](https://inria.hal.science/hal-03753813/)

In this paper, we conducted numerous IOR executions and discovered many interesting things about our system, including incorrect configurations that were limiting the performance of our cluster (read the paper, you'll enjoy it).

But back then, we spent a lot of time writing scripts, and the automation of this process was almost non-existent. It was very error-prone, and the scripts were not portable to other machines: it was a nightmare when we tried to perform the same tests on another machine.

Moreover, it was extremely time-consuming to start the tests, wait for completion, process the data, generate the graphs, and so on. Honestly, we had a postdoc who was doing all that for us, so it wasn't really a big problem because we didn't care much about him, but now he has a permanent position, so we are forced to improve his working conditions (Damn left-wing!).

## Ok! I'm Convinced. How Does It Work?

Well, we can't show you due to a minor detail that we forgot to tell you: it doesn't exist yet.

Of course, we have the scripts from the paper, and some steps like data parsing and graph generation are already in place, but it lacks the glue that IOPS aims to be. Anyway, let me explain how it will work and the architecture behind it.

In practice, to reach the maximum I/O bandwidth of an HPC platform, you need a recipe with four main elements:

1. Sufficient volume in the I/O operation
2. Enough compute nodes (and processes per node) participating in the operation
3. A network fast enough
4. A file system that uses enough Object Storage Targets and Object Storage Servers

The equation is simple: if any of these parameters are set up in the wrong way, it will become the I/O bottleneck. Slow network? The network is the bottleneck. Too few compute nodes? The compute nodes will be the bottleneck. So, the idea is that we adjust these parameters in a way that we find the bottlenecks of the bottlenecks. 

The catch is that to evaluate each of these parameters, we first need to find the right balance. For example, to determine the right number of compute nodes, we must first establish the appropriate file size, and so on.

For instance, let's say we need to find the right number of compute nodes. Initially, we use a fixed number of nodes (say, 4) and plot the curve of file sizes to find the right data volume:

![Find the Right Data Volume](.images/findthevolume.png)

Then, after we've found the plateau, we begin running tests with a fixed file size—let's say 32GB—while varying the number of computing nodes:

![Find the Number of Compute Nodes](.images/findthecnode.png)

At this point, we observe that the maximum bandwidth in the file size test was actually limited by the number of nodes, as we achieve significantly more bandwidth with 16 nodes. This raises the question: is 32GB the right file size when using 16 nodes? The answer is: we don't know.

Therefore, once we've determined the optimal number of nodes, we revisit the file size to see if the graph changes with the newly discovered optimal node count. This process repeats until we identify the ideal parameters.

And that's just for two parameters! We have other variables to consider, such as the number of processes, distinct striping configurations, and file patterns. So, this search for the right parameters can be very time-consuming for you—especially if you don't have a postdoc to exploit. Furthermore, we're expending energy and using resource hours that you'd generally want to conserve for others to use as well.

Consequently, IOPS can't merely be a dispatch tool. It needs to be smart, like you and me. Instead of testing all possible parameter combinations as shown in the previous graphs, IOPS will test only the strictly necessary cases. **We aim to plot a complete characterization of the file systems, showing how these parameters affect performance, while doing so both efficiently and quickly.**


## Brainstorm

This section will list a series of features, ideas, and things that we want in IOPS, so we can start thinking about its development.

### It Needs to Be Modular from Day One

Whether I want to add a new set of tests for another parameter or implement tests using another I/O benchmark, it should be easy to do.

### It Needs to Be AC-DC

- Amazingly Easy to Configure
- Definitely Easy to Commence

We should be able to go to any machine, change a couple of lines in a setup file, and deploy it immediately using the machine's job manager.

### It Will Follow Good Practices of the I/O Community

Tests need to be repeated temporally and spatially to minimize the effects of concurrent applications. In other words, we won't stop a cluster to run an IOPS analysis, so we'll need sufficient repetitions to ensure unbiased results.


### It will work in Steps: Run, then process, then decide the next Test

After running everything, IOPS will perform **Data Aggregation and Analysis**: It will generate graphs and evaluate the results, producing a report on the impact of each parameter on the system under evaluation.





---

## Dependencies

The following packages are required to run the code:

### Core Dependencies

1. **IOR**: The I/O performance benchmark suite.
    - Source code can be found [here](https://github.com/hpc/ior)
    - Follow the installation instructions in their README or build from source.
    - Optionally, IOPS offers an `install_ior.sh` script to simplify the installation process.

2. **libopenmpi-dev**: Open MPI development libraries.
    - **Ubuntu**: 
        ```
        sudo apt-get install libopenmpi-dev
        ```
    - **CentOS/RHEL**: 
        ```
        sudo yum install openmpi-devel
        ```

### Optional Dependencies

1. **Conda**: For environment isolation, though not strictly necessary.
    - Download and install from [here](https://docs.conda.io/en/latest/miniconda.html)


## Installation

This section provides a step-by-step guide for installing and setting up the project. We recommend using Conda for environment isolation. If you don't have Conda installed, you can download it from [here](https://docs.conda.io/en/latest/miniconda.html).

### Steps

#### 1. Clone the Repository

First, clone the project repository to your local machine.

```bash
git clone https://gitlab.inria.fr/lgouveia/iops
```

#### 2. Create Conda Environment

To create a new Conda environment, run the following command:

```bash
conda env create -f environment.yml
```

This will create a new Conda environment and install all the dependencies listed in the `environment.yml` file.

#### 3. Activate the Environment

Activate your new Conda environment with:

```bash
conda activate your_environment_name
```

Replace `your_environment_name` with the name you've given to your Conda environment in the `environment.yml` file.

#### 3. Install IOR 

If you haven't installed IOR yet, you can use the provided `install_ior.sh` script to do so. Before running the script, make sure to give it the necessary permissions:

```bash
chmod +x install_ior.sh
```

Note: Run it in the Conda environment so it will automatically update the $PATH variable.

Then, run the script:

```bash
./install_ior.sh
```

### Verifying the Installation

To verify that everything is set up correctly, you can run the following command:

```bash
iops --check_setup
```

If everything is installed correctly, you should see the expected output:

```bash
Ready to Go!
```

