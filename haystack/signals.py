from django.db import models

from haystack.exceptions import NotHandled


class BaseSignalProcessor:
    """
    A convenient way to attach Haystack to Django's signals & cause things to
    index.

    By default, does nothing with signals but provides underlying functionality.
    """

    def __init__(self, connections, connection_router):
        self.connections = connections
        self.connection_router = connection_router
        self.setup()

    def setup(self):
        """
        A hook for setting up anything necessary for
        ``handle_save/handle_delete`` to be executed.

        Default behavior is to do nothing (``pass``).
        """
        # Do nothing.
        pass

    def teardown(self):
        """
        A hook for tearing down anything necessary for
        ``handle_save/handle_delete`` to no longer be executed.

        Default behavior is to do nothing (``pass``).
        """
        # Do nothing.
        pass

    def handle_save(self, sender, instance, **kwargs):
        """
        Given an individual model instance, determine which backends the
        update should be sent to & update the object on those backends.
        """
        using_backends = self.connection_router.for_write(instance=instance)

        for using in using_backends:
            try:
                index = self.connections[using].get_unified_index().get_index(sender)
                index.update_object(instance, using=using)
            except NotHandled:
                # TODO: Maybe log it or let the exception bubble?
                pass

    def handle_delete(self, sender, instance, **kwargs):
        """
        Given an individual model instance, determine which backends the
        delete should be sent to & delete the object on those backends.
        """
        using_backends = self.connection_router.for_write(instance=instance)

        for using in using_backends:
            try:
                index = self.connections[using].get_unified_index().get_index(sender)
                index.remove_object(instance, using=using)
            except NotHandled:
                # TODO: Maybe log it or let the exception bubble?
                pass


class RealtimeSignalProcessor(BaseSignalProcessor):
    """
    Allows for observing when saves/deletes fire & automatically updates the
    search engine appropriately.
    """

    def _get_indexed_models(self):
        indexed_models = []

        for connection in self.connections.all():
            indexed_models.extend(connection.get_unified_index().get_indexed_models())

        return list(dict.fromkeys(indexed_models))

    def setup(self):
        self.indexed_models = self._get_indexed_models()

        for model_class in self.indexed_models:
            models.signals.post_save.connect(self.handle_save, sender=model_class)
            models.signals.post_delete.connect(self.handle_delete, sender=model_class)

    def teardown(self):
        for model_class in getattr(self, "indexed_models", self._get_indexed_models()):
            models.signals.post_save.disconnect(self.handle_save, sender=model_class)
            models.signals.post_delete.disconnect(self.handle_delete, sender=model_class)
