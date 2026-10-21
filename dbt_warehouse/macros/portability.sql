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
    CAST('{{ var("run_date", run_started_at.strftime("%Y-%m-%d")) }}' AS DATE) AS _run_date,
    CAST(NULL AS {{ dbt.type_string() }}) AS _source_hash,
    {{ dbt.current_timestamp() }} AS _loaded_at
  {%- else -%}
    {{ p }}_run_date, {{ p }}_source_hash, {{ p }}_loaded_at
  {%- endif -%}
{% endmacro %}


{% macro date_spine_days(start_date, end_date) %}
  {#- One row per calendar day between the two bounds, inclusive. -#}
  {%- if target.type == 'duckdb' -%}
    SELECT UNNEST(generate_series(DATE '{{ start_date }}', DATE '{{ end_date }}', INTERVAL 1 DAY))::DATE AS date_day
  {%- else -%}
    SELECT d AS date_day
    FROM UNNEST(GENERATE_DATE_ARRAY('{{ start_date }}', '{{ end_date }}')) AS d
  {%- endif -%}
{% endmacro %}


{% macro year_month(column) %}
  {#- The 'YYYY-MM' partition label used throughout the project. -#}
  {%- if target.type == 'duckdb' -%}
    STRFTIME({{ column }}, '%Y-%m')
  {%- else -%}
    FORMAT_DATE('%Y-%m', {{ column }})
  {%- endif -%}
{% endmacro %}


{% macro day_of_week(column) %}
  {#- Day index. DuckDB spells the field 'dow'; BigQuery spells it 'dayofweek'. -#}
  {%- if target.type == 'duckdb' -%}
    EXTRACT(DOW FROM {{ column }})
  {%- else -%}
    EXTRACT(DAYOFWEEK FROM {{ column }})
  {%- endif -%}
{% endmacro %}


{% macro safe_divide(numerator, denominator) %}
  {#- Division that yields null rather than raising on a zero denominator.
      Portable in place of BigQuery's safe_divide(). -#}
  ({{ numerator }} / NULLIF({{ denominator }}, 0))
{% endmacro %}
