-- Enable RLS for every table owned by the learning module.
-- Intentionally creates no policies: browser roles must not access these tables.

alter table public.learning_sessions enable row level security;
alter table public.learning_messages enable row level security;
alter table public.learning_contexts enable row level security;
alter table public.learning_completion_requests enable row level security;
alter table public.stages enable row level security;
alter table public.concepts enable row level security;
alter table public.user_concept_progress enable row level security;
alter table public.user_stage_progress enable row level security;
alter table public.learning_events enable row level security;
alter table public.quiz_result_receipts enable row level security;
alter table public.quiz_retry_requests enable row level security;
