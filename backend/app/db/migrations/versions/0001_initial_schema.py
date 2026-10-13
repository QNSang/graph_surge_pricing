"""initial schema

Revision ID: 0001
Revises: 
Create Date: 2026-10-12 14:43:47.766290
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


APPEND_ONLY_FN = """
CREATE OR REPLACE FUNCTION audit_events_append_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'audit_events is append-only (% blocked)', TG_OP;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.execute("CREATE SEQUENCE IF NOT EXISTS audit_events_seq")
    op.create_table('audit_events',
    sa.Column('event_id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('demo_session_id', sa.UUID(), nullable=True),
    sa.Column('actor_id', sa.Text(), nullable=False),
    sa.Column('entity_type', sa.Text(), nullable=False),
    sa.Column('entity_id', sa.Text(), nullable=False),
    sa.Column('action', sa.Text(), nullable=False),
    sa.Column('previous_state', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('new_state', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('correlation_id', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('seq', sa.BigInteger(), server_default=sa.text("nextval('audit_events_seq')"), nullable=False),
    sa.PrimaryKeyConstraint('event_id')
    )
    op.create_index('ix_audit_entity', 'audit_events', ['entity_type', 'entity_id', 'created_at'], unique=False)
    op.create_index('ix_audit_seq', 'audit_events', ['seq'], unique=False)
    op.create_index('ix_audit_session_seq', 'audit_events', ['demo_session_id', 'seq'], unique=False)
    op.execute("ALTER SEQUENCE audit_events_seq OWNED BY audit_events.seq")
    op.execute(APPEND_ONLY_FN)
    op.execute(
        "CREATE TRIGGER trg_audit_events_append_only BEFORE UPDATE OR DELETE ON audit_events "
        "FOR EACH ROW EXECUTE FUNCTION audit_events_append_only()"
    )
    op.execute(
        "CREATE TRIGGER trg_audit_events_no_truncate BEFORE TRUNCATE ON audit_events "
        "FOR EACH STATEMENT EXECUTE FUNCTION audit_events_append_only()"
    )
    op.create_table('dataset_releases',
    sa.Column('dataset_id', sa.Text(), nullable=False),
    sa.Column('dataset_name', sa.Text(), nullable=False),
    sa.Column('dataset_version', sa.Text(), nullable=False),
    sa.Column('fingerprint', sa.Text(), nullable=False),
    sa.Column('source_path', sa.Text(), nullable=False),
    sa.Column('schema_version', sa.Text(), nullable=False),
    sa.Column('timezone', sa.Text(), nullable=False),
    sa.Column('snapshot_minutes', sa.Integer(), nullable=False),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('dataset_id')
    )
    op.create_table('demo_sessions',
    sa.Column('demo_session_id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('actor_id', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), server_default='ACTIVE', nullable=False),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('ACTIVE', 'CLOSED')", name='ck_demo_session_status'),
    sa.PrimaryKeyConstraint('demo_session_id')
    )
    op.create_index('ix_demo_sessions_actor', 'demo_sessions', ['actor_id', 'created_at'], unique=False)
    op.create_table('hexes',
    sa.Column('hex_id', sa.Text(), nullable=False),
    sa.Column('region_id', sa.Text(), nullable=False),
    sa.Column('node_mapping_version', sa.Text(), nullable=False),
    sa.Column('node_index', sa.Integer(), nullable=False),
    sa.Column('zone', sa.Text(), nullable=True),
    sa.Column('ring', sa.Integer(), nullable=True),
    sa.Column('lat', sa.Double(), nullable=False),
    sa.Column('lng', sa.Double(), nullable=False),
    sa.Column('polygon', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('neighbors', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.PrimaryKeyConstraint('hex_id')
    )
    op.create_index('ix_hexes_region', 'hexes', ['region_id', 'node_index'], unique=False)
    op.create_table('idempotency_records',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('scope', sa.Text(), nullable=False),
    sa.Column('key', sa.Text(), nullable=False),
    sa.Column('actor_id', sa.Text(), nullable=False),
    sa.Column('operation', sa.Text(), nullable=False),
    sa.Column('request_hash', sa.Text(), nullable=False),
    sa.Column('http_status', sa.Integer(), nullable=False),
    sa.Column('response', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('resource_type', sa.Text(), nullable=False),
    sa.Column('resource_id', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('scope', 'key', name='uq_idempotency_scope_key')
    )
    op.create_index('ix_idempotency_actor_key', 'idempotency_records', ['actor_id', 'key'], unique=False)
    op.create_table('policy_configs',
    sa.Column('policy_version', sa.Text(), nullable=False),
    sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('policy_version')
    )
    op.create_table('provider_metadata',
    sa.Column('provider_id', sa.Text(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('description', sa.Text(), server_default='', nullable=False),
    sa.Column('latest_version', sa.Text(), nullable=False),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('registered_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('provider_id')
    )
    op.create_table('snapshots',
    sa.Column('snapshot_id', sa.Text(), nullable=False),
    sa.Column('dataset_id', sa.Text(), nullable=False),
    sa.Column('region_id', sa.Text(), nullable=False),
    sa.Column('cutoff_ts', sa.DateTime(timezone=True), nullable=False),
    sa.Column('forecast_ts', sa.DateTime(timezone=True), nullable=True),
    sa.Column('node_mapping_version', sa.Text(), nullable=False),
    sa.Column('snapshot_version', sa.Text(), server_default='1', nullable=False),
    sa.Column('data_kind', sa.Text(), nullable=False),
    sa.Column('hex_count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("data_kind IN ('SYNTHETIC', 'HISTORICAL', 'LIVE')", name='ck_snapshot_data_kind'),
    sa.ForeignKeyConstraint(['dataset_id'], ['dataset_releases.dataset_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('snapshot_id'),
    sa.UniqueConstraint('dataset_id', 'region_id', 'cutoff_ts', 'node_mapping_version', name='uq_snapshot_identity')
    )
    op.create_index('ix_snapshots_cutoff', 'snapshots', ['cutoff_ts'], unique=False)
    op.create_table('hex_market_states',
    sa.Column('snapshot_id', sa.Text(), nullable=False),
    sa.Column('hex_id', sa.Text(), nullable=False),
    sa.Column('cutoff_ts', sa.DateTime(timezone=True), nullable=False),
    sa.Column('demand', sa.Double(), nullable=True),
    sa.Column('idle_supply', sa.Double(), nullable=True),
    sa.Column('effective_supply', sa.Double(), nullable=True),
    sa.Column('observed_ds', sa.Double(), nullable=True),
    sa.Column('surge_base', sa.Numeric(), nullable=True),
    sa.Column('bidding_source_version', sa.Text(), nullable=True),
    sa.Column('null_reasons', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('market_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.ForeignKeyConstraint(['hex_id'], ['hexes.hex_id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['snapshot_id'], ['snapshots.snapshot_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('snapshot_id', 'hex_id', name='pk_hex_market_states')
    )
    op.create_index('ix_market_hex_cutoff', 'hex_market_states', ['hex_id', 'cutoff_ts'], unique=False)
    op.create_table('recommendation_sets',
    sa.Column('recommendation_set_id', sa.Text(), nullable=False),
    sa.Column('snapshot_id', sa.Text(), nullable=False),
    sa.Column('provider_id', sa.Text(), nullable=False),
    sa.Column('provider_version', sa.Text(), nullable=False),
    sa.Column('policy_version', sa.Text(), nullable=False),
    sa.Column('output_contract_version', sa.Text(), nullable=False),
    sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('dataset_fingerprint', sa.Text(), nullable=False),
    sa.Column('content_hash', sa.Text(), nullable=False),
    sa.Column('model_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('validation_summary', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('PUBLISHED', 'REJECTED')", name='ck_recset_status'),
    sa.ForeignKeyConstraint(['provider_id'], ['provider_metadata.provider_id'], ),
    sa.ForeignKeyConstraint(['snapshot_id'], ['snapshots.snapshot_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('recommendation_set_id'),
    sa.UniqueConstraint('snapshot_id', 'provider_id', 'provider_version', 'content_hash', name='uq_recset_content')
    )
    op.create_index('ix_recsets_provider', 'recommendation_sets', ['provider_id'], unique=False)
    op.create_index('ix_recsets_snapshot', 'recommendation_sets', ['snapshot_id', 'created_at'], unique=False)
    op.create_table('batch_plans',
    sa.Column('batch_plan_id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('demo_session_id', sa.UUID(), nullable=False),
    sa.Column('actor_id', sa.Text(), nullable=False),
    sa.Column('snapshot_id', sa.Text(), nullable=False),
    sa.Column('recommendation_set_id', sa.Text(), nullable=False),
    sa.Column('selection_mode', sa.Text(), nullable=False),
    sa.Column('items', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('skipped', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("selection_mode IN ('ALL_ELIGIBLE', 'SELECTED')", name='ck_batch_plan_mode'),
    sa.ForeignKeyConstraint(['demo_session_id'], ['demo_sessions.demo_session_id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['recommendation_set_id'], ['recommendation_sets.recommendation_set_id'], ),
    sa.ForeignKeyConstraint(['snapshot_id'], ['snapshots.snapshot_id'], ),
    sa.PrimaryKeyConstraint('batch_plan_id')
    )
    op.create_index('ix_batch_plans_session', 'batch_plans', ['demo_session_id', 'created_at'], unique=False)
    op.create_table('recommendations',
    sa.Column('proposal_id', sa.Text(), nullable=False),
    sa.Column('recommendation_set_id', sa.Text(), nullable=False),
    sa.Column('snapshot_id', sa.Text(), nullable=False),
    sa.Column('hex_id', sa.Text(), nullable=False),
    sa.Column('provider_proposal_id', sa.Text(), nullable=True),
    sa.Column('proposal_version', sa.Text(), server_default='1', nullable=False),
    sa.Column('action', sa.Text(), nullable=False),
    sa.Column('surge_base', sa.Numeric(), nullable=True),
    sa.Column('surge_delta', sa.Numeric(), nullable=True),
    sa.Column('surge_proposed', sa.Numeric(), nullable=True),
    sa.Column('explanation', sa.Text(), server_default='', nullable=False),
    sa.Column('reason_codes', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('evidence', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('policy_version', sa.Text(), nullable=False),
    sa.Column('validation_status', sa.Text(), nullable=False),
    sa.Column('validation_errors', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("action IN ('INCREASE', 'DECREASE', 'HOLD', 'REVIEW')", name='ck_recommendation_action'),
    sa.CheckConstraint("validation_status = 'INVALID' OR surge_base IS NOT NULL", name='ck_recommendation_valid_has_base'),
    sa.CheckConstraint("validation_status IN ('VALID', 'INVALID')", name='ck_recommendation_validation'),
    sa.ForeignKeyConstraint(['hex_id'], ['hexes.hex_id'], ),
    sa.ForeignKeyConstraint(['recommendation_set_id'], ['recommendation_sets.recommendation_set_id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['snapshot_id'], ['snapshots.snapshot_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('proposal_id'),
    sa.UniqueConstraint('recommendation_set_id', 'hex_id', name='uq_recommendation_set_hex')
    )
    op.create_index('ix_recommendations_hex', 'recommendations', ['hex_id'], unique=False)
    op.create_index('ix_recommendations_snapshot_action', 'recommendations', ['snapshot_id', 'action'], unique=False)
    op.create_table('decision_batches',
    sa.Column('batch_id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('batch_plan_id', sa.UUID(), nullable=False),
    sa.Column('demo_session_id', sa.UUID(), nullable=False),
    sa.Column('snapshot_id', sa.Text(), nullable=False),
    sa.Column('recommendation_set_id', sa.Text(), nullable=False),
    sa.Column('actor_id', sa.Text(), nullable=False),
    sa.Column('idempotency_key', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('total_count', sa.Integer(), nullable=False),
    sa.Column('success_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('failure_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('PROCESSING', 'SUCCESS', 'PARTIAL_SUCCESS', 'FAILED')", name='ck_batch_status'),
    sa.ForeignKeyConstraint(['batch_plan_id'], ['batch_plans.batch_plan_id'], ),
    sa.ForeignKeyConstraint(['demo_session_id'], ['demo_sessions.demo_session_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('batch_id'),
    sa.UniqueConstraint('batch_plan_id', name='uq_batch_per_plan')
    )
    op.create_index('ix_batches_session_created', 'decision_batches', ['demo_session_id', 'created_at'], unique=False)
    op.create_table('decisions',
    sa.Column('decision_id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('demo_session_id', sa.UUID(), nullable=False),
    sa.Column('proposal_id', sa.Text(), nullable=False),
    sa.Column('proposal_version', sa.Text(), nullable=False),
    sa.Column('snapshot_id', sa.Text(), nullable=False),
    sa.Column('recommendation_set_id', sa.Text(), nullable=False),
    sa.Column('hex_id', sa.Text(), nullable=False),
    sa.Column('action', sa.Text(), nullable=False),
    sa.Column('surge_base', sa.Numeric(), nullable=False),
    sa.Column('surge_proposed', sa.Numeric(), nullable=True),
    sa.Column('requested_surge', sa.Numeric(), nullable=True),
    sa.Column('surge_decided', sa.Numeric(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('actor_id', sa.Text(), nullable=False),
    sa.Column('idempotency_key', sa.Text(), nullable=False),
    sa.Column('batch_id', sa.UUID(), nullable=True),
    sa.Column('policy_version', sa.Text(), nullable=False),
    sa.Column('provider_id', sa.Text(), nullable=False),
    sa.Column('provider_version', sa.Text(), nullable=False),
    sa.Column('execution_mode', sa.Text(), server_default='DEMO', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("action IN ('ACCEPT_PROPOSAL', 'KEEP_BIDDING', 'OVERRIDE_PROPOSAL')", name='ck_decision_action'),
    sa.CheckConstraint("execution_mode = 'DEMO'", name='ck_decision_demo_only'),
    sa.CheckConstraint("status IN ('RECORDED', 'KEPT_BIDDING')", name='ck_decision_status'),
    sa.ForeignKeyConstraint(['demo_session_id'], ['demo_sessions.demo_session_id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['proposal_id'], ['recommendations.proposal_id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['snapshot_id'], ['snapshots.snapshot_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('decision_id')
    )
    op.create_index('ix_decisions_actor_created', 'decisions', ['actor_id', 'created_at'], unique=False)
    op.create_index('ix_decisions_proposal', 'decisions', ['proposal_id'], unique=False)
    op.create_index('ix_decisions_session_created', 'decisions', ['demo_session_id', 'created_at'], unique=False)
    op.create_index('ix_decisions_snapshot', 'decisions', ['snapshot_id'], unique=False)
    op.create_index('uq_decision_final_per_session', 'decisions', ['demo_session_id', 'proposal_id'], unique=True, postgresql_where=sa.text("status IN ('RECORDED', 'KEPT_BIDDING')"))
    op.create_table('decision_batch_items',
    sa.Column('batch_id', sa.UUID(), nullable=False),
    sa.Column('proposal_id', sa.Text(), nullable=False),
    sa.Column('proposal_version', sa.Text(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('requested_action', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('decision_id', sa.UUID(), nullable=True),
    sa.Column('error_code', sa.Text(), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('PENDING', 'SUCCESS', 'FAILED')", name='ck_batch_item_status'),
    sa.ForeignKeyConstraint(['batch_id'], ['decision_batches.batch_id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['decision_id'], ['decisions.decision_id'], ),
    sa.PrimaryKeyConstraint('batch_id', 'proposal_id', name='pk_decision_batch_items')
    )
    op.create_index('ix_batch_items_decision', 'decision_batch_items', ['decision_id'], unique=False)
    # ### end Alembic commands ###


def downgrade() -> None:
    op.drop_index('ix_batch_items_decision', table_name='decision_batch_items')
    op.drop_table('decision_batch_items')
    op.drop_index('uq_decision_final_per_session', table_name='decisions', postgresql_where=sa.text("status IN ('RECORDED', 'KEPT_BIDDING')"))
    op.drop_index('ix_decisions_snapshot', table_name='decisions')
    op.drop_index('ix_decisions_session_created', table_name='decisions')
    op.drop_index('ix_decisions_proposal', table_name='decisions')
    op.drop_index('ix_decisions_actor_created', table_name='decisions')
    op.drop_table('decisions')
    op.drop_index('ix_batches_session_created', table_name='decision_batches')
    op.drop_table('decision_batches')
    op.drop_index('ix_recommendations_snapshot_action', table_name='recommendations')
    op.drop_index('ix_recommendations_hex', table_name='recommendations')
    op.drop_table('recommendations')
    op.drop_index('ix_batch_plans_session', table_name='batch_plans')
    op.drop_table('batch_plans')
    op.drop_index('ix_recsets_snapshot', table_name='recommendation_sets')
    op.drop_index('ix_recsets_provider', table_name='recommendation_sets')
    op.drop_table('recommendation_sets')
    op.drop_index('ix_market_hex_cutoff', table_name='hex_market_states')
    op.drop_table('hex_market_states')
    op.drop_index('ix_snapshots_cutoff', table_name='snapshots')
    op.drop_table('snapshots')
    op.drop_table('provider_metadata')
    op.drop_table('policy_configs')
    op.drop_index('ix_idempotency_actor_key', table_name='idempotency_records')
    op.drop_table('idempotency_records')
    op.drop_index('ix_hexes_region', table_name='hexes')
    op.drop_table('hexes')
    op.drop_index('ix_demo_sessions_actor', table_name='demo_sessions')
    op.drop_table('demo_sessions')
    op.drop_table('dataset_releases')
    op.drop_index('ix_audit_session_seq', table_name='audit_events')
    op.drop_index('ix_audit_seq', table_name='audit_events')
    op.drop_index('ix_audit_entity', table_name='audit_events')
    op.drop_table('audit_events')
    op.execute("DROP FUNCTION IF EXISTS audit_events_append_only()")
    op.execute("DROP SEQUENCE IF EXISTS audit_events_seq")
