"""Shared, bounded in-memory request budgets for the public deployment."""
from collections import deque
from contextlib import contextmanager
from math import ceil
from threading import Lock
from time import monotonic

from mfds_client import ServiceError


class RateLimitError(ServiceError):
    def __init__(self, reason, retry_after):
        self.retry_after = max(1, ceil(retry_after))
        super().__init__(f'{reason} {self.retry_after}초 뒤 다시 시도해 주세요. 기존 제품 목록은 유지됩니다.')


class PublicRequestLimits:
    """Budgets apply across visitors, not by spoofable forwarded IP headers.

    Counts admitted requests, including upstream failures. Restarts reset the
    process-local budget; this is not a provider-level spending cap.
    """
    def __init__(self, api_limit=120, api_window=60, photo_limit=20,
                 photo_window=600, max_active_photos=2, clock=monotonic):
        self.api_limit, self.api_window = api_limit, api_window
        self.photo_limit, self.photo_window = photo_limit, photo_window
        self.max_active_photos, self.clock = max_active_photos, clock
        self._api, self._photos = deque(), deque()
        self._active_photos = 0
        self._lock = Lock()

    def _admit(self, queue, limit, window, reason):
        now = self.clock()
        while queue and queue[0] <= now - window:
            queue.popleft()
        if len(queue) >= limit:
            raise RateLimitError(reason, queue[0] + window - now)
        queue.append(now)

    def api_request(self):
        with self._lock:
            self._admit(self._api, self.api_limit, self.api_window,
                        '사이트의 일시적인 요청 한도에 도달했습니다.')

    @contextmanager
    def analysis(self):
        with self._lock:
            if self._active_photos >= self.max_active_photos:
                raise RateLimitError('다른 사진을 분석 중입니다.', 5)
            self._admit(self._photos, self.photo_limit, self.photo_window,
                        '사이트의 사진 분석 한도에 도달했습니다.')
            self._active_photos += 1
        try:
            yield
        finally:
            with self._lock:
                self._active_photos -= 1
