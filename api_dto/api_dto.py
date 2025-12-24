from dataclasses import dataclass, field, asdict, is_dataclass
from dacite import from_dict, Config
from typing import Literal, get_origin, List, Dict, Set, TypeVar, Union
from enum import Enum
import types
from .sensitive_fields import SensitiveFields

T = TypeVar("T")

_SERIALIZABLE_ADDED = "_serializable_added"
_NULLABLE_ADDED = "_nullable_added"
_IS_API_DTO = "_is_api_dto"

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
        return cls

    return wrap if cls is None else wrap(cls)


def _to_dict(self):
    data = asdict(self)
    _warn_sensitive_fields(self, data)
    return data


def _enum_hook(value, enum_type):
    # dacite only calls this when enum_type is EXACT enum class
    if value is None:
        return None

    # Try direct match first
    try:
        return enum_type(value)
    except Exception:
        pass

    # Try uppercase matching
    if isinstance(value, str):
        for e in enum_type:
            if e.name.lower() == value.lower():
                return e

    raise ValueError(f"Cannot map value {value!r} to enum {enum_type.__name__}")


def _from_dict(cls, data):
    return from_dict(
        cls,
        data=data,
        config=Config(type_hooks={
            cls_field_type: _enum_hook
            for cls_field_type in cls.__annotations__.values()
            if isinstance(cls_field_type, type) and issubclass(cls_field_type, Enum)
        })
    )


async def _from_http_request(cls, request):
    if request is None:
        raise ValueError("Request cannot be None")

    try:
        data = await request.json()
    except Exception:
        raise ValueError("HTTP response did not contain valid JSON")

    return cls.from_dict(data)

def _to_json(self) -> str:
    import json
    return json.dumps(self.to_dict())

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