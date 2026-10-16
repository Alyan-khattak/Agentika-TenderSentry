"""
TenderSentry Logging Module

Configures a single logger instance that writes to both console and file.
The logger is exported as 'logging' to avoid shadowing the stdlib logging module.

This module must be imported at the repo root (not from inside the logging/ folder)
to avoid shadowing the standard library logging module.

Import pattern:
    from tendersentry.logging.logger import logging
    logging.info("Application started")
    logging.error("An error occurred")

The logger writes to:
- Console (StreamHandler): for real-time visibility
- File (logs/tendersentry.log): for persistent audit trail

Format: [ISO timestamp] logger_name - LEVEL - message
"""

import logging as _logging
import os
from tendersentry.constants import LOGS_DIR


# Create logs directory if it doesn't exist
os.makedirs(LOGS_DIR, exist_ok=True)

# Create a single logger instance for the entire application
logging = _logging.getLogger("tendersentry")
logging.setLevel(_logging.INFO)

# Define log format: timestamp, logger name, level, message
log_format = _logging.Formatter(
    "[%(asctime)s] %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# Console handler: print to stdout in real time
console_handler = _logging.StreamHandler()
console_handler.setLevel(_logging.INFO)
console_handler.setFormatter(log_format)
logging.addHandler(console_handler)

# File handler: write to logs/tendersentry.log
log_file_path = os.path.join(LOGS_DIR, "tendersentry.log")
file_handler = _logging.FileHandler(log_file_path)
file_handler.setLevel(_logging.INFO)
file_handler.setFormatter(log_format)
logging.addHandler(file_handler)

# Prevent duplicate logs if logging is configured multiple times
logging.propagate = False
