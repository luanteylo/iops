#!/bin/bash

# Determine the installation directory to IOR
INSTALL_DIR="$HOME/Devel/ior"

# Step 1: Clone IOR repository
echo "Cloning IOR repository..."
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
    mkdir -p $CONDA_PREFIX/etc/conda/deactivate.d

    # Add IOR to the PATH in the active conda environment
    echo "export PATH=\$PATH:$INSTALL_DIR/bin/" >> $CONDA_PREFIX/etc/conda/activate.d/env_vars.sh
    echo "echo Added IOR to PATH" >> $CONDA_PREFIX/etc/conda/activate.d/env_vars.sh    
    
else
    echo "Not in a conda environment, skipping conda-specific steps."
    echo "Path to IOR: $INSTALL_DIR/bin/"
    echo -e "\e[31mALERT: It's mandatory to add IOR to your PATH manually.\e[0m"

fi

echo -e "\e[32mInstallation complete!\e[0m"

