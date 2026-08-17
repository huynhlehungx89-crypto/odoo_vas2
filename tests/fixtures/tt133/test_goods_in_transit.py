# -*- coding: utf-8 -*-
"""Fixtures TT133 — TK 151 hàng đi đường + regression bug R07b ghi 156 gấp đôi.

  (a) BẬT công tắc: HĐ posted chưa nhập → Nợ 151 / Có 331; IN done → Nợ 156 / Có 151;
      tổng vào 156 đúng 1× giá hàng.
  (b) TẮT (mặc định): HĐ trước hàng → không ghi 156 sớm; 156 chỉ 1× từ R06.
  (c) Hàng về TRƯỚC HĐ (kiểu M01/W2): R06 ghi 156/331, không đụng 151;
      R07b chênh tạm tính vẫn đúng — KHÔNG sửa test_w4_m01.

Ngoài phạm vi: M03 cuối kỳ, kiểm kê 611/631, R24.
"""
from collections import defaultdict

from odoo import Command, fields
from odoo.tests import tagged, TransactionCase
from odoo.tools import float_compare


DATE_BILL = '2099-11-05'
DATE_RECV = '2099-11-10'
UNTAXED = 100_000.0
TAX = 10_000.0
QTY = 1.0


@tagged('connecta_vas', 'connecta_vas_transit', 'post_install', '-at_install')
class TestTt133GoodsInTransit(TransactionCase):
    """M11 nhánh 151 + M02 (tắt) + regression R07b."""

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
        # Mặc định tắt; từng test bật khi cần.
        cls.company.vas_theo_doi_hang_di_duong = False
        cls._ensure_period()
        cls._ensure_rules()

        cls.partner = cls.env['res.partner'].create({
            'name': 'NCC Transit 151',
            'company_id': cls.company.id,
            'supplier_rank': 1,
        })
        cls.tax = cls._make_purchase_tax_10()
        cls.product = cls.env['product.product'].create({
            'name': 'HH Transit 151',
            'is_storable': True,
            'list_price': UNTAXED,
            'standard_price': UNTAXED,
            'supplier_taxes_id': [Command.set(cls.tax.ids)],
            'uom_id': cls.env.ref('uom.product_uom_unit').id,
            'purchase_ok': True,
        })
        cls.purchase_journal = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id),
            ('type', '=', 'purchase'),
        ], limit=1)
        assert cls.purchase_journal, 'Thiếu journal purchase'

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
            ('date_from', '<=', DATE_BILL),
            ('date_to', '>=', DATE_BILL),
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
            'R10': {
                'name': 'Hàng mua đang đi đường (151)',
                'event_type': 'goods_in_transit',
                'sequence': 49,
                'lines': [
                    ('debit', 'goods_in_transit', 'untaxed'),
                    ('credit', 'partner_payable', 'untaxed'),
                ],
            },
            'R07b': {
                'name': 'Điều chỉnh giá tạm tính mua hàng',
                'event_type': 'purchase_price_adjust',
                'sequence': 51,
                'lines': [
                    ('debit', 'product_inventory', 'price_adjust'),
                    ('credit', 'partner_payable', 'price_adjust'),
                ],
            },
        }
        for code, spec in specs.items():
            existing = Rule.search([
                ('regime_id', '=', regime.id), ('code', '=', code),
            ], limit=1)
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
        return Tax.create({
            'name': 'GTGT 10% Transit',
            'amount': 10.0,
            'amount_type': 'percent',
            'type_tax_use': 'purchase',
            'company_id': cls.company.id,
        })

    def _sync(self):
        return self.env['vas.sync'].sync_company(
            self.company, date_from='2099-01-01', date_to='2099-12-31',
        )

    def _net(self, moves):
        bal = defaultdict(float)
        for line in moves.mapped('line_ids'):
            bal[line.account_id.code] += line.debit - line.credit
        return {k: round(v, 2) for k, v in bal.items()}

    def _moves_for_sources(self, *records):
        Move = self.env['vas.move']
        moves = Move
        for rec in records:
            if not rec:
                continue
            moves |= Move.search([
                ('source_model', '=', rec._name),
                ('source_res_id', '=', rec.id),
                ('state', '=', 'posted'),
            ])
        return moves

    def _create_po(self, price=UNTAXED):
        po = self.env['purchase.order'].create({
            'partner_id': self.partner.id,
            'company_id': self.company.id,
            'date_order': DATE_BILL,
            'order_line': [Command.create({
                'product_id': self.product.id,
                'name': self.product.name,
                'product_qty': QTY,
                'price_unit': price,
                'tax_ids': [Command.set(self.tax.ids)],
            })],
        })
        po.button_confirm()
        return po

    def _bill_from_po(self, po, bill_date=DATE_BILL, price=UNTAXED):
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
                'quantity': QTY,
                'price_unit': price,
                'tax_ids': [Command.set(self.tax.ids)],
                'purchase_line_id': po.order_line[:1].id,
            })],
        })
        bill.action_post()
        return bill

    def _receive_po(self, po, recv_date=DATE_RECV, value=UNTAXED):
        picking = po.picking_ids.filtered(lambda p: p.state != 'done')[:1]
        self.assertTrue(picking, 'PO must create receipt picking')
        for move in picking.move_ids:
            move.quantity = QTY
        picking.button_validate()
        receipt = picking.move_ids.filtered(lambda m: m.state == 'done')[:1]
        receipt.write({'date': fields.Datetime.to_datetime(recv_date)})
        if float_compare(receipt.value or 0.0, 0.0, precision_digits=2) == 0:
            receipt.value = value * QTY
        elif float_compare(abs(receipt.value or 0.0), value * QTY, precision_digits=2) != 0:
            receipt.value = value * QTY
        return receipt

    def test_a_toggle_on_bill_then_receipt_via_151(self):
        """(a) BẬT: HĐ → 151/331; Input done → 156/151; NET 156 = 1×."""
        self.company.vas_theo_doi_hang_di_duong = True
        po = self._create_po()
        bill = self._bill_from_po(po)

        self._sync()
        after_bill = self._moves_for_sources(bill)
        bal1 = self._net(after_bill)
        self.assertAlmostEqual(bal1.get('151', 0.0), UNTAXED, places=2,
                               msg=f'Sau HĐ kỳ vọng Nợ 151={UNTAXED}; got {bal1}')
        self.assertAlmostEqual(bal1.get('156', 0.0), 0.0, places=2,
                               msg=f'Sau HĐ không được ghi 156 sớm; got {bal1}')
        self.assertAlmostEqual(bal1.get('1331', 0.0), TAX, places=2)
        # 331 = Có hàng 151 + Có thuế
        self.assertAlmostEqual(bal1.get('331', 0.0), -(UNTAXED + TAX), places=2)

        transit = after_bill.filtered(lambda m: m.move_kind == 'goods_in_transit')
        self.assertTrue(transit, 'Thiếu R10 goods_in_transit')

        receipt = self._receive_po(po)
        self._sync()
        after_recv = self._moves_for_sources(bill, receipt)
        bal2 = self._net(after_recv)
        self.assertAlmostEqual(bal2.get('156', 0.0), UNTAXED, places=2,
                               msg=f'NET 156 phải = 1× giá hàng; got {bal2}')
        self.assertAlmostEqual(bal2.get('151', 0.0), 0.0, places=2,
                               msg=f'151 phải kết chuyển hết; got {bal2}')
        stock = after_recv.filtered(
            lambda m: m.move_kind == 'stock' and m.source_model == 'stock.move'
        )
        self.assertTrue(stock, 'Thiếu R06 sau nhập')
        credit_codes = stock.mapped('line_ids').filtered(
            lambda l: l.credit > 0
        ).mapped('account_id.code')
        self.assertIn('151', credit_codes, f'R06 phải Có 151; credits={credit_codes}')

    def test_b_toggle_off_no_early_156(self):
        """(b) TẮT: HĐ trước → chỉ thuế; sau nhập 156 đúng 1× từ R06 (regression)."""
        self.company.vas_theo_doi_hang_di_duong = False
        po = self._create_po()
        bill = self._bill_from_po(po)

        self._sync()
        after_bill = self._moves_for_sources(bill)
        bal1 = self._net(after_bill)
        # Trước fix: R07b ghi 156=+100k → NET 156=100k sớm (bug).
        self.assertAlmostEqual(bal1.get('156', 0.0), 0.0, places=2,
                               msg=f'TRƯỚC nhập 156 phải = 0 (hết bug gấp đôi); got {bal1}')
        self.assertAlmostEqual(bal1.get('151', 0.0), 0.0, places=2)
        self.assertFalse(
            after_bill.filtered(lambda m: m.move_kind == 'goods_in_transit'),
            'Tắt 151 không được sinh R10',
        )
        self.assertFalse(
            after_bill.filtered(lambda m: m.move_kind == 'manual'),
            'R07b không được chạy khi chưa receipt',
        )
        self.assertAlmostEqual(bal1.get('1331', 0.0), TAX, places=2)
        self.assertAlmostEqual(bal1.get('331', 0.0), -TAX, places=2)

        receipt = self._receive_po(po)
        self._sync()
        after_recv = self._moves_for_sources(bill, receipt)
        bal2 = self._net(after_recv)
        self.assertAlmostEqual(bal2.get('156', 0.0), UNTAXED, places=2,
                               msg=f'SAU nhập NET 156 = 1× (không 2×); got {bal2}')
        stock = after_recv.filtered(
            lambda m: m.move_kind == 'stock' and m.source_model == 'stock.move'
        )
        credit_codes = stock.mapped('line_ids').filtered(
            lambda l: l.credit > 0
        ).mapped('account_id.code')
        self.assertIn('331', credit_codes, f'Tắt 151: R06 phải Có 331; {credit_codes}')
        self.assertNotIn('151', credit_codes)

    def test_c_receive_before_bill_no_151(self):
        """(c) Hàng về trước HĐ: R06 = 156/331; không 151; adjust M01 vẫn OK."""
        self.company.vas_theo_doi_hang_di_duong = True  # bật vẫn không bịa 151
        po = self._create_po(price=800_000.0)
        receipt = self._receive_po(po, recv_date=DATE_BILL, value=800_000.0)
        bill = self._bill_from_po(po, bill_date=DATE_RECV, price=1_000_000.0)
        # Post HĐ có thể ghi đè stock.move.value — giữ giá tạm như test_w4_m01.
        if float_compare(abs(receipt.value or 0.0), 800_000.0, precision_digits=2) != 0:
            receipt.value = 800_000.0

        adjust = self.env['vas.sync']._purchase_price_adjust_amount(bill)
        self.assertAlmostEqual(adjust, 200_000.0, delta=1,
                               msg=f'M01 adjust phải 200k; got {adjust} receipt={receipt.value}')

        self._sync()
        moves = self._moves_for_sources(bill, receipt)
        bal = self._net(moves)
        self.assertAlmostEqual(bal.get('151', 0.0), 0.0, places=2,
                               msg=f'Nhận trước HĐ không đụng 151; got {bal}')
        # R06 800k + R07b 200k = 1_000_000 trên 156
        self.assertAlmostEqual(bal.get('156', 0.0), 1_000_000.0, places=2,
                               msg=f'156 = receipt + chênh; got {bal}')
        self.assertFalse(
            moves.filtered(lambda m: m.move_kind == 'goods_in_transit'),
            'Không sinh R10 khi đã nhập trước HĐ',
        )
        stock = moves.filtered(
            lambda m: m.move_kind == 'stock' and m.source_model == 'stock.move'
        )
        credit_codes = stock.mapped('line_ids').filtered(
            lambda l: l.credit > 0
        ).mapped('account_id.code')
        self.assertIn('331', credit_codes)
        self.assertNotIn('151', credit_codes)
