import logging
import sys

from pythonjsonlogger import jsonlogger


def setup_logger(name: str = "trading", level: str = "INFO") -> logging.Logger:
    """Configures structured JSON logging for production observability."""
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = jsonlogger.JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(module)s %(message)s",
            timestamp=True
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.propagate = False
        
    return logger


logger = setup_logger()
