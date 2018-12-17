"""Module to collect alterantive locks which may be useful.
"""

from logging import getLogger  # Use LOGGER and no other logging things in here
import doctest
import threading

LOGGER = getLogger(__name__)


class TimeoutLock:
    """Custom version of threading.Lock with auto-timeout.

The TimeoutLock is a custom version of threading.Lock which will autoamtically
timeout and raise an Exception if it cannot acquire a lock. This is helpful
since if you are waiting on a lock for a long time, probably it is a deadlock
and you want to be informed.

The following illustrates example usage:

>>> from ox_cache import locks
>>> lock = locks.TimeoutLock(timeout=2)
>>> try:
...     with lock:
...         print('this should get printed fine')
...         with lock:
...             print('this should cause a timeout')
... except Exception as problem:
...     print('got problem: %s' % str(problem))
...
this should get printed fine
got problem: Unable to get lock after timeout of 2
>>> with lock:
...     print('Can reuse lock after it is released')
...
Can reuse lock after it is released

    """

    def __init__(self, timeout=300, lock=threading.Lock):
        self.timeout = timeout
        self.lock = lock()

    def __enter__(self):
        LOGGER.debug('Entering TimeoutLock for ox_cache')
        got_lock = self.lock.acquire(timeout=self.timeout)
        if got_lock:
            return self.lock
        raise Exception('Unable to get lock after timeout of %s' % (
            self.timeout))

    def __exit__(self, *exc):
        self.lock.release()
        LOGGER.debug('Released TimeoutLock for ox_cache')


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
        LOGGER.debug('Faking lock entry for lock named "%s"', self.lock_name)
        return self

    def __exit__(self, *exc):
        LOGGER.debug('Faking lock exit for lock named "%s", exc=%s',
                     self.lock_name, exc)
        return False


if __name__ == '__main__':
    doctest.testmod()
    print('Finished Tests')
