import logging
import sys
import json
from pathlib import Path
from models import Config

# 全局日志回调，用于图形界面
_gui_log_callback = None


def _configure_stdio_encoding():
    """尽量把标准输出切到 UTF-8，避免 Windows 控制台编码导致日志写出失败。"""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

def set_gui_log_callback(callback):
    """设置 GUI 日志回调函数"""
    global _gui_log_callback
    _gui_log_callback = callback
    
    # 给 root logger 加 handler
    root_logger = logging.getLogger()
    # 检查是否已有我们的 handler
    has_gui_handler = False
    for handler in root_logger.handlers:
        if hasattr(handler, '_is_gui_handler'):
            has_gui_handler = True
            break
    if not has_gui_handler:
        # 添加 GUI 回调 handler
        class GuiCallbackHandler(logging.Handler):
            _is_gui_handler = True
            def emit(self, record):
                if _gui_log_callback:
                    try:
                        _gui_log_callback(f"{record.getMessage()}", record.levelname.lower())
                    except Exception:
                        pass
        
        gui_handler = GuiCallbackHandler()
        root_logger.addHandler(gui_handler)


def setup_logger(name=None, level=logging.INFO, log_file=None):
    """设置统一的 logger

    Args:
        name: logger 名称，默认为 root logger
        level: 日志级别，默认为 INFO
        log_file: 可选的日志文件路径，如果提供则同时输出到文件

    Returns:
        配置好的 logger 对象
    """
    _configure_stdio_encoding()
    logger = logging.getLogger(name)
    
    # 避免重复添加 handler
    # 只检查 console 和 file handler，因为 GUI handler 可能被其他地方添加
    has_console_handler = False
    for handler in logger.handlers:
        if isinstance(handler, logging.StreamHandler) and not hasattr(handler, '_is_gui_handler'):
            has_console_handler = True

    if not has_console_handler:
        logger.setLevel(level)
        
        # 日志格式：时间 - 名称 - 级别 - 消息
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%H:%M:%S'
        )
        
        # 添加控制台输出 handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        # 如果指定了日志文件，添加文件输出 handler
        if log_file:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_path, encoding='utf-8')
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
    
    return logger


def get_logger(name):
    """获取 logger 的便捷函数

    Args:
        name: logger 名称

    Returns:
        已配置的 logger 对象
    """
    return logging.getLogger(name)


def load_config(config_path: Path = None) -> Config:
    """从 config.json 加载配置

    Args:
        config_path: 配置文件路径，默认为 config.json

    Returns:
        Config 对象
    """
    if config_path is None:
        config_path = Path("config.json")
    
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")
    
    try:
        return Config.model_validate_json(config_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger = get_logger(__name__)
        logger.error(f"加载配置文件失败，请修正 config.json: {e}")
        raise


def save_config(config: Config, config_path: Path = None):
    """保存配置到 config.json

    Args:
        config: Config 对象
        config_path: 配置文件路径，默认为 config.json
    """
    if config_path is None:
        config_path = Path("config.json")
    
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config.model_dump(), f, ensure_ascii=False, indent=2)
