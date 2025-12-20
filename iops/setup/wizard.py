"""Interactive wizard for creating IOPS benchmark configurations."""

import sys
from pathlib import Path
from typing import Optional
import shutil


class BenchmarkWizard:
    """Wizard for creating benchmark configurations from template."""

    def __init__(self):
        self.template_path = Path(__file__).parent / "template_full.yaml"

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

            # Show next steps
            self._print_next_steps(filename)

            return str(output_file.absolute())

        except Exception as e:
            print(f"\n✗ Error saving file: {e}")
            return None

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

    def _print_next_steps(self, filename: str):
        """Print next steps for the user."""
        print("\n" + "=" * 70)
        print("Next Steps:")
        print("=" * 70)
        print(f"\n1. Edit the configuration:")
        print(f"   nano {filename}")
        print(f"   # or use your preferred editor")
        print(f"\n2. Customize the configuration:")
        print(f"   • Update paths (workdir, sqlite_db)")
        print(f"   • Adjust variables and their sweep ranges")
        print(f"   • Modify the command template")
        print(f"   • Update SLURM directives (partition, time, etc.)")
        print(f"   • Optionally extract scripts to separate files")
        print(f"\n3. Validate the configuration:")
        print(f"   iops {filename} --check_setup")
        print(f"\n4. Preview execution (dry-run):")
        print(f"   iops {filename} --dry-run")
        print(f"\n5. Run the benchmark:")
        print(f"   iops {filename}")
        print(f"\n6. Analyze results:")
        print(f"   iops --analyze /path/to/workdir/run_NNN")
        print("=" * 70 + "\n")
