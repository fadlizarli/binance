import logging, os
from datetime import datetime
from logging.handlers import RotatingFileHandler

def setup_logger(name="CryptoBot", log_dir="logs"):
    os.makedirs(log_dir, exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    if logger.handlers:
        return logger

    fmt = logging.Formatter("%(asctime)s [%(levelname)-8s] %(message)s", datefmt="%H:%M:%S")
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    ch.setLevel(logging.INFO)
    logger.addHandler(ch)

    today = datetime.now().strftime("%Y%m%d")
    fh = RotatingFileHandler(
        os.path.join(log_dir, f"cryptobot_{today}.log"),
        maxBytes=5*1024*1024, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)-8s] %(message)s"))
    fh.setLevel(logging.DEBUG)
    logger.addHandler(fh)
    return logger

def setup_trade_logger(log_dir=None):
    if log_dir is None:
        import os
        base    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        log_dir = os.path.join(base, "logs")
    os.makedirs(log_dir, exist_ok=True)
    tl = logging.getLogger("TradeLog")
    tl.setLevel(logging.INFO)
    if tl.handlers:
        return tl
    today = datetime.now().strftime("%Y%m%d")
    fh = RotatingFileHandler(
        os.path.join(log_dir, f"trades_{today}.log"),
        maxBytes=2*1024*1024, backupCount=5, encoding="utf-8"
    )
    fh.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
    tl.addHandler(fh)
    return tl

logger      = setup_logger()
trade_logger = setup_trade_logger()
