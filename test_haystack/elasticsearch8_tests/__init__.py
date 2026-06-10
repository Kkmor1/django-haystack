import os
import unittest

from haystack.utils import log as logging


def load_tests(loader, standard_tests, pattern):
    log = logging.getLogger("haystack")
    try:
        import elasticsearch

        if not ((8, 0, 0) <= elasticsearch.__version__ < (9, 0, 0)):
            raise ImportError
    except ImportError:
        log.error("Skipping ElasticSearch 8 tests: 'elasticsearch>=8.0.0,<9.0.0' not installed.")
        raise unittest.SkipTest("'elasticsearch>=8.0.0,<9.0.0' not installed.")

    package_tests = loader.discover(start_dir=os.path.dirname(__file__), pattern=pattern)
    standard_tests.addTests(package_tests)
    return standard_tests
