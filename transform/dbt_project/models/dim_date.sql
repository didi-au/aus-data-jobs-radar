select
    row_number() over (order by d) as date_key,
    d as full_date,
    year(d) as year,
    month(d) as month,
    day(d) as day,
    dayname(d) as weekday
from (
    select distinct cast(cast(listedAt as timestamp) as date) as d
    from {{ source('silver', 'job_ads') }}
    where listedAt is not null
)
