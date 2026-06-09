"""
Refactor tests for ``haystack/query.py`` & ``haystack/models.py``.

These tests exercise the two key behavioural guarantees of the
refactor:

* ``SearchQuerySet.load_all()`` pre-loads every ORM object with a
  *constant* number of SQL queries (one ``in_bulk()`` call per model,
  plus one per ``prefetch_related`` lookup), regardless of the number
  of search results.
* ``SearchResult.object`` still behaves lazily when ``load_all()`` was
  *not* used - i.e. the public API is unchanged.
* Multi-model searches, non-integer PKs and ``select_related`` /
  ``prefetch_related`` all round-trip correctly.
"""
