## Write everithing that help:
- to understand what you are doing 
- to progress and see your progression. So you can be back easily to your code
- to write the final report

### Team and iniria presentation

### First exchange on the subject

Yesterday, 03/04. Luan presente me the theory and concept of the internship.

## Theory

On clusters like Platfim clusters, there are nodes for computing, such as Bora, and there are also nodes for IO. Computing nodes run applications to compute and perform IO. On the other hand, IO nodes have applications like PFS (Parallel File System), specifically ss1 and ss2. There are also applications like the BeeGFS file system distribution, which distributes slices of files. Distributed files are stored on OSTs (Object Storage Targets), which are HDD disks on Platfim.

Files are striped into slices. The size of a slice is called the _stripe size_, and the _stripe count_ refers to the number of OSTs because each stripe is stored on a _single OST_ (refer to the figure).

The BeeGFS strategy does not directly allow the setting of the number of OSTs, so we provide a list of folders (see below).

There are 4 OSTs per PFS, totaling 8 OSTs: ost_1.1 through ost_2.4.
It's important to note that the number of OSTs does not linearly correspond to the bandwidth for accessing the PFS.

Some parameters are required at the beginning:

- Number of OSTs: List of folders ost_1, ost_2, ost_4, ost_8
- Volume of the file
- Number of computing nodes


## About ior

**IOR** is a benchmark tool. It conducts **performance analysis** in a way a file can be **distributed** for **PFS** using **MPI processes**. 
**IOR** can be used to test the **performance** of parallel storage systems using various interfaces and access patterns. When different processes write to different files, it's called **N-N**. When writing to the same file, it is called **N-1 "strategy"**, and so it can be in order, a **sequential** order could be like process 1 write to the first part of the file and process 2 write to the second, and so on. On the other hand a **random** order is random writing. So those **IO patterns** also affect the **performance** of **PFS**. 


## Concept
# IOPS

* **Round**:
Full set of tests used to identify the parameters that give us the peak bandwidth. 

* **Round output**:
the set of static parameters that will be used in the next rounds.


We fixe two parameters **volume** and **strip folders** and we variate the **numbers of nodes** 1 ... 8. 
We test and analyze the peak bandwith obtained with this configuration.

Round 1:
static params
- \#nodes 4
- volume 4 GB
- stripe folders ior_2

For example, Round 1 uses 4 nodes, but we saw a peak with 8 nodes. So in Round 2, we will use 8 nodes instead of 4.

Round 2:
static params
- \#nodes 8
- volume 8 GB
- stripe folders ior_4


 
## Questions      
```What are the params that affects the PFS performance ?
```

```How can we compare bandwidth ?
```

```What should be the stop condition ?
```
for now, we define the number of rounds. How many ?




### Architecture

--> DATE: jeu. 04 avril 2024 12:41:29 <--

Starting with two classes. One class call Runner which run test. Another class "generator" generate tests and change rounds (round 1 to round 2). 

update

Start with a same architecture and make it work and run some basics:
- One benchamrk ior
- job manager slurm
- No heuristic way to comparing bandwidth in a test (may be in a set of tests: round)

## Main codes

--> DATE: ven. 05 avril 2024 11:06:54 <--

## Reading paper

**Goal**:
* Characterise the writing performance of BeeGFS, especially the impact of the stripe count.
* How networks can change the observations when evaluating I/O performance.
* A method that can be extended to use other PFS systems instead of BeeGFS only.
* And study the impact of stripe count when multiple applications share the I/O infrastructure. It is showing that sharing storage target does not always negatively impact performance. And seeking to adapt applications' stripe count would not improve write performance.


## Experimental env

Experiments on Plafrim (192 node) within Bora cluster. 
192 GiB RAM. Running OS: CentOS with Linux kernel.

Parallel file system storage BeeGFS deployed over two hosts (using 12 HDD hard disk drives). Each host executes one OSS with 4 OSTs and one MDS. Each HDD has a capacity of 1.8 TB. 

Total storage available for clients: 131 TB.

In Plafrim setup, files are written with a stripe count of 4 and stripe size of 512 KiB. Each slide of files is distributed (stored) on one OST in a round-robin fashion.

Connection between nodes and storage servers is a 10 GBit/s Ethernet network. Bora nodes share a 100 GBit/s Omnipath network that includes the PFS. 

