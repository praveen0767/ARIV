'''Revision ID: 20260903_00_initial_schema
Revises: None
Create Date: 2026-09-03 23:20:00.000000
'''

from alembic import op
import sqlalchemy as sa
import sqlalchemy.dialects.postgresql as pg

# revision identifiers, used by Alembic.
revision = '20260903_00_initial_schema'
down_revision = None
branch_labels = None
depends_on = None

# Enum definitions (must be created before tables that reference them)
TenantType = sa.Enum('ENTERPRISE', 'CONSUMER', 'PARTNER', 'INTERNAL', 'PLATFORM', name='tenanttype')
RecoveryDomain = sa.Enum('B2C', 'B2B', 'EMPLOYEE', 'PLATFORM', 'PARTNER', name='recoverydomain')
CaseType = sa.Enum('INVOICE_OVERDUE', 'PAYMENT_FAILED', 'ACQUIRER_DEGRADATION', name='casetype')
CaseStatus = sa.Enum('OPEN', 'RISK_ASSESSED', 'PENDING_APPROVAL', 'RECOVERED', 'FAILED', 'CLOSED', name='casestatus')
FailureCategory = sa.Enum('TRANSIENT_TECHNICAL', 'CUSTOMER_ACTION_REQUIRED', 'PAYMENT_METHOD_PROBLEM', 'PROVIDER_DEGRADATION',
                         'MERCHANT_CONFIGURATION', 'RISK_OR_FRAUD', 'NON_RETRIABLE', 'UNKNOWN', name='failurecategory')
Retryability = sa.Enum('IMMEDIATE_RETRY_POSSIBLE', 'LATER_RETRY_POSSIBLE', 'REQUIRES_NEW_METHOD', 'BLOCKED', name='retryability')
Recoverability = sa.Enum('HIGH', 'MEDIUM', 'LOW', 'UNKNOWN', name='recoverability')
RecoveryAction = sa.Enum('RETRY_NOW', 'RETRY_LATER', 'REQUEST_PAYMENT_METHOD_UPDATE', 'GENERATE_PAYMENT_LINK',
                        'SEND_REMINDER', 'ESCALATE_TO_HUMAN', 'WAIT', 'STOP_RECOVERY', name='recoveryaction')
PolicyStatus = sa.Enum('APPROVED', 'REJECTED', 'NEEDS_REVIEW', name='policystatus')
AutonomyLevel = sa.Enum('FULL_AUTO', 'HUMAN_APPROVAL', 'SUGGESTION_ONLY', name='autonomylevel')

def upgrade():
    # Enums are created automatically by SQLAlchemy when tables are created.
    # Manual DROP TYPE / CREATE TYPE statements have been removed to prevent duplicate object errors.

    # tenant table
    op.create_table(
        'tenant',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('type', TenantType, nullable=False),
        sa.Column('name', sa.String, nullable=False),
        sa.Column('config', sa.JSON, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )

    # provider_event table
    op.create_table(
        'provider_event',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('provider', sa.String, nullable=False),
        sa.Column('external_id', sa.String, nullable=False),
        sa.Column('payload', sa.JSON, nullable=False),
        sa.Column('idempotency_key', sa.String, nullable=False, unique=True),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.UniqueConstraint('provider', 'external_id', name='uix_provider_external_id'),
    )

    # recovery_case table
    op.create_table(
        'recovery_case',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', pg.UUID(as_uuid=True), sa.ForeignKey('tenant.id', ondelete='CASCADE'), nullable=False),
        sa.Column('domain', RecoveryDomain, nullable=False),
        sa.Column('case_type', CaseType, nullable=False),
        sa.Column('status', CaseStatus, nullable=False, server_default=sa.text("'OPEN'")),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('context', sa.JSON, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), onupdate=sa.text('now()'), nullable=False),
    )

    # decision_record table
    op.create_table(
        'decision_record',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('case_id', pg.UUID(as_uuid=True), sa.ForeignKey('recovery_case.id', ondelete='CASCADE'), nullable=False),
        sa.Column('tenant_id', pg.UUID(as_uuid=True), sa.ForeignKey('tenant.id', ondelete='CASCADE'), nullable=False),
        sa.Column('proposed_action', RecoveryAction, nullable=False),
        sa.Column('baseline_action', RecoveryAction, nullable=False),
        sa.Column('ai_confidence', sa.Float, nullable=True),
        sa.Column('expected_irv', sa.Float, nullable=True),
        sa.Column('policy_status', PolicyStatus, nullable=False),
        sa.Column('autonomy_level', AutonomyLevel, nullable=False),
        sa.Column('rejection_reason', sa.String, nullable=True),
        sa.Column('provenance', sa.JSON, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )

    # recovery_classification table
    op.create_table(
        'recovery_classification',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('case_id', pg.UUID(as_uuid=True), sa.ForeignKey('recovery_case.id', ondelete='CASCADE'), nullable=False),
        sa.Column('failure_category', FailureCategory, nullable=False),
        sa.Column('retryability', Retryability, nullable=False),
        sa.Column('recoverability', Recoverability, nullable=False),
        sa.Column('taxonomy_version', sa.String, nullable=False, server_default='1.0'),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.UniqueConstraint('case_id', 'taxonomy_version', name='uq_recovery_classification_case_taxonomy'),
    )

    # risk_event table
    op.create_table(
        'risk_event',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('case_id', pg.UUID(as_uuid=True), sa.ForeignKey('recovery_case.id', ondelete='CASCADE'), nullable=False),
        sa.Column('canonical_payload', sa.JSON, nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )

    # audit_event table
    op.create_table(
        'audit_event',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('case_id', pg.UUID(as_uuid=True), sa.ForeignKey('recovery_case.id', ondelete='SET NULL'), nullable=True),
        sa.Column('event_type', sa.String, nullable=False),
        sa.Column('details', sa.JSON, nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_audit_event_case_timestamp', 'audit_event', ['case_id', 'timestamp'])

def downgrade():
    # Drop tables in reverse order of dependencies
    op.drop_index('ix_audit_event_case_timestamp', table_name='audit_event')
    op.drop_table('audit_event')
    op.drop_table('risk_event')
    op.drop_table('recovery_classification')
    op.drop_table('decision_record')
    op.drop_table('recovery_case')
    op.drop_table('provider_event')
    op.drop_table('tenant')
    # Drop enums (order does not matter)
    Recoverability.drop(op.get_bind(), checkfirst=True)
    Retryability.drop(op.get_bind(), checkfirst=True)
    FailureCategory.drop(op.get_bind(), checkfirst=True)
    CaseStatus.drop(op.get_bind(), checkfirst=True)
    CaseType.drop(op.get_bind(), checkfirst=True)
    RecoveryDomain.drop(op.get_bind(), checkfirst=True)
    TenantType.drop(op.get_bind(), checkfirst=True)
    PolicyStatus.drop(op.get_bind(), checkfirst=True)
    AutonomyLevel.drop(op.get_bind(), checkfirst=True)
    RecoveryAction.drop(op.get_bind(), checkfirst=True)
