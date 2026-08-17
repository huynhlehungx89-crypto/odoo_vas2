# -*- coding: utf-8 -*-
"""Fixtures TT133 — R25 nhánh thuế NK (Có 3333) qua vas.landed.tax.map.

  (a) LC thuế NK trên phiếu 2 SP → Nợ 156 từng SP đúng phân bổ Odoo / Có 3333;
  (b) LC thuế NK không vendor_bill → vẫn ghi, không cờ no-bill;
  (c) cùng phiếu: cước Có 331 + thuế Có 3333, không chồng.

Nhánh 151 / GTGT NK 33312 / R24 — ngoài phạm vi.
"""
from collections import defaultdict

from odoo import Command, fields
from odoo.tests import tagged, TransactionCase
from odoo.tools import float_compare


DATE = '2099-09-10'
# Hai SP cùng former_cost 1tr → by_current_cost chia đều thuế
QTY_A = 10.0
PRICE_A = 100_000.0  # former 1_000_000
QTY_B = 5.0
PRICE_B = 200_000.0  # former 1_000_000
DUTY_AMT = 300_000.0
FREIGHT_AMT = 50_000.0


@tagged('connecta_vas', 'connecta_vas_landed_tax', 'post_install', '-at_install')
class TestTt133LandedImportTax(TransactionCase):
    """R25 Path A: thuế NK vốn hóa Nợ 156 / Có 3333 (M11-2 nhánh 156)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if 'stock.landed.cost' not in cls.env:
            cls._landed_ready = False
            return
        cls._landed_ready = True

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
        cls._ensure_rules()
        cls._ensure_period()

        cls.partner = cls.env['res.partner'].create({
            'name': 'NCC Import Tax Test',
            'company_id': cls.company.id,
            'supplier_rank': 1,
        })
        cls.partner_freight = cls.env['res.partner'].create({
            'name': 'NCC Cước + Thuế',
            'company_id': cls.company.id,
            'supplier_rank': 1,
        })

        cls.cat_hh = cls.env['product.category'].create({
            'name': 'HH Import Tax FIFO',
            'property_cost_method': 'fifo',
            'property_valuation': 'real_time',
        })
        cls._map_stock(cls.cat_hh, '156')

        uom = cls.env.ref('uom.product_uom_unit')
        cls.p_a = cls.env['product.product'].create({
            'name': 'IMP-TAX-A',
            'is_storable': True,
            'categ_id': cls.cat_hh.id,
            'standard_price': PRICE_A,
            'uom_id': uom.id,
            'purchase_ok': True,
        })
        cls.p_b = cls.env['product.product'].create({
            'name': 'IMP-TAX-B',
            'is_storable': True,
            'categ_id': cls.cat_hh.id,
            'standard_price': PRICE_B,
            'uom_id': uom.id,
            'purchase_ok': True,
        })
        cls.duty = cls.env['product.product'].create({
            'name': 'Thuế NK R25 Test',
            'type': 'service',
            'landed_cost_ok': True,
            'purchase_ok': True,
            'sale_ok': False,
            'split_method_landed_cost': 'by_current_cost_price',
        })
        cls.freight = cls.env['product.product'].create({
            'name': 'Cước R25 Mixed',
            'type': 'service',
            'landed_cost_ok': True,
            'purchase_ok': True,
            'sale_ok': False,
            'split_method_landed_cost': 'equal',
        })

        cls.acc_3333 = cls._acc('3333')
        cls.env['vas.landed.tax.map'].create({
            'regime_id': cls.regime.id,
            'apply_to': 'product',
            'product_id': cls.duty.product_tmpl_id.id,
            'credit_account_id': cls.acc_3333.id,
            'company_id': cls.company.id,
        })

        cls.purchase_journal = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id),
            ('type', '=', 'purchase'),
        ], limit=1)
        cls.lc_journal = (
            cls.company.lc_journal_id
            or cls.env['account.journal'].search([
                ('company_id', '=', cls.company.id),
                ('type', '=', 'general'),
            ], limit=1)
        )
        assert cls.purchase_journal and cls.lc_journal
        if not cls.company.lc_journal_id:
            cls.company.lc_journal_id = cls.lc_journal

    @classmethod
    def _acc(cls, code):
        account = cls.env['vas.account'].search([
            ('regime_id', '=', cls.company.vas_regime_id.id),
            ('code', '=', code),
        ], limit=1)
        assert account, f'Thiếu TK VAS {code}'
        return account

    @classmethod
    def _map_stock(cls, category, code):
        return cls.env['vas.account.map'].create({
            'regime_id': cls.company.vas_regime_id.id,
            'apply_to': 'category',
            'company_id': cls.company.id,
            'category_id': category.id,
            'stock_account_id': cls._acc(code).id,
        })

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
    def _ensure_rules(cls):
        Rule = cls.env['vas.rule']
        regime = cls.company.vas_regime_id
        if not Rule.search([('regime_id', '=', regime.id), ('code', '=', 'R25')], limit=1):
            Rule.create({
                'code': 'R25',
                'name': 'Vốn hóa landed',
                'regime_id': regime.id,
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
        else:
            # DB cũ có thể còn partner_payable trên credit R25
            line = Rule.search([
                ('regime_id', '=', regime.id), ('code', '=', 'R25'),
            ], limit=1).line_ids.filtered(lambda l: l.side == 'credit')[:1]
            if line and line.account_selector == 'partner_payable':
                line.account_selector = 'landed_counterpart'

    def _require_landed(self):
        if not getattr(self, '_landed_ready', False):
            self.skipTest('stock_landed_costs chưa có')

    def _sync(self):
        return self.env['vas.sync'].sync_company(
            self.company, date_from='2099-01-01', date_to='2099-12-31',
        )

    def _net(self, moves):
        bal = defaultdict(float)
        for line in moves.mapped('line_ids'):
            bal[line.account_id.code] += (line.debit or 0.0) - (line.credit or 0.0)
        return dict(bal)

    def _vas_for_adj(self, adj):
        return self.env['vas.move'].search([
            ('source_model', '=', 'stock.valuation.adjustment.lines'),
            ('source_res_id', '=', adj.id),
            ('move_kind', '=', 'landed'),
            ('state', '=', 'posted'),
            ('is_reversal', '=', False),
        ])

    def _receive_two_products(self):
        po = self.env['purchase.order'].create({
            'partner_id': self.partner.id,
            'company_id': self.company.id,
            'date_order': DATE,
            'order_line': [
                Command.create({
                    'product_id': self.p_a.id,
                    'name': self.p_a.name,
                    'product_qty': QTY_A,
                    'price_unit': PRICE_A,
                    'tax_ids': [Command.clear()],
                }),
                Command.create({
                    'product_id': self.p_b.id,
                    'name': self.p_b.name,
                    'product_qty': QTY_B,
                    'price_unit': PRICE_B,
                    'tax_ids': [Command.clear()],
                }),
            ],
        })
        po.button_confirm()
        picking = po.picking_ids.filtered(lambda p: p.state != 'done')[:1]
        self.assertTrue(picking)
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
        picking.button_validate()
        moves = picking.move_ids.filtered(lambda m: m.state == 'done')
        for m in moves:
            m.write({'date': fields.Datetime.to_datetime(DATE)})
            if float_compare(m.value or 0.0, 0.0, precision_digits=2) == 0:
                m.value = (m.quantity or 0.0) * (m.price_unit or 0.0)
        return po, picking, moves

    def _expense_account(self, product):
        acc = product.product_tmpl_id.get_product_accounts().get('expense')
        self.assertTrue(acc, f'Thiếu expense Odoo cho {product.display_name}')
        return acc

    def _validate_lc(self, picking, cost_lines_vals, vendor_bill=None):
        lc = self.env['stock.landed.cost'].create({
            'date': DATE,
            'company_id': self.company.id,
            'account_journal_id': self.lc_journal.id,
            'picking_ids': [Command.set(picking.ids)],
            'vendor_bill_id': vendor_bill.id if vendor_bill else False,
            'cost_lines': [Command.create(v) for v in cost_lines_vals],
        })
        lc.compute_landed_cost()
        lc.button_validate()
        self.assertEqual(lc.state, 'done')
        return lc

    def test_a_duty_allocated_per_product_credit_3333(self):
        """(a) Thuế NK 300k / by_current_cost trên 2 SP former=1tr → 150k mỗi SP."""
        self._require_landed()
        _po, picking, stock_moves = self._receive_two_products()
        self._sync()

        lc = self._validate_lc(picking, [{
            'product_id': self.duty.id,
            'name': self.duty.name,
            'price_unit': DUTY_AMT,
            'split_method': 'by_current_cost_price',
            'account_id': self._expense_account(self.duty).id,
        }])
        adjs = lc.valuation_adjustment_lines
        self.assertEqual(len(adjs), 2)
        by_prod = {a.product_id.id: a for a in adjs}
        self.assertAlmostEqual(
            by_prod[self.p_a.id].additional_landed_cost, 150_000.0, delta=1,
        )
        self.assertAlmostEqual(
            by_prod[self.p_b.id].additional_landed_cost, 150_000.0, delta=1,
        )

        stats = self._sync()
        self.assertGreaterEqual(
            stats.get('landed_cost_adjust', {}).get('tax_created', 0), 2,
            stats.get('landed_cost_adjust'),
        )
        self.assertEqual(
            stats.get('landed_cost_adjust', {}).get('flagged_no_bill', 0), 0,
        )

        credit_3333 = 0.0
        for adj in adjs:
            vm = self._vas_for_adj(adj)
            self.assertEqual(len(vm), 1, f'adj={adj.id} moves={vm}')
            bal = self._net(vm)
            amt = adj.additional_landed_cost
            self.assertAlmostEqual(bal.get('156', 0.0), amt, delta=1, msg=bal)
            self.assertAlmostEqual(bal.get('3333', 0.0), -amt, delta=1, msg=bal)
            self.assertNotIn('331', bal)
            credit_3333 += -bal.get('3333', 0.0)
            print(
                f'  adj {adj.product_id.name}: '
                f'additional={amt} VAS {bal}'
            )
        self.assertAlmostEqual(credit_3333, DUTY_AMT, delta=1)
        print(f'\n=== (a) duty ===\n  Có 3333 tổng={credit_3333}\n')

    def test_b_duty_without_vendor_bill_still_posts(self):
        """(b) Thuế NK không bill → vẫn ghi Có 3333, không cờ no-bill."""
        self._require_landed()
        _po, picking, _moves = self._receive_two_products()
        self._sync()
        lc = self._validate_lc(picking, [{
            'product_id': self.duty.id,
            'name': self.duty.name,
            'price_unit': DUTY_AMT,
            'split_method': 'by_current_cost_price',
            'account_id': self._expense_account(self.duty).id,
        }], vendor_bill=None)
        self.assertFalse(lc.vendor_bill_id)

        stats = self._sync()
        r25 = stats.get('landed_cost_adjust') or {}
        self.assertEqual(r25.get('flagged_no_bill', 0), 0, r25)
        self.assertGreaterEqual(r25.get('created', 0), 2, r25)
        self.assertGreaterEqual(r25.get('tax_created', 0), 2, r25)

        for adj in lc.valuation_adjustment_lines:
            vm = self._vas_for_adj(adj)
            self.assertEqual(len(vm), 1)
            bal = self._net(vm)
            self.assertIn('3333', bal)
            self.assertNotIn('331', bal)
        print(f'\n=== (b) no bill duty ===\n  stats={r25}\n')

    def test_c_mixed_freight_and_duty_no_overlap(self):
        """(c) Cước Có 331 + thuế Có 3333 trên cùng picking — không lẫn."""
        self._require_landed()
        _po, picking, _moves = self._receive_two_products()
        self._sync()

        bill = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': self.partner_freight.id,
            'invoice_date': DATE,
            'date': DATE,
            'journal_id': self.purchase_journal.id,
            'company_id': self.company.id,
            'invoice_line_ids': [Command.create({
                'product_id': self.freight.id,
                'name': self.freight.name,
                'quantity': 1.0,
                'price_unit': FREIGHT_AMT,
                'tax_ids': [Command.clear()],
                'is_landed_costs_line': True,
            })],
        })
        bill.action_post()

        lc = self._validate_lc(picking, [
            {
                'product_id': self.duty.id,
                'name': self.duty.name,
                'price_unit': DUTY_AMT,
                'split_method': 'by_current_cost_price',
                'account_id': self._expense_account(self.duty).id,
            },
            {
                'product_id': self.freight.id,
                'name': self.freight.name,
                'price_unit': FREIGHT_AMT,
                'split_method': 'equal',
                'account_id': self._expense_account(self.freight).id,
            },
        ], vendor_bill=bill)

        stats = self._sync()
        duty_adjs = lc.valuation_adjustment_lines.filtered(
            lambda a: a.cost_line_id.product_id == self.duty
        )
        freight_adjs = lc.valuation_adjustment_lines.filtered(
            lambda a: a.cost_line_id.product_id == self.freight
        )
        self.assertEqual(len(duty_adjs), 2)
        self.assertEqual(len(freight_adjs), 2)

        sum_3333 = sum_331 = sum_156_duty = sum_156_fr = 0.0
        for adj in duty_adjs:
            bal = self._net(self._vas_for_adj(adj))
            self.assertIn('3333', bal, bal)
            self.assertNotIn('331', bal, bal)
            sum_3333 += -bal.get('3333', 0.0)
            sum_156_duty += bal.get('156', 0.0)
        for adj in freight_adjs:
            bal = self._net(self._vas_for_adj(adj))
            self.assertIn('331', bal, bal)
            self.assertNotIn('3333', bal, bal)
            sum_331 += -bal.get('331', 0.0)
            sum_156_fr += bal.get('156', 0.0)

        self.assertAlmostEqual(sum_3333, DUTY_AMT, delta=1)
        self.assertAlmostEqual(sum_331, FREIGHT_AMT, delta=1)
        self.assertAlmostEqual(sum_156_duty, DUTY_AMT, delta=1)
        self.assertAlmostEqual(sum_156_fr, FREIGHT_AMT, delta=1)
        self.assertEqual(
            (stats.get('landed_cost_adjust') or {}).get('flagged_no_bill', 0), 0,
        )
        print(
            f'\n=== (c) mixed ===\n'
            f'  duty 156={sum_156_duty} / 3333={sum_3333}\n'
            f'  freight 156={sum_156_fr} / 331={sum_331}\n'
        )
