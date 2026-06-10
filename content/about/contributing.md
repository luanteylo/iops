---
title: "Contributing to IOPS"
---


Guidelines for contributing to IOPS.

## Getting Started

1. **Fork the Repository**
   ```bash
   # Clone your fork
   git clone https://gitlab.inria.fr/YOUR_USERNAME/iops.git
   cd iops
   ```

2. **Set Up Development Environment**
   ```bash
   # Create virtual environment
   python3 -m venv iops_env
   source iops_env/bin/activate

   # Install in editable mode
   pip install -e .

   # Install development dependencies
   pip install -r requirements-dev.txt

   # Verify the setup
   pytest tests/
   ```

## Development Workflow

1. **Create a Branch**
   ```bash
   git checkout -b feature/my-new-feature
   # or
   git checkout -b fix/issue-description
   ```

2. **Make Changes**
   - Write clear, documented code
   - Add tests for new functionality
   - Update documentation as needed

3. **Run Tests**
   ```bash
   pytest tests/

   # With coverage
   pytest --cov=iops tests/
   ```

4. **Commit Changes**
   ```bash
   git add .
   git commit -m "Description of changes"
   ```

5. **Push and Create Merge Request**
   ```bash
   git push origin feature/my-new-feature
   ```
   Then create a merge request on GitLab.

## Code Style

- Follow PEP 8 guidelines
- Use type hints where appropriate
- Write docstrings for public functions and classes
- Keep functions focused and modular

## Testing

- Write unit tests for new functionality, and integration tests for major features
- Ensure existing tests pass
- Test with both local and SLURM executors when relevant

## Documentation

- Update documentation and add examples for new features
- Keep the YAML format reference up to date

## Reporting Issues

Please include:

- IOPS version (`iops --version`)
- Python version
- Operating system
- Configuration file (if relevant)
- Steps to reproduce
- Expected vs actual behavior
- Error messages or logs

## Feature Requests

Check existing issues first, then describe the use case and expected behavior clearly. A proof-of-concept helps if possible.

## Questions and Support

- **Issues**: [GitLab Issue Tracker](https://gitlab.inria.fr/lgouveia/iops/-/issues)
- **Discussions**: Use GitLab discussions for general questions

## License

By contributing to IOPS, you agree that your contributions will be licensed under the BSD 3-Clause License.

## Contact

- **Main Developers**:
  - Luan Teylo
  - Abdraman Mahamat
  - Francieli Boito
  - Mihail Popov
- **Team**: TADaaM - INRIA Bordeaux
- **Repository**: [https://gitlab.inria.fr/lgouveia/iops](https://gitlab.inria.fr/lgouveia/iops)
