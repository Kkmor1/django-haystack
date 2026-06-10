import datetime

from django.contrib.gis.measure import D
from django.test import TestCase

from haystack import connections
from haystack.inputs import Exact
from haystack.models import SearchResult
from haystack.query import SQ, SearchQuerySet

from ..core.models import AnotherMockModel, MockModel


class Elasticsearch8SearchQueryTestCase(TestCase):
    def setUp(self):
        super().setUp()
        self.sq = connections["elasticsearch8"].get_query()

    def test_build_query_all(self):
        self.assertEqual(self.sq.build_query(), "*:*")

    def test_build_query_single_word(self):
        self.sq.add_filter(SQ(content="hello"))
        self.assertEqual(self.sq.build_query(), "(hello)")

    def test_build_query_boolean(self):
        self.sq.add_filter(SQ(content=True))
        self.assertEqual(self.sq.build_query(), "(True)")

    def test_regression_slash_search(self):
        self.sq.add_filter(SQ(content="hello/"))
        self.assertEqual(self.sq.build_query(), "(hello\\/)")

    def test_build_query_datetime(self):
        self.sq.add_filter(SQ(content=datetime.datetime(2009, 5, 8, 11, 28)))
        self.assertEqual(self.sq.build_query(), "(2009-05-08T11:28:00)")

    def test_build_query_multiple_words_and(self):
        self.sq.add_filter(SQ(content="hello"))
        self.sq.add_filter(SQ(content="world"))
        self.assertEqual(self.sq.build_query(), "((hello) AND (world))")

    def test_build_query_multiple_words_not(self):
        self.sq.add_filter(~SQ(content="hello"))
        self.sq.add_filter(~SQ(content="world"))
        self.assertEqual(
            self.sq.build_query(), "(NOT ((hello)) AND NOT ((world)))"
        )

    def test_build_query_multiple_words_or(self):
        self.sq.add_filter(~SQ(content="hello"))
        self.sq.add_filter(SQ(content="hello"), use_or=True)
        self.assertEqual(
            self.sq.build_query(), "(NOT ((hello)) OR (hello))"
        )

    def test_build_query_multiple_words_mixed(self):
        self.sq.add_filter(SQ(content="why"))
        self.sq.add_filter(SQ(content="hello"), use_or=True)
        self.sq.add_filter(~SQ(content="world"))
        self.assertEqual(
            self.sq.build_query(),
            "(((why) OR (hello)) AND NOT ((world)))",
        )

    def test_build_query_phrase(self):
        self.sq.add_filter(SQ(content="hello world"))
        self.assertEqual(self.sq.build_query(), "(hello AND world)")

        self.sq.add_filter(SQ(content__exact="hello world"))
        self.assertEqual(
            self.sq.build_query(),
            '((hello AND world) AND ("hello world"))',
        )

    def test_build_query_boost(self):
        self.sq.add_filter(SQ(content="hello"))
        self.sq.add_boost("world", 5)
        self.assertEqual(self.sq.build_query(), "(hello) world^5")

    def test_build_query_multiple_filter_types(self):
        self.sq.add_filter(SQ(content="why"))
        self.sq.add_filter(SQ(pub_date__lte=Exact("2009-02-10 01:59:00")))
        self.sq.add_filter(SQ(author__gt="daniel"))
        self.sq.add_filter(SQ(created__lt=Exact("2009-02-12 12:13:00")))
        self.sq.add_filter(SQ(title__gte="B"))
        self.sq.add_filter(SQ(id__in=[1, 2, 3]))
        self.sq.add_filter(SQ(rating__range=[3, 5]))
        self.assertEqual(
            self.sq.build_query(),
            '((why) AND pub_date:([* TO "2009-02-10 01:59:00"]) '
            'AND author:({"daniel" TO *}) '
            'AND created:({* TO "2009-02-12 12:13:00"}) '
            'AND title:(["B" TO *]) AND id:("1" OR "2" OR "3") '
            'AND rating:(["3" TO "5"]))',
        )

    def test_build_query_multiple_filter_types_with_datetimes(self):
        self.sq.add_filter(SQ(content="why"))
        self.sq.add_filter(
            SQ(pub_date__lte=datetime.datetime(2009, 2, 10, 1, 59, 0))
        )
        self.sq.add_filter(SQ(author__gt="daniel"))
        self.sq.add_filter(
            SQ(created__lt=datetime.datetime(2009, 2, 12, 12, 13, 0))
        )
        self.sq.add_filter(SQ(title__gte="B"))
        self.sq.add_filter(SQ(id__in=[1, 2, 3]))
        self.sq.add_filter(SQ(rating__range=[3, 5]))
        self.assertEqual(
            self.sq.build_query(),
            '((why) AND pub_date:([* TO "2009-02-10T01:59:00"]) '
            'AND author:({"daniel" TO *}) '
            'AND created:({* TO "2009-02-12T12:13:00"}) '
            'AND title:(["B" TO *]) AND id:("1" OR "2" OR "3") '
            'AND rating:(["3" TO "5"]))',
        )