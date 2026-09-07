/*
  The searchable universe, which is the SEC's own ticker index and nothing more.

  A row here is a lookup key rather than a fact under study, so it carries no
  available_at and no vintage. The file publishes neither, and a list of which
  companies exist is not a measurement of anything about them. Everything that
  is a measurement, the bars and the filings, keeps its own timestamps in the
  tables that already hold them.
*/
create extension if not exists pg_trgm;

create table basis.company (
  ticker       text primary key,
  cik          text not null,
  name         text not null,
  source_id    text not null references basis.source(id),
  collected_at timestamptz not null default now()
);

/*
  Two searches run against this table and they want different indexes. A reader
  who knows the ticker types it from the front, which a B-tree serves only under
  text_pattern_ops, since the database collation is not C. A reader who half
  remembers the name types a fragment from anywhere inside it, which no B-tree
  can serve at all, so the name carries a trigram index instead.
*/
create index company_ticker_prefix on basis.company (ticker text_pattern_ops);
create index company_name_trgm on basis.company using gin (name gin_trgm_ops);
create index company_cik on basis.company (cik);
