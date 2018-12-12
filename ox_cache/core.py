"""Core implementation of ox_cache

The ox_cache.core module provides tools to build your own simple caching
system. See docs on the following for details:

  - OxCacheBase:        Base class all caches inherit from.
  - TimedRefreshMixin:  Mix-in for time-based refresh.
  - RefreshDictMixin:   Mix-in to refresh full cache from a dict.

The following illustrates how you can use these classes to create a
simple cache which refreshes itself either when a set amount of time
has passed or when a cache miss occurs.

>>> import logging, datetime, time
>>> from ox_cache.core import OxCacheBase, TimedRefreshMixin, RefreshDictMixin
>>> class MyCache(TimedRefreshMixin, RefreshDictMixin, OxCacheBase):
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
>>> cache.refresh_seconds = 1  # make refresh time very short
>>> time.sleep(1.5)  # sleep so that cache becomes stale
>>> cache.ttl(2)
0
>>> cache.get(2)     # check cache to see that we auto-refresh
'26'
>>> cache.refresh_seconds = 1000  # slow down auto refresh for other examples
>>> cache.store(800, 5)
>>> cache.get(800)
5
>>> cache.store('800', 'a string')
>>> cache.get('800')
'a string'
>>> cache.delete(800)
>>> cache.get(800, allow_refresh=False) is None
True


>>> from ox_cache.core import TimedMemoizer
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
>>> my_func.refresh_seconds = 1   # make refresh time very short
>>> import time; time.sleep(1.5)  # sleep so that cache becomes stale
>>> my_func.exists(1, y=2)        # can check existsnce and kwargs works
True
>>> my_func.expired((1, 2))       # verify that cache is expired
True
>>> my_func(1, 2)                 # will call function again since expired
Adding 1 to 2 gives 3
3
"""

import random
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


