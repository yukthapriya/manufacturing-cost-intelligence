{{ latest_by(source('raw', 'opening_inventory'), ['plant_id', 'material_id']) }}
