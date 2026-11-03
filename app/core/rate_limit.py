from slowapi import Limiter
from app.dependencies import get_rate_limit_key

limiter = Limiter(key_func=get_rate_limit_key)