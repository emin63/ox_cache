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


def _regr_test_cache():
    """Simple tests for basic cache.

>>> from ox_cache import OxCacheBase, TimedExpiryMixin
>>> class TimedCache(TimedExpiryMixin, OxCacheBase):
...     'Simple cache which expires items after after self.expiry_seconds.'
...     def make_value(self, key, **opts):
...         'Simple function to create value for requested key.'
...         print('Calling refresh for key="%s"' % key)
...         if opts:
...              print('opts were %s' % str(opts))
...         return 'key="%s" is fun!' % key
...
>>> cache = TimedCache(expiry_seconds=100) # expires after 100 seconds
>>> cache.get('test')  # Will call make_value to generate value.
Calling refresh for key="test"
'key="test" is fun!'
>>> cache.ttl('test') > 60  # Check time to live is pretty long
True
>>> cache.get('test')  # If called immediately, will use cached item
'key="test" is fun!'
>>> cache.expiry_seconds = 1     # Change expiration time to be much faster
>>> import time; time.sleep(1.1) # Wait a few seconds for cache item to expire
>>> cache.get('test')  # Will generate a new value since time limit expired
Calling refresh for key="test"
'key="test" is fun!'
>>> cache['test']
'key="test" is fun!'
>>> cache['test'] = 'blah'  # Manually store new value
>>> cache['test']
'blah'
>>> time.sleep(1.2)
>>> removed = cache.clean()
>>> len(removed)
1
>>> type(removed[0][0].odict())
<class 'dict'>
>>> cache.get('test', __not_keys=('tag',), tag='foo')
Calling refresh for key="test"
opts were {'__not_keys': ('tag',), 'tag': 'foo'}
'key="test" is fun!'
>>> cache.make_key('test', __not_keys=('tag',), tag='foo') #doctest: +ELLIPSIS
OxCacheFullKey(...)
    """

if __name__ == '__main__':
    doctest.testmod()
    print('Finished tests')
