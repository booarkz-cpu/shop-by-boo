"""Node autoscaling against the real Hetzner Cloud API (workflow «Hetzner live», run by hand).

Skipped unless HETZNER_API_TOKEN is set. Creates the cheapest server with the shop's cloud-init, registers it in a
stand-in panel, checks the server exists and has an address, then deletes it — the run costs one hour of the
smallest server. The panel side (create_node, delete_node, keygen) is covered by test_remnawave_live.py."""
import os
from datetime import datetime

import pytest

from app import node_autoscale

pytestmark = pytest.mark.skipif(not os.environ.get("HETZNER_API_TOKEN"), reason="no Hetzner token")


class Panel:
    def __init__(self):
        self.nodes = []

    async def node_secret_key(self):
        return "ci-node-secret-not-used"

    async def create_node(self, node):
        self.nodes.append(node)
        return {"uuid": "ci-node"}

    async def delete_node(self, uuid):
        self.nodes = [n for n in self.nodes if n.get("uuid") != uuid]


@pytest.mark.asyncio
async def test_create_and_delete_a_server():
    config = {**node_autoscale.DEFAULT_CONFIG, "server_type": os.environ.get("HETZNER_SERVER_TYPE", "cx22"),
              "location": os.environ.get("HETZNER_LOCATION", "hel1"), "name_prefix": "corgi-ci"}
    panel = Panel()
    entry = await node_autoscale.scale_up(config, datetime.utcnow(), panel=panel)
    try:
        assert entry["server_id"] and entry["ip"], "Hetzner returned the server and its address"
        assert panel.nodes[0]["address"] == entry["ip"] and panel.nodes[0]["port"] == int(config["node_port"])
        server = await node_autoscale._hetzner("GET", f"/servers/{entry['server_id']}")
        assert server["server"]["labels"].get("corgi") == "autoscale"
    finally:
        await node_autoscale.scale_down(entry, panel=panel)
    import asyncio

    import httpx
    for _ in range(20):  # the delete is an action: the server disappears within seconds
        try:
            await node_autoscale._hetzner("GET", f"/servers/{entry['server_id']}")
        except httpx.HTTPStatusError as exc:
            assert exc.response.status_code == 404
            break
        await asyncio.sleep(3)
    else:
        pytest.fail("the server is still there after a minute — delete it in the Hetzner console")
