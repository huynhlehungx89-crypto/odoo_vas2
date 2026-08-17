# -*- coding: utf-8 -*-
"""Chặng 5 — GTGT_8 trỏ [32]/[33] + phụ lục NQ204; thêm declaration_annex_tag."""


def migrate(cr, version):
    cr.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'vas_tax'"
    )
    cols = {r[0] for r in cr.fetchall()}
    if 'declaration_annex_tag' not in cols:
        cr.execute(
            "ALTER TABLE vas_tax ADD COLUMN declaration_annex_tag VARCHAR"
        )
    cr.execute(
        """
        UPDATE vas_tax
           SET declaration_value_tag = '32',
               declaration_tax_tag = '33',
               declaration_annex_tag = 'NQ204'
         WHERE code = 'GTGT_8'
        """
    )
