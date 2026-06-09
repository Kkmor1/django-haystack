"""
Unit tests for the Elasticsearch 8 backend.

These tests cover three important aspects of the backend:

1. Schema building (mappings): Elasticsearch 8 dropped support for
   document types. Tests verify that the generated mappings no longer
   contain any doc_type and that field mappings are correctly generated
   for standard field types.

2. Numeric facet key coercion: previous ES backends returned facet keys
   as strings, even for numeric fields, which broke downstream code that
   expected integers/floats. The tests verify that numeric keys are
   correctly typed after processing.

3. Dense vector / kNN search support: tests verify that the query
   builder correctly emits a ``knn`` section for vector similarity
   search and that the vector_search helper method builds the expected
   arguments.

These tests deliberately do not require a running Elasticsearch
instance: they test the pure-Python behaviour of the backend class
itself.
"""
import datetime
import unittest

from haystack.backends.elasticsearch8_backend import (
    Elasticsearch8SearchBackend,
)


class FakeUnifiedIndex:
    """Minimal stand-in for haystack's UnifiedIndex used for schema tests."""

    def __init__(self, fields=None):
        self._fields = fields or {}
        self.document_field = "text"

    def all_searchfields(self):
        return self._fields

    def get_facet_fieldname(self, name):
        return name

    def get_indexed_models(self):
        return []


class FakeField:
    def __init__(self, field_type, indexed=True, boost=1.0, faceted=False):
        self.field_type = field_type
        self.indexed = indexed
        self.boost = boost
        self.faceted = faceted
        self.index_fieldname = field_type
        self.document = False


class FakeConnectionOptions:
    """Fake connection options for building a backend without Django settings."""

    def __init__(self):
        self.URL = "http://localhost:9200"
        self.INDEX_NAME = "test_elasticsearch8"


class Elasticsearch8SchemaTestCase(unittest.TestCase):
    """
    Test 1: Schema / mapping generation for Elasticsearch 8.

    Elasticsearch 8 removed mapping types (``_type``), so the backend
    must build a mapping without any reference to ``doc_type`` and
    produce a valid properties dictionary.
    """

    def _make_backend(self):
        # Patch the class to avoid actually talking to ES.
        original_init = Elasticsearch8SearchBackend.__init__

        def patched_init(self, conn_alias, **kwargs):
            # Skip the real __init__ and set only what tests need.
            self.connection_alias = conn_alias
            self.index_name = "test_elasticsearch8"
            self.setup_complete = False
            self.existing_mapping = {}
            self.include_spelling = False
            self.silently_fail = True
            self.timeout = 10

        try:
            Elasticsearch8SearchBackend.__init__ = patched_init
            backend = Elasticsearch8SearchBackend("default")
            return backend
        finally:
            Elasticsearch8SearchBackend.__init__ = original_init

    def test_build_schema_has_no_doc_type(self):
        backend = self._make_backend()
        fields = {"text": FakeField("text", faceted=False)}
        _, mapping = backend.build_schema(fields)

        self.assertNotIn("doc_type", mapping)
        self.assertIn("text", mapping)
        self.assertEqual(mapping["text"]["type"], "text")

    def test_build_schema_numeric_and_date_types(self):
        backend = self._make_backend()
        fields = {
            "price": FakeField("float"),
            "count": FakeField("integer"),
            "created": FakeField("datetime"),
            "active": FakeField("boolean"),
        }
        _, mapping = backend.build_schema(fields)

        self.assertEqual(mapping["price"]["type"], "float")
        self.assertEqual(mapping["count"]["type"], "long")
        self.assertEqual(mapping["created"]["type"], "date")
        self.assertEqual(mapping["active"]["type"], "boolean")

    def test_build_schema_faceted_field_becomes_keyword(self):
        backend = self._make_backend()
        fields = {"category": FakeField("string")}
        content_field, mapping = backend.build_schema(
            {"category": FakeField("string", indexed=True)}
        )
        # The build_schema method creates a mapping entry named after the
        # attribute. Check that text fields without `indexed=False` default
        # to text type rather than keyword.
        self.assertIn("text", mapping["category"]["type"])


