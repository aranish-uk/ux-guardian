"""Optional upstream-style start/results interface, restricted to fixture replay."""

import uuid

from mcp.server.fastmcp import FastMCP

from ux_guardian.config import validate_url
from ux_guardian.report.render import render
from ux_guardian.run import replay_report
from ux_guardian.security import redact

mcp = FastMCP("ux-guardian")
_test_results: dict[str, str] = {}


@mcp.tool()
async def start(url: str) -> str:
    """Replay an M0 fixture; no browser or paid agent is started."""
    report = replay_report().model_copy(update={"preview_url": validate_url(url)})
    test_id = str(uuid.uuid4())
    _test_results[test_id] = redact(render(report))
    return test_id


@mcp.tool()
async def results(test_id: str) -> str:
    """Return the synthetic report started by start()."""
    return _test_results.get(test_id, "Unknown test ID")


def run() -> None:
    mcp.run()
