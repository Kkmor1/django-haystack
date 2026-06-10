from django.test import SimpleTestCase

from haystack import connections, fields, indexes
from haystack.backends.elasticsearch8_backend import Elasticsearch8SearchBackend
from haystack.constants import DJANGO_CT, DJANGO_ID
from haystack.utils.loading import UnifiedIndex

from ..core.models import MockModel


class DenseVectorField(fields.SearchField):
    field_type = "dense_vector"

    def __init__(self, dims, similarity="cosine", index=True, **kwargs):
        super().__init__(**kwargs)
        self.dims = dims
        self.similarity = similarity
        self.index = index


class Elasticsearch8BackendTestSearchIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True, model_attr="author")
    number = indexes.IntegerField(model_attr="id", faceted=True)

    def get_model(self):
        return MockModel


class Elasticsearch8BackendTestCase(SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.backend = Elasticsearch8SearchBackend(
            "elasticsearch",
            URL="http://127.0.0.1:9200/",
            INDEX_NAME="haystack-test",
        )
        self.old_ui = connections["elasticsearch"]._index
        self.ui = UnifiedIndex()
        self.ui.build(indexes=[Elasticsearch8BackendTestSearchIndex()])
        connections["elasticsearch"]._index = self.ui

    def tearDown(self):
        connections["elasticsearch"]._index = self.old_ui
        super().tearDown()

    def test_build_schema_supports_dense_vector_fields(self):
        text_field = indexes.CharField(document=True, model_attr="author")
        text_field.set_instance_name("text")
        embedding_field = DenseVectorField(dims=3, model_attr="embedding", index_fieldname="embedding")
        embedding_field.set_instance_name("embedding")

        content_field_name, mapping = self.backend.build_schema(
            {
                "text": text_field,
                "embedding": embedding_field,
            }
        )

        self.assertEqual(content_field_name, "text")
        self.assertEqual(
            mapping["embedding"],
            {
                "type": "dense_vector",
                "index": True,
                "similarity": "cosine",
                "dims": 3,
            },
        )

    def test_build_search_kwargs_supports_knn_vector_queries(self):
        search_kwargs = self.backend.build_search_kwargs(
            "*:*",
            models={MockModel},
            vector_query={
                "field": "embedding",
                "vector": [0.1, 0.2, 0.3],
                "k": 5,
                "num_candidates": 50,
            },
        )

        self.assertIn("knn", search_kwargs)
        self.assertEqual(search_kwargs["knn"]["field"], "embedding")
        self.assertEqual(search_kwargs["knn"]["query_vector"], [0.1, 0.2, 0.3])
        self.assertEqual(search_kwargs["knn"]["k"], 5)
        self.assertEqual(search_kwargs["knn"]["num_candidates"], 50)
        self.assertEqual(
            search_kwargs["knn"]["filter"],
            {"terms": {DJANGO_CT: ["core.mockmodel"]}},
        )

    def test_process_results_converts_numeric_facet_bucket_keys(self):
        raw_results = {
            "hits": {
                "total": {"value": 1},
                "hits": [
                    {
                        "_score": 1.0,
                        "_source": {
                            DJANGO_CT: "core.mockmodel",
                            DJANGO_ID: "1",
                            "text": "daniel",
                            "number": 1,
                        },
                    }
                ],
            },
            "aggregations": {
                "number": {
                    "meta": {"_type": "terms"},
                    "buckets": [
                        {"key": "1", "doc_count": 2},
                        {"key": 2, "doc_count": 1},
                    ],
                }
            },
        }

        processed = self.backend._process_results(raw_results)

        self.assertEqual(processed["hits"], 1)
        self.assertEqual(processed["facets"]["fields"]["number"], [(1, 2), (2, 1)])
        self.assertEqual(processed["results"][0].number, 1)
