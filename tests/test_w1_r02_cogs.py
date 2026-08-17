# -*- coding: utf-8 -*-
"""W1 R02 COGS: stock.move.value (Odoo 19) with standard_price fallback.

Odoo 19 removed ``stock.valuation.layer``; valued amount is ``stock.move.value``.
"""
from odoo import Command, fields
from odoo.tests import tagged, TransactionCase
from odoo.tools import float_compare


@tagged('connecta_vas', 'connecta_vas_w1')
class TestW1R02Cogs(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.regime = cls.env['vas.regime'].search([('code', '=', 'TT133')], limit=1)
        if not cls.regime:
            cls.regime = cls.env['vas.regime'].create({
                'code': 'TT133',
                'name': 'Thông tư 133/2016/TT-BTC',
            })
        cls.company.vas_regime_id = cls.regime
        cls.company.vas_start_date = '2000-01-01'
        cls.sync = cls.env['vas.sync']

        cls.stock_location = cls.env.ref('stock.stock_location_stock')
        cls.supplier_location = cls.env.ref('stock.stock_location_suppliers')
        cls.customer_location = cls.env.ref('stock.stock_location_customers')
        cls.picking_type_in = cls.env.ref('stock.picking_type_in')
        cls.picking_type_out = cls.env.ref('stock.picking_type_out')
        cls.uom = cls.env.ref('uom.product_uom_unit')

        cls.categ_fifo = cls.env['product.category'].create({
            'name': 'W1 FIFO Test',
            'property_cost_method': 'fifo',
            'property_valuation': 'periodic',
        })

        fy = cls.env['vas.fiscalyear'].search([
            ('company_id', '=', cls.company.id),
            ('date_from', '<=', '2099-06-15'),
            ('date_to', '>=', '2099-06-15'),
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

    def _make_in(self, product, qty, unit_cost):
        move = self.env['stock.move'].create({
            'product_id': product.id,
            'product_uom_qty': qty,
            'product_uom': product.uom_id.id,
            'location_id': self.supplier_location.id,
            'location_dest_id': self.stock_location.id,
            'company_id': self.company.id,
            'picking_type_id': self.picking_type_in.id,
            'price_unit': unit_cost,
            'value_manual': unit_cost * qty,
        })
        move._action_confirm()
        move._action_assign()
        move.picked = True
        move._action_done()
        return move

    def _make_out(self, product, qty):
        move = self.env['stock.move'].create({
            'product_id': product.id,
            'product_uom_qty': qty,
            'product_uom': product.uom_id.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.customer_location.id,
            'company_id': self.company.id,
            'picking_type_id': self.picking_type_out.id,
        })
        move._action_confirm()
        move._action_assign()
        move.quantity = qty
        move.picked = True
        move._action_done()
        return move

    def test_r02_khong_lay_standard_price_khi_chua_dinh_gia(self):
        """value=0 → 0, KHÔNG lấy `qty × standard_price`.

        Trước đây test này kỳ vọng 20.000 (fallback). Fallback đã bị bỏ vì nó
        biến chặng mà Odoo cố ý không định giá thành bút toán giá vốn thật —
        gốc của lỗi ghi giá vốn hai lần trên kho nhiều bước (§5.10).
        """
        product = self.env['product.product'].create({
            'name': 'HH R02 chua dinh gia',
            'is_storable': False,
            'list_price': 50000,
            'standard_price': 20000,
            'uom_id': self.uom.id,
        })
        move = self.env['stock.move'].create({
            'product_id': product.id,
            'product_uom_qty': 1.0,
            'product_uom': product.uom_id.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.customer_location.id,
            'company_id': self.company.id,
            'state': 'done',
            'quantity': 1.0,
            'date': fields.Datetime.to_datetime('2099-06-15'),
        })
        if 'value' in move._fields:
            move.value = 0.0
        amount = self.sync._cogs_amount(move)
        print(f'\n=== R02 chua dinh gia: amount={amount} expect=0 '
              f'standard_price={product.standard_price} move.value={move.value} ===\n')
        self.assertAlmostEqual(
            amount, 0.0,
            msg='value=0 phải ra 0; ra 20.000 nghĩa là fallback standard_price còn sống',
        )

    def test_r02_uses_move_value_fifo(self):
        """FIFO: in @20k then @25k, out 1 → COGS from stock.move.value = 20k (not standard_price)."""
        product = self.env['product.product'].create({
            'name': 'HH R02 FIFO',
            'is_storable': True,
            'list_price': 50000,
            'standard_price': 10000,
            'uom_id': self.uom.id,
            'categ_id': self.categ_fifo.id,
        })
        self.assertEqual(product.cost_method, 'fifo')

        in1 = self._make_in(product, 1.0, 20000.0)
        in2 = self._make_in(product, 1.0, 25000.0)
        print(f'IN1 value={in1.value} is_in={in1.is_in}; IN2 value={in2.value} is_in={in2.is_in}')

        # Decoy standard_price so fallback would be wrong if used
        product.standard_price = 99999.0

        out = self._make_out(product, 1.0)
        amount = self.sync._cogs_amount(out)
        print(
            f'\n=== R02 FIFO: move.value={out.value} cogs={amount} '
            f'standard_price={product.standard_price} expect=20000 ===\n'
        )
        self.assertTrue(float_compare(out.value or 0.0, 0.0, precision_digits=2) != 0)
        self.assertAlmostEqual(amount, abs(out.value))
        self.assertAlmostEqual(amount, 20000.0)
        self.assertNotAlmostEqual(amount, 99999.0)
