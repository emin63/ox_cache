"""Core implementation of ox_cache
"""

import inspect
import doctest
import functools
import logging
import datetime
import threading
import collections


OxCacheItem = collections.namedtuple('OxCacheItem', [
    'payload', 'ttl_info'])
OxCacheItem.__doc__ = '''Cache entry item.

The OxCacheItem represents an item in the cache. It has the following
fields:

  - payload:      The raw data for the cached item.
  - ttl_info:     Information used to determine the time to live for this
                  cache item. See the OxCacheBase.expired doc for details.
'''


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


class OxCacheBase:
    """Base class for caches.

This serve as the base class providing most of the caching functionality
such as locking, checking expiration, and so on. Some of the functions
you may wish to override include:

  - make_value:      Make a value for a requested key not in the cache.
  - ttl_for_record:  Determine time to live for a given cache record.
  - create_ttl:      Create initial time-to-live for record when created.

In order to create a cache, the bare the minimum you need to do is to
override the `make_value` method as illustrated below.

>>> from ox_cache import OxCacheBase
>>> class NeverExipiringCache(OxCacheBase):
...     'Simple cache which never expires'
...     def make_value(self, key, **opts):
...         'Simple function to create value for requested key.'
...         print('Calling refresh for key="%s"' % key)
...         return 'key="%s" is fun!' % key
...
>>> cache = NeverExipiringCache()
>>> cache.get('test')  # Will refresh the cache for this key and return value
Calling refresh for key="test"
'key="test" is fun!'
>>> cache.get('test')  # Will return cached value since already in cache
'key="test" is fun!'
>>> cache.get('foo')   # Will refresh the cache for this key and return value
Calling refresh for key="foo"
'key="foo" is fun!'
>>> cache.delete('test') # Delete item from cache
>>> cache.get('test')  # Will refresh the cache since we deleted this key
Calling refresh for key="test"
'key="test" is fun!'

You can determine things like how keys are expired or removed either by
overriding methods such as ttl_for_record and create_ttl or by using some
of the mixins provided. See `help(ox_cache)` for `print(ox_cache.__doc__)`
for a more detailed discussion.
    """

    def __init__(self, make_lock=threading.Lock):
        self.lock = make_lock()
        self._data = self.make_storage()

    def __len__(self):
        return len(self._data)

    def make_storage(self):
        """Make dict-like storage to store data in.

        Sub-classes can override to return some other dict-like
        structure (e.g., to store to disk or something).
        """
        dummy = self
        return {}

    def make_key(self, base_key, namespace='default', **opts):
        """Make a full key to use in referencing something in the cache.

        :param base_key:     Hashable key for object to refresh. This can
                             be basically anything with a stable __repr__
                             method.

        :param namespace='default':   Optional namespace in case you want
                                      to further distinguish the same keys
                                      using a different namespace.

        :param **opts:  Keyword options which may or may not be part of the
                        key depending on the particular implementation.
                        In the simplest use cases, you can just ignore this.
                        One reason for its existence is to allow sub-classes
                        to customize things as well as implement namespaces
                        anod other things in a convenient way. For example,
                        mention other functions will just call something
                        like `make_key(base_key, **opts)` and allow the
                        **opts to carry the namespace.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        :return:   A string representing the composite key combining the
                   base_key, namespace, and other things in **opts.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        PURPOSE:   Create a string key for an object.

        """
        dummy = self
        full_key = None
        full_key = '/'.join(['namespace:%s' % namespace] + [
            '%s:%s' % (k, opts[k]) for k in sorted(opts)] + [repr(base_key)])

        if full_key is None:
            raise ValueError('Cannot make compose key from %s and %s' % (
                base_key, opts))
        return full_key

    def make_value(self, key, **opts):
        """Make the data value corresponding to the given key/opts.

        :param key:     Hashable key for object to make value for.

        :param **opts:  Keyword options for how to make the value.
                        See the make_key method for details on key/**opts.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        PURPOSE:  Make the value corresponding to the given key/opts.
                  This will be called when the user calls self.get for a
                  key/opts which is not in the cache.

                  Sub-classes must implement.

                  This is one of the core methods which determines how
                  the cache works.
        """
        raise NotImplementedError

    def refresh(self, key, lock=None, **opts):
        """Refresh the cache for key (or maybe for everything).

        :param key:     Hashable key for object to refresh.

        :param lock=None:   Optional lock to use. If None, use self.lock.

        :param **opts:  Keyword options for how to do the refresh.
                        See the make_key method for details on key/**opts.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        PURPOSE:  Refresh self._data either for this key or perhaps
                  for everything. This calls `self.make_value` which is
                  generally what sub-classes will want to overide. The
                  `refresh` method calls `make_value` and also handles
                  things like locking for thread-saftey, calling create_ttl,
                  calling, self.store, and so on.
        """
        logging.debug('Refresh key/opts=%s/%s in %s', key, opts,
                      self.__class__.__name__)
        if lock is None:
            lock = self.lock
        with lock:
            my_value = self.make_value(key, **opts)
            ttl_info = self.create_ttl(key, **opts)
            self.store(key, my_value, ttl_info, lock=FakeLock(), **opts)

    def ttl(self, key, lock=None, **opts):
        """Return time-to-live for given key/**opts.

        :param key:     Hashable key for object to refresh.

        :param lock=None:   Optional lock to use. If None, use self.lock.

        :param **opts:  Keyword options for how to do the refresh.
                        See the make_key method for details on key/**opts.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        :return:  A float value representing the estimated time-to-live for
                  the given key.

                  By default the time-to-live is an estimate in
                  seconds. It is an estimate since some cache expiry methods
                  may be more complicated and not have an exact ttl. Also,
                  some cache expiration methods may be based on size and not
                  time in which case the ttl may be a measure of how close
                  to being kicked out the item is. In any case, a ttl
                  of 0 indicates the item is expired.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        PURPOSE:  Provide a way to get the time-to-live for an item. This
                  is the main function a user will call. Sub-classes should
                  generally override the lower level `self.ttl_for_record`
                  instead of this.
        """
        full_key = self.make_key(key, **opts)
        record = self.get_record(full_key, lock=lock)
        return self.ttl_for_record(record)

    def ttl_for_record(self, record):
        """Determine the time to live for a given cache record.

        :param record:     Instance of OxCacheItem to analyze.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        :return:   The time to live value representing an estimate
                   in seconds for how long this record has before it
                   will be considred expired. A result of 0 indicates
                   the record is expired.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        PURPOSE:   This is one of the key methods which determines how
                   the cache system works. Sub-classes must override
                   this to determine how the cache works.

                   By default, this method returns 1000000 indicating it
                   is a long time before it expires. Sub-classes should
                   either override or include a mixin to control expiration.

                   For example, see the TimedExpiryMixin class for an example
                   where we implement this as basically

           return max(0, self.expiry_seconds - (
               datetime.datetime.utcnow() - record.ttl_info).total_seconds())

                   to compute expiration as whether self.expiry_seconds have
                   passed since the record was created.


        SEE ALSO:  `create_ttl`.

        """
        dummy = self, record
        return 1000000

    def create_ttl(self, key, **opts):
        """Create initial time-to-live information for given key and opts.

        :param key:     Hashable key for object to get ttl info for.

        :param **opts:  Keyword options for how to do the key lookup.
                        See the make_key method for details on key/**opts.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        :return:  The ttl_info object for the record with the given
                  key/**opts.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        PURPOSE:  Create time to live related information By default,
                  this method simply returns datetime.datetime.utcnow()
                  to represent when the item was added to the cache.
                  Sub-classes can use the returned value as they see fit
                  or override this method.
        """
        dummy = self, key, opts
        return datetime.datetime.utcnow()

    def expired(self, key, lock=None, **opts):
        """Determine if the given key/**opts is expired.

        :param key:     Hashable key for object to check expiration for.

        :param lock=None:   Optional lock to use. If None, use self.lock.

        :param **opts:  Keyword options for how to do the key lookup.
                        See the make_key method for details on key/**opts.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        :return:  Whether the given key/**opts is expired. If the item
                  is not in the cache at all, we return false.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        PURPOSE:  Check if something in the cache is expired.

        """
        full_key = self.make_key(key, **opts)
        record = self.get_record(full_key, lock=lock)
        if not record:
            return True
        return self.is_record_expired(record)

    def is_record_expired(self, record):
        """Check if a given record is expired.

        :param record:     Instance of OxCacheItem to analyze.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        :return:  Whether the record is expired.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        PURPOSE:  Mainly meant as a helper function to be called by
                  self.expired. By default just checks if time to live
                  is zero in which case it is considered expired.

        """
        return self.ttl_for_record(record) == 0

    def store(self, key, value, ttl_info=None, lock=None, **opts):
        """Store a value for the given key.

        :param key:     Hashable key for object to store.

        :param value:   Value to store.

        :param ttl_info=None:    Time-to-live information. The form of
                                 this depends on how ttl_for_record is
                                 implemented by a sub-class or mix-in.

        :param lock=None:   Optional lock to use. If None, use self.lock.

        :param **opts:  Keyword options for how to determine full key.
                        See the make_key method for details on key/**opts.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        PURPOSE:  Store a value for the given key.

        """
        if lock is None:
            lock = self.lock
        with lock:
            if ttl_info is None:
                ttl_info = self.create_ttl(key, **opts)
            full_key = self.make_key(key, **opts)
            self._data[full_key] = OxCacheItem(value, ttl_info)

    def delete(self, key, lock=None, **opts):
        """Store a value for the given key.

        :param key:     Hashable key for object to delete.

        :param lock=None:   Optional lock to use. If None, use self.lock.

        :param **opts:  Keyword options for how to determine full key.
                        See the make_key method for details on key/**opts.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        PURPOSE:  Delete the given key. Raise KeyError if no such key
                  exists.

        """
        full_key = self.make_key(key, **opts)
        return self._delete_full_key(full_key, lock=lock)

    def _delete_full_key(self, full_key, lock=None):
        """Helper method to delete an item based on the full key.

        :param full_key:     Full key for the item to delete.

        :param lock=None:   Optional lock to use. If None, use self.lock.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        PURPOSE:   This is a helper method to be called by the delete
                   method or by sub-classes to actually delete data
                   from the data store. If sub-classes want to track
                   keys (e.g., to implement LRU caching), this also
                   serves as a good method to override to do something
                   before or after deletes.
        """
        if lock is None:
            lock = self.lock
        with lock:
            del self._data[full_key]

    def exists(self, key, lock=None, **opts):
        """Check if the given key is in our store.

        :param key:     Hashable key for object to check.

        :param lock=None:   Optional lock to use. If None, use self.lock.

        :param **opts:  Keyword options for how to determine full key.
                        See the make_key method for details on key/**opts.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        PURPOSE:  Return True/False if the key exists or not.

        """
        full_key = self.make_key(key, **opts)
        return self.get_record(full_key, lock=lock) is not None

    def get_record(self, full_key, lock=None):
        """Helper method to get internal OxCacheItem record for key.

        :param full_key:     Full key for the item to lookup.

        :param lock=None:   Optional lock to use. If None, use self.lock.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        PURPOSE:   This is a helper method to be called to get the
                   OxCacheItem for a record (e.g., to determine time-to-live).
                   Users should call `get` not this.
        """
        if lock is None:
            lock = self.lock
        with lock:
            record = self._data.get(full_key, None)
            return record

    def get(self, key, allow_refresh=True, lock=None, default=None, **opts):
        """Get the value for the given key if it exists (or possibly refresh).

        :param key:     key for object to check.

        :param allow_refresh=True:   Whether to allow refreshing or creating
                                     the value for the key if it is either
                                     expired or non-existent.

        :param lock=None:   Optional lock to use. If None, use self.lock.

        :param default=None:   Default value to return if allow_refresh is
                               False and there is no value to return. Usually
                               this is None, but you can set it to something
                               else if you want to distinguish between no
                               value for the key and a key which can have
                               a None value.

        :param **opts:  Keyword options for how to determine full key.
                        See the make_key method for details on key/**opts.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        :return:  Value for the given key or default if not found.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        PURPOSE:  Get the value for a key.

        """
        if lock is None:
            lock = self.lock
        with lock:
            base_key = key
            key = self.make_key(base_key, **opts)
            record = self._data.get(key, None)
            if record is None:     # Do not know anything about requested key
                if allow_refresh:  # If allowed, do a refresh
                    self.refresh(base_key, lock=FakeLock(), **opts)
                    return self.get(base_key, allow_refresh=False,
                                    lock=FakeLock(), **opts)
                return default
            # record was found but may be expired so must check that
            if self.is_record_expired(record):
                if allow_refresh:
                    self.refresh(base_key, lock=FakeLock(), **opts)
                    return self.get(base_key, allow_refresh=False,
                                    lock=FakeLock(), **opts)
                return default

            # Found a non-expired record so return payload
            return record.payload


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

    def __init__(self, *args, max_size=128, **kwargs):
        self.max_size = max_size
        super().__init__(*args, **kwargs)
        self._tracker = collections.OrderedDict()

    def get(self, key, allow_refresh=True, lock=None, default=None, **opts):
        if lock is None:
            lock = self.lock
        with lock:
            full_key = self.make_key(key, **opts)
            if full_key in self._tracker:            # if key already in self
                self._tracker.move_to_end(full_key)  # mark as recently used
            return super().get(key, allow_refresh=allow_refresh,
                               lock=FakeLock(), default=default, **opts)

    def _delete_full_key(self, full_key, lock=None):
        if lock is None:
            lock = self.lock
        with lock:
            try:
                del self._tracker[full_key]
            except KeyError:
                pass
            return super()._delete_full_key(full_key, lock=FakeLock())

    def store(self, key, value, ttl_info=None, lock=None, **opts):
        if lock is None:
            lock = self.lock
        with lock:
            while len(self._data) >= self.max_size:
                full_key_to_delete, dummy = self._tracker.popitem(last=False)
                logging.debug('%s will remove key %s',
                              self.__class__.__name__, full_key_to_delete)
                self._delete_full_key(full_key_to_delete, lock=FakeLock())
            result = super().store(key, value, ttl_info, lock=FakeLock(),
                                   **opts)
            self._tracker[self.make_key(key, **opts)] = key
            return result




