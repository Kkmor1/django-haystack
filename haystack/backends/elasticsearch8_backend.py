import ast
import datetime
import re
import warnings
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

import haystack
from haystack.backends import (
    BaseEngine,
    BaseSearchBackend,
    BaseSearchQuery,
    log_query,
)
from haystack.constants import (
    ALL_FIELD,
    DEFAULT_OPERATOR,
    DJANGO_CT,
    DJANGO_ID,
    FUZZY_MAX_EXPANSIONS,
    FUZZY_MIN_SIM,
    ID,
)
from haystack.exceptions import MissingDependency, MoreLikeThisError, SkipDocument
from haystack.inputs import Clean, Exact, PythonData, Raw
from haystack.models import SearchResult
from haystack.utils import get_identifier, get_model_ct
from haystack.utils import log as logging
from haystack.utils.app_loading import haystack_get_model

try:
    import elasticsearch
    from elasticsearch.exceptions import NotFoundError
    from elasticsearch.helpers import bulk, scan

    if not ((8, 0, 0) <= elasticsearch.__version__ < (9, 0, 0)):
        raise ImportError
except ImportError:
    raise MissingDependency(
        "The 'elasticsearch8' backend requires the installation of "
        "'elasticsearch>=8.0.0,<9.0.0'. Please refer to the documentation."
    )

DATETIME_REGEX = re.compile(
    r"^(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})T"
    r"(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})(\.\d+)?$"
)

