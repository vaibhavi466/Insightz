import json
import logging
from datetime import datetime, timezone

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage()
        }
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        
        # Capture any extra parameters passed to logger (e.g., extra={"user": "...", "latency_ms": 123})
        for key, value in record.__dict__.items():
            if key not in {
                "args", "asctime", "created", "exc_info", "exc_text", "filename", 
                "funcName", "levelname", "levelno", "lineno", "module", "msecs", 
                "message", "msg", "name", "pathname", "process", "processName", 
                "relativeCreated", "stack_info", "thread", "threadName"
            }:
                log_entry[key] = value
        return json.dumps(log_entry)

def setup_json_logging():
    root_logger = logging.getLogger()
    
    # Configure standard console stream handler with JSONFormatter
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    
    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)
    
    # Apply to uvicorn loggers specifically to intercept access/error logs
    for logger_name in ["uvicorn", "uvicorn.error", "uvicorn.access"]:
        uv_logger = logging.getLogger(logger_name)
        for h in uv_logger.handlers[:]:
            uv_logger.removeHandler(h)
        uv_logger.addHandler(handler)
        uv_logger.propagate = False
