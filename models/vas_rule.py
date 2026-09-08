# -*- coding: utf-8 -*-
from odoo import fields, models


class VasRule(models.Model):
    _name = 'vas.rule'
    _description = 'Quy tắc định khoản VAS'
    _order = 'sequence, code, id'

    code = fields.Char(string='Mã', required=True, index=True)
    name = fields.Char(string='Tên', required=True)
    regime_id = fields.Many2one(
        'vas.regime',
        string='Chế độ kế toán',
        required=True,
        index=True,
        ondelete='restrict',
    )
    event_type = fields.Selection(
        selection=[
            ('sale_invoice', 'Hóa đơn bán'),
            ('sale_delivery', 'Xuất kho bán'),
            ('payment_in', 'Thu tiền'),
            ('purchase_receipt', 'Nhập kho mua'),
            ('purchase_invoice', 'Hóa đơn mua'),
            ('payment_out', 'Chi tiền'),
            ('advance_employee', 'Tạm ứng NLĐ'),
            ('advance_settlement', 'Quyết toán tạm ứng (chi phí)'),
            ('advance_refund', 'Hoàn tạm ứng (thu tiền thừa)'),
            ('employee_debt_payment', 'Trả nợ người lao động'),
            ('cash_transfer', 'Nộp/rút quỹ'),
            ('deposit', 'Ký quỹ, ký cược'),
            ('payment_discount', 'Chiết khấu thanh toán'),
            ('sale_refund', 'Hóa đơn trả lại bán'),
            ('sale_return_stock', 'Nhập kho hàng bán trả'),
            ('sale_discount', 'Chiết khấu/giảm giá bán'),
            ('purchase_service', 'Mua dịch vụ'),
            ('purchase_refund', 'Hóa đơn trả lại mua'),
            ('purchase_discount', 'Chiết khấu/giảm giá mua (phi kho)'),
            ('purchase_return_stock', 'Xuất kho trả NCC'),
            ('purchase_price_adjust', 'Điều chỉnh giá tạm tính mua'),
            ('stock_issue_production', 'Xuất NVL cho sản xuất'),
            ('landed_cost_adjust', 'Vốn hóa cước landed cost'),
            ('purchase_landed_tax', 'Thuế GTGT hóa đơn cước'),
            ('import_vat_payment', 'Nộp GTGT hàng nhập khẩu'),
            ('goods_in_transit', 'Hàng mua đang đi đường (151)'),
            ('forex_realized', 'Chênh lệch tỷ giá đã thực hiện'),
            # W9 — lương (adapter hand-built; rule = metadata / UI)
            ('payroll_accrue', 'Trích lương (R38)'),
            ('payroll_deduct', 'Khấu trừ lương (R39)'),
            ('payroll_employer', 'BH DN (R40)'),
            ('payroll_pay', 'Trả lương (R41)'),
            ('payroll_remit', 'Nộp BH/TNCN (R42)'),
            ('pos_sale', 'Bán tại quầy (R43)'),
            ('pos_cogs', 'Giá vốn quầy (R44)'),
            ('pos_refund', 'Trả hàng tại quầy (R45)'),
            ('pos_session_cash', 'Kết ca tiền mặt quầy (R46)'),
            ('pos_session_bank', 'Kết ca thẻ/ví quầy (R47)'),
            ('pos_cash_shortage', 'Đếm thiếu két quầy (R48)'),
            ('pos_cash_overage', 'Đếm thừa két quầy (R49)'),
            ('stock_scrap', 'Hủy hàng (scrap)'),
        ],
        string='Sự kiện',
        required=True,
        index=True,
    )
    condition = fields.Char(
        string='Điều kiện (domain)',
        help='Domain Odoo tùy chọn, ví dụ [("move_type","=","out_invoice")]. Để trống = mọi bản ghi sự kiện.',
    )
    sequence = fields.Integer(string='Thứ tự', default=10)
    active = fields.Boolean(default=True)
    line_ids = fields.One2many('vas.rule.line', 'rule_id', string='Dòng quy tắc', copy=True)

    _sql_constraints = [
        (
            'vas_rule_regime_code_uniq',
            'unique(regime_id, code)',
            'Rule code must be unique per regime.',
        ),
    ]
