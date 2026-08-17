# -*- coding: utf-8 -*-
"""Fixtures TT133 — GTGT hàng NK đường B (vas.import.vat + R27).

  (a) xác nhận tờ khai → Nợ 1331 / Có 33312 (M11-3);
  (b) nộp qua payment nhãn import_vat_payment → Nợ 33312 / Có 111|112;
      R18 KHÔNG ghi trùng Nợ 331 / Có 112;
  (c) cùng lô: thuế NK landed (3333) + GTGT NK (33312) không lẫn.

Ngoài phạm vi: nộp ngoài Odoo, nhánh 151, R24.
"""
from collections import defaultdict

from odoo import Command, fields
from odoo.tests import tagged, TransactionCase
from odoo.tools import float_compare


DATE = '2099-10-05'
VAT_AMT = 200_000.0
DUTY_AMT = 100_000.0
QTY = 10.0
PRICE = 100_000.0


@tagged('connecta_vas', 'connecta_vas_import_vat', 'post_install', '-at_install')
class TestTt133ImportVat(TransactionCase):
    """M11-3 / M11-7 — GTGT hàng NK qua chứng từ VAS + payment nhãn."""

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
        cls._ensure_period()
        cls._ensure_r27()

        cls.partner_hq = cls.env['res.partner'].create({
            'name': 'HQ / NSNN Import VAT Test',
            'company_id': cls.company.id,
            'supplier_rank': 1,
        })
        cls.bank_journal = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id),
            ('type', '=', 'bank'),
        ], limit=1)
        assert cls.bank_journal, 'Thiếu journal bank'

        if 'stock.landed.cost' in cls.env:
            cls._landed_ready = True
            cls._setup_landed_side()
        else:
            cls._landed_ready = False

    @classmethod
    def _acc(cls, code):
        account = cls.env['vas.account'].search([
            ('regime_id', '=', cls.company.vas_regime_id.id),
            ('code', '=', code),
        ], limit=1)
        assert account, f'Thiếu TK VAS {code}'
        return account

    @classmethod
    def _ensure_period(cls):
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

    @classmethod
    def _ensure_r27(cls):
        Rule = cls.env['vas.rule']
        regime = cls.company.vas_regime_id
        if Rule.search([('regime_id', '=', regime.id), ('code', '=', 'R27')], limit=1):
            return
        Rule.create({
            'code': 'R27',
            'name': 'M11-7 · Nợ 33312 / Có 111|112 · TT133 Điều 41',
            'regime_id': regime.id,
            'event_type': 'import_vat_payment',
            'condition': (
                '[("vas_operation_type", "=", "import_vat_payment"), '
                '("payment_type", "=", "outbound")]'
            ),
            'sequence': 61,
            'active': True,
            'line_ids': [
                Command.create({
                    'sequence': 10,
                    'side': 'debit',
                    'account_selector': 'tax_import_vat_payable',
                    'amount_selector': 'paid',
                }),
                Command.create({
                    'sequence': 20,
                    'side': 'credit',
                    'account_selector': 'bank_cash',
                    'amount_selector': 'paid',
                }),
            ],
        })

    @classmethod
    def _setup_landed_side(cls):
        cls.partner_vendor = cls.env['res.partner'].create({
            'name': 'NCC mixed duty+VAT',
            'company_id': cls.company.id,
            'supplier_rank': 1,
        })
        cls.cat_hh = cls.env['product.category'].create({
            'name': 'HH Import VAT Mixed FIFO',
            'property_cost_method': 'fifo',
            'property_valuation': 'real_time',
        })
        cls.env['vas.account.map'].create({
            'regime_id': cls.company.vas_regime_id.id,
            'apply_to': 'category',
            'company_id': cls.company.id,
            'category_id': cls.cat_hh.id,
            'stock_account_id': cls._acc('156').id,
        })
        uom = cls.env.ref('uom.product_uom_unit')
        cls.p_goods = cls.env['product.product'].create({
            'name': 'IMP-VAT-HH',
            'is_storable': True,
            'categ_id': cls.cat_hh.id,
            'standard_price': PRICE,
            'uom_id': uom.id,
            'purchase_ok': True,
        })
        cls.duty = cls.env['product.product'].create({
            'name': 'Thuế NK mixed test',
            'type': 'service',
            'landed_cost_ok': True,
            'purchase_ok': True,
            'sale_ok': False,
            'split_method_landed_cost': 'equal',
        })
        cls.env['vas.landed.tax.map'].create({
            'regime_id': cls.regime.id,
            'apply_to': 'product',
            'product_id': cls.duty.product_tmpl_id.id,
            'credit_account_id': cls._acc('3333').id,
            'company_id': cls.company.id,
        })
        cls.lc_journal = (
            cls.company.lc_journal_id
            or cls.env['account.journal'].search([
                ('company_id', '=', cls.company.id),
                ('type', '=', 'general'),
            ], limit=1)
        )
        if cls.lc_journal and not cls.company.lc_journal_id:
            cls.company.lc_journal_id = cls.lc_journal
        # R25 credit selector
        r25 = cls.env['vas.rule'].search([
            ('regime_id', '=', cls.regime.id), ('code', '=', 'R25'),
        ], limit=1)
        if r25:
            credit = r25.line_ids.filtered(lambda l: l.side == 'credit')[:1]
            if credit and credit.account_selector == 'partner_payable':
                credit.account_selector = 'landed_counterpart'
        else:
            cls.env['vas.rule'].create({
                'code': 'R25',
                'name': 'Vốn hóa landed',
                'regime_id': cls.regime.id,
                'event_type': 'landed_cost_adjust',
                'sequence': 45,
                'active': True,
                'line_ids': [
                    Command.create({
                        'sequence': 10,
                        'side': 'debit',
                        'account_selector': 'product_inventory',
                        'amount_selector': 'landed_cost',
                    }),
                    Command.create({
                        'sequence': 20,
                        'side': 'credit',
                        'account_selector': 'landed_counterpart',
                        'amount_selector': 'landed_cost',
                    }),
                ],
            })

    def _sync(self):
        return self.env['vas.sync'].sync_company(
            self.company, date_from='2099-01-01', date_to='2099-12-31',
        )

    def _net(self, moves):
        bal = defaultdict(float)
        for line in moves.mapped('line_ids'):
            bal[line.account_id.code] += (line.debit or 0.0) - (line.credit or 0.0)
        return dict(bal)

    def _make_declaration(self, amount=VAT_AMT):
        return self.env['vas.import.vat'].create({
            'date': DATE,
            'partner_id': self.partner_hq.id,
            'amount_vat': amount,
            'company_id': self.company.id,
            'regime_id': self.regime.id,
            'ref': 'TK test GTGT NK',
        })

    def _make_vat_payment(self, amount=VAT_AMT, declaration=None):
        payment = self.env['account.payment'].create({
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'partner_id': self.partner_hq.id,
            'amount': amount,
            'date': DATE,
            'journal_id': self.bank_journal.id,
            'company_id': self.company.id,
            'vas_operation_type': 'import_vat_payment',
            'vas_import_vat_id': declaration.id if declaration else False,
        })
        payment.action_post()
        return payment

    def test_a_confirm_accrual_1331_33312(self):
        """(a) Xác nhận tờ khai → Nợ 1331 / Có 33312."""
        decl = self._make_declaration()
        decl.action_confirm()
        self.assertEqual(decl.state, 'confirmed')
        self.assertTrue(decl.accrual_move_id)
        move = decl.accrual_move_id
        self.assertEqual(move.move_kind, 'import_vat')
        self.assertIn('M11-3', move.ref or '')
        self.assertIn('Điều 18', move.ref or '')
        bal = self._net(move)
        self.assertAlmostEqual(bal.get('1331', 0.0), VAT_AMT, delta=1)
        self.assertAlmostEqual(bal.get('33312', 0.0), -VAT_AMT, delta=1)
        self.assertNotIn('156', bal)
        self.assertNotIn('3333', bal)
        print(f'\n=== (a) M11-3 ===\n  {bal}\n  ref={move.ref}\n')

    def test_b_pay_via_labeled_payment_no_r18(self):
        """(b) R27 Nợ 33312/Có 112; R18 không ghi 331 trên cùng payment."""
        decl = self._make_declaration()
        decl.action_confirm()
        payment = self._make_vat_payment(declaration=decl)
        decl.payment_id = payment
        decl.action_mark_paid()
        self.assertEqual(decl.state, 'paid')
        self.assertFalse(decl.pending_odoo_payment)

        stats = self._sync()
        r27 = stats.get('import_vat_payment') or {}
        self.assertGreaterEqual(r27.get('created', 0), 1, r27)

        pay_moves = self.env['vas.move'].search([
            ('source_model', '=', 'account.payment'),
            ('source_res_id', '=', payment.id),
            ('state', '=', 'posted'),
            ('is_reversal', '=', False),
        ])
        kinds = set(pay_moves.mapped('move_kind'))
        self.assertIn('import_vat_payment', kinds)
        self.assertNotIn(
            'payment', kinds,
            'R18 không được sinh move_kind=payment trên payment nhãn import_vat',
        )
        r27_move = pay_moves.filtered(lambda m: m.move_kind == 'import_vat_payment')
        self.assertEqual(len(r27_move), 1)
        self.assertIn('M11-7', r27_move.ref or '')
        bal = self._net(r27_move)
        self.assertAlmostEqual(bal.get('33312', 0.0), VAT_AMT, delta=1)
        # Có 111 hoặc 112
        cash_credit = -(bal.get('112', 0.0) + bal.get('111', 0.0))
        self.assertAlmostEqual(cash_credit, VAT_AMT, delta=1)
        self.assertNotIn('331', bal)
        # Accrual vẫn 1331/33312; sau nộp net 33312 trên 2 moves = 0
        accrual_bal = self._net(decl.accrual_move_id)
        self.assertAlmostEqual(accrual_bal.get('33312', 0.0), -VAT_AMT, delta=1)
        print(
            f'\n=== (b) M11-7 + no R18 ===\n'
            f'  R27 {bal}\n  kinds={kinds}\n  stats={r27}\n'
        )

    def test_b2_unlabeled_sets_pending_flag(self):
        """Không nhãn / không payment → cờ chờ, không tự chế JE nộp."""
        decl = self._make_declaration()
        decl.action_confirm()
        decl.action_mark_paid()
        self.assertEqual(decl.state, 'confirmed')
        self.assertTrue(decl.pending_odoo_payment)
        self.assertFalse(decl.payment_move_id)

    def test_c_duty_and_import_vat_no_overlap(self):
        """(c) Thuế NK 3333 (R25) + GTGT NK 33312 (chứng từ) — không lẫn."""
        if not self._landed_ready:
            self.skipTest('stock_landed_costs chưa có')

        # --- GTGT NK ---
        decl = self._make_declaration(amount=VAT_AMT)
        decl.action_confirm()
        bal_vat = self._net(decl.accrual_move_id)
        self.assertAlmostEqual(bal_vat.get('33312', 0.0), -VAT_AMT, delta=1)
        self.assertNotIn('3333', bal_vat)

        # --- Thuế NK qua LC ---
        po = self.env['purchase.order'].create({
            'partner_id': self.partner_vendor.id,
            'company_id': self.company.id,
            'date_order': DATE,
            'order_line': [Command.create({
                'product_id': self.p_goods.id,
                'name': self.p_goods.name,
                'product_qty': QTY,
                'price_unit': PRICE,
                'tax_ids': [Command.clear()],
            })],
        })
        po.button_confirm()
        picking = po.picking_ids.filtered(lambda p: p.state != 'done')[:1]
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
        picking.button_validate()
        for m in picking.move_ids.filtered(lambda x: x.state == 'done'):
            m.write({'date': fields.Datetime.to_datetime(DATE)})
            if float_compare(m.value or 0.0, 0.0, precision_digits=2) == 0:
                m.value = (m.quantity or 0.0) * (m.price_unit or 0.0)
        self._sync()

        expense = self.duty.product_tmpl_id.get_product_accounts().get('expense')
        self.assertTrue(expense)
        lc = self.env['stock.landed.cost'].create({
            'date': DATE,
            'company_id': self.company.id,
            'account_journal_id': self.lc_journal.id,
            'picking_ids': [Command.set(picking.ids)],
            'cost_lines': [Command.create({
                'product_id': self.duty.id,
                'name': self.duty.name,
                'price_unit': DUTY_AMT,
                'split_method': 'equal',
                'account_id': expense.id,
            })],
        })
        lc.compute_landed_cost()
        lc.button_validate()
        stats = self._sync()
        self.assertGreaterEqual(
            (stats.get('landed_cost_adjust') or {}).get('tax_created', 0), 1,
            stats.get('landed_cost_adjust'),
        )
        duty_moves = self.env['vas.move']
        for adj in lc.valuation_adjustment_lines:
            duty_moves |= self.env['vas.move'].search([
                ('source_model', '=', 'stock.valuation.adjustment.lines'),
                ('source_res_id', '=', adj.id),
                ('move_kind', '=', 'landed'),
                ('state', '=', 'posted'),
                ('is_reversal', '=', False),
            ])
        bal_duty = self._net(duty_moves)
        self.assertAlmostEqual(bal_duty.get('3333', 0.0), -DUTY_AMT, delta=1)
        self.assertNotIn('33312', bal_duty)
        self.assertAlmostEqual(bal_duty.get('156', 0.0), DUTY_AMT, delta=1)

        print(
            f'\n=== (c) no overlap ===\n'
            f'  GTGT NK {bal_vat}\n'
            f'  thuế NK {bal_duty}\n'
        )
