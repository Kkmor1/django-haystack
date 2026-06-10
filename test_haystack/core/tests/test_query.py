import os
import django
from django.test import TestCase
from haystack.query import SearchQuerySet
from test_haystack.core.models import MockModel, AnotherMockModel, MockTag
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.core.management import call_command
from haystack import connections

class LazyLoadAllTestCase(TestCase):
    def setUp(self):
        super().setUp()
        MockTag.objects.all().delete()
        MockModel.objects.all().delete()
        AnotherMockModel.objects.all().delete()
        
        self.tag1 = MockTag.objects.create(name="tag1")
        self.tag2 = MockTag.objects.create(name="tag2")
        
        MockModel.objects.create(author="daniel1", pub_date="2010-01-01 00:00:00", tag=self.tag1)
        MockModel.objects.create(author="daniel2", pub_date="2010-01-01 00:00:00", tag=self.tag2)
        AnotherMockModel.objects.create(author="daniel3", pub_date="2010-01-01 00:00:00")
        AnotherMockModel.objects.create(author="daniel4", pub_date="2010-01-01 00:00:00")
        
        backend = connections["default"].get_backend()
        backend.clear()
        
        # update index
        from test_haystack.test_views import BasicMockModelSearchIndex, BasicAnotherMockModelSearchIndex
        from haystack.utils.loading import UnifiedIndex
        
        self.old_unified_index = connections["default"]._index
        self.ui = UnifiedIndex()
        self.bmmsi = BasicMockModelSearchIndex()
        self.bamsi = BasicAnotherMockModelSearchIndex()
        self.ui.build(indexes=[self.bmmsi, self.bamsi])
        connections["default"]._index = self.ui
        
        backend.update(self.bmmsi, MockModel.objects.all())
        backend.update(self.bamsi, AnotherMockModel.objects.all())

    def tearDown(self):
        connections["default"]._index = self.old_unified_index
        super().tearDown()

    def test_load_all_executes_one_query_per_model(self):
        sqs = SearchQuerySet().models(MockModel).load_all()
        # Evaluate to fetch from backend
        results = list(sqs)
        self.assertEqual(len(results), 2)
        
        # Accessing .object should trigger only 1 query for all 2 results
        with CaptureQueriesContext(connection) as captured_queries:
            for result in results:
                _ = result.object
                
        # Only 1 query to fetch the MockModels
        self.assertEqual(len(captured_queries), 1)

    def test_load_all_multi_model(self):
        sqs = SearchQuerySet().models(MockModel, AnotherMockModel).load_all()
        results = list(sqs)
        self.assertEqual(len(results), 4)
        
        # Accessing .object should trigger 1 query per model -> 2 queries total
        with CaptureQueriesContext(connection) as captured_queries:
            for result in results:
                _ = result.object
                
        # 1 query for MockModel, 1 query for AnotherMockModel
        self.assertEqual(len(captured_queries), 2)
        
    def test_load_all_select_related(self):
        sqs = SearchQuerySet().models(MockModel).load_all().select_related('tag')
        results = list(sqs)
        self.assertEqual(len(results), 2)
        
        # Accessing .object should trigger 1 query to fetch MockModel and join MockTag
        with CaptureQueriesContext(connection) as captured_queries:
            for result in results:
                obj = result.object
                if obj and hasattr(obj, 'tag'):
                    _ = obj.tag.name # Should not trigger query if select_related worked
                    
        self.assertEqual(len(captured_queries), 1)
