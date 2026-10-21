{{ latest_by(source('raw', 'purchase_order_lines'), ['po_id', 'po_line']) }}
