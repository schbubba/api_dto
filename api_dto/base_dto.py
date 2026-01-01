from abc import abstractmethod

import types
import xml.etree.ElementTree as ET
from dataclasses import fields
from typing import Optional, Any, List, TypeVar, Type, Union, get_args, get_origin

T = TypeVar("T", bound="BaseDTO")

class BaseDTO:

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
    def from_xml_string(cls: Type[T], xml: str, namespaces: dict = None) -> T:
        root_element = ET.fromstring(xml)

        return cls.from_xml(root_element, namespaces)

    @classmethod
    def from_xml(cls: Type[T], element: ET.Element, namespaces: dict = None) -> T:
        """
        Automatically deserialize XML element to dataclass instance.
        Sets all XML attributes and child elements as object attributes,
        even if they're not defined in the dataclass.
        """
        if namespaces is None:
            namespaces = cls._extract_all_namespaces(element)

        kwargs = {}
        json_field_values = {}
        extra_attributes = {}  # Attributes not in the dataclass definition
        
        # Get all defined field names for quick lookup
        defined_fields = {f.name for f in fields(cls)}
        
        # Get all @json_field property names
        json_field_names = {
            attr_name for attr_name, attr_value in cls.__dict__.items()
            if hasattr(attr_value, 'is_stored_as_string')
        }

        # Process regular dataclass fields
        for field in fields(cls):
            field_name = field.name
            field_type = field.type

            # Handle xmlns attributes
            if field_name.startswith('xmlns'):
                if field_name == 'xmlns':
                    kwargs[field_name] = element.get('xmlns')
                else:
                    # Convert xmlns_sec -> xmlns:sec
                    attr_name = field_name.replace('_', ':', 1)
                    kwargs[field_name] = element.get(attr_name)
                continue

            # Unwrap Optional/Union types to get the actual type
            actual_type = cls._unwrap_optional(field_type)
            
            # First, try to get value from XML attributes
            attr_value = cls._get_attribute_value(element, field_name)
            if attr_value is not None:
                kwargs[field_name] = cls._parse_value(attr_value, actual_type)
                continue
            
            # Try multiple name variations for XML elements
            xml_names = cls._get_xml_names(field_name, namespaces)
            value = None

            # Check if it's a List type
            origin = get_origin(actual_type)
            if origin is list or origin is List:
                inner_type = get_args(actual_type)[0]
                inner_actual_type = cls._unwrap_optional(inner_type)
                value = []
                for xml_name in xml_names:
                    elements = cls._find_elements(element, xml_name, namespaces)
                    if elements:
                        if hasattr(inner_actual_type, 'from_xml'):
                            value = [inner_actual_type.from_xml(e, namespaces) for e in elements]
                        else:
                            value = [cls._parse_value(e.text, inner_actual_type) for e in elements]
                        break
                if not value:
                    value = []
            else:
                # Single element
                for xml_name in xml_names:
                    child = cls._find_element(element, xml_name, namespaces)
                    if child is not None:
                        # Nested dataclass
                        if hasattr(actual_type, 'from_xml'):
                            value = actual_type.from_xml(child, namespaces)
                        else:
                            value = cls._parse_value(child.text, actual_type)
                        break

            kwargs[field_name] = value

        # Process @json_field properties
        for attr_name, attr_value in cls.__dict__.items():
            if hasattr(attr_value, 'is_stored_as_string'):
                field_type = attr_value.type
                actual_type = cls._unwrap_optional(field_type)
                
                # First, try to get value from XML attributes
                attr_val = cls._get_attribute_value(element, attr_name)
                if attr_val is not None:
                    json_field_values[attr_name] = cls._parse_value(attr_val, actual_type)
                    continue
                
                xml_names = cls._get_xml_names(attr_name, namespaces)
                value = None

                # Check if it's a List type
                origin = get_origin(actual_type)
                if origin is list or origin is List:
                    inner_type = get_args(actual_type)[0]
                    inner_actual_type = cls._unwrap_optional(inner_type)
                    value = []
                    for xml_name in xml_names:
                        elements = cls._find_elements(element, xml_name, namespaces)
                        if elements:
                            if hasattr(inner_actual_type, 'from_xml'):
                                value = [inner_actual_type.from_xml(e, namespaces) for e in elements]
                            else:
                                value = [cls._parse_value(e.text, inner_actual_type) for e in elements]
                            break
                    if not value:
                        value = []
                else:
                    # Single element
                    for xml_name in xml_names:
                        child = cls._find_element(element, xml_name, namespaces)
                        if child is not None:
                            # Nested dataclass
                            if hasattr(actual_type, 'from_xml'):
                                value = actual_type.from_xml(child, namespaces)
                            else:
                                value = cls._parse_value(child.text, actual_type)
                            break

                json_field_values[attr_name] = value

        # Create instance with regular fields
        instance = cls(**kwargs)
        
        # Set @json_field properties after instantiation
        for field_name, value in json_field_values.items():
            setattr(instance, field_name, value)

        # Now process ALL XML attributes and set them dynamically
        for attr_name, attr_value in element.attrib.items():
            # Skip xmlns declarations
            if attr_name == 'xmlns' or attr_name.startswith('xmlns:'):
                continue
            
            # Convert attribute name to snake_case
            snake_name = camel_to_snake(attr_name)
            
            # Only set if not already processed
            if snake_name not in defined_fields and snake_name not in json_field_names:
                # Try to parse as int, float, or keep as string
                parsed_value = cls._auto_parse_value(attr_value)
                setattr(instance, snake_name, parsed_value)

        # Process ALL child elements and set them dynamically
        for child in element:
            local_name = cls._get_local_name(child.tag)
            snake_name = camel_to_snake(local_name)
            
            # Only set if not already processed
            if snake_name not in defined_fields and snake_name not in json_field_names:
                # Check if there are multiple elements with this name
                all_matching = [
                    c for c in element 
                    if cls._get_local_name(c.tag).lower() == local_name.lower()
                ]
                
                if len(all_matching) > 1:
                    # Multiple elements - create a list
                    if not hasattr(instance, snake_name):
                        value_list = []
                        for elem in all_matching:
                            if len(elem) > 0 or elem.attrib:
                                # Has children or attributes - recursively parse
                                value_list.append(cls._parse_element_dynamically(elem, namespaces))
                            else:
                                # Just text content
                                value_list.append(cls._auto_parse_value(elem.text))
                        setattr(instance, snake_name, value_list)
                else:
                    # Single element
                    if len(child) > 0 or child.attrib:
                        # Has children or attributes - recursively parse
                        value = cls._parse_element_dynamically(child, namespaces)
                    else:
                        # Just text content
                        value = cls._auto_parse_value(child.text)
                    setattr(instance, snake_name, value)

        return instance

    @classmethod
    def _parse_element_dynamically(cls, element: ET.Element, namespaces: dict) -> dict:
        """
        Parse an XML element into a dictionary when we don't have a defined DTO for it.
        """
        result = {}
        
        # Add all attributes
        for attr_name, attr_value in element.attrib.items():
            if attr_name != 'xmlns' and not attr_name.startswith('xmlns:'):
                snake_name = camel_to_snake(attr_name)
                result[snake_name] = cls._auto_parse_value(attr_value)
        
        # Add child elements
        for child in element:
            local_name = cls._get_local_name(child.tag)
            snake_name = camel_to_snake(local_name)
            
            # Check if there are multiple elements with this name
            all_matching = [
                c for c in element 
                if cls._get_local_name(c.tag).lower() == local_name.lower()
            ]
            
            if len(all_matching) > 1:
                if snake_name not in result:
                    result[snake_name] = []
                if len(child) > 0 or child.attrib:
                    result[snake_name].append(cls._parse_element_dynamically(child, namespaces))
                else:
                    result[snake_name].append(cls._auto_parse_value(child.text))
            else:
                if len(child) > 0 or child.attrib:
                    result[snake_name] = cls._parse_element_dynamically(child, namespaces)
                else:
                    result[snake_name] = cls._auto_parse_value(child.text)
        
        # If no children or attributes, just return the text
        if not result and element.text:
            return cls._auto_parse_value(element.text)
        
        return result

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