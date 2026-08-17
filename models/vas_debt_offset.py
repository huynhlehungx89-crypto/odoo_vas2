# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare, float_is_zero


class VasDebtOffset(models.Model):
    _name = 'vas.debt.offset'
    _inherit = ['vas.cash.flow.activity.mixin']
    _description = 'Phiếu bù trừ công nợ VAS (R22)'
    _order = 'date desc, id desc'

    name = fields.Char(string='Số phiếu', required=True, copy=False, default='/')
    partner_id = fields.Many2one(
        'res.partner', string='Đối tác', required=True, index=True,
        help='Cùng đối tác vừa có dư 131 vừa có dư 331.',
    )
    date = fields.Date(string='Ngày', required=True, default=fields.Date.context_today, index=True)
    period_id = fields.Many2one('vas.period', string='Kỳ', compute='_compute_period_id', store=True)
    regime_id = fields.Many2one(
        'vas.regime', string='Chế độ', required=True,
        default=lambda self: self.env.company.vas_regime_id,
    )
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company, index=True,
    )
    state = fields.Selection([
        ('draft', 'Nháp'),
        ('posted', 'Đã ghi sổ'),
        ('reversed', 'Đã đảo'),
        ('cancelled', 'Đã hủy'),
    ], default='draft', required=True, copy=False, index=True)
    ref = fields.Char(string='Diễn giải')
    line_ids = fields.One2many('vas.debt.offset.line', 'offset_id', string='Dòng chi tiết', copy=True)
    move_id = fields.Many2one('vas.move', string='Bút toán VAS', copy=False, readonly=True)
    amount_receivable = fields.Monetary(
        string='Tổng bù phải thu', compute='_compute_totals', currency_field='currency_id',
    )
    amount_payable = fields.Monetary(
        string='Tổng bù phải trả', compute='_compute_totals', currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.ref('base.VND'), required=True,
    )

    @api.depends('date', 'company_id')
    def _compute_period_id(self):
        Period = self.env['vas.period']
        for rec in self:
            if not rec.date:
                rec.period_id = False
                continue
            domain = [('date_start', '<=', rec.date), ('date_end', '>=', rec.date)]
            if rec.company_id:
                domain.append(('fiscalyear_id.company_id', '=', rec.company_id.id))
            rec.period_id = Period.search(domain, limit=1)

    @api.depends('line_ids.amount', 'line_ids.side')
    def _compute_totals(self):
        for rec in self:
            rec.amount_receivable = sum(
                l.amount for l in rec.line_ids if l.side == 'receivable'
            )
            rec.amount_payable = sum(
                l.amount for l in rec.line_ids if l.side == 'payable'
            )

    @api.constrains('line_ids')
    def _check_balanced_offset(self):
        for rec in self:
            if not rec.line_ids:
                continue
            if float_compare(rec.amount_receivable, rec.amount_payable, precision_digits=2) != 0:
                raise ValidationError(_(
                    "Tổng bù phải thu (%(recv)s) phải bằng tổng bù phải trả (%(pay)s).",
                    recv=rec.amount_receivable, pay=rec.amount_payable,
                ))

    def action_post(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_("Chỉ phiếu nháp mới ghi sổ được."))
            if not rec.line_ids:
                raise UserError(_("Cần ít nhất một dòng bù trừ."))
            if float_is_zero(rec.amount_receivable, precision_digits=2):
                raise UserError(_("Số tiền bù trừ phải > 0."))
            if float_compare(rec.amount_receivable, rec.amount_payable, precision_digits=2) != 0:
                raise UserError(_("Tổng bù phải thu phải bằng tổng bù phải trả."))
            for line in rec.line_ids:
                line._check_amount_vs_residual()
            move = rec._create_vas_move()
            full = rec.env['vas.full.reconcile'].create({
                'name': rec.name if rec.name != '/' else f'OFFSET/{rec.id}',
            })
            matching = full.name
            for line in rec.line_ids:
                line.move_line_id._vas_apply_match(
                    line.amount, full_reconcile=full, matching_number=matching,
                )
            if rec.name == '/':
                rec.name = f'BT/{rec.date}/{rec.id}'
            rec.write({'state': 'posted', 'move_id': move.id})
        return True

    def _create_vas_move(self):
        self.ensure_one()
        amount = self.amount_receivable
        acc_331 = self.env['vas.account'].search([
            ('regime_id', '=', self.regime_id.id), ('code', '=', '331'),
        ], limit=1)
        acc_131 = self.env['vas.account'].search([
            ('regime_id', '=', self.regime_id.id), ('code', '=', '131'),
        ], limit=1)
        if not acc_331 or not acc_131:
            raise UserError(_("Thiếu tài khoản VAS 131/331."))
        journal = self.env['vas.journal'].search([
            ('company_id', '=', self.company_id.id),
            ('code', '=', 'THU'),
        ], limit=1)
        if not journal:
            raise UserError(_("Thiếu sổ nhật ký VAS THU."))
        from odoo import Command
        move = self.env['vas.move'].create({
            'date': self.date,
            'journal_id': journal.id,
            'regime_id': self.regime_id.id,
            'move_kind': 'debt_offset',
            'ref': self.ref or _('Bù trừ công nợ %s') % (self.partner_id.display_name,),
            'source_model': self._name,
            'source_res_id': self.id,
            'source_ref': self.display_name,
            'company_id': self.company_id.id,
            'currency_id': self.currency_id.id,
            'line_ids': [
                Command.create({
                    'sequence': 10,
                    'account_id': acc_331.id,
                    'name': self.ref or _('Bù trừ'),
                    'debit': amount,
                    'credit': 0.0,
                    'partner_id': self.partner_id.id,
                    'currency_id': self.currency_id.id,
                }),
                Command.create({
                    'sequence': 20,
                    'account_id': acc_131.id,
                    'name': self.ref or _('Bù trừ'),
                    'debit': 0.0,
                    'credit': amount,
                    'partner_id': self.partner_id.id,
                    'currency_id': self.currency_id.id,
                }),
            ],
        })
        move.action_post()
        return move

    def action_reverse(self):
        self.ensure_one()
        if self.state != 'posted' or not self.move_id:
            raise UserError(_("Chỉ phiếu đã ghi sổ mới đảo được."))
        move = self.move_id
        Period = self.env['vas.period']
        status = Period._coverage_status(move.company_id, move.date)
        if status == 'closed':
            move.with_context(
                vas_allow_posted_write=True,
                vas_skip_period_check=True,
            ).write({'source_cancel_pending': True})
            return True
        if status == 'missing':
            Period._raise_missing_period(
                move.company_id, move.date, doc_name=move.name,
            )
        move.action_reverse()
        self._restore_offset_residuals()
        self.state = 'reversed'
        return True

    def action_cancel(self):
        """Hủy nghiệp vụ phiếu → cancelled + đảo JE (hoặc cờ khi kỳ khóa)."""
        Period = self.env['vas.period']
        for rec in self:
            if rec.state != 'posted':
                raise UserError(_("Chỉ phiếu đã ghi sổ mới hủy được."))
            if rec.move_id and rec.move_id.state == 'posted':
                move = rec.move_id
                status = Period._coverage_status(move.company_id, move.date)
                if status == 'closed':
                    move.with_context(
                        vas_allow_posted_write=True,
                        vas_skip_period_check=True,
                    ).write({'source_cancel_pending': True})
                elif status == 'missing':
                    Period._raise_missing_period(
                        move.company_id, move.date, doc_name=move.name,
                    )
                else:
                    move.action_reverse()
                    rec._restore_offset_residuals()
            rec.state = 'cancelled'
        return True

    def _restore_offset_residuals(self):
        """Hoàn residual sau khi đảo JE bù trừ."""
        self.ensure_one()
        for line in self.line_ids:
            ml = line.move_line_id
            if ml.debit:
                new_res = ml.amount_residual + line.amount
            else:
                new_res = ml.amount_residual - line.amount
            ml.with_context(
                vas_allow_reconcile_write=True,
                vas_allow_posted_write=True,
                vas_skip_period_check=True,
            ).write({
                'amount_residual': new_res,
                'reconciled': float_is_zero(new_res, precision_digits=2),
                'full_reconcile_id': False,
                'matching_number': False,
            })

    def write(self, vals):
        # Q7: cancelled là chốt — không reset về draft trên cùng id.
        if 'state' in vals and vals['state'] == 'draft':
            locked = self.filtered(lambda r: r.state == 'cancelled')
            if locked:
                raise UserError(_(
                    "Phiếu đã hủy không mở lại được. Tạo phiếu bù trừ mới."
                ))
        return super().write(vals)


