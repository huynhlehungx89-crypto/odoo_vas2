# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class VasRuleLine(models.Model):
    _name = 'vas.rule.line'
    _description = 'Dòng quy tắc định khoản VAS'
    _order = 'sequence, id'

    rule_id = fields.Many2one(
        'vas.rule',
        string='Quy tắc',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(string='Thứ tự', default=10)
    side = fields.Selection(
        selection=[
            ('debit', 'Nợ'),
            ('credit', 'Có'),
        ],
        string='Bên',
        required=True,
    )
    account_selector = fields.Selection(
        selection=[
            ('fixed', 'Tài khoản cố định'),
            ('partner_receivable', 'Phải thu (131)'),
            ('partner_payable', 'Phải trả (331)'),
            ('product_inventory', 'Tồn kho theo SP/nhóm SP (156/152/153/155)'),
            ('product_revenue', 'Doanh thu theo SP/nhóm SP (5111/5112/5113)'),
            ('product_cogs', 'Giá vốn theo SP/nhóm SP (632)'),
            ('product_expense', 'Chi phí theo SP/nhóm SP (154/6421/6422)'),
            ('bank_cash', 'Tiền mặt/NH (111/112)'),
            ('dest_bank_cash', 'Tiền mặt/NH sổ đích (111/112)'),
            ('cash', 'Tiền mặt (111)'),
            ('bank', 'Tiền gửi NH (112)'),
            ('employee_advance', 'Tạm ứng NLĐ (141)'),
            ('employee_payable', 'Phải trả NLĐ (334)'),
            ('finance_income', 'Doanh thu tài chính (515)'),
            ('finance_expense', 'Chi phí tài chính (635)'),
            ('tax_output', 'Thuế GTGT đầu ra (33311)'),
            ('tax_input', 'Thuế GTGT đầu vào (1331)'),
            ('tax_import_vat_payable', 'Thuế GTGT hàng NK phải nộp (33312)'),
            ('goods_in_transit', 'Hàng mua đang đi đường (151)'),
            ('receipt_counterpart',
             'Đối ứng nhập kho (331 thường / 151 khi treo hàng đi đường)'),
            ('landed_counterpart',
             'Đối ứng landed (331 cước / TK thuế từ vas.landed.tax.map)'),
            ('scrap_expense', 'TK đối ứng hủy hàng (cấu hình công ty)'),
        ],
        string='Cách chọn TK',
        required=True,
    )
    account_id = fields.Many2one(
        'vas.account',
        string='Tài khoản cố định',
        ondelete='restrict',
        domain="[('regime_id', '=', regime_id)]",
    )
    amount_selector = fields.Selection(
        selection=[
            ('untaxed', 'Chưa thuế'),
            ('tax', 'Thuế'),
            ('total', 'Tổng cộng'),
            ('cogs', 'Giá vốn'),
            ('stock_value', 'Giá trị kho (stock.move.value)'),
            ('paid', 'Số tiền thu/chi'),
            ('advance_applied', 'Phần trừ vào tạm ứng (141)'),
            ('advance_excess', 'Phần vượt tạm ứng (334)'),
            ('discount', 'Chiết khấu thanh toán'),
            ('price_adjust', 'Chênh giá tạm tính vs HĐ'),
            ('landed_cost', 'Phần chênh landed cost (additional_landed_cost)'),
            ('forex_diff', 'Chênh lệch tỷ giá đã thực hiện (|settle−book|)'),
        ],
        string='Nguồn số tiền',
        required=True,
    )
    regime_id = fields.Many2one(
        related='rule_id.regime_id',
        store=True,
        readonly=True,
    )

    @api.constrains('account_selector', 'account_id')
    def _check_fixed_account(self):
        for line in self:
            if line.account_selector == 'fixed' and not line.account_id:
                raise ValidationError(
                    'Rule line with account_selector=fixed requires account_id.'
                )
            if line.account_selector != 'fixed' and line.account_id:
                # allow empty; ignore account_id when not fixed
                pass
