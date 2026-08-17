# -*- coding: utf-8 -*-
"""W7 — thẻ vay + lịch lãi (pattern pass-kỳ giống W8, pass riêng)."""
import logging
from datetime import timedelta

from odoo import _, api, fields, models, Command
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare, float_is_zero, float_round

_logger = logging.getLogger(__name__)

BASIS_DAYS = {
    'actual_365': 365,
    'actual_360': 360,
    '30_360': 360,
}


class VasLoan(models.Model):
    _name = 'vas.loan'
    _description = 'Thẻ vay (VAS)'
    _order = 'date_start desc, code, id'

    name = fields.Char(string='Tên', required=True)
    code = fields.Char(string='Mã', required=True, index=True)
    company_id = fields.Many2one(
        'res.company', required=True, index=True,
        default=lambda self: self.env.company,
    )
    regime_id = fields.Many2one(
        'vas.regime', string='Chế độ', required=True, index=True,
        default=lambda self: self.env.company.vas_regime_id,
    )
    partner_id = fields.Many2one('res.partner', string='Bên cho vay', index=True)
    date_start = fields.Date(string='Ngày bắt đầu', required=True)
    date_end = fields.Date(string='Ngày đáo hạn')
    principal = fields.Monetary(
        string='Gốc vay', required=True,
        help='Số gốc hợp đồng. Dư nợ = gốc − Σ trả gốc đã sync.',
    )
    currency_id = fields.Many2one(
        'res.currency', required=True,
        default=lambda self: self.env.ref('base.VND'),
    )
    term_type = fields.Selection(
        selection=[('short', 'Ngắn hạn'), ('long', 'Dài hạn')],
        default='short',
        help='Nhãn quản trị. TK vay: khai account_loan_id; trống = 3411 + cờ '
             '(không tự phân loại DH→NH).',
    )
    interest_rate = fields.Float(
        string='Lãi suất / năm', required=True,
        help='Ví dụ 0.12 = 12%/năm.',
    )
    day_count_basis = fields.Selection(
        selection=[
            ('actual_365', 'Actual/365'),
            ('actual_360', 'Actual/360'),
            ('30_360', '30/360'),
        ],
        default='actual_365', required=True,
    )
    interest_balance_mode = fields.Selection(
        selection=[
            ('accurate', 'Dư thực từng đoạn (tách khi trả giữa kỳ)'),
            ('period_start', 'Dư đầu kỳ cả tháng'),
        ],
        default='accurate', required=True,
        string='Cách lấy dư tính lãi',
    )
    account_loan_id = fields.Many2one(
        'vas.account', string='TK vay (3411)',
        help='Trống = 3411 + cờ dùng TK mặc định.',
    )
    account_interest_expense_id = fields.Many2one(
        'vas.account', string='TK chi phí lãi (635)',
        help='Trống = 635 + cờ dùng TK mặc định.',
    )
    account_interest_payable_id = fields.Many2one(
        'vas.account', string='TK lãi phải trả (335)',
        help='Trống = 335 + cờ dùng TK mặc định.',
    )
    capitalize_interest = fields.Boolean(string='Vốn hóa lãi → 241')
    capitalize_account_id = fields.Many2one('vas.account', string='TK vốn hóa (241)')
    capitalize_date_from = fields.Date(string='Vốn hóa từ')
    capitalize_date_to = fields.Date(string='Vốn hóa đến')
    journal_id = fields.Many2one('vas.journal', string='Sổ nhật ký')
    outstanding_principal = fields.Monetary(
        string='Dư gốc', compute='_compute_outstanding_principal',
        store=True, currency_field='currency_id',
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Nháp'),
            ('running', 'Đang chạy'),
            ('closed', 'Đã tất toán'),
            ('cancelled', 'Đã hủy'),
        ],
        default='draft', required=True, index=True, copy=False,
    )
    line_ids = fields.One2many('vas.loan.line', 'loan_id', string='Lịch lãi')
    disbursement_ids = fields.One2many(
        'vas.loan.disbursement', 'loan_id',
        string='Giải ngân trả thẳng NCC',
    )

    _sql_constraints = [
        (
            'code_company_uniq',
            'unique(code, company_id)',
            'Mã thẻ vay phải duy nhất trong công ty.',
        ),
    ]

    @api.depends('principal')
    def _compute_outstanding_principal(self):
        Move = self.env['vas.move']
        for loan in self:
            if not loan.id:
                loan.outstanding_principal = loan.principal
                continue
            repay_moves = Move.search([
                ('company_id', '=', loan.company_id.id),
                ('move_kind', '=', 'loan_repay'),
                ('is_reversal', '=', False),
                ('state', 'not in', ('reversed', 'cancelled')),
                ('source_model', '=', 'account.payment'),
            ])
            repaid = 0.0
            for move in repay_moves:
                payment = self.env['account.payment'].browse(move.source_res_id).exists()
                if payment and payment.vas_loan_id == loan:
                    repaid += abs(payment.amount)
            loan.outstanding_principal = float_round(
                loan.principal - repaid, precision_digits=0,
            )

    def _account_by_code(self, code):
        self.ensure_one()
        return self.env['vas.account'].search([
            ('regime_id', '=', self.regime_id.id),
            ('code', '=', code),
        ], limit=1)

    def _resolve_loan_account(self, fallbacks=None):
        self.ensure_one()
        if self.account_loan_id:
            return self.account_loan_id
        acc = self._account_by_code('3411')
        if fallbacks is not None:
            fallbacks.append({
                'label': _(
                    'khoản vay %(loan)s — chưa khai TK vay (kỳ hạn), dùng mặc định 3411',
                    loan='%s (%s)' % (self.code, self.name),
                ),
            })
        return acc

    def _resolve_interest_accounts(self, fallbacks=None):
        """(TK Nợ chi phí lãi hoặc 241, TK Có 335)."""
        self.ensure_one()
        expense = self.account_interest_expense_id
        if not expense:
            expense = self._account_by_code('635')
            if fallbacks is not None:
                fallbacks.append({
                    'label': _(
                        'khoản vay %(loan)s — chưa khai TK chi phí lãi, dùng mặc định 635',
                        loan='%s (%s)' % (self.code, self.name),
                    ),
                })
        payable = self.account_interest_payable_id
        if not payable:
            payable = self._account_by_code('335')
            if fallbacks is not None:
                fallbacks.append({
                    'label': _(
                        'khoản vay %(loan)s — chưa khai TK lãi phải trả, dùng mặc định 335',
                        loan='%s (%s)' % (self.code, self.name),
                    ),
                })
        return expense, payable

    def _default_journal(self):
        self.ensure_one()
        if self.journal_id:
            return self.journal_id
        return self.env['vas.journal'].search([
            ('company_id', '=', self.company_id.id),
            ('code', '=', 'TH'),
        ], limit=1)

    def _basis_denominator(self):
        self.ensure_one()
        return BASIS_DAYS.get(self.day_count_basis, 365)

    def _days_between(self, date_from, date_to):
        """Số ngày tính lãi trong [date_from, date_to] inclusive-exclusive end+1 style.

        Dùng số ngày lịch (date_to - date_from + 1) cho actual; 30/360 đơn giản.
        """
        self.ensure_one()
        if not date_from or not date_to or date_to < date_from:
            return 0
        if self.day_count_basis == '30_360':
            d1, d2 = date_from.day, date_to.day
            m1, m2 = date_from.month, date_to.month
            y1, y2 = date_from.year, date_to.year
            return (y2 - y1) * 360 + (m2 - m1) * 30 + (min(d2, 30) - min(d1, 30)) + 1
        return (date_to - date_from).days + 1

    def _repay_events(self):
        """[(date, amount)] trả gốc đã sync, sort theo ngày."""
        self.ensure_one()
        Move = self.env['vas.move']
        events = []
        moves = Move.search([
            ('company_id', '=', self.company_id.id),
            ('move_kind', '=', 'loan_repay'),
            ('is_reversal', '=', False),
            ('state', 'not in', ('reversed', 'cancelled')),
            ('source_model', '=', 'account.payment'),
        ])
        for move in moves:
            payment = self.env['account.payment'].browse(move.source_res_id).exists()
            if payment and payment.vas_loan_id == self:
                events.append((payment.date, abs(payment.amount)))
        events.sort(key=lambda e: (e[0], e[1]))
        return events

    def _balance_before(self, on_date):
        """Dư gốc ngay trước on_date (chưa trừ trả trong ngày on_date)."""
        self.ensure_one()
        repaid = sum(
            amt for d, amt in self._repay_events() if d < on_date
        )
        return float_round(self.principal - repaid, precision_digits=0)

    def compute_interest_for_period(self, period):
        """Tính lãi kỳ + metadata (không ghi DB).

        Default accurate: tách đoạn theo ngày trả gốc trong kỳ.
        """
        self.ensure_one()
        date_from = max(period.date_start, self.date_start)
        date_to = period.date_end
        if self.date_end:
            date_to = min(date_to, self.date_end)
        if date_to < date_from:
            return {
                'amount': 0.0, 'days': 0, 'principal_balance': 0.0,
                'is_capitalized': False, 'date_from': date_from, 'date_to': date_to,
            }

        rate = self.interest_rate
        basis = float(self._basis_denominator())
        start_balance = self._balance_before(date_from)
        days = self._days_between(date_from, date_to)

        if self.interest_balance_mode == 'period_start':
            amount = float_round(
                start_balance * rate * days / basis, precision_digits=0,
            )
        else:
            # accurate: mỗi ngày lãi trên dư thực; trả gốc cuối ngày → giảm dư ngày sau
            amount = 0.0
            bal = start_balance
            repay_map = {}
            for d, amt in self._repay_events():
                if date_from <= d <= date_to:
                    repay_map[d] = repay_map.get(d, 0.0) + amt
            cur = date_from
            while cur <= date_to:
                amount += bal * rate / basis
                if cur in repay_map:
                    bal = float_round(bal - repay_map[cur], precision_digits=0)
                cur += timedelta(days=1)
            amount = float_round(amount, precision_digits=0)

        is_cap = bool(
            self.capitalize_interest
            and self.capitalize_account_id
            and (not self.capitalize_date_from or date_to >= self.capitalize_date_from)
            and (not self.capitalize_date_to or date_from <= self.capitalize_date_to)
        )
        return {
            'amount': max(amount, 0.0),
            'days': days,
            'principal_balance': start_balance,
            'is_capitalized': is_cap,
            'date_from': date_from,
            'date_to': date_to,
        }

    def action_confirm(self):
        for loan in self:
            if loan.state != 'draft':
                raise UserError(_('Chỉ thẻ nháp mới xác nhận được.'))
            if float_compare(loan.principal, 0.0, precision_digits=0) <= 0:
                raise UserError(_('Gốc vay phải > 0.'))
            if loan.capitalize_interest and not loan.capitalize_account_id:
                raise UserError(_('Bật vốn hóa lãi cần chọn TK 241.'))
            with self.env.cr.savepoint():
                loan._build_schedule()
                loan.state = 'running'
        return True

    def _build_schedule(self):
        """Sinh lịch lãi — cấm cắt im lặng khi thiếu kỳ (chung đường với asset)."""
        self.ensure_one()
        self.line_ids.filtered(lambda l: l.state == 'planned').unlink()
        Period = self.env['vas.period']
        date_to = self.date_end or self.date_start
        Period._ensure_periods_covering_range(
            self.company_id,
            self.date_start,
            date_to,
            doc_name=self.display_name,
        )
        domain = [
            ('fiscalyear_id.company_id', '=', self.company_id.id),
            ('date_end', '>=', self.date_start),
        ]
        if self.date_end:
            domain.append(('date_start', '<=', self.date_end))
        periods = Period.search(domain, order='date_start')
        if not periods:
            Period._raise_missing_period(
                self.company_id, self.date_start, doc_name=self.display_name,
            )
        # Coverage continuity: first covers start, last covers end
        if periods[0].date_start > self.date_start or periods[0].date_end < self.date_start:
            Period._raise_missing_period(
                self.company_id, self.date_start, doc_name=self.display_name,
            )
        if self.date_end and (
            periods[-1].date_start > self.date_end or periods[-1].date_end < self.date_end
        ):
            Period._raise_missing_period(
                self.company_id, self.date_end, doc_name=self.display_name,
            )
        seq = 1
        for period in periods:
            info = self.compute_interest_for_period(period)
            if float_is_zero(info['amount'], precision_digits=0) and info['days'] <= 0:
                continue
            self.env['vas.loan.line'].create({
                'loan_id': self.id,
                'sequence': seq,
                'period_id': period.id,
                'date_from': info['date_from'],
                'date_to': info['date_to'],
                'date': info['date_to'],
                'days': info['days'],
                'principal_balance': info['principal_balance'],
                'amount': info['amount'],
                'is_capitalized': info['is_capitalized'],
                'state': 'planned',
            })
            seq += 1
        if seq == 1:
            raise UserError(_(
                'Không sinh được dòng lịch lãi cho «%(loan)s» '
                '(%(start)s → %(end)s). Kiểm tra ngày bắt đầu/đáo hạn và kỳ VAS.',
                loan=self.display_name,
                start=self.date_start,
                end=date_to,
            ))

    def action_recompute_planned_amounts(self):
        """Tính lại amount các line planned (sau trả gốc)."""
        for loan in self:
            for line in loan.line_ids.filtered(lambda l: l.state == 'planned'):
                info = loan.compute_interest_for_period(line.period_id)
                line.write({
                    'amount': info['amount'],
                    'days': info['days'],
                    'principal_balance': info['principal_balance'],
                    'is_capitalized': info['is_capitalized'],
                    'date_from': info['date_from'],
                    'date_to': info['date_to'],
                })
        return True

    def action_cancel(self):
        for loan in self:
            if loan.state in ('cancelled', 'closed'):
                continue
            for line in loan.line_ids.filtered(lambda l: l.state == 'planned'):
                line.state = 'skipped'
            for line in loan.line_ids.filtered(lambda l: l.state == 'posted'):
                move = line.move_id
                if not move or move.state in ('reversed', 'cancelled'):
                    line.state = 'skipped'
                    continue
                if self.env['vas.period']._date_in_closed_period(
                    move.company_id, move.date,
                ):
                    move.with_context(
                        vas_allow_posted_write=True,
                        vas_skip_period_check=True,
                    ).write({'source_cancel_pending': True})
                else:
                    move.action_reverse()
                    line.state = 'skipped'
            for disb in loan.disbursement_ids.filtered(
                lambda d: d.state == 'posted'
            ):
                disb.action_cancel()
            loan.state = 'cancelled'
        return True

    @api.model
    def generate_interest_entries(self, company, period):
        """Pass sinh lãi kỳ — RIÊNG khỏi generate_asset_entries."""
        if period.state == 'closed':
            raise UserError(_(
                'Kỳ %(p)s đã khóa — không sinh lãi vay.',
                p=period.display_name,
            ))
        loans = self.search([
            ('company_id', '=', company.id),
            ('state', '=', 'running'),
            ('date_start', '<=', period.date_end),
        ])
        stats = {'created': 0, 'skipped': 0, 'warnings': []}
        for loan in loans:
            # refresh planned amounts (split after mid-period repay)
            loan.action_recompute_planned_amounts()
            posted = loan.line_ids.filtered(
                lambda l: l.period_id == period and l.state == 'posted'
            )
            if posted:
                stats['skipped'] += 1
                continue
            skipped = loan.line_ids.filtered(
                lambda l: l.period_id == period and l.state == 'skipped'
            )
            if skipped:
                stats['skipped'] += 1
                continue
            line = loan.line_ids.filtered(
                lambda l: l.period_id == period and l.state == 'planned'
            )[:1]
            if not line:
                # maybe need to create line if schedule built before period existed
                info = loan.compute_interest_for_period(period)
                if float_is_zero(info['amount'], precision_digits=0):
                    stats['skipped'] += 1
                    continue
                line = self.env['vas.loan.line'].create({
                    'loan_id': loan.id,
                    'sequence': len(loan.line_ids) + 1,
                    'period_id': period.id,
                    'date_from': info['date_from'],
                    'date_to': info['date_to'],
                    'date': info['date_to'],
                    'days': info['days'],
                    'principal_balance': info['principal_balance'],
                    'amount': info['amount'],
                    'is_capitalized': info['is_capitalized'],
                    'state': 'planned',
                })
            move = loan._post_interest_line(line)
            if move:
                stats['created'] += 1
            else:
                stats['skipped'] += 1
        return stats

    def _post_interest_line(self, line):
        self.ensure_one()
        if line.state != 'planned':
            return self.env['vas.move']
        if line.move_id:
            return line.move_id
        if float_is_zero(line.amount, precision_digits=0):
            line.state = 'skipped'
            return self.env['vas.move']

        existing = self.env['vas.move'].search([
            ('source_model', '=', 'vas.loan.line'),
            ('source_res_id', '=', line.id),
            ('move_kind', '=', 'loan_interest'),
            ('is_reversal', '=', False),
            ('state', 'not in', ('reversed', 'cancelled')),
        ], limit=1)
        if existing:
            line.write({'move_id': existing.id, 'state': 'posted'})
            return existing

        fallbacks = []
        expense, credit_acc = self._resolve_interest_accounts(fallbacks)
        debit_acc = (
            self.capitalize_account_id if line.is_capitalized else expense
        )
        journal = self._default_journal()
        if not journal:
            raise UserError(_('Thiếu sổ nhật ký VAS (TH).'))

        amount = line.amount
        move = self.env['vas.move'].create({
            'date': line.date or line.period_id.date_end,
            'journal_id': journal.id,
            'regime_id': self.regime_id.id,
            'move_kind': 'loan_interest',
            'ref': _('%s — lãi %s') % (self.display_name, line.period_id.display_name),
            'source_model': 'vas.loan.line',
            'source_res_id': line.id,
            'source_ref': '%s/%s' % (self.code, line.period_id.name),
            'company_id': self.company_id.id,
            'currency_id': self.currency_id.id,
            'line_ids': [
                Command.create({
                    'sequence': 10, 'account_id': debit_acc.id,
                    'name': self.name, 'debit': amount, 'credit': 0.0,
                    'currency_id': self.currency_id.id,
                    'partner_id': self.partner_id.id,
                }),
                Command.create({
                    'sequence': 20, 'account_id': credit_acc.id,
                    'name': self.name, 'debit': 0.0, 'credit': amount,
                    'currency_id': self.currency_id.id,
                    'partner_id': self.partner_id.id,
                }),
            ],
            **self.env['vas.sync']._default_account_flag_vals(fallbacks),
        })
        move.action_post()
        line.write({'move_id': move.id, 'state': 'posted'})
        return move

    def action_generate_period_entries(self):
        for loan in self:
            periods = loan.line_ids.filtered(
                lambda l: l.state == 'planned' and l.period_id.state != 'closed'
            ).mapped('period_id')
            for period in periods:
                self.generate_interest_entries(loan.company_id, period)
        return True

    def skip_planned_interest_for_period(self, period, reason=''):
        """Auto-skip planned line khi loan_interest_pay_direct (WARN)."""
        for loan in self:
            lines = loan.line_ids.filtered(
                lambda l: l.period_id == period and l.state == 'planned'
            )
            for line in lines:
                line.state = 'skipped'
                msg = _(
                    'VAS: bỏ qua trích lãi %(loan)s kỳ %(p)s — đã trả lãi thẳng '
                    '(loan_interest_pay_direct). %(r)s',
                    loan=loan.display_name, p=period.display_name, r=reason or '',
                )
                _logger.warning(msg)
        return True


