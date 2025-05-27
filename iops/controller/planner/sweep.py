from typing import List, Dict, Any
from dataclasses import dataclass

from iops.utils.config_loader import IOPSConfig
from iops.controller.planner.base_planner import BasePlanner, PhaseResult, Phase
from iops.utils.logger import HasLogger

class SweepPlanner(BasePlanner, HasLogger):
    """
    Planner that executes a sequence of parameter sweeps.
    Each phase varies one parameter while fixing others,
    recording the best value per phase.
    """

    def __init__(self, config: IOPSConfig):
        self.config = config
        self.history: Dict[str, Any] = {}
        self._phases = self._init_phases()

    def _init_phases(self) -> List[Phase]:
        self.logger.debug("Initializing phases for SweepPlanner")
        
        volume_range = list(range(
            self.config.storage.min_volume,
            self.config.storage.max_volume + 1,
            self.config.storage.volume_step
        ))

        nodes_range = [2**i for i in range(
            self.config.nodes.min_nodes.bit_length() - 1,
            self.config.nodes.max_nodes.bit_length()
        )]

        stripe_folders = self.config.storage.stripe_folders

        full_param_space = {
            "volume": volume_range,
            "min_nodes": nodes_range,
            "stripe_folder": stripe_folders
        }

        fixed_params = {
            "processes_per_node": self.config.nodes.processes_per_node,
            "cores_per_node": self.config.nodes.cores_per_node,
            "filesystem_dir": self.config.storage.filesystem_dir,
            "workdir": self.config.execution.workdir
        }

        return [
            Phase(
                name="file_size",
                sweep_param="volume",
                values=volume_range,
                fixed_params=fixed_params.copy(),
                full_param_space=full_param_space,
                criterion="max_files"
            ),
            Phase(
                name="nodes",
                sweep_param="min_nodes",
                values=nodes_range,
                fixed_params=fixed_params.copy(),
                full_param_space=full_param_space,
                criterion="max_nodes"
            ),
            Phase(
                name="striping",
                sweep_param="stripe_folder",
                values=stripe_folders,
                fixed_params=fixed_params.copy(),
                full_param_space=full_param_space,
                criterion="bandwidth_avg"
            )
        ]

    def phases(self) -> List[Phase]:
        """
        Returns the list of phases to execute.
        """
        self.logger.debug(f"Available phases: {[phase.name for phase in self._phases]}")
        return self._phases

    def update_for_next_phase(self, result: PhaseResult):
        """
        Updates all remaining phases with the best parameters
        found in the last completed phase.
        """
        self.history.update(result.best_params)
        for phase in self._phases:
            self.logger.debug(f"Updating phase '{phase.name}' with history: {self.history}")
            phase.fixed_params.update(self.history)
