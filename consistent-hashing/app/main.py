"""FastAPI application for Consistent Hashing Lab."""

import os
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from app.benchmark import run_comparison_benchmark
from app.ring import ConsistentHashRing

BASE_DIR = Path(__file__).resolve().parent.parent

app = FastAPI(
    title="Consistent Hashing Lab",
    description="Interactive demonstration and visualization of Consistent Hashing.",
    version="1.0.0",
)

DEFAULT_VNODES = int(os.getenv("DEFAULT_VNODES", "100"))
REPLICATION_FACTOR = int(os.getenv("REPLICATION_FACTOR", "3"))
HASH_ALGO = os.getenv("HASH_ALGORITHM", "fnv1a_32")

# Global in-memory cluster ring instance
ring = ConsistentHashRing(
    hash_fn=HASH_ALGO,
    default_vnodes=DEFAULT_VNODES,
    replication_factor=REPLICATION_FACTOR,
)


def seed_default_nodes():
    """Seed initial 4 nodes with curated colors and labels."""
    default_nodes = [
        {"node_id": "node-alpha", "label": "Node Alpha", "color": "#10b981", "weight": 1},
        {"node_id": "node-beta", "label": "Node Beta", "color": "#3b82f6", "weight": 1},
        {"node_id": "node-gamma", "label": "Node Gamma", "color": "#f59e0b", "weight": 1},
        {"node_id": "node-delta", "label": "Node Delta", "color": "#ef4444", "weight": 1},
    ]
    for n in default_nodes:
        ring.add_node(
            node_id=n["node_id"],
            label=n["label"],
            weight=n["weight"],
            vnodes=DEFAULT_VNODES,
            color=n["color"],
            rebalance=False,
        )


# Seed on module load
seed_default_nodes()


# --- Pydantic Request Models ---
class AddNodeRequest(BaseModel):
    node_id: str = Field(..., min_length=1, max_length=50)
    label: Optional[str] = None
    vnodes: Optional[int] = Field(None, ge=1, le=500)
    weight: int = Field(1, ge=1, le=10)
    color: Optional[str] = None


class PutKeyRequest(BaseModel):
    key: str = Field(..., min_length=1, max_length=200)
    value: Optional[str] = None


class PopulateRequest(BaseModel):
    count: int = Field(500, ge=10, le=10000)
    prefix: str = Field("key", max_length=50)


class BenchmarkRequest(BaseModel):
    num_keys: int = Field(10000, ge=100, le=50000)
    initial_nodes: int = Field(5, ge=3, le=15)
    vnodes_count: int = Field(150, ge=10, le=300)


# --- HTML Page Routes ---
@app.get("/", response_class=HTMLResponse)
def index():
    return demo_page()


@app.get("/demo", response_class=HTMLResponse)
def demo_page():
    demo_file = BASE_DIR / "demo.html"
    if not demo_file.exists():
        raise HTTPException(status_code=404, detail="demo.html not found")
    return FileResponse(demo_file)


@app.get("/architecture", response_class=HTMLResponse)
def architecture_page():
    arch_file = BASE_DIR / "architecture.html"
    if not arch_file.exists():
        raise HTTPException(status_code=404, detail="architecture.html not found")
    return FileResponse(arch_file)


# --- API Routes ---
@app.get("/api/ring/state")
def get_ring_state() -> Dict[str, Any]:
    return ring.get_state()


@app.post("/api/ring/nodes")
def add_node(req: AddNodeRequest) -> Dict[str, Any]:
    try:
        report = ring.add_node(
            node_id=req.node_id,
            label=req.label,
            weight=req.weight,
            vnodes=req.vnodes,
            color=req.color,
            rebalance=True,
        )
        return {"status": "success", "report": report, "state": ring.get_state()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/ring/nodes/{node_id}")
def remove_node(node_id: str) -> Dict[str, Any]:
    try:
        report = ring.remove_node(node_id, rebalance=True)
        return {"status": "success", "report": report, "state": ring.get_state()}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/ring/keys")
def insert_key(req: PutKeyRequest) -> Dict[str, Any]:
    primary_node = ring.get_node(req.key)
    if not primary_node:
        raise HTTPException(status_code=503, detail="No active nodes in ring")

    primary_node.put(req.key, req.value)
    routing_info = ring.route_key(req.key)
    return {
        "status": "stored",
        "routing": routing_info,
        "key_count": ring.get_state()["total_keys"],
    }


@app.get("/api/ring/keys/{key}")
def lookup_key(key: str) -> Dict[str, Any]:
    routing = ring.route_key(key)
    if not routing["primary_node"]:
        raise HTTPException(status_code=404, detail="No nodes available on ring")
    node_obj = ring._nodes.get(routing["primary_node"]["node_id"])
    value = node_obj.get(key) if node_obj else None
    return {
        "key": key,
        "routing": routing,
        "found": value is not None,
        "value": value,
    }


@app.post("/api/ring/populate")
def populate_keys(req: PopulateRequest) -> Dict[str, Any]:
    if ring.total_nodes == 0:
        raise HTTPException(status_code=400, detail="Cannot populate keys into empty ring")

    inserted = 0
    for i in range(req.count):
        k = f"{req.prefix}_{i}_{i * 41 % 997}"
        node = ring.get_node(k)
        if node:
            node.put(k, f"payload_{i}")
            inserted += 1

    return {
        "inserted": inserted,
        "total_keys": sum(n.key_count for n in ring._nodes.values()),
        "partitions": ring.get_partition_ownership(),
    }


@app.post("/api/ring/clear-keys")
def clear_keys() -> Dict[str, Any]:
    ring.clear_keys()
    return {"status": "cleared", "total_keys": 0}


@app.post("/api/ring/reset")
def reset_ring() -> Dict[str, Any]:
    global ring
    ring = ConsistentHashRing(
        hash_fn=HASH_ALGO,
        default_vnodes=DEFAULT_VNODES,
        replication_factor=REPLICATION_FACTOR,
    )
    seed_default_nodes()
    return {"status": "reset", "state": ring.get_state()}


@app.post("/api/benchmark")
def run_benchmark(req: BenchmarkRequest) -> Dict[str, Any]:
    return run_comparison_benchmark(
        num_keys=req.num_keys,
        initial_nodes=req.initial_nodes,
        vnodes_count=req.vnodes_count,
    )


@app.get("/healthz")
def healthz():
    return {"status": "ok", "nodes": ring.total_nodes, "vnodes": ring.total_vnodes}


@app.get("/readyz")
def readyz():
    if ring.total_nodes > 0:
        return {"status": "ready"}
    raise HTTPException(status_code=503, detail="Cluster has 0 nodes")
