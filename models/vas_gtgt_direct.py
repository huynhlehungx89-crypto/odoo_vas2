# -*- coding: utf-8 -*-
"""Chặng 7 — phương pháp trực tiếp: nhóm ngành · PP tính thuế · tờ 03/04."""
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero, float_round


class VasGtgtDirectIndustry(models.Model):
    """Bốn nhóm ngành mẫu 04/GTGT — tỷ lệ là DỮ LIỆU, không chôn trong mã."""
    _name = 'vas.gtgt.direct.industry'
    _description = 'Nhóm ngành GTGT trực tiếp trên doanh thu'
    _order = 'sequence, code'

    code = fields.Char(required=True, index=True)
    name = fields.Char(required=True)
    rate_percent = fields.Float(
        string='Tỷ lệ %',
        required=True,
        digits=(16, 4),
        help='Tỷ lệ % trên doanh thu — đọc từ TT 89 mẫu 04, sửa được bằng dữ liệu.',
    )
    sequence = fields.Integer(default=10)
    date_start = fields.Date(required=True, default='2026-07-01')
    date_end = fields.Date()
    active = fields.Boolean(default=True)
    declaration_revenue_tag = fields.Char(
        string='Tag doanh thu trên tờ 04',
        help='Vd 22, 24, 26, 28 — khớp ledger_tag chỉ tiêu.',
    )
    is_gold = fields.Boolean(
        string='Vàng bạc đá quý (mẫu 03)',
        default=False,
        help='Tách khỏi bốn nhóm mẫu 04 — dùng cho tờ 03/GTGT.',
    )

    _code_uniq = models.Constraint(
        'unique(code)',
        'Mã nhóm ngành phải duy nhất.',
    )

    @api.model
    def find_active(self, code, on_date):
        on_date = fields.Date.to_date(on_date)
        return self.search([
            ('code', '=', code),
            ('active', '=', True),
            ('date_start', '<=', on_date),
            '|', ('date_end', '=', False), ('date_end', '>=', on_date),
        ], limit=1)

    @api.model
    def rate_for(self, code, on_date):
        rec = self.find_active(code, on_date)
        return rec.rate_percent if rec else 0.0


class VasGtgtTaxMethod(models.Model):
    """Lịch sử phương pháp tính thuế GTGT của công ty — theo ngày hiệu lực."""
    _name = 'vas.gtgt.tax.method'
    _description = 'Phương pháp tính thuế GTGT (công ty)'
    _order = 'date_start desc, id desc'

    company_id = fields.Many2one(
        'res.company', required=True, ondelete='cascade', index=True,
        default=lambda self: self.env.company,
    )
    method = fields.Selection(
        [
            ('deduction', 'Khấu trừ'),
            ('direct', 'Trực tiếp'),
        ],
        required=True,
        default='deduction',
        index=True,
    )
    date_start = fields.Date(required=True, index=True)
    date_end = fields.Date(index=True)
    note = fields.Char()

    @api.model
    def method_on(self, company, on_date):
        on_date = fields.Date.to_date(on_date)
        rec = self.search([
            ('company_id', '=', company.id),
            ('date_start', '<=', on_date),
            '|', ('date_end', '=', False), ('date_end', '>=', on_date),
        ], order='date_start desc', limit=1)
        return rec.method if rec else 'deduction'

    @api.constrains('date_start', 'date_end', 'company_id')
    def _check_dates(self):
        for rec in self:
            if rec.date_end and rec.date_end < rec.date_start:
                raise ValidationError(_('Ngày kết thúc phải ≥ ngày bắt đầu.'))


