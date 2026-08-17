# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_is_zero


class VasMoveLine(models.Model):
    _name = 'vas.move.line'
    _description = 'Dòng bút toán VAS'
    _order = 'date desc, move_id desc, sequence, id'

    move_id = fields.Many2one(
        'vas.move',
        string='Bút toán',
        required=True,
        index=True,
        ondelete='cascade',
    )
    sequence = fields.Integer(string='Thứ tự', default=10)
    account_id = fields.Many2one(
        'vas.account',
        string='Tài khoản',
        required=True,
        index=True,
        ondelete='restrict',
    )
    name = fields.Char(string='Diễn giải')
    company_currency_id = fields.Many2one(
        'res.currency',
        string='Đồng tiền hạch toán',
        compute='_compute_company_currency_id',
        store=True,
        readonly=True,
        help='Always VND — VAS accounting currency (DAC §0.5 / §9).',
    )
    debit = fields.Monetary(
        string='Nợ',
        currency_field='company_currency_id',
        default=0.0,
    )
    credit = fields.Monetary(
        string='Có',
        currency_field='company_currency_id',
        default=0.0,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Tiền tệ',
        required=True,
        default=lambda self: self.env.ref('base.VND'),
    )
    amount_currency = fields.Monetary(
        string='Số tiền nguyên tệ',
        currency_field='currency_id',
        default=0.0,
        help='Amount in the line currency (signed). Required when currency ≠ VND.',
    )
    partner_id = fields.Many2one('res.partner', string='Đối tác', index=True)
    # Soft-link phiên quầy: Integer + tên, KHÔNG Many2one pos.session
    # (connecta_vas không hard-depend point_of_sale).
    pos_session_res_id = fields.Integer(
        string='Phiên quầy (id)',
        index=True,
        default=0,
        help='id pos.session khi có module quầy. 0 = không gắn phiên. '
             'Không tạo res.partner cho từng phiên.',
    )
    pos_session_name = fields.Char(string='Phiên quầy')
    tax_id = fields.Many2one('vas.tax', string='Thuế', ondelete='restrict', index=True)
    tax_status = fields.Selection(
        [
            ('none', 'Không áp dụng'),
            ('resolved', 'Đã xác định'),
            ('undetermined', 'Chưa xác định'),
        ],
        string='Trạng thái thuế suất',
        default='none',
        required=True,
        index=True,
        help='resolved = đã gắn tax_id; undetermined = cần tra nhưng không khớp '
             '(không mặc định thuế suất); none = dòng không mang chiều thuế '
             '(vd phải thu/phải trả).',
    )
    direct_industry_id = fields.Many2one(
        'vas.gtgt.direct.industry',
        string='Nhóm ngành trực tiếp',
        ondelete='restrict',
        index=True,
        copy=False,
    )
    direct_industry_status = fields.Selection(
        [
            ('none', 'Không áp dụng'),
            ('resolved', 'Đã xác định'),
            ('undetermined', 'Chưa xác định'),
        ],
        string='Trạng thái nhóm ngành',
        default='none',
        required=True,
        index=True,
        copy=False,
    )
    analytic_distribution = fields.Json(string='Phân bổ analytic')
    date = fields.Date(
        related='move_id.date',
        store=True,
        index=True,
        readonly=True,
    )
    period_id = fields.Many2one(
        related='move_id.period_id',
        store=True,
        index=True,
        readonly=True,
    )
    regime_id = fields.Many2one(
        related='move_id.regime_id',
        store=True,
        index=True,
        readonly=True,
    )
    reconciled = fields.Boolean(string='Đã đối chiếu', default=False, copy=False)
    amount_residual = fields.Monetary(
        string='Số dư còn lại',
        currency_field='company_currency_id',
        default=0.0,
        copy=False,
    )
    amount_residual_currency = fields.Monetary(
        string='Số dư còn lại (nguyên tệ)',
        currency_field='currency_id',
        default=0.0,
        copy=False,
    )
    full_reconcile_id = fields.Many2one(
        'vas.full.reconcile',
        string='Nhóm đối chiếu',
        copy=False,
        index=True,
        ondelete='set null',
    )
    matching_number = fields.Char(string='Số khớp', copy=False, index=True)
    company_id = fields.Many2one(
        related='move_id.company_id',
        store=True,
        index=True,
        readonly=True,
    )
    cost_item_id = fields.Many2one(
        'vas.cost.item',
        string='Khoản mục chi phí',
        index=True,
        ondelete='restrict',
        help='W12: máy tra lúc sinh bút toán. Bút toán mới chỉ trỏ lá; '
             'lịch sử được phép trỏ nút từng là lá.',
    )
    cost_object_id = fields.Many2one(
        'vas.cost.object',
        string='Đối tượng tập hợp chi phí',
        index=True,
        ondelete='restrict',
        help='W12 Chặng 1B: chỉ schema + bảo vệ. Engine gắn đối tượng ở Chặng 2.',
    )

    @api.depends('company_id')
    def _compute_company_currency_id(self):
        vnd = self.env.ref('base.VND')
        for line in self:
            line.company_currency_id = vnd

    # -------------------------------------------------------------------------
    # Constraints (DAC §7.5 / §7.6)
    # -------------------------------------------------------------------------

    @api.constrains('cost_item_id')
    def _check_cost_item_is_leaf_for_new(self):
        """Bút toán MỚI chỉ trỏ lá (bản 4 mục 4.1 quy tắc 1)."""
        for line in self:
            item = line.cost_item_id
            if item and item.is_aggregate_node:
                raise ValidationError(_(
                    'Bút toán mới chỉ được trỏ vào khoản mục lá. '
                    '«%(code)s — %(name)s» là nút tổng hợp (đã có con) — '
                    'không nhận bút toán mới.',
                    code=item.code or '',
                    name=item.name or '',
                ))

    @api.constrains('currency_id', 'amount_currency')
    def _check_amount_currency_required(self):
        vnd = self.env.ref('base.VND')
        for line in self:
            if line.currency_id and line.currency_id != vnd:
                if float_is_zero(line.amount_currency, precision_rounding=line.currency_id.rounding):
                    raise ValidationError(_(
                        "amount_currency is required when currency is not VND (line account %(account)s).",
                        account=line.account_id.display_name,
                    ))

    @api.constrains('reconciled', 'amount_residual', 'amount_residual_currency', 'full_reconcile_id', 'matching_number', 'account_id')
    def _check_reconcile_only_on_reconcilable(self):
        for line in self:
            if line.account_id.reconcile:
                continue
            residual_nonzero = False
            if line.company_currency_id:
                residual_nonzero = not float_is_zero(
                    line.amount_residual,
                    precision_rounding=line.company_currency_id.rounding,
                )
            residual_currency_nonzero = False
            if line.currency_id:
                residual_currency_nonzero = not float_is_zero(
                    line.amount_residual_currency,
                    precision_rounding=line.currency_id.rounding,
                )
            if (
                line.reconciled
                or line.full_reconcile_id
                or line.matching_number
                or residual_nonzero
                or residual_currency_nonzero
            ):
                raise ValidationError(_(
                    "Reconciliation fields are only allowed on accounts with Allow Reconciliation "
                    "(account %(account)s).",
                    account=line.account_id.display_name,
                ))

    @api.constrains('debit', 'credit')
    def _check_debit_credit_exclusive(self):
        for line in self:
            currency = line.company_currency_id or self.env.ref('base.VND')
            if (
                not float_is_zero(line.debit, precision_rounding=currency.rounding)
                and not float_is_zero(line.credit, precision_rounding=currency.rounding)
            ):
                raise ValidationError(_("A journal item cannot have both debit and credit."))

    # Related/compute stored + số dư đối chiếu. Còn lại mặc định cấm sau post.
    POSTED_WRITE_ALLOW = frozenset({
        'date', 'period_id', 'regime_id', 'company_id', 'company_currency_id',
        'amount_residual', 'amount_residual_currency', 'reconciled',
        'full_reconcile_id', 'matching_number',
        # GTGT đầu vào: phân loại/khấu trừ sau post — không đổi Nợ/Có/TK.
        'use_purpose', 'deduction_check', 'deduction_rule_id',
        'deductible_amount', 'deduction_base_untaxed', 'deduction_base_gross',
    })
    RECONCILE_FIELDS = frozenset({
        'amount_residual', 'amount_residual_currency', 'reconciled',
        'full_reconcile_id', 'matching_number',
    })

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._check_parent_editable()
        return lines

    def write(self, vals):
        for line in self:
            if line.move_id.state == 'posted' and not self.env.context.get('vas_allow_posted_write'):
                forbidden = set(vals) - self.POSTED_WRITE_ALLOW
                if forbidden:
                    raise UserError(_(
                        "Posted move %(name)s is immutable. Use Reverse Entry instead. "
                        "Cannot modify line fields: %(fields)s",
                        name=line.move_id.name,
                        fields=', '.join(sorted(forbidden)),
                    ))
                touched_reco = set(vals) & self.RECONCILE_FIELDS
                if touched_reco and not self.env.context.get('vas_allow_reconcile_write'):
                    raise UserError(_(
                        "Cannot update reconciliation fields on posted move %(name)s "
                        "without vas_allow_reconcile_write.",
                        name=line.move_id.name,
                    ))
            if not self.env.context.get('vas_skip_period_check'):
                move = line.move_id
                self.env['vas.period']._assert_date_writable(
                    move.company_id,
                    move.date,
                    doc_name=move.name,
                    allow_missing=(move.state == 'draft'),
                )
        return super().write(vals)

    def _vas_init_residuals(self):
        """Set amount_residual = debit − credit on reconcilable accounts."""
        for line in self:
            if not line.account_id.reconcile:
                continue
            balance = (line.debit or 0.0) - (line.credit or 0.0)
            line.with_context(
                vas_allow_reconcile_write=True,
                vas_allow_posted_write=True,
                vas_skip_period_check=True,
            ).write({
                'amount_residual': balance,
                'amount_residual_currency': line.amount_currency or balance,
                'reconciled': False,
            })

    def _vas_apply_match(self, amount, full_reconcile=None, matching_number=None):
        """Reduce residual toward 0 by ``amount`` (positive)."""
        self.ensure_one()
        if not self.account_id.reconcile:
            return
        amount = abs(amount)
        residual = self.amount_residual
        if residual > 0:
            new_res = residual - amount
        else:
            new_res = residual + amount
        vals = {
            'amount_residual': new_res,
            'reconciled': float_is_zero(new_res, precision_digits=2),
        }
        if full_reconcile:
            vals['full_reconcile_id'] = full_reconcile.id
        if matching_number:
            vals['matching_number'] = matching_number
        self.with_context(
            vas_allow_reconcile_write=True,
            vas_allow_posted_write=True,
            vas_skip_period_check=True,
        ).write(vals)


    def unlink(self):
        for line in self:
            if line.move_id.state == 'posted' and not self.env.context.get('vas_allow_posted_write'):
                raise UserError(_(
                    "Posted move %(name)s is immutable. Use Reverse Entry instead.",
                    name=line.move_id.name,
                ))
            if not self.env.context.get('vas_skip_period_check'):
                move = line.move_id
                self.env['vas.period']._assert_date_writable(
                    move.company_id,
                    move.date,
                    doc_name=move.name,
                    allow_missing=(move.state == 'draft'),
                )
        return super().unlink()

    def _check_parent_editable(self):
        for line in self:
            move = line.move_id
            if move.state == 'posted' and not self.env.context.get('vas_allow_posted_write'):
                raise UserError(_(
                    "Posted move %(name)s is immutable. Use Reverse Entry instead.",
                    name=move.name,
                ))
            if not self.env.context.get('vas_skip_period_check'):
                self.env['vas.period']._assert_date_writable(
                    move.company_id,
                    move.date,
                    doc_name=move.name,
                    allow_missing=(move.state == 'draft'),
                )
