"""Pre-built templates for common benchmark types."""

TEMPLATES = {
    "ior": {
        "name": "IOR Benchmark",
        "description": "I/O performance testing with IOR",
        "command_template": "ior -w -b {{ block_size_mb }}mb -t 1mb -O summaryFile={{ summary_file }} -O summaryFormat=JSON -o {{ output_path }}/output.ior",
        "suggested_vars": [
            {
                "name": "processes_per_node",
                "type": "int",
                "sweep_mode": "list",
                "values": [4, 8, 16],
            },
            {
                "name": "volume_size_gb",
                "type": "int",
                "sweep_mode": "list",
                "values": [1, 4, 8],
            },
            {
                "name": "block_size_mb",
                "type": "int",
                "expr": "(volume_size_gb * 1024) / processes_per_node",
            },
            {
                "name": "summary_file",
                "type": "str",
                "expr": "{{ execution_dir }}/summary_{{ execution_id }}_{{ repetition }}.json",
            },
        ],
        "metrics": [
            {"name": "bwMiB", "description": "Write bandwidth in MiB/s"}
        ],
        "parser_script": """def parse(file_path):
    import json
    with open(file_path) as f:
        data = json.load(f)
    # Extract write bandwidth from IOR JSON output
    return {'bwMiB': data['tests'][0]['Results'][0]['bwMiB']}
""",
    },
    "custom_script": {
        "name": "Custom Script",
        "description": "Run a custom benchmark script",
        "command_template": "bash {{ script_path }}",
        "suggested_vars": [
            {
                "name": "script_path",
                "type": "str",
                "sweep_mode": "list",
                "values": [],
            },
        ],
        "metrics": [],
        "parser_script": None,
    },
    "mpi_app": {
        "name": "MPI Application",
        "description": "Generic MPI application benchmark",
        "command_template": "mpirun -n {{ tasks }} {{ executable }} {{ args }}",
        "suggested_vars": [
            {
                "name": "nodes",
                "type": "int",
                "sweep_mode": "list",
                "values": [1, 2, 4],
            },
            {
                "name": "processes_per_node",
                "type": "int",
                "sweep_mode": "list",
                "values": [4, 8],
            },
            {
                "name": "tasks",
                "type": "int",
                "expr": "{{ nodes * processes_per_node }}",
            },
        ],
        "metrics": [
            {"name": "runtime", "description": "Execution time in seconds"}
        ],
        "parser_script": None,
    },
}


def get_template(template_name):
    """Get a template by name."""
    return TEMPLATES.get(template_name.lower())


def list_templates():
    """Get list of available template names with descriptions."""
    return [(name, tmpl["name"], tmpl["description"]) for name, tmpl in TEMPLATES.items()]
