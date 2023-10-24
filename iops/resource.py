# IOPS Resource Classes
#
# This module contains the class definitions for different types of resources
# involved in the I/O Performance Evaluation Suite (IOPS). The primary objective
# of these classes is to handle and update various system parameters required
# for evaluating the peak I/O performance of a Parallel File System (PFS).
#


class Resource:
    def __init__(self, start: int, max_value: int) -> None:
        self.start = start
        self.current = start
        self.max_value = max_value

    def next_parameter(self, value: int):
        raise NotImplementedError("This method must be overridden by a subclass")
        
    def update_current_value(self, value: int) -> None:
        if value <= self.max_value:
            self.current = value
        else:
            raise ValueError(f"Value {value} exceeds the maximum limit {self.max_value}")

class ComputingNodes(Resource):
    def next_parameter(self, value: int):
        self.update_current_value(value)

class Processes(Resource):
    def next_parameter(self, value: int):
        self.update_current_value(value)

class BlockSize(Resource):
    def next_parameter(self, value: int):
        self.update_current_value(value)

class TransferSize(Resource):
    def next_parameter(self, value: int):
        self.update_current_value(value)

class OST(Resource):
    def next_parameter(self, value: int):
        self.update_current_value(value)