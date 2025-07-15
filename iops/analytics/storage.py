from iops.utils.config_loader import IOPSConfig
from iops.utils.config_loader import to_dictionary
from iops.utils.logger import HasLogger

from sqlmodel import SQLModel, Field, Relationship
from sqlmodel import create_engine, Session, select

from typing import Optional
from datetime import datetime
import hashlib
import json



def hash_func(setup: dict) -> str:
    """
    Generate a unique hash for the given dictionary.
    """
    return hashlib.md5(json.dumps(setup, sort_keys=True).encode()).hexdigest()



class ExecutionDB(SQLModel, table=True):
    """
    Table representing a single IOPS benchmark session. Stores environment-related
    information and search space context for the test campaign.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.now, description="Timestamp when the execution was started")
    setup_json: str = Field(description="Serialized JSON describing the full setup/search space config")
    machine: Optional[str] = Field(default=None, description="Machine/environment name where execution was run")

    # One-to-many relationship
    tests: list["TestDB"] = Relationship(back_populates="execution")


class TestDB(SQLModel, table=True):
    """
    Table representing a single benchmark test run. Each row corresponds to a unique
    execution of a parameter set, possibly one of several repetitions.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    execution_id: int = Field(foreign_key="executiondb.id", nullable=False, description="Execution session this test belongs to")
    param_hash: str = Field(index=True, nullable=False, description="Hash of the test parameters")
    param_json: str = Field(nullable=False, description="Full JSON-encoded test parameters")
    repetition: int = Field(default=0, description="Index of this repetition for the given parameter set")
    status: str = Field(default="pending", description="Test execution status: pending, executed, failed, cached")
    result_json: Optional[str] = Field(default=None, description="Raw test result as JSON")

    execution: Optional[ExecutionDB] = Relationship(back_populates="tests")


class TestAggregateDB(SQLModel, table=True):
    """
    Table storing externally computed summary metrics (e.g., avg BW, stddev)
    for a parameter set, identified by param_hash and execution context.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    execution_id: int = Field(foreign_key="executiondb.id", nullable=False, description="Execution session this summary belongs to")
    param_hash: str = Field(index=True, nullable=False, description="Hash of the parameter set being summarized")
    metrics_json: str = Field(nullable=False, description="Aggregate metrics (e.g., avg, std) in JSON format")


    

class MetricsStorage(HasLogger):
    """
    Manages persistent storage of execution metadata, test runs, and aggregate metrics
    using a SQLite database and SQLModel.
    """

    def __init__(self, config: IOPSConfig):
        super().__init__()
        self.config = config
        self.db_path = self.config.environment.sqlite_db
        self.engine = create_engine(f"sqlite:///{self.db_path}")
        SQLModel.metadata.create_all(self.engine)

    def hash_params(self, params: dict) -> str:
        """Generate a stable hash for a parameter set (excluding metadata)."""
        norm = {k: v for k, v in sorted(params.items()) if not k.startswith("__")}
        return hashlib.md5(json.dumps(norm, sort_keys=True).encode()).hexdigest()

    def save_execution(self) -> int:
        """Insert or reuse an ExecutionDB row."""
        setup_dict = to_dictionary(self.config)
        setup_json = json.dumps(setup_dict, sort_keys=True)
        machine = setup_dict.get("machine", "unknown")

        with Session(self.engine) as session:
            existing = session.exec(
                select(ExecutionDB).where(ExecutionDB.setup_json == setup_json)
            ).first()
            if existing:
                self.logger.info(f"Execution already exists (id={existing.id}).")
                return existing.id

            exec_entry = ExecutionDB(setup_json=setup_json, machine=machine)
            session.add(exec_entry)
            session.commit()
            session.refresh(exec_entry)
            self.logger.info(f"New execution saved with id={exec_entry.id}")
            return exec_entry.id

    def save_test(self, execution_id: int, params: dict, repetition: int, status: str, result: Optional[dict]) -> int:
        """Insert or reuse a TestDB row."""
        
        # drop metadata keys from params
        params = {k: v for k, v in params.items() if not k.startswith("__")}
        param_hash = self.hash_params(params)

        with Session(self.engine) as session:
            existing = session.exec(
                select(TestDB).where(
                    TestDB.execution_id == execution_id,
                    TestDB.param_hash == param_hash,
                    TestDB.repetition == repetition
                )
            ).first()
            if existing:
                self.logger.info(f"Test already exists (id={existing.id})")
                return existing.id

            test = TestDB(
                execution_id=execution_id,
                param_hash=param_hash,
                param_json=json.dumps(params, sort_keys=True),
                repetition=repetition,
                status=status,
                result_json=json.dumps(result) if result else None
            )
            session.add(test)
            session.commit()
            session.refresh(test)
            self.logger.info(f"New test saved with id={test.id}")
            return test.id

    def get_test_by_hash(self, execution_id: int, param_hash: str, repetition: int = 0) -> Optional[TestDB]:
        """Lookup a specific test by hash and repetition."""
        with Session(self.engine) as session:
            return session.exec(
                select(TestDB).where(
                    TestDB.execution_id == execution_id,
                    TestDB.param_hash == param_hash,
                    TestDB.repetition == repetition
                )
            ).first()

    def save_aggregate(self, execution_id: int, param_hash: str, metrics: dict) -> int:
        """Store externally computed aggregate metrics for a test group."""
        with Session(self.engine) as session:
            existing = session.exec(
                select(TestAggregateDB).where(
                    TestAggregateDB.execution_id == execution_id,
                    TestAggregateDB.param_hash == param_hash
                )
            ).first()
            if existing:
                self.logger.info(f"Aggregate already exists (id={existing.id})")
                return existing.id

            agg = TestAggregateDB(
                execution_id=execution_id,
                param_hash=param_hash,
                metrics_json=json.dumps(metrics, sort_keys=True)
            )
            session.add(agg)
            session.commit()
            session.refresh(agg)
            self.logger.info(f"Aggregate saved with id={agg.id}")
            return agg.id
