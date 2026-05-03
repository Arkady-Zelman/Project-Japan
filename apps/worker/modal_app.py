"""JEPX-Storage Modal app — entry point for all scheduled jobs and HTTP endpoints.

Milestone 1 stub. Real ingest/forecast/LSM/agent functions land in their respective
milestones (M3, M6, M7, M9) per BUILD_SPEC §11.
"""

import modal

app = modal.App("jepx-storage")

base_image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("pydantic>=2.7", "python-dotenv>=1.0")
)


@app.function(image=base_image)
def healthcheck() -> str:
    """Sanity check that the Modal app is deployable. Run via `modal run`."""
    return "ok"
