"""Core implementation of ox_cache
"""


import doctest
import logging
import datetime
import collections

from ox_cache.locks import FakeLock, TimeoutLock


class OxCacheFullKey(collections.namedtuple('OxCacheFullKey', [
        'namespace', 'base_key', 'opts'])):
    '''Repersentation for the full key in a cache.

The OxCacheFullKey class is a namedtuple to represent a cache key with
the following components:

  - namespace:  The namespace the key lives in.
  - base_key:   The `key` value provided in something like `store` or `get`.
  - opts:       A list of pairs representing the **opts provided to something
                like `store` or `get`.

We use a compose key like this since sometimes it useful to distinguish
the base key from the opts and have both readily available.

While the value of having a namespace in the cache as separate from the key
may be straightforward, you might wonder why we need the opts. Roughly
speaking, these make our implemetnation much more flexible for sub-classes.
For example, they allow a relatively simple implementation of function
memoization as with the OxMemoizer or TimedMemoizer classes.
    '''

    def odict(self):
        """Return a dict representing the **opts for the key.

        You can do something like cache.get(self.base_key, **self.odict()) to
        explicitly call OxCacheBase methods with the base key and opts
        where the key came from if you like.

        Note that generally you can just pass an instance of OxCacheFullKey
        to most OxCacheBase methods and they will recognize how to parse
        the pieces of the key.
        """
        return dict(self.opts, namespace=self.namespace)


OxCacheItem = collections.namedtuple('OxCacheItem', [
    'payload', 'ttl_info'])
OxCacheItem.__doc__ = '''Cache entry item.

The OxCacheItem represents an item in the cache. It has the following
fields:

  - payload:      The raw data for the cached item.
  - ttl_info:     Information used to determine the time to live for this
                  cache item. See the OxCacheBase.expired doc for details.
'''


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
...         return 'key="%s" made' % key
...
>>> cache = NeverExipiringCache()
>>> cache.get('test')  # Will refresh the cache for this key and return value
Calling refresh for key="test"
'key="test" made'
>>> cache.get('test')  # Will return cached value since already in cache
'key="test" made'
>>> cache.get('foo')   # Will refresh the cache for this key and return value
Calling refresh for key="foo"
'key="foo" made'

We can also use many of the familiar built-in features of dicts likes
len, __iter__, in, del, items, and so on. One minor issue is that the cache
keys are OxCacheFullKey instances which are combinations of the key and
the **opts provided. You can still index the cache using OxCacheFullKey
instances but you can also display just the base key if you like as shown
below.

>>> for fkey in sorted(cache): # Can iterate over cache items
...     print('%s: %s' % (fkey.base_key, cache[fkey])) # note [] instead of get
...
foo: key="foo" made
test: key="test" made
>>> cache.delete('test') # Delete item from cache
>>> len(cache), len(list(cache.items()))  # len and items also work
(1, 1)
>>> cache.get('test')  # Will refresh the cache since we deleted this key
Calling refresh for key="test"
'key="test" made'
>>> del cache["test"]
>>> 'test' in cache, 'foo' in cache  # You can use the in operator for exists
(False, True)

