# -*- coding: utf-8 -*-
"""Đếm câu SQL trong phạm vi hẹp — dùng chung test B01a / B02 / B09.

Chỉ bọc ``cr.execute`` giữa ``__enter__`` / ``__exit__``. Không đếm seed,
tạo công ty, hay khởi tạo phiên bên ngoài khối ``with``.
"""


class VasQueryCounter:
    """Context manager: ``with VasQueryCounter(env.cr) as qc: ...; qc.count``."""

    def __init__(self, cr):
        self.cr = cr
        self._real = None
        self.count = 0

    def __enter__(self):
        self.count = 0
        self._real = self.cr.execute

        def wrapped(query, params=None, log_exceptions=True):
            self.count += 1
            return self._real(query, params=params, log_exceptions=log_exceptions)

        self.cr.execute = wrapped
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._real is not None:
            self.cr.execute = self._real
            self._real = None
        return False
