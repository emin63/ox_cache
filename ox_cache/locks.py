"""Module to collect alterantive locks which may be useful.
"""

import logging


class FakeLock:
    """Fake lock.

    The OxCacheBase is designed to be thread-safe and lock most operations
    using an internal lock. Sometimes, however, you may have one locking
    operation call another. For example, you may have `refresh` call `store`
    in which case you want `store` not to try to aquire the lock which
    `refresh` has already aquired. This FakeLock class accomplishes that.
    """

    def __init__(self, lock_name='unnamed'):
        self.lock_name = lock_name

    def __enter__(self):
        logging.debug('Faking lock entry for lock named "%s"', self.lock_name)
        return self

    def __exit__(self, *exc):
        logging.debug('Faking lock exit for lock named "%s", exc=%s',
                      self.lock_name, exc)
        return False
