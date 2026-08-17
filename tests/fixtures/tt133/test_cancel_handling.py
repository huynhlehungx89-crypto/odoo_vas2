# -*- coding: utf-8 -*-
"""Cancel-handling NON-STOCK — C01…C09, R01…R03, P01…P02, N01/N02/N04.

Kho / landed / fingerprint: ngoài phạm vi (task riêng).
"""
from collections import defaultdict

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged, TransactionCase


DATE = '2099-03-15'
DATE_APR = '2099-04-10'


@tagged('connecta_vas', 'connecta_vas_cancel', 'post_install', '-at_install')
class TestTt133CancelHandling(TransactionCase):
    """State-regression → action_reverse; unlock post-again; VAS-owned cancel."""

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
        cls._ensure_periods()

        cls.partner = cls.env['res.partner'].create({
            'name': 'KH Cancel Test',
            'company_id': cls.company.id,
            'customer_rank': 1,
            'supplier_rank': 1,
        })
        cls.tax_sale = cls._tax('sale', 10.0)
        cls.tax_purchase = cls._tax('purchase', 10.0)

        cls.cat = cls.env['product.category'].create({
            'name': 'Cancel HH',
            'property_cost_method': 'fifo',
            'property_valuation': 'real_time',
        })
        cls._map_cat(cls.cat)
        uom = cls.env.ref('uom.product_uom_unit')
        cls.product = cls.env['product.product'].create({
            'name': 'HH Cancel',
            'is_storable': True,
            'list_price': 100_000,
            'standard_price': 60_000,
            'categ_id': cls.cat.id,
            'taxes_id': [Command.set(cls.tax_sale.ids)],
            'supplier_taxes_id': [Command.set(cls.tax_purchase.ids)],
            'uom_id': uom.id,
            'purchase_ok': True,
            'sale_ok': True,
        })
        cls.svc = cls.env['product.product'].create({
            'name': 'DV Cancel',
            'type': 'service',
            'list_price': 50_000,
            'standard_price': 50_000,
            'uom_id': uom.id,
            'purchase_ok': True,
        })

        cls.sale_j = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id), ('type', '=', 'sale'),
        ], limit=1)
        cls.purchase_j = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id), ('type', '=', 'purchase'),
        ], limit=1)
        cls.bank_j = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id), ('type', '=', 'bank'),
        ], limit=1)
        cls.cash_j = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id), ('type', '=', 'cash'),
        ], limit=1)
        assert cls.sale_j and cls.purchase_j and cls.bank_j

        cls.employee = cls.env['hr.employee'].create({
            'name': 'NV Cancel',
            'company_id': cls.company.id,
        })
        cls.emp_partner = cls.env['res.partner'].create({'name': 'NLĐ Cancel'})
        cls.employee.work_contact_id = cls.emp_partner

        cls.exp_product = cls.env['product.product'].create({
            'name': 'Chi phí Cancel',
            'type': 'service',
            'standard_price': 80_000,
            'can_be_expensed': True,
            'supplier_taxes_id': [Command.clear()],
            'uom_id': uom.id,
        })

    @classmethod
    def _acc(cls, code):
        acc = cls.env['vas.account'].search([
            ('regime_id', '=', cls.regime.id), ('code', '=', code),
        ], limit=1)
        assert acc, f'Thiếu TK {code}'
        return acc

    @classmethod
    def _map_cat(cls, cat):
        existing = cls.env['vas.account.map'].search([
            ('regime_id', '=', cls.regime.id),
            ('company_id', '=', cls.company.id),
            ('category_id', '=', cat.id),
        ], limit=1)
        if existing:
            return existing
        return cls.env['vas.account.map'].create({
            'regime_id': cls.regime.id,
            'apply_to': 'category',
            'company_id': cls.company.id,
            'category_id': cat.id,
            'stock_account_id': cls._acc('156').id,
            'revenue_account_id': cls._acc('5111').id,
            'cogs_account_id': cls._acc('632').id,
            'expense_account_id': cls._acc('6422').id,
        })

    @classmethod
    def _tax(cls, type_tax_use, amount):
        Tax = cls.env['account.tax']
        found = Tax.search([
            ('company_id', '=', cls.company.id),
            ('type_tax_use', '=', type_tax_use),
            ('amount', '=', amount),
            ('amount_type', '=', 'percent'),
        ], limit=1)
        if found:
            return found
        return Tax.create({
            'name': f'GTGT {amount}% {type_tax_use} cancel',
            'amount': amount,
            'amount_type': 'percent',
            'type_tax_use': type_tax_use,
            'company_id': cls.company.id,
        })

    @classmethod
    def _ensure_periods(cls):
        fy = cls.env['vas.fiscalyear'].search([
            ('company_id', '=', cls.company.id),
            ('date_from', '<=', DATE),
            ('date_to', '>=', DATE),
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
        cls.fy = fy
        cls.period_mar = cls.env['vas.period'].search([
            ('fiscalyear_id', '=', fy.id),
            ('date_start', '<=', DATE),
            ('date_end', '>=', DATE),
        ], limit=1)
        cls.period_apr = cls.env['vas.period'].search([
            ('fiscalyear_id', '=', fy.id),
            ('date_start', '<=', DATE_APR),
            ('date_end', '>=', DATE_APR),
        ], limit=1)
        assert cls.period_mar and cls.period_apr

    def _sync(self):
        return self.env['vas.sync'].sync_company(
            self.company, date_from='2099-01-01', date_to='2099-12-31',
        )

    def _net(self, moves):
        bal = defaultdict(float)
        for line in moves.mapped('line_ids'):
            bal[line.account_id.code] += (line.debit or 0.0) - (line.credit or 0.0)
        return dict(bal)

    def _vas_for(self, record, live_only=True):
        domain = [
            ('source_model', '=', record._name),
            ('source_res_id', '=', record.id),
            ('is_reversal', '=', False),
        ]
        if live_only:
            domain.append(('state', 'not in', ('reversed', 'cancelled')))
        return self.env['vas.move'].search(domain)

    def _assert_reversed_with_je(self, original, label=''):
        original.invalidate_recordset()
        self.assertEqual(
            original.state, 'reversed',
            f'{label}: gốc phải reversed, đang {original.state}',
        )
        rev = original.reversal_move_id
        self.assertTrue(rev and rev.exists(), f'{label}: thiếu JE đảo')
        self.assertTrue(rev.is_reversal)
        self.assertEqual(rev.state, 'posted')
        # NET cặp gốc+đảo ≈ 0
        combined = self._net(original | rev)
        for code, val in combined.items():
            self.assertTrue(
                abs(val) < 0.01,
                f'{label}: NET sau đảo TK {code}={val} (cần ~0)',
            )
        return rev

    # ------------------------------------------------------------------
    # Builders
    # ------------------------------------------------------------------

    def _out_invoice(self, amount=100_000.0, date=DATE):
        inv = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'invoice_date': date,
            'date': date,
            'journal_id': self.sale_j.id,
            'company_id': self.company.id,
            'invoice_line_ids': [Command.create({
                'product_id': self.product.id,
                'name': self.product.name,
                'quantity': 1,
                'price_unit': amount,
                'tax_ids': [Command.set(self.tax_sale.ids)],
            })],
        })
        inv.action_post()
        return inv

    def _in_invoice_goods(self, amount=100_000.0, date=DATE):
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': self.partner.id,
            'invoice_date': date,
            'date': date,
            'journal_id': self.purchase_j.id,
            'company_id': self.company.id,
            'invoice_line_ids': [Command.create({
                'product_id': self.product.id,
                'name': self.product.name,
                'quantity': 1,
                'price_unit': amount,
                'tax_ids': [Command.set(self.tax_purchase.ids)],
            })],
        })
        bill.action_post()
        return bill

    def _payment(self, amount=50_000.0, inbound=True, date=DATE):
        pay = self.env['account.payment'].create({
            'payment_type': 'inbound' if inbound else 'outbound',
            'partner_type': 'customer' if inbound else 'supplier',
            'partner_id': self.partner.id,
            'amount': amount,
            'date': date,
            'journal_id': self.bank_j.id,
            'company_id': self.company.id,
        })
        pay.action_post()
        return pay

    def _expense_approved(self, total=80_000.0, date=DATE):
        expense = self.env['hr.expense'].create({
            'name': 'Chi cancel test',
            'employee_id': self.employee.id,
            'product_id': self.exp_product.id,
            'total_amount_currency': total,
            'tax_ids': [Command.clear()],
            'company_id': self.company.id,
            'date': date,
            'payment_mode': 'own_account',
        })
        expense.action_submit()
        if expense.state != 'approved':
            expense.action_approve()
        self.assertEqual(expense.state, 'approved')
        return expense

    def _force_close_period(self, period):
        """Đóng kỳ bỏ qua chặn default-account (chỉ test P02)."""
        self.env.cr.execute(
            "UPDATE vas_period SET state='closed' WHERE id=%s",
            (period.id,),
        )
        period.invalidate_recordset()
        self.assertEqual(period.state, 'closed')

    # ------------------------------------------------------------------
    # C01–C02 out_invoice
    # ------------------------------------------------------------------

    def test_c01_out_invoice_draft_reverses(self):
        inv = self._out_invoice()
        self._sync()
        je = self._vas_for(inv)
        self.assertTrue(je, 'C01 cần sale_inv sau sync')
        self.assertTrue(any(m.move_kind == 'sale_inv' for m in je))
        orig = je.filtered(lambda m: m.move_kind == 'sale_inv')[:1]
        net_before = self._net(orig)
        inv.button_draft()
        self.assertEqual(inv.state, 'draft')
        stats = self._sync()
        cr = stats.get('cancel_regression') or {}
        self.assertGreaterEqual(cr.get('reversed', 0), 1, cr)
        self._assert_reversed_with_je(orig, 'C01')
        print(f'\n=== C01 draft → reverse ===\n  before={net_before}\n  stats={cr}\n')

    def test_c02_out_invoice_cancel_reverses(self):
        inv = self._out_invoice(amount=120_000)
        self._sync()
        orig = self._vas_for(inv).filtered(lambda m: m.move_kind == 'sale_inv')[:1]
        self.assertTrue(orig)
        inv.button_draft()
        inv.button_cancel()
        self.assertEqual(inv.state, 'cancel')
        self._sync()
        self._assert_reversed_with_je(orig, 'C02')
        print(f'\n=== C02 cancel → reverse state={orig.state} rev={orig.reversal_move_id.name} ===\n')

    # ------------------------------------------------------------------
    # C03 in_invoice — mọi kind sống
    # ------------------------------------------------------------------

    def test_c03_in_invoice_all_kinds_reverse(self):
        bill = self._in_invoice_goods()
        self._sync()
        lives = self._vas_for(bill)
        self.assertTrue(lives, 'C03 cần ≥1 JE sau sync')
        kinds = set(lives.mapped('move_kind'))
        self.assertIn('purchase_inv', kinds)
        bill.button_draft()
        bill.button_cancel()
        self._sync()
        for move in lives:
            move.invalidate_recordset()
            self._assert_reversed_with_je(move, f'C03 kind={move.move_kind}')
        still = self._vas_for(bill, live_only=True)
        self.assertFalse(still, f'C03 còn JE sống: {still}')
        print(f'\n=== C03 kinds reversed={kinds} ===\n')

    # ------------------------------------------------------------------
    # C04–C05 payment
    # ------------------------------------------------------------------

    def test_c04_payment_in_cancel(self):
        pay = self._payment(inbound=True)
        self._sync()
        orig = self._vas_for(pay).filtered(lambda m: m.move_kind == 'payment')[:1]
        self.assertTrue(orig, 'C04 cần JE payment')
        pay.action_cancel()
        self.assertIn(pay.state, ('canceled', 'cancelled'))
        self._sync()
        self._assert_reversed_with_je(orig, 'C04')
        print(f'\n=== C04 payment_in cancelled → {orig.state} ===\n')

    def test_c05_payment_out_cancel(self):
        pay = self._payment(inbound=False, amount=40_000)
        self._sync()
        orig = self._vas_for(pay).filtered(lambda m: m.move_kind == 'payment')[:1]
        self.assertTrue(orig, 'C05 cần JE payment')
        pay.action_cancel()
        self._sync()
        self._assert_reversed_with_je(orig, 'C05')
        print(f'\n=== C05 payment_out cancelled → {orig.state} ===\n')

    # ------------------------------------------------------------------
    # C06–C07 expense
    # ------------------------------------------------------------------

    def test_c06_expense_refuse(self):
        expense = self._expense_approved()
        self._sync()
        orig = self._vas_for(expense).filtered(lambda m: m.move_kind == 'expense')[:1]
        self.assertTrue(orig, 'C06 cần JE expense')
        if hasattr(expense, '_do_refuse'):
            expense._do_refuse('cancel test')
        else:
            expense.action_refuse()
        self.assertEqual(expense.state, 'refused')
        self._sync()
        self._assert_reversed_with_je(orig, 'C06')
        print(f'\n=== C06 refuse → {orig.state} ===\n')

    def test_c07_expense_reset_draft(self):
        expense = self._expense_approved(total=90_000)
        self._sync()
        orig = self._vas_for(expense).filtered(lambda m: m.move_kind == 'expense')[:1]
        self.assertTrue(orig, 'C07 cần JE expense')
        expense.action_reset()
        self.assertEqual(expense.state, 'draft')
        self._sync()
        self._assert_reversed_with_je(orig, 'C07')
        print(f'\n=== C07 reset draft → {orig.state} ===\n')

    # ------------------------------------------------------------------
    # C08–C09 VAS-owned
    # ------------------------------------------------------------------

    def test_c08_debt_offset_action_cancel(self):
        inv = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'invoice_date': DATE,
            'date': DATE,
            'journal_id': self.sale_j.id,
            'company_id': self.company.id,
            'invoice_line_ids': [Command.create({
                'name': 'AR', 'quantity': 1, 'price_unit': 100_000, 'tax_ids': [],
            })],
        })
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': self.partner.id,
            'invoice_date': DATE,
            'date': DATE,
            'journal_id': self.purchase_j.id,
            'company_id': self.company.id,
            'invoice_line_ids': [Command.create({
                'name': 'AP', 'quantity': 1, 'price_unit': 100_000, 'tax_ids': [],
                'product_id': self.svc.id,
            })],
        })
        (inv + bill).action_post()
        self._sync()
        line_131 = self.env['vas.sync']._vas_find_131_331_line(inv, '131')
        line_331 = self.env['vas.sync']._vas_find_131_331_line(bill, '331')
        self.assertTrue(line_131 and line_331)
        offset = self.env['vas.debt.offset'].create({
            'partner_id': self.partner.id,
            'date': DATE,
            'regime_id': self.regime.id,
            'company_id': self.company.id,
            'line_ids': [
                Command.create({
                    'side': 'receivable', 'move_line_id': line_131.id, 'amount': 100_000,
                }),
                Command.create({
                    'side': 'payable', 'move_line_id': line_331.id, 'amount': 100_000,
                }),
            ],
        })
        offset.action_post()
        move = offset.move_id
        self.assertEqual(move.state, 'posted')
        offset.action_cancel()
        self.assertEqual(offset.state, 'cancelled')
        self._assert_reversed_with_je(move, 'C08')
        with self.assertRaises(UserError):
            offset.write({'state': 'draft'})
        print(f'\n=== C08 offset cancelled move={move.state} ===\n')

    def test_c09_import_vat_cancel_and_paid_raise(self):
        decl = self.env['vas.import.vat'].create({
            'date': DATE,
            'partner_id': self.partner.id,
            'amount_vat': 200_000,
            'company_id': self.company.id,
            'regime_id': self.regime.id,
        })
        decl.action_confirm()
        accrual = decl.accrual_move_id
        self.assertEqual(accrual.state, 'posted')
        decl.action_cancel()
        self.assertEqual(decl.state, 'cancelled')
        self._assert_reversed_with_je(accrual, 'C09 confirmed')
        with self.assertRaises(UserError):
            decl.write({'state': 'draft'})

        # PAID → raise (Q6)
        decl2 = self.env['vas.import.vat'].create({
            'date': DATE,
            'partner_id': self.partner.id,
            'amount_vat': 150_000,
            'company_id': self.company.id,
            'regime_id': self.regime.id,
        })
        decl2.action_confirm()
        pay = self.env['account.payment'].create({
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'partner_id': self.partner.id,
            'amount': 150_000,
            'date': DATE,
            'journal_id': self.bank_j.id,
            'company_id': self.company.id,
            'vas_operation_type': 'import_vat_payment',
            'vas_import_vat_id': decl2.id,
        })
        pay.action_post()
        decl2.payment_id = pay
        decl2.action_mark_paid()
        self.assertEqual(decl2.state, 'paid')
        with self.assertRaises(UserError) as err:
            decl2.action_cancel()
        self.assertIn('Hủy khoản nộp', str(err.exception))
        self.assertEqual(decl2.accrual_move_id.state, 'posted')
        print(f'\n=== C09 cancel ok + paid raise ===\n')

    # ------------------------------------------------------------------
    # R01–R03 hủy → xác nhận lại
    # ------------------------------------------------------------------

    def test_r01_invoice_cancel_repost_new_je(self):
        inv = self._out_invoice(amount=80_000)
        self._sync()
        je1 = self._vas_for(inv).filtered(lambda m: m.move_kind == 'sale_inv')[:1]
        self.assertTrue(je1)
        inv.button_draft()
        self._sync()  # đảo khi đang chết
        self._assert_reversed_with_je(je1, 'R01 step reverse')
        inv.action_post()
        self._sync()
        je2 = self._vas_for(inv).filtered(lambda m: m.move_kind == 'sale_inv')[:1]
        self.assertTrue(je2)
        self.assertNotEqual(je1.id, je2.id)
        self.assertEqual(je2.state, 'posted')
        lives = self._vas_for(inv).filtered(lambda m: m.move_kind == 'sale_inv')
        self.assertEqual(len(lives), 1, 'R01 không được trùng JE sống')
        print(f'\n=== R01 je1={je1.name}→reversed je2={je2.name} ===\n')

    def test_r02_payment_cancel_new_payment(self):
        pay = self._payment(amount=33_000)
        self._sync()
        je1 = self._vas_for(pay).filtered(lambda m: m.move_kind == 'payment')[:1]
        pay.action_cancel()
        self._sync()
        self._assert_reversed_with_je(je1, 'R02')
        pay2 = self._payment(amount=33_000)
        self._sync()
        je2 = self._vas_for(pay2).filtered(lambda m: m.move_kind == 'payment')[:1]
        self.assertTrue(je2 and je2.state == 'posted')
        print(f'\n=== R02 new payment JE={je2.name} ===\n')

    def test_r03_expense_refuse_reapprove(self):
        expense = self._expense_approved(total=70_000)
        self._sync()
        je1 = self._vas_for(expense).filtered(lambda m: m.move_kind == 'expense')[:1]
        expense._do_refuse('r03')
        self._sync()
        self._assert_reversed_with_je(je1, 'R03 reverse')
        expense.action_reset()
        expense.action_submit()
        if expense.state != 'approved':
            expense.action_approve()
        self.assertEqual(expense.state, 'approved')
        self._sync()
        je2 = self._vas_for(expense).filtered(lambda m: m.move_kind == 'expense')[:1]
        self.assertTrue(je2)
        self.assertNotEqual(je1.id, je2.id)
        self.assertEqual(len(self._vas_for(expense).filtered(
            lambda m: m.move_kind == 'expense')), 1)
        print(f'\n=== R03 je1={je1.name} je2={je2.name} ===\n')

    # ------------------------------------------------------------------
    # P01–P02 kỳ
    # ------------------------------------------------------------------

    def test_p01_reverse_same_open_period_date(self):
        inv = self._out_invoice(date=DATE)
        self._sync()
        orig = self._vas_for(inv).filtered(lambda m: m.move_kind == 'sale_inv')[:1]
        orig_date = orig.date
        inv.button_draft()
        inv.button_cancel()
        self._sync()
        rev = self._assert_reversed_with_je(orig, 'P01')
        self.assertEqual(rev.date, orig_date, 'P01 ngày đảo = ngày gốc (kỳ mở)')
        self.assertEqual(rev.period_id, orig.period_id)
        print(f'\n=== P01 reverse_date={rev.date} period={rev.period_id.name} ===\n')

    def test_p02_closed_period_flag_no_auto_reverse(self):
        inv = self._out_invoice(date=DATE)
        self._sync()
        orig = self._vas_for(inv).filtered(lambda m: m.move_kind == 'sale_inv')[:1]
        self.assertTrue(orig)
        self.assertEqual(orig.period_id, self.period_mar)
        # Clear default-account flags so close logic isn't the concern; force SQL.
        self._force_close_period(self.period_mar)
        inv.button_draft()
        inv.button_cancel()
        stats = self._sync()
        cr = stats.get('cancel_regression') or {}
        orig.invalidate_recordset()
        self.assertEqual(orig.state, 'posted', 'P02 không đảo tự động kỳ khóa')
        self.assertTrue(orig.source_cancel_pending, 'P02 phải gắn cờ')
        self.assertGreaterEqual(cr.get('closed_period_flagged', 0), 1, cr)
        self.assertEqual(cr.get('reversed', 0), 0)
        # Reopen for other tests in same class transaction? each test is isolated.
        print(f'\n=== P02 flagged stats={cr} pending={orig.source_cancel_pending} ===\n')

    # ------------------------------------------------------------------
    # N01 / N02 / N04
    # ------------------------------------------------------------------

    def test_n01_already_reversed_idempotent(self):
        inv = self._out_invoice(amount=55_000)
        self._sync()
        orig = self._vas_for(inv).filtered(lambda m: m.move_kind == 'sale_inv')[:1]
        inv.button_draft()
        stats1 = self._sync()
        self._assert_reversed_with_je(orig, 'N01 first')
        rev_id = orig.reversal_move_id.id
        stats2 = self._sync()
        cr2 = stats2.get('cancel_regression') or {}
        self.assertEqual(orig.reversal_move_id.id, rev_id)
        # Second pass: nguồn vẫn draft/dead nhưng JE đã reversed → 0 đảo thêm trên orig
        self.assertEqual(cr2.get('reversed', 0), 0, cr2)
        print(f'\n=== N01 idempotent stats2={cr2} ===\n')

    def test_n02_manual_je_untouched(self):
        journal = self.env['vas.journal'].search([
            ('company_id', '=', self.company.id),
        ], limit=1)
        move = self.env['vas.move'].create({
            'date': DATE,
            'journal_id': journal.id,
            'regime_id': self.regime.id,
            'move_kind': 'manual',
            'company_id': self.company.id,
            'currency_id': self.vnd.id,
            'line_ids': [
                Command.create({
                    'account_id': self._acc('111').id,
                    'name': 'manual',
                    'debit': 10_000,
                    'credit': 0,
                }),
                Command.create({
                    'account_id': self._acc('5111').id,
                    'name': 'manual',
                    'debit': 0,
                    'credit': 10_000,
                }),
            ],
        })
        move.action_post()
        self._sync()
        move.invalidate_recordset()
        self.assertEqual(move.state, 'posted')
        self.assertFalse(move.source_cancel_pending)
        print(f'\n=== N02 manual still posted {move.name} ===\n')

    def test_n04_unlink_source_reverses(self):
        inv = self._out_invoice(amount=44_000)
        self._sync()
        orig = self._vas_for(inv).filtered(lambda m: m.move_kind == 'sale_inv')[:1]
        self.assertTrue(orig)
        inv.button_draft()
        inv.button_cancel()
        inv.unlink()
        self.assertFalse(inv.exists())
        self._sync()
        orig.invalidate_recordset()
        self._assert_reversed_with_je(orig, 'N04 unlink')
        print(f'\n=== N04 unlink → reversed {orig.name} ===\n')
