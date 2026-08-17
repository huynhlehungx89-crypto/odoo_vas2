# -*- coding: utf-8 -*-
"""Tờ khai 01/GTGT — vòng đời + máy tính chỉ tiêu từ sổ VAS."""
import re
from calendar import monthrange
from datetime import date

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero, float_round


_TOKEN_RE = re.compile(r'\[([0-9]+[a-z]?)\]')


class VasGtgtDeclaration(models.Model):
    _name = 'vas.gtgt.declaration'
    _description = 'Tờ khai GTGT'
    _order = 'date_start desc, activity_id, declaration_round'

    name = fields.Char(compute='_compute_name', store=True)
    company_id = fields.Many2one(
        'res.company', required=True, ondelete='cascade', index=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        related='company_id.currency_id', store=True,
    )
    form_type_id = fields.Many2one(
        'vas.gtgt.form.type', required=True, ondelete='restrict', index=True,
    )
    form_version_id = fields.Many2one(
        'vas.gtgt.form.version', required=True, ondelete='restrict', index=True,
        string='Phiên bản mẫu',
    )
    circular_label = fields.Char(
        related='form_version_id.circular_label', string='Văn bản áp dụng', store=True,
    )
    activity_id = fields.Many2one(
        'vas.gtgt.activity', string='Hoạt động [01a]',
        required=True, ondelete='restrict', index=True,
    )
    period_kind = fields.Selection(
        [('month', 'Tháng'), ('quarter', 'Quý')],
        required=True,
    )
    year = fields.Integer(required=True)
    month = fields.Integer(string='Tháng')
    quarter = fields.Integer(string='Quý')
    date_start = fields.Date(required=True, index=True)
    date_end = fields.Date(required=True, index=True)
    declaration_round = fields.Integer(
        string='Lần khai',
        default=0,
        help='0 = lần đầu [02]. Chặng 6 mới làm bổ sung.',
    )
    is_first_filing = fields.Boolean(
        string='Lần đầu [02]',
        default=True,
        compute='_compute_is_first_filing',
        store=True,
    )
    state = fields.Selection(
        [
            ('draft', 'Nháp'),
            ('prepared', 'Đã lập'),
            ('filed', 'Đã nộp'),
            ('accepted', 'Cơ quan thuế chấp nhận'),
            ('rejected', 'Bị từ chối'),
        ],
        default='draft',
        required=True,
        index=True,
    )
    reject_reason = fields.Text(string='Lý do từ chối')

    # Phần đầu tờ (nhập tay / lấy từ công ty)
    taxpayer_name = fields.Char(string='[04] Tên người nộp thuế')
    taxpayer_vat = fields.Char(string='[05] Mã số thuế')
    agent_name = fields.Char(string='[06] Đại lý thuế')
    agent_vat = fields.Char(string='[07] MST đại lý')
    agent_contract = fields.Char(string='[08] Hợp đồng DV thuế')
    branch_name = fields.Char(string='[09] ĐVPT / địa điểm KD')
    branch_vat = fields.Char(string='[10] MST ĐVPT')
    branch_address = fields.Char(string='[11] Địa chỉ')
    branch_ward = fields.Char(string='[11a] Xã/phường')
    branch_province = fields.Char(string='[11c] Tỉnh/TP')

    line_ids = fields.One2many(
        'vas.gtgt.declaration.line', 'declaration_id', string='Chỉ tiêu',
    )
    reduction_annex_ids = fields.One2many(
        'vas.gtgt.reduction.annex', 'declaration_id',
        string='Phụ lục giảm thuế NQ 204',
    )
    reduction_annex_id = fields.Many2one(
        'vas.gtgt.reduction.annex',
        compute='_compute_reduction_annex_id',
        string='Phụ lục giảm thuế',
    )
    show_reduction_annex = fields.Boolean(
        compute='_compute_reduction_annex_id',
    )
    reduction_warning_text = fields.Text(
        string='Cảnh báo NQ 204',
        readonly=True,
    )
    amount_22 = fields.Monetary(
        string='[22] Chuyển kỳ trước',
        currency_field='currency_id',
        help='Lưu trên tờ khai — lấy từ [43] kỳ trước hoặc nhập tay kỳ đầu.',
    )
    amount_22_manual = fields.Boolean(
        string='[22] nhập tay (kỳ đầu)',
        default=False,
    )
    tax_balance_warning = fields.Char(
        string='Cảnh báo lệch TK thuế',
        readonly=True,
    )
    registration_hint = fields.Char(
        string='Tờ khai cần lập kỳ này',
        compute='_compute_registration_hint',
    )

    # Chỉ để xếp giao diện: bảng kê / phân loại đầu vào hiện trên thẻ tờ khai.
    sale_listing_id = fields.Many2one(
        'vas.gtgt.listing', compute='_compute_gtgt_ui_links',
        string='Bảng kê bán ra',
    )
    purchase_listing_id = fields.Many2one(
        'vas.gtgt.listing', compute='_compute_gtgt_ui_links',
        string='Bảng kê mua vào',
    )
    sale_listing_line_ids = fields.One2many(
        related='sale_listing_id.line_ids', string='Dòng bảng kê bán ra',
    )
    purchase_listing_line_ids = fields.One2many(
        related='purchase_listing_id.line_ids', string='Dòng bảng kê mua vào',
    )
    show_input_tax_tab = fields.Boolean(
        related='company_id.vas_has_exempt_sales',
        string='Hiện thẻ phân loại thuế đầu vào',
    )
    input_tax_line_ids = fields.Many2many(
        'vas.move.line', compute='_compute_input_tax_line_ids',
        string='Thuế đầu vào kỳ này',
    )

    _uniq_key = models.Constraint(
        'unique(company_id, form_type_id, date_start, date_end, activity_id, declaration_round)',
        'Trùng khóa tờ khai (mẫu + kỳ + hoạt động + lần khai).',
    )

    @api.depends('form_type_id', 'date_start', 'date_end', 'activity_id', 'declaration_round')
    def _compute_name(self):
        for rec in self:
            act = rec.activity_id.code if rec.activity_id else '?'
            rnd = 'Lần đầu' if not rec.declaration_round else 'Lần %s' % rec.declaration_round
            rec.name = '%s %s→%s · %s · %s' % (
                rec.form_type_id.code or 'GTGT',
                rec.date_start or '',
                rec.date_end or '',
                act,
                rnd,
            )

    @api.depends('declaration_round')
    def _compute_is_first_filing(self):
        for rec in self:
            rec.is_first_filing = not rec.declaration_round

    @api.depends('company_id', 'form_type_id', 'date_start')
    def _compute_registration_hint(self):
        Reg = self.env['vas.gtgt.registration']
        for rec in self:
            if not rec.company_id or not rec.form_type_id:
                rec.registration_hint = False
                continue
            reg = Reg.find_active(rec.company_id, rec.form_type_id, rec.date_start)
            if not reg:
                rec.registration_hint = _('Chưa đăng ký tờ khai này — không được lập.')
            else:
                kind = dict(reg._fields['period_kind'].selection).get(reg.period_kind)
                rec.registration_hint = _('Đã đăng ký %s — kỳ kê khai: %s') % (
                    reg.form_type_id.code, kind,
                )

    @api.depends(
        'company_id', 'date_start', 'date_end',
    )
    def _compute_gtgt_ui_links(self):
        Listing = self.env['vas.gtgt.listing']
        for rec in self:
            if not rec.id or not rec.company_id:
                rec.sale_listing_id = False
                rec.purchase_listing_id = False
                continue
            base = [
                ('company_id', '=', rec.company_id.id),
                '|',
                ('declaration_id', '=', rec.id),
                '&',
                ('date_start', '=', rec.date_start),
                ('date_end', '=', rec.date_end),
            ]
            rec.sale_listing_id = Listing.search(
                base + [('listing_type', '=', 'sale')], limit=1,
            )
            rec.purchase_listing_id = Listing.search(
                base + [('listing_type', '=', 'purchase')], limit=1,
            )

    @api.depends(
        'company_id', 'date_start', 'date_end', 'show_input_tax_tab',
    )
    def _compute_input_tax_line_ids(self):
        Line = self.env['vas.move.line']
        for rec in self:
            if (
                not rec.show_input_tax_tab
                or not rec.company_id
                or not rec.date_start
                or not rec.date_end
            ):
                rec.input_tax_line_ids = Line.browse()
                continue
            rec.input_tax_line_ids = Line.search([
                ('move_id.company_id', '=', rec.company_id.id),
                ('move_id.state', '=', 'posted'),
                ('tax_id', '!=', False),
                ('debit', '>', 0),
                ('account_id.code', '=like', '1331%'),
                ('date', '>=', rec.date_start),
                ('date', '<=', rec.date_end),
            ])

    @api.model
    def action_open_gtgt_registration(self):
        return self.env['ir.actions.act_window']._for_xml_id(
            'connecta_vas.action_vas_gtgt_registration',
        )

    @api.model
    def action_open_gtgt_tax_method(self):
        return self.env['ir.actions.act_window']._for_xml_id(
            'connecta_vas.action_vas_gtgt_tax_method',
        )

    def action_open_sale_listing(self):
        self.ensure_one()
        return self._action_open_listing(self.sale_listing_id)

    def action_open_purchase_listing(self):
        self.ensure_one()
        return self._action_open_listing(self.purchase_listing_id)

    def _action_open_listing(self, listing):
        if not listing:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': listing.display_name,
            'res_model': 'vas.gtgt.listing',
            'res_id': listing.id,
            'view_mode': 'form',
            'target': 'current',
        }

    @api.depends('reduction_annex_ids', 'reduction_annex_ids.has_eligible_sales')
    def _compute_reduction_annex_id(self):
        for rec in self:
            annex = rec.reduction_annex_ids[:1]
            rec.reduction_annex_id = annex
            rec.show_reduction_annex = bool(annex and annex.has_eligible_sales)

    @api.model
    def _period_bounds(self, period_kind, year, month=None, quarter=None):
        if period_kind == 'month':
            if not month or month < 1 or month > 12:
                raise ValidationError(_('Tháng không hợp lệ.'))
            start = date(year, month, 1)
            end = date(year, month, monthrange(year, month)[1])
        elif period_kind == 'quarter':
            if not quarter or quarter < 1 or quarter > 4:
                raise ValidationError(_('Quý không hợp lệ.'))
            m0 = (quarter - 1) * 3 + 1
            start = date(year, m0, 1)
            m1 = m0 + 2
            end = date(year, m1, monthrange(year, m1)[1])
        else:
            raise ValidationError(_('Loại kỳ không hợp lệ.'))
        return start, end

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        # Recordset rỗng + fields_list=[] phải trả {} (hợp đồng ORM / TestOverrides).
        if not fields_list:
            return res
        wanted = set(fields_list)
        Form = self.env['vas.gtgt.form.type']
        form = Form.search([('code', '=', '01/GTGT')], limit=1)
        if form and 'form_type_id' in wanted:
            res.setdefault('form_type_id', form.id)
        today = fields.Date.context_today(self)
        if 'year' in wanted:
            res.setdefault('year', today.year)
        if 'month' in wanted:
            res.setdefault('month', today.month)
        if 'period_kind' in wanted:
            res.setdefault('period_kind', 'month')
        company = self.env.company
        if 'taxpayer_name' in wanted:
            res.setdefault('taxpayer_name', company.name)
        if 'taxpayer_vat' in wanted:
            res.setdefault('taxpayer_vat', company.vat or '')
        return res

    @api.onchange('period_kind', 'year', 'month', 'quarter', 'form_type_id')
    def _onchange_period(self):
        if not self.year or not self.form_type_id:
            return
        try:
            start, end = self._period_bounds(
                self.period_kind, self.year, self.month, self.quarter,
            )
        except ValidationError:
            return
        self.date_start = start
        self.date_end = end
        ver = self.env['vas.gtgt.form.version'].find_for_period_start(
            self.form_type_id, start,
        )
        self.form_version_id = ver

    @api.model_create_multi
    def create(self, vals_list):
        Form = self.env['vas.gtgt.form.type']
        Reg = self.env['vas.gtgt.registration']
        Version = self.env['vas.gtgt.form.version']
        for vals in vals_list:
            form = Form.browse(vals.get('form_type_id')) if vals.get('form_type_id') else Form
            company = self.env['res.company'].browse(
                vals.get('company_id') or self.env.company.id
            )
            kind = vals.get('period_kind')
            year = vals.get('year')
            if not vals.get('date_start') and kind and year:
                start, end = self._period_bounds(
                    kind, year, vals.get('month'), vals.get('quarter'),
                )
                vals['date_start'] = start
                vals['date_end'] = end
            start = fields.Date.to_date(vals.get('date_start'))
            if form and form.exists():
                reg = Reg.find_active(company, form, start)
                if not reg:
                    raise UserError(_(
                        'Chưa đăng ký tờ khai %s — không được lập.',
                        form.code,
                    ))
                if kind and reg.period_kind != kind:
                    raise UserError(_(
                        'Kỳ kê khai đăng ký là «%s», không khớp tờ khai đang lập.',
                        dict(reg._fields['period_kind'].selection).get(reg.period_kind),
                    ))
                if not vals.get('form_version_id') and start:
                    ver = Version.find_for_period_start(form, start)
                    if not ver:
                        raise UserError(_(
                            'Không tìm thấy phiên bản mẫu cho kỳ bắt đầu %s.', start,
                        ))
                    vals['form_version_id'] = ver.id
            vals.setdefault('taxpayer_name', company.name)
            vals.setdefault('taxpayer_vat', company.vat or '')
        records = super().create(vals_list)
        for rec in records:
            rec._ensure_lines()
        return records

    def write(self, vals):
        if 'state' in vals and vals['state'] == 'rejected' and not vals.get('reject_reason'):
            for rec in self:
                if not rec.reject_reason:
                    raise UserError(_('Cần nhập lý do từ chối.'))
        return super().write(vals)

    def _ensure_lines(self):
        Line = self.env['vas.gtgt.declaration.line']
        for rec in self:
            existing = {l.code: l for l in rec.line_ids}
            for ind in rec.form_version_id.indicator_ids.filtered(
                lambda i: i.column_kind != 'header'
            ):
                if ind.code in existing:
                    existing[ind.code].indicator_id = ind.id
                    continue
                Line.create({
                    'declaration_id': rec.id,
                    'indicator_id': ind.id,
                    'code': ind.code,
                    'name': ind.name,
                    'column_kind': ind.column_kind,
                    'source_kind': ind.source_kind,
                    'is_computed': ind.is_computed,
                    'sequence': ind.sequence,
                })

    def _previous_declaration(self):
        self.ensure_one()
        return self.search([
            ('company_id', '=', self.company_id.id),
            ('form_type_id', '=', self.form_type_id.id),
            ('activity_id', '=', self.activity_id.id),
            ('declaration_round', '=', 0),
            ('date_end', '<', self.date_start),
            ('state', 'in', ('prepared', 'filed', 'accepted')),
        ], order='date_end desc', limit=1)

    def _line_amount_map(self):
        return {l.code: l.amount for l in self.line_ids}

    def _eval_formula(self, formula, amounts):
        if not formula:
            return 0.0
        parts = formula.split(';')
        expr = parts[0].strip()
        post = parts[1].strip() if len(parts) > 1 else ''

        def repl(match):
            code = match.group(1)
            return str(float(amounts.get(code, 0.0)))

        safe = _TOKEN_RE.sub(repl, expr)
        if not re.fullmatch(r'[0-9+\-*/().\s]+', safe):
            raise UserError(_('Công thức không hợp lệ: %s') % formula)
        value = float(eval(safe, {'__builtins__': {}}, {}))  # noqa: S307 — biểu thức số đã lọc
        if post == 'max0':
            value = max(value, 0.0)
        elif post == 'min0':
            value = min(value, 0.0)
            value = abs(value) if value < 0 else 0.0
            # [41] trên mẫu: phần âm của biểu thức → số dương «chưa khấu trừ hết»
            # Công thức seed dùng ;neg_as_positive
        elif post == 'neg_as_positive':
            value = abs(min(value, 0.0))
        elif post.startswith('cap:'):
            cap_code = post.split(':', 1)[1]
            cap = float(amounts.get(cap_code, 0.0))
            value = min(value, cap)
        return float_round(value, precision_digits=0)

    def _sum_ledger_output_value(self, tag):
        self.ensure_one()
        lines = self.env['vas.move.line'].search([
            ('move_id.company_id', '=', self.company_id.id),
            ('move_id.state', '=', 'posted'),
            ('date', '>=', self.date_start),
            ('date', '<=', self.date_end),
            ('credit', '>', 0),
            ('account_id.code', '=like', '511%'),
            ('tax_id.declaration_value_tag', '=', tag),
        ])
        return sum(lines.mapped('credit'))

    def _sum_ledger_output_tax(self, tag):
        self.ensure_one()
        lines = self.env['vas.move.line'].search([
            ('move_id.company_id', '=', self.company_id.id),
            ('move_id.state', '=', 'posted'),
            ('date', '>=', self.date_start),
            ('date', '<=', self.date_end),
            ('credit', '>', 0),
            ('account_id.code', '=like', '3331%'),
            ('tax_id.declaration_tax_tag', '=', tag),
        ])
        return sum(lines.mapped('credit'))

    def _input_vat_lines(self):
        self.ensure_one()
        return self.env['vas.move.line'].search([
            ('move_id.company_id', '=', self.company_id.id),
            ('move_id.state', '=', 'posted'),
            ('date', '>=', self.date_start),
            ('date', '<=', self.date_end),
            ('debit', '>', 0),
            ('account_id.code', '=like', '1331%'),
            '|', '|',
            ('tax_id', '!=', False),
            ('move_id.source_model', '=', 'vas.import.vat'),
            ('move_id.move_kind', '=', 'import_vat'),
        ])

    def _sum_input_base(self):
        return sum(self._input_vat_lines().mapped('deduction_base_untaxed'))

    def _sum_input_tax(self):
        return sum(self._input_vat_lines().mapped('debit'))

    def _sum_input_deductible(self):
        return sum(self._input_vat_lines().mapped('deductible_amount'))

    def _sum_import_base(self):
        # NK: dòng thuế gắn nguồn import_vat hoặc TK liên quan 33312 trên cùng move
        lines = self._input_vat_lines().filtered(
            lambda l: l.move_id.source_model == 'vas.import.vat'
            or any(
                (x.account_id.code or '').startswith('33312')
                for x in l.move_id.line_ids
            )
        )
        return sum(lines.mapped('deduction_base_untaxed'))

    def _sum_import_tax(self):
        lines = self._input_vat_lines().filtered(
            lambda l: l.move_id.source_model == 'vas.import.vat'
            or any(
                (x.account_id.code or '').startswith('33312')
                for x in l.move_id.line_ids
            )
        )
        return sum(lines.mapped('debit'))

    def _has_buy_sell_activity(self):
        buy = self._input_vat_lines()
        sell = self.env['vas.move.line'].search_count([
            ('move_id.company_id', '=', self.company_id.id),
            ('move_id.state', '=', 'posted'),
            ('date', '>=', self.date_start),
            ('date', '<=', self.date_end),
            ('credit', '>', 0),
            ('account_id.code', '=like', '511%'),
        ])
        return bool(buy) or bool(sell)

    def _tax_account_balance_133_333(self):
        """Số dư Nợ 1331 − Có 33311 (xấp xỉ thuế còn được khấu trừ trên sổ)."""
        Line = self.env['vas.move.line']
        domain_base = [
            ('move_id.company_id', '=', self.company_id.id),
            ('move_id.state', '=', 'posted'),
            ('date', '<=', self.date_end),
        ]
        d133 = sum(Line.search(domain_base + [
            ('account_id.code', '=like', '1331%'),
        ]).mapped(lambda l: l.debit - l.credit))
        c333 = sum(Line.search(domain_base + [
            ('account_id.code', '=like', '33311%'),
        ]).mapped(lambda l: l.credit - l.debit))
        return d133 - c333

    def action_recompute_amounts(self):
        """Nút LẬP LẠI SỐ — tính từ sổ, không đổi trạng thái."""
        for rec in self:
            block = rec.company_id.vas_gtgt_declaration_block_reason()
            if block:
                raise UserError(block)
            reg = self.env['vas.gtgt.registration'].find_active(
                rec.company_id, rec.form_type_id, rec.date_start,
            )
            if not reg:
                raise UserError(_(
                    'Chưa đăng ký tờ khai %s — không được lập.',
                    rec.form_type_id.code,
                ))
            rec._ensure_lines()
            # [22] từ kỳ trước trừ khi nhập tay kỳ đầu
            prev = rec._previous_declaration()
            if prev and not rec.amount_22_manual:
                prev_43 = prev.line_ids.filtered(lambda l: l.code == '43')[:1]
                rec.amount_22 = prev_43.amount if prev_43 else 0.0
            elif not prev and not rec.amount_22_manual:
                rec.amount_22_manual = True

            amounts = {}
            # Giữ số nhập tay hiện có
            for line in rec.line_ids.sorted('sequence'):
                ind = line.indicator_id
                if not ind:
                    continue
                if ind.source_kind == 'manual':
                    amounts[line.code] = line.amount
                elif ind.source_kind == 'carry_forward':
                    amounts[line.code] = rec.amount_22
                    line.amount = rec.amount_22
                elif ind.source_kind == 'ledger_output_value':
                    amounts[line.code] = rec._sum_ledger_output_value(ind.ledger_tag or line.code)
                elif ind.source_kind == 'ledger_output_tax':
                    amounts[line.code] = rec._sum_ledger_output_tax(ind.ledger_tag or line.code)
                elif ind.source_kind == 'ledger_input_base':
                    amounts[line.code] = rec._sum_input_base()
                elif ind.source_kind == 'ledger_input_tax':
                    amounts[line.code] = rec._sum_input_tax()
                elif ind.source_kind == 'ledger_input_import_base':
                    amounts[line.code] = rec._sum_import_base()
                elif ind.source_kind == 'ledger_input_import_tax':
                    amounts[line.code] = rec._sum_import_tax()
                elif ind.source_kind == 'ledger_input_deductible':
                    amounts[line.code] = rec._sum_input_deductible()
                elif ind.source_kind == 'auto_flag':
                    amounts[line.code] = 0.0 if rec._has_buy_sell_activity() else 1.0
                elif ind.source_kind == 'formula':
                    amounts[line.code] = 0.0  # điền vòng sau
                else:
                    amounts[line.code] = line.amount

            # Hai vòng formula để phụ thuộc chuỗi
            for _pass in range(3):
                for line in rec.line_ids.sorted('sequence'):
                    ind = line.indicator_id
                    if ind and ind.source_kind == 'formula':
                        amounts[line.code] = rec._eval_formula(ind.formula, amounts)

            for line in rec.line_ids:
                if line.code in amounts and line.source_kind != 'manual':
                    line.amount = float_round(amounts[line.code], precision_digits=0)
                elif line.code == '22':
                    line.amount = rec.amount_22

            # Ràng buộc [40b]≤[40a], [42]≤[41] rồi tính lại [40]/[43]
            amt_map = {l.code: l.amount for l in rec.line_ids}
            if '40b' in amt_map and '40a' in amt_map:
                capped = min(amt_map['40b'], amt_map['40a'])
                line_40b = rec.line_ids.filtered(lambda l: l.code == '40b')[:1]
                if line_40b and float_compare(line_40b.amount, capped, 0) != 0:
                    line_40b.amount = capped
                    amt_map['40b'] = capped
            if '42' in amt_map and '41' in amt_map:
                capped = min(amt_map['42'], amt_map['41'])
                line_42 = rec.line_ids.filtered(lambda l: l.code == '42')[:1]
                if line_42 and float_compare(line_42.amount, capped, 0) != 0:
                    line_42.amount = capped
                    amt_map['42'] = capped
            for code, formula in (
                ('40', '[40a]-[40b]'),
                ('43', '[41]-[42]'),
            ):
                line = rec.line_ids.filtered(lambda l: l.code == code)[:1]
                if line:
                    line.amount = rec._eval_formula(formula, amt_map)
                    amt_map[code] = line.amount

            amt_43 = amt_map.get('43', 0.0)
            bal = rec._tax_account_balance_133_333()
            if float_compare(abs(amt_43 - bal), 1.0, precision_digits=0) > 0:
                rec.tax_balance_warning = _(
                    'Cảnh báo: [43]=%(a)s lệch số dư TK thuế trên sổ (~%(b)s). '
                    'Không chặn — lệch có thể hợp lệ sau khai bổ sung.',
                    a=int(amt_43), b=int(bal),
                )
            else:
                rec.tax_balance_warning = False

            rec._rebuild_nq204_annex()
        return True

    def _nq204_force_window(self):
        """Hiệu lực NQ 204 lấy từ dữ liệu vas.tax GTGT_8 (không chôn trong mã)."""
        tax8 = self.env['vas.tax'].search([
            ('code', '=', 'GTGT_8'),
            ('regime_id', '=', self.company_id.vas_regime_id.id),
        ], limit=1)
        if not tax8:
            return False, False
        return tax8.date_start, tax8.date_end

    def _iter_sale_8pct_invoice_lines(self):
        """Yield (vas_revenue_line, account.move.line|False, product|False)."""
        self.ensure_one()
        Line = self.env['vas.move.line']
        value_lines = Line.search([
            ('move_id.company_id', '=', self.company_id.id),
            ('move_id.state', '=', 'posted'),
            ('date', '>=', self.date_start),
            ('date', '<=', self.date_end),
            ('credit', '>', 0),
            ('account_id.code', '=like', '511%'),
            ('tax_id.code', '=', 'GTGT_8'),
        ])
        for vl in value_lines:
            move = vl.move_id
            inv_line = self.env['account.move.line']
            product = self.env['product.product']
            if move.source_model == 'account.move' and move.source_res_id:
                inv = self.env['account.move'].browse(move.source_res_id).exists()
                if inv:
                    # Khớp dòng HĐ theo số tiền gần nhất + thuế 8%
                    cands = inv.invoice_line_ids.filtered(
                        lambda l: any(abs(t.amount - 8.0) < 0.01 for t in l.tax_ids)
                    )
                    if len(cands) == 1:
                        inv_line = cands
                    elif cands:
                        match = cands.filtered(
                            lambda l: float_compare(l.price_subtotal, vl.credit, 0) == 0
                        )[:1]
                        inv_line = match or cands[:1]
                    if inv_line:
                        product = inv_line.product_id
            yield vl, inv_line, product

    def _scan_odoo_8pct_out_of_force_warnings(self, force_start, force_end):
        """HĐ Odoo ghi 8% ngoài hiệu lực — cảnh báo dù VAS không gán GTGT_8."""
        self.ensure_one()
        if not force_start or not force_end:
            return []
        Move = self.env['account.move']
        invoices = Move.search([
            ('company_id', '=', self.company_id.id),
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('date', '>=', self.date_start),
            ('date', '<=', self.date_end),
        ])
        warnings = []
        for inv in invoices:
            inv_date = inv.invoice_date or inv.date
            if not inv_date or (force_start <= inv_date <= force_end):
                continue
            for line in inv.invoice_line_ids:
                if not any(abs(t.amount - 8.0) < 0.01 for t in line.tax_ids):
                    continue
                product = line.product_id
                pname = product.display_name if product else (line.name or '/')
                warnings.append({
                    'declaration_id': self.id,
                    'company_id': self.company_id.id,
                    'warning_kind': 'out_of_force',
                    'product_name': pname,
                    'invoice_ref': inv.name if inv.name != '/' else (inv.ref or ''),
                    'invoice_date': inv_date,
                    'message': _(
                        'HĐ %s ngày %s — mặt hàng «%s» ghi 8%% ngoài hiệu lực '
                        'NQ 204 (%s → %s). Không sửa HĐ.',
                        inv.name, inv_date, pname, force_start, force_end,
                    ),
                })
        return warnings

    def _rebuild_nq204_annex(self):
        """Lập phụ lục Mẫu 01 PL III + cảnh báo; chỉ giữ khi có bán được giảm."""
        self.ensure_one()
        Annex = self.env['vas.gtgt.reduction.annex']
        Warning = self.env['vas.gtgt.reduction.warning']
        Exclusion = self.env['vas.gtgt.reduction.exclusion']
        self.reduction_annex_ids.unlink()
        Warning.search([('declaration_id', '=', self.id)]).unlink()

        force_start, force_end = self._nq204_force_window()
        sale_lines = []
        purchase_untaxed = purchase_tax = 0.0
        warnings = list(self._scan_odoo_8pct_out_of_force_warnings(
            force_start, force_end,
        ))
        seq = 10

        # Mua vào 8% trên sổ (đơn giản: Nợ 1331 gắn GTGT_8)
        buy_tax = self.env['vas.move.line'].search([
            ('move_id.company_id', '=', self.company_id.id),
            ('move_id.state', '=', 'posted'),
            ('date', '>=', self.date_start),
            ('date', '<=', self.date_end),
            ('debit', '>', 0),
            ('account_id.code', '=like', '1331%'),
            ('tax_id.code', '=', 'GTGT_8'),
        ])
        for bl in buy_tax:
            purchase_tax += bl.debit
            purchase_untaxed += bl.deduction_base_untaxed or 0.0

        for vl, inv_line, product in self._iter_sale_8pct_invoice_lines():
            inv_date = vl.date
            inv_ref = vl.move_id.source_ref or vl.move_id.ref or vl.move_id.name
            if vl.move_id.source_model == 'account.move' and vl.move_id.source_res_id:
                inv = self.env['account.move'].browse(vl.move_id.source_res_id).exists()
                if inv:
                    inv_date = inv.invoice_date or inv.date
                    inv_ref = inv.name if inv.name and inv.name != '/' else (inv.ref or inv_ref)
            pname = (
                product.display_name if product
                else (inv_line.name if inv_line else vl.name or _('(không SP)'))
            )

            # Ngoài hiệu lực
            if force_start and force_end and inv_date and (
                inv_date < force_start or inv_date > force_end
            ):
                warnings.append({
                    'declaration_id': self.id,
                    'company_id': self.company_id.id,
                    'warning_kind': 'out_of_force',
                    'product_name': pname,
                    'invoice_ref': inv_ref,
                    'invoice_date': inv_date,
                    'message': _(
                        'HĐ %s ngày %s — mặt hàng «%s» ghi 8%% ngoài hiệu lực '
                        'NQ 204 (%s → %s). Không sửa HĐ.',
                        inv_ref, inv_date, pname, force_start, force_end,
                    ),
                })
                continue

            status, excl = Exclusion.match_product(product, inv_date or vl.date)
            if status == 'undetermined':
                warnings.append({
                    'declaration_id': self.id,
                    'company_id': self.company_id.id,
                    'warning_kind': 'undetermined',
                    'product_name': pname,
                    'invoice_ref': inv_ref,
                    'invoice_date': inv_date,
                    'message': _(
                        'HĐ %s — mặt hàng «%s» CHƯA XÁC ĐỊNH chiều nhận diện '
                        '(VSIC/HS/TTĐB). Không mặc định được giảm.',
                        inv_ref, pname,
                    ),
                })
                continue
            if status == 'excluded':
                warnings.append({
                    'declaration_id': self.id,
                    'company_id': self.company_id.id,
                    'warning_kind': 'excluded',
                    'product_name': pname,
                    'invoice_ref': inv_ref,
                    'invoice_date': inv_date,
                    'exclusion_id': excl.id,
                    'message': _(
                        'HĐ %s — mặt hàng «%s» thuộc danh mục KHÔNG được giảm '
                        '(mã %s · %s · PL %s). Không sửa HĐ.',
                        inv_ref, pname, excl.code, excl.name, excl.annex,
                    ),
                })
                continue

            tax_amt = sum(vl.move_id.line_ids.filtered(
                lambda l: (l.account_id.code or '').startswith('3331')
                and l.tax_id
                and l.tax_id.code == 'GTGT_8'
                and l.credit > 0
            ).mapped('credit'))
            n_rev = len([
                x for x in vl.move_id.line_ids
                if (x.account_id.code or '').startswith('511')
                and x.tax_id and x.tax_id.code == 'GTGT_8'
            ])
            sale_lines.append({
                'sequence': seq,
                'section': 'sale',
                'product_name': pname,
                'amount_untaxed': vl.credit,
                'amount_tax': tax_amt if n_rev <= 1 else float_round(vl.credit * 0.08, 0),
                'rate_before': 10.0,
                'rate_after': 8.0,
                'source_move_line_id': vl.id,
            })
            seq += 1

        warn_text = False
        if warnings:
            warn_text = '\n'.join(w['message'] for w in warnings)

        if not sale_lines:
            for w in warnings:
                Warning.create(w)
            self.reduction_warning_text = warn_text
            return

        annex = Annex.create({
            'declaration_id': self.id,
            'amount_05': float_round(purchase_untaxed, 0),
            'amount_06': float_round(purchase_tax, 0),
            'amount_07': float_round(sum(l['amount_untaxed'] for l in sale_lines), 0),
            'amount_08': float_round(sum(l['amount_tax'] for l in sale_lines), 0),
        })
        annex.amount_09 = float_round(annex.amount_08 - annex.amount_06, 0)
        for vals in sale_lines:
            vals['annex_id'] = annex.id
            self.env['vas.gtgt.reduction.annex.line'].create(vals)
        for w in warnings:
            w['annex_id'] = annex.id
            Warning.create(w)
        self.reduction_warning_text = warn_text

    def action_prepare(self):
        self.action_recompute_amounts()
        self.write({'state': 'prepared'})

    def action_set_state_draft(self):
        self.write({'state': 'draft'})

    def action_set_state_filed(self):
        self.write({'state': 'filed'})

    def action_set_state_accepted(self):
        self.write({'state': 'accepted'})

    def action_set_state_rejected(self):
        for rec in self:
            if not rec.reject_reason:
                raise UserError(_('Cần nhập lý do từ chối.'))
        self.write({'state': 'rejected'})


class VasGtgtDeclarationLine(models.Model):
    _name = 'vas.gtgt.declaration.line'
    _description = 'Dòng chỉ tiêu tờ khai GTGT'
    _order = 'sequence, code'

    declaration_id = fields.Many2one(
        'vas.gtgt.declaration', required=True, ondelete='cascade', index=True,
    )
    indicator_id = fields.Many2one(
        'vas.gtgt.indicator', ondelete='restrict', index=True,
    )
    sequence = fields.Integer(default=100)
    code = fields.Char(required=True, index=True)
    name = fields.Char(required=True)
    column_kind = fields.Selection(
        [
            ('value', 'Giá trị'),
            ('tax', 'Thuế'),
            ('flag', 'Đánh dấu'),
            ('header', 'Đầu tờ'),
        ],
        required=True,
        default='tax',
    )
    source_kind = fields.Char()
    is_computed = fields.Boolean(string='Máy tính')
    amount = fields.Monetary(
        string='Số tiền',
        currency_field='currency_id',
        default=0.0,
    )
    currency_id = fields.Many2one(related='declaration_id.currency_id')

    _decl_code_uniq = models.Constraint(
        'unique(declaration_id, code)',
        'Trùng số hiệu chỉ tiêu trên một tờ khai.',
    )
