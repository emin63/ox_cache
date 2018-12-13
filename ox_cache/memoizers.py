"""Module containing various memoizers based on ox_cache
"""


import inspect
import functools


from ox_cache.core import OxCacheBase
from ox_cache.mixins import TimedExpiryMixin, LRUReplacementMixin

class OxMemoizer(OxCacheBase):
    """FIXME
    """# FIXME

    def __init__(self, func, *args, **kwargs):
        self.func = func
        self.argspec = inspect.getfullargspec(func)
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


class TimedMemoizer(TimedExpiryMixin, OxMemoizer):
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
        LRUReplacementMixin, TimedExpiryMixin, OxMemoizer):
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
