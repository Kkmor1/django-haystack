======================================
Elasticsearch 8 Backend Documentation
======================================

The ``elasticsearch8_backend`` provides full support for Elasticsearch 8.x, adapting to its removal of ``doc_type`` and bringing in new features like ``dense_vector`` support for vector similarity search.

Configuration
=============

To use the Elasticsearch 8 backend, first install the ``elasticsearch8`` dependencies:

.. code-block:: bash

    pip install "django-haystack[elasticsearch8]"

Then, update your ``HAYSTACK_CONNECTIONS`` in ``settings.py``:

.. code-block:: python

    HAYSTACK_CONNECTIONS = {
        'default': {
            'ENGINE': 'haystack.backends.elasticsearch8_backend.Elasticsearch8SearchEngine',
            'URL': 'http://127.0.0.1:9200/',
            'INDEX_NAME': 'haystack',
        },
    }

Features Supported
==================

The Elasticsearch 8 backend implements all features of the ``SearchQuerySet`` API:

* Index CRUD (Create, Read, Update, Delete)
* Searching and Querying
* Faceting (including string, date, and query facets)
* Highlighting
* More Like This
* Spatial Search
* **Vector Similarity Search (Dense Vectors)**

Dense Vector Support
====================

A key addition to the ES8 backend is the ability to map and use ``dense_vector`` fields natively. If you have custom search fields configured for vector searches (e.g. ``field_type = "dense_vector"``), the backend will automatically set them up in the Elasticsearch index mapping.

You can configure vector parameters such as dimensions and similarity in your custom field:

.. code-block:: python

    from haystack import indexes

    class DenseVectorField(indexes.SearchField):
        field_type = "dense_vector"
        
        def __init__(self, **kwargs):
            self.dims = kwargs.pop("dims", None)
            self.index = kwargs.pop("index", True)
            self.similarity = kwargs.pop("similarity", "cosine")
            super().__init__(**kwargs)

    class MySearchIndex(indexes.SearchIndex, indexes.Indexable):
        text = indexes.CharField(document=True, use_template=True)
        my_vector = DenseVectorField(dims=512, similarity="cosine")

You can then pass standard ``knn`` parameters into ``extra_kwargs`` via the Haystack SearchQuerySet API:

.. code-block:: python

    from haystack.query import SearchQuerySet

    results = SearchQuerySet().models(MyModel).extra(knn={
        "field": "my_vector",
        "query_vector": [0.1, 0.2, ...],
        "k": 10,
        "num_candidates": 100
    })

Bug Fixes Included
==================

The ES8 backend correctly handles numerical facets by converting the facet keys back into integers or floats automatically, addressing a bug where numeric type facet search results would previously be returned as strings.

Dependencies
============

This backend requires the official ``elasticsearch`` package version 8.x:

* ``elasticsearch>=8.0.0,<9.0.0``
