{{ latest_by(source('raw', 'standard_costs'), ['item_type', 'item_id', 'cost_component', 'effective_from']) }}
