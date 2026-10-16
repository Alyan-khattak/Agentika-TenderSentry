"""
TenderSentry Exception Module

Custom exception class that captures the file name and line number from the point
where an error occurred, enabling precise error tracking in logs and reports.

This module is the only place exceptions are defined. All errors raised throughout
the application are instances of TenderSentryException (never bare Exception or
custom exceptions).

Import pattern:
    from tendersentry.exception.exception import TenderSentryException
"""

import sys


class TenderSentryException(Exception):
    """
    Base exception for TenderSentry. Captures file name and line number from the
    exception context (sys.exc_info()) and formats them in the error message.

    Args:
        error_message (str): Human-readable error message
        error_detail (sys module): The sys module, used to extract traceback info

    Example:
        try:
            some_operation()
        except Exception as e:
            raise TenderSentryException("Operation failed", sys)
    """

    def __init__(self, error_message: str, error_detail: sys):
        super().__init__(error_message)
        self.error_message = error_message

        # Extract file name and line number from the exception traceback
        _, _, exc_tb = error_detail.exc_info()
        if exc_tb is not None:
            self.lineno = exc_tb.tb_lineno
            self.filename = exc_tb.tb_frame.f_code.co_filename
        else:
            # Fallback if traceback is unavailable
            self.lineno = "unknown"
            self.filename = "unknown"

    def __str__(self) -> str:
        """Return formatted error message with file and line number."""
        return f"Error in script [{self.filename}] at line [{self.lineno}]: {self.error_message}"
