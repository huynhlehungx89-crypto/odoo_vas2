# -*- coding: utf-8 -*-
"""1A-2: chỉ tiêu 01/GTGT = hai ô (giá trị / tiền thuế); sửa số hiệu sai 23/25/…"""

# Khớp seed + ca khóa — không suy từ declaration_tag cũ (dãy sai).
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
        SELECT column_name FROM information_schema.columns
         WHERE table_name = 'vas_tax'
           AND column_name IN (
               'declaration_tag',
               'declaration_value_tag',
               'declaration_tax_tag'
           )
        """
    )
    cols = {r[0] for r in cr.fetchall()}
    if 'declaration_value_tag' not in cols:
        return

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

    if 'declaration_tag' in cols:
        cr.execute('ALTER TABLE vas_tax DROP COLUMN IF EXISTS declaration_tag')
