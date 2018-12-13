"""Module containing various memoizers based on ox_cache
"""

import doctest
import inspect
import functools


from ox_cache import OxCacheBase, OxCacheFullKey
from ox_cache.mixins import TimedExpiryMixin, LRUReplacementMixin


class OxMemoizer(OxCacheBase):
    """Function memoizer based on OxCacheBase.

    This is a class that can be used to cache calls to a function (a
    practice also known as "memoizing" or "memoization"). You can
    use one of the sub-classes of OxMemoizer such as TimedMemoizer
    or LRUMemoizer or create your own pretty easily.

    The base OxMemoizer class can be used as a function decorator
    as shown below. Basically you decorate a function with OxMemoizer
    and then calls will be cached. You will need to manually delete
    entries from the cache with the plain OxMemoizer. But you can
    use other classes like TimedMemoizer or LRUMemoizer to get timed
    expiration or least-recently-used expiraton or write your own
    mix-in to customize how your memoization works.

    See the documentation for OxCacheBase as the OxMemoizer is actually
    a sub-class of OxCacheBase with a few minor tweaks so that it can
    be used as a decorator.

    Without further ado, the following illustrates example usage:

>>> from ox_cache import OxMemoizer
>>> @OxMemoizer
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
Memoized by OxMemoizer...

    """

    def __init__(self, func, *args, **kwargs):
        """Initializer.

        :param func:      Function we are going to cache.

        :param *args, **kwargs:    Passed to super().__init__

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        PURPOSE:  This initializer is designed so that you can use
                  it as a function decorator. Hence, it requires the
                  first argument to be the function to decorate.

                  In decorator form, no other arguments are possible,
                  but you can also use it in a class-form if you like
                  and pass further arguments.
        """
        self.func = func
        self.argspec = inspect.getfullargspec(func)
        super().__init__(*args, **kwargs)
        self._fix_wrapper()

    def _fix_wrapper(self):
        """Helper function to wrap various things to work as a decorator.

In order to work as a function decorator, we need to do the following:

    1. Fix self.__doc__ to include the doc for the wrapped function along
       with some mention that it is wrapped by this class.
    2. Move original versions of methods like ttl, expired, delete, and
       exists into raw_* versions and create wrapped versions of these
       methods which take the *args, **kwargs they get and call
       self.input_to_full_key to normalize the arguments into a stable key.
        """
        orig_doc = getattr(self, '__doc__')
        orig_mod = getattr(self, '__module__')
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
        """Make a decorated version of the given function.

        :param func:     Method to decorate (e.g., self.ttl).

        :param name:     Name of method (e.g., 'ttl').

        :param raw_name: Name to move original method to (e.g., 'raw_ttl').

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        :return:  A decorated version of func which first calls
                  self.input_to_full_key and then calls the original func.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        PURPOSE:  Function calls can occur in a variety of ways because
                  arguments can be supplied normally or with keywords.
                  Therefore we need to use self.input_to_full_key to
                  normalize function inputs to a stable key and then use
                  that to call the underlying OxCacheBase methods.
        """
        @functools.wraps(func)
        def decorated(*args, **kwargs):
            "Decorated method to first normalize function arguments."
            full_key = self.input_to_full_key(*args, **kwargs)
            return func(full_key)
        decorated.__doc__ = '\n'.join([
            '', 'NOTE: wrapped to translate calling %(name)s(*args, **kw)',
            'to first get full_key = self.input_to_full_key(*args, **kw)',
            'and then call self.%(raw_name)s(full_key).', ''
            'Call self.%(raw_name)s for raw version described below.',
            '', '---']) % {'name': name, 'raw_name': raw_name} + (
                func.__doc__ if func.__doc__ else '(no docs for %s)' % (
                    raw_name))
        return decorated

    def make_value(self, key, **opts):
        "Make the value for a key by calling underling self.func."

        if (not opts) and isinstance(key, OxCacheFullKey):
            opts = dict(key.opts)
            try:  # remove namespace from the opts if it is there
                opts.pop('namespace')
            except KeyError:
                pass

        return self.func(**opts)

    def input_to_full_key(self, *args, **kwargs):
        """Take function inputs and conver to full key.

        :param *args, **kwargs:    Function inputs.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        :return:  An instance of OxCacheFullKey based on function arguments
                  normalized somewhat which can be used to call most
                  of the usual OxCacheBase methods.

        ~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-~-

        PURPOSE:  Function calls can occur in a variety of ways because
                  arguments can be supplied normally or with keywords.
                  Therefore we need to use self.input_to_full_key to
                  normalize function inputs to a stable full key. That
                  full key can then be used to reference the function
                  output even if the function is called in different (but
                  equivalent ways).
        """
        key = self.func.__name__
        if (not kwargs) and (len(args) == 1) and isinstance(
                args[0], OxCacheFullKey):  # being called with a full key
            full_key = args[0]             # already so just return it
        else:
            opts = dict(kwargs)
            for num, value in enumerate(args):
                name = self.argspec.args[num]
                opts[name] = value
            full_key = self.make_key(key, **opts)

        return full_key

    def __call__(self, *args, **kwargs):
        """In decorator form, this represents a call to the function.
        """
        full_key = self.input_to_full_key(*args, **kwargs)
        return self.get(full_key)


