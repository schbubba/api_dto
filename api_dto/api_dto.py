from dataclasses import dataclass, field, asdict, is_dataclass
from dacite import from_dict, Config
from datetime import datetime
from typing import Literal, get_origin, List, Dict, Set, TypeVar, Union
from enum import Enum
import types
from .sensitive_fields import SensitiveFields
from .base_dto import BaseDTO
import json
import importlib

T = TypeVar("T")

_SERIALIZABLE_ADDED = "_serializable_added"
_NULLABLE_ADDED = "_nullable_added"
_IS_API_DTO = "_is_api_dto"

_IS_STORED_AS_STRING = "_is_stored_as_string"

class JsonFieldDescriptor:
    def __init__(self, func):
        self.func = func
        self.is_stored_as_string = True
        self.type = func.__annotations__.get("return")
        self.name = func.__name__ 

    def __set_name__(self, owner, name):
        """Called automatically when the class is created."""
        self.owner = owner
        self.private_name = f"_{name}"

    def __get__(self, instance, owner):
        if instance is None:
            return self  # accessing the property on the class
        # Return the underlying stored value
        return getattr(instance, self.private_name, None)

    def __set__(self, instance, value):
        # Example conversion: store as string
        if value is None:
            setattr(instance, self.private_name, None)
        else:
            setattr(instance, self.private_name, value)

    def __delete__(self, instance):
        setattr(instance, self.private_name, None)


def json_field(func=None, *, value=True):
    return JsonFieldDescriptor(func)

# ------------------------------
# Core DTO decorator
# ------------------------------
def api_dto(cls=None, *, optional=True, serializable=True, auto_collections=True):
    """
    Combined decorator for DTO classes.
    """
    def wrap(cls):
        is_api_dto, has_nullable, has_serialization = _is_api_dto(cls)

        if not is_api_dto and is_dataclass(cls):
            _remove_dataclass(cls)

        if not is_api_dto:
            if optional and not has_nullable:
                cls = make_nullable(auto_collections=auto_collections)(cls)

            if not is_dataclass(cls):
                cls = dataclass()(cls=cls)

            if serializable and not has_serialization:
                cls = add_serializable()(cls)
            
            setattr(cls, _IS_API_DTO, True)

        return cls

    if cls is None:
        return wrap
    return wrap(cls)

def add_serializable(cls=None):
    def wrap(cls):
        setattr(cls, _SERIALIZABLE_ADDED, True)
        
        cls.to_dict = _to_dict
        cls.from_dict = classmethod(_from_dict)
        cls.from_http_request = classmethod(_from_http_request)
        cls.to_json = _to_json
        cls.from_json = classmethod(_from_json)
        cls._find_string_fields = _find_string_fields
        return cls

    return wrap if cls is None else wrap(cls)

def _find_string_fields(self):
    """Return {field_name: field_type} for all @store_as_string fields."""
    result = {}
    for name, attr in self.__class__.__dict__.items():
        if isinstance(attr, JsonFieldDescriptor):
            result[name] = attr.type
    return result


def _to_dict(self, expand_json_fields=False):
    """
    Serialize DTO to dict.
    
    Args:
        expand_json_fields: If True, @json_field decorated fields will be 
                           serialized as nested dicts instead of JSON strings
    """
    import json

    try:
        data = asdict(self)
        
        if not expand_json_fields:
            string_fields = self._find_string_fields()

            for field, _type in string_fields.items():
                value = getattr(self, field)

                if value is None:
                    data[field] = None
                else:
                    # full nested object → dict → JSON string
                    if hasattr(value, "to_dict"):
                        nested_dict = value.to_dict(expand_json_fields=False)
                    else:
                        nested_dict = asdict(value)

                    data[field] = json.dumps(nested_dict)
        else:
            # When expanding, just use the nested dict directly
            string_fields = self._find_string_fields()
            
            for field, _type in string_fields.items():
                value = getattr(self, field)

                if value is None:
                    data[field] = None
                else:
                    # Recursively expand nested objects
                    if hasattr(value, "to_dict"):
                        data[field] = value.to_dict(expand_json_fields=True)
                    else:
                        data[field] = asdict(value)

        return data

    except Exception as e:
        print(f"Error serializing DTO: {e}")
        raise

