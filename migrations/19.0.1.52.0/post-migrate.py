# -*- coding: utf-8 -*-
"""Nạp phân loại B09 + trạng thái bảng (XML noupdate=1 không refresh DB cũ)."""


def migrate(cr, version):
    from odoo.addons.connecta_vas.models.vas_b09_meta import LINE_META, TABLE_STATUS

    for code, info in LINE_META.items():
        cr.execute(
            """
            UPDATE vas_report_line
               SET b09_fill_kind = %s,
                   b09_gap_reason = %s,
                   basis_kind = %s,
                   basis_note = %s
             WHERE form_code = 'B09-DNN' AND code = %s
            """,
            [
                info['fill_kind'],
                info.get('gap_reason') or None,
                info['basis_kind'],
                info.get('basis_note') or None,
                code,
            ],
        )

    for code, (status, note) in TABLE_STATUS.items():
        cr.execute(
            """
            UPDATE vas_report_line
               SET b09_table_status = %s,
                   b09_table_status_note = %s
             WHERE form_code = 'B09-DNN' AND code = %s
            """,
            [status, note, code],
        )

    cr.execute(
        """
        UPDATE vas_report_line
           SET b09_table_status = NULL,
               b09_table_status_note = NULL
         WHERE form_code = 'B09-DNN'
           AND code <> ALL(%s)
        """,
        [list(TABLE_STATUS.keys())],
    )
