
from iops.utils.logger import HasLogger

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


class Executions(SQLModel, table=True):
    execution_id: Optional[int] = Field(primary_key=True, default=None)
    created_at: datetime = Field(default_factory=datetime.now)
    setup_json: str
    setup_hash: str = Field(default=None, index=True)
    machine_name: Optional[str] = Field(default=None)
    status: str = Field(default="running")  # running, interrupted, completed

    tests: list["Tests"] = Relationship(back_populates="execution")
    summaries: list["TestSummaries"] = Relationship(back_populates="execution")


class Tests(SQLModel, table=True):
    test_id: Optional[int] = Field(default=None, primary_key=True)
    param_hash: str 
    repetition: int 
    execution_id: int = Field(foreign_key="executions.execution_id")    
    param_json: str
    result_json: Optional[str] = Field(default=None)
    status: str = Field(default="pending")  # pending, running, completed, failed

    execution: Optional[Executions] = Relationship(back_populates="tests")


class TestSummaries(SQLModel, table=True):
    summary_id: Optional[int] = Field(default=None, primary_key=True)
    execution_id: int = Field(foreign_key="executions.execution_id")
    sweep_param: str
    created_at: datetime = Field(default_factory=datetime.now)
    param_hash: str
    param_json: str
    metrics_json: str

    execution: Optional[Executions] = Relationship(back_populates="summaries")


class MetricsStorage(HasLogger):
    def __init__(self, db_path: Path, create_file: bool = True):
        super().__init__()
        if not create_file and not db_path.exists():
            raise FileNotFoundError(f"The database file {db_path} does not exist.")
        
        self.db_path = db_path
        self.engine = create_engine(f"sqlite:///{self.db_path}")
        SQLModel.metadata.create_all(self.engine)

    def hash_params(self, params: dict[str, Any]) -> str:
        norm = {k: v for k, v in sorted(params.items()) if not k.startswith("__")}
        return hashlib.md5(json.dumps(norm, sort_keys=True).encode()).hexdigest()

    def save_execution(self, setup_dict) -> Executions:
        setup_json = json.dumps(setup_dict, sort_keys=True)
        setup_hash = self.hash_params(setup_dict)
        machine = setup_dict.get("machine_name", "unknown")

        with Session(self.engine) as session:
            existing = session.exec(
                select(Executions).where(Executions.setup_hash == setup_hash)
            ).first()
            if existing:
                self.logger.debug(f"Execution already exists (id={existing.execution_id}).")
                return existing

            exec_entry = Executions(
                setup_json=setup_json,
                setup_hash=setup_hash,
                machine_name=machine
            )
            session.add(exec_entry)
            session.commit()
            session.refresh(exec_entry)
            self.logger.debug(f"New execution saved with id={exec_entry.execution_id}")
            return exec_entry

    def save_test(self, execution_id: int, params: dict[str, Any], repetition: int, status: str, result: dict[str, Any]) -> Tests:
        params_clean = {k: v for k, v in params.items() if not k.startswith("__")}
        param_hash = self.hash_params(params_clean)

        with Session(self.engine) as session:          
            test = Tests(
                execution_id=execution_id,
                param_hash=param_hash,
                param_json=json.dumps(params_clean, sort_keys=True),                
                repetition=repetition,
                status=status,
                result_json=json.dumps(result) 
            )
            session.add(test)
            session.commit()
            session.refresh(test)
            self.logger.debug(f"New test saved: {param_hash} (rep={repetition})")

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

    def get_test(self, param: dict[str, Any], repetition: int) -> Optional[Tests]:
        param_hash = self.hash_params(param)
        with Session(self.engine) as session:
            return session.exec(
                select(Tests).where(
                    Tests.param_hash == param_hash,
                    Tests.repetition == repetition
                )
            ).first()
    
    def get_execution(self, execution_id: int) -> Optional[Executions]:
        with Session(self.engine) as session:
            return session.exec(
                select(Executions).where(Executions.execution_id == execution_id)
            ).first()
    def save_summary(self, execution_id: int, param_sweep: str, param: dict[str, Any], metrics: dict[str, Any]) -> None:
        param_hash = self.hash_params(param)

        with Session(self.engine) as session:       
            summary = TestSummaries(
                execution_id=execution_id,
                param_hash=param_hash,
                sweep_param=param_sweep,
                param_json=json.dumps(param, sort_keys=True),
                metrics_json=json.dumps(metrics, sort_keys=True)
            )
            session.add(summary)
            session.commit()
            self.logger.debug(f"Summary saved for execution {execution_id}, sweep_param {param_sweep}, hash {param_hash}")

    def refresh(self, obj: SQLModel) -> SQLModel:
        """Refresh a SQLModel instance from the database."""
        with Session(self.engine) as session:
            session.refresh(obj)
            return obj

    def update_status(self, obj: SQLModel, status: str) -> None:
        """Update the status of an Executions or Tests instance."""
        with Session(self.engine) as session:
            obj.status = status
            session.add(obj)
            session.commit()
            session.refresh(obj)
