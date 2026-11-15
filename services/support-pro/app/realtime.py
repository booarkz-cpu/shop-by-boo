import json
import logging
import os
import redis.asyncio as redis

from urllib.parse import urlsplit, unquote
redis_url = os.getenv('REDIS_URL', 'redis://redis:6379/0')
redis_password = os.getenv('REDIS_PASSWORD', '')
embedded_password = unquote(urlsplit(redis_url).password or '')
if redis_password and embedded_password and redis_password != embedded_password:
    raise ValueError('REDIS_PASSWORD conflicts with REDIS_URL password')
r = redis.from_url(redis_url, decode_responses=True, **({'password': redis_password} if redis_password and not embedded_password else {}))


async def publish(tid, payload):
    try:
        await r.publish(f'ticket:{tid}', json.dumps(payload, ensure_ascii=False))
    except Exception:
        logging.getLogger(__name__).warning('Realtime unavailable; committed changes remain in database')
