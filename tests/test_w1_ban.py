# -*- coding: utf-8 -*-
"""W1 — Bán xương sống: chấm B01/B02/B03/B05 theo khớp hiệu quả."""
from collections import defaultdict

from odoo import Command, fields
from odoo.tests import tagged, TransactionCase
from odoo.tools import float_compare


@tagged('connecta_vas', 'connecta_vas_w1')
class TestW1Ban(TransactionCase):
    """Fixture tối thiểu + vas.sync → so đáp án workbook (khớp hiệu quả)."""

    UNTAXED = 1_000_000.0
    TAX_RATE = 10.0
    COGS = 600_000.0
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

        # Ensure W1 rules exist (XML may not reload in some test paths)
        cls._ensure_w1_rules()

        cls.fiscalyear = cls.env['vas.fiscalyear'].search([
            ('company_id', '=', cls.company.id),
            ('date_from', '<=', '2099-01-15'),
            ('date_to', '>=', '2099-01-15'),
        ], limit=1)
        if not cls.fiscalyear:
            cls.fiscalyear = cls.env['vas.fiscalyear'].create({
                'name': '2099',
                'date_from': '2099-01-01',
                'date_to': '2099-12-31',
                'state': 'open',
                'company_id': cls.company.id,
            })
        cls.period = cls.env['vas.period'].search([
            ('fiscalyear_id', '=', cls.fiscalyear.id),
            ('date_start', '<=', '2099-01-15'),
            ('date_end', '>=', '2099-01-15'),
        ], limit=1)
        if not cls.period:
            cls.period = cls.env['vas.period'].create({
                'name': '01/2099',
                'date_start': '2099-01-01',
                'date_end': '2099-01-31',
                'fiscalyear_id': cls.fiscalyear.id,
                'state': 'open',
            })
        else:
            cls.period.state = 'open'

        cls.partner = cls.env['res.partner'].create({
            'name': 'KH W1 Test',
            'company_id': cls.company.id,
        })

        cls.tax = cls._make_sale_tax_10()

        cls.product = cls.env['product.product'].create({
            'name': 'HH W1 Test',
            'is_storable': True,
            'invoice_policy': 'order',
            'list_price': cls.UNTAXED,
            'standard_price': cls.COGS,
            'taxes_id': [Command.set(cls.tax.ids)],
            'uom_id': cls.env.ref('uom.product_uom_unit').id,
        })

        cls.stock_location = cls.env.ref('stock.stock_location_stock')
        cls.customer_location = cls.env.ref('stock.stock_location_customers')
        cls.env['stock.quant'].with_context(inventory_mode=True).create({
            'product_id': cls.product.id,
            'location_id': cls.stock_location.id,
            'inventory_quantity': 100.0,
        }).action_apply_inventory()

        cls.sale_journal = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id),
            ('type', '=', 'sale'),
        ], limit=1)
        cls.bank_journal = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id),
            ('type', '=', 'bank'),
        ], limit=1)
        cls.assertTrue(cls.sale_journal and cls.bank_journal, 'Need sale + bank journals')

        cls.TAX = cls.UNTAXED * cls.TAX_RATE / 100.0
        cls.TOTAL = cls.UNTAXED + cls.TAX

    @classmethod
    def _ensure_w1_rules(cls):
        Rule = cls.env['vas.rule']
        Account = cls.env['vas.account']
        regime = cls.company.vas_regime_id

        def acc(code):
            rec = Account.search([('regime_id', '=', regime.id), ('code', '=', code)], limit=1)
            assert rec, f'Missing VAS account {code}'
            return rec

        specs = {
            'R01': {
                'name': 'Hóa đơn bán hàng',
                'event_type': 'sale_invoice',
                'sequence': 10,
                'lines': [
                    ('debit', 'partner_receivable', False, 'total'),
                    ('credit', 'product_revenue', False, 'untaxed'),
                    ('credit', 'tax_output', False, 'tax'),
                ],
            },
            'R02': {
                'name': 'Xuất kho bán hàng',
                'event_type': 'sale_delivery',
                'sequence': 20,
                'lines': [
                    ('debit', 'product_cogs', False, 'cogs'),
                    ('credit', 'product_inventory', False, 'cogs'),
                ],
            },
            'R17': {
                'name': 'Thu tiền khách hàng',
                'event_type': 'payment_in',
                'sequence': 30,
                'lines': [
                    ('debit', 'bank_cash', False, 'paid'),
                    ('credit', 'partner_receivable', False, 'paid'),
                ],
            },
        }
        for code, spec in specs.items():
            rule = Rule.search([('regime_id', '=', regime.id), ('code', '=', code)], limit=1)
            if rule:
                continue
            line_cmds = []
            for seq, (side, selector, fixed_code, amount) in enumerate(spec['lines'], start=1):
                vals = {
                    'sequence': seq * 10,
                    'side': side,
                    'account_selector': selector,
                    'amount_selector': amount,
                }
                if selector == 'fixed':
                    vals['account_id'] = acc(fixed_code).id
                line_cmds.append(Command.create(vals))
            Rule.create({
                'code': code,
                'name': spec['name'],
                'regime_id': regime.id,
                'event_type': spec['event_type'],
                'sequence': spec['sequence'],
                'active': True,
                'line_ids': line_cmds,
            })

    @classmethod
    def _make_sale_tax_10(cls):
        Tax = cls.env['account.tax']
        existing = Tax.search([
            ('company_id', '=', cls.company.id),
            ('type_tax_use', '=', 'sale'),
            ('amount', '=', 10.0),
            ('amount_type', '=', 'percent'),
        ], limit=1)
        if existing:
            return existing
        template = Tax.search([
            ('company_id', '=', cls.company.id),
            ('type_tax_use', '=', 'sale'),
            ('amount_type', '=', 'percent'),
        ], limit=1)
        if template:
            return template.copy({
                'name': 'GTGT 10% W1',
                'amount': 10.0,
            })
        return Tax.create({
            'name': 'GTGT 10% W1',
            'amount': 10.0,
            'amount_type': 'percent',
            'type_tax_use': 'sale',
            'company_id': cls.company.id,
        })

    # ------------------------------------------------------------------
    # Document builders
    # ------------------------------------------------------------------

    def _create_invoice(self, date='2099-01-15', sale_order=None):
        if sale_order:
            inv = sale_order._create_invoices()
            inv.invoice_date = date
            inv.date = date
            inv.action_post()
            self.assertAlmostEqual(inv.amount_untaxed, self.UNTAXED)
            self.assertAlmostEqual(inv.amount_tax, self.TAX)
            return inv
        move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'invoice_date': date,
            'date': date,
            'journal_id': self.sale_journal.id,
            'company_id': self.company.id,
            'invoice_line_ids': [Command.create({
                'product_id': self.product.id,
                'name': self.product.name,
                'quantity': self.QTY,
                'price_unit': self.UNTAXED,
                'tax_ids': [Command.set(self.tax.ids)],
            })],
        })
        move.action_post()
        self.assertAlmostEqual(move.amount_untaxed, self.UNTAXED)
        self.assertAlmostEqual(move.amount_tax, self.TAX)
        self.assertAlmostEqual(move.amount_total, self.TOTAL)
        return move

    def _create_sale_order(self, date='2099-01-15'):
        so = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'date_order': date,
            'company_id': self.company.id,
            'order_line': [Command.create({
                'product_id': self.product.id,
                'product_uom_qty': self.QTY,
                'price_unit': self.UNTAXED,
                'tax_ids': [Command.set(self.tax.ids)],
            })],
        })
        so.action_confirm()
        return so

    def _deliver_so(self, so, date='2099-01-15'):
        """Xác nhận hết mọi chặng (ship_only lẫn pick_ship) rồi trả move đi khách."""
        pickings = so.picking_ids
        self.assertTrue(pickings, 'SO has no outgoing picking')
        for _round in range(6):
            pending = pickings.filtered(lambda p: p.state not in ('done', 'cancel'))
            if not pending:
                break
            for pick in pending:
                pick = pick.with_context(skip_sms=True, skip_sanity_check=True)
                pick.action_assign()
                for move in pick.move_ids:
                    move.quantity = move.product_uom_qty
                    move.picked = True
                pick.button_validate()
            pickings |= pickings.mapped('move_ids.move_dest_ids.picking_id')
        done_moves = pickings.mapped('move_ids').filtered(
            lambda m: m.state == 'done' and m.location_dest_usage == 'customer'
        )
        self.assertTrue(done_moves, 'SO chưa có chặng done đi khách')
        done_moves.write({'date': fields.Datetime.to_datetime(date)})
        return done_moves[:1]

    def _create_delivery(self, date='2099-01-15', with_sale_line=True):
        """Legacy helper — returns delivery; SO is on delivery.sale_line_id.order_id."""
        if with_sale_line:
            so = self._create_sale_order(date=date)
            return self._deliver_so(so, date=date)

        move = self.env['stock.move'].create({
            'product_id': self.product.id,
            'product_uom_qty': self.QTY,
            'product_uom': self.product.uom_id.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.customer_location.id,
            'company_id': self.company.id,
            'date': fields.Datetime.to_datetime(date),
        })
        move._action_confirm()
        move.quantity = self.QTY
        move.picked = True
        move._action_done()
        move.write({'date': fields.Datetime.to_datetime(date)})
        return move

    def _create_payment(self, amount=None, date='2099-01-20'):
        payment = self.env['account.payment'].create({
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': self.partner.id,
            'amount': amount if amount is not None else self.TOTAL,
            'date': date,
            'journal_id': self.bank_journal.id,
            'company_id': self.company.id,
            'currency_id': self.vnd.id,
        })
        payment.action_post()
        self.assertIn(payment.state, ('in_process', 'paid'))
        return payment

    def _sync(self):
        return self.env['vas.sync'].sync_company(
            self.company,
            date_from='2099-01-01',
            date_to='2099-12-31',
        )

    def _moves_for_sources(self, *records):
        Move = self.env['vas.move']
        moves = Move
        for rec in records:
            if not rec:
                continue
            if rec._name == 'stock.move':
                domain_kind = ('cogs', 'revenue')
            elif rec._name == 'account.move':
                domain_kind = ('sale_inv',)
            elif rec._name == 'account.payment':
                domain_kind = ('payment',)
            else:
                continue
            found = Move.search([
                ('source_model', '=', rec._name),
                ('source_res_id', '=', rec.id),
                ('move_kind', 'in', domain_kind),
                ('state', '=', 'posted'),
            ])
            moves |= found
        return moves

    def _net_balances(self, moves):
        bal = defaultdict(float)
        for line in moves.mapped('line_ids'):
            bal[line.account_id.code] += line.debit - line.credit
        return {k: round(v, 2) for k, v in bal.items() if float_compare(v, 0.0, 2) != 0 or k == '131'}

    def _expected_full_cycle(self):
        """Net balances after invoice + delivery + payment (bank → 112)."""
        return {
            '131': 0.0,
            '5111': -self.UNTAXED,
            '33311': -self.TAX,
            '632': self.COGS,
            '156': -self.COGS,
            '112': self.TOTAL,
        }

    def _grade(self, scenario, moves, expected):
        bal = self._net_balances(moves)
        lines_dump = []
        for move in moves.sorted(lambda m: (m.date, m.id)):
            for line in move.line_ids.sorted('sequence'):
                lines_dump.append(
                    f"  {move.move_kind} {move.source_ref}: "
                    f"{line.account_id.code} N={line.debit} C={line.credit}"
                )
        diffs = []
        for code, exp in expected.items():
            got = bal.get(code, 0.0)
            if float_compare(got, exp, precision_digits=2) != 0:
                diffs.append(f'{code}: got={got} expected={exp}')
        # 131 must be zero (transit)
        if float_compare(bal.get('131', 0.0), 0.0, precision_digits=2) != 0:
            if '131' not in ''.join(diffs):
                diffs.append(f"131 transit hung: {bal.get('131')}")
        status = 'ĐẠT' if not diffs else 'LỆCH'
        report = (
            f"\n=== {scenario}: {status} ===\n"
            f"Balances: {dict(sorted(bal.items()))}\n"
            f"Expected: {expected}\n"
            f"Lines:\n" + ('\n'.join(lines_dump) if lines_dump else '  (none)') + '\n'
            + (f"Diffs: {diffs}\n" if diffs else '')
        )
        print(report)
        return status, bal, diffs, report

    # ------------------------------------------------------------------
    # Scenarios
    # ------------------------------------------------------------------

    def test_w1_b01_giao_va_hoa_don_ban_chiu(self):
        """B01: giao + HĐ chịu → thu tiền. Events: delivery, invoice, payment."""
        so = self._create_sale_order(date='2099-01-10')
        delivery = self._deliver_so(so, date='2099-01-10')
        invoice = self._create_invoice(date='2099-01-12', sale_order=so)
        payment = self._create_payment(date='2099-01-20')
        self._sync()
        moves = self._moves_for_sources(delivery, invoice, payment)
        status, _bal, diffs, _ = self._grade('B01', moves, self._expected_full_cycle())
        self.assertEqual(status, 'ĐẠT', diffs)
        before = len(moves)
        self._sync()
        moves2 = self._moves_for_sources(delivery, invoice, payment)
        self.assertEqual(len(moves2), before)

    def test_w1_b02_giao_truoc_hoa_don_sau(self):
        """B02: giao trước, hóa đơn sau, rồi thu — cùng 3 sự kiện."""
        so = self._create_sale_order(date='2099-01-05')
        delivery = self._deliver_so(so, date='2099-01-05')
        invoice = self._create_invoice(date='2099-01-18', sale_order=so)
        payment = self._create_payment(date='2099-01-25')
        self._sync()
        moves = self._moves_for_sources(delivery, invoice, payment)
        status, _bal, diffs, _ = self._grade('B02', moves, self._expected_full_cycle())
        self.assertEqual(status, 'ĐẠT', diffs)

    def test_w1_b03_ung_truoc_giao_sau(self):
        """B03: thu ứng trước → hóa đơn + xuất kho."""
        payment = self._create_payment(date='2099-01-03')
        so = self._create_sale_order(date='2099-01-15')
        delivery = self._deliver_so(so, date='2099-01-15')
        invoice = self._create_invoice(date='2099-01-15', sale_order=so)
        self._sync()
        moves = self._moves_for_sources(delivery, invoice, payment)
        status, _bal, diffs, _ = self._grade('B03', moves, self._expected_full_cycle())
        self.assertEqual(status, 'ĐẠT', diffs)

    def test_w1_b05_thu_tien_ngay(self):
        """B05: bán thu tiền ngay — workbook ghi thẳng 111/112; chấp nhận qua 131 (khớp hiệu quả)."""
        so = self._create_sale_order(date='2099-01-15')
        invoice = self._create_invoice(date='2099-01-15', sale_order=so)
        payment = self._create_payment(date='2099-01-15')
        delivery = self._deliver_so(so, date='2099-01-15')
        self._sync()
        moves = self._moves_for_sources(delivery, invoice, payment)
        status, _bal, diffs, _ = self._grade('B05', moves, self._expected_full_cycle())
        self.assertEqual(status, 'ĐẠT', diffs)

    def test_w1_order_discount_line_not_abs_inflated(self):
        """Chiết khấu cả đơn (dòng âm) ghi DT net, không cộng abs thành 100k+3k."""
        gross = 100_000.0
        disc = -3_000.0
        net = 97_000.0
        tax = net * self.TAX_RATE / 100.0
        move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'invoice_date': '2099-01-15',
            'date': '2099-01-15',
            'journal_id': self.sale_journal.id,
            'company_id': self.company.id,
            'invoice_line_ids': [
                Command.create({
                    'product_id': self.product.id,
                    'name': self.product.name,
                    'quantity': 1.0,
                    'price_unit': gross,
                    'tax_ids': [Command.set(self.tax.ids)],
                }),
                Command.create({
                    'name': 'Chiết khấu đơn 3%',
                    'quantity': 1.0,
                    'price_unit': disc,
                    'tax_ids': [Command.set(self.tax.ids)],
                }),
            ],
        })
        move.action_post()
        self.assertAlmostEqual(move.amount_untaxed, net)
        self._sync()
        vas = self._moves_for_sources(move)
        self.assertTrue(vas, 'sale invoice phải sinh vas.move')
        bal = self._net_balances(vas)
        self.assertEqual(float_compare(bal.get('5111', 0.0), -net, 2), 0, bal)
        self.assertEqual(float_compare(bal.get('33311', 0.0), -tax, 2), 0, bal)
        self.assertEqual(float_compare(bal.get('131', 0.0), net + tax, 2), 0, bal)
