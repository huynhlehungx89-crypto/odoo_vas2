# -*- coding: utf-8 -*-
"""Đổi mã/xmlid TRƯỚC khi nạp XML — tránh tạo bản ghi trùng V.3đ cạnh V.3e cũ.

Không import connecta_vas.models (pre-migrate chạy trước khi nạp model mới).
"""

CODE_RENAMES = {
    'V.3e': 'V.3đ',
    'V.3e.total': 'V.3đ.total',
    'V.14e': 'V.14đ',
}
XMLID_RENAMES = {
    'vas_report_line_b09_V_3e': 'vas_report_line_b09_V_3đ',
    'vas_report_line_b09_V_3e_total': 'vas_report_line_b09_V_3đ_total',
    'vas_report_line_b09_V_14e': 'vas_report_line_b09_V_14đ',
}


def migrate(cr, version):
    for old, new in CODE_RENAMES.items():
        cr.execute(
            """
            SELECT id FROM vas_report_line
             WHERE form_code = 'B09-DNN' AND code = %s
            """,
            [new],
        )
        new_ids = [r[0] for r in cr.fetchall()]
        cr.execute(
            """
            SELECT id FROM vas_report_line
             WHERE form_code = 'B09-DNN' AND code = %s
            """,
            [old],
        )
        old_ids = [r[0] for r in cr.fetchall()]
        if old_ids and new_ids:
            cr.execute(
                """
                UPDATE vas_report_snapshot_line sl
                   SET report_line_id = %s, code = %s
                  FROM vas_report_snapshot s
                 WHERE sl.snapshot_id = s.id
                   AND s.form_code = 'B09-DNN'
                   AND sl.code = %s
                """,
                [new_ids[0], new, old],
            )
            cr.execute(
                'DELETE FROM vas_report_line WHERE id = ANY(%s)',
                [old_ids],
            )
        elif old_ids:
            cr.execute(
                """
                UPDATE vas_report_line
                   SET code = %s
                 WHERE id = ANY(%s)
                """,
                [new, old_ids],
            )
            cr.execute(
                """
                UPDATE vas_report_snapshot_line sl
                   SET code = %s
                  FROM vas_report_snapshot s
                 WHERE sl.snapshot_id = s.id
                   AND s.form_code = 'B09-DNN'
                   AND sl.code = %s
                """,
                [new, old],
            )

        cr.execute(
            """
            UPDATE vas_report_line
               SET warn_message = replace(coalesce(warn_message, ''), %s, %s),
                   basis_note = replace(coalesce(basis_note, ''), %s, %s)
             WHERE form_code = 'B09-DNN'
               AND (
                   coalesce(warn_message, '') LIKE %s
                   OR coalesce(basis_note, '') LIKE %s
               )
            """,
            [old, new, old, new, '%' + old + '%', '%' + old + '%'],
        )

    for old_xml, new_xml in XMLID_RENAMES.items():
        cr.execute(
            """
            SELECT id FROM ir_model_data
             WHERE module = 'connecta_vas' AND name = %s
            """,
            [new_xml],
        )
        if cr.fetchone():
            cr.execute(
                """
                DELETE FROM ir_model_data
                 WHERE module = 'connecta_vas'
                   AND model = 'vas.report.line'
                   AND name = %s
                """,
                [old_xml],
            )
        else:
            cr.execute(
                """
                UPDATE ir_model_data
                   SET name = %s
                 WHERE module = 'connecta_vas'
                   AND model = 'vas.report.line'
                   AND name = %s
                """,
                [new_xml, old_xml],
            )
