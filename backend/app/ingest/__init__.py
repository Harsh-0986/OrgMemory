"""Ingestion: turn an uploaded document into graph entities.

Two halves, deliberately separate:

* `documents.to_markdown` converts any supported file to Markdown locally. No
  model, no network, no cost.
* `extract.extract_graph` asks the model to read that Markdown and propose
  entities and relationships, then validates every proposal against the graph's
  label and relationship allowlists before anything can be written.

`service.ingest_document` runs both and applies the result.
"""

from app.ingest.documents import (
    MAX_UPLOAD_BYTES,
    SUPPORTED_EXTENSIONS,
    UnsupportedDocument,
    is_supported,
    to_markdown,
)
from app.ingest.extract import (
    ExtractedEntity,
    ExtractedRelationship,
    ExtractionOutcome,
    RejectedItem,
    extract_graph,
    slugify,
    validate_extraction,
)

__all__ = [
    "MAX_UPLOAD_BYTES",
    "SUPPORTED_EXTENSIONS",
    "ExtractedEntity",
    "ExtractedRelationship",
    "ExtractionOutcome",
    "RejectedItem",
    "UnsupportedDocument",
    "extract_graph",
    "is_supported",
    "slugify",
    "to_markdown",
    "validate_extraction",
]
