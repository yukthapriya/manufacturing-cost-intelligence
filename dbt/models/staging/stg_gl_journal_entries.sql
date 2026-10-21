with gl as (
    {{ latest_by(source('raw', 'gl_journal_entries'), ['je_id', 'je_line']) }}
)

select
    je_id,
    je_line,
    je_date,
    period_id,
    plant_id,
    account,
    debit,
    credit,
    debit - credit as net_amount,
    source_type,
    description,
    posted_at,
    _loaded_at
from gl
