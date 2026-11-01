"""Execução de um workflow disparado pelo n8n.

Concentra o que todo gatilho precisa: lock contra execução concorrente, uma
linha em `workflow_runs` e o modo dry-run. No dry-run o trabalho roda dentro de
um savepoint que é desfeito — o resultado é fiel ao que aconteceria, mas nada
do funil é gravado. A linha de `workflow_runs` sobrevive de propósito: é o
registro de que a execução existiu.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.locks import execution_lock
from app.domain.enums import RunStatus
from app.models.control import WorkflowRun
from app.schemas.runs import RunResponse


@dataclass
class WorkOutcome:
    summary: dict
    items_processed: int = 0
    warnings: list[str] = field(default_factory=list)


def run_workflow(
    db: Session,
    *,
    name: str,
    owner: str,
    dry_run: bool,
    work: Callable[[], WorkOutcome],
) -> RunResponse:
    with execution_lock(db, lock_name=name, owner=owner):
        run = WorkflowRun(workflow_name=name, dry_run=dry_run, status=RunStatus.RUNNING)
        db.add(run)
        db.flush()

        savepoint = db.begin_nested()
        try:
            outcome = work()
        except Exception as exc:
            savepoint.rollback()
            run.status = RunStatus.FAILED
            run.error = str(exc)
            run.finished_at = datetime.now(UTC)
            db.flush()
            raise

        if dry_run:
            savepoint.rollback()
        else:
            savepoint.commit()

        run.status = RunStatus.SUCCESS
        run.items_processed = outcome.items_processed
        run.summary = outcome.summary
        run.finished_at = datetime.now(UTC)
        db.flush()

    return RunResponse(
        run_id=run.id,
        status=run.status.value,
        dry_run=dry_run,
        summary=outcome.summary,
        warnings=outcome.warnings,
    )
