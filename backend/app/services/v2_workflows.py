import re

from sqlalchemy import text

from app.contracts.v2 import WorkflowDefinition, digest
from app.core.database import get_engine
from app.core.errors import AppError
from app.repositories.v2 import audit, encode, one
from app.services import v2_engine


def revision(header):
    if header is None:
        raise AppError(428, "PRECONDITION_REQUIRED", "If-Match is required")
    if not re.fullmatch(r'"[1-9][0-9]*"', header):
        raise AppError(422, "VALIDATION_ERROR", "Invalid If-Match revision")
    return int(header[1:-1])


def create(body):
    with get_engine().begin() as conn:
        result = one(
            conn,
            """INSERT INTO workflows(name,description,draft)
          VALUES(:name,:description,CAST(:draft AS jsonb)) RETURNING *""",
            name=body["name"],
            description=body.get("description"),
            draft=encode(body["draft"]),
        )
        audit(conn, "workflow.created", "workflow", result["workflow_id"])
        return result


def update(workflow_id, body, expected):
    with get_engine().begin() as conn:
        old = one(
            conn,
            "SELECT * FROM workflows WHERE workflow_id=:id FOR UPDATE",
            id=workflow_id,
        )
        if old["revision"] != expected:
            raise AppError(
                412,
                "REVISION_MISMATCH",
                "The draft changed",
                {"revision": old["revision"]},
            )
        result = one(
            conn,
            """UPDATE workflows SET name=:name,description=:description,draft=CAST(:draft AS jsonb),
          archived_at=CASE WHEN :archived THEN coalesce(archived_at,clock_timestamp()) ELSE NULL END,
          revision=revision+1,updated_at=clock_timestamp() WHERE workflow_id=:id RETURNING *""",
            id=workflow_id,
            name=body.get("name", old["name"]),
            description=body.get("description", old["description"]),
            draft=encode(body.get("draft", old["draft"])),
            archived=body.get("archived", old["archived_at"] is not None),
        )
        audit(
            conn,
            "workflow.updated",
            "workflow",
            workflow_id,
            {"revision": result["revision"]},
        )
        return result


def publish(workflow_id, expected, expected_hash):
    # Validate outside the write lock; revision is rechecked before publication.
    with get_engine().connect() as conn:
        draft = one(
            conn, "SELECT * FROM workflows WHERE workflow_id=:id", id=workflow_id
        )
    if draft["revision"] != expected:
        raise AppError(412, "REVISION_MISMATCH", "The draft changed")
    definition = WorkflowDefinition.model_validate(draft["draft"]).root
    report = v2_engine.validate_workflow(definition)
    if not report["valid"]:
        raise AppError(422, "WORKFLOW_INVALID", "Workflow is invalid", report)
    hashed = digest(definition)
    if expected_hash != hashed:
        raise AppError(409, "CONFLICT", "Definition hash does not match")
    with get_engine().begin() as conn:
        current = one(
            conn,
            "SELECT * FROM workflows WHERE workflow_id=:id FOR UPDATE",
            id=workflow_id,
        )
        if current["revision"] != expected:
            raise AppError(412, "REVISION_MISMATCH", "The draft changed")
        if current["archived_at"] is not None:
            raise AppError(409, "CONFLICT", "Workflow is archived")
        version = one(
            conn,
            """INSERT INTO workflow_versions(workflow_id,version_no,definition,definition_hash)
          SELECT :id,coalesce(max(version_no),0)+1,CAST(:definition AS jsonb),:hash FROM workflow_versions
          WHERE workflow_id=:id RETURNING *""",
            id=workflow_id,
            definition=encode(definition),
            hash=hashed,
        )
        conn.execute(
            text(
                "UPDATE workflows SET revision=revision+1,updated_at=clock_timestamp() WHERE workflow_id=:id"
            ),
            {"id": workflow_id},
        )
        audit(
            conn,
            "workflow.published",
            "workflow",
            workflow_id,
            {"version_id": str(version["version_id"]), "definition_hash": hashed},
        )
        return version
