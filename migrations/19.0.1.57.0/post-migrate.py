# -*- coding: utf-8 -*-
"""B03-2: chuyển code_custom_key b03_pending → b03_stage2 cho mã đã làm."""


def migrate(cr, version):
    codes = (
        '03', '04', '05', '06', '07', '08',
        '10', '11', '12', '13', '14',
    )
    cr.execute(
        """
        UPDATE vas_report_line
           SET code_custom_key = 'b03_stage2'
         WHERE form_code = 'B03-DNN'
           AND code = ANY(%s)
           AND code_custom_key = 'b03_pending'
        """,
        [list(codes)],
    )
