{{ latest_by(source('raw', 'inventory_snapshots'), ['plant_id', 'material_id', 'snapshot_date']) }}
