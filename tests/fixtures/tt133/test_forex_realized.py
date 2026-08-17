# -*- coding: utf-8 -*-
"""R24 chênh + R17/R18 gốc ngoại tệ (V07 / V08 / M12).

Số chuẩn: 100 USD @25.000 → @26.000 (hoặc @24.000) → chênh 100.000 VND.
Assert R24 riêng + E2E NET (gốc payment + chênh forex).
"""
from collections import defaultdict

from odoo import Command
from odoo.tests import tagged, TransactionCase
from odoo.tools.float_utils import float_compare


INV_DATE = '2099-08-10'
PAY_DATE = '2099-08-20'
PAY_DATE_LOSS = '2099-08-21'
FC_AMOUNT = 100.0
RATE_BOOK = 25_000.0
RATE_SETTLE = 26_000.0
RATE_LOSS = 24_000.0
BOOK_VND = 2_500_000.0
SETTLE_VND = 2_600_000.0
SETTLE_LOW = 2_400_000.0
DIFF = 100_000.0


@tagged('connecta_vas', 'connecta_vas_fx', 'post_install', '-at_install')
class TestTt133ForexRealized(TransactionCase):
    """V07 lãi/lỗ, V08/M12 lãi/lỗ — JE R24 đúng chiều & số."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.vnd = cls.env.ref('base.VND')
        cls.usd = cls.env.ref('base.USD')
        if cls.company.currency_id != cls.vnd:
            cls.company.currency_id = cls.vnd
        cls.usd.active = True

        cls.regime = cls.env['vas.regime'].search([('code', '=', 'TT133')], limit=1)
        if not cls.regime:
            cls.regime = cls.env['vas.regime'].create({
                'code': 'TT133',
                'name': 'Thông tư 133/2016/TT-BTC',
            })
        cls.company.vas_regime_id = cls.regime
        cls.company.vas_start_date = '2000-01-01'
        cls.env['vas.journal']._connecta_seed_tt133_journals()
        cls._ensure_periods()
        cls._ensure_r24_rules()
        cls._ensure_r17_r18_rules()
        cls._ensure_fx_company_config()
        cls._ensure_usd_rates()

        cls.partner = cls.env['res.partner'].create({
            'name': 'FX Partner R24',
            'company_id': cls.company.id,
            'customer_rank': 1,
            'supplier_rank': 1,
        })
        cls.sale_j = cls._journal('sale', 'FXSL', 'FX Sale')
        cls.purchase_j = cls._journal('purchase', 'FXPU', 'FX Purchase')
        cls.bank_j = cls._journal('bank', 'FXBK', 'FX Bank')

        uom = cls.env.ref('uom.product_uom_unit')
        cls.product = cls.env['product.product'].create({
            'name': 'HH FX R24',
            'type': 'service',
            'list_price': FC_AMOUNT,
            'standard_price': FC_AMOUNT,
            'uom_id': uom.id,
            'sale_ok': True,
            'purchase_ok': True,
            'taxes_id': [Command.clear()],
            'supplier_taxes_id': [Command.clear()],
        })

    @classmethod
    def _journal(cls, jtype, code, name):
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
    def _ensure_periods(cls):
        fy = cls.env['vas.fiscalyear'].search([
            ('company_id', '=', cls.company.id),
            ('date_from', '<=', INV_DATE),
            ('date_to', '>=', PAY_DATE),
        ], limit=1)
        if not fy:
            fy = cls.env['vas.fiscalyear'].create({
                'name': '2099 FX',
                'date_from': '2099-01-01',
                'date_to': '2099-12-31',
                'state': 'open',
                'company_id': cls.company.id,
            })
        if not fy.period_ids:
            fy.action_generate_periods()
        else:
            fy.period_ids.write({'state': 'open'})

    @classmethod
    def _ensure_r24_rules(cls):
        """Đảm bảo R24a–d có trên DB test (kể cả chưa upgrade XML)."""
        specs = {
            'R24a': [
                ('debit', 'bank_cash', 'forex_diff'),
                ('credit', 'finance_income', 'forex_diff'),
            ],
            'R24b': [
                ('debit', 'finance_expense', 'forex_diff'),
                ('credit', 'partner_receivable', 'forex_diff'),
            ],
            'R24c': [
                ('debit', 'finance_expense', 'forex_diff'),
                ('credit', 'bank_cash', 'forex_diff'),
            ],
            'R24d': [
                ('debit', 'partner_payable', 'forex_diff'),
                ('credit', 'finance_income', 'forex_diff'),
            ],
        }
        Rule = cls.env['vas.rule']
        for seq, (code, lines) in enumerate(specs.items(), start=240):
            rule = Rule.search([
                ('regime_id', '=', cls.regime.id), ('code', '=', code),
            ], limit=1)
            if not rule:
                rule = Rule.create({
                    'code': code,
                    'name': f'FX {code}',
                    'regime_id': cls.regime.id,
                    'event_type': 'forex_realized',
                    'sequence': seq,
                    'active': True,
                })
            if not rule.line_ids:
                for i, (side, sel, amt) in enumerate(lines, start=1):
                    cls.env['vas.rule.line'].create({
                        'rule_id': rule.id,
                        'sequence': i * 10,
                        'side': side,
                        'account_selector': sel,
                        'amount_selector': amt,
                    })

    @classmethod
    def _ensure_r17_r18_rules(cls):
        """R17/R18 — GỐC thu/chi (paid → FX principal khi ngoại tệ)."""
        specs = {
            'R17': (
                'payment_in', 17,
                [
                    ('debit', 'bank_cash', 'paid'),
                    ('credit', 'partner_receivable', 'paid'),
                ],
            ),
            'R18': (
                'payment_out', 18,
                [
                    ('debit', 'partner_payable', 'paid'),
                    ('credit', 'bank_cash', 'paid'),
                ],
            ),
        }
        Rule = cls.env['vas.rule']
        for code, (event, seq, lines) in specs.items():
            rule = Rule.search([
                ('regime_id', '=', cls.regime.id), ('code', '=', code),
            ], limit=1)
            if not rule:
                rule = Rule.create({
                    'code': code,
                    'name': f'{code} FX principal',
                    'regime_id': cls.regime.id,
                    'event_type': event,
                    'sequence': seq,
                    'active': True,
                })
            if not rule.line_ids:
                for i, (side, sel, amt) in enumerate(lines, start=1):
                    cls.env['vas.rule.line'].create({
                        'rule_id': rule.id,
                        'sequence': i * 10,
                        'side': side,
                        'account_selector': sel,
                        'amount_selector': amt,
                    })

    @classmethod
    def _ensure_fx_company_config(cls):
        """Odoo cần journal + TK P&L FX để sinh EXCH (tín hiệu R24)."""
        exch_j = cls.company.currency_exchange_journal_id
        if not exch_j:
            exch_j = cls.env['account.journal'].search([
                ('company_id', '=', cls.company.id),
                ('type', '=', 'general'),
            ], limit=1)
            if not exch_j:
                exch_j = cls.env['account.journal'].create({
                    'name': 'Exchange Difference',
                    'code': 'EXCH',
                    'type': 'general',
                    'company_id': cls.company.id,
                })
            cls.company.currency_exchange_journal_id = exch_j
        if not cls.company.income_currency_exchange_account_id:
            income = cls.env['account.account'].search([
                ('company_ids', 'in', cls.company.id),
                ('account_type', 'in', ('income', 'income_other')),
            ], limit=1)
            cls.company.income_currency_exchange_account_id = income
        if not cls.company.expense_currency_exchange_account_id:
            expense = cls.env['account.account'].search([
                ('company_ids', 'in', cls.company.id),
                ('account_type', '=', 'expense'),
            ], limit=1)
            cls.company.expense_currency_exchange_account_id = expense

    @classmethod
    def _ensure_usd_rates(cls):
        Rate = cls.env['res.currency.rate']
        # Thử rate = 1/VND_per_USD (chuẩn nhiều bản Odoo: amount_company = amount / rate)
        days = (
            (INV_DATE, RATE_BOOK),
            (PAY_DATE, RATE_SETTLE),
            (PAY_DATE_LOSS, RATE_LOSS),
        )
        for day, vnd_rate in days:
            existing = Rate.search([
                ('currency_id', '=', cls.usd.id),
                ('name', '=', day),
                ('company_id', '=', cls.company.id),
            ], limit=1)
            rate_val = 1.0 / vnd_rate
            if existing:
                existing.write({'rate': rate_val})
            else:
                Rate.create({
                    'currency_id': cls.usd.id,
                    'name': day,
                    'company_id': cls.company.id,
                    'rate': rate_val,
                })
        got = cls.usd._convert(FC_AMOUNT, cls.vnd, cls.company, INV_DATE)
        if float_compare(got, BOOK_VND, precision_digits=0) != 0:
            # Đảo: rate = VND per USD
            for day, vnd_rate in days:
                rec = Rate.search([
                    ('currency_id', '=', cls.usd.id),
                    ('name', '=', day),
                    ('company_id', '=', cls.company.id),
                ], limit=1)
                rec.rate = vnd_rate
            got = cls.usd._convert(FC_AMOUNT, cls.vnd, cls.company, INV_DATE)
        assert float_compare(got, BOOK_VND, precision_digits=0) == 0, (
            f'USD rate setup failed: convert(100)={got}, want {BOOK_VND}'
        )

    def _sync(self, date_from=INV_DATE, date_to=PAY_DATE):
        return self.env['vas.sync'].sync_company(
            self.company, date_from=date_from, date_to=date_to,
        )

    def _net_by_code(self, moves):
        net = defaultdict(float)
        for line in moves.mapped('line_ids'):
            code = line.account_id.code
            net[code] += (line.debit or 0.0) - (line.credit or 0.0)
        return dict(net)

    def _r24_for(self, partial):
        return self.env['vas.move'].search([
            ('source_model', '=', 'account.partial.reconcile'),
            ('source_res_id', '=', partial.id),
            ('move_kind', '=', 'forex'),
            ('is_reversal', '=', False),
            ('state', 'not in', ('reversed', 'cancelled')),
        ])

    def _receivable_line(self, move):
        return move.line_ids.filtered(
            lambda l: l.account_id.account_type == 'asset_receivable'
        )[:1]

    def _payable_line(self, move):
        return move.line_ids.filtered(
            lambda l: l.account_id.account_type == 'liability_payable'
        )[:1]

    def _create_out_invoice_usd(self, rate_date=INV_DATE):
        inv = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'journal_id': self.sale_j.id,
            'invoice_date': rate_date,
            'date': rate_date,
            'currency_id': self.usd.id,
            'company_id': self.company.id,
            'invoice_line_ids': [Command.create({
                'product_id': self.product.id,
                'name': 'FX sale',
                'quantity': 1,
                'price_unit': FC_AMOUNT,
                'tax_ids': [Command.clear()],
            })],
        })
        inv.action_post()
        return inv

    def _create_in_invoice_usd(self, rate_date=INV_DATE):
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': self.partner.id,
            'journal_id': self.purchase_j.id,
            'invoice_date': rate_date,
            'date': rate_date,
            'currency_id': self.usd.id,
            'company_id': self.company.id,
            'invoice_line_ids': [Command.create({
                'product_id': self.product.id,
                'name': 'FX purchase',
                'quantity': 1,
                'price_unit': FC_AMOUNT,
                'tax_ids': [Command.clear()],
            })],
        })
        bill.action_post()
        return bill

    def _bank_settle_ar(self, invoice, settle_vnd=SETTLE_VND, pay_date=PAY_DATE):
        """JE ngân hàng: Nợ NH settle_vnd / Có phải thu settle_vnd (+100 USD)."""
        ar = self._receivable_line(invoice)
        bank_account = self.bank_j.default_account_id
        self.assertTrue(bank_account, 'Bank journal thiếu default_account_id')
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.bank_j.id,
            'date': pay_date,
            'company_id': self.company.id,
            'ref': f'FX settle AR {invoice.name}',
            'line_ids': [
                Command.create({
                    'account_id': bank_account.id,
                    'name': 'Bank in',
                    'debit': settle_vnd,
                    'credit': 0.0,
                    'amount_currency': FC_AMOUNT,
                    'currency_id': self.usd.id,
                    'partner_id': self.partner.id,
                }),
                Command.create({
                    'account_id': ar.account_id.id,
                    'name': 'AR clear',
                    'debit': 0.0,
                    'credit': settle_vnd,
                    'amount_currency': -FC_AMOUNT,
                    'currency_id': self.usd.id,
                    'partner_id': self.partner.id,
                }),
            ],
        })
        move.action_post()
        return move

    def _bank_settle_ap(self, bill, settle_vnd=SETTLE_VND, pay_date=PAY_DATE):
        """JE ngân hàng: Nợ phải trả settle_vnd / Có NH settle_vnd (−100 USD)."""
        ap = self._payable_line(bill)
        bank_account = self.bank_j.default_account_id
        self.assertTrue(bank_account, 'Bank journal thiếu default_account_id')
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.bank_j.id,
            'date': pay_date,
            'company_id': self.company.id,
            'ref': f'FX settle AP {bill.name}',
            'line_ids': [
                Command.create({
                    'account_id': ap.account_id.id,
                    'name': 'AP clear',
                    'debit': settle_vnd,
                    'credit': 0.0,
                    'amount_currency': FC_AMOUNT,
                    'currency_id': self.usd.id,
                    'partner_id': self.partner.id,
                }),
                Command.create({
                    'account_id': bank_account.id,
                    'name': 'Bank out',
                    'debit': 0.0,
                    'credit': settle_vnd,
                    'amount_currency': -FC_AMOUNT,
                    'currency_id': self.usd.id,
                    'partner_id': self.partner.id,
                }),
            ],
        })
        move.action_post()
        return move

    def _reconcile_debt(self, invoice_or_bill, bank_move, side='ar'):
        if side == 'ar':
            a = self._receivable_line(invoice_or_bill)
            b = bank_move.line_ids.filtered(
                lambda l: l.account_id == a.account_id
            )[:1]
        else:
            a = self._payable_line(invoice_or_bill)
            b = bank_move.line_ids.filtered(
                lambda l: l.account_id == a.account_id
            )[:1]
        (a + b).reconcile()
        partial = (a.matched_debit_ids | a.matched_credit_ids).filtered(
            'exchange_move_id'
        )[:1]
        self.assertTrue(
            partial,
            'Odoo phải sinh partial có exchange_move_id (tín hiệu R24)',
        )
        return partial

    def _assert_r24_lines(self, partial, expect_debit_codes, expect_credit_codes, amount):
        je = self._r24_for(partial)
        self.assertEqual(len(je), 1, f'Cần đúng 1 JE R24, được {je}')
        self.assertEqual(je.move_kind, 'forex')
        debits = {
            l.account_id.code: l.debit
            for l in je.line_ids if l.debit
        }
        credits = {
            l.account_id.code: l.credit
            for l in je.line_ids if l.credit
        }
        for code in expect_debit_codes:
            self.assertIn(code, debits, f'Thiếu Nợ {code}: {debits}')
            self.assertEqual(
                float_compare(debits[code], amount, precision_digits=2), 0,
                f'Nợ {code}={debits[code]} ≠ {amount}',
            )
        for code in expect_credit_codes:
            self.assertIn(code, credits, f'Thiếu Có {code}: {credits}')
            self.assertEqual(
                float_compare(credits[code], amount, precision_digits=2), 0,
                f'Có {code}={credits[code]} ≠ {amount}',
            )
        codes = set(je.line_ids.mapped('account_id.code'))
        self.assertFalse(codes & {'441', '441000', '641', '641000'})
        return je

    def _payment_je(self, payment):
        return self.env['vas.move'].search([
            ('source_model', '=', 'account.payment'),
            ('source_res_id', '=', payment.id),
            ('move_kind', '=', 'payment'),
            ('is_reversal', '=', False),
            ('state', 'not in', ('reversed', 'cancelled')),
        ])

    def _pay_invoice_usd(self, move, pay_date=PAY_DATE):
        """Register payment USD + force JE → reconcile (có thể sinh EXCH)."""
        wiz = self.env['account.payment.register'].with_context(
            active_model='account.move',
            active_ids=move.ids,
            force_payment_move=True,
        ).create({
            'payment_date': pay_date,
            'journal_id': self.bank_j.id,
            'currency_id': self.usd.id,
            'amount': FC_AMOUNT,
        })
        payment = wiz.with_context(force_payment_move=True)._create_payments()[:1]
        if payment.state in ('draft', 'in_process'):
            payment.with_context(force_payment_move=True).action_post()
        return payment

    def _fx_partial_for_payment(self, payment):
        Sync = self.env['vas.sync']
        partials = Sync._payment_debt_partials(payment).filtered('exchange_move_id')
        return partials[:1]

    def _assert_net(self, moves, expect):
        net = self._net_by_code(moves)
        for code, amount in expect.items():
            got = net.get(code, 0.0)
            self.assertEqual(
                float_compare(got, amount, precision_digits=2), 0,
                f'NET {code}={got} ≠ {amount}; full={net}',
            )

    def _assert_payment_principal(self, payment, amount, debt_code, cash_codes):
        je = self._payment_je(payment)
        self.assertEqual(len(je), 1, f'Cần 1 JE R17/R18, được {je}')
        net = self._net_by_code(je)
        self.assertEqual(
            float_compare(abs(net.get(debt_code, 0.0)), amount, precision_digits=2), 0,
            f'Gốc {debt_code}={net.get(debt_code)} ≠ ±{amount}; {net}',
        )
        cash_got = sum(abs(net.get(c, 0.0)) for c in cash_codes)
        self.assertEqual(
            float_compare(cash_got, amount, precision_digits=2), 0,
            f'Gốc tiền={cash_got} ≠ {amount}; {net}',
        )
        for pnl in ('515', '635'):
            self.assertTrue(
                float_compare(abs(net.get(pnl, 0.0)), 0.0, precision_digits=2) == 0,
                f'R17/R18 không được ghi {pnl}: {net}',
            )
        return je

    def _e2e_ar(self, settle_high=True):
        inv = self._create_out_invoice_usd()
        pay_date = PAY_DATE if settle_high else PAY_DATE_LOSS
        payment = self._pay_invoice_usd(inv, pay_date=pay_date)
        self._sync(date_from=INV_DATE, date_to=pay_date)
        return inv, payment

    def _e2e_ap(self, settle_high=True):
        bill = self._create_in_invoice_usd()
        pay_date = PAY_DATE if settle_high else PAY_DATE_LOSS
        payment = self._pay_invoice_usd(bill, pay_date=pay_date)
        self._sync(date_from=INV_DATE, date_to=pay_date)
        return bill, payment

    # ------------------------------------------------------------------ tests

    def test_v07_gain_r24a(self):
        """Thu AR: settle > book → Nợ 1122 / Có 515 = 100k."""
        inv = self._create_out_invoice_usd()
        bank = self._bank_settle_ar(inv, SETTLE_VND)
        partial = self._reconcile_debt(inv, bank, 'ar')
        stats = self._sync()
        self.assertGreaterEqual(stats.get('forex_realized', {}).get('created', 0), 1)
        self._assert_r24_lines(partial, ['1122'], ['515'], DIFF)

    def test_v07_loss_r24b(self):
        """Thu AR: settle < book → Nợ 635 / Có 131 = 100k."""
        inv = self._create_out_invoice_usd()
        low = SETTLE_LOW
        bank = self._bank_settle_ar(inv, low)
        partial = self._reconcile_debt(inv, bank, 'ar')
        self._sync()
        self._assert_r24_lines(partial, ['635'], ['131'], DIFF)

    def test_v08_loss_r24c(self):
        """Trả AP: settle > book → Nợ 635 / Có 1122 = 100k (M12 lỗ cùng)."""
        bill = self._create_in_invoice_usd()
        bank = self._bank_settle_ap(bill, SETTLE_VND)
        partial = self._reconcile_debt(bill, bank, 'ap')
        self._sync()
        self._assert_r24_lines(partial, ['635'], ['1122'], DIFF)

    def test_v08_gain_r24d(self):
        """Trả AP: settle < book → Nợ 331 / Có 515 = 100k (M12 lãi cùng)."""
        bill = self._create_in_invoice_usd()
        bank = self._bank_settle_ap(bill, SETTLE_LOW)
        partial = self._reconcile_debt(bill, bank, 'ap')
        self._sync()
        self._assert_r24_lines(partial, ['331'], ['515'], DIFF)

    def test_m12_loss_same_as_v08(self):
        """M12 lỗ = V08 lỗ — cùng R24c."""
        bill = self._create_in_invoice_usd()
        bank = self._bank_settle_ap(bill, SETTLE_VND)
        partial = self._reconcile_debt(bill, bank, 'ap')
        self._sync()
        self._assert_r24_lines(partial, ['635'], ['1122'], DIFF)

    def test_m12_gain_same_as_v08(self):
        """M12 lãi = V08 lãi — cùng R24d."""
        bill = self._create_in_invoice_usd()
        bank = self._bank_settle_ap(bill, SETTLE_LOW)
        partial = self._reconcile_debt(bill, bank, 'ap')
        self._sync()
        self._assert_r24_lines(partial, ['331'], ['515'], DIFF)

    def test_r24_idempotent(self):
        inv = self._create_out_invoice_usd()
        bank = self._bank_settle_ar(inv, SETTLE_VND)
        partial = self._reconcile_debt(inv, bank, 'ar')
        self._sync()
        self._sync()
        self.assertEqual(len(self._r24_for(partial)), 1)

    def test_partial_unlink_reverses_r24(self):
        """Cancel-handling Q8: unlink partial → đảo JE R24."""
        inv = self._create_out_invoice_usd()
        bank = self._bank_settle_ar(inv, SETTLE_VND)
        partial = self._reconcile_debt(inv, bank, 'ar')
        self._sync()
        je = self._r24_for(partial)
        self.assertEqual(len(je), 1)
        partial_id = partial.id
        lines = partial.debit_move_id | partial.credit_move_id
        lines.remove_move_reconcile()
        self.assertFalse(
            self.env['account.partial.reconcile'].browse(partial_id).exists(),
        )
        self._sync()
        je.invalidate_recordset()
        self.assertEqual(je.state, 'reversed')

    def test_e2e_v07_gain_principal_plus_r24(self):
        """V07 lãi: R17@book + R24a → NET tiền +S / 131 −B / 515 −D."""
        _inv, payment = self._e2e_ar(settle_high=True)
        partial = self._fx_partial_for_payment(payment)
        self.assertTrue(partial, 'Cần partial+EXCH sau payment FX')
        pay_je = self._assert_payment_principal(
            payment, BOOK_VND, '131', ('1122', '112', '1112', '111'),
        )
        r24 = self._assert_r24_lines(partial, ['1122'], ['515'], DIFF)
        net = self._net_by_code(pay_je | r24)
        cash = net.get('1122', 0.0) + net.get('112', 0.0) + net.get('1112', 0.0)
        self.assertEqual(float_compare(cash, SETTLE_VND, precision_digits=2), 0, net)
        self.assertEqual(float_compare(net.get('131', 0.0), -BOOK_VND, precision_digits=2), 0, net)
        self.assertEqual(float_compare(net.get('515', 0.0), -DIFF, precision_digits=2), 0, net)

    def test_e2e_v07_loss_principal_plus_r24(self):
        """V07 lỗ: R17@settle + R24b → NET tiền +S / 131 −B / 635 +D."""
        _inv, payment = self._e2e_ar(settle_high=False)
        partial = self._fx_partial_for_payment(payment)
        self.assertTrue(partial, 'Cần partial+EXCH')
        pay_je = self._assert_payment_principal(
            payment, SETTLE_LOW, '131', ('1122', '112', '1112', '111'),
        )
        r24 = self._assert_r24_lines(partial, ['635'], ['131'], DIFF)
        net = self._net_by_code(pay_je | r24)
        cash = net.get('1122', 0.0) + net.get('112', 0.0) + net.get('1112', 0.0)
        self.assertEqual(float_compare(cash, SETTLE_LOW, precision_digits=2), 0, net)
        self.assertEqual(float_compare(net.get('131', 0.0), -BOOK_VND, precision_digits=2), 0, net)
        self.assertEqual(float_compare(net.get('635', 0.0), DIFF, precision_digits=2), 0, net)

    def test_e2e_v08_loss_principal_plus_r24(self):
        """V08/M12 lỗ: R18@book + R24c → NET 331 +B / tiền −S / 635 +D."""
        _bill, payment = self._e2e_ap(settle_high=True)
        partial = self._fx_partial_for_payment(payment)
        self.assertTrue(partial, 'Cần partial+EXCH')
        pay_je = self._assert_payment_principal(
            payment, BOOK_VND, '331', ('1122', '112', '1112', '111'),
        )
        r24 = self._assert_r24_lines(partial, ['635'], ['1122'], DIFF)
        net = self._net_by_code(pay_je | r24)
        cash = net.get('1122', 0.0) + net.get('112', 0.0) + net.get('1112', 0.0)
        self.assertEqual(float_compare(net.get('331', 0.0), BOOK_VND, precision_digits=2), 0, net)
        self.assertEqual(float_compare(cash, -SETTLE_VND, precision_digits=2), 0, net)
        self.assertEqual(float_compare(net.get('635', 0.0), DIFF, precision_digits=2), 0, net)

    def test_e2e_v08_gain_principal_plus_r24(self):
        """V08/M12 lãi: R18@settle + R24d → NET 331 +B / tiền −S / 515 −D."""
        _bill, payment = self._e2e_ap(settle_high=False)
        partial = self._fx_partial_for_payment(payment)
        self.assertTrue(partial, 'Cần partial+EXCH')
        pay_je = self._assert_payment_principal(
            payment, SETTLE_LOW, '331', ('1122', '112', '1112', '111'),
        )
        r24 = self._assert_r24_lines(partial, ['331'], ['515'], DIFF)
        net = self._net_by_code(pay_je | r24)
        cash = net.get('1122', 0.0) + net.get('112', 0.0) + net.get('1112', 0.0)
        self.assertEqual(float_compare(net.get('331', 0.0), BOOK_VND, precision_digits=2), 0, net)
        self.assertEqual(float_compare(cash, -SETTLE_LOW, precision_digits=2), 0, net)
        self.assertEqual(float_compare(net.get('515', 0.0), -DIFF, precision_digits=2), 0, net)

    def test_e2e_no_diff_principal_only(self):
        """Không chênh: R17@book, không R24 515/635."""
        inv = self._create_out_invoice_usd()
        payment = self._pay_invoice_usd(inv, pay_date=INV_DATE)
        self._sync(date_from=INV_DATE, date_to=INV_DATE)
        pay_je = self._assert_payment_principal(
            payment, BOOK_VND, '131', ('1122', '112', '1112', '111'),
        )
        partials = self.env['vas.sync']._payment_debt_partials(payment)
        for p in partials:
            self.assertFalse(self._r24_for(p), 'Không chênh → không JE R24')
        net = self._net_by_code(pay_je)
        self.assertTrue(
            float_compare(abs(net.get('515', 0.0)), 0.0, precision_digits=2) == 0
            and float_compare(abs(net.get('635', 0.0)), 0.0, precision_digits=2) == 0,
            net,
        )

    def test_fx_payment_skip_until_reconcile(self):
        """Payment FX chưa khớp HĐ → skip R17."""
        payment = self.env['account.payment'].with_context(
            force_payment_move=True,
        ).create({
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': self.partner.id,
            'amount': FC_AMOUNT,
            'currency_id': self.usd.id,
            'journal_id': self.bank_j.id,
            'date': PAY_DATE,
            'company_id': self.company.id,
        })
        payment.with_context(force_payment_move=True).action_post()
        Sync = self.env['vas.sync']
        self.assertTrue(Sync._payment_is_foreign(payment, self.company))
        self.assertTrue(Sync._payment_fx_awaiting_reconcile(payment, self.company))
        self._sync()
        self.assertFalse(
            self._payment_je(payment),
            'FX chưa partial → chưa ghi R17',
        )

    def test_regression_vnd_payment_unchanged(self):
        """Payment VND: GỐC = payment.amount; không R24."""
        amount = 1_000_000.0
        inv = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'journal_id': self.sale_j.id,
            'invoice_date': INV_DATE,
            'date': INV_DATE,
            'currency_id': self.vnd.id,
            'company_id': self.company.id,
            'invoice_line_ids': [Command.create({
                'product_id': self.product.id,
                'name': 'VND sale',
                'quantity': 1,
                'price_unit': amount,
                'tax_ids': [Command.clear()],
            })],
        })
        inv.action_post()
        wiz = self.env['account.payment.register'].with_context(
            active_model='account.move',
            active_ids=inv.ids,
            force_payment_move=True,
        ).create({
            'payment_date': INV_DATE,
            'journal_id': self.bank_j.id,
            'currency_id': self.vnd.id,
            'amount': amount,
        })
        payment = wiz.with_context(force_payment_move=True)._create_payments()[:1]
        if payment.state in ('draft', 'in_process'):
            payment.with_context(force_payment_move=True).action_post()
        self._sync(date_from=INV_DATE, date_to=INV_DATE)
        pay_je = self._assert_payment_principal(
            payment, amount, '131', ('112', '111', '1122', '1112'),
        )
        self.assertFalse(
            any(self._r24_for(p) for p in self.env['vas.sync']._payment_debt_partials(payment)),
        )
        Sync = self.env['vas.sync']
        self.assertIsNone(Sync._payment_fx_principal_amount(payment, self.company))
        self.assertEqual(
            float_compare(
                abs(self._net_by_code(pay_je).get('131', 0.0)), amount, precision_digits=2,
            ),
            0,
        )
