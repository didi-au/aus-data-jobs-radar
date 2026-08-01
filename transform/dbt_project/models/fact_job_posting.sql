-- Grain: ONE ROW PER JOB POSTING.
-- Foreign keys point at the surrogate keys in each dimension.
-- LLM-extracted attributes (seniority, visa) are left-joined so the fact
-- still builds if extraction has not been run yet.
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
    a.seniority,
    a.visa_friendly,
    a.years_experience_required
from {{ source('silver', 'job_ads') }} j
left join {{ ref('dim_company') }} c
    on j.company = c.company_name
left join {{ ref('dim_location') }} l
    on j.city = l.city and j.state = l.state
left join {{ ref('dim_date') }} d
    on cast(cast(j.listedAt as timestamp) as date) = d.full_date
left join extract.job_attrs a
    on j.id = a.job_id
