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
        """
        import re
        from typing import get_args
        from dataclasses import fields, is_dataclass
        
        def strip_ns(tag: str) -> str:
            """Remove namespace from an XML tag."""
            return tag.split("}", 1)[1] if "}" in tag else tag

        def camel_to_snake(name: str) -> str:
            s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
            return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()

        def is_complex(elem):
            return len(list(elem)) > 0
        
        def auto_parse_value(text: str, target_type: Type = None) -> Any:
            """
            Automatically parse a string value to the target type or infer type.
            """
            if text is None:
                return None
            
            text = text.strip()
            if not text:
                return None
            
            # If we have a target type, use it
            if target_type:
                origin = get_origin(target_type)
                if origin is Union:
                    non_none = [t for t in get_args(target_type) if t is not type(None)]
                    target_type = non_none[0] if non_none else None
                
                if target_type == int:
                    return int(text)
                elif target_type == float:
                    return float(text)
                elif target_type == bool:
                    return text.lower() in ('true', '1', 'yes')
                elif target_type == str:
                    return text
            
            # Otherwise, infer the type
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

        def set_properties(obj, elem: ET.Element, is_root_call: bool = True):
            # Only search for the object by name on the initial call
            if is_root_call:
                xml_obj = elem.findall(f".//{{*}}{type(obj).__name__.lower()}")
                elements_to_iterate = xml_obj if xml_obj else [elem]
            else:
                elements_to_iterate = [elem]

            # Get annotations (works for both dataclasses and regular classes)
            annotations = getattr(type(obj), "__annotations__", {})
            
            # Get dataclass fields if this is a dataclass
            dataclass_fields = {}
            if is_dataclass(type(obj)):
                dataclass_fields = {f.name: f.type for f in fields(type(obj))}

            for el in elements_to_iterate:
                for child in el:
                    tag = camel_to_snake(strip_ns(child.tag))

                    # Get the expected type for this field (from dataclass or annotations)
                    expected_type = dataclass_fields.get(tag) or annotations.get(tag, None)

                    # --- simple scalar ---
                    if not is_complex(child):
                        value = auto_parse_value(child.text, expected_type)
                        setattr(obj, tag, value)
                        continue

                    # --- complex object ---
                    attr_type = expected_type
                    current_val = getattr(obj, tag, None)
                    origin = getattr(attr_type, "__origin__", None) if attr_type else None

                    # handle Optional[T]
                    if origin is Union:
                        non_none = [t for t in get_args(attr_type) if t is not type(None)]
                        attr_type = non_none[0] if non_none else None
                        origin = getattr(attr_type, "__origin__", None)

                    # --- LIST ---
                    if origin in (list, List):
                        item_type = get_args(attr_type)[0] if attr_type else None
                        if current_val is None:
                            current_val = []
                            setattr(obj, tag, current_val)

                        # Check if 'child' is the list container or an individual item
                        if strip_ns(child.tag).lower() == tag.rstrip('s').lower() or len(list(child)) == 0 or strip_ns(list(child)[0].tag).lower() != tag.rstrip('s').lower():
                            # 'child' IS the list item itself
                            item_obj = item_type() if item_type else cls._create_dynamic_obj()
                            current_val.append(item_obj)
                            
                            # map attributes
                            for key in child.attrib.keys():
                                attr_tag = camel_to_snake(strip_ns(key))
                                attr_value = child.attrib[key]
                                # Get type hint for this attribute if item_type has annotations
                                item_annotations = getattr(item_type, "__annotations__", {}) if item_type else {}
                                attr_expected_type = item_annotations.get(attr_tag, None)
                                setattr(item_obj, attr_tag, auto_parse_value(attr_value, attr_expected_type))
                            
                            # map child elements
                            for field in child:
                                field_tag = camel_to_snake(strip_ns(field.tag))
                                if is_complex(field):
                                    sub_attr_type = getattr(item_type, "__annotations__", {}).get(field_tag, None) if item_type else None
                                    sub_obj = sub_attr_type() if sub_attr_type else cls._create_dynamic_obj()
                                    setattr(item_obj, field_tag, sub_obj)
                                    set_properties(sub_obj, field, is_root_call=False)
                                else:
                                    # Get type hint for this field
                                    item_annotations = getattr(item_type, "__annotations__", {}) if item_type else {}
                                    field_expected_type = item_annotations.get(field_tag, None)
                                    setattr(item_obj, field_tag, auto_parse_value(field.text, field_expected_type))
                        else:
                            # 'child' is the container
                            for list_item_elem in child:
                                item_obj = item_type() if item_type else cls._create_dynamic_obj()
                                current_val.append(item_obj)

                                # map attributes
                                for key in list_item_elem.attrib.keys():
                                    attr_tag = camel_to_snake(strip_ns(key))
                                    attr_value = list_item_elem.attrib[key]
                                    item_annotations = getattr(item_type, "__annotations__", {}) if item_type else {}
                                    attr_expected_type = item_annotations.get(attr_tag, None)
                                    setattr(item_obj, attr_tag, auto_parse_value(attr_value, attr_expected_type))

                                # map child elements
                                for field in list_item_elem:
                                    field_tag = camel_to_snake(strip_ns(field.tag))
                                    if is_complex(field):
                                        sub_attr_type = getattr(item_type, "__annotations__", {}).get(field_tag, None) if item_type else None
                                        sub_obj = sub_attr_type() if sub_attr_type else cls._create_dynamic_obj()
                                        setattr(item_obj, field_tag, sub_obj)
                                        set_properties(sub_obj, field, is_root_call=False)
                                    else:
                                        item_annotations = getattr(item_type, "__annotations__", {}) if item_type else {}
                                        field_expected_type = item_annotations.get(field_tag, None)
                                        setattr(item_obj, field_tag, auto_parse_value(field.text, field_expected_type))
                        continue

                    # --- SINGLE COMPLEX OBJECT ---
                    if current_val is None:
                        sub_obj = attr_type() if attr_type else cls._create_dynamic_obj()
                        setattr(obj, tag, sub_obj)
                    else:
                        sub_obj = current_val

                    set_properties(sub_obj, child, is_root_call=False)

        # Create instance and populate it
        obj = cls()
        set_properties(obj, element)
        return obj

    @classmethod
    def _create_dynamic_obj(cls):
        """Create a dynamic object that can have any attributes set"""
        class DynamicDTO(BaseDTO): pass
        return DynamicDTO()

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