# IOPS Test Suite

Comprehensive test suite for the IOPS benchmark framework.

## Running Tests

### Quick Start

Run all tests:
```bash
./run_tests.sh
```

### Options

```bash
# Verbose output
./run_tests.sh -v

# With coverage report
./run_tests.sh -c

# Run specific test file
./run_tests.sh -t test_config.py

# Combine options
./run_tests.sh -v -c
```

### Using pytest directly

```bash
# Run all tests
pytest tests/

# Run specific test file
pytest tests/test_config.py

# Run specific test function
pytest tests/test_config.py::test_load_valid_config

# Verbose output
pytest tests/ -v

# Show print statements
pytest tests/ -s

# Stop on first failure
pytest tests/ -x

# Run with coverage
pytest tests/ --cov=iops --cov-report=html
```

## Test Organization

### `conftest.py`
Shared fixtures for all tests:
- `tmp_workdir`: Temporary working directory
- `sample_config_dict`: Basic config dictionary
- `sample_config_file`: YAML config file

### `test_config.py`
Configuration loading and validation:
- Valid config loading
- Missing fields detection
- Variable configuration (sweep, derived)
- Parser validation
- Output settings

### `test_matrix.py`
Execution matrix generation:
- Basic matrix building
- Variable expansion
- Derived variable computation
- Execution ID assignment
- Lazy template rendering
- Cartesian product generation

### `test_cache.py`
Execution caching:
- Cache initialization
- Store and retrieve operations
- Cache misses
- Repetition isolation
- Parameter normalization
- Variable exclusion
- Cache updates

### `test_executors.py`
Executor implementations:
- Executor registry
- LocalExecutor submission
- Post-script execution
- Failure handling
- SlurmExecutor job submission
- Job ID parsing
- Metadata initialization

### `test_integration.py`
End-to-end workflows:
- Complete execution workflow
- Cache integration
- Post-script processing
- Result verification

## Test Coverage

Current test coverage includes:
- ✅ Config loading and validation
- ✅ Execution matrix generation
- ✅ Variable expansion (sweep, derived, fixed)
- ✅ Cache operations (store, retrieve, update)
- ✅ Executor functionality (local, SLURM)
- ✅ Post-script execution
- ✅ End-to-end integration

## Adding New Tests

### 1. Create Test File

Create a new file in `tests/` directory:
```python
# tests/test_myfeature.py
import pytest

def test_my_feature():
    """Test description."""
    assert True
```

### 2. Use Fixtures

Leverage existing fixtures from `conftest.py`:
```python
def test_with_config(sample_config_file):
    """Test using sample config."""
    config = load_config(sample_config_file)
    assert config.benchmark.name == "Test Benchmark"
```

### 3. Create Custom Fixtures

Add fixtures in `conftest.py` or in your test file:
```python
@pytest.fixture
def my_fixture():
    """Custom fixture."""
    return {"key": "value"}
```

### 4. Mock External Dependencies

Use `unittest.mock` for mocking:
```python
from unittest.mock import Mock, patch

def test_with_mock():
    with patch("module.function") as mock_func:
        mock_func.return_value = "mocked"
        # test code
```

## Best Practices

1. **One assertion per test**: Keep tests focused and simple
2. **Use descriptive names**: `test_config_missing_required_field` is better than `test_error`
3. **Test edge cases**: Test boundary conditions, empty inputs, invalid data
4. **Use fixtures**: Avoid code duplication, use fixtures for common setup
5. **Mock external dependencies**: Don't rely on external systems (SLURM, file systems)
6. **Clean up**: Use `tmp_path` fixture for temporary files, pytest cleans up automatically

## Running Before Commits

### Pre-commit Hook

Create `.git/hooks/pre-commit`:
```bash
#!/bin/bash
./run_tests.sh
```

Make it executable:
```bash
chmod +x .git/hooks/pre-commit
```

### Manual Check

Always run tests before committing:
```bash
./run_tests.sh
git add .
git commit -m "Your commit message"
```

## Troubleshooting

### Import Errors

If you see import errors, install IOPS in development mode:
```bash
pip install -e .
```

### Missing Dependencies

Install test dependencies:
```bash
pip install pytest pytest-mock pytest-cov
```

### Failed Tests

Run with verbose output to see details:
```bash
./run_tests.sh -v
```

Show print statements:
```bash
pytest tests/ -s
```

Stop on first failure:
```bash
pytest tests/ -x
```

## Continuous Integration

Tests are designed to run in CI/CD pipelines:
```yaml
# Example GitHub Actions
- name: Run tests
  run: |
    pip install -e .
    pip install pytest pytest-mock
    pytest tests/
```
