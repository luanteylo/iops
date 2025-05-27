from iops.controller.planner.base_planner import BasePlanner

class BayesianPlanner(BasePlanner):
    def __init__(self, config):
        #self.optimizer = Optimizer(
        #    dimensions=[(1, 32), (1024, 8192)],
        #    base_estimator="GP"
        #)
        self.history = []
        #...

    def phases(self):
        yield {"min_nodes": 2, "volume": 4096}  # Just an example

    def update_for_next_phase(self, result):
        self.optimizer.tell(list(result.values()), result["bandwidth_avg"])
