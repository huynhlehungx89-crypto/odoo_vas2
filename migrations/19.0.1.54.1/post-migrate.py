# -*- coding: utf-8 -*-
"""V.8.tax_recv: chỉ lấy SD Nợ 333 (không signed_debit)."""


def migrate(cr, version):
    cr.execute(
        """
        UPDATE vas_report_line
           SET balance_side = 'debit',
               basis_note = 'SD Nợ TK 333 (+ con) — phải thu NSNN'
         WHERE form_code = 'B09-DNN' AND code = 'V.8.tax_recv'
        """
    )