class VasLoanDisbursement(models.Model):
    """Sự kiện giải ngân vay trả thẳng NCC (V02) — gắn thẻ vay, không chứng từ độc lập."""
    _name = 'vas.loan.disbursement'
    _description = 'Giải ngân vay trả thẳng NCC'
    _order = 'date desc, id desc'

    loan_id = fields.Many2one(
        'vas.loan', required=True, ondelete='cascade', index=True,
    )
    date = fields.Date(
        required=True, index=True,
        default=fields.Date.context_today,
    )
    amount = fields.Monetary(required=True, currency_field='currency_id')
    partner_id = fields.Many2one(
        'res.partner', string='Nhà cung cấp', required=True, index=True,
    )
    ref = fields.Char(string='Diễn giải')
    currency_id = fields.Many2one(
        related='loan_id.currency_id', store=True, readonly=True,
    )
    company_id = fields.Many2one(
        related='loan_id.company_id', store=True, readonly=True,
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

    @api.constrains('amount')
    def _check_amount(self):
        for rec in self:
            if float_is_zero(rec.amount, precision_digits=2) or rec.amount < 0:
                raise ValidationError(_('Số tiền giải ngân phải > 0.'))

    def action_post(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Chỉ sự kiện nháp mới ghi sổ được.'))
            if rec.loan_id.state not in ('running', 'draft'):
                raise UserError(_(
                    'Thẻ vay phải ở trạng thái nháp hoặc đang chạy.'
                ))
            if float_is_zero(rec.amount, precision_digits=2):
                raise UserError(_('Số tiền phải > 0.'))
            move = rec._create_vas_move()
            rec.write({'state': 'posted', 'move_id': move.id})
        return True

    def _create_vas_move(self):
        self.ensure_one()
        loan = self.loan_id
        existing = self.env['vas.move'].search([
            ('source_model', '=', self._name),
            ('source_res_id', '=', self.id),
            ('move_kind', '=', 'loan_disburse'),
            ('is_reversal', '=', False),
            ('state', 'not in', ('reversed', 'cancelled')),
        ], limit=1)
        if existing:
            return existing

        debit = self.env['vas.account'].search([
            ('regime_id', '=', loan.regime_id.id),
            ('code', '=', '331'),
        ], limit=1)
        fallbacks = []
        credit = loan._resolve_loan_account(fallbacks)
        if not debit:
            raise UserError(_('Thiếu TK 331 (phải trả NCC).'))
        if not credit:
            raise UserError(_('Thiếu TK vay (và không có mặc định 3411).'))
        journal = loan._default_journal()
        if not journal:
            raise UserError(_('Thiếu sổ nhật ký VAS (TH).'))

        amount = self.amount
        label = self.ref or _('Giải ngân %s → %s') % (
            loan.display_name, self.partner_id.display_name,
        )
        move = self.env['vas.move'].create({
            'date': self.date,
            'journal_id': journal.id,
            'regime_id': loan.regime_id.id,
            'move_kind': 'loan_disburse',
            'ref': label,
            'source_model': self._name,
            'source_res_id': self.id,
            'source_ref': '%s/GN/%s' % (loan.code, self.id or 'new'),
            'company_id': loan.company_id.id,
            'currency_id': loan.currency_id.id,
            'line_ids': [
                Command.create({
                    'sequence': 10,
                    'account_id': debit.id,
                    'name': label,
                    'debit': amount,
                    'credit': 0.0,
                    'currency_id': loan.currency_id.id,
                    'partner_id': self.partner_id.id,
                }),
                Command.create({
                    'sequence': 20,
                    'account_id': credit.id,
                    'name': label,
                    'debit': 0.0,
                    'credit': amount,
                    'currency_id': loan.currency_id.id,
                    'partner_id': self.partner_id.id,
                }),
            ],
            **self.env['vas.sync']._default_account_flag_vals(fallbacks),
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

    def action_reverse(self):
        return self.action_cancel()


class VasLoanLine(models.Model):
    _name = 'vas.loan.line'
    _description = 'Dòng lịch lãi vay'
    _order = 'loan_id, sequence, id'

    loan_id = fields.Many2one(
        'vas.loan', required=True, ondelete='cascade', index=True,
    )
    sequence = fields.Integer(default=1)
    period_id = fields.Many2one('vas.period', required=True, index=True)
    date_from = fields.Date()
    date_to = fields.Date()
    date = fields.Date(string='Ngày ghi')
    days = fields.Integer()
    principal_balance = fields.Monetary(currency_field='currency_id')
    amount = fields.Monetary(currency_field='currency_id')
    is_capitalized = fields.Boolean()
    state = fields.Selection(
        selection=[
            ('planned', 'Kế hoạch'),
            ('posted', 'Đã ghi'),
            ('skipped', 'Bỏ qua'),
        ],
        default='planned', required=True, index=True,
    )
    move_id = fields.Many2one('vas.move', ondelete='set null', copy=False)
    currency_id = fields.Many2one(related='loan_id.currency_id')
    company_id = fields.Many2one(related='loan_id.company_id', store=True)

    _sql_constraints = [
        (
            'loan_period_uniq',
            'unique(loan_id, period_id)',
            'Mỗi kỳ chỉ một dòng lãi trên một thẻ vay.',
        ),
    ]
