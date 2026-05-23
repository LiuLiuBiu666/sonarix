"""
core_shared/database.py
-----------------------
Khởi tạo và trả về Supabase client singleton.
Tất cả module đều import get_client() từ đây.
"""

import os
from functools import lru_cache

from dotenv import load_dotenv
from supabase import Client, create_client

from core_shared.logger import get_logger

load_dotenv()
logger = get_logger(__name__)

_SUPABASE_URL = os.getenv("SUPABASE_URL", "")
_SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")


@lru_cache(maxsize=1)
def get_client() -> Client:
    """
    Trả về Supabase Client dùng chung (singleton qua lru_cache).
    Dùng SERVICE_ROLE_KEY để có toàn quyền ghi/đọc server-side.

    Raises:
        EnvironmentError: Nếu biến môi trường chưa được cấu hình.
    """
    if not _SUPABASE_URL or not _SUPABASE_KEY:
        raise EnvironmentError(
            "Thiếu SUPABASE_URL hoặc SUPABASE_SERVICE_ROLE_KEY trong file .env"
        )
    client = create_client(_SUPABASE_URL, _SUPABASE_KEY)
    logger.info("Kết nối Supabase thành công.")
    return client
