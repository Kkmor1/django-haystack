.. _ref-backend-support:

===============
Backend Support
===============


Supported Backends
==================

* Solr_
* Elasticsearch_
* Whoosh_
* Xapian_
* `PostgreSQL Full Text Search`_

.. _Solr: http://lucene.apache.org/solr/
.. _Elasticsearch: https://www.elastic.co/elasticsearch/
.. _Whoosh: https://github.com/whoosh-community/whoosh/
.. _Xapian: http://xapian.org/
.. _PostgreSQL Full Text Search: https://www.postgresql.org/docs/current/textsearch.html

Backend Capabilities
====================

Solr
----

**Complete & included with Haystack.**

* Full SearchQuerySet support
* Automatic query building
* "More Like This" functionality
* Term Boosting
* Faceting
* Stored (non-indexed) fields
* Highlighting
* Spatial search
* Requires: pysolr (2.0.13+) & Solr 3.5+

ElasticSearch (1.x/2.x/5.x/7.x)
-----------------------------------

**Complete & included with Haystack.**

* Full SearchQuerySet support
* Automatic query building
* "More Like This" functionality
* Term Boosting
* Faceting (up to 100 facets)
* Stored (non-indexed) fields
* Highlighting
* Spatial search
* Requires: `elasticsearch-py <https://pypi.python.org/pypi/elasticsearch>`_ 1.x, 2.x, 5.X, or 7.X.

Elasticsearch 8.x
-----------------

**Complete & included with Haystack.**

* Full SearchQuerySet support
* Automatic query building
* "More Like This" functionality
* Term Boosting
* Faceting (numeric types preserved, not returned as strings)
* Stored (non-indexed) fields
* Highlighting
* Spatial search
* Dense vector field support (``dense_vector``) for vector similarity search
* kNN and cosine similarity vector search support
* Requires: `elasticsearch-py <https://pypi.org/project/elasticsearch/>`_ >=8.0.0,<9.0.0

Configuration
`````````````

To use the Elasticsearch 8.x backend, configure your ``HAYSTACK_CONNECTIONS``
setting similar to the following::

    HAYSTACK_CONNECTIONS = {
        'default': {
            'ENGINE': 'haystack.backends.elasticsearch8_backend.Elasticsearch8SearchEngine',
            'URL': 'http://127.0.0.1:9200/',
            'INDEX_NAME': 'haystack',
        },
    }

Install the required package::

    pip install "elasticsearch>=8.0.0,<9.0.0"


Dense Vector / Vector Similarity Search
```````````````````````````````````````

The Elasticsearch 8.x backend supports ``dense_vector`` fields for storing
vector embeddings and performing vector similarity search. This enables
semantic search, recommendation, and other AI-powered search features.

To define a vector field in your ``SearchIndex``::

    from haystack import indexes

    class MySearchIndex(indexes.SearchIndex, indexes.Indexable):
        text = indexes.CharField(document=True, use_template=True)
        embedding = indexes.CharField(field_type='dense_vector')

        def get_model(self):
            return MyModel

        def prepare_embedding(self, obj):
            # Return a list of floats representing the embedding vector
            return your_embedding_function(obj.text)

The default vector dimension is 768. You can customize the dimension by
passing dimensions via the ``DEFAULT_SETTINGS`` when subclassing the backend,
or by using the standard Haystack field weight mechanism.

To perform a vector similarity search, pass a ``vector_query`` parameter::

    from haystack.query import SearchQuerySet

    results = SearchQuerySet().vector_query(
        query_vector=[0.1, 0.2, ...],  # your embedding vector
        field='embedding',              # optional, defaults to text_vector
        k=10,                           # optional, number of results
        num_candidates=100,             # optional, for kNN accuracy
    )

Key Differences from Elasticsearch 7.x Backend
``````````````````````````````````````````````

1. **No doc_type**: Elasticsearch 8.x removed mapping types entirely. The
   backend no longer includes ``doc_type`` in any API calls.

