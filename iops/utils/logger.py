import logging
import textwrap
from pathlib import Path


class HasLogger:
    @property
    def logger(self) -> logging.Logger:
        return logging.getLogger(f"iops.{self.__class__.__name__}")


def setup_logger(
    name: str = "iops",
    log_file: Path | None = None,
    to_stdout: bool = True,
    to_file: bool = True,
    level: int = logging.INFO,
    max_width: int = 100,   # <-- CONTROL LINE WIDTH HERE
) -> logging.Logger:

    logger = logging.getLogger(name)
    logger.setLevel(level)

    if logger.hasHandlers():
        logger.handlers.clear()

    fmt = "%(asctime)s | %(levelname)-5s | %(message)s"
    if level <= logging.DEBUG:
        fmt = "%(asctime)s | %(levelname)-5s | %(class_tag)-15s | %(message)s"
    
    datefmt = "%Y-%m-%d %H:%M:%S"

    class WrappedMultilineFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            # Resolve class tag
            if record.name == "iops":
                record.class_tag = "IOPS"
            elif record.name.startswith("iops."):
                record.class_tag = record.name.split(".", 1)[1]
            else:
                record.class_tag = record.name

            # Format normally first
            raw = super().format(record)

            # Split prefix from message
            try:
                prefix, message = raw.rsplit(" | ", 1)
                prefix += " | "
            except ValueError:
                return raw  # fallback, should not happen

            wrapped_lines = []

            for line in message.splitlines() or [""]:
                wrapped = textwrap.wrap(
                    line,
                    width=max_width,
                    replace_whitespace=False,
                    drop_whitespace=False,
                    break_long_words=False,
                ) or [""]

                wrapped_lines.extend(wrapped)

            # Re-apply prefix to every wrapped line
            return "\n".join(prefix + line for line in wrapped_lines)

    formatter = WrappedMultilineFormatter(fmt, datefmt=datefmt)

    if to_stdout:
        sh = logging.StreamHandler()
        sh.setFormatter(formatter)
        logger.addHandler(sh)

    if to_file and log_file:
        fh = logging.FileHandler(log_file)
        fh.setFormatter(formatter)
        logger.addHandler(fh)

    return logger
