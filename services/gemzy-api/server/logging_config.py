"""Structured JSON logging configuration."""
import os
import sys
import json
import logging
from datetime import datetime

class JsonFormatter(logging.Formatter):
    """Format logs as JSON."""
    def format(self, record):
        log_record = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "module": record.module,
            "func": record.funcName,
        }
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_record)

def setup_logging():
    """Configure structured logging."""
    # Check if we should use JSON formatting (e.g. in production)
    use_json = os.getenv("LOG_FORMAT", "text") == "json"
    
    if use_json:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    else:
        # Standard logging for local development
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
