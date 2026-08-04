-- Grain: ONE ROW PER JOB POSTING.
-- Foreign keys point at the surrogate keys in each dimension.
--
-- extract.job_attrs is produced by extract/llm_extract.py, which needs an API
-- key. CI has no key, so the table may genuinely not exist. A LEFT JOIN is not
-- enough — the relation must exist to be joined at all — so we check for it at
-- compile time and fall back to nulls. The star schema stays buildable without
-- the LLM layer.
{% set has_attrs = adapter.get_relation(database=target.database, schema='extract', identifier='job_attrs') is not none %}

select
    j.id as job_id,
    c.company_key,
    l.location_key,
    d.date_key,
    j.title,
    j.workArrangements as work_arrangement,
    j.workTypes as work_type,
    j.salary_min,
    j.salary_max,
    j.salary_period,
{% if has_attrs %}
    a.seniority,
    a.visa_friendly,
    a.years_experience_required
{% else %}
    cast(null as varchar) as seniority,
    cast(null as boolean) as visa_friendly,
    cast(null as double) as years_experience_required
{% endif %}
from {{ source('silver', 'job_ads') }} j
left join {{ ref('dim_company') }} c
    on j.company = c.company_name
left join {{ ref('dim_location') }} l
    on j.city = l.city and j.state = l.state
left join {{ ref('dim_date') }} d
    on cast(cast(j.listedAt as timestamp) as date) = d.full_date
{% if has_attrs %}
left join extract.job_attrs a
    on j.id = a.job_id
{% endif %}
