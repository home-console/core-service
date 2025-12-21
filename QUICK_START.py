"""
QUICK START: Using new utilities in admin_app.py

This shows how to start using the new utilities RIGHT NOW 
without breaking existing code.
"""

# ============= OLD CODE (в admin_app.py) =============
# def _http_json(...):  # 50+ строк кода
#     ...
# 
# data = await asyncio.to_thread(_http_json, "GET", "/api/clients")


# ============= NEW CODE (использует utils) =============
from utils.http_client import _http_json  # Переиспользуем утилиту!

data = await asyncio.to_thread(_http_json, "GET", "/api/clients")


# ============= Пример: JWT аутентификация =============

# OLD: 50+ строк дублированного кода в нескольких местах
# def generate_jwt():
#     admin_jwt_secret = os.getenv('ADMIN_JWT_SECRET', '')
#     if admin_jwt_secret:
#         alg = os.getenv('ADMIN_JWT_ALG', 'HS256').upper()
#         # ... еще 40 строк ...

# NEW: одна строка!
from utils.auth import generate_jwt_token, get_admin_headers

token = generate_jwt_token(subject='install:agent-123')
headers = get_admin_headers()  # Автоматически выбирает JWT или ADMIN_TOKEN


# ============= Пример: новый endpoint =============

# Вместо того чтобы добавлять в огромный admin_app.py,
# создайте новый файл routes/my_feature.py:

from fastapi import APIRouter
from utils.http_client import _http_json

router = APIRouter(prefix="/my-feature", tags=["my-feature"])

@router.get("/data")
async def get_data():
    data = await asyncio.to_thread(_http_json, "GET", "/api/something")
    return data

# И подключите его в app.py:
# app.include_router(my_feature.router, prefix="/api")


# ============= Преимущества =============
# ✅ Меньше дублирования кода
# ✅ Легче тестировать
# ✅ Проще понимать и поддерживать
# ✅ Можно начать использовать СЕГОДНЯ
# ✅ Не ломает существующий код
