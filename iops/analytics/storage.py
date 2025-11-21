
from iops.utils.logger import HasLogger
from sqlalchemy.orm import selectinload
from sqlmodel import (
    SQLModel,
    Field,
    Relationship,
    create_engine,
    Session,
    select,
)

from typing import Optional, Any
from datetime import datetime
import hashlib
import json
from pathlib import Path


class Tests(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)    
    param_hash: str    
    repetition: int  
    phase_index: int    
    test_index: int     
    sweep_param: str    
    param_json: str
    result_json: Optional[str] = Field(default=None)
    status: str = Field(default="pending")  # pending, running, completed, failed
    created_at: datetime = Field(default_factory=datetime.now) 




class MetricsStorage(HasLogger):
    def __init__(self, db_path: Path, read_only: bool = False):
        super().__init__()
        
        self.db_path = db_path
        self.engine = create_engine(f"sqlite:///{self.db_path}")

        if not read_only:
            SQLModel.metadata.create_all(self.engine)

    def _normalize_value(self, v):
            if isinstance(v, str):
                # Check if it's an integer
                if v.isdigit():
                    return int(v)
                # Check if it's a float
                try:
                    return float(v)
                except ValueError:
                    return v  # leave as string if not numeric
            return v  # leave as-is if already int/float/None/etc.
    
    def hash_params(self, params: dict[str, any]) -> str:
        # Filter out __keys and normalize
        norm = {k: self._normalize_value(v) for k, v in sorted(params.items())
                if not k.startswith("__") and k != "all"}
        return hashlib.md5(json.dumps(norm, sort_keys=True).encode()).hexdigest()
    
    def save_test(self, params: dict[str, Any], status: str, result: dict[str, Any] = None) -> Tests:
        phase_index = params.get("__phase_index")
        sweep_param = params.get("__phase_sweep_param")
        test_index = params.get("__test_index")        
        repetition_index = params.get("__test_repetition")
       
        params_clean = {k: v for k, v in params.items() if not k.startswith("__")}
        param_hash = self.hash_params(params_clean)

        with Session(self.engine) as session:          
            test = Tests(
                param_hash=param_hash,
                repetition=repetition_index,
                phase_index=phase_index,
                test_index=test_index,
                sweep_param=sweep_param,
                param_json=json.dumps(params_clean, sort_keys=True),
                result_json= json.dumps(result, sort_keys=True) if result else None,
                status=status,
            )
            session.add(test)
            session.commit()
            session.refresh(test)
            self.logger.debug(f"New test saved: {param_hash} (rep={repetition_index})")

            return test
    
    def update_test(self, test: Tests, status: str, result: Optional[dict[str, Any]] = None) -> Tests:
        """Update the status and result of a test."""
        with Session(self.engine) as session:
            test.status = status
            if result is not None:
                test.result_json = json.dumps(result, sort_keys=True)
            session.add(test)
            session.commit()
            session.refresh(test)
            self.logger.debug(f"Test updated: {test.param_hash} (rep={test.repetition}), status={status}")
            return test

    def get_test(self, param: dict[str, Any], repetition: int, status="SUCCESS") -> Optional[Tests]:
        # get the most recent test for the given parameters and repetition
        param_hash = self.hash_params(param)
        with Session(self.engine) as session:
            return session.exec(
                select(Tests)
                .where(
                    Tests.param_hash == param_hash,
                    Tests.repetition == repetition,
                    Tests.status == status
                )
                .order_by(Tests.created_at.desc())
            ).first()                            
    
   