2. **Numeric facet values preserved**: Facet results for numeric fields
   (``boolean``, ``float``, ``long``, ``integer``) are now returned with their
   correct Python types instead of always being strings. This fixes a
   longstanding bug present in earlier ES backends.

3. **Dense vector support**: The ``dense_vector`` field type is supported
   for storing and querying vector embeddings.

4. **API compatibility**: Uses the Elasticsearch 8.x client API conventions,
   including changed response structures (e.g. ``hits.total`` is always an
   object with ``value`` and ``relation`` keys).

Whoosh
------

**Complete & included with Haystack.**

* Full SearchQuerySet support
* Automatic query building
* "More Like This" functionality
* Term Boosting
* Stored (non-indexed) fields
* Highlighting
* Faceting (no queries)
* Requires: whoosh (2.0.0+)
* Per-field analyzers

Xapian
------

**Complete & available as a third-party download.**

* Full SearchQuerySet support
* Automatic query building
* "More Like This" functionality
* Term Boosting
* Faceting
* Stored (non-indexed) fields
* Highlighting
* Requires: Xapian 1.0.5+ & python-xapian 1.0.5+
* Backend can be downloaded here: `xapian-haystack <http://github.com/notanumber/xapian-haystack/>`__

PostgreSQL Full Text Search
---------------------------

**Available as a third party download.**

* Full SearchQuerySet support
* Automatic query building
* Term Boosting
* Faceting
* Stored (non-indexed) fields
* Highlighting
* Backend can be downloaded here: `postgres-fts-backend <https://pypi.org/project/postgres-fts-backend/>`__



Backend Support Matrix
======================

+----------------+------------------------+---------------------+----------------+------------+-------------+---------------+--------------+---------+
| Backend        | SearchQuerySet Support | Auto Query Building | More Like This | Term Boost | Faceting    | Stored Fields | Highlighting | Spatial |
+================+========================+=====================+================+============+=============+===============+==============+=========+
| Solr           | Yes                    | Yes                 | Yes            | Yes        | Yes         | Yes           | Yes          | Yes     |
+----------------+------------------------+---------------------+----------------+------------+-------------+---------------+--------------+---------+
| Elasticsearch  | Yes                    | Yes                 | Yes            | Yes        | Yes         | Yes           | Yes          | Yes     |
+----------------+------------------------+---------------------+----------------+------------+-------------+---------------+--------------+---------+
| Elasticsearch 8| Yes                    | Yes                 | Yes            | Yes        | Yes         | Yes           | Yes          | Yes     |
+----------------+------------------------+---------------------+----------------+------------+-------------+---------------+--------------+---------+
| Whoosh         | Yes                    | Yes                 | Yes            | Yes        | Yes (basic) | Yes           | Yes          | No      |
+----------------+------------------------+---------------------+----------------+------------+-------------+---------------+--------------+---------+
| Xapian         | Yes                    | Yes                 | Yes            | Yes        | Yes         | Yes           | Yes (plugin) | No      |
+----------------+------------------------+---------------------+----------------+------------+-------------+---------------+--------------+---------+
| PostgreSQL FTS | Yes                    | Yes                 | No             | Yes        | Yes         | Yes           | Yes (plugin) | No      |
+----------------+------------------------+---------------------+----------------+------------+-------------+---------------+--------------+---------+


Unsupported Backends & Alternatives
===================================

If you have a search engine which you would like to see supported in Haystack, the current recommendation is
to develop a plugin following the lead of `xapian-haystack <https://pypi.python.org/pypi/xapian-haystack>`_ so
that project can be developed and tested independently of the core Haystack release schedule.

Sphinx
------

This backend has been requested multiple times over the years but does not yet have a volunteer maintainer. If
you would like to work on it, please contact the Haystack maintainers so your project can be linked here and,
if desired, added to the `django-haystack <https://github.com/django-haystack/>`_ organization on GitHub.

In the meantime, Sphinx users should consider Jorge C. Leitão's
`django-sphinxql <https://github.com/jorgecarleitao/django-sphinxql>`_ project.
