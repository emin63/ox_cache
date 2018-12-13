"""Package for creating various kinds of data caches.
"""

import logging

from ox_cache.core import (OxCacheBase, RefreshDictMixin)

if __name__ == '__main__':
    logging.info(
        'Imported various ox_cache classes:\n%s', '\n'.join([
            str(m) for m in [OxCacheBase, RefreshDictMixin]] + [
                'Nothing gets done when running this module as main.']))