class OxCacheBase:
    """Base class for caches.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self._data = {}

    def __len__(self):
        return len(self._data)

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

    def refresh(self, key, **opts):
        """Refresh the cache for key (or maybe for everything).

        :param key:     Hashable key for object to refresh.

        :param **opts:  Keyword options for how to do the refresh.
                        See the make_key method for details on key/**opts.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        PURPOSE:  Refresh self._data either for this key or perhaps
                  for everything.  Sub-classes must implement.

                  This is one of the core methods which determines how
                  the cache works.
        """
        raise NotImplementedError

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
        """
        raise NotImplementedError

    def get_ttl_info(self, key, **opts):
        """Return time to live related information for given key and opts

        :param key:     Hashable key for object to refresh.

        :param **opts:  Keyword options for how to do the refresh.
                        See the make_key method for details on key/**opts.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        :return:  The ttl_info object for the record with the given
                  key/**opts.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        PURPOSE:  Get time to live related information or None if there
                  is no record for the given key/**opts. By default,
                  this method simply returns datetime.datetime.utcnow()
                  to represent when the item was added to the cache.
                  Sub-classes can use the returned value as they see fit
                  or override this method.
        """
        dummy = self, key, opts
        return datetime.datetime.utcnow()

    def expired(self, key, lock=None, **opts):
        """Determine if the given key/**opts is expired.

        :param key:     Hashable key for object to refresh.

        :param lock=None:   Optional lock to use. If None, use self.lock.

        :param **opts:  Keyword options for how to do the refresh.
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
        if lock is None:
            lock = self.lock
        with lock:
            if ttl_info is None:
                ttl_info = self.get_ttl_info(key, **opts)
            full_key = self.make_key(key, **opts)
            self._data[full_key] = OxCacheItem(value, ttl_info)

    def delete(self, key, lock=None, **opts):
        full_key = self.make_key(key, **opts)
        return self._delete_full_key(full_key, lock=lock)

    def _delete_full_key(self, full_key, lock=None):
        if lock is None:
            lock = self.lock
        with lock:
            try:
                del self._data[full_key]
            except KeyError:
                pass

    def exists(self, key, lock=None, **opts):
        full_key = self.make_key(key, **opts)
        return self.get_record(full_key, lock=lock) is not None

    def get_record(self, full_key, lock=None):
        if lock is None:
            lock = self.lock
        with lock:        
            record = self._data.get(full_key, None)
            return record

    def get(self, key, allow_refresh=True, lock=None, default=None, **opts):
        if lock is None:
            lock = self.lock
        with lock:
            base_key = key
            key = self.make_key(base_key, **opts)
            record = self._data.get(key, None)
            fake_lock = threading.Lock()  # already locked so fake lower lock
            if record is None:     # Do not know anything about requested key
                if allow_refresh:  # If allowed, do a refresh
                    self.refresh(base_key, lock=fake_lock, **opts)
                    return self.get(base_key, allow_refresh=False,
                                    lock=fake_lock, **opts)
                else:
                    return default
            # record was found but may be expired so must check that
            if self.is_record_expired(record):
                if allow_refresh:
                    self.refresh(base_key, lock=fake_lock, **opts)
                    return self.get(base_key, allow_refresh=False,
                                    lock=fake_lock, **opts)
                else:
                    return default

            # Found a non-expired record so return payload
            return record.payload


class TimedRefreshMixin:

    def __init__(self, *args, refresh_seconds=3600, **kwargs):
        self.refresh_seconds = refresh_seconds
        super().__init__(*args, **kwargs)

    def ttl(self, key, **opts):
        full_key = self.make_key(key, **opts)
        record = self.get_record(full_key)
        return self.ttl_for_record(record)

    def ttl_for_record(self, record):
        now = datetime.datetime.utcnow()
        return max(0, self.refresh_seconds - 
                   (now - record.ttl_info).total_seconds())


class RandomReplacementMixin:

    def __init__(self, *args, max_size=5, **kwargs):
        self.max_size = max_size
        super().__init__(*args, **kwargs)

    def store(self, key, value, ttl_info=None, lock=None, **opts):
        orig_lock = lock
        if lock is None:
            lock = self.lock
        with lock:
            fake_lock = threading.Lock()
            while len(self._data) >= self.max_size:
                full_key_to_delete = random.choice(list(self._data))
                logging.debug('%s will remove key %s',
                              self.__class__.__name__, full_key_to_delete)
                self._delete_full_key(full_key_to_delete, lock=fake_lock)
        return super().store(key, value, ttl_info, orig_lock, **opts)


class RefreshDictMixin:

    def refresh(self, key, lock=None, **opts):
        logging.debug('Calling %s in %s', 'refresh', self.__class__.__name__)
        if lock is None:
            lock = self.lock
        with lock:
            my_dict = self.make_dict(key)
            ttl_info = self.get_ttl_info(key, **opts)
            fake_lock = threading.Lock()  # already locked so fake lower lock
            for base_key, value in my_dict.items():
                self.store(base_key, value, ttl_info,
                           lock=fake_lock, **opts)


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


class TimedMemoizer(TimedRefreshMixin, MemoizerMixin):
    """Memoizer class using time based refresh via TimedRefreshMixin.

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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class RandomReplacementMemoizer(
        RandomReplacementMixin, TimedRefreshMixin, MemoizerMixin):
    """Memoizer class using time based refresh via RandomReplacementMixin

    This is a class that can be used to memoize a function via something
    like

>>> from ox_cache.core import RandomReplacementMemoizer
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
>>> import random; random.seed(123) # make test repeatable
>>> my_func.max_size = 3
>>> data = [my_func(1, random.randint(1, 50)) for i in range(5)]
called my_func(1, 4) = 5
called my_func(1, 18) = 19
called my_func(1, 6) = 7
called my_func(1, 50) = 51
>>> len(my_func)
3
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

if __name__ == '__main__':
    doctest.testmod()
    print('Finished Tests')
