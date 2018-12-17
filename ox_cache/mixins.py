"""Mixin classes to change caching behaviour
"""

import logging
import datetime
import collections

from ox_cache.locks import FakeLock


class RefreshDictMixin:
    """Mixin for a cache which refreshes keys from a single `make_dict` method.

By inheriting from OxCacheBase along with RefreshDictMixin, you can define
a `make_dict` function which will be called on a cache miss to populate the
entire cache. This is useful for making a `batch cache` such as if you pull
data from an FTP site or external web site or file on disk. In those cases,
it is usually more efficient to populate the cache for a lot of keys at
once rather than just a single key each time.

The following shows example usage.

>>> from ox_cache import RefreshDictMixin, OxCacheBase
>>> class DictCache(RefreshDictMixin, OxCacheBase):
...     'Example cache which populates using a `make_dict` method.'
...     def make_dict(self, key, **opts):
...         "Function to make dict to use to refresh cache."
...         print('Refresh trigged for key=%s' % key)
...         return {k: str(k)+self.info for k in ([key] + list(range(10)))}
...
>>> cache = DictCache()
>>> cache.info = '5'
>>> cache.get(2)  # This call will trigger a refresh
Refresh trigged for key=2
'25'
>>> cache.get(4)  # The refresh already setup this key so no refresh occurs
'45'
>>> cache.get(50) # This call will trigger a refresh since not in original dict
Refresh trigged for key=50
'505'
"""

    def make_dict(self, key, **opts):
        """Make a dictionary of keys and values to store in the cache.

        :param key:     The base key which triggered the refresh request.
                        At an aboslute minimum the returned result *MUST*
                        contain this key.

        :param **opts:  Keyword options for how to determine full key.
                        See the make_key method for details on key/**opts.
                        Note these `opts` will be used for **ALL** the keys
                        returned by `self.make_dict`.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        :return:   A dictionary of keys and values.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        PURPOSE:   Provide a function which takes a key and returns a
                   dictionary of keys and values to store in the cache.
                   This returned dictionary **MUST** contain the `key`
                   argument which `make_dict` was called with and may
                   optionally contain more keys.
        """
        raise NotImplementedError

    def refresh(self, key, lock=None, **opts):
        """Refresh the cache by calling a make_dict method.

        :param key:     key for object which triggered the refresh request.

        :param lock=None:   Optional lock to use. If None, use self.lock.

        :param **opts:  Keyword options for how to determine full key.
                        See the make_key method for details on key/**opts.
                        Note these `opts` will be used for **ALL** the keys
                        returned by `self.make_dict`.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        PURPOSE:  This will call `self.make_dict(key, **opts)` to get the
                  refresh data while providing other conveniences such as
                  locking for thread safety, calling self.create_ttl to setup
                  time-to-live properly, calling self.store, etc.

        """
        logging.debug('Calling %s in %s', 'refresh', self.__class__.__name__)
        if lock is None:
            lock = self.lock
        with lock:
            my_dict = self.make_dict(key, **opts)
            assert key in my_dict, (
                'Base key "%s" not in result of make_dict!' % str(key))
            for base_key, value in my_dict.items():
                ttl_info = self.create_ttl(base_key, **opts)
                self.store(base_key, value, ttl_info,
                           lock=FakeLock(), **opts)


class TimedExpiryMixin:
    """Mixin which expires cache elements after a fixed time in seconds.

By creating your own class which inherits from both OxCacheBase
and TimedExpiryMixin, you can get timed expiration as illusrated below.
You can either provide the expiry_seconds keyword argument on __init__
or simply change self.expiry_seconds as desired.

>>> from ox_cache import OxCacheBase, TimedExpiryMixin
>>> class TimedCache(TimedExpiryMixin, OxCacheBase):
...     'Simple cache which expires items after after self.expiry_seconds.'
...     def make_value(self, key, **opts):
...         'Simple function to create value for requested key.'
...         print('Calling refresh for key="%s"' % key)
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
    """

    def __init__(self, *args, expiry_seconds=3600, **kwargs):
        """Initializer for TimedExpiryMixin.

        :param expiry_seconds=3600:  You can set this keyword argument to
                                     be how log you want keys to live.

        Otherwise *args, **kwargs are passed along to super().__init__.
        """
        self.expiry_seconds = expiry_seconds
        super().__init__(*args, **kwargs)

    def ttl_for_record(self, record):
        """Override to compute expiration as whether self.expiry_seconds passed

        :param record:     Instance of OxCacheItem to analyze.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        :return:  Time-to-live in seconds.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        PURPOSE:  Compute the time-to-live as how many seconds remain before
                  the record is past `self.expiry_seconds` old. This assumes
                  that `record.ttl_info` was generated by the default
                  `OxCacheBase.create_ttl` method.

        """
        now = datetime.datetime.utcnow()
        return max(0, self.expiry_seconds -
                   (now - record.ttl_info).total_seconds())


class LRUReplacementMixin:
    """Mixin to provide least-recently-used cache semantics.

By including the LRUReplacementMixin you can set your cache to have a
maximum size and evict least recently used elements when they size limit
is reached.

The following illustrates an example.

>>> from ox_cache import OxCacheBase, LRUReplacementMixin
>>> class LRUCache(LRUReplacementMixin, OxCacheBase):
...     'Simple cache which evicts least recently used items to save space.'
...     def make_value(self, key, **opts):
...         'Simple function to create value for requested key.'
...         print('Calling refresh for key="%s"' % key)
...         return 'key="%s" is fun!' % key
...
>>> cache = LRUCache(max_size=3)
>>> cache.get('test')  # Will call make_value to generate value.
Calling refresh for key="test"
'key="test" is fun!'
>>> cache.get('test')  # Will get element from cache.
'key="test" is fun!'
>>> data = [cache.get(x) for x in ['a', 'b', 'test', 'c']]
Calling refresh for key="a"
Calling refresh for key="b"
Calling refresh for key="c"
>>> cache.get('test')  # Will get element from cache since it was recent.
'key="test" is fun!'
>>> cache.get('a')  # Will have to refresh cache since 'a' was least recent.
Calling refresh for key="a"
'key="a" is fun!'
>>> cache.reset()   # We can reset the cache completely if
>>> len(cache)      # we want to just start over.
0
    """

    def __init__(self, *args, max_size=128, **kwargs):
        self.max_size = max_size
        super().__init__(*args, **kwargs)
        self._tracker = collections.OrderedDict()

    def _pre_get(self, key, allow_refresh, **opts):
        "Track get request to implement LRU semantics."
        dummy = allow_refresh
        full_key = self.make_key(key, **opts)
        if full_key in self._tracker:
            self._tracker.move_to_end(full_key)  # pylint: disable=no-member

    def _pre_delete_full_key(self, full_key):
        "Track delete request to implement LRU semantics."
        try:
            del self._tracker[full_key]
        except KeyError:
            pass

    def _post_reset(self):
        "Reset the tracker after the cache had self.reset() called."
        self._tracker = collections.OrderedDict()

    def _pre_store(self, key, value, ttl_info, **opts):
        dummy = value, ttl_info
        full_key_to_delete = self.make_key(key, **opts)
        while len(self._data) >= self.max_size:
            full_key_to_delete, dummy = self._tracker.popitem(last=False)
            logging.debug('%s will remove key %s',
                          self.__class__.__name__, full_key_to_delete)
            self._delete_full_key(full_key_to_delete, lock=FakeLock())

    def _post_store(self, key, value, ttl_info, **opts):
        dummy = value, ttl_info
        self._tracker[self.make_key(key, **opts)] = key
