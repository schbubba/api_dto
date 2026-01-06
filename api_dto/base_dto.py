from abc import abstractmethod
import io
import types
import xml.etree.ElementTree as ET
from datetime import datetime
from enum import Enum
from typing import Optional, Any, List, TypeVar, Type, Union, get_args, get_origin
from dataclasses import dataclass

T = TypeVar("T", bound="BaseDTO")

class BaseDTO:
    _namespaces = {}

    @abstractmethod
    def to_dict(self, expand_json_fields=False) -> dict:
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
    def to_json(self, indent=None, expand_json_fields=False) -> str:
        """Encode to JSON string"""

    @classmethod
    @abstractmethod
    def from_json(cls, json_str: str):
        """Decode from JSON string"""

    @classmethod
    def from_xml(cls, xml: str):
        """
        Docstring for from_xml
        
        :param obj: Description
        :param xml: Description
        :type xml: str
        """
        obj = cls()
        root = ET.fromstring(xml)
        source_element = cls._xml_get_source_element(root)
        obj._xml_map_element(obj, source_element)

        return obj

    def _load_namespaces_from_xml(self, xml: str):
        for event, elem in ET.iterparse(io.BytesIO(xml.encode('utf-8')), events=['start-ns']):
            prefix, uri = elem
            print(  f"Registering namespace: prefix='{prefix}', uri='{uri}'"  )
            self._namespaces[prefix] = uri

    def _xml_map_element(self, obj, element: ET.Element):
        """Map all child elements and attributes to the object"""
        # Map attributes first
        for attr_name, attr_value in element.attrib.items():
            if not attr_name.startswith('xmlns'):
                self._xml_set_property(obj, attr_name, attr_value)
        
        # Get object's type annotations
        annotations = getattr(type(obj), "__annotations__", {})

        # Map child elements
        for child in element:
            tag = self._camel_to_snake(self._strip_namespace(child.tag))
            # Get the expected type for this property
            expected_type = annotations.get(tag, None)
            origin = get_origin(expected_type) if expected_type else None
            
            # Handle Optional[T]
            if origin is Union:
                non_none = [t for t in get_args(expected_type) if t is not type(None)]
                expected_type = non_none[0] if non_none else None
                origin = get_origin(expected_type)
            
            if origin in (list, List):
                self._xml_handle_list_element(obj, tag, child, expected_type)
            elif self._xml_is_scalar(child):
                self._xml_handle_scalar_element(obj, tag, child, expected_type)
            else:
                self._xml_handle_complex_element(obj, tag, child, expected_type)

    def _xml_set_property(self, obj, name, value):
        property_name = self._camel_to_snake(self._strip_namespace(name))
        annotations = getattr(obj.__class__, "__annotations__", {})

        if property_name in annotations:
            expected_type = annotations[property_name]
            value = self._coerce_value(expected_type, value)

        setattr(obj, property_name, value)

    def _xml_is_scalar(self, element: ET.Element) -> bool:
        """Determine if the element is a scalar value"""
        return len(list(element)) == 0 and len(element.attrib) == 0

    def _xml_is_complex(self, element: ET.Element) -> bool:
        """Determine if the element is a complex type"""
        return not self._xml_is_scalar(element)

    def _xml_is_list(self, obj, tag: str, element: ET.Element) -> bool:
        """
        Determine if the element is a list container or list item.
        Returns True if element is a list item (not the container).
        """
        child_elements = list(element)
        
        # If element has no children, it's a list item
        if len(child_elements) == 0:
            return True
        
        # Check if all children have the same tag name
        if child_elements:
            first_child_tag = self._strip_namespace(child_elements[0].tag)
            if all(self._strip_namespace(child.tag) == first_child_tag for child in child_elements):
                # All children have same tag = this is a container
                return False
        
        # Mixed tags or other structure = this is a list item with properties
        return True

    def _xml_auto_parse(self, text: str, target_type: Type = None) -> Any:
        """Parse text to appropriate type"""
        if text is None:
            return None
        
        # If we have a target type, use it
        if target_type:
            if target_type == int:
                return int(text)
            elif target_type == float:
                return float(text)
            elif target_type == bool:
                return text.lower() in ('true', '1', 'yes')
            elif target_type == str:
                return text
        
        # Auto-detect type
        if text.lower() in ('true', 'false'):
            return text.lower() == 'true'
        
        try:
            return int(text)
        except ValueError:
            pass
        
        try:
            return float(text)
        except ValueError:
            pass
        
        return text

    @classmethod
    def _xml_get_source_element(cls, root: ET.Element) -> ET.Element:
        """Get the source element - either root itself or first child"""
        children = list(root)
        source_element = root.find(f"{{*}}{cls.__name__.lower()}")
        
        if source_element is None:
            source_element = root.find(f"{{*}}{cls.__name__}")
    
        # print(f"Warning: Could not find matching element for {cls.__name__}, using first child or root")
        # Fallback to first child or root
        result = source_element if source_element is not None else root
        # print(f"Using element: {result.tag}")
        return result

    @classmethod
    def _create_dynamic_obj(cls):
        """Create a dynamic object that can have any attributes set"""
        class DynamicDTO(BaseDTO): pass
        return DynamicDTO()

    def _xml_handle_scalar_element(self, obj, tag, element: ET.Element, expected_type=None):
        """Handle simple scalar values"""
        value = element.text.strip() if element.text else None
        parsed_value = self._xml_auto_parse(value, expected_type)
        self._xml_set_property(obj, tag, parsed_value)

    def _xml_handle_complex_element(self, obj, tag, element: ET.Element, expected_type=None):
        """Handle complex nested objects"""
        # Create the nested object
        if tag in type(obj).__annotations__.keys():
            obj_type = type(obj).__annotations__[tag]
            if obj_type and get_origin(obj_type) is Union:
                expected_type = expected_type if expected_type else get_args(obj_type)[0]

        nested_obj = expected_type() if expected_type else self._xml_get_dto()
        self._xml_set_property(obj, tag, nested_obj)

        # Recursively map the element to the nested object
        self._xml_map_element(nested_obj, element)

    def _xml_handle_list_element(self, obj, tag, element: ET.Element, list_type):
        """Handle list elements"""
        item_type = get_args(list_type)[0] if list_type else None
        # Get or create the list
        current_list = getattr(obj, tag, None)
        if current_list is None:
            current_list = []
            self._xml_set_property(obj, tag, current_list)
        
        child_elements = list(element)        
        # Check if element is the list item or the container
        if self._xml_is_list(obj, tag, element):
            # Element IS the list item
            item_obj = item_type() if item_type else self._xml_get_dto()

            # Handle primitive types (str, int, etc.)
            if item_type in (str, int, float, bool):
                item_value = element.text.strip() if element.text else None
                if item_type != str and item_value:
                    item_value = item_type(item_value)  # Convert to int/float/bool
                current_list.append(item_value)
                return

            current_list.append(item_obj)
            # Map attributes
            for attr_name, attr_value in element.attrib.items():
                self._xml_set_property(item_obj, attr_name, attr_value)

            # Map child elements
            for child in child_elements:
                child_tag = self._camel_to_snake(self._strip_namespace(child.tag))
                if self._xml_is_scalar(child):
                    self._xml_handle_scalar_element(item_obj, child_tag, child)
                else:
                    self._xml_handle_complex_element(item_obj, child_tag, child)
        else:
            # Element is the container, iterate its children
            for list_item_elem in child_elements:
                item_obj = item_type() if item_type else self._xml_get_dto()
                current_list.append(item_obj)

                # Map attributes
                for attr_name, attr_value in list_item_elem.attrib.items():
                    self._xml_set_property(item_obj, attr_name, attr_value)
                
                # Map child elements
                for child in list_item_elem:
                    child_tag = self._camel_to_snake(self._strip_namespace(child.tag))
                    if self._xml_is_scalar(child):
                        self._xml_handle_scalar_element(item_obj, child_tag, child)
                    else:
                        self._xml_handle_complex_element(item_obj, child_tag, child)

    def _coerce_value(self, expected_type, value):
        # Null stays null
        if value is None:
            return None

        origin = get_origin(expected_type)
        args = get_args(expected_type)

        # Handle Optional / Union[T, None]
        if origin is Union or origin is None:
            if args:
                # strip NoneType if present
                non_none = [t for t in args if t is not type(None)]
                if non_none:
                    expected_type = non_none[0]

        # ---- INT ----
        if expected_type is int:
            try: return int(value)
            except: return value

        # ---- FLOAT ----
        if expected_type is float:
            try: return float(value)
            except: return value

        # ---- BOOL ----
        if expected_type is bool:
            if isinstance(value, str):
                v = value.strip().lower()
                if v in ("true", "1", "yes", "on"): return True
                if v in ("false", "0", "no", "off"): return False
            return bool(value)

        # ---- DATETIME ----
        if expected_type is datetime:
            if isinstance(value, str):
                try:
                    return datetime.fromisoformat(value)
                except Exception:
                    pass  # fallback to original string
            return value

        # ---- ENUM ----
        if isinstance(expected_type, type) and issubclass(expected_type, Enum):
            # Try direct enum(value)
            try:
                return expected_type(value)
            except:
                pass

            # Case-insensitive match to enum name
            if isinstance(value, str):
                v = value.lower()
                for e in expected_type:
                    if e.name.lower() == v:
                        return e

        # Default: leave as string
        return value

    def _xml_get_dto(self):
        """
        Used to get a BaseDTO object.
        if the source element has complex types 
        but the target DTO doesn't contain a property for it
        to map to, created an empty DTO
        
        :param value: Description
        """
        
        @dataclass
        class o(BaseDTO): 
            pass

        return o()

    def _strip_namespace(self, tag: str) -> str:
        """Remove namespace from an XML tag."""
        return tag.split("}", 1)[1] if "}" in tag else tag

    def _snake_to_camel(self, name: str) -> str:
        """Convert snake_case to camelCase for XML matching"""
        components = name.split('_')
        return components[0] + ''.join(x.title() for x in components[1:])

    def _camel_to_snake(self, name: str) -> str:
        """Convert camelCase to snake_case"""
        result = []
        for i, char in enumerate(name):
            if char.isupper() and i > 0:
                # Don't add underscore if previous char was also uppercase (e.g., "URLPath")
                if i + 1 < len(name) and name[i + 1].islower():
                    result.append('_')
                elif not name[i - 1].isupper():
                    result.append('_')
            result.append(char.lower())
        return ''.join(result)

    @classmethod
    def _auto_parse_value(cls, text: str) -> Any:
        """
        Automatically parse a string value to int, float, bool, or keep as string.
        """
        if text is None:
            return None
        
        text = text.strip()
        if not text:
            return None
        
        # Try bool
        if text.lower() in ('true', 'false'):
            return text.lower() == 'true'
        
        # Try int
        try:
            return int(text)
        except ValueError:
            pass
        
        # Try float
        try:
            return float(text)
        except ValueError:
            pass
        
        # Keep as string
        return text

    @classmethod
    def _unwrap_optional(cls, field_type):
        """
        Unwrap Optional[T] or T | None to get the actual type T.
        Returns the field_type unchanged if it's not Optional.
        """
        origin = get_origin(field_type)
        args = get_args(field_type)
        
        # Handle Union types (including Optional which is Union[T, None])
        if origin is Union or (hasattr(types, 'UnionType') and origin is types.UnionType):
            # Filter out NoneType to get the actual type(s)
            non_none_types = [arg for arg in args if arg is not type(None)]
            if len(non_none_types) == 1:
                return non_none_types[0]
            elif len(non_none_types) > 1:
                # Multiple non-None types in Union, return the first one
                # or could raise an error
                return non_none_types[0]
        
        return field_type

    @classmethod
    def _extract_all_namespaces(cls, element: ET.Element) -> dict:
        """Extract all namespace mappings from the entire tree"""
        namespaces = {}

        # Get namespaces from root element
        for key, value in element.attrib.items():
            if key == 'xmlns':
                namespaces[''] = value
            elif key.startswith('xmlns:'):
                prefix = key.split(':', 1)[1]
                namespaces[prefix] = value

        # Also check the element's tag for inline namespace declarations
        # ElementTree stores these in the tag itself
        for elem in element.iter():
            for key, value in elem.attrib.items():
                if key == 'xmlns':
                    if '' not in namespaces:
                        namespaces[''] = value
                elif key.startswith('xmlns:'):
                    prefix = key.split(':', 1)[1]
                    if prefix not in namespaces:
                        namespaces[prefix] = value

        # Build reverse mapping: URI -> prefix
        uri_to_prefix = {v: k for k, v in namespaces.items()}

        # Extract namespace URIs from actual element tags in the tree
        for elem in element.iter():
            if '}' in elem.tag:
                ns_uri = elem.tag.split('}')[0][1:]  # Remove leading {
                if ns_uri not in uri_to_prefix:
                    # Generate a prefix for unmapped namespaces
                    prefix = f"ns{len(uri_to_prefix)}"
                    uri_to_prefix[ns_uri] = prefix
                    namespaces[prefix] = ns_uri

        return namespaces

    @classmethod
    def _find_element(cls, element: ET.Element, name: str, namespaces: dict) -> Optional[ET.Element]:
        """Find a single child element, handling namespaces properly"""
        # Method 1: Try with namespace prefix if provided
        if ':' in name:
            prefix, local = name.split(':', 1)
            if prefix in namespaces:
                full_name = f"{{{namespaces[prefix]}}}{local}"
                child = element.find(full_name)
                if child is not None:
                    return child

        # Method 2: Try with default namespace
        if '' in namespaces:
            full_name = f"{{{namespaces['']}}}{name}"
            child = element.find(full_name)
            if child is not None:
                return child

        # Method 3: Try without namespace
        child = element.find(name)
        if child is not None:
            return child

        # Method 4: Search across ALL namespaces for matching local name
        # This allows product_cap to match sec:ProductCap, pnpx:ProductCap, etc.
        camel_name = snake_to_camel(name)
        for child in element:
            local_name = cls._get_local_name(child.tag)
            
            # Try exact match
            if local_name == camel_name or local_name == name:
                return child
            
            # Try case-insensitive match
            if local_name.lower() == camel_name.lower() or local_name.lower() == name.lower():
                return child

        return None

    @classmethod
    def _find_elements(cls, element: ET.Element, name: str, namespaces: dict) -> List[ET.Element]:
        """Find multiple child elements, handling namespaces properly"""
        # Method 1: Try with namespace prefix if provided
        if ':' in name:
            prefix, local = name.split(':', 1)
            if prefix in namespaces:
                full_name = f"{{{namespaces[prefix]}}}{local}"
                children = element.findall(full_name)
                if children:
                    return children

        # Method 2: Try with default namespace
        if '' in namespaces:
            full_name = f"{{{namespaces['']}}}{name}"
            children = element.findall(full_name)
            if children:
                return children

        # Method 3: Try without namespace
        children = element.findall(name)
        if children:
            return children

        # Method 4: Search across ALL namespaces for matching local name
        camel_name = snake_to_camel(name)
        results = []
        for child in element:
            local_name = cls._get_local_name(child.tag)
            
            if local_name == camel_name or local_name == name:
                results.append(child)
            elif local_name.lower() == camel_name.lower() or local_name.lower() == name.lower():
                results.append(child)

        return results

    @classmethod
    def _get_local_name(cls, tag: str) -> str:
        """Extract local name from a tag, stripping namespace"""
        if '}' in tag:
            return tag.split('}', 1)[1]
        return tag

    @classmethod
    def _get_attribute_value(cls, element: ET.Element, field_name: str) -> Optional[str]:
        """
        Try to get value from element attributes.
        Tries multiple name variations (camelCase, snake_case, etc.)
        """
        # Try direct attribute name
        if field_name in element.attrib:
            return element.attrib[field_name]
        
        # Try camelCase
        camel = snake_to_camel(field_name)
        if camel in element.attrib:
            return element.attrib[camel]
        
        # Try lowercase
        lower = field_name.lower()
        if lower in element.attrib:
            return element.attrib[lower]
        
        # Try case-insensitive search
        for attr_name, attr_value in element.attrib.items():
            if attr_name.lower() == lower:
                return attr_value
        
        return None

    @classmethod
    def _get_xml_names(cls, field_name: str, namespaces: dict) -> List[str]:
        """
        Generate possible XML element names for a field.
        Now returns just camelCase conversions and lets _find_element 
        search across all namespaces.
        """
        names = []

        # Standard camelCase conversion
        camel = snake_to_camel(field_name)
        names.append(camel)

        # Try exact uppercase matches (for UDN, SCPDURL, etc.)
        upper = field_name.upper().replace('_', '')
        if upper != camel.upper():
            names.append(upper)

        # Also try variations with different capitalization
        # For example: x_compatible_id -> X_compatibleId, XCompatibleId, etc.
        if field_name.startswith('x_'):
            # Try X_camelCase
            names.append('X_' + snake_to_camel(field_name[2:]))
            # Try XCamelCase
            names.append('X' + snake_to_camel(field_name[2:]).capitalize())

        # Try the original field name as last resort
        names.append(field_name)

        return names

    @classmethod
    def _parse_value(cls, text: str, target_type: Type) -> Any:
        """Parse text content to the target type"""
        if text is None:
            return None

        # Handle Optional types
        origin = get_origin(target_type)
        if origin is type(Optional):
            args = get_args(target_type)
            target_type = args[0] if args else str

        if target_type == int:
            return int(text)
        elif target_type == float:
            return float(text)
        elif target_type == bool:
            return text.lower() in ('true', '1', 'yes')
        else:
            return text
        

def snake_to_camel(name: str) -> str:
    """Convert snake_case to camelCase for XML matching"""
    components = name.split('_')
    return components[0] + ''.join(x.title() for x in components[1:])

def camel_to_snake(name: str) -> str:
    """Convert camelCase to snake_case"""
    result = []
    for i, char in enumerate(name):
        if char.isupper() and i > 0:
            # Don't add underscore if previous char was also uppercase (e.g., "URLPath")
            if i + 1 < len(name) and name[i + 1].islower():
                result.append('_')
            elif not name[i - 1].isupper():
                result.append('_')
        result.append(char.lower())
    return ''.join(result)

# Debug helper
def debug_element(element: ET.Element, indent=0):
    """Print element structure for debugging"""
    prefix = "  " * indent
    tag = element.tag
    if '}' in tag:
        ns, local = tag.split('}', 1)
        print(f"{prefix}{local} (ns: {ns[1:]})")
    else:
        print(f"{prefix}{tag}")
    
    for child in element:
        debug_element(child, indent + 1)