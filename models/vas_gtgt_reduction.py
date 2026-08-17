# -*- coding: utf-8 -*-
"""Giảm thuế GTGT NQ 204/2025 — danh mục không giảm (dữ liệu) + phụ lục Mẫu 01 PL III."""
from odoo import api, fields, models, _
from odoo.tools import float_compare, float_round


class VasGtgtReductionExclusion(models.Model):
    """HH/DV KHÔNG được giảm — Phụ lục I (VSIC/HS) và II (TTĐB) NĐ 174."""
    _name = 'vas.gtgt.reduction.exclusion'
    _description = 'Danh mục không được giảm thuế GTGT (NQ 204)'
    _order = 'annex, code_kind, code, id'

    sequence = fields.Integer(default=10)
    code = fields.Char(
        string='Mã nhận diện',
        required=True,
        index=True,
        help='Mã Cap VSIC, mã HS, hoặc mã nhóm TTĐB.',
    )
    name = fields.Char(string='Tên nhóm', required=True)
    code_kind = fields.Selection(
        [
            ('vsic', 'Mã ngành / cấp sản phẩm (VSIC Cap)'),
            ('hs', 'Mã HS (khâu nhập khẩu)'),
            ('ttdb', 'Nhóm chịu thuế TTĐB (Phụ lục II)'),
        ],
        string='Cách nhận diện',
        required=True,
        index=True,
    )
    annex = fields.Selection(
        [('I', 'Phụ lục I'), ('II', 'Phụ lục II')],
        string='Phụ lục NĐ 174',
        required=True,
        default='I',
    )
    date_start = fields.Date(string='Hiệu lực từ', required=True, index=True)
    date_end = fields.Date(string='Hiệu lực đến', required=True, index=True)
    active = fields.Boolean(default=True)

    _code_kind_uniq = models.Constraint(
        'unique(code, code_kind)',
        'Mã nhận diện trùng trong cùng loại nhận diện.',
    )

    @api.model
    def _domain_on_date(self, on_date):
        on_date = fields.Date.to_date(on_date)
        return [
            ('active', '=', True),
            ('date_start', '<=', on_date),
            ('date_end', '>=', on_date),
        ]

    @api.model
    def match_product(self, product, on_date):
        """Trả (status, exclusion_or_empty).

        status: 'allowed' | 'excluded' | 'undetermined'
        """
        if product and product._name == 'product.product':
            product = product.product_tmpl_id
        if not product:
            return 'undetermined', self.browse()
        vsic = (product.vas_vsic_code or '').strip()
        hs = (product.vas_hs_code or '').strip()
        ttdb = (product.vas_ttdb_code or '').strip()
        if not vsic and not hs and not ttdb:
            return 'undetermined', self.browse()
        excl = self.search(self._domain_on_date(on_date))
        for row in excl:
            if row.code_kind == 'vsic' and vsic:
                if vsic == row.code or vsic.startswith(row.code):
                    return 'excluded', row
            elif row.code_kind == 'hs' and hs:
                norm_p = hs.replace(' ', '')
                norm_e = row.code.replace(' ', '')
                if norm_p == norm_e or norm_p.startswith(norm_e):
                    return 'excluded', row
            elif row.code_kind == 'ttdb' and ttdb:
                if ttdb == row.code:
                    return 'excluded', row
        return 'allowed', self.browse()


