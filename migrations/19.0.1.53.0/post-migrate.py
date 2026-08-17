# -*- coding: utf-8 -*-
"""B09: nối machine_now (ledger/text) + cập nhật trạng thái bảng."""


LEDGER = {
    'V.1.cash': ('111', 'debit', None),
    'V.1.bank': ('112', 'debit', None),
    'V.2c.sec': ('2291', 'credit', None),
    'V.2c.other': ('2292', 'credit', None),
    'V.4.transit': ('151', 'debit', None),
    'V.4.material': ('152', 'debit', None),
    'V.4.tool': ('153', 'debit', None),
    'V.4.wip': ('154', 'debit', None),
    'V.4.fg': ('155', 'debit', None),
    'V.4.merch': ('156', 'debit', None),
    'V.4.consign': ('157', 'debit', None),
    'V.9c.accrued': ('335', 'credit', None),
    'VI.6.selling': ('6421', None, 'counterpart'),
    'VI.6.admin': ('6422', None, 'counterpart'),
}

TEXT = {
    'II.1': 'b09_from_text:fiscalyear',
    'II.2': 'b09_from_text:currency',
}


def migrate(cr, version):
    from odoo.addons.connecta_vas.models.vas_b09_meta import LINE_META, TABLE_STATUS

    for code, key in TEXT.items():
        cr.execute(
            """
            UPDATE vas_report_line
               SET code_custom_key = %s,
                   warn_message = NULL
             WHERE form_code = 'B09-DNN' AND code = %s
            """,
            [key, code],
        )

    for code, (acc, side, mode) in LEDGER.items():
        if mode == 'counterpart':
            cr.execute(
                """
                UPDATE vas_report_line
                   SET code_custom_key = 'b09_from_ledger',
                       account_codes = %s,
                       turnover_mode = 'counterpart',
                       source_side = 'credit',
                       counterpart_account_codes = '911',
                       counterpart_side = 'debit',
                       sign_negative = TRUE,
                       show_negative_paren = TRUE,
                       balance_side = NULL,
                       warn_message = NULL
                 WHERE form_code = 'B09-DNN' AND code = %s
                """,
                [acc, code],
            )
        else:
            cr.execute(
                """
                UPDATE vas_report_line
                   SET code_custom_key = 'b09_from_ledger',
                       account_codes = %s,
                       balance_side = %s,
                       turnover_mode = NULL,
                       source_side = NULL,
                       counterpart_account_codes = NULL,
                       counterpart_side = NULL,
                       warn_message = NULL
                 WHERE form_code = 'B09-DNN' AND code = %s
                """,
                [acc, side, code],
            )

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
