"""Package for creating various kinds of data caches.

The ox_cache package provides tools to build your own simple caching
system. See docs on the following for details:

  - OxCacheBase:        Base class all caches inherit from.
  - TimedExpiryMixin:   Mix-in for time-based expiration of cache elements.
  - RefreshDictMixin:   Mix-in to refresh full cache from a dict.

The following illustrates how you can use these classes to create a
simple cache which refreshes itself either when a set amount of time
has passed or when a cache miss occurs.

>>> import logging, datetime, time
>>> from ox_cache import OxCacheBase, TimedExpiryMixin, RefreshDictMixin
>>> class MyCache(TimedExpiryMixin, RefreshDictMixin, OxCacheBase):
...     'Simple cache with time-based refresh via a function that gives dict'
...     def make_dict(self, key):
...         "Function to make dict to use to refresh cache."
...         logging.info('Refresh trigged for key=%s', key)
...         second = datetime.datetime.utcnow().second
...         return {k: str(k)+self.info for k in ([key] + list(range(10)))}
...
>>> cache = MyCache()
>>> cache.info = '5'
>>> cache.get(2) # will auto-refresh using make_dict
'25'
>>> cache.ttl(2) > 0
True
>>> cache.info = '6'
>>> cache.get(2) # cache has not been marked as stale so no refresh
'25'
>>> cache.expiry_seconds = 1  # make refresh time very short
>>> time.sleep(1.5)  # sleep so that cache becomes stale
>>> cache.ttl(2)
0
>>> cache.get(2)     # check cache to see that we auto-refresh
'26'
>>> cache.expiry_seconds = 1000  # slow down auto refresh for other examples
>>> cache.store(800, 5)
>>> cache.get(800)
5
>>> cache.store('800', 'a string')
>>> cache.get('800')
'a string'
>>> cache.delete(800)
>>> cache.get(800, allow_refresh=False) is None
True


>>> from ox_cache import TimedMemoizer
>>> @TimedMemoizer
... def my_func(x, y):
...     'Add two inputs together'
...     z = x + y
...     print('Adding %s to %s gives %s' % (x, y, z))
...     return z
...
>>> my_func(1, 2)  # Calling the first time will call the underlying function
Adding 1 to 2 gives 3
3
>>> my_func(1, 2)  # Now the function is cached so it is not actually called
3
>>> my_func.ttl(1, 2) > 0  # You can access TimedMemoizer methods like ttl
True
>>> my_func.expiry_seconds = 1    # make refresh time very short
>>> import time; time.sleep(1.5)  # sleep so that cache becomes stale
>>> my_func.exists(1, y=2)        # can check existsnce and kwargs works
True
>>> my_func.expired((1, 2))       # verify that cache is expired
True
>>> my_func(1, 2)                 # will call function again since expired
Adding 1 to 2 gives 3
3
"""


import logging

from ox_cache.core import (
    OxCacheBase, OxCacheFullKey, OxCacheItem)
from ox_cache.mixins import (
    RefreshDictMixin, TimedExpiryMixin, LRUReplacementMixin)
from ox_cache.memoizers import (
    OxMemoizer, TimedMemoizer, LRUReplacementMemoizer)

VERSION = '1.3.1'

if __name__ == '__main__':
    logging.info(
        'Imported various ox_cache classes:\n%s', '\n'.join([
            str(m) for m in [
                OxCacheBase, OxCacheFullKey, OxCacheItem,
                RefreshDictMixin, TimedExpiryMixin, LRUReplacementMixin,
                OxMemoizer, TimedMemoizer, LRUReplacementMemoizer]
            ] + ['Nothing gets done when running this module as main.']))
