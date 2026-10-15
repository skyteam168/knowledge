from functools import lru_cache
from typing import Any, Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_DIRECTORY_SECRET = "change-me-directory-secret"
DEV_OIDC_BRIDGE_SECRET = "change-me-oidc-bridge-secret"
DEV_OPEN_API_PEPPER = "change-me-open-api-pepper"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Enterprise Knowledge Base"
    app_env: Literal["dev", "test", "staging", "prod"] = "dev"
    log_level: str = "INFO"
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    database_url: str = "postgresql+asyncpg://ekb:ekb@localhost:5432/ekb"
    database_pool_size: int = 10
    # Per process: (pool_size + max_overflow) x processes must stay below PG max_connections.
    database_max_overflow: int = 10
    database_pool_timeout_seconds: float = 10.0
    database_pool_recycle_seconds: int = 1800
    database_echo: bool = False

    redis_url: str = "redis://localhost:6379/0"

    minio_endpoint: str = "http://localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "ekb-documents"
    # Browser-facing endpoint used to sign upload/preview URLs (signature covers the host).
    minio_public_endpoint: str = "http://localhost:9000"
    minio_region: str = "us-east-1"
    presign_expiry_seconds: int = 3600

    upload_max_bytes: int = 200 * 1024 * 1024
    upload_ticket_ttl_seconds: int = 3600

    # PDF backend: auto = docling when installed, else the built-in pdfplumber parser.
    pdf_parser: Literal["auto", "docling", "mineru", "basic"] = "auto"
    mineru_api_url: str | None = None
    mineru_timeout_seconds: float = 600.0
    ocr_enabled: bool = True
    # Pages with fewer extracted characters than this are treated as scanned and OCR'd.
    ocr_min_page_chars: int = 20

    chunk_parent_target_tokens: int = 1500
    chunk_parent_max_tokens: int = 2000
    chunk_child_target_tokens: int = 400
    chunk_child_max_tokens: int = 500
    chunk_child_overlap_tokens: int = 60

    ingest_max_retries: int = 3

    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    qdrant_timeout_seconds: float = 30.0

    opensearch_url: str = "http://localhost:9200"
    opensearch_user: str | None = None
    opensearch_password: str | None = None
    opensearch_timeout_seconds: float = 60.0
    opensearch_shards: int = 1
    opensearch_replicas: int = 0
    # Relative to the OpenSearch config dir; must exist on every node.
    opensearch_synonyms_path: str = "analysis/synonyms.txt"

    # Readers use the aliases; physical names are `{alias}_v{generation}`.
    index_alias: str = "kb_chunks"
    index_write_batch_size: int = 128

    outbox_poll_interval_seconds: float = 2.0
    outbox_batch_size: int = 50
    outbox_max_attempts: int = 8
    outbox_backoff_base_seconds: float = 5.0
    outbox_backoff_max_seconds: float = 1800.0
    # A claimed event not finished within the lease is claimed again (worker crash).
    outbox_lease_seconds: int = 900

    keycloak_url: str = "http://localhost:8080"
    keycloak_public_url: str = "http://localhost:8080"
    keycloak_realm: str = "ekb"
    keycloak_audience: str = "ekb-backend"
    jwks_cache_ttl_seconds: int = 600
    jwt_leeway_seconds: int = 30
    auth_org_claim: str = "org_id"
    auth_default_org_code: str = "default"
    auth_auto_create_org: bool = True
    auth_ignored_roles: list[str] = ["offline_access", "uma_authorization"]
    platform_admin_role: str = "platform_admin"
    authz_cache_ttl_seconds: int = 600

    # openai: OpenAI-compatible HTTP endpoints (vLLM / TEI); mock: in-process fakes.
    llm_provider: Literal["openai", "mock"] = "openai"
    embedding_base_url: str = "http://localhost:9100/v1"
    embedding_model: str = "mock-embedding"
    embedding_dim: int = 1024
    # Send `dimensions` in requests (Matryoshka models such as Qwen3-Embedding).
    embedding_send_dimensions: bool = False
    embedding_batch_size: int = 32
    embedding_concurrency: int = 4
    embedding_timeout_seconds: float = 60.0
    rerank_base_url: str = "http://localhost:9100/v1"
    rerank_model: str = "mock-reranker"
    # Appended to rerank_base_url: vLLM `/rerank`, DashScope `/reranks`.
    rerank_path: str = "/rerank"
    # Task instruction for instruction-aware rerankers (DashScope qwen3-rerank `instruct`).
    rerank_instruct: str | None = None
    rerank_timeout_seconds: float = 30.0
    chat_base_url: str = "http://localhost:9100/v1"
    chat_model: str = "mock-chat"
    chat_fallback_base_url: str | None = None
    chat_fallback_model: str | None = None
    # Extra JSON fields merged into every chat request, e.g. {"enable_thinking": false}.
    chat_extra_body: dict[str, Any] = {}
    # Request `stream_options.include_usage`; disable for servers that reject the field.
    chat_stream_include_usage: bool = True
    # Record every model call (tokens, latency, caller) into llm_usage.
    llm_usage_enabled: bool = True
    llm_usage_flush_seconds: float = 2.0
    llm_usage_batch_size: int = 500
    # Register the models above in the model admin page on first start (enabled for the API
    # server in docker compose only).
    llm_config_import_on_startup: bool = False
    # Chat models chosen in the model admin page: each process re-reads them at most this often.
    llm_route_refresh_seconds: float = 5.0
    llm_check_timeout_seconds: float = 30.0
    # Encrypts provider API keys stored in the database; empty = DIRECTORY_SECRET_KEY.
    llm_secret_key: str = ""
    llm_api_key: str = "EMPTY"
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 2
    llm_retry_backoff_seconds: float = 0.5
    # Per process, shared by embedding / rerank / chat; every streaming answer holds one.
    llm_max_connections: int = 200
    llm_max_keepalive_connections: int = 50
    llm_pool_timeout_seconds: float = 10.0

    # Defaults of the built-in retrieval profile (orgs override them with stored profiles).
    retrieval_query_instruction: str = (
        "Instruct: Given a user question, retrieve relevant passages from the enterprise "
        "knowledge base that answer it\nQuery:"
    )
    retrieval_dense_top_k: int = 40
    retrieval_sparse_top_k: int = 40
    retrieval_rrf_k: int = 60
    retrieval_rerank_enabled: bool = True
    retrieval_rerank_top_n: int = 40
    retrieval_top_k: int = 10
    retrieval_embedding_cache_ttl_seconds: int = 7 * 24 * 3600
    retrieval_result_cache_ttl_seconds: int = 60
    # Serialized size cap of one retrieval_traces.stages document.
    retrieval_trace_max_bytes: int = 64 * 1024
    # Knowledge objects (is_ko=true) first: RRF score multiplier and rerank score bonus.
    retrieval_ko_boost_enabled: bool = True
    retrieval_ko_rrf_weight: float = 1.5
    retrieval_ko_rerank_bonus: float = 0.1

    # ---- AI assistant (question answering) ----
    # Previous user/assistant turns given to the rewriter and the answer prompt.
    chat_history_turns: int = 3
    chat_rewrite_enabled: bool = True
    chat_rewrite_timeout_seconds: float = 15.0
    # Sub-queries of a decomposed complex question (each retrieved separately, then merged).
    chat_max_subqueries: int = 3
    chat_retrieval_top_k: int = 8
    # Knowledge expansion: child -> parent chunk, +/- N adjacent chunks, related KOs.
    chat_expand_parent: bool = True
    chat_expand_neighbors: int = 1
    chat_expand_ko: bool = True
    # Published KOs citing the hit documents added to the context (besides KO hits).
    chat_expand_ko_limit: int = 2
    chat_context_token_budget: int = 6000
    # Evidence gate on the best rerank score: below min -> refuse without calling the LLM;
    # between min and confident -> answer, but uncertain parts must be called out.
    chat_evidence_min_score: float = 0.2
    chat_evidence_confident_score: float = 0.5
    chat_min_evidence: int = 1
    chat_temperature: float = 0.2
    chat_max_tokens: int = 1500
    chat_quote_max_chars: int = 300

    # ---- knowledge loop (gaps -> review -> knowledge objects) ----
    # Incremental clustering: cosine similarity of question embeddings to a cluster centroid.
    gap_cluster_similarity: float = 0.85
    # Only clusters seen within this window take new members.
    gap_cluster_window_days: int = 90
    gap_cluster_batch_size: int = 500
    gap_cluster_interval_seconds: float = 300.0
    # Knowledge compiler (LLM drafts) and conflict detection.
    ko_compiler_max_materials: int = 8
    ko_compiler_max_chars: int = 12000
    ko_compiler_timeout_seconds: float = 120.0
    ko_faq_max_items: int = 10
    ko_conflict_top_k: int = 8
    ko_conflict_min_score: float = 0.3
    ko_conflict_max_judgements: int = 5
    # Expiry reminders: owners are notified this many days before effective_to.
    expiry_notice_days: int = 7
    expiry_check_interval_seconds: float = 3600.0

    # ---- analytics (summary tables refreshed by the scheduler) ----
    # Day boundaries of the daily summaries.
    analytics_timezone: str = "Asia/Shanghai"
    analytics_refresh_interval_seconds: float = 900.0
    # Each refresh recomputes this many recent days (late feedback / gap resolutions).
    analytics_refresh_days: int = 2
    analytics_top_questions_per_day: int = 50
    # Indexed documents not cited for this many days are "zombie" documents.
    analytics_zombie_days: int = 90
    analytics_expiring_days: int = 30

    # ---- data retention (days; 0 keeps rows forever) ----
    # Traces hold questions and retrieved context; analytics keep their own daily summaries.
    retention_trace_days: int = 180
    retention_outbox_days: int = 30
    retention_api_call_log_days: int = 180
    retention_llm_usage_days: int = 365
    # Audit logs are often subject to compliance rules: kept unless configured.
    retention_audit_days: int = 0
    retention_batch_size: int = 5000
    retention_check_interval_seconds: float = 86400.0

    # ---- offline evaluation ----
    eval_judge_enabled: bool = True
    eval_judge_timeout_seconds: float = 60.0
    eval_max_cases_per_run: int = 1000
    eval_concurrency: int = 4

    # ---- observability ----
    otel_enabled: bool = False
    otel_service_name: str = "ekb-backend"
    # OTLP/HTTP endpoint of a collector (Jaeger, Tempo, otel-collector ...).
    otel_exporter_otlp_endpoint: str = "http://localhost:4318"
    otel_sample_ratio: float = 1.0
    # Optional: LLM spans (llm.*) are also exported to Langfuse's OTLP endpoint.
    langfuse_host: str | None = None
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    # Attach prompts/completions to llm.* spans (they may contain document content).
    llm_trace_content: bool = False
    metrics_enabled: bool = True
    # When set, GET /metrics requires `Authorization: Bearer <token>`.
    metrics_token: str | None = None
    metrics_gauge_cache_seconds: float = 10.0
    # Worker processes expose /metrics on this port (run one process per container/port).
    worker_metrics_port: int | None = None

    # ---- security hardening ----
    rate_limit_enabled: bool = True
    rate_limit_window_seconds: int = 60
    rate_limit_user_requests: int = 300
    rate_limit_org_requests: int = 3000
    # Question answering (LLM calls) has its own, tighter budget.
    rate_limit_chat_user_requests: int = 20
    rate_limit_chat_org_requests: int = 300
    rate_limit_upload_user_requests: int = 30
    # Allowed upload kinds (see services.ingest.parsers.base.detect_kind); empty = all supported.
    upload_allowed_kinds: list[str] = []
    # Reject files whose leading bytes contradict their extension.
    upload_sniff_content: bool = True
    virus_scan_backend: Literal["none", "clamav"] = "none"
    clamav_host: str = "localhost"
    clamav_port: int = 3310
    clamav_timeout_seconds: float = 30.0
    # Sensitive information masking: phone, id_card, email, bank_card.
    pii_mask_on_ingest: bool = False
    pii_mask_on_output: bool = False
    pii_types: list[str] = ["phone", "id_card", "bank_card"]

    # ---- open API for external agents ----
    open_api_enabled: bool = True
    # HMAC key for API key hashes; changing it invalidates every issued key.
    open_api_key_pepper: str = DEV_OPEN_API_PEPPER
    open_api_default_rate_per_minute: int = 60
    open_api_max_top_k: int = 20
    # Characters of chunk content returned per retrieved item.
    open_api_content_max_chars: int = 2000
    open_api_log_query_chars: int = 500
    # X-Forwarded-For is only honoured when the direct peer is one of these (IP or CIDR);
    # otherwise an agent could spoof its address past the client's IP allowlist.
    open_api_trusted_proxies: list[str] = []

    # ---- organization directory sync (WeCom / DingTalk / Weaver / Excel) ----
    # Encrypts stored source credentials; changing it makes existing sources unreadable.
    directory_secret_key: str = DEV_DIRECTORY_SECRET
    # An apply that would disable more than this share of a source's active users is aborted
    # (rerun with force after review).
    directory_sync_max_disable_ratio: float = 0.2
    # Below this many disables the ratio guard does not trigger (small orgs).
    directory_sync_guard_min_disables: int = 5
    directory_sync_check_interval_seconds: float = 60.0
    directory_http_timeout_seconds: float = 30.0
    directory_db_timeout_seconds: int = 60
    # Changes kept per category in a sync run record (counts are always complete).
    directory_sync_max_change_details: int = 500

    # ---- QR-code login: OIDC bridge for WeCom / DingTalk (Keycloak identity provider) ----
    # Browser-facing base URL of this platform (nginx), used in OAuth redirect URIs.
    public_base_url: str = "http://localhost:3000"
    oidc_bridge_enabled: bool = True
    # PEM RSA private key for id_token signatures; empty in dev = generated and shared via Redis.
    oidc_bridge_signing_key: str | None = None
    oidc_bridge_client_id: str = "keycloak"
    oidc_bridge_client_secret: str = DEV_OIDC_BRIDGE_SECRET
    oidc_bridge_code_ttl_seconds: int = 60
    oidc_bridge_state_ttl_seconds: int = 600
    oidc_bridge_token_ttl_seconds: int = 300
    # How Keycloak reaches this backend for token / jwks calls (container network).
    oidc_bridge_internal_url: str = "http://backend:8000"
    # Keycloak admin API (confidential client with realm-management manage-users), used to
    # register identity providers and to open password login for synced users.
    keycloak_admin_client_id: str = "ekb-backend"
    keycloak_admin_client_secret: str | None = None

    ready_check_timeout_seconds: float = 3.0

    @model_validator(mode="after")
    def _check_production_secrets(self) -> "Settings":
        if self.app_env != "prod":
            return self
        missing = [
            name
            for name, value, dev in (
                ("DIRECTORY_SECRET_KEY", self.directory_secret_key, DEV_DIRECTORY_SECRET),
                (
                    "OIDC_BRIDGE_CLIENT_SECRET",
                    self.oidc_bridge_client_secret,
                    DEV_OIDC_BRIDGE_SECRET,
                ),
            )
            if not value or value == dev
        ]
        if self.oidc_bridge_enabled and not self.oidc_bridge_signing_key:
            missing.append("OIDC_BRIDGE_SIGNING_KEY")
        if self.open_api_enabled and self.open_api_key_pepper == DEV_OPEN_API_PEPPER:
            missing.append("OPEN_API_KEY_PEPPER")
        if self.metrics_enabled and not self.metrics_token:
            missing.append("METRICS_TOKEN")
        if missing:
            raise ValueError(f"Production requires: {', '.join(missing)}")
        return self

    @property
    def keycloak_issuer_discovery_url(self) -> str:
        return f"{self.keycloak_url}/realms/{self.keycloak_realm}/.well-known/openid-configuration"

    @property
    def keycloak_jwks_url(self) -> str:
        return f"{self.keycloak_url}/realms/{self.keycloak_realm}/protocol/openid-connect/certs"

    @property
    def keycloak_issuer(self) -> str:
        return f"{self.keycloak_public_url}/realms/{self.keycloak_realm}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
