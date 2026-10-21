-- Layer reconciliation: every row read from a source file was either loaded or rejected,
-- and what audit.load_log says was loaded is what is actually in the raw table.
with audit as (
    select source, sum(rows_read) as rows_read, sum(rows_loaded) as rows_loaded, sum(rows_rejected) as rows_rejected
    from audit.load_log group by 1
),

rejects as (
    select source, count(*) as n from {{ source('raw', 'rejects') }} group by 1
),

loaded as (
    select 'material_issues' as source, count(*) as n from {{ source('raw', 'material_issues') }}
    union all select 'labor_entries', count(*) from {{ source('raw', 'labor_entries') }}
    union all select 'invoice_lines', count(*) from {{ source('raw', 'invoice_lines') }}
    union all select 'gl_journal_entries', count(*) from {{ source('raw', 'gl_journal_entries') }}
    union all select 'scrap_records', count(*) from {{ source('raw', 'scrap_records') }}
)

select a.source, a.rows_read, a.rows_loaded, a.rows_rejected, l.n as raw_rows, coalesce(r.n, 0) as reject_rows
from audit a
join loaded l using (source)
left join rejects r using (source)
where a.rows_read <> a.rows_loaded + a.rows_rejected
   or a.rows_loaded <> l.n
   or a.rows_rejected <> coalesce(r.n, 0)
