from typing import Dict, Type

class StoreRegistry:
    _registry: Dict[str, Type] = {}

    # Register a store class with a given name
    @classmethod
    def register_store(cls, name: str, store_class: Type):
        cls._registry[name] = store_class

    # Retrieve a store class by name
    @classmethod
    def get_store(cls, name: str) -> Type:
        return cls._registry.get(name)
    
    # List all registered stores
    @classmethod
    def list_stores(cls) -> Dict[str, Type]:
        return cls._registry
    
