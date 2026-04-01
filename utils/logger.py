import sys
import os
import atexit
import warnings
import logging

# Suppress ResourceWarning for unclosed files in non-critical threads
warnings.filterwarnings('ignore', category=ResourceWarning)

class OnlyInfo(logging.Filter):
    """Filter that only allows INFO level messages."""
    def filter(self, record):
        return record.levelno == logging.INFO

class Logger:
    """Custom logger with separate files for different log levels."""
    
    def __init__(self):
        self.log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
        os.makedirs(self.log_dir, exist_ok=True)
        self.logger = logging.getLogger(__name__)
        self.setup_logger()
 
    def setup_logger(self):
        """Configure logger with multiple handlers for info and error logs."""
        self.logger.setLevel(logging.DEBUG)
        
        formatter = logging.Formatter(
            '%(asctime)s - %(funcName)s - %(levelname)s - %(message)s', 
            datefmt='%d/%m/%Y %I:%M:%S'
        )
 
        self.logger.handlers.clear()
 
        info_handler = logging.FileHandler(
            os.path.join(self.log_dir, "info.log"), 
            encoding="utf-8"
        )
        info_handler.setLevel(logging.INFO)
        info_handler.addFilter(OnlyInfo())
        info_handler.setFormatter(formatter)
 
        error_handler = logging.FileHandler(
            os.path.join(self.log_dir, "error.log"), 
            encoding="utf-8"
        )
        error_handler.setLevel(logging.ERROR) 
        error_handler.setFormatter(formatter)
 
        self.logger.addHandler(info_handler)
        self.logger.addHandler(error_handler)
        self.logger.propagate = False

        # Ensure handlers are cleanly closed on exit
        atexit.register(self._close_handlers)

        return self.logger

    def _close_handlers(self):
        """Explicitly close all file handlers to prevent ResourceWarning."""
        for handler in self.logger.handlers[:]:
            try:
                handler.flush()
                handler.close()
            except Exception:
                pass

_logger_instance = Logger()
logger = _logger_instance.logger

def log_info(message: str, agent: str = None):
    """Log info message with optional agent name."""
    if agent:
        logger.info(f"[{agent}] {message}")
    else:
        logger.info(message)

def log_error(message: str, agent: str = None):
    """Log error message with optional agent name."""
    if agent:
        logger.error(f"[{agent}] {message}")
    else:
        logger.error(message)

def log_debug(message: str, agent: str = None):
    """Log debug message with optional agent name."""
    if agent:
        logger.debug(f"[{agent}] {message}")
    else:
        logger.debug(message)

def log_warning(message: str, agent: str = None):
    """Log warning message with optional agent name."""
    if agent:
        logger.warning(f"[{agent}] {message}")
    else:
        logger.warning(message)
