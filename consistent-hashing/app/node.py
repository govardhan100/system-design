"""Node representation for the consistent hashing ring."""

from typing import Any, Dict, List, Optional
import time


class Node:
    """Represents a physical cache or database node in the cluster."""

    def __init__(
        self,
        node_id: str,
        label: Optional[str] = None,
        weight: int = 1,
        vnodes: int = 100,
        color: Optional[str] = None,
    ):
        self.node_id: str = node_id
        self.label: str = label or node_id
        self.weight: int = max(1, weight)
        self.vnodes: int = max(1, vnodes)
        self.color: str = color or "#2563eb"
        self.status: str = "active"  # "active", "draining", "crashed"

        # In-memory storage of keys mapped to this node
        self.storage: Dict[str, Any] = {}

        # Runtime telemetry
        self.read_count: int = 0
        self.write_count: int = 0
        self.created_at: float = time.time()

    @property
    def key_count(self) -> int:
        return len(self.storage)

    def put(self, key: str, value: Any = None) -> None:
        self.storage[key] = value if value is not None else f"val_{key}"
        self.write_count += 1

    def get(self, key: str) -> Optional[Any]:
        self.read_count += 1
        return self.storage.get(key)

    def delete(self, key: str) -> bool:
        if key in self.storage:
            del self.storage[key]
            return True
        return False

    def clear(self) -> None:
        self.storage.clear()

    def get_keys(self) -> List[str]:
        return list(self.storage.keys())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "label": self.label,
            "weight": self.weight,
            "vnodes": self.vnodes,
            "color": self.color,
            "status": self.status,
            "key_count": self.key_count,
            "read_count": self.read_count,
            "write_count": self.write_count,
            "created_at": self.created_at,
        }
