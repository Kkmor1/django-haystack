import datetime
import operator
import unittest

import elasticsearch
from django.conf import settings
from django.test import TestCase
from django.test.utils import override_settings

from haystack import connections, indexes
from haystack.models import SearchResult
from haystack.utils.loading import UnifiedIndex

from ..core.models import MockModel


def clear_elasticsearch8_index():
    url = settings.HAYSTACK_CONNECTIONS.get("elasticsearch8", {}).get("URL")
    if not url:
        url = settings.HAYSTACK_CONNECTIONS.get("elasticsearch", {}).get("URL", "http://localhost:9200/")
    index_name = settings.HAYSTACK_CONNECTIONS.get("elasticsearch8", {}).get("INDEX_NAME")
    if not index_name:
        index_name = settings.HAYSTACK_CONNECTIONS.get("elasticsearch", {}).get("INDEX_NAME", "test_es8")

    raw_es = elasticsearch.Elasticsearch(url)
    try:
        raw_es.indices.delete(index=index_name, ignore=[400, 404])
        raw_es.indices.refresh(index=index_name, ignore=[404])
    except elasticsearch.TransportError:
        pass

    connections["elasticsearch8"].get_backend().setup_complete = False


class Elasticsearch8MockSearchIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True, use_template=True)
    name = indexes.CharField(model_attr="author", faceted=True)
    pub_date = indexes.DateTimeField(model_attr="pub_date")
    post_count = indexes.IntegerField(model_attr="post_count", faceted=True)
    average_rating = indexes.FloatField(model_attr="average_rating", faceted=True)

    def get_model(self):
        return MockModel


class Elasticsearch8RoundTripSearchIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True, default="")
    name = indexes.CharField()
    is_active = indexes.BooleanField()
    post_count = indexes.IntegerField()
    average_rating = indexes.FloatField()
    pub_date = indexes.DateField()
    created = indexes.DateTimeField()
    tags = indexes.MultiValueField()

    def get_model(self):
        return MockModel

    def prepare(self, obj):
        prepped = super().prepare(obj)
        prepped.update(
            {
                "text": "This is some example text.",
                "name": "Mister Pants",
                "is_active": True,
                "post_count": 25,
                "average_rating": 3.6,
                "pub_date": datetime.date(2009, 11, 21),
                "created": datetime.datetime(2009, 11, 21, 21, 31, 00),
                "tags": ["staff", "outdoor", "activist", "scientist"],
            }
        )
        return prepped


class Elasticsearch8SearchBackendTestCase(TestCase):
    def setUp(self):
        super().setUp()

        self.old_ui = connections["elasticsearch8"].get_unified_index()
        self.ui = UnifiedIndex()
        self.smmi = Elasticsearch8MockSearchIndex()
        self.ui.build(indexes=[self.smmi])
        connections["elasticsearch8"]._index = self.ui
        self.sb = connections["elasticsearch8"].get_backend()

        self.sb.existing_mapping = {}
        self.sb.setup()

        self.sample_objs = []

        for i in range(1, 4):
            mock = MockModel()
            mock.id = i
            mock.author = "daniel%s" % i
            mock.pub_date = datetime.date(2009, 2, 25) - datetime.timedelta(days=i)
            mock.post_count = i * 10
            mock.average_rating = float(i) * 1.5
            self.sample_objs.append(mock)

        self.sb.update(self.smmi, self.sample_objs)

    def tearDown(self):
        connections["elasticsearch8"]._index = self.old_ui
        super().tearDown()

    def test_update_and_search(self):
        results = self.sb.search("*:*")
        self.assertEqual(results["hits"], 3)
        result_pks = {result.pk for result in results["results"]}
        self.assertEqual(result_pks, {"1", "2", "3"})

    def test_facet_returns_numeric_types(self):
        results = self.sb.search("*:*", facets={"post_count": {}})
        self.assertIn("facets", results)
        self.assertIn("fields", results["facets"])
        self.assertIn("post_count", results["facets"]["fields"])

        facet_values = results["facets"]["fields"]["post_count"]
        for value, count in facet_values:
            self.assertIsInstance(
                value,
                (int, float),
                f"Facet value should be numeric, got {type(value)}: {value}",
            )

    def test_float_facet_returns_numeric_types(self):
        results = self.sb.search("*:*", facets={"average_rating": {}})
        self.assertIn("facets", results)
        self.assertIn("fields", results["facets"])
        self.assertIn("average_rating", results["facets"]["fields"])

        facet_values = results["facets"]["fields"]["average_rating"]
        for value, count in facet_values:
            self.assertIsInstance(
                value,
                (int, float),
                f"Facet value should be numeric, got {type(value)}: {value}",
            )
