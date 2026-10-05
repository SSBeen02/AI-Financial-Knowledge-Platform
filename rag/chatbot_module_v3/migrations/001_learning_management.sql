-- PostgreSQL/Supabase migration for learning and stage management.
-- Apply this migration with the same owner used by CHAT_DB_URL.

create table if not exists learning_sessions (
    session_id text primary key,
    user_id text not null,
    stage text not null,
    concept_id text not null,
    term text not null,
    attempt integer not null,
    start_type text not null check (start_type in ('keyword', 'detected', 'relearn', 'quiz_retry')),
    status text not null check (status in ('active', 'completed')),
    created_at timestamptz not null,
    completed_at timestamptz null
);
create index if not exists ix_learning_sessions_user_id on learning_sessions(user_id);
create unique index if not exists uq_learning_sessions_one_active
    on learning_sessions(user_id) where status = 'active';

create table if not exists learning_messages (
    message_id text primary key,
    session_id text null references learning_sessions(session_id),
    user_id text not null,
    role text not null check (role in ('user', 'assistant')),
    content text not null,
    is_related boolean null,
    band text null,
    top_score double precision null,
    sources jsonb null,
    display_sources jsonb null,
    latency_ms integer null,
    created_at timestamptz not null
);
create index if not exists ix_learning_messages_user_id on learning_messages(user_id);
create index if not exists ix_learning_messages_session_id on learning_messages(session_id);

create table if not exists learning_contexts (
    session_id text primary key references learning_sessions(session_id),
    user_id text not null,
    concept_id text not null,
    quiz_status text not null check (quiz_status in ('pending', 'passed', 'failed', 'generation_failed')),
    payload jsonb not null,
    created_at timestamptz not null
);
create index if not exists ix_learning_contexts_user_id on learning_contexts(user_id);

create table if not exists learning_completion_requests (
    request_id text primary key,
    user_id text not null,
    session_id text not null references learning_sessions(session_id),
    idempotency_key text not null,
    payload jsonb not null,
    created_at timestamptz not null,
    constraint uq_learning_completion_user_key unique (user_id, idempotency_key)
);

create table if not exists stages (
    stage_id text primary key,
    name_ko text not null,
    display_order integer not null unique,
    is_optional boolean not null default false
);

create table if not exists concepts (
    concept_id text not null,
    stage_id text not null references stages(stage_id),
    term text not null,
    display_order integer not null,
    primary key (concept_id, stage_id),
    constraint uq_concepts_stage_order unique (stage_id, display_order)
);
create index if not exists ix_concepts_stage_order
    on concepts(stage_id, display_order);

create table if not exists user_concept_progress (
    user_id text not null,
    concept_id text not null,
    stage_id text not null,
    status text not null check (status in ('not_started', 'in_progress', 'passed')),
    started_at timestamptz null,
    first_passed_at timestamptz null,
    updated_at timestamptz not null,
    primary key (user_id, concept_id, stage_id),
    foreign key (concept_id, stage_id) references concepts(concept_id, stage_id)
);
create index if not exists ix_user_concept_progress_user_stage
    on user_concept_progress(user_id, stage_id);
create unique index if not exists uq_user_concept_progress_one_in_progress
    on user_concept_progress(user_id) where status = 'in_progress';

create table if not exists user_stage_progress (
    user_id text not null,
    stage_id text not null references stages(stage_id),
    status text not null check (status in ('in_progress', 'completed')),
    started_at timestamptz not null,
    completed_at timestamptz null,
    primary key (user_id, stage_id)
);
create index if not exists ix_user_stage_progress_user
    on user_stage_progress(user_id);

create table if not exists learning_events (
    event_id text primary key,
    event_type text not null check (event_type in ('concept_passed', 'stage_completed')),
    user_id text not null,
    payload jsonb not null,
    occurred_at timestamptz not null,
    processed_at timestamptz null
);
create index if not exists ix_learning_events_user_id on learning_events(user_id);
create index if not exists ix_learning_events_unprocessed
    on learning_events(processed_at, occurred_at);

-- Internal learning-management tables. Other modules must use service functions.
create table if not exists quiz_result_receipts (
    submission_id text primary key,
    user_id text not null,
    session_id text not null,
    concept_id text not null,
    stage_id text not null,
    result_payload jsonb not null,
    created_at timestamptz not null
);
create index if not exists ix_quiz_result_receipts_user_id
    on quiz_result_receipts(user_id);
create index if not exists ix_quiz_result_receipts_session_id
    on quiz_result_receipts(session_id);

create table if not exists quiz_retry_requests (
    request_id text primary key,
    user_id text not null,
    original_session_id text not null,
    retry_session_id text not null,
    idempotency_key text not null,
    response_payload jsonb not null,
    created_at timestamptz not null,
    constraint uq_quiz_retry_user_key unique (user_id, idempotency_key)
);
create index if not exists ix_quiz_retry_requests_user_id
    on quiz_retry_requests(user_id);
create index if not exists ix_quiz_retry_requests_original_session_id
    on quiz_retry_requests(original_session_id);
create index if not exists ix_quiz_retry_requests_retry_session_id
    on quiz_retry_requests(retry_session_id);

-- Browser-facing Supabase roles must not read these tables directly.
alter table stages enable row level security;
alter table concepts enable row level security;
alter table user_concept_progress enable row level security;
alter table user_stage_progress enable row level security;
alter table learning_events enable row level security;
alter table quiz_result_receipts enable row level security;
alter table quiz_retry_requests enable row level security;
alter table learning_sessions enable row level security;
alter table learning_messages enable row level security;
alter table learning_contexts enable row level security;
alter table learning_completion_requests enable row level security;

