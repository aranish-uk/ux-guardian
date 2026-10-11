"""Cross-platform dispatch adapter: inputs remain data, never shell code."""

import os

from ux_guardian.cli import app


def main() -> None:
    args = ["ci", "--pr", os.environ["UX_PR_NUMBER"],
            "--preview-url", os.environ["UX_PREVIEW_URL"]]
    if os.environ.get("UX_AGENT_RUNS", "false").lower() == "true":
        args.append("--agent-runs")
    app(args)


if __name__ == "__main__":
    main()
