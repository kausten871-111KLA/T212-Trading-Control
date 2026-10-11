from __future__ import annotations
async def claim_due(self, now_ns: int, limit: int = 10, db: Optional[AsyncSession] = None) -> list[AutomationModel]:
    """
    Atomically claim due automations for execution.

    Advances next_run_at immediately so the row can never be
    double-claimed. On PostgreSQL, uses FOR UPDATE SKIP LOCKED
    for zero-contention distributed work claiming.
    """
    async with get_async_db_context(db) as db:
        stmt = (
            select(Automation)
            .where(
                Automation.is_active == True,
                Automation.next_run_at <= now_ns,
            )
            .order_by(Automation.next_run_at)
            .limit(limit)
        )

        if db.bind.dialect.name == 'postgresql':
            stmt = stmt.with_for_update(skip_locked=True)

        result = await db.execute(stmt)
        rows = result.scalars().all()

        from open_webui.utils.automations import next_run_ns
        from open_webui.utils.recurrence import RecurrenceEvaluationTimeout

        # Batch-fetch user timezones so rescheduling respects each
        # user's local timezone instead of falling back to server time.
        user_ids = list({row.user_id for row in rows})
        timezone_by_user_id: dict[str, Optional[str]] = {}
        if user_ids:
            from open_webui.models.users import User

            tz_result = await db.execute(select(User.id, User.timezone).where(User.id.in_(user_ids)))
            timezone_by_user_id = {uid: tz for uid, tz in tz_result.all()}

        claimed = []
        for row in rows:
            try:
                next_run_at = await next_run_ns(row.data.get('rrule', ''), tz=timezone_by_user_id.get(row.user_id))
            except RecurrenceEvaluationTimeout:
                log.warning('Skipping automation %s: recurrence evaluation timed out', row.id)
                continue
            row.last_run_at = now_ns
            row.next_run_at = next_run_at
            claimed.append(row)

        await db.commit()

        return [AutomationModel.model_validate(r) for r in claimed]

