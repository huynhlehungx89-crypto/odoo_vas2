# -*- coding: utf-8 -*-
"""Xóa view kế thừa cũ còn trỏ tới field vas_is_employee_advance.

View này phải biến mất TRƯỚC khi nạp lại dữ liệu module, nếu không Odoo
validate arch của form account.payment và báo field không tồn tại.
"""
OBSOLETE_VIEWS = ('view_account_payment_form_vas_advance',)


def migrate(cr, version):
    if not version:
        return
    cr.execute(
        """
        DELETE FROM ir_ui_view
         WHERE id IN (
            SELECT res_id FROM ir_model_data
             WHERE module = 'connecta_vas'
               AND model = 'ir.ui.view'
               AND name IN %s
         )
        """,
        (OBSOLETE_VIEWS,),
    )
    cr.execute(
        """
        DELETE FROM ir_model_data
         WHERE module = 'connecta_vas'
           AND model = 'ir.ui.view'
           AND name IN %s
        """,
        (OBSOLETE_VIEWS,),
    )
