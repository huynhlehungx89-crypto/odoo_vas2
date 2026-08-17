# -*- coding: utf-8 -*-
"""B03-3: gỡ vas_cash_flow_activity khỏi account.move (thông tin chết)."""


def migrate(cr, version):
    cr.execute("""
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'account_move'
           AND column_name = 'vas_cash_flow_activity'
    """)
    if cr.fetchone():
        cr.execute(
            'ALTER TABLE account_move DROP COLUMN IF EXISTS vas_cash_flow_activity'
        )
