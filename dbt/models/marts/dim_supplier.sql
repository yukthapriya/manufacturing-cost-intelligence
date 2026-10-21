select supplier_id, supplier_name, payment_terms_days, country from {{ ref('stg_suppliers') }}
