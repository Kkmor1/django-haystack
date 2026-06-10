from django.test import TestCase

from haystack.signals import RealtimeSignalProcessor
from test_haystack.core.models import MockModel, MockTag


class FakeUnifiedIndex:
    def __init__(self, indexed_models):
        self.indexed_models = indexed_models

    def get_indexed_models(self):
        return self.indexed_models


class FakeConnection:
    def __init__(self, indexed_models):
        self.unified_index = FakeUnifiedIndex(indexed_models)

    def get_unified_index(self):
        return self.unified_index


class FakeConnections:
    def __init__(self, *connections):
        self.connections = connections

    def all(self):
        return self.connections


class RecordingRealtimeSignalProcessor(RealtimeSignalProcessor):
    def __init__(self, *args, **kwargs):
        self.saved_instances = []
        self.deleted_instances = []
        super().__init__(*args, **kwargs)

    def handle_save(self, sender, instance, **kwargs):
        self.saved_instances.append((sender, instance.pk))

    def handle_delete(self, sender, instance, **kwargs):
        self.deleted_instances.append((sender, instance.pk))


class RealtimeSignalProcessorRegistrationTestCase(TestCase):
    def setUp(self):
        super().setUp()
        self.signal_processor = RecordingRealtimeSignalProcessor(
            FakeConnections(
                FakeConnection([MockModel]),
                FakeConnection([MockModel]),
            ),
            None,
        )
        self.tag = MockTag.objects.create(name="indexed-tag")

    def tearDown(self):
        self.signal_processor.teardown()
        super().tearDown()

    def test_only_indexed_models_trigger_signal_handlers(self):
        indexed_instance = MockModel.objects.create(
            author="indexed",
            foo="tracked",
            tag=self.tag,
        )
        unindexed_instance = MockTag.objects.create(name="unindexed-tag")

        self.assertEqual(self.signal_processor.saved_instances, [(MockModel, indexed_instance.pk)])

        indexed_instance.delete()
        unindexed_instance.delete()

        self.assertEqual(
            self.signal_processor.deleted_instances,
            [(MockModel, indexed_instance.pk)],
        )
