# -*- coding: utf-8 -*-
from odoo import fields, models


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    vas_is_prepaid = fields.Boolean(
        string='VAS: chi phí trả trước (242)',
        default=False,
        help='Đánh dấu dòng dịch vụ trả trước nhiều kỳ. VAS ghi Nợ 242, '
             'loại khỏi R08, tạo thẻ vas.asset prepaid_service.',
    )
    vas_prepaid_months = fields.Integer(
        string='VAS: số kỳ phân bổ (tháng)',
        help='Khai tay khi hóa đơn không có deferred_start/end của Odoo. '
             'Chỉ dùng khi vas_is_prepaid. Để trống nếu đã có deferred.',
    )
