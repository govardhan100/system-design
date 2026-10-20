"""Consistent Hash Ring implementation with virtual nodes and replication."""

import bisect
import hashlib
from typing import Any, Dict, List, Optional, Set, Tuple

from app.node import Node

RING_SIZE = 2**32  # 32-bit unsigned hash space: [0, 4,294,967,295]


def fnv1a_32(data: str) -> int:
    """32-bit FNV-1a non-cryptographic hash function."""
    hval = 0x811C9DC5
    fnv_32_prime = 0x01000193
    uint32_max = 2**32
    for byte in data.encode("utf-8"):
        hval = (hval ^ byte) * fnv_32_prime
        hval &= uint32_max - 1
    return hval


def md5_32(data: str) -> int:
    """MD5 truncated to 32-bit unsigned integer (Ketama-style)."""
    digest = hashlib.md5(data.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], byteorder="big")


class ConsistentHashRing:
    """
    Consistent Hash Ring utilizing virtual nodes and binary search.
    Provides O(log(N * V)) key lookup and minimum key movement on topology changes.
    """

    def __init__(
        self,
        hash_fn: str = "md5_32",
        default_vnodes: int = 100,
        replication_factor: int = 3,
        bounded_load_factor: Optional[float] = None,
    ):
        self.hash_algo_name = hash_fn
        self._hash_fn = md5_32 if hash_fn == "md5_32" else fnv1a_32
        self.default_vnodes = max(1, default_vnodes)
        self.replication_factor = max(1, replication_factor)
        self.bounded_load_factor = bounded_load_factor

        # Ring data structures
        self._ring: Dict[int, str] = {}  # token -> node_id
        self._sorted_tokens: List[int] = []  # Sorted array of 32-bit token integers
        self._nodes: Dict[str, Node] = {}  # node_id -> Node instance
        self._node_tokens: Dict[str, List[int]] = {}  # node_id -> list of tokens

    @property
    def total_nodes(self) -> int:
        return len(self._nodes)

    @property
    def total_vnodes(self) -> int:
        return len(self._sorted_tokens)

    def hash(self, value: str) -> int:
        """Hash any string value into the [0, RING_SIZE - 1] space."""
        return self._hash_fn(value) % RING_SIZE

    def add_node(
        self,
        node_id: str,
        label: Optional[str] = None,
        weight: int = 1,
        vnodes: Optional[int] = None,
        color: Optional[str] = None,
        rebalance: bool = True,
    ) -> Dict[str, Any]:
        """
        Add a physical node with virtual nodes into the ring.
        Optionally migrates keys from existing nodes to the new node.
        """
        if node_id in self._nodes:
            raise ValueError(f"Node '{node_id}' already exists in the ring")

        actual_vnodes = (vnodes or self.default_vnodes) * max(1, weight)
        node = Node(
            node_id=node_id,
            label=label,
            weight=weight,
            vnodes=actual_vnodes,
            color=color,
        )
        self._nodes[node_id] = node
        self._node_tokens[node_id] = []

        # Generate virtual node tokens
        for i in range(actual_vnodes):
            vnode_key = f"{node_id}#vn{i}"
            token = self.hash(vnode_key)
            # Handle token collision on ring
            while token in self._ring:
                vnode_key += "_alt"
                token = self.hash(vnode_key)

            self._ring[token] = node_id
            self._node_tokens[node_id].append(token)
            bisect.insort(self._sorted_tokens, token)

        migration_report: Dict[str, Any] = {
            "node_id": node_id,
            "vnodes_added": actual_vnodes,
            "keys_moved": 0,
            "transfers": [],
        }

        # Rebalance keys across existing nodes if requested
        if rebalance and len(self._nodes) > 1:
            all_keys: List[Tuple[str, str, Any]] = []
            for n_id, n in self._nodes.items():
                if n_id != node_id:
                    for k, v in list(n.storage.items()):
                        all_keys.append((k, n_id, v))

            transfers: List[Dict[str, Any]] = []
            for k, from_node, val in all_keys:
                primary_node = self.get_node(k)
                if primary_node and primary_node.node_id == node_id:
                    # Move key from source node to new node
                    self._nodes[from_node].delete(k)
                    node.put(k, val)
                    transfers.append(
                        {
                            "key": k,
                            "from_node": from_node,
                            "to_node": node_id,
                            "token": self.hash(k),
                        }
                    )

            migration_report["keys_moved"] = len(transfers)
            migration_report["transfers"] = transfers[:50]  # Cap payload size

        return migration_report

    def remove_node(self, node_id: str, rebalance: bool = True) -> Dict[str, Any]:
        """
        Remove a physical node and its virtual nodes from the ring.
        Reassigns keys to next clockwise successor nodes.
        """
        if node_id not in self._nodes:
            raise ValueError(f"Node '{node_id}' does not exist in the ring")

        node = self._nodes[node_id]
        tokens_to_remove = self._node_tokens.get(node_id, [])
        orphan_keys = list(node.storage.items())

        # Remove tokens from ring
        for token in tokens_to_remove:
            if token in self._ring:
                del self._ring[token]

        # Re-filter sorted tokens
        tokens_set = set(tokens_to_remove)
        self._sorted_tokens = [t for t in self._sorted_tokens if t not in tokens_set]

        del self._nodes[node_id]
        del self._node_tokens[node_id]

        migration_report: Dict[str, Any] = {
            "node_id": node_id,
            "vnodes_removed": len(tokens_to_remove),
            "keys_moved": 0,
            "transfers": [],
        }

        if rebalance and self._sorted_tokens and orphan_keys:
            transfers: List[Dict[str, Any]] = []
            for k, v in orphan_keys:
                new_owner = self.get_node(k)
                if new_owner:
                    new_owner.put(k, v)
                    transfers.append(
                        {
                            "key": k,
                            "from_node": node_id,
                            "to_node": new_owner.node_id,
                            "token": self.hash(k),
                        }
                    )
            migration_report["keys_moved"] = len(transfers)
            migration_report["transfers"] = transfers[:50]

        return migration_report

    def get_token_index(self, token: int) -> int:
        """Find index of the first token >= given token using binary search."""
        if not self._sorted_tokens:
            return -1
        idx = bisect.bisect_right(self._sorted_tokens, token)
        if idx == len(self._sorted_tokens):
            return 0  # Wrap around to start of circle
        return idx

    def get_node(self, key: str) -> Optional[Node]:
        """Look up the primary physical node responsible for the key."""
        if not self._sorted_tokens:
            return None

        token = self.hash(key)
        idx = self.get_token_index(token)
        assigned_token = self._sorted_tokens[idx]
        node_id = self._ring[assigned_token]
        candidate_node = self._nodes.get(node_id)

        # Check bounded loads if enabled
        if self.bounded_load_factor and candidate_node:
            total_keys = sum(n.key_count for n in self._nodes.values())
            if total_keys > 0 and len(self._nodes) > 1:
                avg_keys = total_keys / len(self._nodes)
                cap = max(1.0, avg_keys * self.bounded_load_factor)
                if candidate_node.key_count >= cap:
                    # Spillover to next distinct physical node
                    replicas = self.get_nodes(key, count=2)
                    if len(replicas) > 1:
                        return replicas[1]

        return candidate_node

    def get_nodes(self, key: str, count: Optional[int] = None) -> List[Node]:
        """
        Get primary + replica nodes for a key.
        Guarantees distinct physical nodes by walking clockwise on the ring.
        """
        if not self._sorted_tokens:
            return []

        target_count = min(count or self.replication_factor, len(self._nodes))
        token = self.hash(key)
        start_idx = self.get_token_index(token)

        selected_nodes: List[Node] = []
        seen_node_ids: Set[str] = set()

        total_tokens = len(self._sorted_tokens)
        for step in range(total_tokens):
            curr_idx = (start_idx + step) % total_tokens
            curr_token = self._sorted_tokens[curr_idx]
            curr_node_id = self._ring[curr_token]

            if curr_node_id not in seen_node_ids:
                seen_node_ids.add(curr_node_id)
                node_obj = self._nodes.get(curr_node_id)
                if node_obj:
                    selected_nodes.append(node_obj)

            if len(selected_nodes) >= target_count:
                break

        return selected_nodes

    def route_key(self, key: str) -> Dict[str, Any]:
        """Provide detailed diagnostic routing information for a key."""
        token = self.hash(key)
        if not self._sorted_tokens:
            return {
                "key": key,
                "token": token,
                "angle_degrees": (token / RING_SIZE) * 360.0,
                "primary_node": None,
                "replicas": [],
            }

        idx = self.get_token_index(token)
        successor_token = self._sorted_tokens[idx]
        primary_node_id = self._ring[successor_token]
        nodes = self.get_nodes(key, self.replication_factor)

        return {
            "key": key,
            "token": token,
            "angle_degrees": round((token / RING_SIZE) * 360.0, 3),
            "successor_token": successor_token,
            "successor_angle": round((successor_token / RING_SIZE) * 360.0, 3),
            "primary_node": self._nodes[primary_node_id].to_dict() if primary_node_id in self._nodes else None,
            "replicas": [n.to_dict() for n in nodes[1:]],
        }

    def get_partition_ownership(self) -> List[Dict[str, Any]]:
        """
        Calculate exact mathematical percentage of the ring owned by each node.
        Each token T_i owns the arc (T_{i-1}, T_i].
        """
        if not self._sorted_tokens:
            return []

        total_tokens = len(self._sorted_tokens)
        node_arc_sums: Dict[str, int] = {nid: 0 for nid in self._nodes}

        for i in range(total_tokens):
            curr_token = self._sorted_tokens[i]
            prev_token = self._sorted_tokens[(i - 1) % total_tokens]
            node_id = self._ring[curr_token]

            if i == 0:
                # Wrap-around arc: (T_{M-1}, RING_SIZE - 1] + [0, T_0]
                arc_len = (RING_SIZE - prev_token) + curr_token
            else:
                arc_len = curr_token - prev_token

            node_arc_sums[node_id] = node_arc_sums.get(node_id, 0) + arc_len

        results = []
        for nid, node in self._nodes.items():
            arc = node_arc_sums.get(nid, 0)
            share = (arc / RING_SIZE) * 100.0
            results.append(
                {
                    "node_id": nid,
                    "label": node.label,
                    "color": node.color,
                    "vnodes": len(self._node_tokens.get(nid, [])),
                    "arc_sum": arc,
                    "ring_percentage": round(share, 2),
                    "key_count": node.key_count,
                }
            )

        return sorted(results, key=lambda x: x["node_id"])

    def get_state(self) -> Dict[str, Any]:
        """Return complete snapshot of the ring for UI visualizer."""
        # Sample or return virtual nodes for rendering
        sample_vnodes = []
        # Return up to 200 virtual nodes for smooth rendering
        step = max(1, len(self._sorted_tokens) // 200)
        for i in range(0, len(self._sorted_tokens), step):
            tok = self._sorted_tokens[i]
            nid = self._ring[tok]
            node = self._nodes.get(nid)
            sample_vnodes.append(
                {
                    "token": tok,
                    "angle": round((tok / RING_SIZE) * 360.0, 3),
                    "node_id": nid,
                    "color": node.color if node else "#999",
                }
            )

        total_keys = sum(n.key_count for n in self._nodes.values())
        return {
            "total_nodes": self.total_nodes,
            "total_vnodes": self.total_vnodes,
            "total_keys": total_keys,
            "hash_algorithm": self.hash_algo_name,
            "default_vnodes": self.default_vnodes,
            "replication_factor": self.replication_factor,
            "nodes": [n.to_dict() for n in self._nodes.values()],
            "partitions": self.get_partition_ownership(),
            "vnode_samples": sample_vnodes,
        }

    def clear_keys(self) -> None:
        """Clear all stored keys across all nodes."""
        for node in self._nodes.values():
            node.clear()
