import logging
import os
import colorlog
from config import config

os.makedirs(config.LOG_DIR, exist_ok=True)


def get_logger(name):
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    ch = logging.StreamHandler()
    ch.setFormatter(colorlog.ColoredFormatter(
        "%(log_color)s[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
        log_colors={
            'DEBUG': 'cyan', 'INFO': 'green', 'WARNING': 'yellow',
            'ERROR': 'red', 'CRITICAL': 'bold_red'
        }
    ))
    logger.addHandler(ch)
    fh = logging.FileHandler(f"{config.LOG_DIR}/bot.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
    ))
    logger.addHandler(fh)
    return logger
