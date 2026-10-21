{# Project-local generic tests (no package dependency). #}

{% test expression_is_true(model, expression, where=none, column_name=none) %}
select * from {{ model }}
where not ({{ expression }})
{% if where %} and {{ where }}{% endif %}
{% endtest %}


{% test unique_combination(model, columns) %}
select {{ columns | join(', ') }}, count(*) as n
from {{ model }}
group by {{ columns | join(', ') }}
having count(*) > 1
{% endtest %}


{% test non_negative(model, column_name) %}
select * from {{ model }} where {{ column_name }} < 0
{% endtest %}


{# Flags rows matching a known data-quality condition. Used with severity: warn to
   track injected/expected source problems on the DQ dashboard without failing the run. #}
{% test no_rows_where(model, condition) %}
select * from {{ model }} where {{ condition }}
{% endtest %}
