/*
  Two accounts, no roles, no invitations, no password reset by email.

  There is no tenant column anywhere in this schema and there should not be
  one. Both accounts read the same canonical record; what differs between them
  is language and timezone, which is presentation and not authorisation. A
  roles table added later would be the first sign this stopped being a tool for
  two people.
*/

create table if not exists basis.account (
  id            bigserial primary key,
  email         text not null unique,
  display_name  text not null,
  password_hash text not null,
  password_salt text not null,
  language      text not null default 'pt' check (language in ('pt', 'en')),
  timezone      text not null default 'America/Sao_Paulo',
  created_at    timestamptz not null default now(),
  last_seen_at  timestamptz
);
