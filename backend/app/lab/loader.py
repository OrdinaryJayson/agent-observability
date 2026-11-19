"""Reserved public adapter awaiting the project lead's logical record contract.

The primitives in database.py are used by B's fixed PostgreSQL fixtures. They
must not be advertised as the C generator integration or mark manifests READY.
"""

from uuid import UUID

from app.core.errors import AppError
from app.lab.database import configured_url


def load_dataset(dataset_id, records, expected_manifest):
    configured_url()
    UUID(str(dataset_id))
    raise AppError(
        409,
        "FEATURE_NOT_AVAILABLE",
        "Loader awaits frozen records and expected_manifest structures; no records were consumed or written",
    )
