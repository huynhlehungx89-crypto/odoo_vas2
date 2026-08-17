# -*- coding: utf-8 -*-
"""Gỡ view kế thừa trỏ vào 3 trường sắp bị xóa.

Bảng ánh xạ chuyển sang model `vas.account.map`, nên
`vas_stock_account_id` / `vas_revenue_account_id` / `vas_cogs_account_id` biến khỏi
`product.category` và `product.template`. Hai view kế thừa cũ vẫn nằm trong DB và
Odoo kiểm tra view trước khi tới post-migrate → phải xóa ở đây, nếu không nâng cấp
sẽ chết với "Field ... does not exist".
"""
import logging

_logger = logging.getLogger(__name__)

OBSOLETE_VIEWS = (
    'view_product_category_form_vas',
    'view_product_template_form_vas',
)


def migrate(cr, version):
    if not version:
        return
    cr.execute(
        """
        SELECT res_id FROM ir_model_data
         WHERE module = 'connecta_vas'
           AND model = 'ir.ui.view'
           AND name IN %s
        """,
        (OBSOLETE_VIEWS,),
    )
    view_ids = [row[0] for row in cr.fetchall()]
    if not view_ids:
        return
    cr.execute("DELETE FROM ir_ui_view WHERE id IN %s", (tuple(view_ids),))
    cr.execute(
        """
        DELETE FROM ir_model_data
         WHERE module = 'connecta_vas'
           AND model = 'ir.ui.view'
           AND name IN %s
        """,
        (OBSOLETE_VIEWS,),
    )
    _logger.info('connecta_vas: go %s view ke thua cua 3 truong TK cu', len(view_ids))
