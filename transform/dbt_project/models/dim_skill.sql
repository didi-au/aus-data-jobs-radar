-- Skill vocabulary is seeded (transform/dbt_project/seeds/skills.csv) rather
-- than inferred, so the keyword pass and the LLM pass share one canonical list.
select
    skill_key,
    skill_name,
    pattern
from {{ ref('skills') }}
