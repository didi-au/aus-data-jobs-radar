-- Custom data test: a salary range must never be inverted.
-- dbt tests pass when they return zero rows.
select
    job_id,
    salary_min,
    salary_max
from {{ ref('fact_job_posting') }}
where salary_min is not null
  and salary_max is not null
  and salary_min > salary_max
