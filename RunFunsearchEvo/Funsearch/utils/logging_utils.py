"""Logging utilities for FunSearch experiments."""
import os
import logging
from datetime import datetime
from typing import Optional


def create_log_directory(base_dir: str = None) -> str:
    """
    Create a timestamped log directory.
    
    Args:
        base_dir: Base directory for logs. If None, uses Funsearch/Logs from project root
        
    Returns:
        Path to the created timestamped directory
    """
    if base_dir is None:
        # Get project root (auto-world-rules directory)
        this_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.abspath(os.path.join(this_dir, '..', '..'))
        base_dir = os.path.join(project_root, "Funsearch", "Logs")
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = os.path.join(base_dir, f"run_{timestamp}")
    os.makedirs(log_dir, exist_ok=True)
    return log_dir


def create_logger(name: str, log_file: str, level=logging.INFO) -> logging.Logger:
    """
    Create a logger that writes to a specific file.
    
    Args:
        name: Name of the logger
        log_file: Path to the log file
        level: Logging level
        
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Remove any existing handlers
    logger.handlers = []
    
    # Create file handler
    file_handler = logging.FileHandler(log_file, mode='w')
    file_handler.setLevel(level)
    
    # Create console handler (optional - comment out if you only want file logging)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    
    # Create formatter
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(message)s')
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # Add handlers to logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger


def setup_experiment_logging(log_dir: str, num_samplers: int, log_level: str = 'INFO') -> dict:
    """
    Set up logging for an entire experiment.
    
    Args:
        log_dir: Directory for log files
        num_samplers: Number of samplers to create loggers for
        log_level: Logging level as string ('DEBUG', 'INFO', 'WARNING', 'ERROR')
        
    Returns:
        Dictionary with 'main' logger and 'samplers' list of loggers
    """
    # Convert string log level to logging constant
    level = getattr(logging, log_level.upper(), logging.INFO)
    
    loggers = {}
    
    # Create main logger
    main_log_file = os.path.join(log_dir, "main-code.log")
    loggers['main'] = create_logger('main', main_log_file, level=level)
    
    # Create sampler loggers
    loggers['samplers'] = []
    for i in range(num_samplers):
        sampler_log_file = os.path.join(log_dir, f"sampler{i}.log")
        sampler_logger = create_logger(f'sampler{i}', sampler_log_file, level=level)
        loggers['samplers'].append(sampler_logger)
    
    return loggers
