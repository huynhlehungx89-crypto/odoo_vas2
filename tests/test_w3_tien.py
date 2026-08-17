# -*- coding: utf-8 -*-
"""W3 — Tiền & công nợ: chấm T03/T06/T07/T08/T10/M10/B09.

R19/R20/R21 dùng chung nhãn ``account.payment.vas_operation_type``.
R22 (bù trừ) đã chuyển sang ``vas.debt.offset`` — xem test_post_w4_fixes.
"""
from collections import defaultdict

from odoo import Command, fields
from odoo.tests import tagged, TransactionCase
from odoo.tools import float_compare


@tagged('connecta_vas', 'connecta_vas_w3')
class TestW3Tien(TransactionCase):
    AMOUNT = 1_000_000.0
    DISCOUNT = 20_000.0
    INVOICE = 100_000.0
    PAID = 98_000.0  # INVOICE - 2% style; tests use INVOICE=100k, discount=2k

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.vnd = cls.env.ref('base.VND')
        if cls.company.currency_id != cls.vnd:
            cls.company.currency_id = cls.vnd

        cls.regime = cls.env['vas.regime'].search([('code', '=', 'TT133')], limit=1)
        if not cls.regime:
            cls.regime = cls.env['vas.regime'].create({
                'code': 'TT133',
                'name': 'Thông tư 133/2016/TT-BTC',
            })
        cls.company.vas_regime_id = cls.regime
        cls.company.vas_start_date = '2000-01-01'
        cls._ensure_w3_rules()

        fy = cls.env['vas.fiscalyear'].search([
            ('company_id', '=', cls.company.id),
            ('date_from', '<=', '2099-04-15'),
            ('date_to', '>=', '2099-04-15'),
        ], limit=1)
        if not fy:
            fy = cls.env['vas.fiscalyear'].create({
                'name': '2099',
                'date_from': '2099-01-01',
                'date_to': '2099-12-31',
                'state': 'open',
                'company_id': cls.company.id,
            })
        if not fy.period_ids:
            fy.action_generate_periods()
        else:
            fy.period_ids.write({'state': 'open'})

        cls.bank_journal = cls._journal('bank', 'W3BK', 'W3 Bank')
        cls.cash_journal = cls._journal('cash', 'W3CS', 'W3 Cash')
        cls.sale_journal = cls._journal('sale', 'W3SL', 'W3 Sale')
        cls.purchase_journal = cls._journal('purchase', 'W3PU', 'W3 Purchase')

        # Employee + work contact for R19 FALLBACK
        cls.emp_partner = cls.env['res.partner'].create({
            'name': 'NV W3 Advance',
            'company_id': cls.company.id,
        })
        cls.employee = cls.env['hr.employee'].create({
            'name': 'NV W3 Advance',
            'company_id': cls.company.id,
            'work_contact_id': cls.emp_partner.id,
        })

        cls.writeoff_income = cls.env['account.account'].search([
            ('company_ids', 'in', cls.company.id),
            ('account_type', 'in', ('income_other', 'income')),
        ], limit=1)
        cls.writeoff_expense = cls.env['account.account'].search([
            ('company_ids', 'in', cls.company.id),
            ('account_type', '=', 'expense'),
        ], limit=1)

    @classmethod
    def _journal(cls, jtype, code, name):
        """Sổ Odoo theo loại; tự tạo nếu DB chưa có (DB sạch không demo data)."""
        Journal = cls.env['account.journal']
        journal = Journal.search([
            ('company_id', '=', cls.company.id), ('type', '=', jtype),
        ], limit=1)
        if not journal:
            journal = Journal.create({
                'name': name,
                'code': code,
                'type': jtype,
                'company_id': cls.company.id,
            })
        return journal

    @classmethod
    def _ensure_w3_rules(cls):
        Rule = cls.env['vas.rule']
        regime = cls.company.vas_regime_id
        specs = {
            'R19': {
                'event_type': 'advance_employee',
                'condition': '[("payment_type", "=", "outbound")]',
                'sequence': 55,
                'name': 'Tạm ứng NLĐ (chi)',
                'lines': [
                    ('debit', 'employee_advance', 'paid'),
                    ('credit', 'bank_cash', 'paid'),
                ],
            },
            'R19b': {
                'event_type': 'advance_employee',
                'condition': '[("payment_type", "=", "inbound")]',
                'sequence': 56,
                'name': 'Hoàn tạm ứng',
                'lines': [
                    ('debit', 'bank_cash', 'paid'),
                    ('credit', 'employee_advance', 'paid'),
                ],
            },
            'R20': {
                'event_type': 'cash_transfer',
                'condition': False,
                'sequence': 45,
                'name': 'Nộp/rút quỹ',
                'lines': [
                    ('debit', 'dest_bank_cash', 'paid'),
                    ('credit', 'bank_cash', 'paid'),
                ],
            },
            'R21a': {
                'event_type': 'deposit',
                'condition': '[("vas_operation_type", "=", "deposit_out"),'
                             ' ("payment_type", "=", "outbound")]',
                'sequence': 57,
                'name': 'Chi tiền ký quỹ mang đi',
                'lines': [
                    ('debit', 'fixed', 'paid', '1386'),
                    ('credit', 'bank_cash', 'paid'),
                ],
            },
            'R21b': {
                'event_type': 'deposit',
                'condition': '[("vas_operation_type", "=", "deposit_out"),'
                             ' ("payment_type", "=", "inbound")]',
                'sequence': 58,
                'name': 'Nhận lại tiền ký quỹ mang đi',
                'lines': [
                    ('debit', 'bank_cash', 'paid'),
                    ('credit', 'fixed', 'paid', '1386'),
                ],
            },
            'R21c': {
                'event_type': 'deposit',
                'condition': '[("vas_operation_type", "=", "deposit_in"),'
                             ' ("payment_type", "=", "inbound")]',
                'sequence': 59,
                'name': 'Nhận ký quỹ, ký cược của đối tác',
                'lines': [
                    ('debit', 'bank_cash', 'paid'),
                    ('credit', 'fixed', 'paid', '3386'),
                ],
            },
            'R21d': {
                'event_type': 'deposit',
                'condition': '[("vas_operation_type", "=", "deposit_in"),'
                             ' ("payment_type", "=", "outbound")]',
                'sequence': 60,
                'name': 'Hoàn trả ký quỹ, ký cược đã nhận',
                'lines': [
                    ('debit', 'fixed', 'paid', '3386'),
                    ('credit', 'bank_cash', 'paid'),
                ],
            },
            'R23a': {
                'event_type': 'payment_discount',
                'condition': '[("payment_type", "=", "outbound")]',
                'sequence': 65,
                'name': 'Chiết khấu thanh toán được hưởng (mua)',
                'lines': [
                    ('debit', 'partner_payable', 'discount'),
                    ('credit', 'finance_income', 'discount'),
                ],
            },
            'R23b': {
                'event_type': 'payment_discount',
                'condition': '[("payment_type", "=", "inbound")]',
                'sequence': 66,
                'name': 'Chiết khấu thanh toán cho khách (bán)',
                'lines': [
                    ('debit', 'finance_expense', 'discount'),
                    ('credit', 'partner_receivable', 'discount'),
                ],
            },
        }
        Account = cls.env['vas.account']
        for code, spec in specs.items():
            if Rule.search([('regime_id', '=', regime.id), ('code', '=', code)], limit=1):
                continue
            line_cmds = []
            for i, line in enumerate(spec['lines']):
                side, sel, amt = line[0], line[1], line[2]
                line_vals = {
                    'sequence': (i + 1) * 10,
                    'side': side,
                    'account_selector': sel,
                    'amount_selector': amt,
                }
                if sel == 'fixed':
                    acc = Account.search([
                        ('regime_id', '=', regime.id), ('code', '=', line[3]),
                    ], limit=1)
                    assert acc, f'Missing VAS account {line[3]} for rule {code}'
                    line_vals['account_id'] = acc.id
                line_cmds.append(Command.create(line_vals))
            vals = {
                'code': code,
                'name': spec['name'],
                'regime_id': regime.id,
                'event_type': spec['event_type'],
                'sequence': spec['sequence'],
                'active': True,
                'line_ids': line_cmds,
            }
            if spec['condition']:
                vals['condition'] = spec['condition']
            Rule.create(vals)

    def _sync(self):
        return self.env['vas.sync'].sync_company(
            self.company, date_from='2099-01-01', date_to='2099-12-31',
        )

    def _vas_for_payments(self, *payments):
        Move = self.env['vas.move']
        moves = Move
        for p in payments:
            moves |= Move.search([
                ('source_model', '=', 'account.payment'),
                ('source_res_id', '=', p.id),
                ('state', '=', 'posted'),
            ])
        return moves

    def _net(self, moves):
        bal = defaultdict(float)
        for line in moves.mapped('line_ids'):
            bal[line.account_id.code] += line.debit - line.credit
        return {k: round(v, 2) for k, v in bal.items()}

    def _grade(self, scenario, moves, expected):
        bal = self._net(moves)
        lines = []
        for move in moves.sorted(lambda m: (m.date, m.id)):
            for line in move.line_ids.sorted('sequence'):
                lines.append(
                    f"  {move.move_kind} {move.name}: "
                    f"{line.account_id.code} N={line.debit} C={line.credit}"
                )
        diffs = []
        for code, exp in expected.items():
            got = bal.get(code, 0.0)
            if float_compare(got, exp, precision_digits=2) != 0:
                diffs.append(f'{code}: got={got} expected={exp}')
        status = 'ĐẠT' if not diffs else 'LỆCH'
        print(
            f"\n=== {scenario}: {status} ===\n"
            f"Balances: {dict(sorted(bal.items()))}\n"
            f"Expected: {expected}\n"
            f"Lines:\n" + ('\n'.join(lines) if lines else '  (none)') + '\n'
            + (f"Diffs: {diffs}\n" if diffs else '')
        )
        return status, bal, diffs

    def test_w3_t03_tam_ung_nld(self):
        """T03: chi tạm ứng — Nợ 141 / Có 112 (FALLBACK R19)."""
        pmt = self.env['account.payment'].create({
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'partner_id': self.emp_partner.id,
            'amount': self.AMOUNT,
            'date': '2099-04-05',
            'journal_id': self.bank_journal.id,
            'company_id': self.company.id,
            'currency_id': self.vnd.id,
            'memo': 'W3-T03-advance',
            'vas_operation_type': 'employee_advance',
        })
        pmt.action_post()
        self._sync()
        moves = self._vas_for_payments(pmt)
        status, bal, diffs = self._grade('T03', moves, {
            '141': self.AMOUNT,
            '112': -self.AMOUNT,
        })
        self.assertEqual(status, 'ĐẠT', diffs)
        # Must NOT also book R18 (331)
        self.assertNotIn('331', bal)

    def _make_transfer(self, src_journal, dest_journal, date, memo):
        pmt = self.env['account.payment'].create({
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'amount': self.AMOUNT,
            'date': date,
            'journal_id': src_journal.id,
            'company_id': self.company.id,
            'currency_id': self.vnd.id,
            'memo': memo,
            'vas_operation_type': 'internal_transfer',
            'vas_dest_journal_id': dest_journal.id,
        })
        pmt.action_post()
        return pmt

    def test_w3_t06_nop_quy(self):
        """T06: nộp TM vào NH — MỘT payment quỹ→ngân hàng, Nợ 112 / Có 111."""
        pmt = self._make_transfer(
            self.cash_journal, self.bank_journal, '2099-04-06', 'W3-T06-transfer')
        self._sync()
        moves = self._vas_for_payments(pmt)
        self.assertEqual(len(moves), 1, moves.mapped('source_ref'))
        status, _bal, diffs = self._grade('T06', moves, {
            '112': self.AMOUNT,
            '111': -self.AMOUNT,
        })
        self.assertEqual(status, 'ĐẠT', diffs)

    def test_w3_t07_rut_quy(self):
        """T07: rút NH về TM — MỘT payment ngân hàng→quỹ, Nợ 111 / Có 112."""
        pmt = self._make_transfer(
            self.bank_journal, self.cash_journal, '2099-04-07', 'W3-T07-transfer')
        self._sync()
        moves = self._vas_for_payments(pmt)
        self.assertEqual(len(moves), 1)
        status, _bal, diffs = self._grade('T07', moves, {
            '111': self.AMOUNT,
            '112': -self.AMOUNT,
        })
        self.assertEqual(status, 'ĐẠT', diffs)

    def test_w3_t06_khong_gan_nhan_thi_khong_la_chuyen_quy(self):
        """Bỏ heuristic: 2 payment cùng ngày + cùng số tiền KHÔNG còn bị ghép cặp."""
        cash_out = self.env['account.payment'].create({
            'payment_type': 'outbound', 'partner_type': 'supplier',
            'partner_id': self.company.partner_id.id, 'amount': self.AMOUNT,
            'date': '2099-04-08', 'journal_id': self.cash_journal.id,
            'company_id': self.company.id, 'currency_id': self.vnd.id,
        })
        bank_in = self.env['account.payment'].create({
            'payment_type': 'inbound', 'partner_type': 'customer',
            'partner_id': self.company.partner_id.id, 'amount': self.AMOUNT,
            'date': '2099-04-08', 'journal_id': self.bank_journal.id,
            'company_id': self.company.id, 'currency_id': self.vnd.id,
        })
        (cash_out + bank_in).action_post()
        self._sync()
        moves = self._vas_for_payments(cash_out, bank_in)
        bal = self._net(moves)
        print(
            f"\n=== R20 no-heuristic: {len(moves)} bút toán, balances={bal} ===\n"
            "2 payment rời được xử như thu/chi thường (R17/R18), không ghép cặp.\n"
        )
        # Không có bút toán 111↔112 ghép cặp: mỗi payment đi đường R17/R18 riêng
        self.assertFalse(
            moves.filtered(lambda m: m.ref and 'Nộp/rút quỹ' in (m.ref or '')),
            'Heuristic ghép cặp vẫn còn chạy',
        )

    def _make_deposit(self, op_type, payment_type, date, memo, partner):
        pmt = self.env['account.payment'].create({
            'payment_type': payment_type,
            'partner_type': 'supplier' if payment_type == 'outbound' else 'customer',
            'partner_id': partner.id,
            'amount': self.AMOUNT,
            'date': date,
            'journal_id': self.bank_journal.id,
            'company_id': self.company.id,
            'currency_id': self.vnd.id,
            'memo': memo,
            'vas_operation_type': op_type,
        })
        pmt.action_post()
        return pmt

    def test_w3_t10_ky_quy_mang_di(self):
        """T10 (workbook b1/b2): Nợ 1386 / Có 112 khi chi; đảo lại khi nhận về."""
        partner = self.env['res.partner'].create({
            'name': 'Ben nhan ky quy T10', 'company_id': self.company.id,
        })
        out = self._make_deposit(
            'deposit_out', 'outbound', '2099-04-16', 'W3-T10-out', partner)
        self._sync()
        status, _bal, diffs = self._grade('T10-b1', self._vas_for_payments(out), {
            '1386': self.AMOUNT,
            '112': -self.AMOUNT,
        })
        self.assertEqual(status, 'ĐẠT', diffs)

        back = self._make_deposit(
            'deposit_out', 'inbound', '2099-04-17', 'W3-T10-back', partner)
        self._sync()
        status2, _b2, diffs2 = self._grade('T10-b2', self._vas_for_payments(back), {
            '112': self.AMOUNT,
            '1386': -self.AMOUNT,
        })
        self.assertEqual(status2, 'ĐẠT', diffs2)

    def test_w3_t08_nhan_ky_quy(self):
        """T08 (workbook b1/b2): Nợ 112 / Có 3386 khi nhận; đảo lại khi hoàn trả."""
        partner = self.env['res.partner'].create({
            'name': 'Ben dat coc T08', 'company_id': self.company.id,
        })
        rcv = self._make_deposit(
            'deposit_in', 'inbound', '2099-04-18', 'W3-T08-in', partner)
        self._sync()
        status, _bal, diffs = self._grade('T08-b1', self._vas_for_payments(rcv), {
            '112': self.AMOUNT,
            '3386': -self.AMOUNT,
        })
        self.assertEqual(status, 'ĐẠT', diffs)

        refund = self._make_deposit(
            'deposit_in', 'outbound', '2099-04-19', 'W3-T08-refund', partner)
        self._sync()
        status2, _b2, diffs2 = self._grade('T08-b2', self._vas_for_payments(refund), {
            '3386': self.AMOUNT,
            '112': -self.AMOUNT,
        })
        self.assertEqual(status2, 'ĐẠT', diffs2)

    def test_w3_b09_chiet_khau_ban(self):
        """B09: CK cho KH — Nợ 635 / Có 131 + thu phần còn lại (R23 FALLBACK + R17)."""
        partner = self.env['res.partner'].create({
            'name': 'KH W3 B09',
            'company_id': self.company.id,
            'customer_rank': 1,
        })
        inv = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': partner.id,
            'invoice_date': '2099-04-10',
            'date': '2099-04-10',
            'journal_id': self.sale_journal.id,
            'company_id': self.company.id,
            'invoice_line_ids': [Command.create({
                'name': 'Hang',
                'quantity': 1,
                'price_unit': 100_000,
                'tax_ids': [],
            })],
        })
        inv.action_post()
        assert self.writeoff_expense, 'Need expense account for write-off'
        wiz = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=inv.ids, force_payment_move=True,
        ).create({
            'amount': 98_000,
            'journal_id': self.bank_journal.id,
            'payment_date': '2099-04-11',
            'payment_difference_handling': 'reconcile',
            'writeoff_account_id': self.writeoff_expense.id,
            'writeoff_label': 'W3-B09-discount',
        })
        payment = wiz.with_context(force_payment_move=True)._create_payments()[:1]
        self._sync()
        # VAS moves: sale invoice (W1) + discount + payment
        vas_pay = self._vas_for_payments(payment)
        # Discount is move_kind expense
        disc = vas_pay.filtered(lambda m: m.move_kind == 'expense')
        cash = vas_pay.filtered(lambda m: m.move_kind == 'payment')
        status_d, bal_d, diffs_d = self._grade('B09-discount', disc, {
            '635': 2_000.0,
            '131': -2_000.0,
        })
        status_c, bal_c, diffs_c = self._grade('B09-cash', cash, {
            '112': 98_000.0,
            '131': -98_000.0,
        })
        self.assertEqual(status_d, 'ĐẠT', diffs_d)
        self.assertEqual(status_c, 'ĐẠT', diffs_c)

    def test_w3_m10_chiet_khau_mua(self):
        """M10: CK được hưởng — Nợ 331 / Có 515 + trả phần còn lại."""
        partner = self.env['res.partner'].create({
            'name': 'NCC W3 M10',
            'company_id': self.company.id,
            'supplier_rank': 1,
        })
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': partner.id,
            'invoice_date': '2099-04-12',
            'date': '2099-04-12',
            'journal_id': self.purchase_journal.id,
            'company_id': self.company.id,
            'invoice_line_ids': [Command.create({
                'name': 'Hang mua',
                'quantity': 1,
                'price_unit': 100_000,
                'tax_ids': [],
            })],
        })
        bill.action_post()
        assert self.writeoff_income, 'Need income account for write-off'
        wiz = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=bill.ids, force_payment_move=True,
        ).create({
            'amount': 98_000,
            'journal_id': self.bank_journal.id,
            'payment_date': '2099-04-13',
            'payment_difference_handling': 'reconcile',
            'writeoff_account_id': self.writeoff_income.id,
            'writeoff_label': 'W3-M10-discount',
        })
        payment = wiz.with_context(force_payment_move=True)._create_payments()[:1]
        self._sync()
        vas_pay = self._vas_for_payments(payment)
        disc = vas_pay.filtered(lambda m: m.move_kind == 'expense')
        cash = vas_pay.filtered(lambda m: m.move_kind == 'payment')
        status_d, _b, diffs_d = self._grade('M10-discount', disc, {
            '331': 2_000.0,
            '515': -2_000.0,
        })
        status_c, _b, diffs_c = self._grade('M10-cash', cash, {
            '331': 98_000.0,
            '112': -98_000.0,
        })
        self.assertEqual(status_d, 'ĐẠT', diffs_d)
        self.assertEqual(status_c, 'ĐẠT', diffs_c)

    def test_w3_t09_deferred_cross_reconcile(self):
        """T09/R22: xác nhận Odoo 19 vẫn chặn reconcile AR/AP khác account — DEFER."""
        partner = self.env['res.partner'].create({
            'name': 'Dual W3 T09',
            'company_id': self.company.id,
            'customer_rank': 1,
            'supplier_rank': 1,
        })
        inv = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': partner.id,
            'invoice_date': '2099-04-14',
            'date': '2099-04-14',
            'journal_id': self.sale_journal.id,
            'company_id': self.company.id,
            'invoice_line_ids': [Command.create({
                'name': 'A', 'quantity': 1, 'price_unit': 100, 'tax_ids': [],
            })],
        })
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': partner.id,
            'invoice_date': '2099-04-14',
            'date': '2099-04-14',
            'journal_id': self.purchase_journal.id,
            'company_id': self.company.id,
            'invoice_line_ids': [Command.create({
                'name': 'B', 'quantity': 1, 'price_unit': 100, 'tax_ids': [],
            })],
        })
        (inv + bill).action_post()
        ar = inv.line_ids.filtered(lambda l: l.account_id.account_type == 'asset_receivable')
        ap = bill.line_ids.filtered(lambda l: l.account_id.account_type == 'liability_payable')
        error = None
        try:
            (ar + ap).reconcile()
        except Exception as e:
            error = str(e)
        print(f"\n=== T09: DEFER ===\nCross-reconcile error: {error}\n")
        self.assertTrue(error, 'Expected Odoo to block AR/AP cross reconcile')
        self.assertIn('same account', error.lower())
