-- One row per distinct advertiser. Surrogate key via row_number so joins
-- never depend on messy company-name strings.
select
    row_number() over (order by company) as company_key,
    company as company_name
from (
    select distinct company
    from {{ source('silver', 'job_ads') }}
    where company is not null
)
