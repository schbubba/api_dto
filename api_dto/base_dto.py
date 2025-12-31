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
    def to_json(self, indent=None) -> str:
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
        """
        if namespaces is None:
            namespaces = cls._extract_all_namespaces(element)

        kwargs = {}
        json_field_values = {}  # Store @json_field values separately

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

        # Also process @json_field properties
        for attr_name, attr_value in cls.__dict__.items():
            # Check if it's a JsonFieldDescriptor (or whatever you named it)
            if hasattr(attr_value, 'is_stored_as_string'):
                field_type = attr_value.type
                actual_type = cls._unwrap_optional(field_type)
                
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

        return instance

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
        # Build reverse mapping for lookup
        uri_to_prefix = {v: k for k, v in namespaces.items()}

        # Method 1: Try with namespace prefix
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

        # Method 4: Brute force - check all children by local name only
        for child in element:
            # Strip namespace from tag
            tag = child.tag
            if '}' in tag:
                tag = tag.split('}', 1)[1]

            # Try exact match
            if tag == name:
                return child

            # Try case-insensitive match
            if tag.lower() == name.lower():
                return child

            # Try matching against the field name variations
            # For fields like pnpx_x_compatible_id, check if tag matches X_compatibleId
            if '_' in name:
                parts = name.split('_')
                # Try with first part as namespace
                if len(parts) > 1:
                    potential_local = snake_to_camel('_'.join(parts[1:]))
                    if tag == potential_local:
                        return child

        return None

    @classmethod
    def _find_elements(cls, element: ET.Element, name: str, namespaces: dict) -> List[ET.Element]:
        """Find multiple child elements, handling namespaces properly"""
        # Method 1: Try with namespace prefix
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

        # Method 4: Brute force - check all children by local name
        results = []
        for child in element:
            tag = child.tag
            if '}' in tag:
                tag = tag.split('}', 1)[1]

            # Try exact match
            if tag == name:
                results.append(child)
                continue

            # Try case-insensitive
            if tag.lower() == name.lower():
                results.append(child)
                continue

            # Try matching field name variations
            if '_' in name:
                parts = name.split('_')
                if len(parts) > 1:
                    potential_local = snake_to_camel('_'.join(parts[1:]))
                    if tag == potential_local:
                        results.append(child)

        return results

    @classmethod
    def _get_xml_names(cls, field_name: str, namespaces: dict) -> List[str]:
        """Generate possible XML element names for a field"""
        names = []

        # Handle fields with namespace prefixes (e.g., sec_product_cap -> ProductCap)
        # We'll search by local name only since namespace might vary
        parts = field_name.split('_')

        if len(parts) > 1:
            # Check if first part might be a namespace prefix
            potential_prefix = parts[0]
            if potential_prefix in namespaces:
                # It's a known namespace prefix
                local_name = snake_to_camel('_'.join(parts[1:]))
                names.append(f"{potential_prefix}:{local_name}")
                # Also add just the local name for brute-force matching
                names.append(local_name)
            else:
                # Not a namespace, try other combinations
                for i in range(1, len(parts)):
                    potential_prefix = '_'.join(parts[:i])
                    if potential_prefix in namespaces:
                        local_name = snake_to_camel('_'.join(parts[i:]))
                        names.append(f"{potential_prefix}:{local_name}")
                        names.append(local_name)

        # Standard camelCase conversion (full field name)
        camel = snake_to_camel(field_name)
        names.append(camel)

        # For fields like pnpx_x_compatible_id, also try X_compatibleId
        if field_name.count('_') > 1:
            # Try converting just the part after first underscore
            after_first = '_'.join(field_name.split('_')[1:])
            names.append(snake_to_camel(after_first))
            # Also try with underscores preserved for X_ prefixes
            if after_first.startswith('x_'):
                names.append('X_' + snake_to_camel(after_first[2:]))

        # Try exact uppercase matches (for UDN, SCPDURL, etc.)
        upper = field_name.upper().replace('_', '')
        if upper != camel.upper():
            names.append(upper)

        # Try the original field name
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

# Example usage with your models
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
