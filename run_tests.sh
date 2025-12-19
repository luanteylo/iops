#!/bin/bash
# IOPS Test Runner
# Run this script before committing changes

set -e  # Exit on error

echo "============================================"
echo "IOPS Test Suite"
echo "============================================"
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if pytest is installed
if ! command -v pytest &> /dev/null; then
    echo -e "${RED}ERROR: pytest is not installed${NC}"
    echo "Install with: pip install pytest pytest-mock"
    exit 1
fi

# Parse arguments
VERBOSE=""
COVERAGE=""
SPECIFIC_TEST=""

while [[ $# -gt 0 ]]; do
    case $1 in
        -v|--verbose)
            VERBOSE="-v"
            shift
            ;;
        -c|--coverage)
            COVERAGE="--cov=iops --cov-report=term-missing"
            shift
            ;;
        -t|--test)
            SPECIFIC_TEST="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: ./run_tests.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  -v, --verbose     Verbose output"
            echo "  -c, --coverage    Run with coverage report"
            echo "  -t, --test FILE   Run specific test file"
            echo "  -h, --help        Show this help message"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

# Change to script directory
cd "$(dirname "$0")"

echo -e "${YELLOW}Running tests...${NC}"
echo ""

# Run pytest
if [ -n "$SPECIFIC_TEST" ]; then
    echo "Running specific test: $SPECIFIC_TEST"
    pytest tests/$SPECIFIC_TEST $VERBOSE $COVERAGE
else
    pytest tests/ $VERBOSE $COVERAGE
fi

EXIT_CODE=$?

echo ""
echo "============================================"
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✓ All tests passed!${NC}"
    echo "============================================"
    exit 0
else
    echo -e "${RED}✗ Some tests failed${NC}"
    echo "============================================"
    exit $EXIT_CODE
fi
