# -*- coding: utf-8 -*-
"""B03-3: chuyển code_custom_key b03_pending → b03_stage3 cho mã luồng tiền."""


def migrate(cr, version):
    codes = (
        '15', '16', '17', '18',
        '21', '22', '23', '24', '25',
        '31', '32', '33', '34', '35',
        '61',
    )
    cr.execute(
        """
        UPDATE vas_report_line
           SET code_custom_key = 'b03_stage3'
         WHERE form_code = 'B03-DNN'
           AND code = ANY(%s)
           AND code_custom_key = 'b03_pending'
        """,
        [list(codes)],
    )