class VasDebtOffsetLine(models.Model):
    _name = 'vas.debt.offset.line'
    _description = 'Dòng phiếu bù trừ công nợ VAS'
    _order = 'side, id'

    offset_id = fields.Many2one(
        'vas.debt.offset', required=True, ondelete='cascade', index=True,
    )
    side = fields.Selection([
        ('receivable', 'Phải thu (131)'),
        ('payable', 'Phải trả (331)'),
    ], required=True)
    move_line_id = fields.Many2one(
        'vas.move.line', string='Dòng công nợ VAS', required=True, ondelete='restrict',
        domain="[('partner_id', '=', partner_id), ('account_id.reconcile', '=', True)]",
    )
    partner_id = fields.Many2one(related='offset_id.partner_id', store=True)
    amount_residual = fields.Monetary(
        related='move_line_id.amount_residual', string='Số dư còn lại',
        currency_field='currency_id',
    )
    amount = fields.Monetary(string='Số tiền bù', required=True, currency_field='currency_id')
    currency_id = fields.Many2one(related='offset_id.currency_id')
    company_id = fields.Many2one(related='offset_id.company_id', store=True)

    @api.constrains('amount', 'move_line_id', 'side')
    def _check_amount_vs_residual(self):
        for line in self:
            if float_compare(line.amount, 0.0, precision_digits=2) <= 0:
                raise ValidationError(_("Số tiền bù phải > 0."))
            residual_abs = abs(line.move_line_id.amount_residual)
            if float_compare(line.amount, residual_abs, precision_digits=2) > 0:
                raise ValidationError(_(
                    "Số bù %(amt)s vượt số dư còn lại %(res)s trên dòng %(line)s.",
                    amt=line.amount, res=residual_abs, line=line.move_line_id.display_name,
                ))
            code = line.move_line_id.account_id.code or ''
            if line.side == 'receivable' and not code.startswith('131'):
                raise ValidationError(_("Dòng phải thu phải chọn tài khoản 131."))
            if line.side == 'payable' and not code.startswith('331'):
                raise ValidationError(_("Dòng phải trả phải chọn tài khoản 331."))
            if line.move_line_id.partner_id != line.offset_id.partner_id:
                raise ValidationError(_("Chỉ được chọn dòng cùng đối tác với phiếu."))