class Elasticsearch8SearchBackend(BaseSearchBackend):
    # Word reserved by Elasticsearch for special use.
    RESERVED_WORDS = ("AND", "NOT", "OR", "TO")

    # Characters reserved by Elasticsearch for special use.
    RESERVED_CHARACTERS = (
        "\\", "+", "-", "&&", "||", "!", "(", ")", "{", "}",
        "[", "]", "^", '"', "~", "*", "?", ":", "/",
    )

    DEFAULT_SETTINGS = {
        "settings": {
            "index": {
                "max_ngram_diff": 2,
            },
            "analysis": {
                "analyzer": {
                    "ngram_analyzer": {
                        "tokenizer": "standard",
                        "filter": ["haystack_ngram", "lowercase"],
                    },
                    "edgengram_analyzer": {
                        "tokenizer": "standard",
                        "filter": ["haystack_edgengram", "lowercase"],
                    },
                },
                "filter": {
                    "haystack_ngram": {
                        "type": "ngram",
                        "min_gram": 3,
                        "max_gram": 4,
                    },
                    "haystack_edgengram": {
                        "type": "edge_ngram",
                        "min_gram": 2,
                        "max_gram": 15,
                    },
                },
            }
        }
    }

    DEFAULT_FIELD_MAPPING = {"type": "text", "analyzer": "snowball"}
    FIELD_MAPPINGS = {
        "edge_ngram": {"type": "text", "analyzer": "edgengram_analyzer"},
        "ngram": {"type": "text", "analyzer": "ngram_analyzer"},
        "date": {"type": "date"},
        "datetime": {"type": "date"},
        "location": {"type": "geo_point"},
        "boolean": {"type": "boolean"},
        "float": {"type": "float"},
        "long": {"type": "long"},
        "integer": {"type": "long"},
        "dense_vector": {"type": "dense_vector"},
    }

    def __init__(self, connection_alias, **connection_options):
        super().__init__(connection_alias, **connection_options)

        if "URL" not in connection_options:
            raise ImproperlyConfigured(
                "You must specify a 'URL' in your settings for connection '%s'."
                % connection_alias
            )

        if "INDEX_NAME" not in connection_options:
            raise ImproperlyConfigured(
                "You must specify a 'INDEX_NAME' in your settings for connection '%s'."
                % connection_alias
            )

        self.conn = elasticsearch.Elasticsearch(
            connection_options["URL"],
            timeout=self.timeout,
            **connection_options.get("KWARGS", {}),
        )
        self.index_name = connection_options["INDEX_NAME"]
        self.log = logging.getLogger("haystack")
        self.setup_complete = False
        self.existing_mapping = {}
        self.content_field_name = None

    def setup(self):
        try:
            mapping = self.conn.indices.get_mapping(index=self.index_name)
            if hasattr(mapping, "body"):
                mapping = mapping.body
            self.existing_mapping = mapping.get(self.index_name, {}).get("mappings", {})
        except NotFoundError:
            pass
        except Exception:
            if not self.silently_fail:
                raise

        unified_index = haystack.connections[self.connection_alias].get_unified_index()
        self.content_field_name, field_mapping = self.build_schema(
            unified_index.all_searchfields()
        )
        current_mapping = {"properties": field_mapping}

        if current_mapping != self.existing_mapping:
            try:
                if not self.conn.indices.exists(index=self.index_name):
                    self.conn.indices.create(
                        index=self.index_name, body=self.DEFAULT_SETTINGS, ignore=400
                    )
                self.conn.indices.put_mapping(
                    index=self.index_name,
                    body=current_mapping,
                )
                self.existing_mapping = current_mapping
            except Exception:
                if not self.silently_fail:
                    raise

        self.setup_complete = True

    def _get_common_mapping(self):
        return {
            DJANGO_CT: {"type": "keyword"},
            DJANGO_ID: {"type": "keyword"},
        }

    def build_schema(self, fields):
        content_field_name = ""
        mapping = self._get_common_mapping()

        for _, field_class in fields.items():
            field_mapping = self.FIELD_MAPPINGS.get(
                field_class.field_type, self.DEFAULT_FIELD_MAPPING
            ).copy()
            if field_class.boost != 1.0:
                field_mapping["boost"] = field_class.boost

            if field_class.document is True:
                content_field_name = field_class.index_fieldname

            if field_mapping["type"] == "text":
                if field_class.indexed is False or hasattr(field_class, "facet_for"):
                    field_mapping["type"] = "keyword"
                    if "analyzer" in field_mapping:
                        del field_mapping["analyzer"]

            if field_class.field_type == "dense_vector":
                if hasattr(field_class, "dims"):
                    field_mapping["dims"] = field_class.dims
                if hasattr(field_class, "index"):
                    field_mapping["index"] = field_class.index
                if hasattr(field_class, "similarity"):
                    field_mapping["similarity"] = field_class.similarity

            mapping[field_class.index_fieldname] = field_mapping

        return (content_field_name, mapping)

    def _prepare_object(self, index, obj):
        return index.full_prepare(obj)

    def _iso_datetime(self, value):
        if hasattr(value, "strftime"):
            if hasattr(value, "hour"):
                return value.isoformat()
            else:
                return "%sT00:00:00" % value.isoformat()

    def _from_python(self, value):
        iso = self._iso_datetime(value)
        if iso:
            return iso
        elif isinstance(value, bytes):
            return str(value, errors="replace")
        elif isinstance(value, set):
            return list(value)
        return value

    def _to_python(self, value):
        if isinstance(value, (int, float, complex, list, tuple, bool)):
            return value

        if isinstance(value, str):
            possible_datetime = DATETIME_REGEX.search(value)
            if possible_datetime:
                date_values = possible_datetime.groupdict()
                for dk, dv in date_values.items():
                    if dv is not None:
                        date_values[dk] = int(float(dv))
                return datetime.datetime(
                    date_values["year"],
                    date_values["month"],
                    date_values["day"],
                    date_values["hour"],
                    date_values["minute"],
                    date_values["second"],
                )

        try:
            converted_value = ast.literal_eval(value)
            if isinstance(converted_value, (int, list, tuple, set, dict, float, complex)):
                return converted_value
        except Exception:
            pass

        return value

    def update(self, index, iterable, commit=True):
        if not self.setup_complete:
            try:
                self.setup()
            except Exception:
                if not self.silently_fail:
                    raise
                self.log.exception("Failed to add documents to Elasticsearch")
                return

        prepped_docs = []

        for obj in iterable:
            try:
                prepped_data = self._prepare_object(index, obj)
                final_data = {}
                for key, value in prepped_data.items():
                    final_data[key] = self._from_python(value)
                final_data["_id"] = final_data[ID]
                prepped_docs.append(final_data)
            except SkipDocument:
                self.log.debug("Indexing for object `%s` skipped", obj)
            except Exception:
                if not self.silently_fail:
                    raise
                self.log.exception(
                    "Preparing object for update",
                    extra={"data": {"index": index, "object": get_identifier(obj)}},
                )

        actions = (
            {
                "_op_type": "index",
                "_index": self.index_name,
                "_id": doc["_id"],
                "_source": doc,
            }
            for doc in prepped_docs
        )

        try:
            bulk(self.conn, actions=actions, index=self.index_name)
            if commit:
                self.conn.indices.refresh(index=self.index_name)
        except Exception:
            if not self.silently_fail:
                raise
            self.log.exception("Failed to bulk update documents to Elasticsearch")

    def remove(self, obj_or_string, commit=True):
        doc_id = get_identifier(obj_or_string)

        if not self.setup_complete:
            try:
                self.setup()
            except Exception:
                if not self.silently_fail:
                    raise
                self.log.exception(
                    "Failed to remove document '%s' from Elasticsearch", doc_id
                )
                return

        try:
            self.conn.delete(index=self.index_name, id=doc_id, ignore=404)
            if commit:
                self.conn.indices.refresh(index=self.index_name)
        except Exception:
            if not self.silently_fail:
                raise
            self.log.exception(
                "Failed to remove document '%s' from Elasticsearch", doc_id
            )

    def clear(self, models=None, commit=True):
        if models is not None:
            assert isinstance(models, (list, tuple))

        try:
            if models is None:
                self.conn.indices.delete(index=self.index_name, ignore=404)
                self.setup_complete = False
                self.existing_mapping = {}
                self.content_field_name = None
            else:
                models_to_delete = []
                for model in models:
                    models_to_delete.append("%s:%s" % (DJANGO_CT, get_model_ct(model)))

                query = {
                    "query": {"query_string": {"query": " OR ".join(models_to_delete)}}
                }
                generator = scan(self.conn, query=query, index=self.index_name)
                actions = (
                    {"_op_type": "delete", "_id": doc["_id"]} for doc in generator
                )
                bulk(self.conn, actions=actions, index=self.index_name)
                self.conn.indices.refresh(index=self.index_name)
        except Exception:
            if not self.silently_fail:
                raise
            if models is not None:
                self.log.exception(
                    "Failed to clear Elasticsearch index of models '%s'",
                    ",".join(models_to_delete),
                )
            else:
                self.log.exception("Failed to clear Elasticsearch index")

    def _build_search_query_dwithin(self, dwithin):
        lng, lat = dwithin["point"].coords
        distance = "%(dist).6f%(unit)s" % {"dist": dwithin["distance"].km, "unit": "km"}
        return {
            "geo_distance": {
                "distance": distance,
                dwithin["field"]: {"lat": lat, "lon": lng},
            }
        }

    def _build_search_query_within(self, within):
        from haystack.utils.geo import generate_bounding_box

        (south, west), (north, east) = generate_bounding_box(
            within["point_1"], within["point_2"]
        )
        return {
            "geo_bounding_box": {
                within["field"]: {
                    "top_left": {"lat": north, "lon": west},
                    "bottom_right": {"lat": south, "lon": east},
                }
            }
        }

    def build_search_kwargs(
        self,
        query_string,
        sort_by=None,
        start_offset=0,
        end_offset=None,
        fields="",
        highlight=False,
        facets=None,
        date_facets=None,
        query_facets=None,
        narrow_queries=None,
        spelling_query=None,
        within=None,
        dwithin=None,
        distance_point=None,
        models=None,
        limit_to_registered_models=None,
        result_class=None,
        **extra_kwargs,
    ):
        index = haystack.connections[self.connection_alias].get_unified_index()
        content_field = index.document_field

        if query_string == "*:*":
            kwargs = {"query": {"match_all": {}}}
        else:
            kwargs = {
                "query": {
                    "query_string": {
                        "default_field": content_field,
                        "default_operator": DEFAULT_OPERATOR,
                        "query": query_string,
                        "analyze_wildcard": True,
                    }
                }
            }

        filters = []

        if fields:
            if isinstance(fields, (list, set)):
                fields = " ".join(fields)
            kwargs["stored_fields"] = fields

        if sort_by is not None:
            order_list = []
            for field, direction in sort_by:
                if field == "distance" and distance_point:
                    lng, lat = distance_point["point"].coords
                    sort_kwargs = {
                        "_geo_distance": {
                            distance_point["field"]: [lng, lat],
                            "order": direction,
                            "unit": "km",
                        }
                    }
                else:
                    sort_kwargs = {field: {"order": direction}}
                order_list.append(sort_kwargs)
            kwargs["sort"] = order_list

        if highlight:
            kwargs["highlight"] = {"fields": {content_field: {}}}
            if isinstance(highlight, dict):
                kwargs["highlight"].update(highlight)

        if self.include_spelling:
            kwargs["suggest"] = {
                "suggest": {
                    "text": spelling_query or query_string,
                    "term": {
                        "field": "text",
                    },
                }
            }

        if narrow_queries is None:
            narrow_queries = set()

        if facets is not None:
            kwargs.setdefault("aggs", {})
            for facet_fieldname, extra_options in facets.items():
                facet_options = {
                    "meta": {"_type": "terms"},
                    "terms": {"field": index.get_facet_fieldname(facet_fieldname)},
                }
                if "order" in extra_options:
                    facet_options["meta"]["order"] = extra_options.pop("order")
                if extra_options.pop("global_scope", False):
                    facet_options["global"] = True
                if "facet_filter" in extra_options:
                    facet_options["facet_filter"] = extra_options.pop("facet_filter")
                facet_options["terms"].update(extra_options)
                kwargs["aggs"][facet_fieldname] = facet_options

        if date_facets is not None:
            kwargs.setdefault("aggs", {})
            for facet_fieldname, value in date_facets.items():
                interval = value.get("gap_by").lower()
                if value.get("gap_amount", 1) != 1 and interval not in ("month", "year"):
                    interval = "%s%s" % (value["gap_amount"], interval[:1])

                kwargs["aggs"][facet_fieldname] = {
                    "meta": {"_type": "date_histogram"},
                    "date_histogram": {"field": facet_fieldname, "calendar_interval": interval},
                    "aggs": {
                        facet_fieldname: {
                            "date_range": {
                                "field": facet_fieldname,
                                "ranges": [
                                    {
                                        "from": self._from_python(value.get("start_date")),
                                        "to": self._from_python(value.get("end_date")),
                                    }
                                ],
                            }
                        }
                    },
                }

        if query_facets is not None:
            kwargs.setdefault("aggs", {})
            for facet_fieldname, value in query_facets:
                kwargs["aggs"][facet_fieldname] = {
                    "meta": {"_type": "query"},
                    "filter": {"query_string": {"query": value}},
                }

        if limit_to_registered_models is None:
            limit_to_registered_models = getattr(
                settings, "HAYSTACK_LIMIT_TO_REGISTERED_MODELS", True
            )

        if models and len(models):
            model_choices = sorted(get_model_ct(model) for model in models)
        elif limit_to_registered_models:
            model_choices = self.build_models_list()
        else:
            model_choices = []

        if len(model_choices) > 0:
            filters.append({"terms": {DJANGO_CT: model_choices}})

        for q in narrow_queries:
            filters.append({"query_string": {"query": q}})

        if within is not None:
            filters.append(self._build_search_query_within(within))

        if dwithin is not None:
            filters.append(self._build_search_query_dwithin(dwithin))

        if filters:
            kwargs["query"] = {"bool": {"must": kwargs.pop("query")}}
            if len(filters) == 1:
                kwargs["query"]["bool"]["filter"] = filters[0]
            else:
                kwargs["query"]["bool"]["filter"] = {"bool": {"must": filters}}

        if extra_kwargs:
            kwargs.update(extra_kwargs)

        return kwargs

    @log_query
    def search(self, query_string, **kwargs):
        if len(query_string) == 0:
            return {"results": [], "hits": 0}

        if not self.setup_complete:
            self.setup()

        search_kwargs = self.build_search_kwargs(query_string, **kwargs)
        search_kwargs["from_"] = kwargs.get("start_offset", 0)

        order_fields = set()
        for order in search_kwargs.get("sort", []):
            for key in order.keys():
                order_fields.add(key)

        geo_sort = "_geo_distance" in order_fields

        end_offset = kwargs.get("end_offset")
        start_offset = kwargs.get("start_offset", 0)
        if end_offset is not None and end_offset > start_offset:
            search_kwargs["size"] = end_offset - start_offset

        try:
            raw_results = self.conn.search(
                body=search_kwargs,
                index=self.index_name,
            )
            if hasattr(raw_results, "body"):
                raw_results = raw_results.body
        except Exception:
            if not self.silently_fail:
                raise
            self.log.exception("Failed to query Elasticsearch using '%s'", query_string)
            raw_results = {}

        return self._process_results(
            raw_results,
            highlight=kwargs.get("highlight"),
            result_class=kwargs.get("result_class", SearchResult),
            distance_point=kwargs.get("distance_point"),
            geo_sort=geo_sort,
        )

    def more_like_this(
        self,
        model_instance,
        additional_query_string=None,
        start_offset=0,
        end_offset=None,
        models=None,
        limit_to_registered_models=None,
        result_class=None,
        **kwargs,
    ):
        from haystack import connections

        if not self.setup_complete:
            self.setup()

        model_klass = model_instance._meta.concrete_model
        index = (
            connections[self.connection_alias]
            .get_unified_index()
            .get_index(model_klass)
        )
        field_name = index.get_content_field()
        params = {}

        if start_offset is not None:
            params["from_"] = start_offset

        if end_offset is not None:
            params["size"] = end_offset - start_offset

        doc_id = get_identifier(model_instance)

        try:
            mlt_query = {
                "query": {
                    "more_like_this": {
                        "fields": [field_name],
                        "like": [{"_index": self.index_name, "_id": doc_id}],
                    }
                }
            }

            narrow_queries = []
            if additional_query_string and additional_query_string != "*:*":
                narrow_queries.append({"query_string": {"query": additional_query_string}})

            if limit_to_registered_models is None:
                limit_to_registered_models = getattr(
                    settings, "HAYSTACK_LIMIT_TO_REGISTERED_MODELS", True
                )

            if models and len(models):
                model_choices = sorted(get_model_ct(model) for model in models)
            elif limit_to_registered_models:
                model_choices = self.build_models_list()
            else:
                model_choices = []

            if len(model_choices) > 0:
                narrow_queries.append({"terms": {DJANGO_CT: model_choices}})

            if len(narrow_queries) > 0:
                mlt_query = {
                    "query": {
                        "bool": {
                            "must": mlt_query["query"],
                            "filter": {"bool": {"must": narrow_queries}},
                        }
                    }
                }

            raw_results = self.conn.search(
                body=mlt_query, index=self.index_name, **params
            )
            if hasattr(raw_results, "body"):
                raw_results = raw_results.body
        except Exception:
            if not self.silently_fail:
                raise
            self.log.exception(
                "Failed to fetch More Like This from Elasticsearch for document '%s'",
                doc_id,
            )
            raw_results = {}

        return self._process_results(raw_results, result_class=result_class)

    def _process_hits(self, raw_results):
        hits = raw_results.get("hits", {}).get("total", 0)
        if isinstance(hits, dict):
            return hits.get("value", 0)
        return hits

    def _process_results(
        self,
        raw_results,
        highlight=False,
        result_class=None,
        distance_point=None,
        geo_sort=False,
    ):
        from haystack import connections

        results = []
        hits = self._process_hits(raw_results)
        facets = {}
        spelling_suggestion = None

        if result_class is None:
            result_class = SearchResult

        if self.include_spelling and "suggest" in raw_results:
            raw_suggest = raw_results["suggest"].get("suggest")
            if raw_suggest:
                spelling_suggestion = " ".join(
                    [
                        (
                            word["text"]
                            if len(word["options"]) == 0
                            else word["options"][0]["text"]
                        )
                        for word in raw_suggest
                    ]
                )

        if "aggregations" in raw_results:
            facets = {"fields": {}, "dates": {}, "queries": {}}
            unified_index = connections[self.connection_alias].get_unified_index()
            field_data = unified_index.all_searchfields()

            for facet_fieldname, facet_info in raw_results["aggregations"].items():
                facet_type = facet_info["meta"]["_type"]
                if facet_type == "terms":
                    facets["fields"][facet_fieldname] = []
                    for individual in facet_info["buckets"]:
                        key = individual["key"]
                        if facet_fieldname in field_data and hasattr(field_data[facet_fieldname], "convert"):
                            key = field_data[facet_fieldname].convert(key)
                        facets["fields"][facet_fieldname].append((key, individual["doc_count"]))
                    
                    if "order" in facet_info["meta"] and facet_info["meta"]["order"] == "reverse_count":
                        facets["fields"][facet_fieldname] = sorted(
                            facets["fields"][facet_fieldname], key=lambda x: x[1]
                        )
                elif facet_type == "date_histogram":
                    facets["dates"][facet_fieldname] = [
                        (
                            datetime.datetime.utcfromtimestamp(individual["key"] / 1000),
                            individual["doc_count"],
                        )
                        for individual in facet_info["buckets"]
                    ]
                elif facet_type == "query":
                    facets["queries"][facet_fieldname] = facet_info["doc_count"]

        unified_index = connections[self.connection_alias].get_unified_index()
        indexed_models = unified_index.get_indexed_models()
        content_field = unified_index.document_field

        for raw_result in raw_results.get("hits", {}).get("hits", []):
            source = raw_result.get("_source", {})
            if not source:
                continue
            app_label, model_name = source[DJANGO_CT].split(".")
            additional_fields = {}
            model = haystack_get_model(app_label, model_name)

            if model and model in indexed_models:
                index = source and unified_index.get_index(model)
                for key, value in source.items():
                    string_key = str(key)
                    if string_key in index.fields and hasattr(
                        index.fields[string_key], "convert"
                    ):
                        additional_fields[string_key] = index.fields[string_key].convert(value)
                    else:
                        additional_fields[string_key] = self._to_python(value)

                del additional_fields[DJANGO_CT]
                del additional_fields[DJANGO_ID]

                if "highlight" in raw_result:
                    additional_fields["highlighted"] = raw_result["highlight"].get(
                        content_field, ""
                    )

                if distance_point:
                    additional_fields["_point_of_origin"] = distance_point
                    if geo_sort and raw_result.get("sort"):
                        from django.contrib.gis.measure import Distance
                        additional_fields["_distance"] = Distance(
                            km=float(raw_result["sort"][0])
                        )
                    else:
                        additional_fields["_distance"] = None

                result = result_class(
                    app_label,
                    model_name,
                    source[DJANGO_ID],
                    raw_result["_score"],
                    **additional_fields,
                )
                results.append(result)
            else:
                hits -= 1

        return {
            "results": results,
            "hits": hits,
            "facets": facets,
            "spelling_suggestion": spelling_suggestion,
        }

