-- =============================================================================
-- Graph Surge Recommendation Console: PostgreSQL schema
-- =============================================================================
-- Nguồn contract: docs/backend/spec_backend.md (mục 3, 5, 6, 7, 11),
--                 docs/product/product_spec.md (mục 9, 11, 12),
--                 docs/data/metadata.md (định nghĩa D/S, quy tắc null).
-- Giải thích thiết kế và ERD: database/ERD.md.
--
-- Yêu cầu: PostgreSQL 15+ (dùng UNIQUE NULLS NOT DISTINCT, partial unique index).
-- Phạm vi: chỉ phần backend console. Orders, hex_features, graph_edges vẫn ở
-- Parquet; DB giữ metadata dataset, market state theo snapshot, recommendation,
-- decision, batch, idempotency và audit.
--
-- Quy ước:
--   * ID nội bộ: BIGINT GENERATED ALWAYS AS IDENTITY.
--   * Thời gian: timestamptz. Dữ liệu nguồn không có timezone (Asia/Ho_Chi_Minh),
--     importer phải chuyển bằng `ts AT TIME ZONE 'Asia/Ho_Chi_Minh'`.
--   * Hệ số surge: NUMERIC(6,4). NUMERIC tự làm tròn phần thập phân khi insert,
--     nên importer/API phải kiểm tra precision TRƯỚC khi ghi.
--   * Mọi FK mặc định ON DELETE RESTRICT: dữ liệu lịch sử không bị xoá dây chuyền.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- 0. Hàm trigger dùng chung
-- -----------------------------------------------------------------------------

-- Chặn DELETE và chặn UPDATE mọi cột trừ các cột được liệt kê trong TG_ARGV.
-- Không truyền tham số nào nghĩa là bảng hoàn toàn bất biến (chỉ INSERT).
CREATE FUNCTION guard_immutable_columns() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  -- TG_ARGV là NULL (không phải mảng rỗng) khi trigger không có tham số.
  allowed TEXT[] := coalesce(TG_ARGV, '{}');
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'IMMUTABLE_ROW: DELETE is not allowed on %', TG_TABLE_NAME
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF (to_jsonb(NEW) - allowed) IS DISTINCT FROM (to_jsonb(OLD) - allowed) THEN
    RAISE EXCEPTION 'IMMUTABLE_ROW: only columns % may change on %', allowed, TG_TABLE_NAME
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE FUNCTION forbid_truncate() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'IMMUTABLE_TABLE: TRUNCATE is not allowed on %', TG_TABLE_NAME
    USING ERRCODE = 'restrict_violation';
END;
$$;

-- -----------------------------------------------------------------------------
-- 1. Tham chiếu: vùng, hex, node mapping, metric
-- -----------------------------------------------------------------------------

