from collections import MutableMapping, Mapping

from flask import current_app

from flask_restalchemy.resources import ToManyRelationResource, ModelResource, \
    CollectionPropertyResource
from flask_restalchemy.resources.resources import BaseResource
from flask_restalchemy.serialization import ColumnSerializer
from flask_restalchemy.serialization.datetimeserializer import is_datetime_field, DateTimeSerializer
from flask_restalchemy.serialization.enumserializer import is_enum_field, EnumSerializer


class Api(object):

    def __init__(self, blueprint=None, errors=None, request_decorators=None):
        """
        :param (Flask|Blueprint) blueprint: Flask application or Blueprint

        :param str prefix: API endpoints prefix

        :param errors: A dictionary to define a custom response for each
            exception or error raised during a request

        :param callable request_decorators: request decorators for this API object (see
            Flask-Restful decorators docs for more information)
        """
        # noinspection PyPackageRequirements
        self.default_mediatype = 'application/json'
        self._blueprint = blueprint
        self._db = None
        self._api_request_decorators = ResourceDecorators(request_decorators)

    def init_app(self, blueprint):
        self._blueprint = blueprint

    def add_model(self, model, url=None, serializer_class=None, view_name=None, request_decorators=None):
        """
        Create API endpoints for the given SQLAlchemy declarative class.

        :param class model: the SQLAlchemy declarative class

        :param string url: one or more url routes to match for the resource, standard flask routing
            rules apply. Defaults to model name in lower case.

        :param string view_name: custom name for the collection endpoint url definition, if
            not set the model table name will be used

        :param Type[ModelSerializer] serializer_class: If `None`, a default serializer will be
            created.

        :param list|dict request_decorators: decorators to be applied to HTTP methods. Could be a
            list of decorators or a dict mapping HTTP method types to a list of decorators (dict
            keys should be 'get', 'post' or 'put').

        :param preprocessors: A dict with the lists of callable preprocessors for each API method

        :param postprocessors: A dict with the lists of callable postprocessors for each API method
        """
        view_name = view_name or model.__tablename__
        if not serializer_class:
            serializer = self.create_default_serializer(model)
        else:
            serializer = serializer_class(model)
        url = url or '/' + view_name.lower()

        view_init_args = (model, serializer, self.get_db_session)
        decorators = self._create_decorators(request_decorators)
        self.add_resource(ModelResource, url, view_name, view_init_args, decorators=decorators)

    def add_relation(self, relation_property, url_rule=None, serializer_class=None,
                     request_decorators=None, endpoint_name=None):
        """
        Create API endpoints for the given SQLAlchemy relationship.

        :param relation_property: model relationship representing the collection to receive the
            CRUD operations.

        :param string url_rule: one or more url routes to match for the resource, standard
             flask routing rules apply. Defaults to model name in lower case.

        :param Type[ModelSerializer] serializer_class: If `None`, a default serializer will be created.

        :param list|dict request_decorators: decorators to be applied to HTTP methods. Could be a list of decorators
            or a dict mapping HTTP method types to a list of decorators (dict keys should be 'get', 'post' or 'put').
            See https://flask-restful.readthedocs.io/en/latest/extending.html#resource-method-decorators for more
            details.

        :param list|dict collection_decorators: decorators to be applied to HTTP methods for collections. It defaults to
            request_decorators value.

        :param string endpoint_name: endpoint name (defaults to :meth:`{model_collection_name}-{related_collection_name}-relation`
            Can be used to reference this route in :class:`fields.Url` fields

        """
        model = relation_property.prop.mapper.class_
        related_model = relation_property.class_
        view_name = "{}_{}".format(model.__name__, related_model.__name__).lower()

        if not serializer_class:
            serializer = self.create_default_serializer(model)
        else:
            serializer = serializer_class(model)
        if url_rule:
            assert '<int:relation_id>' in url_rule
        else:
            parent_endpoint = related_model.__tablename__.lower()
            url_rule = '/{}/<int:relation_id>/{}'.format(parent_endpoint, relation_property.key)
        endpoint_name = endpoint_name or url_rule

        view_init_args = (relation_property, serializer, self.get_db_session)
        self.add_resource(
            ToManyRelationResource,
            url_rule,
            view_name,
            view_init_args,
            decorators=self._create_decorators(request_decorators)
        )

    def add_property(self, property_type, model, property_name, url_rule=None,
                     serializer_class=None, request_decorators=[], endpoint_name=None):
        if not serializer_class:
            serializer = self.create_default_serializer(property_type)
        else:
            serializer = serializer_class(property_type)
        view_name = "{}_{}".format(model.__name__, property_name).lower()
        if url_rule:
            assert '<int:relation_id>' in url_rule
        else:
            parent_endpoint = (model.__tablename__.lower())
            url_rule = '/{}/<int:relation_id>/{}'.format(parent_endpoint, property_name.lower())

        endpoint = endpoint_name or url_rule

        view_init_args = (property_type, model, property_name, serializer, self.get_db_session)
        self.add_resource(
            CollectionPropertyResource,
            url_rule,
            view_name,
            view_init_args,
            decorators=self._create_decorators(request_decorators)
        )

    def add_resource(self, resource_class, url_rule, view_name, resource_init_args=(), resource_init_kwargs=None,
                     decorators=None):
        if not issubclass(resource_class, BaseResource):
            raise TypeError("Resource must inherit BaseResource")
        if resource_init_kwargs is None:
            resource_init_kwargs = {}
        else:
            assert 'request_decorators' not in resource_init_kwargs, "Use add_resource 'decorators' parameter"
        resource_init_kwargs['request_decorators'] = self._create_decorators(decorators)
        view_func = resource_class.as_view(view_name, *resource_init_args, **resource_init_kwargs)
        self.register_view(view_func, url_rule)

    def register_view(self, view_func, url, pk='id', pk_type='int'):
        app = self._blueprint
        app.add_url_rule(url, defaults={pk: None}, view_func=view_func, methods=['GET', ])
        app.add_url_rule(url, view_func=view_func, methods=['POST', ])
        app.add_url_rule('%s/<%s:%s>' % (url, pk_type, pk), view_func=view_func, methods=['GET', 'PUT', 'DELETE'])

    def _create_decorators(self, request_decorators):
        merged_request_decorators = ResourceDecorators(request_decorators)
        merged_request_decorators.merge(self._api_request_decorators)
        return merged_request_decorators


    @staticmethod
    def create_default_serializer(model_class):
        """
        Create a default serializer for the given SQLAlchemy declarative class. Recipe based on
        https://marshmallow-sqlalchemy.readthedocs.io/en/latest/recipes.html#automatically-generating-schemas-for-sqlalchemy-models

        :param model_class: the SQLAlchemy mapped class

        :rtype: class
        """
        from flask_restalchemy.serialization.modelserializer import ModelSerializer
        return ModelSerializer(model_class)

    def get_db_session(self):
        """
        Returns an SQLAlchemy object session. Used by flask-restful Resources to access
        the database.
        """
        if not self._db:
            # Get the Flask application
            flask_app = current_app
            assert flask_app and flask_app.extensions, "Flask App not initialized yet"
            self._db = flask_app.extensions['sqlalchemy'].db
        return self._db.session

    _FIELD_SERIALIZERS = [(DateTimeSerializer, is_datetime_field), (EnumSerializer, is_enum_field)]

    @classmethod
    def register_column_serializer(cls, serializer_class, predicate):
        '''
        Register a serializer for a given column to be used globally by ModelSerializers

        :param Type[ColumnSerializer] serializer_class: the Serializer class
        :param callable predicate: a function that receives a column type and returns True if the
            given serializer is valid for that column
        '''
        if not issubclass(serializer_class, ColumnSerializer):
            raise TypeError('Invalid serializer class')
        cls._FIELD_SERIALIZERS.append((serializer_class, predicate))

    @classmethod
    def find_column_serializer(cls, column):
        '''
        :param Column column: search for a registered serializer for the given column

        :rtype: ColumnSerializer
        '''
        for serializer_class, predicate in reversed(cls._FIELD_SERIALIZERS):
            if predicate(column):
                return serializer_class(column)
        else:
            return None



class ResourceDecorators(Mapping):

    def __init__(self, request_decorators=None):
        self._verb_decorators = {}
        for verb in ['ALL', 'GET', 'POST', 'PUT', 'DELETE']:
            self._verb_decorators[verb] = []
        if request_decorators:
            self.merge(request_decorators)

    def merge(self, request_decorators):
        if callable(request_decorators):
            self._verb_decorators['ALL'].append(request_decorators)
        elif isinstance(request_decorators, list):
            self._verb_decorators['ALL'].extend(request_decorators)
        elif isinstance(request_decorators, (dict, ResourceDecorators)):
            for verb, decorator_value in request_decorators.items():
                if callable(decorator_value):
                    self._verb_decorators[verb].append(decorator_value)
                elif isinstance(decorator_value, list):
                    self._verb_decorators[verb].extend(decorator_value)
                else:
                    raise TypeError()
        else:
            TypeError()


    def __getitem__(self, verb):
        return self._verb_decorators[verb]

    def __iter__(self):
        return iter(self._verb_decorators)

    def __len__(self):
        return len(self._verb_decorators)