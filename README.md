
# Introduction

The `ox_cache` package is a collection of tools for fast, thread-safe, and
flexible caching or memoizing of results. In particular, `ox_cache` is
designed to make it easy to implement the quirks of your particular
caching needs.

For example, if you want to repopulate the entire cache when you get a
single cache miss, you can include the `RefreshDictMixin`. Or if you
want to include least-recently-used semantics, you can include the
`LRUReplacementMixin`.

The basic structure is that you create a sub-class of `OxCacheBase`,
include appropriate mixins, and then define a way to get a new value
on a cache miss.

## Features

Some of the interesting features of `ox_cache` include:

  1. Flexible: You can mix and match mixins and overrides to easily get
               desired caching behaviour.
  2. Memoization: Built-in decorators for function memoization.
  3. Dict-like: Dictionary methods such as `__setitem__`, `__getitem__`, `__delitem__`, `__contains__`, `__iter__`, and `items` are provided.
  4. Thread-safe:  All of the basic operations use threading.Lock().
  5. Thread-smart: Hooks and overridable methods are structured so
                   that you can ignore threads in your customization but
				   stay thread safe.
  6. Docs: Python docstrings are provided for every class and method.
  7. Unit tests: Source code comes with unit tests with very high code coverage.

  

# Quick Start

## Installation

Install with the usual
```sh
$ pip install ox_cache
```

## Caching

To get a cache you simply sub-class `OxCacheBase` and then override
desired methods. The only required method you must override is the
`make_value` method to make the value when a key is not in the
cache. The following illustrates the simplest use case:

```python
>>> from ox_cache import OxCacheBase
>>> class BasicCache(OxCacheBase):
...     def make_value(self, key, **opts):
...         'Simple function to create value for requested key.'
...         print('Calling refresh for key="%s"' % key)
...         return 'x' * key  # create a bunch of x's
...
>>> cache = BasicCache()
>>> cache.get(5)  # Will call make_value to generate 1st value.
Calling refresh for key="5"
'xxxxx'
>>> cache.get(5)  # Will get value from cache without calling make_value
'xxxxx'

```

You can get more interesting cache features by including mixins.  The
following illustrate a simple example where we include the
`TimedExpiryMixin` so that cache entries expire after a set amount of
time.

```python

>>> from ox_cache import OxCacheBase, TimedExpiryMixin
>>> class TimedCache(TimedExpiryMixin, OxCacheBase):
...     'Cache which expires items after after self.expiry_seconds.'
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

```

In addition to the `get` method illustrated above, a few other methods
you may find useful include:

  1. `ttl`: Return the time-to-live for a key.
  2. `expired`: Return whether the cache entry for a key has expired.
  3. `delete`: Remove an entry from the cache.
  4. `clean`: Go through the entire cache and remove expired elements.
  5. `exists`: Check if an element is in the cache (possibly expired).
  

For more sophisticated caching you can use more mix-ins or override
the desired functions. See the docs for the `OxCacheBase` class in the
source code or in the following documentation sections.

## Memoization

To memoize (cache) function calls you can use something like
the `OxMemoizer` as a function decorator as shown in the example below:

```python

>>> from ox_cache import OxMemoizer
>>> @OxMemoizer
... def my_func(x, y):
...     'Add two inputs'
...     z = x + y
...     print('called my_func(%s, %s) = %s' % (x, y, z))
...     return z
...
>>> my_func(1, 2)  # This will actually call the function.
called my_func(1, 2) = 3
3
>>> my_func(1, 2)  # This will use a cached value.
3

```

Since `OxMemoizer` is just a sub-class of `OxCacheBase` you can use
one of the provided mixins to control expiration or just use something
like the `LRUReplacementMemoizer`. As shown below, setting the
`max_size` property of an instance of `LRUReplacementMemoizer` will
automatically kick out least recently used cache entries when the
cache gets too large.

```python

>>> from ox_cache import LRUReplacementMemoizer
>>> @LRUReplacementMemoizer
... def my_func(x, y):
...     'Add two inputs'
...     z = x + y
...     print('called my_func(%s, %s) = %s' % (x, y, z))
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
>>> len(my_func), my_func.exists(1, 0)  # Verify least recent item kicked out
(3, False)

```

If you wanted time based expiration, you could use `TimedMemoizer` or
simply subclass `OxMemoizer` and include mixins like
`LRUReplacementMixin` and/or `TimedExpiryMixin`.

Note that since our memoizers are sub-classes of `OxCacheBase`, you
can use any of the methods from `OxCacheBase` as shown below:

```python

>>> my_func.exists(1, 3)
True
>>> my_func.delete(1, 3)
>>> my_func.exists(1, 3)
False

```

# Discussion

The ox_cache package provides tools to build your own simple caching
system. The core class is `OxCacheBase` which everything inherits
from.  The only function which you must provide when you sub-class
`OxCacheBase` is `make_value` which defines how to create a value
which is not in the cache.

You can further customize how the cache works either by overriding
appropriate methods or by using one of the many mixins provided.  For
example, the following illustrates how you can use the
`TimedExpiryMixin` and the `RefreshDictMixin` to create a `BatchCache`
which updates the whole cache any time there is a cache miss:

```python

>>> from ox_cache import OxCacheBase, TimedExpiryMixin, RefreshDictMixin
>>> class BatchCache(TimedExpiryMixin, RefreshDictMixin, OxCacheBase):
...     'Simple cache with time-based refresh via a function that gives dict'
...     def make_dict(self, key):
...         "Function to make dict to use to refresh cache."
...         return {k: str(k)+self.info for k in ([key] + list(range(10)))}
...
>>> cache = BatchCache()
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

```

# Additional Information

You can find the project page at https://github.com/emin63/ox_cache