CREATE TABLE regions (
  region_id      TEXT PRIMARY KEY,
  label          TEXT NOT NULL,
  timezone       TEXT NOT NULL DEFAULT 'Asia/Ho_Chi_Minh',
  h3_resolution  SMALLINT NOT NULL CHECK (h3_resolution BETWEEN 0 AND 15),
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE hexes (
  hex_id      TEXT PRIMARY KEY,                       -- chuỗi H3 index
  region_id   TEXT NOT NULL REFERENCES regions (region_id) ON DELETE RESTRICT,
  zone        TEXT NOT NULL CHECK (zone IN ('airport','cbd','office','residential','suburb','venue')),
  ring        SMALLINT NOT NULL CHECK (ring >= 0),
  lat         DOUBLE PRECISION NOT NULL CHECK (lat BETWEEN -90 AND 90),
  lng         DOUBLE PRECISION NOT NULL CHECK (lng BETWEEN -180 AND 180),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX hexes_region_id_idx ON hexes (region_id);

-- Thứ tự node của graph (hex -> chỉ số node). Một snapshot gắn với đúng một mapping.
CREATE TABLE node_mappings (
  node_mapping_id  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  region_id        TEXT NOT NULL REFERENCES regions (region_id) ON DELETE RESTRICT,
  version          TEXT NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (region_id, version)
);

CREATE TABLE node_mapping_hexes (
  node_mapping_id  BIGINT NOT NULL REFERENCES node_mappings (node_mapping_id) ON DELETE RESTRICT,
  hex_id           TEXT NOT NULL REFERENCES hexes (hex_id) ON DELETE RESTRICT,
  node_index       INTEGER NOT NULL CHECK (node_index >= 0),
  PRIMARY KEY (node_mapping_id, hex_id),
  UNIQUE (node_mapping_id, node_index)
);
CREATE INDEX node_mapping_hexes_hex_id_idx ON node_mapping_hexes (hex_id);

-- Định nghĩa metric (D/S quan sát, D/S dự báo...). Giao diện hiển thị theo bảng này.
CREATE TABLE metric_definitions (
  metric_id           TEXT PRIMARY KEY,               -- ví dụ 'ds_eff_observed.v1'
  display_name        TEXT NOT NULL,
  equation            TEXT NOT NULL,
  units               TEXT NOT NULL,
  zero_supply_policy  TEXT NOT NULL,                  -- ví dụ 'NULL_WITH_REASON'
  description         TEXT,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- 2. Dữ liệu nguồn: dataset release, snapshot, market state (bất biến)
-- -----------------------------------------------------------------------------

CREATE TABLE dataset_releases (
  dataset_id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  dataset_key            TEXT NOT NULL UNIQUE,        -- data/CURRENT.json: dataset_id
  fingerprint            TEXT NOT NULL UNIQUE,        -- data/CURRENT.json: data_fingerprint
  layout_version         TEXT NOT NULL,
  schema_version         TEXT NOT NULL,
  source_path            TEXT NOT NULL,
  data_kind              TEXT NOT NULL CHECK (data_kind IN ('SYNTHETIC','HISTORICAL','LIVE')),
  observation_metric_id  TEXT NOT NULL REFERENCES metric_definitions (metric_id) ON DELETE RESTRICT,
  metadata               JSONB NOT NULL DEFAULT '{}',
  imported_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE snapshots (
  snapshot_id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  dataset_id        BIGINT NOT NULL REFERENCES dataset_releases (dataset_id) ON DELETE RESTRICT,
  region_id         TEXT NOT NULL REFERENCES regions (region_id) ON DELETE RESTRICT,
  node_mapping_id   BIGINT NOT NULL REFERENCES node_mappings (node_mapping_id) ON DELETE RESTRICT,
  cutoff_ts         TIMESTAMPTZ NOT NULL,
  forecast_ts       TIMESTAMPTZ,
  snapshot_version  TEXT NOT NULL DEFAULT '1',
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (forecast_ts IS NULL OR forecast_ts > cutoff_ts),
  -- Danh tính snapshot (spec 3.3, 11.3). cutoff_ts đứng trước node_mapping_id
  -- để index này phục vụ luôn truy vấn khoảng thời gian (dataset, region, cutoff).
  CONSTRAINT snapshots_identity_key UNIQUE (dataset_id, region_id, cutoff_ts, node_mapping_id)
);

-- Trạng thái thị trường từng hex tại một snapshot. Null luôn đi kèm lý do.
CREATE TABLE hex_market_states (
  snapshot_id              BIGINT NOT NULL REFERENCES snapshots (snapshot_id) ON DELETE RESTRICT,
  hex_id                   TEXT NOT NULL REFERENCES hexes (hex_id) ON DELETE RESTRICT,
  demand                   INTEGER CHECK (demand >= 0),              -- demand_5m
  idle_supply              INTEGER CHECK (idle_supply >= 0),         -- idle_supply_t
  effective_supply         DOUBLE PRECISION CHECK (effective_supply >= 0 AND effective_supply < 'Infinity'),
  observed_ds              DOUBLE PRECISION CHECK (observed_ds >= 0 AND observed_ds < 'Infinity'),
  observed_ds_null_reason  TEXT,                                     -- ví dụ 'ZERO_EFFECTIVE_SUPPLY'
  eta_sec                  DOUBLE PRECISION CHECK (eta_sec >= 0 AND eta_sec < 'Infinity'),
  surge_base               NUMERIC(6,4) NOT NULL CHECK (surge_base > 0 AND surge_base < 100),
  bidding_source_version   TEXT,
  null_reasons             JSONB NOT NULL DEFAULT '{}',              -- lý do null cho các cột khác
  PRIMARY KEY (snapshot_id, hex_id),
  CHECK ((observed_ds IS NULL) = (observed_ds_null_reason IS NOT NULL))
);

-- -----------------------------------------------------------------------------
-- 3. Provider, policy, recommendation (bất biến sau khi publish)
-- -----------------------------------------------------------------------------

CREATE TABLE providers (
  provider_id   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  provider_key  TEXT NOT NULL UNIQUE,                 -- ví dụ 'gnn_provider'
  kind          TEXT NOT NULL CHECK (kind IN ('MOCK','RULE_BASED','ML','GNN','PRECOMPUTED')),
  description   TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Mỗi thay đổi giới hạn surge là một dòng mới. Chỉ is_active được phép đổi.
CREATE TABLE policy_configs (
  policy_config_id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  policy_version            TEXT NOT NULL UNIQUE,
  surge_min                 NUMERIC(6,4) NOT NULL CHECK (surge_min > 0 AND surge_min < 100),
  surge_max                 NUMERIC(6,4) NOT NULL CHECK (surge_max > 0 AND surge_max < 100),
  max_deviation             NUMERIC(6,4) NOT NULL CHECK (max_deviation >= 0 AND max_deviation < 100),
  step                      NUMERIC(6,4) NOT NULL CHECK (step > 0 AND step < 100),
  precision                 SMALLINT NOT NULL CHECK (precision BETWEEN 0 AND 4),
  override_reason_required  BOOLEAN NOT NULL DEFAULT true,
  is_active                 BOOLEAN NOT NULL DEFAULT false,
  created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (surge_min <= surge_max)
);
-- Tối đa một policy đang active.
CREATE UNIQUE INDEX policy_configs_single_active_idx ON policy_configs ((true)) WHERE is_active;

CREATE TABLE recommendation_sets (
  recommendation_set_id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  snapshot_id                    BIGINT NOT NULL REFERENCES snapshots (snapshot_id) ON DELETE RESTRICT,
  provider_id                    BIGINT NOT NULL REFERENCES providers (provider_id) ON DELETE RESTRICT,
  provider_version               TEXT NOT NULL,
  policy_config_id               BIGINT NOT NULL REFERENCES policy_configs (policy_config_id) ON DELETE RESTRICT,
  output_contract_version        TEXT NOT NULL,       -- ví dụ 'recommendation.v1'
  source_run_id                  TEXT NOT NULL,       -- inference run / file đã import
  provider_reported_fingerprint  TEXT NOT NULL,       -- fingerprint provider khai báo, đối chiếu với dataset
  forecast_metric_id             TEXT REFERENCES metric_definitions (metric_id) ON DELETE RESTRICT,
  status                         TEXT NOT NULL DEFAULT 'INGESTING'
                                 CHECK (status IN ('INGESTING','PUBLISHED','REJECTED','SUPERSEDED')),
  generated_at                   TIMESTAMPTZ NOT NULL,  -- thời điểm provider tạo output
  imported_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
  published_at                   TIMESTAMPTZ,
  superseded_at                  TIMESTAMPTZ,
  model_metadata                 JSONB NOT NULL DEFAULT '{}',  -- checkpoint, feature schema, target transform...
  validation_summary             JSONB NOT NULL DEFAULT '{}',  -- lỗi cấp set
  UNIQUE (snapshot_id, provider_id, provider_version, source_run_id),
  UNIQUE (recommendation_set_id, snapshot_id),        -- đích cho FK kép từ recommendations/batch_plans
  CHECK ((status IN ('PUBLISHED','SUPERSEDED')) = (published_at IS NOT NULL)),
  CHECK ((status = 'SUPERSEDED') = (superseded_at IS NOT NULL))
);
-- Mỗi (snapshot, provider) chỉ có một set PUBLISHED đang hiệu lực.
CREATE UNIQUE INDEX recommendation_sets_one_published_idx
  ON recommendation_sets (snapshot_id, provider_id) WHERE status = 'PUBLISHED';
CREATE INDEX recommendation_sets_provider_id_idx ON recommendation_sets (provider_id);
CREATE INDEX recommendation_sets_policy_config_id_idx ON recommendation_sets (policy_config_id);

CREATE TABLE recommendations (
  proposal_id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  recommendation_set_id  BIGINT NOT NULL,
  snapshot_id            BIGINT NOT NULL,
  external_proposal_id   TEXT,                        -- proposal_id provider gửi, ví dụ 'rec_001'
  hex_id                 TEXT,                        -- NULL khi provider gửi hex không thuộc snapshot
  proposal_version       INTEGER NOT NULL DEFAULT 1 CHECK (proposal_version >= 1),
  action                 TEXT CHECK (action IN ('INCREASE','DECREASE','HOLD','REVIEW')),
  surge_base             NUMERIC(6,4) CHECK (surge_base > 0 AND surge_base < 100),
  surge_delta            NUMERIC(6,4) CHECK (surge_delta > -100 AND surge_delta < 100),
  surge_proposed         NUMERIC(6,4) CHECK (surge_proposed > 0 AND surge_proposed < 100),
  explanation            TEXT,
  reason_codes           TEXT[] NOT NULL DEFAULT '{}',
  evidence               JSONB NOT NULL DEFAULT '{}',
  raw_payload            JSONB NOT NULL,              -- bản gốc provider gửi, giữ để truy vết
  validation_status      TEXT NOT NULL CHECK (validation_status IN ('VALID','INVALID')),
  validation_errors      JSONB NOT NULL DEFAULT '[]',
  created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),

  FOREIGN KEY (recommendation_set_id, snapshot_id)
    REFERENCES recommendation_sets (recommendation_set_id, snapshot_id) ON DELETE RESTRICT,
  -- Hex phải có market state trong đúng snapshot đó (validation 4.5 mục 4).
  FOREIGN KEY (snapshot_id, hex_id)
    REFERENCES hex_market_states (snapshot_id, hex_id) ON DELETE RESTRICT,

  UNIQUE (proposal_id, recommendation_set_id),        -- đích cho FK kép từ batch_plan_items
  UNIQUE (proposal_id, proposal_version),             -- đích cho FK kép từ decisions

  -- Dòng VALID phải đủ trường bắt buộc.
  CHECK (validation_status = 'INVALID' OR (
    external_proposal_id IS NOT NULL AND hex_id IS NOT NULL
    AND action IS NOT NULL AND surge_base IS NOT NULL AND explanation IS NOT NULL)),
  -- Dòng INVALID phải có ít nhất một lỗi.
  CHECK (validation_status = 'VALID' OR jsonb_array_length(validation_errors) > 0),
  -- Nhất quán action/surge (spec 5.1 Layer B), chỉ áp cho dòng VALID.
  CHECK (validation_status = 'INVALID' OR action = 'REVIEW' OR (
    surge_proposed IS NOT NULL AND surge_delta IS NOT NULL
    AND surge_delta = surge_proposed - surge_base
    AND (   (action = 'INCREASE' AND surge_proposed > surge_base)
         OR (action = 'DECREASE' AND surge_proposed < surge_base)
         OR (action = 'HOLD'     AND surge_proposed = surge_base)))),
  -- REVIEW không mang giá có thể phê duyệt khác base.
  CHECK (validation_status = 'INVALID' OR action <> 'REVIEW'
         OR surge_proposed IS NULL OR surge_proposed = surge_base)
);
-- Không trùng hex / proposal id trong cùng set (chỉ xét dòng VALID; dòng trùng được lưu là INVALID).
CREATE UNIQUE INDEX recommendations_set_hex_valid_key
  ON recommendations (recommendation_set_id, hex_id) WHERE validation_status = 'VALID';
CREATE UNIQUE INDEX recommendations_set_external_valid_key
  ON recommendations (recommendation_set_id, external_proposal_id) WHERE validation_status = 'VALID';
CREATE INDEX recommendations_set_hex_idx ON recommendations (recommendation_set_id, hex_id);
CREATE INDEX recommendations_snapshot_action_idx ON recommendations (snapshot_id, action);
CREATE INDEX recommendations_snapshot_hex_idx ON recommendations (snapshot_id, hex_id);

-- -----------------------------------------------------------------------------
-- 4. Actor, demo session, decision
-- -----------------------------------------------------------------------------

CREATE TABLE actors (
  actor_id      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  actor_key     TEXT NOT NULL UNIQUE,                 -- định danh do backend cấp, không do frontend tự khai
  display_name  TEXT NOT NULL,
  role          TEXT NOT NULL CHECK (role IN ('OPERATOR','VIEWER','ADMIN')),
  is_active     BOOLEAN NOT NULL DEFAULT true,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE demo_sessions (
  demo_session_id  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  owner_actor_id   BIGINT NOT NULL REFERENCES actors (actor_id) ON DELETE RESTRICT,
  name             TEXT NOT NULL,
  execution_mode   TEXT NOT NULL DEFAULT 'DEMO' CHECK (execution_mode = 'DEMO'),
  status           TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','CLOSED')),
  metadata         JSONB NOT NULL DEFAULT '{}',
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  closed_at        TIMESTAMPTZ,
  CHECK ((status = 'CLOSED') = (closed_at IS NOT NULL))
);
CREATE INDEX demo_sessions_owner_created_idx ON demo_sessions (owner_actor_id, created_at);

-- Quyết định của operator. Không sửa recommendation; giá trị gốc lấy qua proposal_id.
CREATE TABLE decisions (
  decision_id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  demo_session_id   BIGINT NOT NULL REFERENCES demo_sessions (demo_session_id) ON DELETE RESTRICT,
  proposal_id       BIGINT NOT NULL,
  proposal_version  INTEGER NOT NULL,
  actor_id          BIGINT NOT NULL REFERENCES actors (actor_id) ON DELETE RESTRICT,
  policy_config_id  BIGINT NOT NULL REFERENCES policy_configs (policy_config_id) ON DELETE RESTRICT,
  action            TEXT NOT NULL CHECK (action IN ('ACCEPT_PROPOSAL','KEEP_BIDDING','OVERRIDE_PROPOSAL')),
  requested_surge   NUMERIC(6,4) CHECK (requested_surge > 0 AND requested_surge < 100),
  surge_decided     NUMERIC(6,4) CHECK (surge_decided > 0 AND surge_decided < 100),
  reason            TEXT,
  status            TEXT NOT NULL DEFAULT 'PENDING'
                    CHECK (status IN ('PENDING','RECORDED','KEPT_BIDDING','REJECTED','FAILED')),
  error_code        TEXT,
  error_message     TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  recorded_at       TIMESTAMPTZ,

  FOREIGN KEY (proposal_id, proposal_version)
    REFERENCES recommendations (proposal_id, proposal_version) ON DELETE RESTRICT,
  UNIQUE (decision_id, proposal_id),                  -- đích cho FK kép từ decision_batch_items

  -- requested_surge chỉ có ở OVERRIDE và bắt buộc ở OVERRIDE.
  CHECK ((action = 'OVERRIDE_PROPOSAL') = (requested_surge IS NOT NULL)),
  -- Thành công phải có giá quyết định và thời điểm ghi nhận.
  CHECK (status NOT IN ('RECORDED','KEPT_BIDDING') OR (surge_decided IS NOT NULL AND recorded_at IS NOT NULL)),
  -- KEEP_BIDDING thành công luôn mang status KEPT_BIDDING, các action khác thành công là RECORDED.
  CHECK (status <> 'KEPT_BIDDING' OR action = 'KEEP_BIDDING'),
  CHECK (status <> 'RECORDED' OR action <> 'KEEP_BIDDING'),
  -- Thất bại/bị từ chối phải có mã lỗi.
  CHECK (status NOT IN ('REJECTED','FAILED') OR error_code IS NOT NULL)
);
-- Chốt chống race (spec 6.6, BE-13): mỗi proposal chỉ có một quyết định thành công trong một session.
CREATE UNIQUE INDEX decisions_one_final_per_session_key
  ON decisions (demo_session_id, proposal_id) WHERE status IN ('RECORDED','KEPT_BIDDING');
CREATE INDEX decisions_session_proposal_idx ON decisions (demo_session_id, proposal_id);
CREATE INDEX decisions_proposal_idx ON decisions (proposal_id, proposal_version);
CREATE INDEX decisions_actor_created_idx ON decisions (actor_id, created_at);
CREATE INDEX decisions_policy_config_id_idx ON decisions (policy_config_id);

-- Vòng đời decision: chỉ PENDING được chuyển sang trạng thái cuối, trạng thái cuối bất biến.
CREATE FUNCTION check_decision_transition() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.status <> 'PENDING' THEN
    RAISE EXCEPTION 'DECISION_FINAL: decision % is already %', OLD.decision_id, OLD.status
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$;

-- -----------------------------------------------------------------------------
-- 5. Batch: plan (preview đóng băng), batch commit, item
-- -----------------------------------------------------------------------------

CREATE TABLE batch_plans (
  batch_plan_id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  demo_session_id        BIGINT NOT NULL REFERENCES demo_sessions (demo_session_id) ON DELETE RESTRICT,
  actor_id               BIGINT NOT NULL REFERENCES actors (actor_id) ON DELETE RESTRICT,
  snapshot_id            BIGINT NOT NULL,
  recommendation_set_id  BIGINT NOT NULL,
  policy_config_id       BIGINT NOT NULL REFERENCES policy_configs (policy_config_id) ON DELETE RESTRICT,
  selection_mode         TEXT NOT NULL CHECK (selection_mode IN ('ALL_ELIGIBLE','SELECTED')),
  created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at             TIMESTAMPTZ NOT NULL,
  FOREIGN KEY (recommendation_set_id, snapshot_id)
    REFERENCES recommendation_sets (recommendation_set_id, snapshot_id) ON DELETE RESTRICT,
  UNIQUE (batch_plan_id, recommendation_set_id),      -- đích cho FK kép từ batch_plan_items
  UNIQUE (batch_plan_id, demo_session_id),            -- đích cho FK kép từ decision_batches
  CHECK (expires_at > created_at)
);
CREATE INDEX batch_plans_session_created_idx ON batch_plans (demo_session_id, created_at);
CREATE INDEX batch_plans_set_snapshot_idx ON batch_plans (recommendation_set_id, snapshot_id);
CREATE INDEX batch_plans_actor_id_idx ON batch_plans (actor_id);

CREATE TABLE batch_plan_items (
  batch_plan_id          BIGINT NOT NULL,
  proposal_id            BIGINT NOT NULL,
  recommendation_set_id  BIGINT NOT NULL,
  proposal_version       INTEGER NOT NULL,
  eligible               BOOLEAN NOT NULL,
  skip_reason_code       TEXT,
  PRIMARY KEY (batch_plan_id, proposal_id),
  -- Hai FK kép này buộc mọi item thuộc đúng recommendation set (và snapshot) của plan (BE-09).
  FOREIGN KEY (batch_plan_id, recommendation_set_id)
    REFERENCES batch_plans (batch_plan_id, recommendation_set_id) ON DELETE RESTRICT,
  FOREIGN KEY (proposal_id, recommendation_set_id)
    REFERENCES recommendations (proposal_id, recommendation_set_id) ON DELETE RESTRICT,
  FOREIGN KEY (proposal_id, proposal_version)
    REFERENCES recommendations (proposal_id, proposal_version) ON DELETE RESTRICT,
  CHECK (eligible = (skip_reason_code IS NULL))
);
CREATE INDEX batch_plan_items_proposal_idx ON batch_plan_items (proposal_id, recommendation_set_id);

CREATE TABLE decision_batches (
  batch_id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  batch_plan_id    BIGINT NOT NULL UNIQUE,            -- một plan chỉ commit một lần
  demo_session_id  BIGINT NOT NULL,
  actor_id         BIGINT NOT NULL REFERENCES actors (actor_id) ON DELETE RESTRICT,
  status           TEXT NOT NULL DEFAULT 'PROCESSING'
                   CHECK (status IN ('PROCESSING','SUCCEEDED','PARTIAL_SUCCESS','FAILED')),
  total_count      INTEGER NOT NULL CHECK (total_count >= 0),
  success_count    INTEGER NOT NULL DEFAULT 0 CHECK (success_count >= 0),
  failure_count    INTEGER NOT NULL DEFAULT 0 CHECK (failure_count >= 0),
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at     TIMESTAMPTZ,
  FOREIGN KEY (batch_plan_id, demo_session_id)
    REFERENCES batch_plans (batch_plan_id, demo_session_id) ON DELETE RESTRICT,
  UNIQUE (batch_id, batch_plan_id),                   -- đích cho FK kép từ decision_batch_items
  CHECK (success_count + failure_count <= total_count),
  CHECK ((status = 'PROCESSING') = (completed_at IS NULL)),
  CHECK (status = 'PROCESSING' OR success_count + failure_count = total_count)
);
CREATE INDEX decision_batches_session_created_idx ON decision_batches (demo_session_id, created_at);
CREATE INDEX decision_batches_actor_id_idx ON decision_batches (actor_id);

CREATE TABLE decision_batch_items (
  batch_id       BIGINT NOT NULL,
  batch_plan_id  BIGINT NOT NULL,
  proposal_id    BIGINT NOT NULL,
  status         TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','SUCCESS','FAILED')),
  decision_id    BIGINT UNIQUE,
  error_code     TEXT,
  error_message  TEXT,
  processed_at   TIMESTAMPTZ,
  PRIMARY KEY (batch_id, proposal_id),
  FOREIGN KEY (batch_id, batch_plan_id)
    REFERENCES decision_batches (batch_id, batch_plan_id) ON DELETE RESTRICT,
  -- Chỉ xử lý proposal đã có trong plan lúc preview (BE-23).
  FOREIGN KEY (batch_plan_id, proposal_id)
    REFERENCES batch_plan_items (batch_plan_id, proposal_id) ON DELETE RESTRICT,
  -- Decision gắn với item phải đúng proposal của item.
  FOREIGN KEY (decision_id, proposal_id)
    REFERENCES decisions (decision_id, proposal_id) ON DELETE RESTRICT,
  CHECK (status <> 'SUCCESS' OR decision_id IS NOT NULL),
  CHECK (status <> 'FAILED'  OR error_code IS NOT NULL),
  CHECK ((status = 'PENDING') = (processed_at IS NULL))
);
CREATE INDEX decision_batch_items_plan_proposal_idx ON decision_batch_items (batch_plan_id, proposal_id);
-- Tìm nhanh item còn dở để resume sau khi server dừng giữa chừng (BE-21).
CREATE INDEX decision_batch_items_pending_idx ON decision_batch_items (batch_id) WHERE status = 'PENDING';

-- -----------------------------------------------------------------------------
-- 6. Idempotency
-- -----------------------------------------------------------------------------

CREATE TABLE idempotency_records (
  idempotency_record_id  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  actor_id               BIGINT NOT NULL REFERENCES actors (actor_id) ON DELETE RESTRICT,
  demo_session_id        BIGINT NOT NULL REFERENCES demo_sessions (demo_session_id) ON DELETE RESTRICT,
  operation              TEXT NOT NULL CHECK (operation IN ('DECISION','BATCH_COMMIT')),
  idempotency_key        TEXT NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 200),
  request_hash           TEXT NOT NULL,               -- sha256 của payload đã chuẩn hoá
  state                  TEXT NOT NULL DEFAULT 'IN_PROGRESS' CHECK (state IN ('IN_PROGRESS','COMPLETED')),
  response_code          SMALLINT,
  response_body          JSONB,
  resource_type          TEXT CHECK (resource_type IN ('DECISION','DECISION_BATCH')),
  resource_id            BIGINT,
  created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at           TIMESTAMPTZ,
  CONSTRAINT idempotency_records_scope_key UNIQUE (actor_id, demo_session_id, operation, idempotency_key),
  CHECK ((state = 'COMPLETED') = (completed_at IS NOT NULL AND response_code IS NOT NULL))
);
CREATE INDEX idempotency_records_session_idx ON idempotency_records (demo_session_id);

-- -----------------------------------------------------------------------------
-- 7. Audit (append-only)
-- -----------------------------------------------------------------------------

CREATE TABLE audit_events (
  event_id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  actor_id         BIGINT REFERENCES actors (actor_id) ON DELETE RESTRICT,           -- NULL = hệ thống (ingestion)
  demo_session_id  BIGINT REFERENCES demo_sessions (demo_session_id) ON DELETE RESTRICT,
  entity_type      TEXT NOT NULL CHECK (entity_type IN (
                     'DATASET_RELEASE','SNAPSHOT','RECOMMENDATION_SET','RECOMMENDATION',
                     'POLICY_CONFIG','DEMO_SESSION','DECISION','BATCH_PLAN','DECISION_BATCH')),
  entity_id        BIGINT NOT NULL,
  action           TEXT NOT NULL,                     -- ví dụ 'DECISION_RECORDED', 'SET_PUBLISHED'
  previous_state   JSONB,
  new_state        JSONB,
  metadata         JSONB NOT NULL DEFAULT '{}',
  correlation_id   TEXT NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX audit_events_entity_idx ON audit_events (entity_type, entity_id, created_at);
CREATE INDEX audit_events_session_created_idx ON audit_events (demo_session_id, created_at);
CREATE INDEX audit_events_actor_created_idx ON audit_events (actor_id, created_at);
CREATE INDEX audit_events_correlation_idx ON audit_events (correlation_id);

-- -----------------------------------------------------------------------------
-- 8. Trigger bất biến và vòng đời
-- -----------------------------------------------------------------------------

-- Bất biến hoàn toàn.
CREATE TRIGGER dataset_releases_immutable BEFORE UPDATE OR DELETE ON dataset_releases
  FOR EACH ROW EXECUTE FUNCTION guard_immutable_columns();
CREATE TRIGGER snapshots_immutable BEFORE UPDATE OR DELETE ON snapshots
  FOR EACH ROW EXECUTE FUNCTION guard_immutable_columns();
CREATE TRIGGER hex_market_states_immutable BEFORE UPDATE OR DELETE ON hex_market_states
  FOR EACH ROW EXECUTE FUNCTION guard_immutable_columns();
CREATE TRIGGER recommendations_immutable BEFORE UPDATE OR DELETE ON recommendations
  FOR EACH ROW EXECUTE FUNCTION guard_immutable_columns();
CREATE TRIGGER batch_plan_items_immutable BEFORE UPDATE OR DELETE ON batch_plan_items
  FOR EACH ROW EXECUTE FUNCTION guard_immutable_columns();
CREATE TRIGGER audit_events_append_only BEFORE UPDATE OR DELETE ON audit_events
  FOR EACH ROW EXECUTE FUNCTION guard_immutable_columns();
CREATE TRIGGER audit_events_no_truncate BEFORE TRUNCATE ON audit_events
  FOR EACH STATEMENT EXECUTE FUNCTION forbid_truncate();

-- Chỉ cho đổi một số cột theo vòng đời.
CREATE TRIGGER policy_configs_guard BEFORE UPDATE OR DELETE ON policy_configs
  FOR EACH ROW EXECUTE FUNCTION guard_immutable_columns('is_active');
CREATE TRIGGER recommendation_sets_guard BEFORE UPDATE OR DELETE ON recommendation_sets
  FOR EACH ROW EXECUTE FUNCTION guard_immutable_columns('status', 'published_at', 'superseded_at', 'validation_summary');
CREATE TRIGGER demo_sessions_guard BEFORE UPDATE OR DELETE ON demo_sessions
  FOR EACH ROW EXECUTE FUNCTION guard_immutable_columns('status', 'closed_at', 'metadata');
CREATE TRIGGER batch_plans_guard BEFORE UPDATE OR DELETE ON batch_plans
  FOR EACH ROW EXECUTE FUNCTION guard_immutable_columns();
CREATE TRIGGER decisions_guard BEFORE UPDATE OR DELETE ON decisions
  FOR EACH ROW EXECUTE FUNCTION guard_immutable_columns('status', 'surge_decided', 'error_code', 'error_message', 'recorded_at');
CREATE TRIGGER decisions_transition BEFORE UPDATE ON decisions
  FOR EACH ROW EXECUTE FUNCTION check_decision_transition();
CREATE TRIGGER decision_batches_guard BEFORE UPDATE OR DELETE ON decision_batches
  FOR EACH ROW EXECUTE FUNCTION guard_immutable_columns('status', 'success_count', 'failure_count', 'completed_at');
CREATE TRIGGER decision_batch_items_guard BEFORE UPDATE OR DELETE ON decision_batch_items
  FOR EACH ROW EXECUTE FUNCTION guard_immutable_columns('status', 'decision_id', 'error_code', 'error_message', 'processed_at');
CREATE TRIGGER idempotency_records_guard BEFORE UPDATE OR DELETE ON idempotency_records
  FOR EACH ROW EXECUTE FUNCTION guard_immutable_columns('state', 'response_code', 'response_body', 'resource_type', 'resource_id', 'completed_at');

-- Vòng đời recommendation set: INGESTING -> PUBLISHED | REJECTED, PUBLISHED -> SUPERSEDED.
CREATE FUNCTION check_recommendation_set_transition() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
       (OLD.status = 'INGESTING' AND NEW.status IN ('PUBLISHED','REJECTED'))
    OR (OLD.status = 'PUBLISHED' AND NEW.status = 'SUPERSEDED')) THEN
    RAISE EXCEPTION 'INVALID_TRANSITION: recommendation set % cannot go % -> %',
      OLD.recommendation_set_id, OLD.status, NEW.status
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER recommendation_sets_transition BEFORE UPDATE ON recommendation_sets
  FOR EACH ROW EXECUTE FUNCTION check_recommendation_set_transition();

-- Chỉ được thêm recommendation khi set còn INGESTING: set đã publish là bất biến.
CREATE FUNCTION check_recommendation_set_open() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  set_status TEXT;
BEGIN
  SELECT status INTO set_status FROM recommendation_sets
   WHERE recommendation_set_id = NEW.recommendation_set_id
   FOR SHARE;
  IF set_status IS DISTINCT FROM 'INGESTING' THEN
    RAISE EXCEPTION 'SET_NOT_OPEN: recommendation set % is %', NEW.recommendation_set_id, set_status
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER recommendations_set_open BEFORE INSERT ON recommendations
  FOR EACH ROW EXECUTE FUNCTION check_recommendation_set_open();

-- -----------------------------------------------------------------------------
-- 9. View eligibility (không lưu cứng, suy ra từ dữ liệu hiện hành)
-- -----------------------------------------------------------------------------
-- Eligibility độc lập với action (spec 5.4). View này không phụ thuộc demo session;
-- trạng thái "đã quyết định trong session" ghép thêm ở truy vấn queue (xem ERD.md mục 7).
-- EXPIRED không phát sinh ở chế độ DEMO_REPLAY (spec 5.5), nên view không sinh EXPIRED.
CREATE VIEW v_recommendation_eligibility AS
SELECT
  r.proposal_id,
  r.recommendation_set_id,
  r.snapshot_id,
  r.hex_id,
  r.proposal_version,
  r.action,
  r.surge_base,
  r.surge_delta,
  r.surge_proposed,
  CASE
    WHEN rs.status = 'SUPERSEDED'                       THEN 'SUPERSEDED'
    WHEN rs.status <> 'PUBLISHED'                       THEN 'BLOCKED'
    WHEN r.validation_status = 'INVALID'                THEN 'BLOCKED'
    WHEN r.action = 'REVIEW'                            THEN 'BLOCKED'
    WHEN ap.policy_config_id IS NULL                    THEN 'UNKNOWN'
    WHEN ap.policy_config_id <> rs.policy_config_id     THEN 'BLOCKED'
    WHEN r.surge_proposed < ap.surge_min
      OR r.surge_proposed > ap.surge_max
      OR abs(r.surge_proposed - r.surge_base) > ap.max_deviation
      OR r.surge_proposed <> round(r.surge_proposed, ap.precision)
      OR mod(r.surge_proposed - ap.surge_min, ap.step) <> 0 THEN 'BLOCKED'
    ELSE 'ELIGIBLE'
  END AS eligibility,
  CASE
    WHEN rs.status = 'SUPERSEDED'                       THEN 'PROPOSAL_SUPERSEDED'
    WHEN rs.status <> 'PUBLISHED'                       THEN 'SET_NOT_PUBLISHED'
    WHEN r.validation_status = 'INVALID'                THEN 'PROVIDER_OUTPUT_INVALID'
    WHEN r.action = 'REVIEW'                            THEN 'REVIEW_REQUIRED'
    WHEN ap.policy_config_id IS NULL                    THEN 'NO_ACTIVE_POLICY'
    WHEN ap.policy_config_id <> rs.policy_config_id     THEN 'POLICY_VERSION_CONFLICT'
    WHEN r.surge_proposed < ap.surge_min
      OR r.surge_proposed > ap.surge_max
      OR abs(r.surge_proposed - r.surge_base) > ap.max_deviation THEN 'SURGE_LIMIT_EXCEEDED'
    WHEN r.surge_proposed <> round(r.surge_proposed, ap.precision) THEN 'INVALID_SURGE_PRECISION'
    WHEN mod(r.surge_proposed - ap.surge_min, ap.step) <> 0 THEN 'INVALID_SURGE_STEP'
    ELSE NULL
  END AS blocked_reason
FROM recommendations r
JOIN recommendation_sets rs ON rs.recommendation_set_id = r.recommendation_set_id
LEFT JOIN policy_configs ap ON ap.is_active;

-- -----------------------------------------------------------------------------
-- 10. Mô tả bảng
-- -----------------------------------------------------------------------------
COMMENT ON TABLE dataset_releases     IS 'Một bản phát hành dữ liệu (data/CURRENT.json). Bất biến.';
COMMENT ON TABLE snapshots            IS 'Trạng thái marketplace tại một cutoff_ts; không phụ thuộc provider. Bất biến.';
COMMENT ON TABLE hex_market_states    IS 'Market state mỗi (snapshot, hex): demand, supply, D/S quan sát, surge_base. Null luôn có lý do. Bất biến.';
COMMENT ON TABLE recommendation_sets  IS 'Output của một provider trên một snapshot. Chỉ status/published_at/superseded_at đổi được.';
COMMENT ON TABLE recommendations      IS 'Một proposal cho một hex. Bất biến; dòng INVALID giữ lại để truy vết lỗi provider.';
COMMENT ON TABLE policy_configs       IS 'Giới hạn surge theo version. Đổi giới hạn = thêm dòng mới.';
COMMENT ON TABLE demo_sessions        IS 'Phạm vi cô lập quyết định mô phỏng; execution_mode luôn DEMO.';
COMMENT ON TABLE decisions            IS 'Quyết định của operator; tối đa một quyết định thành công mỗi (session, proposal).';
COMMENT ON TABLE batch_plans          IS 'Kết quả preview batch: tập proposal được đóng băng.';
COMMENT ON TABLE decision_batches     IS 'Một lần commit batch plan; hỗ trợ partial success.';
COMMENT ON TABLE decision_batch_items IS 'Kết quả từng proposal trong batch; PENDING còn lại dùng để resume.';
COMMENT ON TABLE idempotency_records  IS 'Kết quả của request mutation theo (actor, session, operation, key).';
COMMENT ON TABLE audit_events         IS 'Nhật ký append-only; UPDATE/DELETE/TRUNCATE bị chặn bằng trigger.';

COMMIT;

-- -----------------------------------------------------------------------------
-- Gợi ý phân quyền (chạy riêng, đổi tên role theo môi trường):
--   CREATE ROLE surge_app LOGIN PASSWORD '...';
--   GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA public TO surge_app;
--   GRANT UPDATE ON recommendation_sets, policy_configs, demo_sessions, decisions,
--                   decision_batches, decision_batch_items, idempotency_records TO surge_app;
--   GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO surge_app;
--   -- Không GRANT UPDATE/DELETE/TRUNCATE trên audit_events cho role ứng dụng.
-- -----------------------------------------------------------------------------
