# -*- coding: utf-8 -*-
"""W11: aggregate_by_partner + cảnh báo TK cha dùng chung (noupdate seed)."""


def migrate(cr, version):
    # Công nợ — cộng theo đối tác
    cr.execute(
        """
        UPDATE vas_report_line
           SET aggregate_by_partner = TRUE
         WHERE form_code = 'B01a-DNN'
           AND code IN ('131','132','134','182','311','312','313','314','315')
        """
    )
    # TK cha dùng chung — cảnh báo số dư (không gắn chỉ tiêu)
    updates = [
        (
            '124',
            'balance_on_codes',
            '229',
            'TK cha 229 còn SD — không tự gắn nhiều chỉ tiêu dự phòng (124/136/142).',
        ),
        (
            '152',
            'balance_on_codes',
            '214',
            'TK cha 214 còn SD — không tự gắn nhiều chỉ tiêu hao mòn (152/162).',
        ),
        (
            '133',
            'balance_on_codes',
            '136,1361',
            '136/1361 còn SD — chưa gắn TK cha dùng chung; C6 đa đơn vị.',
        ),
        (
            '134',
            'balance_on_codes',
            '138',
            'TK cha 138 còn SD — không tự gắn nhiều chỉ tiêu phải thu khác.',
        ),
        (
            '317',
            'balance_on_codes',
            '336,3361',
            '336/3361 còn SD — chưa gắn TK cha dùng chung; C6 đa đơn vị.',
        ),
    ]
    for code, warn_kind, warn_codes, warn_msg in updates:
        cr.execute(
            """
            UPDATE vas_report_line
               SET warn_kind = %s,
                   warn_account_codes = %s,
                   warn_message = %s
             WHERE form_code = 'B01a-DNN'
               AND code = %s
            """,
            [warn_kind, warn_codes, warn_msg, code],
        )
