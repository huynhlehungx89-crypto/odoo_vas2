# -*- coding: utf-8 -*-
"""DB DEFAULT cho direct_industry_status — raw SQL insert (benchmark) không qua ORM."""


def migrate(cr, version):
    cr.execute(
        """
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'vas_move_line'
           AND column_name = 'direct_industry_status'
        """
    )
    if not cr.fetchone():
        return
    cr.execute(
        """
        UPDATE vas_move_line
           SET direct_industry_status = 'none'
         WHERE direct_industry_status IS NULL
        """
    )
    cr.execute(
        """
        ALTER TABLE vas_move_line
         ALTER COLUMN direct_industry_status SET DEFAULT 'none'
        """
    )
