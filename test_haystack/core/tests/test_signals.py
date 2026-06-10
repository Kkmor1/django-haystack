from django.db import models
from django.test import TestCase

from haystack import connections
from haystack import indexes
from haystack.signals import RealtimeSignalProcessor
from haystack.utils.loading import UnifiedIndex
from test_haystack.core.models import AnotherMockModel, MockModel, MockTag


class MockModelSearchIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True)

    def get_model(self):
        return MockModel


class TrackingRealtimeSignalProcessor(RealtimeSignalProcessor):
    def __init__(self, *args, **kwargs):
        self.handled_saves = []
        self.handled_deletes = []
        super().__init__(*args, **kwargs)

    def handle_save(self, sender, instance, **kwargs):
        self.handled_saves.append((sender, instance))

    def handle_delete(self, sender, instance, **kwargs):
        self.handled_deletes.append((sender, instance))


class RealtimeSignalProcessorTestCase(TestCase):
    def setUp(self):
        self.old_ui = connections["default"]._index
        self.ui = UnifiedIndex()
        self.ui.build(indexes=[MockModelSearchIndex()])
        connections["default"]._index = self.ui

        self.processor = TrackingRealtimeSignalProcessor(
            connections, connections.router
        )

    def tearDown(self):
        self.processor.teardown()
        connections["default"]._index = self.old_ui

    def test_non_indexed_model_save_does_not_trigger_handle_save(self):
        AnotherMockModel.objects.create(author="nobody")

        non_indexed_saves = [
            (s, i) for s, i in self.processor.handled_saves
            if s is AnotherMockModel
        ]
        self.assertEqual(len(non_indexed_saves), 0)

    def test_indexed_model_save_triggers_handle_save(self):
        tag = MockTag.objects.create(name="test")
        obj = MockModel.objects.create(author="someone", foo="bar", tag=tag)

        indexed_saves = [
            (s, i) for s, i in self.processor.handled_saves
            if s is MockModel
        ]
        self.assertEqual(len(indexed_saves), 1)
        self.assertEqual(indexed_saves[0][1], obj)

    def test_non_indexed_model_delete_does_not_trigger_handle_delete(self):
        obj = AnotherMockModel.objects.create(author="nobody")
        self.processor.handled_saves.clear()

        obj.delete()

        non_indexed_deletes = [
            (s, i) for s, i in self.processor.handled_deletes
            if s is AnotherMockModel
        ]
        self.assertEqual(len(non_indexed_deletes), 0)

    def test_indexed_model_delete_triggers_handle_delete(self):
        tag = MockTag.objects.create(name="test")
        obj = MockModel.objects.create(author="someone", foo="bar", tag=tag)
        self.processor.handled_saves.clear()

        obj.delete()

        indexed_deletes = [
            (s, i) for s, i in self.processor.handled_deletes
            if s is MockModel
        ]
        self.assertEqual(len(indexed_deletes), 1)

    def test_teardown_disconnects_signals(self):
        self.processor.teardown()

        tag = MockTag.objects.create(name="test2")
        MockModel.objects.create(author="after_teardown", foo="baz", tag=tag)

        self.assertEqual(len(self.processor.handled_saves), 0)
