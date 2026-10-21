-- Scrap rate by reason code with a Pareto (cumulative share) and the month each reason
-- peaked, per line. Scrap rate = scrap value at standard / material issued at standard.
with by_reason as (
    select
        line_id,
        reason_code,
        sum(scrap_value) as scrap_value,
        sum(scrap_events) as events
    from marts.fct_scrap
    group by 1, 2
),

issued as (
    select line_id, sum(issued_value) as issued_value
    from (select distinct line_id, period_id, issued_value from marts.fct_scrap) x
    group by 1
),

peak as (
    select distinct on (line_id, reason_code) line_id, reason_code, period_id as peak_month, scrap_rate as peak_rate
    from marts.fct_scrap
    order by line_id, reason_code, scrap_rate desc
)

select
    b.line_id,
    b.reason_code,
    b.events,
    round(b.scrap_value, 2) as scrap_value,
    round(100 * b.scrap_value / i.issued_value, 3) as scrap_rate_pct,
    round(100 * sum(b.scrap_value) over (partition by b.line_id order by b.scrap_value desc)
          / sum(b.scrap_value) over (partition by b.line_id), 1) as pareto_cum_pct,
    p.peak_month,
    round(100 * p.peak_rate, 3) as peak_month_rate_pct
from by_reason b
join issued i using (line_id)
join peak p using (line_id, reason_code)
order by b.line_id, b.scrap_value desc;
