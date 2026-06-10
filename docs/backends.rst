Backends
========

Elasticsearch 8.x
-----------------

Haystack includes an Elasticsearch 8 backend at
``haystack.backends.elasticsearch8_backend.Elasticsearch8SearchEngine``.

Installation
~~~~~~~~~~~~

Install the backend dependency group:

::

    pip install ".[elasticsearch8]"

You can also install the client directly:

::

    pip install "elasticsearch>=8,<9"

Basic Configuration
~~~~~~~~~~~~~~~~~~~

Set the Haystack connection to the Elasticsearch 8 backend:

::

    HAYSTACK_CONNECTIONS = {
        "default": {
            "ENGINE": "haystack.backends.elasticsearch8_backend.Elasticsearch8SearchEngine",
            "URL": "http://127.0.0.1:9200/",
            "INDEX_NAME": "haystack",
        },
    }

Supported connection options:

- ``URL``: Elasticsearch node URL.
- ``INDEX_NAME``: target index name.
- ``TIMEOUT``: request timeout in seconds.
- ``BATCH_SIZE``: batch size used by Haystack indexing.
- ``INCLUDE_SPELLING``: enables term suggestions.
- ``SILENTLY_FAIL``: controls whether transport and API errors are swallowed.
- ``KWARGS``: extra keyword arguments passed to ``elasticsearch.Elasticsearch(...)``.

Common examples for ``KWARGS`` include ``basic_auth``, ``api_key``,
``verify_certs`` and ``ca_certs``.

Feature Support
~~~~~~~~~~~~~~~

The Elasticsearch 8 backend supports the standard SearchQuerySet API,
including:

- indexing, updating and deleting indexed documents
- clearing whole indexes or only selected models
- filtering and ordering
- highlighting
- field, date and query facets
- spelling suggestions
- More Like This queries
- bounding-box and radius-based spatial search
- distance sorting
- raw queries
- dense vector mapping and vector similarity search

Elasticsearch 8 Mapping Notes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Elasticsearch 8 removed ``doc_type``. The backend writes mappings directly to
``mappings.properties`` and never sends ``doc_type`` in CRUD or query calls.

Standard Haystack fields are mapped to Elasticsearch 8 field types. Text fields
use ``text`` mappings, faceted text fields use ``keyword``, location fields use
``geo_point``, and numeric/date fields use native numeric/date mappings.

The backend also converts facet bucket keys back into Haystack field values.
This fixes the long-standing issue where numeric facet buckets could be exposed
as strings instead of Python numeric values.

Dense Vector Fields
~~~~~~~~~~~~~~~~~~~

Haystack does not ship a built-in vector field class, but the Elasticsearch 8
backend supports custom fields whose ``field_type`` is ``"dense_vector"``.
The field must expose either ``dims`` or ``dimension`` so the backend can build
an Elasticsearch mapping.

Example custom field:

.. code-block:: python

    from haystack import fields


    class DenseVectorField(fields.SearchField):
        field_type = "dense_vector"

        def __init__(self, dims, similarity="cosine", index=True, **kwargs):
            super().__init__(**kwargs)
            self.dims = dims
            self.similarity = similarity
            self.index = index

        def prepare(self, obj):
            return getattr(obj, self.model_attr)

Example SearchIndex:

.. code-block:: python

    from haystack import indexes
    from path.to.fields import DenseVectorField
    from app.models import Document


    class DocumentIndex(indexes.SearchIndex, indexes.Indexable):
        text = indexes.CharField(document=True, use_template=True)
        embedding = DenseVectorField(model_attr="embedding", dims=384)

        def get_model(self):
            return Document

Vector Similarity Search
~~~~~~~~~~~~~~~~~~~~~~~~

Use ``raw_search`` and pass ``vector_query`` through to the backend:

.. code-block:: python

    from haystack.query import SearchQuerySet


    results = SearchQuerySet().raw_search(
        "*:*",
        vector_query={
            "field": "embedding",
            "vector": [0.12, 0.98, 0.44],
            "k": 10,
            "num_candidates": 100,
        },
    )

The default mode uses Elasticsearch 8 native kNN search. Supported keys are:

- ``field``: vector field name.
- ``vector`` or ``query_vector``: query embedding.
- ``k``: number of hits to return.
- ``num_candidates``: candidate pool for native kNN.
- ``boost``: optional kNN boost.
- ``similarity``: optional native kNN similarity threshold.
- ``mode``: ``"knn"`` or ``"script_score"``.

For exact vector scoring, switch to ``script_score`` mode:

.. code-block:: python

    results = SearchQuerySet().raw_search(
        "*:*",
        vector_query={
            "mode": "script_score",
            "field": "embedding",
            "vector": [0.12, 0.98, 0.44],
            "similarity": "cosine",
        },
    )

Supported ``script_score`` similarities are ``cosine``, ``dot_product``,
``max_inner_product`` and ``l2_norm``.

Highlighting
~~~~~~~~~~~~

Highlighting uses the normal SearchQuerySet API:

.. code-block:: python

    sqs = SearchQuerySet().filter(content="example").highlight()

Highlighted fragments are exposed on ``result.highlighted``.

Faceting
~~~~~~~~

Field, date and query facets work through the standard SearchQuerySet methods:

.. code-block:: python

    sqs = (
        SearchQuerySet()
        .filter(content="search")
        .facet("author")
        .date_facet("pub_date", start_date, end_date, "month")
        .query_facet("author", "author:daniel")
    )

Facet buckets are returned via ``sqs.facet_counts()``.

More Like This
~~~~~~~~~~~~~~

Use the standard Haystack API:

.. code-block:: python

    related = SearchQuerySet().more_like_this(obj)

The backend uses Elasticsearch 8 ``more_like_this`` queries and still applies
Haystack model restrictions.

Spatial Search
~~~~~~~~~~~~~~

Bounding-box and distance queries are supported through the normal API:

.. code-block:: python

    from haystack.query import SearchQuerySet


    sqs = SearchQuerySet().within("location", point_1, point_2)
    sqs = SearchQuerySet().dwithin("location", point, distance)
    sqs = SearchQuerySet().distance("location", point).order_by("distance")

Operational Notes
~~~~~~~~~~~~~~~~~

- The backend recreates mappings with Elasticsearch 8 style ``mappings.properties``.
- Bulk indexing uses the official Elasticsearch helpers.
- ``clear(models=[...])`` removes only the matching model documents.
- ``SearchQuerySet.raw_search`` is the recommended entry point for advanced
  Elasticsearch-specific features such as vector search.
