begin;
create table public.signups (
 id uuid primary key default gen_random_uuid(),
 name text not null check (char_length(btrim(name)) between 1 and 60),
 contact text not null check (char_length(btrim(contact)) between 5 and 120),
 message text not null default '' check (char_length(message) <= 2000),
 created_at timestamptz not null default now()
);
alter table public.signups enable row level security;
revoke all on public.signups from public, anon, authenticated;
grant insert (name, contact, message) on public.signups to anon, authenticated;
create policy signup_insert_only on public.signups for insert to anon, authenticated with check (true);
commit;
