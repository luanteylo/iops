"""Interactive wizard for creating IOPS benchmark configurations."""

import sys
from pathlib import Path
from typing import Optional
import shutil


class BenchmarkWizard:
    """Wizard for creating benchmark configurations from template."""

    def __init__(self):
        self.template_path = Path(__file__).parent / "template_full.yaml"
        # Path to examples directory in the package
        package_root = Path(__file__).parent.parent.parent
        self.examples_source = package_root / "docs" / "examples"

    def run(self, output_path: Optional[str] = None) -> Optional[str]:
        """
        Generate a comprehensive configuration template.

        Args:
            output_path: Optional path for the output file. If None, prompts user.

        Returns:
            Path to the generated file, or None if cancelled.
        """
        self._print_header()

        # Determine output filename
        if output_path:
            filename = output_path
        else:
            filename = self._ask_filename()
            if not filename:
                return None

        # Ensure .yaml extension
        if not filename.endswith('.yaml') and not filename.endswith('.yml'):
            filename += '.yaml'

        # Check if file exists
        output_file = Path(filename)
        if output_file.exists():
            if not self._confirm_overwrite(output_file):
                print("\n✗ Configuration not saved")
                return None

        # Copy template to output location
        try:
            shutil.copy(self.template_path, output_file)
            print(f"\n✓ Configuration template saved to: {output_file.absolute()}")

            # Copy examples folder to the same directory as the output file
            examples_copied = self._copy_examples_folder(output_file)

            # Show next steps
            self._print_next_steps(filename, examples_copied)

            return str(output_file.absolute())

        except Exception as e:
            print(f"\n✗ Error saving file: {e}")
            return None

    def _copy_examples_folder(self, output_file: Path) -> bool:
        """
        Copy the examples folder (YAML configs and scripts) to the same directory as the output file.

        Args:
            output_file: Path to the generated configuration file

        Returns:
            True if examples were copied successfully, False otherwise
        """
        try:
            # Destination is an 'examples' folder next to the output file
            examples_dest = output_file.parent / "examples"

            # Check if examples source exists
            if not self.examples_source.exists():
                print(f"\n⚠ Warning: Examples not found at {self.examples_source}")
                return False

            # Check if destination already exists
            if examples_dest.exists():
                print(f"\n⚠ Examples folder already exists at {examples_dest.absolute()}")
                prompt = "   Overwrite examples folder? (y/N): "
                try:
                    answer = input(prompt).strip().lower()
                    if not answer.startswith('y'):
                        print("   → Keeping existing examples folder")
                        return True
                except (KeyboardInterrupt, EOFError):
                    print("\n   → Keeping existing examples folder")
                    return True

                # Remove existing folder
                shutil.rmtree(examples_dest)

            # Copy the examples folder
            shutil.copytree(self.examples_source, examples_dest)
            print(f"✓ Examples copied to: {examples_dest.absolute()}")

            return True

        except Exception as e:
            print(f"\n⚠ Warning: Could not copy examples folder: {e}")
            return False

    def _print_header(self):
        """Print wizard header."""
        print("\n" + "=" * 70)
        print("           IOPS Benchmark Configuration Generator")
        print("=" * 70)
        print("\nThis will generate a comprehensive YAML configuration template")
        print("with all available options documented and ready to customize.")
        print("\nPress Ctrl+C at any time to cancel.\n")

    def _ask_filename(self) -> Optional[str]:
        """Ask for output filename."""
        try:
            default_name = "benchmark_config.yaml"
            prompt = f"→ Save template as [default: {default_name}]: "
            filename = input(prompt).strip()

            if not filename:
                filename = default_name

            return filename

        except (KeyboardInterrupt, EOFError):
            print("\n\n✗ Cancelled by user")
            sys.exit(0)

    def _confirm_overwrite(self, file_path: Path) -> bool:
        """Ask for confirmation to overwrite existing file."""
        try:
            prompt = f"\n⚠ File '{file_path}' already exists. Overwrite? (y/N): "
            answer = input(prompt).strip().lower()
            return answer.startswith('y')

        except (KeyboardInterrupt, EOFError):
            print("\n\n✗ Cancelled by user")
            sys.exit(0)

    def _print_next_steps(self, filename: str, examples_copied: bool):
        """Print next steps for the user."""
        print("\n" + "=" * 70)
        print("Next Steps:")
        print("=" * 70)
        print(f"\n1. Review example configurations:")
        if examples_copied:
            print(f"   • Check out example YAMLs in ./examples/ folder (organized by tool):")
            print(f"     IOR examples:")
            print(f"       - examples/ior/local/ior_simple.yaml - Basic local configuration")
            print(f"       - examples/ior/local/ior_bayesian.yaml - Bayesian optimization")
            print(f"       - examples/ior/slurm/ior_simple_slurm.yaml - SLURM cluster example")
            print(f"     mdtest examples:")
            print(f"       - examples/mdtest/local/mdtest_local.yaml - Local mdtest")
            print(f"       - examples/mdtest/slurm/mdtest_slurm.yaml - SLURM mdtest")
            print(f"   • Example scripts in tool-specific folders:")
            print(f"     - examples/ior/scripts/ior_parser.py - IOR parser")
            print(f"     - examples/ior/scripts/ior_slurm.sh - SLURM script for IOR")
        print(f"\n2. Edit the configuration:")
        print(f"   nano {filename}")
        print(f"   # or use your preferred editor")
        print(f"\n3. Customize the configuration:")
        print(f"   • Update paths (workdir, sqlite_db)")
        print(f"   • Adjust variables and their sweep ranges")
        print(f"   • Modify the command template")
        print(f"   • Update SLURM directives (partition, time, etc.)")
        if not examples_copied:
            print(f"   • Update script paths or use embedded scripts")
        print(f"\n4. Validate the configuration:")
        print(f"   iops {filename} --check_setup")
        print(f"\n5. Preview execution (dry-run):")
        print(f"   iops {filename} --dry-run")
        print(f"\n6. Run the benchmark:")
        print(f"   iops {filename}")
        print(f"\n7. Analyze results:")
        print(f"   iops --analyze /path/to/workdir/run_NNN")
        print("=" * 70 + "\n")
