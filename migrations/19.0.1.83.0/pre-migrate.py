# -*- coding: utf-8 -*-
"""Chặng 2: cột điều kiện khấu trừ trên vas_move_line — DEFAULT trước NOT NULL."""


def migrate(cr, version):
    cr.execute(
        """
        SELECT column_name FROM information_schema.columns
         WHERE table_name = 'vas_move_line'
        """
    )
    cols = {r[0] for r in cr.fetchall()}
    if 'deduction_check' not in cols:
        cr.execute(
            "ALTER TABLE vas_move_line "
            "ADD COLUMN deduction_check VARCHAR DEFAULT 'none'"
        )
    else:
        cr.execute(
            "UPDATE vas_move_line SET deduction_check = 'none' "
            "WHERE deduction_check IS NULL"
        )
    if 'use_purpose' not in cols:
        cr.execute(
            "ALTER TABLE vas_move_line "
            "ADD COLUMN use_purpose VARCHAR DEFAULT 'unset'"
        )
    else:
        cr.execute(
            "UPDATE vas_move_line SET use_purpose = 'unset' "
            "WHERE use_purpose IS NULL"
        )
    if 'deductible_amount' not in cols:
        cr.execute(
            "ALTER TABLE vas_move_line "
            "ADD COLUMN deductible_amount NUMERIC DEFAULT 0"
        )
    for col, default in (
        ('deduction_base_untaxed', '0'),
        ('deduction_base_gross', '0'),
    ):
        if col not in cols:
            cr.execute(
                f"ALTER TABLE vas_move_line ADD COLUMN {col} NUMERIC DEFAULT {default}"
            )
