from typing import Dict, Type

class StoreRegistry:
    _registry: Dict[str, Type] = {}

    @classmethod
    def register_store(cls, name: str, store_class: Type):
        cls._registry[name] = store_class

    @classmethod
    def get_store(cls, name: str) -> Type:
        return cls._registry.get(name)

    @classmethod
    def list_stores(cls) -> Dict[str, Type]:
        return cls._registry
    
