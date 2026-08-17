# -*- coding: utf-8 -*-
"""W2 — Mua xương sống: chấm M02/M05/M06/T02 theo khớp hiệu quả."""
from collections import defaultdict

from odoo import Command, fields
from odoo.tests import tagged, TransactionCase
from odoo.tools import float_compare


@tagged('connecta_vas', 'connecta_vas_w2')
class TestW2Mua(TransactionCase):
    """R06 receipt + R07 tax bill + R18 payment_out."""

    UNTAXED = 1_000_000.0
    TAX_RATE = 10.0
    QTY = 1.0

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
        cls._ensure_w2_rules()

        fy = cls.env['vas.fiscalyear'].search([
            ('company_id', '=', cls.company.id),
            ('date_from', '<=', '2099-03-15'),
            ('date_to', '>=', '2099-03-15'),
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

        cls.partner = cls.env['res.partner'].create({
            'name': 'NCC W2 Test',
            'company_id': cls.company.id,
            'supplier_rank': 1,
        })
        cls.tax = cls._make_purchase_tax_10()
        cls.product = cls.env['product.product'].create({
            'name': 'HH W2 Test',
            'is_storable': True,
            'list_price': cls.UNTAXED,
            'standard_price': cls.UNTAXED,
            'supplier_taxes_id': [Command.set(cls.tax.ids)],
            'uom_id': cls.env.ref('uom.product_uom_unit').id,
            'purchase_ok': True,
        })
        cls.purchase_journal = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id),
            ('type', '=', 'purchase'),
        ], limit=1)
        cls.bank_journal = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id),
            ('type', '=', 'bank'),
        ], limit=1)
        assert cls.purchase_journal and cls.bank_journal, 'Need purchase + bank journals'

        cls.TAX = cls.UNTAXED * cls.TAX_RATE / 100.0
        cls.TOTAL = cls.UNTAXED + cls.TAX

    @classmethod
    def _ensure_w2_rules(cls):
        Rule = cls.env['vas.rule']
        regime = cls.company.vas_regime_id
        specs = {
            'R06': {
                'name': 'Nhập kho mua hàng',
                'event_type': 'purchase_receipt',
                'sequence': 40,
                'lines': [
                    ('debit', 'product_inventory', 'stock_value'),
                    ('credit', 'receipt_counterpart', 'stock_value'),
                ],
            },
            'R07': {
                'name': 'Hóa đơn mua (thuế)',
                'event_type': 'purchase_invoice',
                'sequence': 50,
                'lines': [
                    ('debit', 'tax_input', 'tax'),
                    ('credit', 'partner_payable', 'tax'),
                ],
            },
            'R18': {
                'name': 'Chi trả NCC',
                'event_type': 'payment_out',
                'sequence': 60,
                'lines': [
                    ('debit', 'partner_payable', 'paid'),
                    ('credit', 'bank_cash', 'paid'),
                ],
            },
        }
        for code, spec in specs.items():
            existing = Rule.search([('regime_id', '=', regime.id), ('code', '=', code)], limit=1)
            if existing:
                if code == 'R06':
                    credit = existing.line_ids.filtered(lambda l: l.side == 'credit')[:1]
                    if credit and credit.account_selector == 'partner_payable':
                        credit.account_selector = 'receipt_counterpart'
                continue
            Rule.create({
                'code': code,
                'name': spec['name'],
                'regime_id': regime.id,
                'event_type': spec['event_type'],
                'sequence': spec['sequence'],
                'active': True,
                'line_ids': [
                    Command.create({
                        'sequence': (i + 1) * 10,
                        'side': side,
                        'account_selector': sel,
                        'amount_selector': amt,
                    })
                    for i, (side, sel, amt) in enumerate(spec['lines'])
                ],
            })

    @classmethod
    def _make_purchase_tax_10(cls):
        Tax = cls.env['account.tax']
        existing = Tax.search([
            ('company_id', '=', cls.company.id),
            ('type_tax_use', '=', 'purchase'),
            ('amount', '=', 10.0),
            ('amount_type', '=', 'percent'),
        ], limit=1)
        if existing:
            return existing
        template = Tax.search([
            ('company_id', '=', cls.company.id),
            ('type_tax_use', '=', 'purchase'),
            ('amount_type', '=', 'percent'),
        ], limit=1)
        if template:
            return template.copy({'name': 'GTGT 10% W2 mua', 'amount': 10.0})
        return Tax.create({
            'name': 'GTGT 10% W2 mua',
            'amount': 10.0,
            'amount_type': 'percent',
            'type_tax_use': 'purchase',
            'company_id': cls.company.id,
        })

    def _create_po_receive_bill_pay(self, receive_date, bill_date, pay_date, do_pay=True):
        po = self.env['purchase.order'].create({
            'partner_id': self.partner.id,
            'company_id': self.company.id,
            'date_order': receive_date,
            'order_line': [Command.create({
                'product_id': self.product.id,
                'name': self.product.name,
                'product_qty': self.QTY,
                'price_unit': self.UNTAXED,
                'tax_ids': [Command.set(self.tax.ids)],
            })],
        })
        po.button_confirm()
        picking = po.picking_ids.filtered(lambda p: p.state != 'done')[:1]
        self.assertTrue(picking, 'PO must create receipt picking')
        for move in picking.move_ids:
            move.quantity = self.QTY
        picking.button_validate()
        receipt = picking.move_ids.filtered(lambda m: m.state == 'done')[:1]
        receipt.write({'date': fields.Datetime.to_datetime(receive_date)})
        # Ensure valued for R06
        if float_compare(receipt.value or 0.0, 0.0, precision_digits=2) == 0:
            receipt.value = self.UNTAXED * self.QTY

        bill = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': self.partner.id,
            'invoice_date': bill_date,
            'date': bill_date,
            'journal_id': self.purchase_journal.id,
            'company_id': self.company.id,
            'invoice_line_ids': [Command.create({
                'product_id': self.product.id,
                'name': self.product.name,
                'quantity': self.QTY,
                'price_unit': self.UNTAXED,
                'tax_ids': [Command.set(self.tax.ids)],
                'purchase_line_id': po.order_line[:1].id,
            })],
        })
        bill.action_post()
        self.assertAlmostEqual(bill.amount_untaxed, self.UNTAXED)
        self.assertAlmostEqual(bill.amount_tax, self.TAX)

        payment = self.env['account.payment']
        if do_pay:
            payment = self.env['account.payment'].create({
                'payment_type': 'outbound',
                'partner_type': 'supplier',
                'partner_id': self.partner.id,
                'amount': self.TOTAL,
                'date': pay_date,
                'journal_id': self.bank_journal.id,
                'company_id': self.company.id,
                'currency_id': self.vnd.id,
            })
            payment.action_post()
        return receipt, bill, payment

    def _sync(self):
        return self.env['vas.sync'].sync_company(
            self.company, date_from='2099-01-01', date_to='2099-12-31',
        )

    def _moves_for(self, *records):
        Move = self.env['vas.move']
        kind_map = {
            'account.move': 'purchase_inv',
            'stock.move': 'stock',
            'account.payment': 'payment',
        }
        moves = Move
        for rec in records:
            if not rec:
                continue
            moves |= Move.search([
                ('source_model', '=', rec._name),
                ('source_res_id', '=', rec.id),
                ('move_kind', '=', kind_map[rec._name]),
                ('state', '=', 'posted'),
            ])
        return moves

    def _net_balances(self, moves):
        bal = defaultdict(float)
        for line in moves.mapped('line_ids'):
            bal[line.account_id.code] += line.debit - line.credit
        return {k: round(v, 2) for k, v in bal.items()}

    def _expected_full(self):
        return {
            '156': self.UNTAXED,
            '1331': self.TAX,
            '331': 0.0,
            '112': -self.TOTAL,
        }

    def _grade(self, scenario, moves, expected):
        bal = self._net_balances(moves)
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
        report = (
            f"\n=== {scenario}: {status} ===\n"
            f"Balances: {dict(sorted(bal.items()))}\n"
            f"Expected: {expected}\n"
            f"Lines:\n" + ('\n'.join(lines) if lines else '  (none)') + '\n'
            + (f"Diffs: {diffs}\n" if diffs else '')
        )
        print(report)
        return status, bal, diffs, report

    def test_w2_m02_hoa_don_va_nhap_kho(self):
        """M02: nhập + HĐ + thanh toán — khớp hiệu quả (331 về 0)."""
        receipt, bill, payment = self._create_po_receive_bill_pay(
            '2099-03-10', '2099-03-10', '2099-03-20',
        )
        self._sync()
        moves = self._moves_for(receipt, bill, payment)
        status, bal, diffs, _ = self._grade('M02', moves, self._expected_full())
        # Evidence: receipt value feeds 156
        self.assertAlmostEqual(abs(receipt.value), self.UNTAXED)
        self.assertEqual(status, 'ĐẠT', diffs)
        self.assertAlmostEqual(bal.get('156', 0.0), self.UNTAXED)
        self.assertAlmostEqual(bal.get('1331', 0.0), self.TAX)

    def test_w2_m05_mua_chiu(self):
        """M05: mua chịu — nhận/HĐ trước, trả sau."""
        receipt, bill, payment = self._create_po_receive_bill_pay(
            '2099-03-05', '2099-03-05', '2099-03-25',
        )
        self._sync()
        moves = self._moves_for(receipt, bill, payment)
        status, _bal, diffs, _ = self._grade('M05', moves, self._expected_full())
        self.assertEqual(status, 'ĐẠT', diffs)

    def test_w2_m06_thanh_toan_ngay(self):
        """M06: thanh toán ngay — 331 trung chuyển về 0 (khớp hiệu quả)."""
        receipt, bill, payment = self._create_po_receive_bill_pay(
            '2099-03-15', '2099-03-15', '2099-03-15',
        )
        self._sync()
        moves = self._moves_for(receipt, bill, payment)
        status, _bal, diffs, _ = self._grade('M06', moves, self._expected_full())
        self.assertEqual(status, 'ĐẠT', diffs)

    def test_w2_t02_chi_tra_ncc(self):
        """T02: chỉ sự kiện chi trả — Nợ 331 / Có 112."""
        payment = self.env['account.payment'].create({
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'partner_id': self.partner.id,
            'amount': self.TOTAL,
            'date': '2099-03-18',
            'journal_id': self.bank_journal.id,
            'company_id': self.company.id,
            'currency_id': self.vnd.id,
        })
        payment.action_post()
        self._sync()
        moves = self._moves_for(payment)
        expected = {'331': self.TOTAL, '112': -self.TOTAL}
        status, bal, diffs, _ = self._grade('T02', moves, expected)
        self.assertEqual(status, 'ĐẠT', diffs)
        self.assertAlmostEqual(bal.get('331', 0.0), self.TOTAL)
        self.assertAlmostEqual(bal.get('112', 0.0), -self.TOTAL)