def _from_dict(cls, data):
    """
    Deserialize DTO from dict.
    Automatically detects whether @json_field values are JSON strings or dicts.
    """
    # make a copy
    data = dict(data)

    # find all @json_field fields
    string_fields = {
        name: attr.func.__annotations__.get("return")
        for name, attr in cls.__dict__.items()
        if hasattr(attr, "is_stored_as_string")
    }

    # Extract and deserialize @json_field fields separately
    string_field_values = {}
    for field_name, field_type in string_fields.items():
        raw = data.pop(field_name, None)  # Remove from data
        if raw is not None:
            # Auto-detect: if it's a string, deserialize from JSON
            # if it's already a dict, deserialize as nested object
            if isinstance(raw, str):
                # JSON string format (from database)
                string_field_values[field_name] = _deserialize_string_field(raw, field_type)
            elif isinstance(raw, dict):
                # Already expanded dict format (from API/expanded to_dict)
                if hasattr(field_type, 'from_dict'):
                    string_field_values[field_name] = field_type.from_dict(raw)
                else:
                    string_field_values[field_name] = raw
            else:
                # Some other type, just pass it through
                string_field_values[field_name] = raw

    def int_cast(value):
        if value is None:
            return None
        return int(value)

    def datetime_cast(value):
        if value is None:
            return None
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                pass
        return value


    type_hooks = {
        int: int_cast,
        datetime: datetime_cast
    }

    # Add enum hooks
    for t in cls.__annotations__.values():
        if isinstance(t, type) and issubclass(t, Enum):
            type_hooks[t] = _value_hook

    # Create instance with dacite (without @json_field fields)
    instance = from_dict(
        cls,
        data=data,
        config=Config(type_hooks=type_hooks) if type_hooks else Config()
    )

    # Now manually set the @json_field fields
    for field_name, value in string_field_values.items():
        setattr(instance, field_name, value)

    return instance

def _value_hook(value, type_):

    # None is always allowed
    if value is None:
        return None

    # -------- INT CASTING SUPPORT --------
    if type_ is int:
        try:
            return int(value)
        except (ValueError, TypeError):
            return value  # fallback without breaking
    # -------------------------------------

    # Enum support
    if isinstance(type_, type) and issubclass(type_, Enum):
        # Try direct match
        try:
            return type_(value)
        except Exception:
            pass

        # Try name-case-insensitive match
        if isinstance(value, str):
            lname = value.lower()
            for e in type_:
                if e.name.lower() == lname:
                    return e

    # Nested DTO support
    if isinstance(type_, type) and issubclass(type_, BaseDTO):
        # JSON-deserialized DTO inside string field
        json_value = json.loads(value)
        return json_value

    return value



def _deserialize_string_field(value, target_type):
    """Recursively convert JSON strings into DTO objects."""
    if value is None:
        return None

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None

        if isinstance(parsed, dict):
            # recursively deserialize nested @store_as_string fields
            return target_type.from_dict(parsed)
        elif isinstance(parsed, str):
            # nested string in string
            return _deserialize_string_field(parsed, target_type)
        else:
            return parsed
    else:
        return value


async def _from_http_request(cls, request):
    if request is None:
        raise ValueError("Request cannot be None")

    try:
        data = await request.json()
    except Exception:
        raise ValueError("HTTP response did not contain valid JSON")

    return cls.from_dict(data)

def _to_json(self, indent=None, expand_json_fields=False) -> str:
    import json
    return json.dumps(self.to_dict(expand_json_fields=expand_json_fields), indent=indent)

def _from_json(cls, json_str: str):
    import json
    data = json.loads(json_str)
    return cls.from_dict(data)

# ------------------------------
# Nullable / optional fields
# ------------------------------
def make_nullable(cls=None, *, auto_collections=True):
    def wrap(cls):
        setattr(cls, _NULLABLE_ADDED, True)
        return _make_nullable(cls, auto_collections=auto_collections)
    
    if cls is None:
        return wrap
    return wrap(cls)

