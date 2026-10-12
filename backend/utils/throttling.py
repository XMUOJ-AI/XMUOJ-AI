import math


class TokenBucket:
    # Redis runs the refill and debit together, across all web/worker processes.
    SCRIPT = """
        local now_parts = redis.call('TIME')
        local now = tonumber(now_parts[1]) + tonumber(now_parts[2]) / 1000000
        local state = redis.call('HMGET', KEYS[1], 'last_capacity', 'last_timestamp')
        local capacity = tonumber(ARGV[1])
        local rate = tonumber(ARGV[2])
        local available = tonumber(state[1]) or tonumber(ARGV[3])
        local last = tonumber(state[2]) or now
        available = math.min(capacity, available + math.max(0, now - last) * rate)
        local allowed = 0
        local wait = 0
        if available >= tonumber(ARGV[4]) then
            available = available - tonumber(ARGV[4])
            allowed = 1
        else
            wait = (tonumber(ARGV[4]) - available) / rate
        end
        redis.call('HSET', KEYS[1], 'last_capacity', available, 'last_timestamp', now)
        redis.call('EXPIRE', KEYS[1], ARGV[5])
        return {allowed, tostring(wait)}
    """

    def __init__(self, key, capacity, fill_rate, default_capacity, redis_conn):
        if capacity <= 0 or fill_rate <= 0 or not 0 <= default_capacity <= capacity:
            raise ValueError("Invalid token bucket configuration")
        self._key = key
        self._capacity = capacity
        self._fill_rate = fill_rate
        self._default_capacity = default_capacity
        self._redis_conn = redis_conn

    def consume(self, num=1):
        if not 0 < num <= self._capacity:
            raise ValueError("Invalid token count")
        result = self._redis_conn.eval(
            self.SCRIPT, 1, self._key, self._capacity, self._fill_rate,
            self._default_capacity, num, math.ceil(self._capacity / self._fill_rate) + 60)
        return bool(result[0]), float(result[1])
