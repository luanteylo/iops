# Publishing IOPS to PyPI

This guide explains how to publish IOPS to PyPI so users can install it with `pip install iops`.

## Prerequisites

1. Create accounts on:
   - [PyPI](https://pypi.org/account/register/) (production)
   - [TestPyPI](https://test.pypi.org/account/register/) (testing)

2. Install required tools:
   ```bash
   pip install --upgrade build twine
   ```

3. Configure PyPI credentials:
   ```bash
   # Create ~/.pypirc file
   cat > ~/.pypirc << EOF
   [distutils]
   index-servers =
       pypi
       testpypi

   [pypi]
   username = __token__
   password = pypi-YOUR-API-TOKEN-HERE

   [testpypi]
   username = __token__
   password = pypi-YOUR-TESTPYPI-TOKEN-HERE
   EOF

   chmod 600 ~/.pypirc
   ```

## Build the Package

```bash
# Clean previous builds
rm -rf dist/ build/ *.egg-info

# Build source distribution and wheel
python -m build

# Verify the build
ls -lh dist/
# Should show:
# - iops-X.Y.Z-py3-none-any.whl
# - iops-X.Y.Z.tar.gz
```

## Test the Package (Optional but Recommended)

```bash
# Upload to TestPyPI
twine upload --repository testpypi dist/*

# Test installation from TestPyPI in a clean environment
python -m venv test_env
source test_env/bin/activate
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ iops

# Verify it works
iops --version
deactivate
rm -rf test_env
```

## Publish to PyPI

```bash
# Upload to PyPI (production)
twine upload dist/*

# Verify the upload
# Visit: https://pypi.org/project/iops/

# Test installation
pip install iops
iops --version
```

## Post-Publication

1. Update README.md to remove the "Coming Soon" note from the PyPI installation section
2. Create a git tag for the release:
   ```bash
   git tag -a v3.0.0 -m "Release version 3.0.0"
   git push origin v3.0.0
   ```

## Troubleshooting

### Package name already exists
If `iops` is already taken on PyPI, you may need to use a different name like:
- `iops-benchmark`
- `iops-suite`
- `io-performance-suite`

Update the name in:
- `setup.py` (name parameter)
- `pyproject.toml` ([project] name)

### Build errors
- Ensure all dependencies are properly specified in `requirements.txt` and `pyproject.toml`
- Check that all necessary files are included in `MANIFEST.in`

### Upload errors
- Verify your PyPI API token is correct
- Check that the version number in `iops/VERSION` hasn't been published before
- Ensure you have proper permissions for the package

## Version Management

To publish a new version:

1. Update `iops/VERSION` file:
   ```bash
   echo "3.0.1" > iops/VERSION
   ```

2. Commit the version change:
   ```bash
   git add iops/VERSION
   git commit -m "Release version 3.0.1"
   git push
   ```

3. Build and upload:
   ```bash
   rm -rf dist/ build/ *.egg-info
   python -m build
   twine upload dist/*
   ```

4. Create a git tag:
   ```bash
   git tag -a v3.0.1 -m "Release version 3.0.1"
   git push origin v3.0.1
   ```

## Security Notes

- Never commit your PyPI API tokens to version control
- Use API tokens instead of passwords for better security
- Consider using GitHub Actions or GitLab CI for automated releases