class VasGtgtDeclarationDirect(models.Model):
    _inherit = 'vas.gtgt.declaration'

    amount_neg_carry = fields.Monetary(
        string='GTGT âm chuyển kỳ sau (03)',
        currency_field='currency_id',
        help='max(0, −[26]) — nguồn [21] kỳ sau.',
        readonly=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        Method = self.env['vas.gtgt.tax.method']
        Form = self.env['vas.gtgt.form.type']
        for vals in vals_list:
            form = Form.browse(vals.get('form_type_id')) if vals.get('form_type_id') else Form
            company = self.env['res.company'].browse(
                vals.get('company_id') or self.env.company.id,
            )
            start = fields.Date.to_date(vals.get('date_start'))
            if form and form.exists() and start:
                method = Method.method_on(company, start)
                if form.tax_method != method:
                    raise UserError(_(
                        'Kỳ bắt đầu %s: công ty theo phương pháp «%s» — '
                        'không lập tờ «%s».',
                        start,
                        dict(Method._fields['method'].selection).get(method),
                        form.code,
                    ))
        return super().create(vals_list)

    def _sum_direct_industry_revenue(self, industry_code):
        self.ensure_one()
        lines = self.env['vas.move.line'].search([
            ('move_id.company_id', '=', self.company_id.id),
            ('move_id.state', '=', 'posted'),
            ('date', '>=', self.date_start),
            ('date', '<=', self.date_end),
            ('credit', '>', 0),
            ('account_id.code', '=like', '511%'),
            ('direct_industry_id.code', '=', industry_code),
            ('direct_industry_status', '=', 'resolved'),
        ])
        return sum(lines.mapped('credit'))

    def _direct_industry_tax(self, industry_code):
        self.ensure_one()
        revenue = self._sum_direct_industry_revenue(industry_code)
        rate = self.env['vas.gtgt.direct.industry'].rate_for(
            industry_code, self.date_start,
        )
        return float_round(revenue * rate / 100.0, precision_digits=0)

    def _count_undetermined_direct_products(self):
        """SP bán trong kỳ chưa khai nhóm ngành."""
        self.ensure_one()
        Move = self.env['account.move']
        invoices = Move.search([
            ('company_id', '=', self.company_id.id),
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('date', '>=', self.date_start),
            ('date', '<=', self.date_end),
        ])
        products = self.env['product.product']
        for inv in invoices:
            for line in inv.invoice_line_ids:
                if line.display_type in ('line_section', 'line_note'):
                    continue
                if line.product_id and not line.product_id.vas_gtgt_direct_industry_id:
                    products |= line.product_id
        # Cũng đếm dòng sổ undetermined
        undet_lines = self.env['vas.move.line'].search_count([
            ('move_id.company_id', '=', self.company_id.id),
            ('move_id.state', '=', 'posted'),
            ('date', '>=', self.date_start),
            ('date', '<=', self.date_end),
            ('credit', '>', 0),
            ('account_id.code', '=like', '511%'),
            ('direct_industry_status', '=', 'undetermined'),
        ])
        return products, undet_lines

    def _sum_gold_revenue(self):
        self.ensure_one()
        lines = self.env['vas.move.line'].search([
            ('move_id.company_id', '=', self.company_id.id),
            ('move_id.state', '=', 'posted'),
            ('date', '>=', self.date_start),
            ('date', '<=', self.date_end),
            ('credit', '>', 0),
            ('account_id.code', '=like', '511%'),
            ('direct_industry_id.is_gold', '=', True),
        ])
        return sum(lines.mapped('credit'))

    def _sum_gold_cost(self):
        """Giá thanh toán mua vào / giá vốn vàng bạc — Nợ 632 hoặc 156 xuất kho gắn ngành vàng."""
        self.ensure_one()
        lines = self.env['vas.move.line'].search([
            ('move_id.company_id', '=', self.company_id.id),
            ('move_id.state', '=', 'posted'),
            ('date', '>=', self.date_start),
            ('date', '<=', self.date_end),
            ('debit', '>', 0),
            '|',
            ('account_id.code', '=like', '632%'),
            ('account_id.code', '=like', '156%'),
            '|',
            ('direct_industry_id.is_gold', '=', True),
            ('move_id.ref', 'ilike', 'GOLD'),
        ])
        # Nếu không gắn ngành trên dòng mua: cộng Nợ 632 của công ty kỳ này (DN chỉ KD vàng)
        if not lines:
            lines = self.env['vas.move.line'].search([
                ('move_id.company_id', '=', self.company_id.id),
                ('move_id.state', '=', 'posted'),
                ('date', '>=', self.date_start),
                ('date', '<=', self.date_end),
                ('debit', '>', 0),
                ('account_id.code', '=like', '632%'),
            ])
        return sum(lines.mapped('debit'))

    def _previous_neg_gtgt_carry(self):
        """[21] mẫu 03 = GTGT âm KC từ tờ lần đầu kỳ trước."""
        self.ensure_one()
        prev = self.search([
            ('company_id', '=', self.company_id.id),
            ('form_type_id', '=', self.form_type_id.id),
            ('activity_id', '=', self.activity_id.id),
            ('declaration_round', '=', 0),
            ('date_end', '<', self.date_start),
            ('state', 'in', ('prepared', 'filed', 'accepted')),
        ], order='date_end desc', limit=1)
        if not prev:
            return 0.0
        if prev.amount_neg_carry:
            return prev.amount_neg_carry
        line26 = prev.line_ids.filtered(lambda l: l.code == '26')[:1]
        if line26 and float_compare(line26.amount, 0.0, 0) < 0:
            return abs(line26.amount)
        return 0.0

    def _apply_direct_source_kinds(self, amounts):
        """Điền chỉ tiêu trực tiếp vào dict amounts theo source_kind."""
        self.ensure_one()
        for line in self.line_ids.sorted('sequence'):
            ind = line.indicator_id
            if not ind:
                continue
            sk = ind.source_kind
            tag = ind.ledger_tag or ''
            if sk == 'ledger_direct_revenue':
                amounts[line.code] = self._sum_direct_industry_revenue(tag)
            elif sk == 'direct_industry_tax':
                amounts[line.code] = self._direct_industry_tax(tag)
            elif sk == 'ledger_gold_revenue':
                amounts[line.code] = self._sum_gold_revenue()
            elif sk == 'ledger_gold_cost':
                amounts[line.code] = self._sum_gold_cost()
            elif sk == 'carry_neg_gtgt':
                amounts[line.code] = self._previous_neg_gtgt_carry()
        return amounts

    def action_recompute_amounts(self):
        for rec in self:
            if rec.form_type_id.tax_method == 'direct' and rec.form_type_id.code == '04/GTGT':
                products, undet_n = rec._count_undetermined_direct_products()
                if products or undet_n:
                    raise UserError(_(
                        'Có %s sản phẩm / %s dòng DT CHƯA XÁC ĐỊNH nhóm ngành — '
                        'không lập tờ 04/GTGT. SP: %s',
                        len(products), undet_n,
                        ', '.join(products.mapped('display_name')[:5]),
                    ))
        res = super().action_recompute_amounts()
        for rec in self:
            if rec.declaration_round:
                continue
            if rec.form_type_id.tax_method != 'direct':
                continue
            if rec.state in ('filed', 'accepted'):
                continue
            amounts = {l.code: l.amount for l in rec.line_ids}
            # Giữ manual
            for line in rec.line_ids:
                ind = line.indicator_id
                if ind and ind.source_kind == 'manual':
                    amounts[line.code] = line.amount
            rec._apply_direct_source_kinds(amounts)
            for _pass in range(3):
                for line in rec.line_ids.sorted('sequence'):
                    ind = line.indicator_id
                    if ind and ind.source_kind == 'formula':
                        amounts[line.code] = rec._eval_formula(ind.formula, amounts)
            for line in rec.line_ids:
                if line.code in amounts and line.source_kind != 'manual':
                    line.amount = float_round(amounts[line.code], precision_digits=0)
            # Mẫu 03: lưu GTGT âm chuyển kỳ sau
            if rec.form_type_id.code == '03/GTGT':
                a26 = amounts.get('26', 0.0)
                rec.amount_neg_carry = float_round(max(0.0, -a26), 0)
                # [26b] = [26]-[26a] nếu công thức chưa cover
                line_26b = rec.line_ids.filtered(lambda l: l.code == '26b')[:1]
                if line_26b and line_26b.indicator_id and line_26b.indicator_id.source_kind == 'formula':
                    pass
                a26b = amounts.get('26b', max(0.0, a26 - amounts.get('26a', 0.0)))
                line_27 = rec.line_ids.filtered(lambda l: l.code == '27')[:1]
                if line_27 and line_27.indicator_id.source_kind == 'formula':
                    line_27.amount = rec._eval_formula(
                        line_27.indicator_id.formula,
                        {**amounts, '26b': a26b},
                    )
        return res


class VasGtgtFormTypeMethod(models.Model):
    _inherit = 'vas.gtgt.form.type'

    tax_method = fields.Selection(
        [
            ('deduction', 'Khấu trừ'),
            ('direct', 'Trực tiếp'),
        ],
        string='Phương pháp',
        default='deduction',
        required=True,
        index=True,
    )


class VasGtgtIndicatorDirect(models.Model):
    _inherit = 'vas.gtgt.indicator'

    source_kind = fields.Selection(
        selection_add=[
            ('ledger_direct_revenue', 'Doanh thu theo nhóm ngành (trực tiếp)'),
            ('direct_industry_tax', 'Thuế = DT nhóm × tỷ lệ dữ liệu'),
            ('ledger_gold_revenue', 'DT vàng bạc đá quý [22] mẫu 03'),
            ('ledger_gold_cost', 'Giá vốn / giá mua vàng bạc [23] mẫu 03'),
            ('carry_neg_gtgt', 'GTGT âm KC kỳ trước [21] mẫu 03'),
        ],
        ondelete={
            'ledger_direct_revenue': 'cascade',
            'direct_industry_tax': 'cascade',
            'ledger_gold_revenue': 'cascade',
            'ledger_gold_cost': 'cascade',
            'carry_neg_gtgt': 'cascade',
        },
    )


class VasGtgtRegistrationMethod(models.Model):
    _inherit = 'vas.gtgt.registration'

    @api.onchange('company_id')
    def _onchange_company_method_domain(self):
        if not self.company_id:
            return
        method = self.env['vas.gtgt.tax.method'].method_on(
            self.company_id, fields.Date.context_today(self),
        )
        return {
            'domain': {
                'form_type_id': [('tax_method', '=', method)],
            },
        }

    @api.model_create_multi
    def create(self, vals_list):
        Method = self.env['vas.gtgt.tax.method']
        Form = self.env['vas.gtgt.form.type']
        for vals in vals_list:
            company = self.env['res.company'].browse(
                vals.get('company_id') or self.env.company.id,
            )
            form = Form.browse(vals['form_type_id']) if vals.get('form_type_id') else Form
            on_date = fields.Date.to_date(
                vals.get('date_start') or fields.Date.context_today(self),
            )
            method = Method.method_on(company, on_date)
            if form and form.exists() and form.tax_method != method:
                raise UserError(_(
                    'Công ty đang theo phương pháp «%s» — không đăng ký tờ «%s» '
                    '(phương pháp %s).',
                    dict(Method._fields['method'].selection).get(method),
                    form.code,
                    dict(form._fields['tax_method'].selection).get(form.tax_method),
                ))
        return super().create(vals_list)
