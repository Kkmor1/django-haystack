# "Hey, Django! Look at me, I'm an app! For Serious!"
from django.core.exceptions import ObjectDoesNotExist
from django.utils.encoding import force_str
from django.utils.text import capfirst

from haystack.constants import DEFAULT_ALIAS
from haystack.exceptions import NotHandled, SpatialError
from haystack.utils import log as logging
from haystack.utils.app_loading import haystack_get_model

try:
    from geopy import distance as geopy_distance
except ImportError:
    geopy_distance = None


# Not a Django model, but tightly tied to them and there doesn't seem to be a
# better spot in the tree.
class SearchResult:
    """
    A single search result. The actual object is loaded lazily by accessing
    object; until then this object only stores the model, pk, and score.

    ``SearchResult`` supports bulk pre-population. When the same result set
    has been batch-loaded via ``SearchQuerySet.load_all()``, the ``object``
    property will use the shared in-memory cache instead of issuing a
    per-result database query. A single result never knows whether it has
    been bulk-loaded; it simply checks the cache first and falls back to the
    lazy one-by-one lookup otherwise.
    """

    # Class-level registry of bulk-loaded objects. Keys are
    # ``(app_label, model_name, pk)`` tuples. The design deliberately uses a
    # class-level dict (not an instance attribute) so that any ``SearchResult``
    # instance - regardless of where it was created - can benefit from a
    # pre-populated cache without passing references around.
    _bulk_cache = {}

    def __init__(self, app_label, model_name, pk, score, **kwargs):
        self.app_label, self.model_name = app_label, model_name
        self.pk = pk
        self.score = score
        self._object = None
        self._model = None
        self._verbose_name = None
        self._additional_fields = []
        self._point_of_origin = kwargs.pop("_point_of_origin", None)
        self._distance = kwargs.pop("_distance", None)
        self.stored_fields = None
        self.log = self._get_log()

        for key, value in kwargs.items():
            if key not in self.__dict__:
                self.__dict__[key] = value
                self._additional_fields.append(key)

    def _get_log(self):
        return logging.getLogger("haystack")

    def __repr__(self):
        return "<SearchResult: %s.%s (pk=%r)>" % (
            self.app_label,
            self.model_name,
            self.pk,
        )

    def __str__(self):
        return force_str(self.__repr__())

    def __getattr__(self, attr):
        if attr == "__getnewargs__":
            raise AttributeError

        return self.__dict__.get(attr, None)

    def _get_searchindex(self):
        from haystack import connections

        return connections[DEFAULT_ALIAS].get_unified_index().get_index(self.model)

    searchindex = property(_get_searchindex)

    def _cache_key(self):
        """
        Build a hashable key for this result in the shared bulk cache.

        The primary key is coerced to a string when used as a cache key
        because PKs may arrive as ``int``, ``str``, ``UUID`` or custom
        objects, but must be comparable against keys populated by the bulk
        loader (which always uses the model's native PK type after
        conversion). Stringification keeps comparisons stable and cheap.
        """
        return (self.app_label, self.model_name, str(self.pk))

    def _get_object(self):
        """
        Return the ORM object corresponding to this search result.

        Lazy loading semantics are preserved: no database query is issued
        until this property is accessed. If the result has been
        batch-preloaded by a ``SearchQuerySet.load_all()`` call, the cached
        object is returned without hitting the database.
        """
        if self._object is not None:
            return self._object

        if self.model is None:
            self.log.error("Model could not be found for SearchResult '%s'.", self)
            return None

        # 1) Try the shared bulk cache first. The cache key is stable across
        #    calls because it only depends on immutable metadata
        #    (app_label/model_name/pk).
        cache_key = self._cache_key()
        if cache_key in self._bulk_cache:
            cached = self._bulk_cache[cache_key]
            # ``False`` is a sentinel meaning "we tried to load and the object
            # no longer exists". Return ``None`` (same as the lazy path) but
            # avoid re-querying.
            if cached is False:
                return None
            self._object = cached
            return self._object

        # 2) Fall back to the classic lazy one-object-at-a-time lookup.
        try:
            try:
                self._object = self.searchindex.read_queryset().get(pk=self.pk)
            except NotHandled:
                self.log.warning(
                    "Model '%s.%s' not handled by the routers.",
                    self.app_label,
                    self.model_name,
                )
                # Revert to old behaviour
                self._object = self.model._default_manager.get(pk=self.pk)
        except ObjectDoesNotExist:
            self.log.error(
                "Object could not be found in database for SearchResult '%s'.", self
            )
            self._object = None

        return self._object

    def _set_object(self, obj):
        self._object = obj

    object = property(_get_object, _set_object)  # noqa A003

    def _get_model(self):
        if self._model is None:
            try:
                self._model = haystack_get_model(self.app_label, self.model_name)
            except LookupError:
                # this changed in change 1.7 to throw an error instead of
                # returning None when the model isn't found. So catch the
                # lookup error and keep self._model == None.
                pass

        return self._model

    def _set_model(self, obj):
        self._model = obj

    model = property(_get_model, _set_model)

    def _get_distance(self):
        from django.contrib.gis.measure import Distance

        if self._distance is None:
            # We didn't get it from the backend & we haven't tried calculating
            # it yet. Check if geopy is available to do it the "slow" way
            # (even though slow meant 100 distance calculations in 0.004 seconds
            # in my testing).
            if geopy_distance is None:
                raise SpatialError(
                    "The backend doesn't have 'DISTANCE_AVAILABLE' enabled & the 'geopy' library could not be imported, so distance information is not available."
                )

            if not self._point_of_origin:
                raise SpatialError("The original point is not available.")

            if not hasattr(self, self._point_of_origin["field"]):
                raise SpatialError(
                    "The field '%s' was not included in search results, so the distance could not be calculated."
                    % self._point_of_origin["field"]
                )

            po_lng, po_lat = self._point_of_origin["point"].coords
            location_field = getattr(self, self._point_of_origin["field"])

            if location_field is None:
                return None

            lf_lng, lf_lat = location_field.coords
            self._distance = Distance(
                km=geopy_distance.distance((po_lat, po_lng), (lf_lat, lf_lng)).km
            )

        # We've either already calculated it or the backend returned it, so
        # let's use that.
        return self._distance

    def _set_distance(self, dist):
        self._distance = dist

    distance = property(_get_distance, _set_distance)

    def _get_verbose_name(self):
        if self.model is None:
            self.log.error("Model could not be found for SearchResult '%s'.", self)
            return ""

        return force_str(capfirst(self.model._meta.verbose_name))

    verbose_name = property(_get_verbose_name)

    def _get_verbose_name_plural(self):
        if self.model is None:
            self.log.error("Model could not be found for SearchResult '%s'.", self)
            return ""

        return force_str(capfirst(self.model._meta.verbose_name_plural))

    verbose_name_plural = property(_get_verbose_name_plural)

    def content_type(self):
        """Returns the content type for the result's model instance."""
        if self.model is None:
            self.log.error("Model could not be found for SearchResult '%s'.", self)
            return ""

        return str(self.model._meta)

    def get_additional_fields(self):
        """
        Returns a dictionary of all of the fields from the raw result.

        Useful for serializing results. Only returns what was seen from the
        search engine, so it may have extra fields Haystack's indexes aren't
        aware of.
        """
        additional_fields = {}

        for fieldname in self._additional_fields:
            additional_fields[fieldname] = getattr(self, fieldname)

        return additional_fields

    def get_stored_fields(self):
        """
        Returns a dictionary of all of the stored fields from the SearchIndex.

        Useful for serializing results. Only returns the fields Haystack's
        indexes are aware of as being 'stored'.
        """
        if self._stored_fields is None:
            from haystack import connections

            try:
                index = (
                    connections[DEFAULT_ALIAS].get_unified_index().get_index(self.model)
                )
            except NotHandled:
                # Not found? Return nothing.
                return {}

            self._stored_fields = {}

            # Iterate through the index's fields, pulling out the fields that
            # are stored.
            for fieldname, field in index.fields.items():
                if field.stored is True:
                    self._stored_fields[fieldname] = getattr(self, fieldname, "")

        return self._stored_fields

    def __getstate__(self):
        """
        Returns a dictionary representing the ``SearchResult`` in order to
        make it pickleable.
        """
        # The ``log`` is excluded because, under the hood, ``logging`` uses
        # ``threading.Lock``, which doesn't pickle well.
        ret_dict = self.__dict__.copy()
        del ret_dict["log"]
        return ret_dict

    def __setstate__(self, data_dict):
        """
        Updates the object's attributes according to data passed by pickle.
        """
        self.__dict__.update(data_dict)
        self.log = self._get_log()

    # --- Bulk-cache public helpers -------------------------------------------
    #
    # These methods are the single authoritative API for populating and
    # clearing the class-level bulk cache. Callers (``SearchQuerySet``) use
    # them; individual ``SearchResult`` instances only ever read via
    # ``_get_object``.

    @classmethod
    def bulk_populate(cls, objects_by_model):
        """
        Register a mapping of ``{model: {pk: instance}}`` into the shared
        cache. ``objects_by_model`` may be partial; missing pks will simply
        fall through to the lazy lookup path.

        The caller is responsible for normalizing PKs to the model's native
        type (see ``SearchQuerySet.post_process_results``).
        """
        for model, pk_map in objects_by_model.items():
            if not pk_map:
                continue
            app_label = model._meta.app_label
            model_name = model._meta.model_name
            for pk, obj in pk_map.items():
                cls._bulk_cache[(app_label, model_name, str(pk))] = obj

    @classmethod
    def bulk_mark_missing(cls, model, pks):
        """
        Mark a set of PKs for a model as "known missing" so the lazy path
        does not re-query the database for them.
        """
        app_label = model._meta.app_label
        model_name = model._meta.model_name
        for pk in pks:
            cls._bulk_cache[(app_label, model_name, str(pk))] = False

    @classmethod
    def bulk_clear(cls, models=None):
        """
        Clear the shared bulk cache.

        ``models`` is an optional iterable of model classes. When provided,
        only entries for those models are removed; otherwise the entire
        cache is cleared.
        """
        if models is None:
            cls._bulk_cache.clear()
            return

        keys_to_drop = set()
        for model in models:
            app_label = model._meta.app_label
            model_name = model._meta.model_name
            for key in cls._bulk_cache:
                if key[0] == app_label and key[1] == model_name:
                    keys_to_drop.add(key)
        for key in keys_to_drop:
            del cls._bulk_cache[key]


def reload_indexes(sender, *args, **kwargs):
    from haystack import connections

    for conn in connections.all():
        ui = conn.get_unified_index()
        # Note: Unlike above, we're resetting the ``UnifiedIndex`` here.
        # Thi gives us a clean slate.
        ui.reset()