class MemoizerMixin(OxCacheBase):
    """FIXME
    """# FIXME

    def __init__(self, func, *args, **kwargs):
        self.func = func
        self.argspec = inspect.getargspec(func)
        super().__init__(*args, **kwargs)
        self._fix_wrapper()

    def _fix_wrapper(self):
        orig_doc, orig_mod = self.__doc__, self.__module__
        functools.update_wrapper(self, self.func)
        self.__doc__ = '\n'.join([
            'memoized: ' + self.func.__doc__, '', '---\n',
            'Memoized by %s:' % self.__class__.__name__, orig_doc])
        self.__module__ = orig_mod
        for name in ['ttl', 'expired', 'delete', 'exists']:
            orig_func = getattr(self, name)
            raw_name = 'raw_%s' % name
            setattr(self, raw_name, orig_func)
            decorated = self._make_dec(orig_func, name, raw_name)
            setattr(self, name, decorated)

    def _make_dec(self, func, name, raw_name):
        @functools.wraps(func)
        def decorated(*args, **kwargs):
            key, opts = self.input_to_key_opts(*args, **kwargs)
            return func(key, **opts)
        decorated.__doc__ = '\n'.join([
            '', 'NOTE: wrapped to translate calling %(name)s(*args, **kw)',
            'to first get key, opts = self.input_to_key_opts(*args, **kw)',
            'and then call self.%(raw_name)s(key, **opts).', ''
            'Call self.%(raw_name)s for raw version described below.',
            '', '---']) % {'name': name, 'raw_name': raw_name} + (
                func.__doc__ if func.__doc__ else '(no docs for %s)' % (
                    raw_name))
        return decorated

    def refresh(self, key, lock=None, **opts):
        result = self.func(**opts)
        self.store(key, result, lock=lock, **opts)

    def input_to_key_opts(self, *args, **kwargs):
        key = self.func.__name__
        opts = dict(kwargs)
        for num, value in enumerate(args):
            name = self.argspec.args[num]
            opts[name] = value
        return key, opts

    def __call__(self, *args, **kwargs):
        key, opts = self.input_to_key_opts(*args, **kwargs)
        return self.get(key, **opts)


