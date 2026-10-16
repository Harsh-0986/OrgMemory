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
    extract_graph,
    slugify,
    validate_extraction,
)
from app.ingest.service import SOURCE_TYPES, document_id_for, ingest_document
from app.models.ingest import RejectedItem

__all__ = [
    "MAX_UPLOAD_BYTES",
    "SOURCE_TYPES",
    "SUPPORTED_EXTENSIONS",
    "ExtractedEntity",
    "ExtractedRelationship",
    "ExtractionOutcome",
    "RejectedItem",
    "UnsupportedDocument",
    "document_id_for",
    "extract_graph",
    "ingest_document",
    "is_supported",
    "slugify",
    "to_markdown",
    "validate_extraction",
]
