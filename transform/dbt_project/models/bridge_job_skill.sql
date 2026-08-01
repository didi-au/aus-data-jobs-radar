-- Many-to-many: a job has many skills, a skill appears in many jobs.
-- Regex match on title + description against the seeded skill patterns.
-- \b anchors both ends to a word boundary, so the "sas" pattern matches
-- "SAS" but not "subassembly".
select distinct
    j.id as job_id,
    s.skill_key
from {{ source('silver', 'job_ads') }} j
join {{ ref('dim_skill') }} s
    on regexp_matches(
        lower(coalesce(j.title, '') || ' ' || coalesce(j.description_clean, '')),
        '\b(' || s.pattern || ')\b'
    )
