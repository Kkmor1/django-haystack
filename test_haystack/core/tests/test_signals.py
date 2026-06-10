from unittest.mock import patch

from django.db import models
from django.test import TestCase

from haystack import connection_router, connections
from haystack.signals import RealtimeSignalProcessor
from test_haystack.core.models import MockModel
from test_haystack.discovery.models import Foo


class RealtimeSignalProcessorTestCase(TestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sp = RealtimeSignalProcessor(connections, connection_router)

    @classmethod
    def tearDownClass(cls):
        cls.sp.teardown()
        super().tearDownClass()

    def test_signals_only_connected_for_indexed_models(self):
        indexed_models = set()
        for conn in connections.all():
            ui = conn.get_unified_index()
            for model in ui.get_indexed_models():
                indexed_models.add(model)

        self.assertIn(Foo, indexed_models)
        self.assertNotIn(MockModel, indexed_models)

        for receiver in models.signals.post_save.receivers:
            recv_func, sender_key = receiver[0], receiver[1]
            if _is_same_handler(recv_func, self.sp.handle_save):
                self.assertIsNotNone(
                    sender_key,
                    "handle_save should be connected with a specific sender",
                )

        for receiver in models.signals.post_delete.receivers:
            recv_func, sender_key = receiver[0], receiver[1]
            if _is_same_handler(recv_func, self.sp.handle_delete):
                self.assertIsNotNone(
                    sender_key,
                    "handle_delete should be connected with a specific sender",
                )

    def test_handle_save_called_for_indexed_model(self):
        with patch.object(
            self.sp, "handle_save", wraps=self.sp.handle_save
        ) as mock_handle_save:
            foo = Foo.objects.create(title="Signal test", body="test body")

            mock_handle_save.assert_called_once()
            args, kwargs = mock_handle_save.call_args
            self.assertIsInstance(args[1], Foo)

    def test_handle_save_not_called_for_non_indexed_model(self):
        with patch.object(
            self.sp, "handle_save", wraps=self.sp.handle_save
        ) as mock_handle_save:
            MockModel.objects.create(author="Test", foo="bar")

            mock_handle_save.assert_not_called()

    def test_handle_delete_called_for_indexed_model(self):
        foo = Foo.objects.create(title="Delete test", body="test body")

        with patch.object(
            self.sp, "handle_delete", wraps=self.sp.handle_delete
        ) as mock_handle_delete:
            foo.delete()

            mock_handle_delete.assert_called_once()
            args, kwargs = mock_handle_delete.call_args
            self.assertIsInstance(args[1], Foo)

    def test_handle_delete_not_called_for_non_indexed_model(self):
        obj = MockModel.objects.create(author="Delete test", foo="bar")

        with patch.object(
            self.sp, "handle_delete", wraps=self.sp.handle_delete
        ) as mock_handle_delete:
            obj.delete()

            mock_handle_delete.assert_not_called()


def _is_same_handler(recv, handler):
    if recv is handler:
        return True
    if hasattr(recv, "__self__") and hasattr(recv, "__func__"):
        return recv.__self__ is handler.__self__ and recv.__func__ is handler.__func__
    return False