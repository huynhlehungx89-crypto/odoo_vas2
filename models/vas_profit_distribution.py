# -*- coding: utf-8 -*-
"""W7 — phân phối lợi nhuận / trích quỹ (R30, V10+V11-2)."""
from odoo import _, api, fields, models, Command
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare, float_is_zero, float_round


class VasProfitDistribution(models.Model):
    _name = 'vas.profit.distribution'
    _description = 'Phân phối LN / trích quỹ (VAS)'
    _order = 'date desc, id desc'

    name = fields.Char(string='Số chứng từ', required=True, copy=False, default='/')
    company_id = fields.Many2one(
        'res.company', required=True, index=True,
        default=lambda self: self.env.company,
    )
    regime_id = fields.Many2one(
        'vas.regime', required=True,
        default=lambda self: self.env.company.vas_regime_id,
    )
    date = fields.Date(
        required=True, index=True,
        default=fields.Date.context_today,
    )
    fiscalyear_id = fields.Many2one('vas.fiscalyear', string='Năm tài chính')
    period_id = fields.Many2one(
        'vas.period', string='Kỳ',
        compute='_compute_period_id', store=True,
    )
    source_account_id = fields.Many2one(
        'vas.account', string='Nguồn (4211)', required=True,
    )
    amount_total = fields.Monetary(
        compute='_compute_amount_total', store=True,
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        'res.currency', required=True,
        default=lambda self: self.env.ref('base.VND'),
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Nháp'),
            ('posted', 'Đã ghi sổ'),
            ('cancelled', 'Đã hủy'),
        ],
        default='draft', required=True, index=True, copy=False,
    )
    line_ids = fields.One2many(
        'vas.profit.distribution.line', 'distribution_id', string='Dòng',
        copy=True,
    )
    move_id = fields.Many2one('vas.move', copy=False, readonly=True)
    ref = fields.Char(string='Diễn giải')

    @api.depends('date', 'company_id')
    def _compute_period_id(self):
        Period = self.env['vas.period']
        for rec in self:
            if not rec.date:
                rec.period_id = False
                continue
            domain = [
                ('date_start', '<=', rec.date),
                ('date_end', '>=', rec.date),
            ]
            if rec.company_id:
                domain.append(
                    ('fiscalyear_id.company_id', '=', rec.company_id.id)
                )
            rec.period_id = Period.search(domain, limit=1)

    @api.depends('line_ids.amount_gross')
    def _compute_amount_total(self):
        for rec in self:
            rec.amount_total = sum(rec.line_ids.mapped('amount_gross'))

    def action_post(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Chỉ phiếu nháp mới ghi sổ được.'))
            if not rec.line_ids:
                raise UserError(_('Cần ít nhất một dòng phân phối.'))
            if float_is_zero(rec.amount_total, precision_digits=0):
                raise UserError(_('Tổng phân phối phải > 0.'))
            for line in rec.line_ids:
                line._prepare_amounts()
            move = rec._create_vas_move()
            if rec.name == '/':
                rec.name = 'PP/%s/%s' % (rec.date, rec.id)
            rec.write({'state': 'posted', 'move_id': move.id})
        return True

    def _create_vas_move(self):
        self.ensure_one()
        journal = self.env['vas.journal'].search([
            ('company_id', '=', self.company_id.id),
            ('code', '=', 'TH'),
        ], limit=1)
        if not journal:
            raise UserError(_('Thiếu sổ nhật ký VAS (TH).'))

        existing = self.env['vas.move'].search([
            ('source_model', '=', self._name),
            ('source_res_id', '=', self.id),
            ('move_kind', '=', 'profit_distribution'),
            ('is_reversal', '=', False),
            ('state', 'not in', ('reversed', 'cancelled')),
        ], limit=1)
        if existing:
            return existing

        # Gom theo tài khoản: Nợ 4211 tổng; Có 3388/3335/418…
        debit_total = 0.0
        credit_buckets = {}  # account_id -> (amount, partner_id)

        def _add_credit(account, amount, partner=False):
            if float_is_zero(amount, precision_digits=0):
                return
            key = (account.id, partner.id if partner else False)
            prev = credit_buckets.get(key)
            if prev:
                credit_buckets[key] = (prev[0] + amount, partner)
            else:
                credit_buckets[key] = (amount, partner)

        tax_acc = self.env['vas.account'].search([
            ('regime_id', '=', self.regime_id.id), ('code', '=', '3335'),
        ], limit=1)

        for line in self.line_ids:
            debit_total += line.amount_gross
            if line.line_type == 'dividend':
                dest = line.dest_account_id
                if not dest:
                    dest = self.env['vas.account'].search([
                        ('regime_id', '=', self.regime_id.id),
                        ('code', '=', '3388'),
                    ], limit=1)
                if not dest:
                    raise UserError(_('Thiếu TK 3388 cho cổ tức.'))
                _add_credit(dest, line.amount_net, line.partner_id)
                if not float_is_zero(line.amount_tax, precision_digits=0):
                    if not tax_acc:
                        raise UserError(_('Thiếu TK 3335 (TNCN).'))
                    _add_credit(tax_acc, line.amount_tax, line.partner_id)
            else:
                # fund — V11-2 only (V11-3 park)
                dest = line.dest_account_id
                if not dest:
                    dest = self.env['vas.account'].search([
                        ('regime_id', '=', self.regime_id.id),
                        ('code', '=', '418'),
                    ], limit=1)
                if not dest:
                    raise UserError(_('Thiếu TK đích quỹ (418).'))
                _add_credit(dest, line.amount_gross, False)

        cmds = [
            Command.create({
                'sequence': 10,
                'account_id': self.source_account_id.id,
                'name': self.ref or self.name,
                'debit': debit_total,
                'credit': 0.0,
                'currency_id': self.currency_id.id,
            }),
        ]
        seq = 20
        for (_acc_id, _pid), (amt, partner) in credit_buckets.items():
            acc = self.env['vas.account'].browse(_acc_id)
            cmds.append(Command.create({
                'sequence': seq,
                'account_id': acc.id,
                'name': self.ref or self.name,
                'debit': 0.0,
                'credit': amt,
                'currency_id': self.currency_id.id,
                'partner_id': partner.id if partner else False,
            }))
            seq += 10

        move = self.env['vas.move'].create({
            'date': self.date,
            'journal_id': journal.id,
            'regime_id': self.regime_id.id,
            'move_kind': 'profit_distribution',
            'ref': self.ref or self.name,
            'source_model': self._name,
            'source_res_id': self.id,
            'source_ref': self.name,
            'company_id': self.company_id.id,
            'currency_id': self.currency_id.id,
            'line_ids': cmds,
        })
        move.action_post()
        return move

    def action_cancel(self):
        for rec in self:
            if rec.state == 'cancelled':
                continue
            move = rec.move_id
            if move and move.state not in ('reversed', 'cancelled'):
                if self.env['vas.period']._date_in_closed_period(
                    move.company_id, move.date,
                ):
                    move.with_context(
                        vas_allow_posted_write=True,
                        vas_skip_period_check=True,
                    ).write({'source_cancel_pending': True})
                else:
                    move.action_reverse()
            rec.state = 'cancelled'
        return True


class VasProfitDistributionLine(models.Model):
    _name = 'vas.profit.distribution.line'
    _description = 'Dòng phân phối LN / quỹ'
    _order = 'distribution_id, id'

    distribution_id = fields.Many2one(
        'vas.profit.distribution', required=True, ondelete='cascade', index=True,
    )
    line_type = fields.Selection(
        selection=[
            ('dividend', 'Cổ tức / LN trả CSH'),
            ('fund', 'Trích quỹ'),
        ],
        required=True, default='dividend',
    )
    partner_id = fields.Many2one('res.partner', string='Chủ sở hữu')
    amount_gross = fields.Monetary(required=True, currency_field='currency_id')
    withholding_rate = fields.Float(
        string='% TNCN',
        help='Tỷ lệ khấu trừ TNCN trên cổ tức (vd 0.05 = 5%).',
    )
    amount_tax = fields.Monetary(currency_field='currency_id')
    amount_net = fields.Monetary(currency_field='currency_id')
    dest_account_id = fields.Many2one(
        'vas.account', string='TK đích (3388/418/…)',
    )
    currency_id = fields.Many2one(related='distribution_id.currency_id')

    @api.onchange('amount_gross', 'withholding_rate', 'line_type')
    def _onchange_amounts(self):
        for line in self:
            line._prepare_amounts()

    def _prepare_amounts(self):
        for line in self:
            gross = line.amount_gross or 0.0
            if line.line_type == 'fund':
                line.amount_tax = 0.0
                line.amount_net = gross
                continue
            rate = line.withholding_rate or 0.0
            tax = float_round(gross * rate, precision_digits=0)
            line.amount_tax = tax
            line.amount_net = float_round(gross - tax, precision_digits=0)