def _make_nullable(cls, auto_collections=True):
    annotations = dict(getattr(cls, "__annotations__", {}))
    
    for field_name, field_type in annotations.items():
        # Make non-optional types optional
        if not _is_optional(field_type):
            annotations[field_name] = field_type | None

        # Check for unsupported types (sets)
        origin = get_origin(field_type) or field_type
        if origin is set or origin is Set:
            raise TypeError(f"Field '{field_name}' uses set, which is not supported by @dto")

        # Set default value if no default exists
        if not hasattr(cls, field_name):
            default = None
            if auto_collections:
                if origin in (list, List):
                    default = field(default_factory=list)
                elif origin in (dict, Dict):
                    default = field(default_factory=dict)
            setattr(cls, field_name, default)

    cls.__annotations__ = annotations
    return cls

def _is_optional(annotation):
    """Checks if a type annotation is Optional[T] or T | None."""
    origin = get_origin(annotation)
    args = getattr(annotation, "__args__", ())

    # Check for T | None (UnionType in Python 3.10+)
    if origin is types.UnionType:
        return type(None) in args

    # Check for typing.Optional[T] or typing.Union[T, None]
    if origin is None:
        return False
    if origin is tuple([*args]):  # fallback, rare
        return type(None) in args
    if origin is getattr(annotation, "__origin__", None):
        return type(None) in args
    if origin is getattr(annotation, "__args__", None):
        return type(None) in args

    if origin is getattr(annotation, "__origin__", None):
        return type(None) in args
    if origin is getattr(annotation, "__args__", None):
        return type(None) in args

    if origin is getattr(annotation, "__origin__", None):
        return type(None) in args
    if origin is getattr(annotation, "__args__", None):
        return type(None) in args

    if origin is getattr(annotation, "__origin__", None):
        return type(None) in args
    if origin is getattr(annotation, "__args__", None):
        return type(None) in args

    if origin is getattr(annotation, "__origin__", None):
        return type(None) in args
    if origin is getattr(annotation, "__args__", None):
        return type(None) in args

    # For normal Optional[T]
    if origin is Union and type(None) in args:
        return True

    return False

def _warn_sensitive_fields(cls, data: dict):
    """
    Recursively checks the dictionary for sensitive fields and logs a warning.
    """
    import logging

    logger_name = type(cls).__name__ if cls else "api_dto"
    logger = logging.getLogger(logger_name)

    sensitive_fields = SensitiveFields()

    if not sensitive_fields.enabled:
        return

    for key, value in data.items():
        key_lower = key.lower()

        # Warn if key matches known sensitive names or ends with sensitive suffix
        if key_lower in sensitive_fields._SENSITIVE_FIELDS or key_lower.endswith(sensitive_fields._SENSITIVE_SUFFIXES):
            if sensitive_fields.log_mode == 'warn':
                logger.warning(f"⚠️\tWARNING: Serializing sensitive field '{logger_name}.{key}'")
            elif sensitive_fields.log_mode == 'strict':
                logger.error(f"❌\tERROR: Serializing sensitive field '{logger_name}.{key}'")
                raise AttributeError(f"Invalid field name for serialization: '{logger_name}.{key}'")

        # Recursively check nested dicts
        if isinstance(value, dict):
            _warn_sensitive_fields(cls, value)
        elif isinstance(value, list):
            for item in value:
                if hasattr(item, "to_dict"):  # nested DTO object
                    _warn_sensitive_fields(item, item.to_dict())
                elif isinstance(item, dict):
                    _warn_sensitive_fields(cls, item)


def _remove_dataclass(cls):
    """Removes dataclass magic methods and attributes from a class at runtime."""
    # List of attributes and methods typically added by @dataclass
    dataclass_attrs = [
        '__init__', '__repr__', '__eq__', '__hash__',
        '__match_args__', '__dataclass_params__', '__dataclass_fields__'
    ]

    for attr in dataclass_attrs:
        if hasattr(cls, attr):
            delattr(cls, attr)
    
    return cls

def _is_api_dto(obj):
    cls = obj if isinstance(obj, type) else type(obj)
    is_api_dto = hasattr(cls, _IS_API_DTO)
    is_nullable_added = hasattr(cls, _NULLABLE_ADDED)
    is_serializable_added = hasattr(cls, _SERIALIZABLE_ADDED)

    return is_api_dto, is_nullable_added, is_serializable_added