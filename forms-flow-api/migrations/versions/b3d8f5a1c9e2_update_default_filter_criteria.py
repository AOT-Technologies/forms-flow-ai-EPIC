"""update default filter criteria to use orQueries

Revision ID: b3d8f5a1c9e2
Revises: e85c21a0c08f
Create Date: 2026-08-03 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
import json


revision = 'b3d8f5a1c9e2'
down_revision = 'e85c21a0c08f'
branch_labels = None
depends_on = None

# Previous criteria only checked candidateGroupsExpression, with no assignee
# condition at all. Camunda's INNER JOIN on ACT_RU_IDENTITYLINK also meant a
# task needed *some* candidate-group identity-link just to survive the join -
# so any two users sharing that same candidate-group value could see each
# other's tasks, since assignee was never actually checked.
#
# orQueries makes Camunda evaluate assignee OR candidateGroups together, and
# critically switches the join to a LEFT JOIN (see Task.xml's
# isOrQueryActive handling) - a task with zero candidate-group links no
# longer gets dropped before the assignee check runs, so assignee alone is
# now sufficient for a task to show up for its assignee.
NEW_CRITERIA = {
    "orQueries": [
        {
            "assigneeExpression": "${currentUser()}",
            "candidateGroupsExpression": "${currentUserGroups()}",
            "includeAssignedTasks": True,
        }
    ]
}

PREVIOUS_CRITERIA = {
    "candidateGroupsExpression": "${currentUserGroups()}",
    "includeAssignedTasks": True,
}


def upgrade():
    """Update system-generated task filters to use orQueries criteria format.

    Targets filters where created_by='system', filter_type='TASK', status='active'.
    """
    conn = op.get_bind()

    system_task_filters = conn.execute(
        sa.text("""
            SELECT id
            FROM public.filter
            WHERE created_by = 'system'
              AND filter_type = 'TASK'
              AND status = 'active'
              AND name = 'All Tasks'
        """)
    ).fetchall()

    if not system_task_filters:
        return

    criteria_json = json.dumps(NEW_CRITERIA)

    for task_filter in system_task_filters:
        conn.execute(
            sa.text("""
                UPDATE public.filter
                SET criteria = CAST(:criteria AS json)
                WHERE id = :filter_id
            """),
            {
                "criteria": criteria_json,
                "filter_id": task_filter.id,
            },
        )


def downgrade():
    """Revert system-generated task filters to the previous flat criteria format."""
    conn = op.get_bind()

    conn.execute(
        sa.text("""
            UPDATE public.filter
            SET criteria = CAST(:criteria AS json)
            WHERE created_by = 'system'
              AND filter_type = 'TASK'
              AND status = 'active'
              AND criteria::jsonb ? 'orQueries'
              AND name = 'All Tasks'
        """),
        {"criteria": json.dumps(PREVIOUS_CRITERIA)},
    )
