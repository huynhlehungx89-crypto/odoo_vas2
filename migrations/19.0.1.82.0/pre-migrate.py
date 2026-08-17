# -*- coding: utf-8 -*-
"""Pre: tạo/điền hai cột chỉ tiêu trước khi ORM bắt required trên dòng cũ."""

_TAG_BY_CODE = {
    'GTGT_EXEMPT': ('26', None),
    'GTGT_NON_TAXABLE': ('32a', None),
    'GTGT_0': ('29', None),
    'GTGT_5': ('30', '31'),
    'GTGT_8': ('PL3', 'PL3'),
    'GTGT_10': ('32', '33'),
}


def migrate(cr, version):
    cr.execute(
        """
        SELECT 1 FROM information_schema.tables
         WHERE table_name = 'vas_tax'
        """
    )
    if not cr.fetchone():
        return

    cr.execute(
        """
        SELECT column_name FROM information_schema.columns
         WHERE table_name = 'vas_tax'
        """
    )
    cols = {r[0] for r in cr.fetchall()}

    if 'declaration_value_tag' not in cols:
        cr.execute(
            "ALTER TABLE vas_tax ADD COLUMN declaration_value_tag VARCHAR"
        )
    if 'declaration_tax_tag' not in cols:
        cr.execute(
            "ALTER TABLE vas_tax ADD COLUMN declaration_tax_tag VARCHAR"
        )

    for code, (value_tag, tax_tag) in _TAG_BY_CODE.items():
        cr.execute(
            """
            UPDATE vas_tax
               SET declaration_value_tag = %s,
                   declaration_tax_tag = %s
             WHERE code = %s
            """,
            (value_tag, tax_tag, code),
        )

    # Dòng lạ (nếu có): tránh NULL trên cột required
    cr.execute(
        """
        UPDATE vas_tax
           SET declaration_value_tag = COALESCE(NULLIF(declaration_value_tag, ''), '?')
         WHERE declaration_value_tag IS NULL OR declaration_value_tag = ''
        """
    )
