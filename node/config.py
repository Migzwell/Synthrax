"""Reads .env."""
import os

try:                                   # python-dotenv is optional: plain environment variables also work
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DEFAULT_URLS = "carehome=http://localhost:8001,gp=http://localhost:8002,pharmacy=http://localhost:8003"
NODE_URLS: dict[str, str] = dict(p.split("=", 1) for p in os.getenv("NODE_URLS", DEFAULT_URLS).split(","))
CLOCK_URL = os.getenv("CLOCK_URL", "http://localhost:8000")
SYNC_INTERVAL_SECONDS = float(os.getenv("SYNC_INTERVAL_SECONDS", "2"))


def peers_of(node_id: str) -> dict[str, str]:
    """Every other site's address, e.g. peers_of('carehome') -> {'gp': ..., 'pharmacy': ...}."""
    return {n: url for n, url in NODE_URLS.items() if n != node_id}


def port_of(node_id: str) -> int:
    return int(NODE_URLS[node_id].rsplit(":", 1)[1])