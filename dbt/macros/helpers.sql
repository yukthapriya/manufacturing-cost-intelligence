{# Use the configured schema name as-is (staging, intermediate, marts, recon)
   instead of dbt's default "<target_schema>_<custom>" naming. #}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}{{ target.schema }}{%- else -%}{{ custom_schema_name | trim }}{%- endif -%}
{%- endmacro %}


{# Extended value rounded to cents the way the ERP does it (numeric round is half away
   from zero). Every transaction is valued like this before summing, so subledger
   totals tie to the GL to the cent. #}
{% macro money(qty, price) -%}
    round(({{ qty }})::numeric * ({{ price }})::numeric, 2)
{%- endmacro %}


{# Period-lock routing rule (mirrors common/fiscal_calendar.py::accounting_period).
   A transaction books to its own period unless it was posted after that period's
   close date, in which case the closed period is locked and it books to the period
   of the posting date. `cal` must be stg_fiscal_calendar joined on the transaction
   date's period. #}
{% macro accounting_period(tx_date, posting_date, cal='cal') -%}
    case when {{ posting_date }} <= {{ cal }}.close_date then {{ cal }}.period_id
         else to_char({{ posting_date }}, 'YYYY-MM') end
{%- endmacro %}


{% macro period_of(d) -%}
    to_char({{ d }}, 'YYYY-MM')
{%- endmacro %}


{# Incremental watermark: rows loaded after (newest _max_loaded_at in the target - lookback). #}
{% macro incremental_watermark(column='_max_loaded_at') -%}
    (select coalesce(max({{ column }}), '1900-01-01'::timestamptz) - interval '{{ var("lookback_days") }} days' from {{ this }})
{%- endmacro %}


{# Orders touched by anything loaded after the watermark. Order-grain incremental
   models delete+insert these orders so late labor, new scrap or a completion event
   recomputes the whole order. #}
{% macro changed_orders() -%}
    select order_id from {{ ref('int_material_issues') }} where _max_loaded_at > {{ incremental_watermark() }}
    union
    select order_id from {{ ref('int_labor_entries') }} where _max_loaded_at > {{ incremental_watermark() }}
    union
    select order_id from {{ ref('stg_scrap_records') }} where _loaded_at > {{ incremental_watermark() }}
    union
    select order_id from {{ ref('stg_production_orders') }} where _loaded_at > {{ incremental_watermark() }}
{%- endmacro %}


{% macro aging_bucket(days) -%}
    case when {{ days }} is null then null
         when {{ days }} <= 30 then '0-30'
         when {{ days }} <= 60 then '31-60'
         when {{ days }} <= 90 then '61-90'
         else '90+' end
{%- endmacro %}


{# Latest version of each natural key across reloads of a source. #}
{% macro latest_by(relation, keys, order_by='_loaded_at desc') -%}
    select distinct on ({{ keys | join(', ') }}) *
    from {{ relation }}
    order by {{ keys | join(', ') }}, {{ order_by }}
{%- endmacro %}
