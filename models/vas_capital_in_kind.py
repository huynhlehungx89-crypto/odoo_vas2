# -*- coding: utf-8 -*-
"""W7 V06 — góp vốn bằng hiện vật (chứng từ VAS, không đọc JE Odoo)."""
from odoo import _, api, fields, models, Command
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_is_zero


class VasCapitalInKind(models.Model):
    _name = 'vas.capital.in.kind'
    _description = 'Góp vốn bằng hiện vật (VAS)'
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Số chứng từ', required=True, copy=False, default='/',
    )
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
    period_id = fields.Many2one(
        'vas.period', string='Kỳ',
        compute='_compute_period_id', store=True,
    )
    partner_id = fields.Many2one(
        'res.partner', string='Đối tác góp vốn', index=True,
    )
    amount = fields.Monetary(required=True, currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency', required=True,
        default=lambda self: self.env.ref('base.VND'),
    )
    asset_account_id = fields.Many2one(
        'vas.account', string='TK tài sản nhận vào',
        help='Kế toán chọn thẳng TK tài sản. Trống = 2111 + cờ TK mặc định.',
    )
    equity_account_id = fields.Many2one(
        'vas.account', string='TK vốn (4111)',
        compute='_compute_equity_account', store=True, readonly=False,
    )
    ref = fields.Char(string='Diễn giải')
    spawn_asset = fields.Boolean(
        string='Sinh thẻ tài sản nháp',
        default=False,
        help='Khi bật: tạo vas.asset draft gắn chứng từ này.',
    )
    asset_name = fields.Char(string='Tên tài sản')
    asset_id = fields.Many2one(
        'vas.asset', string='Thẻ tài sản', copy=False, readonly=True,
    )
    move_id = fields.Many2one(
        'vas.move', string='Bút toán VAS', copy=False, readonly=True,
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Nháp'),
            ('posted', 'Đã ghi sổ'),
            ('cancelled', 'Đã hủy'),
        ],
        default='draft', required=True, index=True, copy=False,
    )

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

    @api.depends('regime_id')
    def _compute_equity_account(self):
        for rec in self:
            if not rec.regime_id:
                rec.equity_account_id = False
                continue
            rec.equity_account_id = self.env['vas.account'].search([
                ('regime_id', '=', rec.regime_id.id),
                ('code', '=', '4111'),
            ], limit=1)

    @api.constrains('spawn_asset', 'asset_name')
    def _check_asset_name(self):
        for rec in self:
            if rec.spawn_asset and not (rec.asset_name or '').strip():
                raise ValidationError(_(
                    'Khi chọn sinh thẻ tài sản phải nhập tên tài sản.'
                ))

    @api.constrains('amount')
    def _check_amount(self):
        for rec in self:
            if float_is_zero(rec.amount, precision_digits=2) or rec.amount < 0:
                raise ValidationError(_('Số tiền góp vốn phải > 0.'))

    def action_post(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Chỉ phiếu nháp mới ghi sổ được.'))
            if float_is_zero(rec.amount, precision_digits=2):
                raise UserError(_('Số tiền phải > 0.'))
            equity = rec.equity_account_id
            if not equity:
                equity = self.env['vas.account'].search([
                    ('regime_id', '=', rec.regime_id.id),
                    ('code', '=', '4111'),
                ], limit=1)
            if not equity:
                raise UserError(_('Thiếu TK 4111 (vốn góp).'))
            move = rec._create_vas_move(equity)
            asset = False
            if rec.spawn_asset:
                asset = rec._spawn_asset()
            vals = {'state': 'posted', 'move_id': move.id}
            if asset:
                vals['asset_id'] = asset.id
            if rec.name == '/':
                vals['name'] = 'GVHV/%s/%s' % (rec.date, rec.id)
            rec.write(vals)
        return True

    def _create_vas_move(self, equity_account):
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
            ('move_kind', '=', 'capital_receipt'),
            ('is_reversal', '=', False),
            ('state', 'not in', ('reversed', 'cancelled')),
        ], limit=1)
        if existing:
            return existing

        amount = self.amount
        label = self.ref or self.name
        fallbacks = []
        asset_acc = self.asset_account_id
        if not asset_acc:
            asset_acc = self.env['vas.account'].search([
                ('regime_id', '=', self.regime_id.id),
                ('code', '=', '2111'),
            ], limit=1)
            if asset_acc:
                fallbacks.append({
                    'label': _(
                        'phiếu góp vốn %(cap)s — chưa khai TK tài sản nhận vào, '
                        'dùng mặc định 2111',
                        cap=self.ref or self.name or ('#%s' % self.id),
                    ),
                })
        if not asset_acc:
            raise UserError(_('Thiếu TK tài sản nhận vào (và không có mặc định 2111).'))
        move = self.env['vas.move'].create({
            'date': self.date,
            'journal_id': journal.id,
            'regime_id': self.regime_id.id,
            'move_kind': 'capital_receipt',
            'ref': label,
            'source_model': self._name,
            'source_res_id': self.id,
            'source_ref': self.name,
            'company_id': self.company_id.id,
            'currency_id': self.currency_id.id,
            'line_ids': [
                Command.create({
                    'sequence': 10,
                    'account_id': asset_acc.id,
                    'name': label,
                    'debit': amount,
                    'credit': 0.0,
                    'currency_id': self.currency_id.id,
                    'partner_id': self.partner_id.id if self.partner_id else False,
                }),
                Command.create({
                    'sequence': 20,
                    'account_id': equity_account.id,
                    'name': label,
                    'debit': 0.0,
                    'credit': amount,
                    'currency_id': self.currency_id.id,
                    'partner_id': self.partner_id.id if self.partner_id else False,
                }),
            ],
            **self.env['vas.sync']._default_account_flag_vals(fallbacks),
        })
        move.action_post()
        return move

    def _spawn_asset(self):
        """Tạo vas.asset draft — KT nhập số năm KH rồi xác nhận."""
        self.ensure_one()
        if self.asset_id:
            return self.asset_id
        if 'vas.asset' not in self.env:
            return False
        regime = self.regime_id
        accum = self.env['vas.account'].search([
            ('regime_id', '=', regime.id), ('code', '=', '2141'),
        ], limit=1) or self.env['vas.account'].search([
            ('regime_id', '=', regime.id), ('code', '=', '214'),
        ], limit=1)
        expense = self.env['vas.account'].search([
            ('regime_id', '=', regime.id), ('code', '=', '6422'),
        ], limit=1)
        if not accum:
            raise UserError(_(
                'Thiếu TK 214 — không sinh được thẻ tài sản.'
            ))
        code = 'GVHV-%s' % self.id
        existing = self.env['vas.asset'].search([
            ('company_id', '=', self.company_id.id),
            ('code', '=', code),
        ], limit=1)
        if existing:
            return existing
        return self.env['vas.asset'].create({
            'code': code,
            'name': self.asset_name or self.ref or self.name,
            'company_id': self.company_id.id,
            'regime_id': regime.id,
            'asset_type': 'tscd',
            'original_value': self.amount,
            'date_start': self.date,
            'method': 'straight_line',
            'useful_life_years': 0.0,
            'account_gross_id': self.asset_account_id.id if self.asset_account_id else False,
            'account_accum_id': accum.id,
            'account_expense_id': False,
            'source_mode': 'manual',
            'state': 'draft',
            'warning_note': _(
                'Spawn từ góp vốn hiện vật %s — TK hao mòn mặc định 2141, '
                'TK chi phí chưa khai (sẽ dùng 6422 + cờ). KT nhập số năm KH '
                'và khai TK rồi xác nhận.',
                self.name,
            ),
        })

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
            if rec.asset_id and rec.asset_id.state == 'draft':
                rec.asset_id.write({'state': 'cancelled'})
            rec.state = 'cancelled'
        return True

    def action_reverse(self):
        """Đảo bút toán khi kỳ mở — cùng hành vi action_cancel trên posted."""
        return self.action_cancel()
