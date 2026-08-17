# -*- coding: utf-8 -*-
"""B01a: bổ sung TK cha 411 vào chỉ tiêu 411 (seed noupdate không tự cập nhật)."""


def migrate(cr, version):
    cr.execute(
        """
        UPDATE vas_report_line
           SET account_codes = '411,4111'
         WHERE form_code = 'B01a-DNN'
           AND code = '411'
           AND (account_codes IS DISTINCT FROM '411,4111')
        """
    )