PFS performance is limited by the slowest component in the I/O path (say, for now: network speed component and storage component).
 Two scenarios of execution:
- In **Scenario 1**, using Ethernet, the network speed is slower than the storage components, limiting I/O performance.

- In **Scenario 2**, the speed of the Omnipath is greater than that of the storage components, so the latter are the most important factor for performance.


**Questions**:
- [ ] What is Omnipath here, is it related to a real path or an abstract path?


## Benchmarking tool

IOR is used to conduct all tests. It is a benchmark tool that measures the performance of I/O operations considering different parameters such as the file size, the transfer size, and the number of segments.

Multiple IOR executions are performed to avoid warm-up effects. Using the POSIX interface and a 1 MiB transfer size has two advantages. The stripe size is 512 and stripe count is 4. So, 1024/4 = 256 is less than the 512 KiB stripe size, meaning it is aligned and large enough compared to the default stripe size to require more than one OST.

 

## Execution protocol
--> DATE: lun. 08 avril 2024 09:29:51 <--

## Results

It is important first to evaluate the number of computing nodes because not using enough nodes limits **network performance** (assuming all links have the same capacity). There are two scenarios: 1) the number of computing nodes is greater than or equal to the number of OSSs (PFS servers), where the network is slower than storage, and 2) the number of computing nodes is less than the number of OSSs, where storage is slower than the network.

The number of nodes can limit the IO performance regardless of the network speed.

Processes per node have an impact on the performance. We reach high performance with 4 nodes in scenario 1 and with 16 nodes in scenario 2. The only difference between the two scenarios is the concurrent requests, meaning the number of processes per node used. More parallelism is available at the storage system.

One hypothesis: we can increase the number of processes per node to decrease the number of nodes.

A test shows not much changing behavior between 8 and 16 processes per node. This can be explained by the competition for access to the network interface, memory, and BeeGFS. So, the number of processes per node should be considered in the evaluation, as it impacts the IO performance.


**Scenario 1:**
When evaluating the number of OSTs, high performance is reached when using (allocating) the same number of OSTs on both servers. The worst performance is observed when using only one server, like (0,1), (0,3).

**Scenario 2:**
Bandwidth increases linearly with the number of OSTs. We see confirmation of the most important parameter, which is the number of OSTs.


Impact of concurrent application sharing the OSTs
One limitation obseved in PFS software like BeeGFS is that when multiple processes write to the same files (it's called the shared-file strategy N-1) it could result to a contention between node. 

## Related work


## Issues

Remote SSH connection problem on Plafrim due to quota issues has been resolved by removing unnecessary folders consuming memory (because it allow to copy a ssh key on plafrim for first connexion)

**DATE:** Mar. 09 April 2024 09:29:33

I figured out how to switch tabs in Gedit. The shortcut is Ctrl + Alt + Page Up/Down.

I am working on the first task that I have to complete. I started yesterday and made progress. It's a simple task, just moving a piece of code to another class and considering this operation, as well as changing whatever calls this method.

 
**DATE**: mer. 10 avril 2024 11:15:47 <--
## task 1

Refactoring the code. Moving the print_config method from main to config file. Adapted changes to support this. 

## task 2

**Round Next Method:**
Implement a simple idea to run the next round. The parameters in the next round will be updated. The number of computing nodes will increase by 1, the next stripe folder will be selected, and the volume of the file will increase by 1024.

The question arises: should the idea for the next round come from the updated static parameters, or should the next round be based on the current static parameters?

For now, we are just updating the parameters from the starting values. For example, if the starting volume is 1, in the next round the volume will be increased by 1024. Similarly, the number of computing nodes will increase from 1 to 2. The round will test the number of computing nodes = 2, 3, ..., up to max_nodes (which is currently set to 32).


## Heuristic
An idea of heuristic is one call hill climbing algorithm. 
```The hill climbing algorithm is a basic optimization technique that starts with an initial solution and iteratively makes small improvements to it.
```
**DATE**: jeu. 11 avril 2024 09:28:49

Today, I will discuss with Luan to the task 2 that I pushed yesterday. For now, I corrected the spelling in this file and pushed it on the development branch **dev-1.0** because I don't want to lose it.





