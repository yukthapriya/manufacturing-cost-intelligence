select plant_id, plant_name, city, state from {{ ref('stg_plants') }}