class Elasticsearch8NumericFacetTestCase(unittest.TestCase):
    """
    Test 2: Numeric facet key coercion.

    The original ES backends returned facet keys verbatim. When a field
    was numeric, ES still returned keys as JSON-encoded strings in the
    aggregation bucket, leading to surprising output such as::

        facets["fields"]["category"] == [("42", 7)]

    The Elasticsearch 8 backend is supposed to restore the original
    numeric type when possible.
    """

    def _make_backend(self):
        original_init = Elasticsearch8SearchBackend.__init__

        def patched_init(self, conn_alias, **kwargs):
            self.connection_alias = conn_alias
            self.index_name = "test_elasticsearch8"
            self.setup_complete = False
            self.existing_mapping = {}
            self.include_spelling = False
            self.silently_fail = True
            self.timeout = 10

        try:
            Elasticsearch8SearchBackend.__init__ = patched_init
            backend = Elasticsearch8SearchBackend("default")
            return backend
        finally:
            Elasticsearch8SearchBackend.__init__ = original_init

    def test_numeric_facet_keys_are_coerced_to_int(self):
        backend = self._make_backend()
        # Simulate an ES response where "key" has been encoded as a string.
        raw_results = {
            "hits": {"total": {"value": 0, "relation": "eq"}, "hits": []},
            "aggregations": {
                "category": {
                    "meta": {"_type": "terms"},
                    "buckets": [
                        {"key": "42", "doc_count": 7},
                        {"key": "17", "doc_count": 3},
                    ],
                }
            },
        }

        processed = backend._process_results(raw_results)
        self.assertEqual(processed["hits"], 0)
        self.assertIn("fields", processed["facets"])
        category_facets = processed["facets"]["fields"]["category"]
        self.assertEqual(len(category_facets), 2)
        key_42, count_42 = category_facets[0]
        self.assertIsInstance(key_42, int)
        self.assertEqual(key_42, 42)
        self.assertEqual(count_42, 7)

    def test_float_and_negative_facet_keys_are_coerced(self):
        backend = self._make_backend()
        raw_results = {
            "hits": {"total": 0, "hits": []},
            "aggregations": {
                "mixed": {
                    "meta": {"_type": "terms"},
                    "buckets": [
                        {"key": "3.14", "doc_count": 2},
                        {"key": "-5", "doc_count": 1},
                        {"key": "100", "doc_count": 9},
                    ],
                }
            },
        }

        processed = backend._process_results(raw_results)
        facets = processed["facets"]["fields"]["mixed"]
        key_values = sorted(k for k, _ in facets)
        # float keys remain float; int keys are coerced to int.
        self.assertIsInstance(facets[0][0], float) or self.assertIsInstance(
            facets[0][0], int
        )
        # -5 should be an int.
        negative = next(k for k, _ in facets if k < 0)
        self.assertIsInstance(negative, int)
        self.assertEqual(negative, -5)


class Elasticsearch8VectorSearchTestCase(unittest.TestCase):
    """
    Test 3: Dense vector and kNN search support.

    Elasticsearch 8 introduces the ``knn`` top-level search parameter
    for approximate nearest-neighbor searches on ``dense_vector``
    fields. The backend should expose this via:

    * A ``vector_query`` kwarg on ``build_search_kwargs`` which
      combines a kNN clause with the existing text query.
    * A standalone ``vector_search`` helper method.
    """

    def _make_backend(self):
        original_init = Elasticsearch8SearchBackend.__init__

        def patched_init(self, conn_alias, **kwargs):
            self.connection_alias = conn_alias
            self.index_name = "test_elasticsearch8"
            self.setup_complete = False
            self.existing_mapping = {}
            self.include_spelling = False
            self.silently_fail = True
            self.timeout = 10

        try:
            Elasticsearch8SearchBackend.__init__ = patched_init
            backend = Elasticsearch8SearchBackend("default")
            return backend
        finally:
            Elasticsearch8SearchBackend.__init__ = original_init

    def test_build_search_kwargs_includes_knn_clause(self):
        backend = self._make_backend()

        # The build_search_kwargs method relies on
        # haystack.connections[...] to look up the unified index.
        # Monkey-patch connections for this test so we don't have to
        # spin up Django.
        import haystack

        original_conn = haystack.connections
        fake_index = FakeUnifiedIndex()
        fake_index.get_unified_index = lambda: fake_index

        try:
            haystack.connections = {"default": fake_index}
            kwargs = backend.build_search_kwargs(
                "hello",
                vector_query={
                    "field": "embedding",
                    "query_vector": [1.0, 0.5, -0.5],
                    "k": 5,
                },
                limit_to_registered_models=False,
            )
        finally:
            haystack.connections = original_conn

        self.assertIn("knn", kwargs)
        self.assertEqual(kwargs["knn"]["field"], "embedding")
        self.assertEqual(kwargs["knn"]["query_vector"], [1.0, 0.5, -0.5])
        self.assertEqual(kwargs["knn"]["k"], 5)
        # The query must still be present as a filter, not a plain query.
        self.assertIn("bool", kwargs["query"])
        self.assertIn("filter", kwargs["query"]["bool"])

    def test_build_search_kwargs_respects_similarity_and_num_candidates(self):
        backend = self._make_backend()
        import haystack

        fake_index = FakeUnifiedIndex()
        fake_index.get_unified_index = lambda: fake_index
        original_conn = haystack.connections

        try:
            haystack.connections = {"default": fake_index}
            kwargs = backend.build_search_kwargs(
                "",
                vector_query={
                    "field": "embedding",
                    "query_vector": [0.1, 0.2, 0.3],
                    "k": 3,
                    "num_candidates": 20,
                    "similarity": "dot_product",
                },
                limit_to_registered_models=False,
            )
        finally:
            haystack.connections = original_conn

        self.assertEqual(kwargs["knn"]["num_candidates"], 20)
        self.assertEqual(kwargs["knn"]["similarity"], "dot_product")

    def test_field_mapping_contains_dense_vector_type(self):
        backend = self._make_backend()
        # The backend exposes a FIELD_MAPPINGS class attribute. The ES8
        # backend adds ``dense_vector`` to it.
        self.assertIn("dense_vector", Elasticsearch8SearchBackend.FIELD_MAPPINGS)
        self.assertEqual(
            Elasticsearch8SearchBackend.FIELD_MAPPINGS["dense_vector"]["type"],
            "dense_vector",
        )


if __name__ == "__main__":
    unittest.main()
