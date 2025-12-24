from abc import abstractmethod
from typing import TypeVar, Type

T = TypeVar("T", bound="BaseDTO")

class BaseDTO:

    @abstractmethod
    def to_dict(self) -> dict:
        """Serialize DTO to dict"""
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def from_dict(cls: Type[T], data: dict) -> T:
        """Deserialize DTO from dict"""
        raise NotImplementedError
    
    @classmethod
    @abstractmethod
    async def from_request(cls: Type[T], request) -> T:
        """Deserialize DTO from http request"""

    @abstractmethod
    def to_json(self) -> str:
        """Encode to JSON string"""

    @classmethod
    @abstractmethod
    def from_json(cls, json_str: str):
        """Decode from JSON string"""
