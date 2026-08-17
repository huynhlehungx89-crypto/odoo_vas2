# -*- coding: utf-8 -*-
def migrate(cr, version):
    """1A: default tax_status cho dòng sổ cũ / insert SQL thô."""
    cr.execute(
        """
        UPDATE vas_move_line
           SET tax_status = 'none'
         WHERE tax_status IS NULL
        """
    )
    cr.execute(
        """
        ALTER TABLE vas_move_line
            ALTER COLUMN tax_status SET DEFAULT 'none'
        """
    )
