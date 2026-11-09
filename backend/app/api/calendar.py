"""Calendar & tasks: natural-language AI planning, tasks, daily view, analytics."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..models.task import Task
from ..models.user import User
from ..providers import get_provider
from ..security.deps import get_current_user, get_db, require_csrf

router = APIRouter(prefix="/calendar", tags=["calendar"])

_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _week_start(ref: dt.date | None = None) -> dt.date:
    ref = ref or dt.date.today()
    return ref - dt.timedelta(days=ref.weekday())


def _date_for_day(day: str | None, week_start: dt.date) -> dt.date | None:
    if day and day.lower() in _DAYS:
        return week_start + dt.timedelta(days=_DAYS.index(day.lower()))
    return None


# ---- schemas ----------------------------------------------------------

class PlanRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8000)


class ProposedTask(BaseModel):
    title: str
    day: str | None = None
    scheduled_date: dt.date | None = None
    duration_minutes: int | None = None
    priority: str = "medium"
    category: str | None = None


class PlanResponse(BaseModel):
    summary: str
    tasks: list[ProposedTask]
    questions: list[str]
    ai_generated: bool


class SaveTasksRequest(BaseModel):
    tasks: list[ProposedTask]
    week_start: dt.date | None = None


class TaskInfo(BaseModel):
    id: int
    title: str
    scheduled_date: dt.date | None
    duration_minutes: int | None
    priority: str
    status: str
    category: str | None
    source: str


class TaskPatch(BaseModel):
    status: str | None = None
    title: str | None = None
    scheduled_date: dt.date | None = None
    duration_minutes: int | None = None
    priority: str | None = None


# ---- planning ---------------------------------------------------------

@router.post("/plan", response_model=PlanResponse)
def plan(
    body: PlanRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_csrf),
) -> PlanResponse:
    """Turn free text into a proposed schedule (NOT saved — review first)."""
    result = get_provider().plan_tasks(body.text)
    record_audit(db, action="calendar.plan", category="calendar")
    return PlanResponse(
        summary=result.summary,
        tasks=[ProposedTask(**t) for t in result.tasks],
        questions=result.notes,
        ai_generated=result.ai_generated,
    )


@router.post("/tasks", response_model=list[TaskInfo], status_code=status.HTTP_201_CREATED)
def save_tasks(
    body: SaveTasksRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_csrf),
) -> list[Task]:
    """Save approved tasks. Day names are mapped onto the target week."""
    week = body.week_start or _week_start()
    created: list[Task] = []
    for pt in body.tasks:
        date = pt.scheduled_date or _date_for_day(pt.day, week)
        task = Task(
            title=pt.title,
            scheduled_date=date,
            duration_minutes=pt.duration_minutes,
            priority=pt.priority or "medium",
            category=pt.category,
            source="ai" if (pt.day or pt.duration_minutes) else "manual",
        )
        db.add(task)
        created.append(task)
    db.commit()
    for t in created:
        db.refresh(t)
    record_audit(db, action="calendar.tasks.saved", category="calendar", detail={"count": len(created)})
    return created


@router.get("/tasks", response_model=list[TaskInfo])
def list_tasks(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    date_from: dt.date | None = Query(None),
    date_to: dt.date | None = Query(None),
    task_status: str | None = Query(None),
) -> list[Task]:
    q = db.query(Task)
    if date_from:
        q = q.filter(Task.scheduled_date >= date_from)
    if date_to:
        q = q.filter(Task.scheduled_date <= date_to)
    if task_status:
        q = q.filter(Task.status == task_status)
    return q.order_by(Task.scheduled_date.is_(None), Task.scheduled_date, Task.priority).all()


@router.patch("/tasks/{task_id}", response_model=TaskInfo)
def update_task(
    task_id: int,
    body: TaskPatch,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_csrf),
) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if body.status is not None:
        if body.status not in ("planned", "done", "missed"):
            raise HTTPException(status_code=400, detail="bad status")
        task.status = body.status
        task.completed_at = dt.datetime.now(dt.timezone.utc) if body.status == "done" else None
    if body.title is not None:
        task.title = body.title
    if body.scheduled_date is not None:
        task.scheduled_date = body.scheduled_date
    if body.duration_minutes is not None:
        task.duration_minutes = body.duration_minutes
    if body.priority is not None:
        task.priority = body.priority
    db.commit()
    db.refresh(task)
    return task


@router.delete("/tasks/{task_id}", response_model=dict)
def delete_task(
    task_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_csrf),
) -> dict:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    db.delete(task)
    db.commit()
    return {"deleted": task_id}


@router.get("/today")
def today(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    """Today's tasks plus a short briefing."""
    d = dt.date.today()
    tasks = (
        db.query(Task)
        .filter(Task.scheduled_date == d)
        .order_by(Task.priority, Task.id)
        .all()
    )
    total_minutes = sum(t.duration_minutes or 0 for t in tasks)
    done = sum(1 for t in tasks if t.status == "done")
    return {
        "date": d.isoformat(),
        "task_count": len(tasks),
        "done": done,
        "remaining": len(tasks) - done,
        "estimated_minutes": total_minutes,
        "tasks": [TaskInfo.model_validate(t, from_attributes=True).model_dump() for t in tasks],
    }


@router.get("/analytics")
def analytics(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    days: int = Query(7, ge=1, le=365),
) -> dict:
    start = dt.date.today() - dt.timedelta(days=days - 1)
    tasks = db.query(Task).filter(Task.scheduled_date >= start).all()
    total = len(tasks)
    done = sum(1 for t in tasks if t.status == "done")
    missed = sum(1 for t in tasks if t.status == "missed")
    planned = sum(1 for t in tasks if t.status == "planned")
    rate = round(done / total * 100) if total else 0
    return {
        "days": days,
        "total": total,
        "done": done,
        "missed": missed,
        "planned": planned,
        "completion_rate": rate,
        "note": "Completion rate is a signal, not a judgement.",
    }