class TimedMemoizer(TimedExpiryMixin, MemoizerMixin):
    """Memoizer class using time based refresh via TimedExpiryMixin.

    This is a class that can be used to memoize a function via something
    like

>>> from ox_cache.core import TimedMemoizer
>>> @TimedMemoizer
... def my_func(x, y):
...     'Add two inputs'
...     z = x + y
...     print('called my_func(%s, %s) = %s' % (repr(x), repr(y), repr(z)))
...     return z
...
>>> my_func(1, 2)
called my_func(1, 2) = 3
3
>>> my_func(1, 2)   # does not print to stdout since memoized
3
>>> my_func(1, y=2) # handles keyword args correctly
3
>>> my_func.ttl(1, y=2) > 0  # can call things like ttl even with kw args
True
>>> my_func.expired(1, 2)    # can check if expired
False
>>> my_func.exists(1, 2)     # can check if exists (True even if expired)
True
>>> my_func.delete(1, 2)     # can delete
>>> my_func.exists(1, 2)
False
>>> my_func(1, 2)
called my_func(1, 2) = 3
3
>>> print(my_func.func.__doc__.strip())  # Get the docs for decorated func.
Add two inputs
>>> note = 'Full docstring includes above and mentions memoizer.'
>>> print(my_func.__doc__.strip()) # doctest: +ELLIPSIS +NORMALIZE_WHITESPACE
memoized: Add two inputs
<BLANKLINE>
---
Memoized by TimedMemoizer...

    """


class LRUReplacementMemoizer(
        LRUReplacementMixin, TimedExpiryMixin, MemoizerMixin):
    """Memoizer class using time based refresh via LRUReplacementMixin

This is a class that can be used to memoize a function keeping
only `self.max_size` elements with least recently used items being replaced.

>>> from ox_cache.core import LRUReplacementMemoizer
>>> @LRUReplacementMemoizer
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
>>> data = [my_func(1, i) for i in range(4)]
called my_func(1, 0) = 1
called my_func(1, 1) = 2
called my_func(1, 3) = 4
>>> len(my_func), my_func.exists(1, 0)  # Verify least recet item kicked out
(3, False)
>>> my_func.delete(1, 2)  # Delete an item and add some more
>>> data = [my_func(2, i) for i in range(2)]
called my_func(2, 0) = 2
called my_func(2, 1) = 3
>>> my_func.exists(1, 1)  # Verify that least recent item kicked out
False
    """


if __name__ == '__main__':
    doctest.testmod()
    print('Finished Tests')
