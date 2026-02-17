from typing import Dict, Type

# A registry to manage different store classes
class StoreRegistry:
    _registry: Dict[str, Type] = {}

    # Register a store class with a given name
    @classmethod
    def register_store(cls, store_type: str):
        def decorator(wrapper_class: Type):
            cls._registry[store_type.lower()] = wrapper_class
            return wrapper_class
        return decorator
    

    # Retrieve a store class by name
    @classmethod
    def get_store(cls, name: str) -> Type:
        return cls._registry.get(name)
    
    # List all registered stores
    @classmethod
    def list_stores(cls) -> Dict[str, Type]:
        return cls._registry
    
