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

            # Build the full message body (including exception/stack text)
            message = record.getMessage()
            if record.exc_info and not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
            if record.exc_text:
                message = f"{message}\n{record.exc_text}" if message else record.exc_text
            if record.stack_info:
                message = f"{message}\n{self.formatStack(record.stack_info)}"

            # Compute the prefix by rendering the format string with an empty
            # message. Splitting the formatted record on " | " is not safe
            # because messages themselves routinely contain that separator
            # (e.g. per-test metric summaries).
            record.message = ""
            if self.usesTime():
                record.asctime = self.formatTime(record, self.datefmt)
            prefix = self.formatMessage(record)

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
