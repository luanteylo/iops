import json

def parse(file_path: str):
    """
    IOR JSON parser.

    Returns a dict with ALL fields from the first write Results entry:
        - bwMiB
        - blockKiB
        - xferKiB
        - iops
        - latency
        - openTime
        - wrRdTime
        - closeTime
        - totalTime
        - access
    """
    with open(file_path, "r") as f:
        data = json.load(f)

    # Prefer tests[].Results (per-execution detailed metrics)
    tests = data.get("tests", [])
    if not tests:
        raise ValueError("No tests found in IOR JSON")

    results = tests[0].get("Results", [])
    if not results:
        raise ValueError("No Results found in IOR JSON")

    # Pick the write result (or the first one if only one exists)
    write_res = next(
        (r for r in results if str(r.get("access", "")).lower() == "write"),
        results[0],
    )

    # Return everything as-is
    return write_res