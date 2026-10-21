{#
  Cross-dialect helpers.

  The warehouse targets BigQuery in production and DuckDB locally, so that the
  models can be built and their tests actually executed without cloud
  credentials. Everything that differs between the two dialects is isolated
  here rather than branched inside the models, so a model reads as SQL and not
  as a pile of conditionals.
#}


{% macro provenance_columns(alias='') %}
  {#-
    Lineage columns carried through the staging layer.

    On BigQuery these are real columns: scripts/load_to_bigquery.py stamps
    every loaded table with the run date, the source file's SHA-256 and the
    load timestamp.

    The local DuckDB target reads the pipeline's processed Parquet directly,
    which deliberately does *not* carry them -- the processed layer must stay
    byte-reproducible, and a load timestamp would change on every run. They are
    synthesised here instead so the staging contract holds in both targets.
  -#}
  {%- set p = (alias ~ '.') if alias else '' -%}
  {%- if target.type == 'duckdb' -%}
    cast('{{ var("run_date", run_started_at.strftime("%Y-%m-%d")) }}' as date) as _run_date,
    cast(null as {{ dbt.type_string() }}) as _source_hash,
    {{ dbt.current_timestamp() }} as _loaded_at
  {%- else -%}
    {{ p }}_run_date, {{ p }}_source_hash, {{ p }}_loaded_at
  {%- endif -%}
{% endmacro %}


{% macro date_spine_days(start_date, end_date) %}
  {#- One row per calendar day between the two bounds, inclusive. -#}
  {%- if target.type == 'duckdb' -%}
    select unnest(generate_series(date '{{ start_date }}', date '{{ end_date }}', interval 1 day))::date as date_day
  {%- else -%}
    select d as date_day
    from unnest(generate_date_array('{{ start_date }}', '{{ end_date }}')) as d
  {%- endif -%}
{% endmacro %}


{% macro year_month(column) %}
  {#- The 'YYYY-MM' partition label used throughout the project. -#}
  {%- if target.type == 'duckdb' -%}
    strftime({{ column }}, '%Y-%m')
  {%- else -%}
    format_date('%Y-%m', {{ column }})
  {%- endif -%}
{% endmacro %}


{% macro day_of_week(column) %}
  {#- Day index. DuckDB spells the field 'dow'; BigQuery spells it 'dayofweek'. -#}
  {%- if target.type == 'duckdb' -%}
    extract(dow from {{ column }})
  {%- else -%}
    extract(dayofweek from {{ column }})
  {%- endif -%}
{% endmacro %}


{% macro safe_divide(numerator, denominator) %}
  {#- Division that yields null rather than raising on a zero denominator.
      Portable in place of BigQuery's safe_divide(). -#}
  ({{ numerator }} / nullif({{ denominator }}, 0))
{% endmacro %}
