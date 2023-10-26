from rich.console import Console
from rich.progress import Progress

from typing import List

class Analyzer:
    def __init__(self) -> None:
        self.console = Console() 
    def check_result(self) -> Test:
        raise NotImplementedError("This method must be overridden by a subclass")
    



class IORAnalyzer(Analyzer):
    def __init__(self) -> None:
        super().__init__()
        self.console = Progress(console=None)  
        self.console.print(f"Starting {self.__class__.__name__}")

    def check_result(self, result: Result) -> Test:        
        return Test()