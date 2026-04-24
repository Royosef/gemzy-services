create table if not exists public.push_notification_logs (
  id uuid primary key default gen_random_uuid(),
  notification_id uuid references public.app_notifications(id) on delete set null,
  user_id uuid references public.profiles(id) on delete set null,
  push_token text,
  provider text not null default 'expo',
  status text not null check (status in ('accepted', 'failed')),
  ticket_id text,
  error_code text,
  error_message text,
  payload jsonb,
  ticket jsonb,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create index if not exists push_notification_logs_notification_id_idx
  on public.push_notification_logs (notification_id);

create index if not exists push_notification_logs_user_id_idx
  on public.push_notification_logs (user_id);

create index if not exists push_notification_logs_status_idx
  on public.push_notification_logs (status);

create index if not exists push_notification_logs_ticket_id_idx
  on public.push_notification_logs (ticket_id);
