.. _ref-backend-support:

===============
Backend Support
===============


Supported Backends
==================

* Solr_
* ElasticSearch_
* Whoosh_
* Xapian_
* `PostgreSQL Full Text Search`_

.. _Solr: http://lucene.apache.org/solr/
.. _ElasticSearch: http://elasticsearch.org/
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

ElasticSearch
-------------

**Complete & included with Haystack.**

* Full SearchQuerySet support
* Automatic query building
* "More Like This" functionality
* Term Boosting
* Faceting (up to 100 facets)
* Stored (non-indexed) fields
* Highlighting
* Spatial search
* Requires: `elasticsearch-py <https://pypi.python.org/pypi/elasticsearch>`_ 1.x, 2.x, 5.X, 7.X, or 8.X.

ElasticSearch 8.x
-----------------

**Complete & included with Haystack.**

ElasticSearch 8.x backend is a from-scratch implementation that directly inherits from
``BaseSearchBackend`` and ``BaseSearchQuery``. It supports all features of the ES 7.x backend
plus the following ES 8.x specific features:

* Full SearchQuerySet support
* Automatic query building
* "More Like This" functionality
* Term Boosting
* Faceting with proper type preservation (numeric facet values remain numeric, not strings)
* Stored (non-indexed) fields
* Highlighting
* Spatial search (geo_point, geo_distance, geo_bounding_box)
* **Dense Vector Search**: Native support for ``dense_vector`` field type with kNN similarity search
* No doc_type dependency (ES 8.x removed doc_type support entirely)
* Requires: `elasticsearch-py <https://pypi.python.org/pypi/elasticsearch>`_ 8.x

Configuration
~~~~~~~~~~~~~

Add the following to your Django settings::

    HAYSTACK_CONNECTIONS = {
        'default': {
            'ENGINE': 'haystack.backends.elasticsearch8_backend.Elasticsearch8SearchEngine',
            'URL': 'http://localhost:9200/',
            'INDEX_NAME': 'haystack',
        },
    }

Vector Search
~~~~~~~~~~~~~

ES8 backend supports dense vector fields for semantic search. Define a vector field in your
SearchIndex::

    from haystack import indexes

    class DocumentIndex(indexes.SearchIndex, indexes.Indexable):
        text = indexes.CharField(document=True, use_template=True)
        embedding = indexes.VectorField(dims=384, similarity='cosine')

        def prepare_embedding(self, obj):
            return get_embedding(obj.text)

Then perform vector similarity search::

    from haystack.connections import get_connection

    backend = get_connection('default').get_backend()
    results = backend.vector_search('embedding', query_vector, k=10)

Numeric Facet Bug Fix
~~~~~~~~~~~~~~~~~~~~~

The ES8 backend fixes a bug present in earlier ES backends where numeric type facet results
were returned as strings. In ES8, facet values maintain their original numeric types (int, float)
through proper handling of Elasticsearch aggregations.

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
| ElasticSearch  | Yes                    | Yes                 | Yes            | Yes        | Yes         | Yes           | Yes          | Yes     |
+----------------+------------------------+---------------------+----------------+------------+-------------+---------------+--------------+---------+
| ElasticSearch8 | Yes                    | Yes                 | Yes            | Yes        | Yes         | Yes           | Yes          | Yes     |
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
