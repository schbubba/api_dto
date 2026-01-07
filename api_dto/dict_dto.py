import json
from api_dto import api_dto, BaseDTO
from dacite import from_dict

from typing import Type, TypeVar

T = TypeVar("T", bound="DictDTO")

class DictDTO(dict, BaseDTO):
    """
    A dict-backed DTO that converts nested objects
    to/from DTOs.
    """

    # Override in subclasses
    __dto_fields__: dict[str, type["BaseDTO"]] = {}
    __list_dto_fields__: dict[str, type["BaseDTO"]] = {}

    @classmethod
    def from_json(cls: Type[T], data) -> T:
        dict = json.loads(data)
        result = cls.from_dict(dict)

        for key in result.keys():
            t = cls.__list_dto_fields__["items"]
            value = result[key]
            result[key] = t.from_dict(value)

        return result

    @classmethod
    def from_dict(cls, data: dict):
        obj = cls()

        for key, value in data.items():
            if key in cls.__dto_fields__ and isinstance(value, dict):
                obj[key] = cls.__dto_fields__[key].from_dict(value)

            elif key in cls.__list_dto_fields__ and isinstance(value, list):
                dto_cls = cls.__list_dto_fields__[key]
                obj[key] = [
                    dto_cls.from_dict(v) if isinstance(v, dict) else v
                    for v in value
                ]

            else:
                obj[key] = value

        return obj

    def to_dict(self) -> dict:
        result = {}

        for key, value in self.items():
            if isinstance(value, BaseDTO):
                result[key] = value.to_dict()

            elif isinstance(value, list):
                result[key] = [
                    v.to_dict() if isinstance(v, BaseDTO) else v
                    for v in value
                ]

            else:
                result[key] = value

        return result
