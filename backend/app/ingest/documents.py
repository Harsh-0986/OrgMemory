"""Document conversion for ingestion.

Everything a user uploads is turned into Markdown before anything else touches
it, using Microsoft's MarkItDown. One conversion step means the extractor only
ever sees one shape of input, so a PDF, a Word file and a pasted runbook take
exactly the same path through the pipeline.

Conversion is local and costs nothing. The model is only involved later, when
the Markdown is turned into graph entities.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

#: Extensions we will attempt. MarkItDown sniffs content as well, but refusing
#: obvious binaries early gives a clearer error than a converter traceback.
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".md",
        ".markdown",
        ".txt",
        ".text",
        ".html",
        ".htm",
        ".pdf",
        ".docx",
        ".pptx",
        ".xlsx",
        ".csv",
        ".json",
        ".xml",
        ".rtf",
        ".epub",
    }
)

#: Guard rail on size. A single upload is converted in memory, and the
#: extracted Markdown is then sent to a model, so an unbounded file is both a
#: memory risk and an unbounded bill.
MAX_UPLOAD_BYTES = 8 * 1024 * 1024

#: Markdown longer than this is truncated before extraction. The prompt budget
#: matters more than the tail of a very long document.
MAX_EXTRACT_CHARS = 60_000


class UnsupportedDocument(RuntimeError):
    """Raised when a file cannot be converted to Markdown."""


@dataclass
class ConvertedDocument:
    """The result of conversion: Markdown plus what we learned on the way."""

    markdown: str
    truncated: bool = False


def _extension_of(filename: str) -> str:
    lowered = filename.lower()
    dot = lowered.rfind(".")
    return lowered[dot:] if dot != -1 else ""


def is_supported(filename: str) -> bool:
    """Whether we would attempt to convert this filename."""
    return _extension_of(filename) in SUPPORTED_EXTENSIONS


def to_markdown(filename: str, data: bytes) -> ConvertedDocument:
    """Convert an uploaded file to Markdown.

    Raises `UnsupportedDocument` with a message meant for the user, not a
    stack trace: upload failures are a normal thing to hit, not a bug.
    """
    if not data:
        raise UnsupportedDocument("The uploaded file is empty.")

    if len(data) > MAX_UPLOAD_BYTES:
        raise UnsupportedDocument(
            f"The file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
        )

    extension = _extension_of(filename)
    if extension and extension not in SUPPORTED_EXTENSIONS:
        raise UnsupportedDocument(
            f"'{extension}' files are not supported. Try "
            f"{', '.join(sorted(SUPPORTED_EXTENSIONS))}."
        )

    try:
        from markitdown import MarkItDown
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise UnsupportedDocument(
            "Document conversion is unavailable: markitdown is not installed."
        ) from exc

    try:
        result = MarkItDown().convert_stream(
            io.BytesIO(data),
            file_extension=extension or None,
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the user verbatim
        logger.warning("MarkItDown failed for %s: %s", filename, exc)
        raise UnsupportedDocument(
            f"Could not read that file as a document ({exc})."
        ) from exc

    markdown = (result.text_content or "").strip()
    if not markdown:
        raise UnsupportedDocument(
            "That file converted to no text. If it is a scan, it needs OCR first."
        )

    truncated = len(markdown) > MAX_EXTRACT_CHARS
    if truncated:
        # Trim on a paragraph boundary so the model does not receive half a
        # sentence and invent the rest.
        cut = markdown.rfind("\n\n", 0, MAX_EXTRACT_CHARS)
        markdown = markdown[: cut if cut > 0 else MAX_EXTRACT_CHARS]
        logger.info("Document truncated to %d characters for extraction", len(markdown))

    return ConvertedDocument(markdown=markdown, truncated=truncated)
