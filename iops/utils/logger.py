import logging
from pathlib import Path


class HasLogger:
    """
    Mixin to inject a class-specific logger named as 'iops.ClassName'.
    """
    @property
    def logger(self) -> logging.Logger:
        return logging.getLogger(f"iops.{self.__class__.__name__}")


def setup_logger(
    name: str = "iops",
    log_file: Path | None = None,
    to_stdout: bool = True,
    to_file: bool = True,
    level: int = logging.INFO,
) -> logging.Logger:
    """
    Configure and return a logger that can log to stdout and/or a file.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if logger.hasHandlers():
        logger.handlers.clear()

    log_format = "[%(asctime)s] [%(class_tag)s] %(levelname)s: %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    class ClassTagFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            record.class_tag = record.name.split(".")[-1] if record.name.startswith("iops.") else record.name
            return super().format(record)

    formatter = ClassTagFormatter(log_format, datefmt=date_format)

    if to_stdout:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    if to_file and log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger
