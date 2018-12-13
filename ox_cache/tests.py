"""Provide various tests of core code.
"""

import logging
import doctest
import random

from ox_cache.mixins import TimedExpiryMixin
from ox_cache.memoizers import OxMemoizer
from ox_cache.locks import FakeLock


class RandomReplacementMixin:
    """Example mixin to do random replacement.
    """

    def __init__(self, *args, max_size=128, **kwargs):
        self.max_size = max_size
        super().__init__(*args, **kwargs)

    def _pre_store(self, key, value, ttl_info=None, **opts):
        dummy = key, value, ttl_info, opts
        while len(self._data) >= self.max_size:
            full_key_to_delete = random.choice(list(self._data))
            logging.debug('%s will remove key %s',
                          self.__class__.__name__, full_key_to_delete)
            self._delete_full_key(full_key_to_delete, lock=FakeLock())


class RandomReplacementMemoizer(
        RandomReplacementMixin, TimedExpiryMixin, OxMemoizer):
    """Memoizer class using time based refresh via RandomReplacementMixin

This is a class that can be used to memoize a function keeping
only `self.max_size` elements with random replacement. This is mainly
for demonstration or statistical purposes since randomly kicking
out an item is inefficient.

>>> from ox_cache.tests import RandomReplacementMemoizer
>>> @RandomReplacementMemoizer
... def my_func(x, y):
...     'Add two inputs'
...     z = x + y
...     print('called my_func(%s, %s) = %s' % (repr(x), repr(y), repr(z)))
...     return z
...
>>> my_func(1, 2)
called my_func(1, 2) = 3
3
>>> my_func.max_size = 3
>>> data = [my_func(1, i) for i in range(5)]  # doctest: +ELLIPSIS
called my_func(1, 0) = ...
called my_func(1, 1) = ...
called my_func(1, 3) = ...
called my_func(1, 4) = ...
>>> len(my_func)
3
    """

if __name__ == '__main__':
    doctest.testmod()
    print('Finished tests')

