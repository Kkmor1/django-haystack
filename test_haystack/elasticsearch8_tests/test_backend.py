import datetime
import operator
import unittest

import elasticsearch
from django.conf import settings
from django.test import TestCase

from haystack import connections, indexes
from haystack.exceptions import SkipDocument
from haystack.query import SearchQuerySet
from haystack.utils.loading import UnifiedIndex

from ..core.models import AnotherMockModel, MockModel, ASixthMockModel


def clear_elasticsearch_index():
    raw_es = elasticsearch.Elasticsearch(
        settings.HAYSTACK_CONNECTIONS["elasticsearch8"]["URL"]
    )
    try:
        raw_es.indices.delete(
            index=settings.HAYSTACK_CONNECTIONS["elasticsearch8"]["INDEX_NAME"]
        )
        raw_es.indices.refresh()
    except elasticsearch.TransportError:
        pass

    connections["elasticsearch8"].get_backend().setup_complete = False


class Elasticsearch8MockSearchIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True, use_template=True)
    name = indexes.CharField(model_attr="author", faceted=True)
    pub_date = indexes.DateTimeField(model_attr="pub_date")

    def get_model(self):
        return MockModel


class Elasticsearch8MockSearchIndexWithSkipDocument(
    Elasticsearch8MockSearchIndex
):
    def prepare_text(self, obj):
        if obj.author == "daniel3":
            raise SkipDocument
        return "Indexed!\n%s" % obj.id


class Elasticsearch8MockSpellingIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True)
    name = indexes.CharField(model_attr="author", faceted=True)
    pub_date = indexes.DateTimeField(model_attr="pub_date")

    def get_model(self):
        return MockModel

    def prepare_text(self, obj):
        return obj.foo


class Elasticsearch8MaintainTypeMockSearchIndex(
    indexes.SearchIndex, indexes.Indexable
):
    text = indexes.CharField(document=True, use_template=True)
    month = indexes.CharField(indexed=False)
    pub_date = indexes.DateTimeField(model_attr="pub_date")

    def prepare_month(self, obj):
        return "%02d" % obj.pub_date.month

    def get_model(self):
        return MockModel


class Elasticsearch8SpatialSearchIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(model_attr="name", document=True)
    location = indexes.LocationField()

    def prepare_location(self, obj):
        return "%s,%s" % (obj.lat, obj.lon)

    def get_model(self):
        return ASixthMockModel


class Elasticsearch8SearchBackendTestCase(TestCase):
    def setUp(self):
        super().setUp()

        self.raw_es = elasticsearch.Elasticsearch(
            settings.HAYSTACK_CONNECTIONS["elasticsearch8"]["URL"]
        )
        clear_elasticsearch_index()

        self.old_ui = connections["elasticsearch8"].get_unified_index()
        self.ui = UnifiedIndex()
        self.smmi = Elasticsearch8MockSearchIndex()
        self.smmidni = Elasticsearch8MockSearchIndexWithSkipDocument()
        self.smtmmi = Elasticsearch8MaintainTypeMockSearchIndex()
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
            self.sample_objs.append(mock)

    def tearDown(self):
        connections["elasticsearch8"]._index = self.old_ui
        super().tearDown()
        self.sb.silently_fail = True

    def raw_search(self, query="*:*"):
        try:
            return self.raw_es.search(
                index=settings.HAYSTACK_CONNECTIONS["elasticsearch8"][
                    "INDEX_NAME"
                ],
                body={"query": {"match_all": {}}},
            )
        except elasticsearch.TransportError:
            return {}

    def test_update(self):
        self.sb.update(self.smmi, self.sample_objs)

        result = self.raw_search()
        self.assertEqual(result["hits"]["total"]["value"], 3)
        self.assertEqual(
            sorted(
                [
                    res["_source"]
                    for res in result["hits"]["hits"]
                ],
                key=lambda x: x["id"],
            ),
            [
                {
                    "django_id": "1",
                    "django_ct": "core.mockmodel",
                    "name": "daniel1",
                    "name_exact": "daniel1",
                    "text": "Indexed!\n1\n",
                    "pub_date": "2009-02-24T00:00:00",
                    "id": "core.mockmodel.1",
                },
                {
                    "django_id": "2",
                    "django_ct": "core.mockmodel",
                    "name": "daniel2",
                    "name_exact": "daniel2",
                    "text": "Indexed!\n2\n",
                    "pub_date": "2009-02-23T00:00:00",
                    "id": "core.mockmodel.2",
                },
                {
                    "django_id": "3",
                    "django_ct": "core.mockmodel",
                    "name": "daniel3",
                    "name_exact": "daniel3",
                    "text": "Indexed!\n3\n",
                    "pub_date": "2009-02-22T00:00:00",
                    "id": "core.mockmodel.3",
                },
            ],
        )

    def test_remove(self):
        self.sb.update(self.smmi, self.sample_objs)
        self.assertEqual(self.raw_search()["hits"]["total"]["value"], 3)

        self.sb.remove(self.sample_objs[0])
        self.assertEqual(self.raw_search()["hits"]["total"]["value"], 2)
        self.assertEqual(
            sorted(
                [
                    res["_source"]
                    for res in self.raw_search()["hits"]["hits"]
                ],
                key=operator.itemgetter("django_id"),
            ),
            [
                {
                    "django_id": "2",
                    "django_ct": "core.mockmodel",
                    "name": "daniel2",
                    "name_exact": "daniel2",
                    "text": "Indexed!\n2\n",
                    "pub_date": "2009-02-23T00:00:00",
                    "id": "core.mockmodel.2",
                },
                {
                    "django_id": "3",
                    "django_ct": "core.mockmodel",
                    "name": "daniel3",
                    "name_exact": "daniel3",
                    "text": "Indexed!\n3\n",
                    "pub_date": "2009-02-22T00:00:00",
                    "id": "core.mockmodel.3",
                },
            ],
        )

    def test_clear(self):
        self.sb.update(self.smmi, self.sample_objs)
        self.assertEqual(
            self.raw_search()
            .get("hits", {})
            .get("total", {})
            .get("value", 0),
            3,
        )

        self.sb.clear()
        self.assertEqual(
            self.raw_search()
            .get("hits", {})
            .get("total", {})
            .get("value", 0),
            0,
        )

        self.sb.update(self.smmi, self.sample_objs)
        self.assertEqual(
            self.raw_search()
            .get("hits", {})
            .get("total", {})
            .get("value", 0),
            3,
        )

        self.sb.clear([MockModel])
        self.assertEqual(
            self.raw_search()
            .get("hits", {})
            .get("total", {})
            .get("value", 0),
            0,
        )