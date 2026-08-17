# -*- coding: utf-8 -*-
"""Dòng vượt / tiết kiệm (cấp A) và phương án xử lý (cấp B)."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare

from .vas_variance import TREATMENT_TYPES


class VasVarianceLine(models.Model):
    _name = 'vas.variance.line'
    _description = 'Dòng vượt định mức / sai hỏng'
    _order = 'id'

    sheet_id = fields.Many2one(
        'vas.variance.sheet', required=True, index=True, ondelete='cascade',
    )
    company_id = fields.Many2one(related='sheet_id.company_id', store=True)
    period_id = fields.Many2one(related='sheet_id.period_id', store=True)
    currency_id = fields.Many2one(related='sheet_id.currency_id')
    line_kind = fields.Selection(
        selection=[
            ('excess', 'Vượt định mức / sai hỏng'),
            ('saving', 'Tiết kiệm (chỉ quản trị)'),
        ],
        string='Loại dòng', required=True, default='excess', index=True,
    )
    suggestion_source = fields.Selection(
        selection=[
            ('bom', 'Tự động từ BOM'),
            ('manual', 'Nhập thủ công'),
        ],
        string='Nguồn gợi ý', required=True, default='manual',
    )
    cost_object_id = fields.Many2one(
        'vas.cost.object', string='Đối tượng tập hợp',
        required=True, ondelete='restrict', index=True,
    )
    cost_item_id = fields.Many2one(
        'vas.cost.item', string='Khoản mục', ondelete='restrict',
    )
    product_id = fields.Many2one('product.product', string='NVL', ondelete='restrict')
    qty_standard = fields.Float(string='Số định mức', digits='Product Unit of Measure', readonly=True)
    qty_actual = fields.Float(string='Số thực tế', digits='Product Unit of Measure', readonly=True)
    qty_variance = fields.Float(
        string='Chênh lượng', digits='Product Unit of Measure',
        compute='_compute_qty_variance', store=True,
    )
    amount_suggested = fields.Monetary(
        string='Số hệ thống gợi ý', currency_field='currency_id', readonly=True,
    )
    amount_confirmed = fields.Monetary(
        string='Số kế toán xác nhận', currency_field='currency_id',
    )
    amount_difference = fields.Monetary(
        string='Chênh lệch', currency_field='currency_id',
        compute='_compute_diff', store=True,
    )
    reason = fields.Text(string='Lý do / điều chỉnh')
    cause = fields.Text(string='Nguyên nhân')
    responsible_name = fields.Char(
        string='Người chịu trách nhiệm (văn bản)',
        help='Ảnh chụp diễn giải — không thay liên kết partner/employee.',
    )
    source_model = fields.Char(string='Model nguồn', index=True, readonly=True)
    source_res_id = fields.Integer(string='ID nguồn', index=True, readonly=True)
    source_label = fields.Char(string='Dấu vết nguồn', readonly=True)
    stock_value_actual = fields.Monetary(
        string='Giá trị xuất thực tế', currency_field='currency_id', readonly=True,
    )
    amount_processed = fields.Monetary(
        string='Số đã xử lý', currency_field='currency_id', default=0.0,
    )
    amount_remaining = fields.Monetary(
        string='Số còn chờ', currency_field='currency_id',
        compute='_compute_remaining', store=True,
    )
    treatment_ids = fields.One2many(
        'vas.variance.treatment', 'line_id', string='Phương án xử lý',
    )

    @api.depends('qty_standard', 'qty_actual')
    def _compute_qty_variance(self):
        for line in self:
            line.qty_variance = line.qty_actual - line.qty_standard

    @api.depends('amount_suggested', 'amount_confirmed')
    def _compute_diff(self):
        for line in self:
            line.amount_difference = line.amount_confirmed - line.amount_suggested

    @api.depends('amount_confirmed', 'amount_processed', 'treatment_ids.amount_remaining')
    def _compute_remaining(self):
        for line in self:
            if line.line_kind == 'saving':
                line.amount_remaining = 0.0
            else:
                pending = line.treatment_ids.filtered(
                    lambda t: t.treatment_type == 'pending',
                )
                line.amount_remaining = sum(pending.mapped('amount_remaining'))

    @api.constrains('line_kind', 'treatment_ids')
    def _check_saving_no_treatment(self):
        for line in self:
            if line.line_kind == 'saving' and line.treatment_ids:
                raise ValidationError(_(
                    'Dòng tiết kiệm không được có phương án xử lý (tầng dữ liệu).',
                ))

    def write(self, vals):
        if 'treatment_ids' in vals:
            for line in self:
                if line.line_kind == 'saving':
                    raise UserError(_(
                        'Dòng tiết kiệm «%s» không nhận phương án.',
                        line.display_name,
                    ))
        return super().write(vals)


class VasVarianceTreatment(models.Model):
    _name = 'vas.variance.treatment'
    _description = 'Phương án xử lý dòng vượt'
    _order = 'id'

    line_id = fields.Many2one(
        'vas.variance.line', required=True, index=True, ondelete='cascade',
    )
    sheet_id = fields.Many2one(related='line_id.sheet_id', store=True)
    company_id = fields.Many2one(related='line_id.company_id', store=True)
    currency_id = fields.Many2one(related='line_id.currency_id')
    treatment_type = fields.Selection(
        selection=TREATMENT_TYPES, string='Loại xử lý', required=True,
    )
    account_id = fields.Many2one(
        'vas.account', string='Tài khoản xử lý', ondelete='restrict',
    )
    account_used_id = fields.Many2one(
        'vas.account', string='TK thực tế đã dùng', ondelete='restrict', copy=False,
        help='Ảnh chụp lúc ghi sổ — không đổi khi cấu hình sau thay đổi.',
    )
    amount = fields.Monetary(string='Số tiền', currency_field='currency_id', required=True)
    percent = fields.Float(string='Tỷ lệ %')
    partner_id = fields.Many2one('res.partner', string='Đối tác', ondelete='restrict')
    employee_id = fields.Many2one('hr.employee', string='Nhân viên', ondelete='restrict')
    responsible_name = fields.Char(string='Tên chịu trách nhiệm (văn bản)')
    name = fields.Char(string='Diễn giải')
    reason = fields.Text(string='Lý do (không thu hồi)')
    amount_processed = fields.Monetary(
        string='Đã xử lý tiếp', currency_field='currency_id', default=0.0, copy=False,
    )
    amount_remaining = fields.Monetary(
        string='Còn chờ', currency_field='currency_id', default=0.0, copy=False,
    )
    followup_sheet_ids = fields.One2many(
        'vas.variance.sheet', 'parent_treatment_id', string='Phiếu tiếp',
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            line = self.env['vas.variance.line'].browse(vals['line_id'])
            if line.line_kind == 'saving':
                raise UserError(_(
                    'Không thêm phương án vào dòng tiết kiệm.',
                ))
        return super().create(vals_list)

    def _assert_partner_employee_reason(self):
        self.ensure_one()
        t = self.treatment_type
        if t == 'claim' and not self.partner_id:
            raise UserError(_(
                'Phải thu bồi thường bắt buộc partner_id («%s»).',
                self.line_id.display_name,
            ))
        if t == 'payroll':
            if not self.employee_id:
                raise UserError(_(
                    'Khấu trừ lương bắt buộc employee_id («%s»).',
                    self.line_id.display_name,
                ))
            emp_company = self.employee_id.company_id
            if emp_company and emp_company != self.company_id:
                raise UserError(_(
                    'Nhân viên «%(e)s» thuộc công ty khác — không khấu trừ lương.',
                    e=self.employee_id.display_name,
                ))
            # Nhân viên khách / ngoài: nếu có partner công ty khác gắn với employee
            # → bắt buộc phải thu. Heuristic: employee không thuộc company phiếu.
            if not emp_company:
                raise UserError(_(
                    'Nhân viên «%s» không thuộc công ty phiếu — dùng phải thu.',
                    self.employee_id.display_name,
                ))
        if t == 'writeoff' and not (self.reason or '').strip():
            raise UserError(_(
                'Không thu hồi được bắt buộc lý do («%s»).',
                self.line_id.display_name,
            ))
        if (self.responsible_name or '').strip():
            if t == 'claim' and not self.partner_id:
                raise UserError(_(
                    'Có tên văn bản nhưng thiếu partner_id — không thay liên kết.',
                ))
            if t == 'payroll' and not self.employee_id:
                raise UserError(_(
                    'Có tên văn bản nhưng thiếu employee_id — không thay liên kết.',
                ))
