
from typing import Literal
LogMode = Literal["warn", "strict"]

class SensitiveFields(object):
    log_mode: LogMode = 'warn'
    _SENSITIVE_SUFFIXES = ("_id", "_key")
    _SENSITIVE_FIELDS = ("api_key", "session_id", "password", "token")
    _instance = None  # Class variable to store the single instance
    enabled = True

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            # Create a new instance if one doesn't exist
            cls._instance = super(SensitiveFields, cls).__new__(cls)
        return cls._instance
    
    def __init__(self, value=None):
        # This __init__ method will be called every time the class is instantiated,
        # so logic to handle re-initialization might be needed if arguments matter.
        if value is not None:
            self.value = value

    def initialize(self, enabled=True, fields=None, suffixes=None, replace=False, log_mode: LogMode='warn'):
        self.enabled = enabled
        self.log_mode = log_mode
        if fields:
            if isinstance(fields, str):
                fields = (fields,)
            self._SENSITIVE_FIELDS = tuple(fields) if replace else tuple(set(self._SENSITIVE_FIELDS) | set(fields))
        
        if suffixes:
            if isinstance(suffixes, str):
                suffixes = (suffixes,)
            self._SENSITIVE_SUFFIXES = tuple(suffixes) if replace else tuple(set(self._SENSITIVE_SUFFIXES) | set(suffixes))

def is_sensitive_field(value):
    sensitive_fields = SensitiveFields()

    if not sensitive_fields.enabled:
        return
    
    if value in sensitive_fields._SENSITIVE_FIELDS or value.endswith(sensitive_fields._SENSITIVE_SUFFIXES):
        return True
    return False