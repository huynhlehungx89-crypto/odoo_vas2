# -*- coding: utf-8 -*-
"""Danh mục mẫu / phiên bản / chỉ tiêu / đăng ký tờ khai GTGT — dữ liệu thắng mã."""
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class VasGtgtFormType(models.Model):
    _name = 'vas.gtgt.form.type'
    _description = 'Loại tờ khai GTGT'
    _order = 'code'

    code = fields.Char(required=True, index=True)
    name = fields.Char(required=True)
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint(
        'unique(code)',
        'Mã loại tờ khai phải duy nhất.',
    )


class VasGtgtFormVersion(models.Model):
    """Phiên bản mẫu tờ khai — hiệu lực theo ngày là DỮ LIỆU, không chôn trong mã."""
    _name = 'vas.gtgt.form.version'
    _description = 'Phiên bản mẫu tờ khai GTGT'
    _order = 'date_start desc, code'

    code = fields.Char(required=True, index=True)
    name = fields.Char(required=True)
    form_type_id = fields.Many2one(
        'vas.gtgt.form.type', required=True, ondelete='restrict', index=True,
    )
    circular_label = fields.Char(
        string='Văn bản áp dụng',
        required=True,
        help='Hiện trên tờ khai (vd «Thông tư 89/2026/TT-BTC»).',
    )
    date_start = fields.Date(string='Áp dụng từ kỳ có ngày bắt đầu ≥', required=True)
    date_end = fields.Date(string='Áp dụng đến kỳ có ngày bắt đầu ≤')
    active = fields.Boolean(default=True)
    indicator_ids = fields.One2many(
        'vas.gtgt.indicator', 'form_version_id', string='Chỉ tiêu',
    )

    _code_form_uniq = models.Constraint(
        'unique(code, form_type_id)',
        'Mã phiên bản phải duy nhất trong một loại tờ khai.',
    )

    @api.model
    def find_for_period_start(self, form_type, period_start):
        """Máy tự chọn phiên bản theo ngày bắt đầu kỳ tính thuế."""
        period_start = fields.Date.to_date(period_start)
        domain = [
            ('form_type_id', '=', form_type.id),
            ('active', '=', True),
            ('date_start', '<=', period_start),
            '|', ('date_end', '=', False), ('date_end', '>=', period_start),
        ]
        return self.search(domain, order='date_start desc', limit=1)


class VasGtgtActivity(models.Model):
    _name = 'vas.gtgt.activity'
    _description = 'Hoạt động SXKD [01a]'
    _order = 'sequence, code'

    code = fields.Char(required=True, index=True)
    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint(
        'unique(code)',
        'Mã hoạt động phải duy nhất.',
    )


class VasGtgtIndicator(models.Model):
    """Mỗi chỉ tiêu = một bản ghi dữ liệu (công thức / cách lấy số)."""
    _name = 'vas.gtgt.indicator'
    _description = 'Chỉ tiêu tờ khai GTGT'
    _order = 'form_version_id, sequence, code'

    form_version_id = fields.Many2one(
        'vas.gtgt.form.version', required=True, ondelete='cascade', index=True,
    )
    code = fields.Char(string='Số hiệu', required=True, index=True)
    name = fields.Char(required=True)
    sequence = fields.Integer(default=100)
    column_kind = fields.Selection(
        [
            ('value', 'Cột giá trị HHĐV'),
            ('tax', 'Cột thuế GTGT'),
            ('flag', 'Đánh dấu'),
            ('header', 'Phần đầu tờ'),
        ],
        required=True,
        default='tax',
    )
    source_kind = fields.Selection(
        [
            ('ledger_output_value', 'Cộng giá trị bán ra theo tag thuế'),
            ('ledger_output_tax', 'Cộng thuế đầu ra theo tag thuế'),
            ('ledger_input_base', 'Cộng giá trị mua vào (cơ sở 1331)'),
            ('ledger_input_tax', 'Cộng thuế mua vào (Nợ 1331)'),
            ('ledger_input_import_base', 'Cộng giá trị NK'),
            ('ledger_input_import_tax', 'Cộng thuế NK'),
            ('ledger_input_deductible', 'Thuế đầu vào được khấu trừ [25]'),
            ('formula', 'Công thức từ chỉ tiêu khác'),
            ('manual', 'Kế toán nhập tay'),
            ('carry_forward', 'Chuyển từ [43] kỳ trước'),
            ('auto_flag', 'Tự đánh dấu (không PS mua bán)'),
            ('header', 'Thông tin đầu tờ'),
        ],
        string='Cách lấy số',
        required=True,
    )
    ledger_tag = fields.Char(
        string='Tag trên vas.tax',
        help='Khớp declaration_value_tag hoặc declaration_tax_tag.',
    )
    formula = fields.Char(
        string='Công thức',
        help='Vd [29]+[30]+[32]+[32a]-[32b]. Hậu tố ;max0 / ;min0 / ;cap:40a.',
    )
    is_computed = fields.Boolean(
        string='Máy tính',
        compute='_compute_is_computed',
        store=True,
    )

    _version_code_uniq = models.Constraint(
        'unique(form_version_id, code)',
        'Số hiệu chỉ tiêu trùng trong cùng phiên bản mẫu.',
    )

    @api.depends('source_kind')
    def _compute_is_computed(self):
        manualish = {'manual', 'header'}
        for rec in self:
            rec.is_computed = rec.source_kind not in manualish


class VasGtgtRegistration(models.Model):
    """Đăng ký tờ khai sử dụng — kỳ kê khai gắn TỪNG DÒNG."""
    _name = 'vas.gtgt.registration'
    _description = 'Đăng ký tờ khai GTGT'
    _order = 'company_id, form_type_id'

    company_id = fields.Many2one(
        'res.company', required=True, ondelete='cascade', index=True,
        default=lambda self: self.env.company,
    )
    form_type_id = fields.Many2one(
        'vas.gtgt.form.type', required=True, ondelete='restrict', index=True,
    )
    period_kind = fields.Selection(
        [('month', 'Tháng'), ('quarter', 'Quý')],
        string='Kỳ kê khai',
        required=True,
    )
    active = fields.Boolean(default=True)
    date_start = fields.Date(string='Hiệu lực từ')
    date_end = fields.Date(string='Hiệu lực đến')

    _company_form_uniq = models.Constraint(
        'unique(company_id, form_type_id)',
        'Mỗi loại tờ khai chỉ đăng ký một kỳ kê khai (tháng hoặc quý) trên một công ty.',
    )

    @api.depends('form_type_id.code', 'period_kind')
    def _compute_display_name(self):
        kind = dict(self._fields['period_kind'].selection)
        for rec in self:
            rec.display_name = '%s — %s' % (
                rec.form_type_id.code or '',
                kind.get(rec.period_kind, rec.period_kind) or '',
            )

    @api.model
    def find_active(self, company, form_type, on_date=None):
        on_date = fields.Date.to_date(on_date or fields.Date.context_today(self))
        domain = [
            ('company_id', '=', company.id),
            ('form_type_id', '=', form_type.id),
            ('active', '=', True),
            '|', ('date_start', '=', False), ('date_start', '<=', on_date),
            '|', ('date_end', '=', False), ('date_end', '>=', on_date),
        ]
        return self.search(domain, limit=1)
