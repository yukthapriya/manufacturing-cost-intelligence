{# Minimal stand-in for dbt_utils.generate_surrogate_key so the project has no package dependency. #}
{% macro dbt_utils_surrogate(cols) -%}
    md5({% for c in cols %}coalesce({{ c }}::text, '_null_'){% if not loop.last %} || '|' || {% endif %}{% endfor %})
{%- endmacro %}
