# -*- coding: utf-8 -*-
"""Danh mục điều kiện khấu trừ GTGT đầu vào — dữ liệu, không hard-code ngưỡng."""
from odoo import api, fields, models


class VasTaxDeductionRule(models.Model):
    _name = 'vas.tax.deduction.rule'
    _description = 'Điều kiện khấu trừ thuế GTGT đầu vào'
    _order = 'sequence, code'

    code = fields.Char(string='Mã', required=True, index=True)
    name = fields.Char(string='Tên', required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    amount_threshold = fields.Float(
        string='Ngưỡng tiền',
        digits=(16, 0),
        help='Ngưỡng đọc từ NĐ (vd 5.000.000 đã gồm thuế; 1.600.000.000 giá chưa thuế). '
             'Không hard-code trong mã nguồn.',
    )
    threshold_basis = fields.Selection(
        [
            ('gross_incl_vat', 'Giá trị đã gồm thuế GTGT'),
            ('untaxed', 'Giá trị chưa có thuế GTGT'),
        ],
        string='Cơ sở ngưỡng',
        default='gross_incl_vat',
        required=True,
    )
    date_start = fields.Date(string='Hiệu lực từ', required=True)
    date_end = fields.Date(string='Hiệu lực đến')
    consequence = fields.Selection(
        [
            ('deny_all', 'Không khấu trừ toàn bộ'),
            ('deny_excess', 'Khấu trừ hạn chế (phần vượt ngưỡng)'),
            ('wait_due', 'Chờ đến hạn thanh toán'),
        ],
        string='Hậu quả',
        required=True,
    )
    check_kind = fields.Selection(
        [
            ('cash_payment', 'Thanh toán tiền mặt vượt ngưỡng'),
            ('cash_cumulative', 'Cộng dồn cùng NCC cùng ngày'),
            ('deferred_payment', 'Trả chậm / trả góp'),
            ('passenger_car', 'Ô tô chở người ≤ 09 chỗ'),
        ],
        string='Kiểu kiểm máy',
        required=True,
        index=True,
    )
    match_product_code = fields.Char(
        string='Mã SP khớp (ô tô…)',
        help='default_code sản phẩm Odoo — dữ liệu, không hard-code trong máy kiểm.',
    )
    note = fields.Text(string='Ghi chú nguồn')

    _sql_constraints = [
        (
            'vas_tax_deduction_rule_code_uniq',
            'unique(code)',
            'Mã điều kiện khấu trừ phải duy nhất.',
        ),
    ]

    @api.model
    def find_active(self, check_kind, on_date):
        """Trả về rule hiệu lực theo kiểu kiểm + ngày chứng từ."""
        domain = [
            ('check_kind', '=', check_kind),
            ('active', '=', True),
            ('date_start', '<=', on_date),
            '|',
            ('date_end', '=', False),
            ('date_end', '>=', on_date),
        ]
        return self.search(domain, limit=1, order='sequence, id')
