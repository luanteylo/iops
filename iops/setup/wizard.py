"""Interactive wizard for creating IOPS benchmark configurations."""

import sys
from pathlib import Path
from typing import Optional
import shutil


class BenchmarkWizard:
    """Wizard for creating benchmark configurations from templates."""

    # Template mapping: (benchmark, executor) -> template file
    TEMPLATES = {
        ("ior", "local"): "templates/ior_local.yaml",
        ("ior", "slurm"): "templates/ior_slurm.yaml",
        ("mdtest", "local"): "templates/mdtest_local.yaml",
        ("mdtest", "slurm"): "templates/mdtest_slurm.yaml",
    }

    def __init__(self):
        self.setup_dir = Path(__file__).parent
        self.full_template_path = self.setup_dir / "template_full.yaml"
        # Path to examples directory in the package
        package_root = Path(__file__).parent.parent.parent
        self.examples_source = package_root / "docs" / "examples"

    def _get_template_path(self, benchmark: str, executor: str) -> Path:
        """Get the path to the appropriate template file."""
        template_file = self.TEMPLATES.get((benchmark, executor))
        if template_file:
            return self.setup_dir / template_file
        # Fallback to IOR local if not found
        return self.setup_dir / "templates/ior_local.yaml"

    def run(
        self,
        output_path: Optional[str] = None,
        executor: str = "local",
        benchmark: str = "ior",
        full_template: bool = False,
        copy_examples: bool = False
    ) -> Optional[str]:
        """
        Generate a configuration template.

        Args:
            output_path: Optional path for the output file. If None, prompts user.
            executor: Executor type ("local" or "slurm")
            benchmark: Benchmark type ("ior" or "mdtest")
            full_template: If True, generate fully documented template with all options
            copy_examples: If True, copy example configurations and scripts

        Returns:
            Path to the generated file, or None if cancelled.
        """
        self._print_header(executor, benchmark, full_template)

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
                print("\n[X] Configuration not saved")
                return None

        # Select template
        if full_template:
            template_path = self.full_template_path
        else:
            template_path = self._get_template_path(benchmark, executor)

        # Copy template to output location
        try:
            if not template_path.exists():
                print(f"\n[X] Template not found: {template_path}")
                return None

            shutil.copy(template_path, output_file)
            print(f"\n[OK] Configuration template saved to: {output_file.absolute()}")

            # Copy examples folder only if requested
            examples_copied = False
            if copy_examples:
                examples_copied = self._copy_examples_folder(output_file)

            return str(output_file.absolute())

        except Exception as e:
            print(f"\n[X] Error saving file: {e}")
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
                print(f"\n[!] Warning: Examples not found at {self.examples_source}")
                return False

            # Check if destination already exists
            if examples_dest.exists():
                print(f"\n[!] Examples folder already exists at {examples_dest.absolute()}")
                prompt = "   Overwrite examples folder? (y/N): "
                try:
                    answer = input(prompt).strip().lower()
                    if not answer.startswith('y'):
                        print("   -> Keeping existing examples folder")
                        return True
                except (KeyboardInterrupt, EOFError):
                    print("\n   -> Keeping existing examples folder")
                    return True

                # Remove existing folder
                shutil.rmtree(examples_dest)

            # Copy the examples folder
            shutil.copytree(self.examples_source, examples_dest)
            print(f"[OK] Examples copied to: {examples_dest.absolute()}")

            return True

        except Exception as e:
            print(f"\n[!] Warning: Could not copy examples folder: {e}")
            return False

    def _print_header(self, executor: str, benchmark: str, full_template: bool):
        """Print wizard header."""
        print("\n" + "=" * 70)
        print("           IOPS Benchmark Configuration Generator")
        print("=" * 70)

        if full_template:
            print("\nGenerating FULL template with all options documented.")
        else:
            print(f"\nGenerating simple template: {benchmark.upper()} benchmark, {executor.upper()} executor")
            print("\nTip: Use 'iops generate --full' for a complete template with all options.")        

    def _ask_filename(self) -> Optional[str]:
        """Ask for output filename."""
        try:
            default_name = "benchmark_config.yaml"
            prompt = f"-> Save template as [default: {default_name}]: "
            filename = input(prompt).strip()

            if not filename:
                filename = default_name

            return filename

        except (KeyboardInterrupt, EOFError):
            print("\n\n[X] Cancelled by user")
            sys.exit(0)

    def _confirm_overwrite(self, file_path: Path) -> bool:
        """Ask for confirmation to overwrite existing file."""
        try:
            prompt = f"\n[!] File '{file_path}' already exists. Overwrite? (y/N): "
            answer = input(prompt).strip().lower()
            return answer.startswith('y')

        except (KeyboardInterrupt, EOFError):
            print("\n\n[X] Cancelled by user")
            sys.exit(0)

   