class VasGtgtReductionAnnex(models.Model):
    """Mẫu số 01 — Phụ lục III NĐ 174 (giảm thuế theo NQ 204), kèm tờ khai."""
    _name = 'vas.gtgt.reduction.annex'
    _description = 'Phụ lục giảm thuế GTGT NQ 204'
    _order = 'id desc'

    name = fields.Char(compute='_compute_name', store=True)
    declaration_id = fields.Many2one(
        'vas.gtgt.declaration', required=True, ondelete='cascade', index=True,
    )
    company_id = fields.Many2one(related='declaration_id.company_id', store=True)
    currency_id = fields.Many2one(related='declaration_id.currency_id')
    date_start = fields.Date(related='declaration_id.date_start', store=True)
    date_end = fields.Date(related='declaration_id.date_end', store=True)
    line_ids = fields.One2many(
        'vas.gtgt.reduction.annex.line', 'annex_id', string='Dòng',
    )
    amount_05 = fields.Monetary(string='[05] GT mua vào 8%', currency_field='currency_id')
    amount_06 = fields.Monetary(string='[06] Thuế mua vào KT', currency_field='currency_id')
    amount_07 = fields.Monetary(string='[07] GT bán ra được giảm', currency_field='currency_id')
    amount_08 = fields.Monetary(string='[08] Thuế bán ra sau giảm', currency_field='currency_id')
    amount_09 = fields.Monetary(string='[09]=[08]−[06]', currency_field='currency_id')
    warning_ids = fields.One2many(
        'vas.gtgt.reduction.warning', 'annex_id', string='Cảnh báo',
    )
    has_eligible_sales = fields.Boolean(
        string='Có hàng bán được giảm',
        compute='_compute_has_eligible',
        store=True,
    )

    @api.depends('declaration_id.name')
    def _compute_name(self):
        for rec in self:
            rec.name = _('PL giảm thuế NQ 204 — %s') % (
                rec.declaration_id.name or '',
            )

    @api.depends('amount_07', 'line_ids', 'line_ids.section')
    def _compute_has_eligible(self):
        for rec in self:
            sales = rec.line_ids.filtered(lambda l: l.section == 'sale')
            rec.has_eligible_sales = bool(sales) or float_compare(
                rec.amount_07 or 0.0, 0.0, precision_digits=0,
            ) > 0


class VasGtgtReductionAnnexLine(models.Model):
    _name = 'vas.gtgt.reduction.annex.line'
    _description = 'Dòng phụ lục giảm thuế NQ 204'
    _order = 'section, sequence, id'

    annex_id = fields.Many2one(
        'vas.gtgt.reduction.annex', required=True, ondelete='cascade', index=True,
    )
    sequence = fields.Integer(default=10)
    section = fields.Selection(
        [('purchase', 'I. Mua vào 8%'), ('sale', 'II. Bán ra được giảm')],
        required=True,
    )
    product_name = fields.Char(string='Tên HH/DV')
    amount_untaxed = fields.Monetary(currency_field='currency_id')
    amount_tax = fields.Monetary(currency_field='currency_id')
    rate_before = fields.Float(string='Thuế suất/tỷ lệ trước giảm')
    rate_after = fields.Float(string='Thuế suất/tỷ lệ sau giảm')
    currency_id = fields.Many2one(related='annex_id.currency_id')
    source_move_line_id = fields.Many2one('vas.move.line', ondelete='set null')


class VasGtgtReductionWarning(models.Model):
    _name = 'vas.gtgt.reduction.warning'
    _description = 'Cảnh báo giảm thuế NQ 204'
    _order = 'id'

    annex_id = fields.Many2one(
        'vas.gtgt.reduction.annex', ondelete='cascade', index=True,
    )
    declaration_id = fields.Many2one(
        'vas.gtgt.declaration', ondelete='cascade', index=True,
    )
    company_id = fields.Many2one('res.company', required=True, index=True)
    warning_kind = fields.Selection(
        [
            ('excluded', 'Mặt hàng thuộc danh mục không được giảm'),
            ('out_of_force', 'Ngoài thời hạn hiệu lực'),
            ('undetermined', 'CHƯA XÁC ĐỊNH chiều nhận diện'),
        ],
        required=True,
    )
    product_name = fields.Char(required=True)
    invoice_ref = fields.Char()
    invoice_date = fields.Date()
    message = fields.Text(required=True)
    exclusion_id = fields.Many2one('vas.gtgt.reduction.exclusion', ondelete='set null')
