import datetime
import unittest

from django.test import TestCase

try:
    import elasticsearch
    from haystack.backends.elasticsearch8_backend import Elasticsearch8SearchBackend
    from test_haystack.core.models import MockModel
    from haystack.utils.loading import UnifiedIndex
    from haystack import indexes
except ImportError:
    elasticsearch = None

class Elasticsearch8MockSearchIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True, use_template=True)
    name = indexes.CharField(model_attr="author", faceted=True)
    pub_date = indexes.DateTimeField(model_attr="pub_date")

    def get_model(self):
        return MockModel

@unittest.skipUnless(
    elasticsearch and (8, 0, 0) <= elasticsearch.__version__ < (9, 0, 0),
    "elasticsearch 8.x not installed"
)
class Elasticsearch8SearchBackendTestCase(TestCase):
    def setUp(self):
        super().setUp()
        self.sb = Elasticsearch8SearchBackend(
            "default",
            URL="http://localhost:9200/",
            INDEX_NAME="test_es8_backend",
            SILENTLY_FAIL=False,
        )
        
        self.ui = UnifiedIndex()
        self.smmi = Elasticsearch8MockSearchIndex()
        self.ui.build(indexes=[self.smmi])
        
        # Monkey patch to return our index
        import haystack
        self.old_get_unified_index = haystack.connections["default"].get_unified_index
        haystack.connections["default"].get_unified_index = lambda: self.ui
        
        self.sb.clear()
        self.sb.setup()

        self.sample_objs = []
        for i in range(1, 4):
            mock = MockModel()
            mock.id = i
            mock.author = "daniel%s" % i
            mock.pub_date = datetime.date(2009, 2, 25) - datetime.timedelta(days=i)
            self.sample_objs.append(mock)

    def tearDown(self):
        import haystack
        haystack.connections["default"].get_unified_index = self.old_get_unified_index
        self.sb.clear()
        super().tearDown()

    def test_update(self):
        self.sb.update(self.smmi, self.sample_objs)
        # Verify docs are inserted
        res = self.sb.search("*:*")
        self.assertEqual(res["hits"], 3)

    def test_remove(self):
        self.sb.update(self.smmi, self.sample_objs)
        self.assertEqual(self.sb.search("*:*")["hits"], 3)
        self.sb.remove(self.sample_objs[0])
        self.assertEqual(self.sb.search("*:*")["hits"], 2)

    def test_clear(self):
        self.sb.update(self.smmi, self.sample_objs)
        self.assertEqual(self.sb.search("*:*")["hits"], 3)
        self.sb.clear()
        self.assertEqual(self.sb.search("*:*")["hits"], 0)
