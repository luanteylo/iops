#!/bin/bash

# Function to check if a command exists
command_exists () {
    type "$1" &> /dev/null ;
}

# Check for MPI
if ! command_exists mpiexec; then
    echo -e "\e[31mError: MPI not found. Please install an MPI library like Open MPI or MPICH.\e[0m"
    exit 1
fi

# Check for Autoconf and Automake
if ! command_exists autoconf || ! command_exists automake; then
    echo -e "\e[31mError: Autoconf and/or Automake not found. Please install them to proceed.\e[0m"
    exit 1
fi

# Check for gcc
if ! command_exists gcc; then
    echo -e "\e[31mError: GCC not found. Please install it to proceed.\e[0m"
    exit 1
fi

# Default installation directory for IOR
DEFAULT_INSTALL_DIR="$HOME/ior"

# Ask the user for the installation directory
read -p "Enter the directory where you want to install IOR [Default: $DEFAULT_INSTALL_DIR]: " INSTALL_DIR

# If the user just pressed enter, use the default directory
if [ -z "$INSTALL_DIR" ]; then
    INSTALL_DIR=$DEFAULT_INSTALL_DIR
fi

# Step 1: Clone IOR repository
echo "Cloning IOR repository into $INSTALL_DIR..."
git clone https://github.com/hpc/ior.git $INSTALL_DIR

# Step 2: Build IOR
echo "Building IOR..."
cd $INSTALL_DIR

if [ ! -f "configure" ]; then
    echo "Running bootstrap..."
    ./bootstrap
fi

echo "Running configure..."
./configure --prefix=$INSTALL_DIR

echo "Running make..."
make

echo "Running make install..."
make install

# Check if in a conda environment
if [ ! -z "$CONDA_PREFIX" ]; then
    # Create the conda activate.d and deactivate.d directories if they don't exist
    mkdir -p $CONDA_PREFIX/etc/conda/activate.d

    # Add IOR to the PATH in the active conda environment
    echo "export PATH=\$PATH:$INSTALL_DIR/bin/" >> $CONDA_PREFIX/etc/conda/activate.d/env_vars.sh
    echo "echo Added IOR to PATH" >> $CONDA_PREFIX/etc/conda/activate.d/env_vars.sh    

    echo -e "\e[32mConda detected. Adding $INSTALL_DIR/bin/ to $CONDA_PREFIX/etc/conda/activate.d\n\e[0m"
    echo -e "\e[32mYou may need to restart your conda environment for the changes to take effect.\n\e[0m"
    
else
    echo "Not in a conda environment, skipping conda-specific steps."
    echo "Path to IOR: $INSTALL_DIR/bin/"
    echo -e "\e[31mALERT: It's mandatory to add IOR to your PATH manually.\e[0m"
fi

echo -e "\e[32mInstallation complete!\e[0m"
