-- Run once in Supabase SQL Editor. Existing application data is not overwritten.
-- JSONB preserves all legacy IDs, submission ordering and nested grading feedback.
begin;

create table if not exists public.yt_documents (
    name text primary key,
    payload jsonb not null,
    version bigint not null default 1,
    updated_at timestamptz not null default now()
);

create table if not exists public.yt_assets (
    path text primary key,
    object_key text not null,
    sha256 text not null,
    size_bytes bigint not null,
    content_type text not null,
    updated_at timestamptz not null default now()
);

alter table public.yt_documents enable row level security;
alter table public.yt_assets enable row level security;
revoke all on public.yt_documents, public.yt_assets from anon, authenticated;
grant all on public.yt_documents, public.yt_assets to service_role;

create or replace function public.yt_save_document(
    p_name text, p_payload jsonb, p_expected_version bigint
) returns bigint language plpgsql security invoker set search_path = public as $$
declare next_version bigint;
begin
    if p_expected_version = 0 then
        insert into yt_documents(name, payload) values (p_name, p_payload)
        on conflict do nothing returning version into next_version;
    else
        update yt_documents set payload = p_payload, version = version + 1, updated_at = now()
        where name = p_name and version = p_expected_version
        returning version into next_version;
    end if;
    if next_version is null then
        -- Explicit HTTP conflict avoids PostgREST retrying serialization failures.
        raise sqlstate 'PT409' using message = 'Document changed; reload before saving';
    end if;
    return next_version;
end;
$$;

-- Atomic append avoids losing another student's submission during a long AI call.
create or replace function public.yt_append_document(p_name text, p_item jsonb)
returns bigint language plpgsql security invoker set search_path = public as $$
declare current_payload jsonb; item_index bigint;
begin
    select payload into current_payload from yt_documents where name = p_name for update;
    if current_payload is null or jsonb_typeof(current_payload) <> 'array' then
        raise exception 'Expected an initialized array document';
    end if;
    item_index := jsonb_array_length(current_payload);
    update yt_documents set payload = current_payload || jsonb_build_array(p_item),
        version = version + 1, updated_at = now() where name = p_name;
    return item_index;
end;
$$;

revoke all on function public.yt_save_document(text, jsonb, bigint) from public, anon, authenticated;
revoke all on function public.yt_append_document(text, jsonb) from public, anon, authenticated;
grant execute on function public.yt_save_document(text, jsonb, bigint) to service_role;
grant execute on function public.yt_append_document(text, jsonb) to service_role;

insert into storage.buckets(id, name, public)
values ('yt-private-data', 'yt-private-data', false)
on conflict (id) do nothing;

notify pgrst, 'reload schema';
commit;
