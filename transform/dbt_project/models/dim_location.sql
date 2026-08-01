select
    row_number() over (order by state, city) as location_key,
    city,
    state
from (
    select distinct city, state
    from {{ source('silver', 'job_ads') }}
    where city is not null
)