class TimedMemoizer(TimedExpiryMixin, OxMemoizer):
    """Memoizer class using time based refresh via TimedExpiryMixin.

This is a class that can be used to memoize a function and expire the
cache elements using the TimedExpiryMixin. This class is actually
trivial. It consists of the line

    class TimedMemoizer(TimedExpiryMixin, OxMemoizer):

followed by this docstring. That is, the entire class is created by
combining the TimedExpiryMixin class with the OxMemoizer. The effect
is that it works as described for OxMemoizer with the additional feature
that cache entry expiration is done as described for TimedExpiryMixin.

The following illustrates example usage:

>>> from ox_cache import TimedMemoizer
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
>>> my_func.expiry_seconds = 1   # Set expiration time to 1 second.
>>> import time; time.sleep(1.1) # Sleep and then check for expiration.
>>> my_func.expired(1, 2)
True
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
    """Memoizer class using time based refresh and LRU replacement.

This is a class that can be used to memoize a function keeping
only `self.max_size` elements with least recently used items being replaced.
The class is actually trivial. It consists of the line

    class TimedMemoizer(LRUReplacementMixin, TimedExpiryMixin, OxMemoizer):

followed by this docstring. That is, the entire class is created by
combining the LRUReplacementMixin, with the TimedExpiryMixin, and the
the OxMemoizer. The effect is that it works as described for
OxMemoizer with the additional feature that cache entry expiration is
done as described for TimedExpiryMixin and if there are too many elements
we kick out the least recently used.

>>> from ox_cache import LRUReplacementMemoizer
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
>>> len(my_func), my_func.exists(1, 0)  # Verify least recent item kicked out
(3, False)
>>> my_func.delete(1, 2)  # Delete an item and add some more
>>> data = [my_func(2, i) for i in range(2)]
called my_func(2, 0) = 2
called my_func(2, 1) = 3
>>> my_func.exists(1, 1)  # Verify that least recent item kicked out
False
>>> my_func.expiry_seconds = 1   # Set things to expire after 1 second
>>> import time; time.sleep(1.1) # Sleep and then check for expiration.
>>> my_func.expired(2, 1)        # Note that it is expired but still in cache
True
>>> for full_key, record in list(sorted(my_func.items())):  # Illustrate how
...     if my_func.is_record_expired(record):               # to iterate
...         k = ', '.join(['%s=%s' % (k, v) for k, v in full_key.opts])
...         v = record.payload # extract the data from the cache entry
...         print('Delete (%s)=%s since expired' % (k, v))
...         my_func.delete(full_key)
...
Delete (x=1, y=3)=4 since expired
Delete (x=2, y=0)=2 since expired
Delete (x=2, y=1)=3 since expired
    """


if __name__ == '__main__':
    doctest.testmod()
    print('Finished tests')
