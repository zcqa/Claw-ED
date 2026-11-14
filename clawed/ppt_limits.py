"""Shared workbench/engine limits for complete PPT template processing.

Copied unchanged into the private engine by presenton_runtime.
"""

TEMPLATE_MAX_SLIDES = 60
TEMPLATE_MAX_FILE_MB = 50
TEMPLATE_MAX_UNPACKED_MB = 250


def template_limits() -> dict[str, int]:
    return {"max_pages": TEMPLATE_MAX_SLIDES, "max_file_mb": TEMPLATE_MAX_FILE_MB,
            "max_unpacked_mb": TEMPLATE_MAX_UNPACKED_MB}