class Elasticsearch8SearchQuery(BaseSearchQuery):
    def matching_all_fragment(self):
        return "*:*"

    def build_query_fragment(self, field, filter_type, value):
        from haystack import connections

        query_frag = ""

        if not hasattr(value, "input_type_name"):
            if hasattr(value, "values_list"):
                value = list(value)

            if isinstance(value, str):
                value = Clean(value)
            else:
                value = PythonData(value)

        prepared_value = value.prepare(self)

        if not isinstance(prepared_value, (set, list, tuple)):
            prepared_value = self.backend._from_python(prepared_value)

        if field == "content":
            index_fieldname = ""
        else:
            index_fieldname = "%s:" % connections[
                self._using
            ].get_unified_index().get_index_fieldname(field)

        filter_types = {
            "content": "%s",
            "contains": "*%s*",
            "endswith": "*%s",
            "startswith": "%s*",
            "exact": "%s",
            "gt": "{%s TO *}",
            "gte": "[%s TO *]",
            "lt": "{* TO %s}",
            "lte": "[* TO %s]",
            "fuzzy": "%s~",
        }

        if value.post_process is False:
            query_frag = prepared_value
        else:
            if filter_type in ["content", "contains", "startswith", "endswith", "fuzzy"]:
                if value.input_type_name == "exact":
                    query_frag = prepared_value
                else:
                    terms = []
                    if isinstance(prepared_value, str):
                        for possible_value in prepared_value.split(" "):
                            terms.append(
                                filter_types[filter_type]
                                % self.backend._from_python(possible_value)
                            )
                    else:
                        terms.append(
                            filter_types[filter_type]
                            % self.backend._from_python(prepared_value)
                        )
                    if len(terms) == 1:
                        query_frag = terms[0]
                    else:
                        query_frag = "(%s)" % " AND ".join(terms)
            elif filter_type == "in":
                in_options = []
                if not prepared_value:
                    query_frag = "(!*:*)"
                else:
                    for possible_value in prepared_value:
                        in_options.append(
                            '"%s"' % self.backend._from_python(possible_value)
                        )
                    query_frag = "(%s)" % " OR ".join(in_options)
            elif filter_type == "range":
                start = self.backend._from_python(prepared_value[0])
                end = self.backend._from_python(prepared_value[1])
                query_frag = '["%s" TO "%s"]' % (start, end)
            elif filter_type == "exact":
                if value.input_type_name == "exact":
                    query_frag = prepared_value
                else:
                    prepared_value = Exact(prepared_value).prepare(self)
                    query_frag = filter_types[filter_type] % prepared_value
            else:
                if value.input_type_name != "exact":
                    prepared_value = Exact(prepared_value).prepare(self)
                query_frag = filter_types[filter_type] % prepared_value

        if len(query_frag) and not isinstance(value, Raw):
            if not query_frag.startswith("(") and not query_frag.endswith(")"):
                query_frag = "(%s)" % query_frag

        return "%s%s" % (index_fieldname, query_frag)

    def build_params(self, spelling_query=None, **kwargs):
        search_kwargs = {
            "start_offset": self.start_offset,
            "result_class": self.result_class,
        }
        order_by_list = None

        if self.order_by:
            if order_by_list is None:
                order_by_list = []
            for field in self.order_by:
                direction = "asc"
                if field.startswith("-"):
                    direction = "desc"
                    field = field[1:]
                order_by_list.append((field, direction))
            search_kwargs["sort_by"] = order_by_list

        if self.date_facets:
            search_kwargs["date_facets"] = self.date_facets
        if self.distance_point:
            search_kwargs["distance_point"] = self.distance_point
        if self.dwithin:
            search_kwargs["dwithin"] = self.dwithin
        if self.end_offset is not None:
            search_kwargs["end_offset"] = self.end_offset
        if self.facets:
            search_kwargs["facets"] = self.facets
        if self.fields:
            search_kwargs["fields"] = self.fields
        if self.highlight:
            search_kwargs["highlight"] = self.highlight
        if self.models:
            search_kwargs["models"] = self.models
        if self.narrow_queries:
            search_kwargs["narrow_queries"] = self.narrow_queries
        if self.query_facets:
            search_kwargs["query_facets"] = self.query_facets
        if self.within:
            search_kwargs["within"] = self.within

        if spelling_query:
            search_kwargs["spelling_query"] = spelling_query
        elif self.spelling_query:
            search_kwargs["spelling_query"] = self.spelling_query

        return search_kwargs

    def add_field_facet(self, field, **options):
        self.facets[field] = options.copy()

    def run(self, spelling_query=None, **kwargs):
        final_query = self.build_query()
        search_kwargs = self.build_params(spelling_query, **kwargs)

        if kwargs:
            search_kwargs.update(kwargs)

        results = self.backend.search(final_query, **search_kwargs)
        self._results = results.get("results", [])
        self._hit_count = results.get("hits", 0)
        self._facet_counts = self.post_process_facets(results)
        self._spelling_suggestion = results.get("spelling_suggestion", None)

    def run_mlt(self, **kwargs):
        if self._more_like_this is False or self._mlt_instance is None:
            raise MoreLikeThisError(
                "No instance was provided to determine 'More Like This' results."
            )

        additional_query_string = self.build_query()
        search_kwargs = {
            "start_offset": self.start_offset,
            "result_class": self.result_class,
            "models": self.models,
        }

        if self.end_offset is not None:
            search_kwargs["end_offset"] = self.end_offset - self.start_offset

        results = self.backend.more_like_this(
            self._mlt_instance, additional_query_string, **search_kwargs
        )
        self._results = results.get("results", [])
        self._hit_count = results.get("hits", 0)

class Elasticsearch8SearchEngine(BaseEngine):
    backend = Elasticsearch8SearchBackend
    query = Elasticsearch8SearchQuery
