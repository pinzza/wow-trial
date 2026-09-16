#!/usr/bin/env python3
"""统一配置入口：WCL API Key 与公共路径。

公开仓库不再硬编码任何凭证。所有调用方一律::

    from core.config import get_api_key

- 优先读取 ``WCL_API_KEY`` 环境变量；
- 缺失时抛出 ``RuntimeError`` 并提示获取方式，不再静默回退到内置 Key。
"""

from __future__ import annotations

import os
from pathlib import Path

WCL_API_KEY_ENV = "WCL_API_KEY"
WCL_V1_BASE = "https://www.warcraftlogs.com/v1"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
WCL_DB_DIR = DATA_DIR / "wcl_db"
CACHE_DIR = DATA_DIR / "cache"


def get_api_key() -> str:
    """获取 WCL V1 API Key，缺失时抛错（不提供默认值）。"""
    key = os.environ.get(WCL_API_KEY_ENV, "").strip()
    if not key:
        raise RuntimeError(
            f"缺少环境变量 {WCL_API_KEY_ENV}。"
            "请先在 https://www.warcraftlogs.com/api/clients 申请 V1 Key，"
            f"再 export {WCL_API_KEY_ENV}=<your-key> 后重试。"
            "公开仓库不会内置任何可用 Key。"
        )
    return key
