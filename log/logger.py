import os
import logging
from datetime import datetime
import structlog


class CustomLogger:
    def __init__(self, log_dir="logs"):
        # Ensure logs directory exists
        self.logs_dir = os.path.join(os.getcwd(), log_dir)
        os.makedirs(self.logs_dir, exist_ok=True)

        # Timestamped log file (for persistence)
        log_file = f"{datetime.now().strftime('%m_%d_%Y_%H_%M_%S')}.log"
        self.log_file_path = os.path.join(self.logs_dir, log_file)

    def get_logger(self, name=__file__):
        logger_name = os.path.basename(name)

        # Configure logging for console + file (both JSON)
        file_handler = logging.FileHandler(self.log_file_path)
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(logging.Formatter("%(message)s"))  # Raw JSON lines

        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(logging.Formatter("%(message)s"))

        # IMPORTANT: we must not stack handlers repeatedly if imported multiple times
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)

        # Clear existing handlers to avoid duplicates
        if root_logger.handlers:
            root_logger.handlers.clear()

        root_logger.addHandler(console_handler)
        root_logger.addHandler(file_handler)

        # Configure structlog for JSON structured logging
        structlog.configure(
            processors=[
                structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
                structlog.processors.add_log_level,
                structlog.processors.EventRenamer(to="event"),
                structlog.processors.JSONRenderer(),
            ],
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )

        return structlog.get_logger(logger_name)