You can determine things like how keys are expired or removed either by
overriding methods such as ttl_for_record and create_ttl or by using some
of the mixins provided. See `help(ox_cache)` for `print(ox_cache.__doc__)`
for a more detailed discussion.
    """

    def __init__(self, lock=None):
        """Initializer.

        :param lock=None:  Context manager for locking. If this is None,
                           we use TimeoutLock(). If you want a different
                           timeout provide TimeoutLock(your_timeout).
        """
        self.lock = lock if lock is not None else TimeoutLock()
        self._data = self.make_storage()

    def __contains__(self, key):
        return self.exists(key)

    def __len__(self):
        return len(self._data)

    def __iter__(self):
        return self._data.__iter__()

    def __delitem__(self, key):
        return self.delete(key)

    def __getitem__(self, key):
        return self.get(key)

    def __setitem__(self, key, value):
        return self.store(key, value)

    def items(self):
        """Return a list of pairs representing keys and records in the cache.

        The result will be a sequence of (KEY, VALUE) pairs where the
        KEY elements are instances of OxCacheFullKey and the VALUE
        elements are instances of OxCacheItem. See docs for those for
        details or see main class help/__doc__ for an example usage.
        """
        return self._data.items()

    def make_storage(self):
        """Make dict-like storage to store data in.

        Sub-classes can override to return some other dict-like
        structure (e.g., to store to disk or something).
        """
        dummy = self
        return {}

    def make_key(self, base_key, namespace='default', __not_keys=(),
                 **opts):
        """Make a full key to use in referencing something in the cache.

        :param base_key:     Hashable key for object to refresh. If this is
                             an instance of OxCacheFullKey and opts is empty,
                             then base_key will be used as the full key.
                             Otherwise, we will create an instance of
                             OxCacheFullKey by combing the base_key with
                             the namespace and the **opts.

        :param namespace='default':   Optional namespace in case you want
                                      to further distinguish the same keys
                                      using a different namespace.

        :param __not_keys=():  Optional sequence of strings which are in
                               opts.keys() but should be ignored by make_key.
                               This can be useful if your make_value method
                               needs some arguments from **opts that you want
                               to use in creating the value but you do not
                               want that part of the key.

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
        if isinstance(base_key, OxCacheFullKey) and not opts:
            full_key = base_key
        else:
            if __not_keys:
                opts = {k: v for k, v in opts.items() if k not in __not_keys}
            full_key = OxCacheFullKey(namespace, base_key, tuple(
                (k, opts[k]) for k in sorted(opts)))

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

    def _pre_get(self, key, allow_refresh, **opts):
        """Hook called right after `self.get` enters its lock.

        :param key, allow_refresh, **opts:  As received by `self.get` method.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        PURPOSE:  This is a hook that the `get` method shall execute
                  right after it locks things.
                  Having a hook into `get` makes it easier to implement
                  things like an LRU caching mechanism. See the
                  LRUReplacementMixin for example usage.
        """
        dummy = self, key, allow_refresh, opts

    def _pre_store(self, key, value, ttl_info, **opts):
        """Hook called right after `store` enters lock and computes ttl_info.

        :param key, value:  As provided to store method.

        :param ttl_info:    The `ttl_info` computed by `store`.

        :param **opts:      As provided to store method.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        PURPOSE:  This is a hook that the `store` method shall execute
                  right after it locks things and computes `ttl_info`.
                  Having a hook into `store` makes it easier to implement
                  things like an LRU caching mechanism. See the
                  LRUReplacementMixin for example usage.
        """
        dummy = self, key, value, ttl_info, opts

    def _post_store(self, key, value, ttl_info, **opts):
        """Hook called right before `store` exits lock.

        :param key, value:  As provided to store method.

        :param ttl_info:    The `ttl_info` computed by `store`.

        :param **opts:      As provided to store method.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        PURPOSE:  This is a hook that the `store` method shall execute
                  right before it exits its lock.
                  Having a hook into `store` makes it easier to implement
                  things like an LRU caching mechanism. See the
                  LRUReplacementMixin for example usage.
        """
        dummy = self, key, value, ttl_info, opts

    def _pre_delete_full_key(self, full_key):
        """Hook called right after `_pre_delete_full_key` enters lock.

        :param full_key:  As provided to _pre_delete_full_key method.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        PURPOSE:  This is a hook that the `_pre_delete_full_key` method shall
                  execute right after it locks things.
                  Having a hook into `_pre_delete_full_key` makes it easier
                  to implement things like an LRU caching mechanism. See the
                  LRUReplacementMixin for example usage.

                  If a sub-class implements this hook, it may also want to
                  implement the _post_reset hook as well.
        """
        dummy = self, full_key

    def _post_reset(self):
        """Hook called after self.reset() finishes just before lock released.
        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        PURPOSE:  This is a hook that the `reset` method shall call right
                  after it finishes but before it releases its lock.
                  Having a hook into `_post_reset` makes it easier
                  to implement things like an LRU caching mechanism. See the
                  LRUReplacementMixin for example usage.
        """
        dummy = self

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

    def reset(self, lock=None):
        """Reset and clear the cache.

        :param lock=None:   Optional lock to use. If None, use self.lock.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        PURPOSE:  Clear everything in the cache by resetting self._data and
                  then call self._post_reset() before relesaing lock.
                  Mix-ins may want to implement _post_reset.
        """
        if lock is None:
            lock = self.lock
        with lock:
            self._data = self.make_storage()
            self._post_reset()

    def clean(self, lock=None):
        """Go through everything in the cache and remove expired elements.

        :param lock=None:   Optional lock to use. If None, use self.lock.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        :return:  Returns a list of pairs similar to `self.items` for
                  items we removed from the cache.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        PURPOSE:  Go through everything in the cache which is expired and
                  remove it. You can either use this to prune the cache
                  as necessary or use mixins like the LRUReplacementMixin
                  to keep the cache size managable.
        """
        removed = []
        if lock is None:
            lock = self.lock
        with lock:
            for full_key, ox_rec in list(self.items()):
                ttl = self.ttl_for_record(ox_rec)
                if ttl <= 0:
                    self._delete_full_key(full_key, FakeLock())
                    removed.append((full_key, ox_rec))
            return removed

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

        PURPOSE:  Store a value for the given key. You can also store
                  a value with something like `self[full_key] = value`
                  but then cannot provide things like `ttl_info`, `lock`,
                  or `**opts`.

        """
        if lock is None:
            lock = self.lock
        with lock:
            if ttl_info is None:
                ttl_info = self.create_ttl(key, **opts)
            self._pre_store(key, value, ttl_info, **opts)
            full_key = self.make_key(key, **opts)
            self._data[full_key] = OxCacheItem(value, ttl_info)
            self._post_store(key, value, ttl_info, **opts)

    def delete(self, key, lock=None, **opts):
        """Store a value for the given key.

        :param key:     Hashable key for object to delete.

        :param lock=None:   Optional lock to use. If None, use self.lock.

        :param **opts:  Keyword options for how to determine full key.
                        See the make_key method for details on key/**opts.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        PURPOSE:  Delete the given key. Raise KeyError if no such key
                  exists. You can also do `del self[full_key]` but in that
                  form you cannot provide `lock` or `**opts`.

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
            self._pre_delete_full_key(full_key)
            del self._data[full_key]

    def exists(self, key, lock=None, **opts):
        """Check if the given key is in our store.

        :param key:     Hashable key for object to check.

        :param lock=None:   Optional lock to use. If None, use self.lock.

        :param **opts:  Keyword options for how to determine full key.
                        See the make_key method for details on key/**opts.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        PURPOSE:  Return True/False if the key exists or not. Note that
                  a key may exist but still be expired. You can also use
                  something like `full_key in self` but then cannot provide
                  `lock` or `**opts` in that form.

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

        PURPOSE:  Get the value for a key. You can also use something like
                  `self[full_key]` but cannot provide other paramters in
                  that form.

        """
        if lock is None:
            lock = self.lock
        with lock:
            self._pre_get(key, allow_refresh=allow_refresh, **opts)
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


if __name__ == '__main__':
    doctest.testmod()
    print('Finished Tests')
