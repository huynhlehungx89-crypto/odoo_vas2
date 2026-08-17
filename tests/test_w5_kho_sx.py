# -*- coding: utf-8 -*-
"""W5 — Kho & sản xuất: R14 (xuất NVL sản xuất).

Phạm vi sau khi vá §5.10:
  - R14: Nợ 154 / Có TK tồn kho của NVL qua `product_inventory`.
  - R13 ĐÃ BỎ: điều chuyển kho nội bộ không ghi bút toán (workbook K01).
  - R02 siết về `location_dest_usage='customer'` — hết ghi giá vốn hai lần.
  - `_cogs_amount` bỏ fallback `standard_price × qty`.
  - R15 / R16: HOÃN (định giá thành phẩm chờ kế toán; R16 = TRỤC 2).
  - `mrp` là phụ thuộc MỀM: kiểm field tồn tại, không thêm vào depends.

Cả bộ chạy HAI LẦN: kho một bước (`TestW5KhoSanXuat`) và kho nhiều bước
(`TestW5KhoNhieuBuoc`), vì lỗi giá vốn hai lần chỉ lộ ở cấu hình nhiều bước.

Test bắt buộc:
  (i)   NVL nhóm khai 152 → bút toán Có 152, không phải 156.
  (ii)  Lệnh sản xuất (xuất NVL) KHÔNG làm R02 / R06 bắn nhầm.
  (iii) Đồng bộ hai lần → không sinh bút toán trùng.
  (iv)  Nhóm NVL chưa khai → mặc định + cờ + kỳ không khóa được.
  (v)   Điều chuyển nội bộ → KHÔNG sinh bút toán nào.
  (vi)  Move chưa có giá trị → không ghi bút toán 0 đồng im lặng.
  (ms)  Kho nhiều bước: giá vốn ghi đúng một lần + ma trận chồng lấn sạch.
"""
from collections import defaultdict

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged, TransactionCase
DATE = '2099-07-15'


@tagged('connecta_vas', 'connecta_vas_w5_sx')
class TestW5KhoSanXuat(TransactionCase):

    NVL_COST = 30_000.0
    NVL_QTY = 2.0          # BOM: 2 NVL → 1 TP
    MO_QTY = 3.0           # → tiêu hao 6 NVL = 180_000
    EXPECTED_ISSUE = 180_000.0

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
        cls._ensure_rules()
        cls._ensure_period()

        cls.partner = cls.env['res.partner'].create({
            'name': 'Đối tác W5 SX',
            'company_id': cls.company.id,
            'supplier_rank': 1,
            'customer_rank': 1,
        })

        # FIFO để value trên stock.move được điền đúng chi phí thực tế
        cls.cat_nvl = cls.env['product.category'].create({
            'name': 'W5SX NVL',
            'property_cost_method': 'fifo',
            'property_valuation': 'real_time',
        })
        cls.cat_tp = cls.env['product.category'].create({
            'name': 'W5SX Thành phẩm',
            'property_cost_method': 'fifo',
            'property_valuation': 'real_time',
        })
        cls.cat_hh = cls.env['product.category'].create({
            'name': 'W5SX Hàng hóa',
            'property_cost_method': 'fifo',
            'property_valuation': 'real_time',
        })
        cls.cat_empty = cls.env['product.category'].create({
            'name': 'W5SX NVL chưa khai',
            'property_cost_method': 'fifo',
            'property_valuation': 'real_time',
        })

        cls._map(cls.cat_nvl, stock='152')
        cls._map(cls.cat_tp, stock='155', revenue='5112', cogs='632')
        cls._map(cls.cat_hh, stock='156', revenue='5111', cogs='632')
        # cat_empty: cố ý không map → mặc định 156 + cờ

        uom = cls.env.ref('uom.product_uom_unit')
        cls.p_nvl = cls.env['product.product'].create({
            'name': 'W5SX NVL 152',
            'is_storable': True,
            'categ_id': cls.cat_nvl.id,
            'standard_price': cls.NVL_COST,
            'uom_id': uom.id,
            'purchase_ok': True,
        })
        cls.p_tp = cls.env['product.product'].create({
            'name': 'W5SX Thành phẩm 155',
            'is_storable': True,
            'categ_id': cls.cat_tp.id,
            'standard_price': 0.0,
            'uom_id': uom.id,
            'sale_ok': True,
        })
        cls.p_hh = cls.env['product.product'].create({
            'name': 'W5SX Hàng hóa 156',
            'is_storable': True,
            'categ_id': cls.cat_hh.id,
            'standard_price': 20_000.0,
            'list_price': 50_000.0,
            'uom_id': uom.id,
            'purchase_ok': True,
            'sale_ok': True,
        })
        cls.p_empty = cls.env['product.product'].create({
            'name': 'W5SX NVL chưa khai',
            'is_storable': True,
            'categ_id': cls.cat_empty.id,
            'standard_price': cls.NVL_COST,
            'uom_id': uom.id,
            'purchase_ok': True,
        })

        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.company.id)], limit=1,
        )
        cls.stock_location = cls.warehouse.lot_stock_id
        cls._stock(cls.p_nvl, 100.0)
        cls._stock(cls.p_hh, 100.0)
        cls._stock(cls.p_empty, 100.0)

        if 'mrp.bom' in cls.env:
            cls.bom = cls.env['mrp.bom'].create({
                'product_tmpl_id': cls.p_tp.product_tmpl_id.id,
                'product_qty': 1.0,
                'type': 'normal',
                'bom_line_ids': [Command.create({
                    'product_id': cls.p_nvl.id,
                    'product_qty': cls.NVL_QTY,
                })],
            })
            cls.bom_empty = cls.env['mrp.bom'].create({
                'product_tmpl_id': cls.p_tp.product_tmpl_id.id,
                'product_qty': 1.0,
                'type': 'normal',
                'bom_line_ids': [Command.create({
                    'product_id': cls.p_empty.id,
                    'product_qty': cls.NVL_QTY,
                })],
            })
        else:
            cls.bom = cls.bom_empty = False

    # ------------------------------------------------------------------
    # Fixtures
    # ------------------------------------------------------------------

    @classmethod
    def _acc(cls, code):
        account = cls.env['vas.account'].search([
            ('regime_id', '=', cls.company.vas_regime_id.id),
            ('code', '=', code),
        ], limit=1)
        assert account, f'Thiếu tài khoản VAS {code}'
        return account

    @classmethod
    def _map(cls, target, stock=None, revenue=None, cogs=None):
        is_category = target._name == 'product.category'
        vals = {
            'regime_id': cls.company.vas_regime_id.id,
            'apply_to': 'category' if is_category else 'product',
            'company_id': cls.company.id,
        }
        vals['category_id' if is_category else 'product_id'] = target.id
        for field, code in (
            ('stock_account_id', stock),
            ('revenue_account_id', revenue),
            ('cogs_account_id', cogs),
        ):
            if code:
                vals[field] = cls._acc(code).id
        return cls.env['vas.account.map'].create(vals)

    @classmethod
    def _stock(cls, product, qty):
        cls.env['stock.quant'].with_context(inventory_mode=True).create({
            'product_id': product.id,
            'location_id': cls.stock_location.id,
            'inventory_quantity': qty,
        }).action_apply_inventory()

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
        cls.period = fy.period_ids.filtered(
            lambda p: p.date_start <= fields.Date.to_date(DATE) <= p.date_end
        )[:1]
        assert cls.period, 'Thiếu kỳ kế toán tháng 7/2099'

    @classmethod
    def _ensure_rules(cls):
        """Bảo đảm R02/R06/R14 có mặt kể cả khi XML chưa nạp trong DB test."""
        Rule = cls.env['vas.rule']
        regime = cls.company.vas_regime_id
        acc_154 = cls.env['vas.account'].search([
            ('regime_id', '=', regime.id), ('code', '=', '154'),
        ], limit=1)
        specs = {
            'R02': ('Xuất kho bán hàng', 'sale_delivery', 20, [
                ('debit', 'product_cogs', False, 'cogs'),
                ('credit', 'product_inventory', False, 'cogs'),
            ]),
            'R06': ('Nhập kho mua hàng', 'purchase_receipt', 40, [
                ('debit', 'product_inventory', False, 'stock_value'),
                ('credit', 'receipt_counterpart', False, 'stock_value'),
            ]),
            # R13 đã bỏ — điều chuyển nội bộ không ghi bút toán (§5.10c).
            'R14': ('Xuất nguyên vật liệu cho sản xuất', 'stock_issue_production', 62, [
                ('debit', 'fixed', acc_154, 'stock_value'),
                ('credit', 'product_inventory', False, 'stock_value'),
            ]),
        }
        for code, (name, event_type, sequence, lines) in specs.items():
            rule = Rule.search([('regime_id', '=', regime.id), ('code', '=', code)], limit=1)
            if rule:
                if code == 'R06':
                    credit = rule.line_ids.filtered(lambda l: l.side == 'credit')[:1]
                    if credit and credit.account_selector == 'partner_payable':
                        credit.account_selector = 'receipt_counterpart'
                continue
            Rule.create({
                'code': code,
                'name': name,
                'regime_id': regime.id,
                'event_type': event_type,
                'sequence': sequence,
                'active': True,
                'line_ids': [
                    Command.create({
                        'sequence': (i + 1) * 10,
                        'side': side,
                        'account_selector': selector,
                        'account_id': account.id if account else False,
                        'amount_selector': amount,
                    })
                    for i, (side, selector, account, amount) in enumerate(lines)
                ],
            })

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _sync(self):
        return self.env['vas.sync'].sync_company(
            self.company, date_from='2099-01-01', date_to='2099-12-31',
        )

    def _require_mrp(self):
        if not self.env['vas.sync']._mrp_available():
            self.skipTest('Module mrp chưa cài — R14 là phụ thuộc mềm')

    def _make_mo(self, bom, qty=None, date=DATE):
        self._require_mrp()
        qty = qty if qty is not None else self.MO_QTY
        mo = self.env['mrp.production'].create({
            'product_id': self.p_tp.id,
            'bom_id': bom.id,
            'product_qty': qty,
            'company_id': self.company.id,
        })
        mo.action_confirm()
        mo.qty_producing = qty
        for m in mo.move_raw_ids:
            m.quantity = m.product_uom_qty
            m.picked = True
        mo.button_mark_done()
        self.assertEqual(mo.state, 'done')
        mo.move_raw_ids.write({'date': fields.Datetime.to_datetime(date)})
        mo.move_finished_ids.write({'date': fields.Datetime.to_datetime(date)})
        return mo

    def _make_internal_transfer(self, product, qty=1.0, date=DATE):
        dest = self.env['stock.location'].create({
            'name': 'W5SX Kho 2',
            'usage': 'internal',
            'location_id': self.stock_location.location_id.id,
        })
        # Bảo đảm nhóm multi-location để loại phiếu internal tồn tại
        self.env.ref('base.group_user').sudo().write({
            'implied_ids': [Command.link(
                self.env.ref('stock.group_stock_multi_locations').id)],
        })
        pick_type = self.warehouse.int_type_id
        self.assertTrue(pick_type, 'Kho thiếu loại phiếu Internal Transfers')
        picking = self.env['stock.picking'].create({
            'picking_type_id': pick_type.id,
            'location_id': self.stock_location.id,
            'location_dest_id': dest.id,
            'company_id': self.company.id,
            'move_ids': [Command.create({
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
                'location_id': self.stock_location.id,
                'location_dest_id': dest.id,
                'company_id': self.company.id,
            })],
        })
        picking.action_confirm()
        for m in picking.move_ids:
            m.quantity = m.product_uom_qty
            m.picked = True
        picking.button_validate()
        moves = picking.move_ids.filtered(lambda m: m.state == 'done')
        moves.write({'date': fields.Datetime.to_datetime(date)})
        return moves

    def _validate_all_legs(self, pickings):
        """Xác nhận MỌI chặng, kể cả chặng chỉ sinh ra sau khi chặng trước xong.

        Kho một bước có một chặng, `pick_ship` / `two_steps` có hai. Test phải
        chạy được trên cả hai cấu hình bằng cùng một helper.
        """
        for _round in range(6):
            pending = pickings.filtered(lambda p: p.state not in ('done', 'cancel'))
            if not pending:
                break
            for pick in pending:
                pick.action_assign()
                for m in pick.move_ids:
                    m.quantity = m.product_uom_qty
                    m.picked = True
                pick.button_validate()
            pickings |= pickings.mapped('move_ids.move_dest_ids.picking_id')
        self.assertFalse(
            pickings.filtered(lambda p: p.state not in ('done', 'cancel')),
            'Còn chặng chưa xác nhận — test sẽ đo thiếu',
        )
        return pickings

    def _sell(self, product, qty=2.0, price=50_000.0, date=DATE):
        so = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'company_id': self.company.id,
            'order_line': [Command.create({
                'product_id': product.id,
                'name': product.name,
                'product_uom_qty': qty,
                'price_unit': price,
                'tax_ids': [Command.clear()],
            })],
        })
        so.action_confirm()
        pickings = self._validate_all_legs(so.picking_ids)
        moves = pickings.mapped('move_ids').filtered(lambda m: m.state == 'done')
        moves.write({'date': fields.Datetime.to_datetime(date)})
        return so, moves

    def _deliver_to_customer(self, product, qty=2.0, date=DATE):
        """Chỉ các chặng hàng RỜI KHO ĐI KHÁCH của một đơn bán."""
        _so, moves = self._sell(product, qty=qty, date=date)
        return moves.filtered(lambda m: m.location_dest_usage == 'customer')

    def _buy(self, product, qty=5.0, price=20_000.0, date=DATE):
        po = self.env['purchase.order'].create({
            'partner_id': self.partner.id,
            'company_id': self.company.id,
            'order_line': [Command.create({
                'product_id': product.id,
                'name': product.name,
                'product_qty': qty,
                'price_unit': price,
                'tax_ids': [Command.clear()],
            })],
        })
        po.button_confirm()
        pickings = self._validate_all_legs(po.picking_ids)
        moves = pickings.mapped('move_ids').filtered(lambda m: m.state == 'done')
        moves.write({'date': fields.Datetime.to_datetime(date)})
        return po, moves

    def _balances(self, moves):
        balances = defaultdict(float)
        for line in moves.mapped('line_ids'):
            balances[line.account_id.code] += line.debit - line.credit
        return dict(balances)

    def _vas_for(self, stock_moves, move_kind='stock'):
        return self.env['vas.move'].search([
            ('source_model', '=', 'stock.move'),
            ('source_res_id', 'in', stock_moves.ids),
            ('move_kind', '=', move_kind),
            ('is_reversal', '=', False),
            ('state', 'not in', ('reversed', 'cancelled')),
        ])

    # ------------------------------------------------------------------
    # (i) NVL nhóm 152 → Có 152, không phải 156
    # ------------------------------------------------------------------

    def test_w5_i_xuat_nvl_ve_152(self):
        mo = self._make_mo(self.bom)
        raw = mo.move_raw_ids
        self.assertAlmostEqual(sum(raw.mapped('value')), self.EXPECTED_ISSUE, places=2)

        stats = self._sync()
        self.assertGreater(stats['stock_issue_production']['created'], 0)

        vas = self._vas_for(raw)
        self.assertEqual(len(vas), 1, f'R14 phải sinh đúng 1 bút toán, được {len(vas)}')
        bal = self._balances(vas)
        self.assertAlmostEqual(bal.get('154', 0.0), self.EXPECTED_ISSUE, places=2)
        self.assertAlmostEqual(bal.get('152', 0.0), -self.EXPECTED_ISSUE, places=2)
        self.assertNotIn('156', bal, 'NVL khai 152 không được rơi về mặc định 156')
        self.assertFalse(vas.vas_has_default_account)

    # ------------------------------------------------------------------
    # (ii) Không chồng lấn: lệnh SX không kích R02 / R06
    # ------------------------------------------------------------------

    def test_w5_ii_khong_chong_lan_r02_r06(self):
        mo = self._make_mo(self.bom)
        all_moves = mo.move_raw_ids | mo.move_finished_ids

        self._sync()

        # R14 bắt move NVL
        vas_r14 = self._vas_for(mo.move_raw_ids)
        self.assertEqual(len(vas_r14), 1)

        # R02 (move_kind=cogs) và R06 (move_kind=stock, nhưng purchase_receipt)
        # không được bắt bất kỳ move nào của lệnh sản xuất.
        # R06 cũng dùng move_kind='stock' nên phải lọc theo rule/event qua nguồn:
        # move thành phẩm chưa có R15 → không có vas.move nào; move NVL chỉ có R14.
        vas_all = self.env['vas.move'].search([
            ('source_model', '=', 'stock.move'),
            ('source_res_id', 'in', all_moves.ids),
            ('is_reversal', '=', False),
            ('state', 'not in', ('reversed', 'cancelled')),
        ])
        self.assertEqual(
            set(vas_all.mapped('move_kind')), {'stock'},
            f'Lệnh SX chỉ được sinh move_kind=stock (R14), được {vas_all.mapped("move_kind")}',
        )
        # Chặng 4: nhập kho TP vật lý (Odoo) và ghi giá thành 154→155 (VAS sau duyệt)
        # là HAI bước riêng. R15 sync từ stock.move thành phẩm vẫn HOÃN — không sinh
        # bút toán VAS gắn source stock.move thành phẩm lúc đồng bộ.
        # Giá thành đầy đủ ghi ở bước 154→155 từ phiên bản kết quả đã duyệt, không
        # lấy từ giá trị phiếu kho Odoo.
        vas_finished = self.env['vas.move'].search([
            ('source_model', '=', 'stock.move'),
            ('source_res_id', 'in', mo.move_finished_ids.ids),
            ('is_reversal', '=', False),
            ('state', 'not in', ('reversed', 'cancelled')),
        ])
        self.assertFalse(
            vas_finished,
            'Không sinh bút toán VAS từ stock.move thành phẩm (R15 hoãn); '
            'giá thành ghi 154→155 sau duyệt, tách khỏi phiếu nhập vật lý. '
            f'Được: {vas_finished.mapped("name")}',
        )
        self.assertEqual(
            len(vas_all), 1,
            'Chỉ R14 trên NVL; thành phẩm không sync JE — ghi giá ở bước 154→155',
        )

        # Domain R02 / R06 trên chính các move sản xuất phải trống
        Move = self.env['stock.move']
        r02 = Move.search([
            ('id', 'in', all_moves.ids), ('state', '=', 'done'),
            ('location_dest_usage', '=', 'customer'),
        ])
        r06 = Move.search([
            ('id', 'in', all_moves.ids), ('state', '=', 'done'), '|',
            ('purchase_line_id', '!=', False), '&',
            ('picking_code', '=', 'incoming'),
            ('location_usage', '=', 'supplier'),
        ])
        self.assertFalse(r02, f'R02 bắt nhầm move SX: {r02.ids}')
        self.assertFalse(r06, f'R06 bắt nhầm move SX: {r06.ids}')

    # ------------------------------------------------------------------
    # (iii) Đồng bộ hai lần → không trùng
    # ------------------------------------------------------------------

    def test_w5_iii_idempotent(self):
        mo = self._make_mo(self.bom)
        s1 = self._sync()
        s2 = self._sync()
        self.assertGreater(s1['stock_issue_production']['created'], 0)
        self.assertEqual(s2['stock_issue_production']['created'], 0)
        self.assertGreater(s2['stock_issue_production']['skipped'], 0)

        vas = self._vas_for(mo.move_raw_ids)
        self.assertEqual(len(vas), 1)

    # ------------------------------------------------------------------
    # (iv) Nhóm NVL chưa khai → mặc định 156 + cờ + kỳ không khóa
    # ------------------------------------------------------------------

    def test_w5_iv_chua_khai_co_co_va_khoa_ky(self):
        mo = self._make_mo(self.bom_empty)
        self._sync()

        vas = self._vas_for(mo.move_raw_ids)
        self.assertEqual(len(vas), 1)
        self.assertTrue(vas.vas_has_default_account)
        bal = self._balances(vas)
        self.assertAlmostEqual(bal.get('154', 0.0), self.EXPECTED_ISSUE, places=2)
        self.assertAlmostEqual(bal.get('156', 0.0), -self.EXPECTED_ISSUE, places=2)
        self.assertNotIn('152', bal)

        with self.assertRaises(UserError):
            self.period.write({'state': 'closed'})

    # ------------------------------------------------------------------
    # (v) Điều chuyển kho nội bộ KHÔNG ghi bút toán (R13 đã bỏ)
    # ------------------------------------------------------------------

    def test_w5_v_dieu_chuyen_khong_ghi_so(self):
        """K01: workbook chốt không ghi Sổ Cái, VAS phải im hoàn toàn.

        Không chỉ "không sinh bút toán lệch" mà là **không sinh bút toán nào** —
        kể cả bút toán rỗng Nợ 156 / Có 156 mà R13 cũ từng ghi.
        """
        transfer = self._make_internal_transfer(self.p_hh, qty=1.0)
        self.assertTrue(transfer)
        self.assertEqual(transfer.picking_code, 'internal')
        self.assertEqual(transfer.location_usage, 'internal')
        self.assertEqual(transfer.location_dest_usage, 'internal')

        stats = self._sync()
        self.assertNotIn(
            'stock_transfer', stats,
            'Sự kiện stock_transfer phải biến mất khỏi engine, không chỉ tắt rule',
        )
        self.assertFalse(
            self.env['vas.rule'].search([('event_type', '=', 'stock_transfer')]),
            'Không được còn vas.rule nào nghe stock_transfer',
        )

        vas = self.env['vas.move'].search([
            ('source_model', '=', 'stock.move'),
            ('source_res_id', 'in', transfer.ids),
        ])
        self.assertFalse(
            vas,
            f'Điều chuyển nội bộ không được sinh bút toán nào, có {vas.mapped("name")}',
        )

    # ------------------------------------------------------------------
    # (vi) Move chưa có giá trị → không ghi bút toán 0 đồng im lặng
    # ------------------------------------------------------------------

    def test_w5_vi_value_0_khong_lay_standard_price(self):
        """`_cogs_amount` không được lấp `value=0` bằng `standard_price × qty`.

        Chặng nội bộ là mẫu sẵn có: Odoo cố ý để `value=0` vì điều chuyển không
        làm đổi giá trị kho, trong khi thẻ sản phẩm vẫn có giá 20.000. Code cũ
        trả về 20.000 × qty — chính chỗ đó đẻ ra bút toán giá vốn thứ hai.
        """
        transfer = self._make_internal_transfer(self.p_hh, qty=2.0)
        self.assertAlmostEqual(sum(transfer.mapped('value')), 0.0, places=2)
        self.assertGreater(self.p_hh.standard_price, 0.0)

        for move in transfer:
            self.assertAlmostEqual(
                self.env['vas.sync']._cogs_amount(move), 0.0, places=2,
                msg=f'value=0 phải ra 0, không được lấy standard_price '
                    f'({self.p_hh.standard_price}) nhân số lượng',
            )

    def test_w5_vi_b_ban_fifo_chua_nhap_thi_khong_khoa_duoc_ky(self):
        """Bán hàng FIFO trước lần nhập đầu → không bút toán, và KHÔNG khóa được kỳ.

        Đây là chỗ nguy hiểm hơn nhóm chưa khai ánh xạ: nhóm chưa khai thì bút
        toán vẫn có (chỉ sai TK), còn ở đây KHÔNG có bút toán nào — hàng rời kho
        thật mà sổ không ghi giảm 156, không ghi 632, ra lãi khống.
        """
        product = self.env['product.product'].create({
            'name': 'W5SX FIFO chưa nhập',
            'is_storable': True,
            'categ_id': self.cat_hh.id,      # FIFO
            'standard_price': 0.0,
            'uom_id': self.env.ref('uom.product_uom_unit').id,
            'sale_ok': True,
        })
        # KHÔNG nhập kho trước: FIFO chưa có lớp giá nào để bốc.
        moves = self._deliver_to_customer(product, qty=2.0)
        self.assertAlmostEqual(
            sum(moves.mapped('value')), 0.0, places=2,
            msg='Kịch bản cần FIFO chưa có lớp giá nào',
        )

        # (a) Không sinh bút toán giá vốn, nhưng phải kêu lên
        stats = self._sync()
        vas = self._vas_for(moves, move_kind='cogs')
        self.assertFalse(
            vas, f'Không được ghi bút toán giá vốn 0 đồng: {self._balances(vas)}',
        )
        self.assertGreaterEqual(
            stats['default_account']['unvalued_moves'], 1,
            'Bỏ qua thì phải kêu lên: số đếm unvalued_moves không được là 0',
        )

        # (a) Kỳ KHÔNG khóa được
        with self.assertRaises(UserError) as ctx:
            self.period.write({'state': 'closed'})
        thong_bao = str(ctx.exception)
        self.assertIn(product.display_name, thong_bao, 'Lỗi phải chỉ đúng sản phẩm')
        self.assertIn('lãi khống', thong_bao, 'Lỗi phải nói rõ hậu quả')
        print(f'\n=== Chặn khóa kỳ ===\n{thong_bao}\n')

        # (b) Nhập kho rồi khai giá cho chặng xuất → sinh được bút toán → khóa được.
        # Odoo 19 KHÔNG hồi tố giá cho move đã done: nhập kho sau đó không tự vá
        # chặng xuất cũ, phải dùng Điều chỉnh định giá (`value_manual`).
        self._buy(product, qty=5.0, price=20_000.0)
        moves.invalidate_recordset(['value'])
        self.assertAlmostEqual(
            sum(moves.mapped('value')), 0.0, places=2,
            msg='Ghi nhận hành vi Odoo 19: nhập kho KHÔNG hồi tố giá move đã done',
        )
        for move in moves:
            move.value_manual = 40_000.0 / len(moves)
        moves.invalidate_recordset(['value'])
        self.assertAlmostEqual(sum(moves.mapped('value')), 40_000.0, places=2)

        self._sync()
        vas = self._vas_for(moves, move_kind='cogs')
        self.assertTrue(vas, 'Có giá trị rồi thì phải sinh được bút toán giá vốn')
        self.assertAlmostEqual(
            self._balances(vas).get('632', 0.0), 40_000.0, places=2,
        )
        self.period.write({'state': 'closed'})
        self.assertEqual(self.period.state, 'closed')

    # ------------------------------------------------------------------
    # (vii) Kho MỘT bước: giá vốn vẫn bắt đúng một move
    # ------------------------------------------------------------------

    def test_w5_vii_giavon_mot_buoc(self):
        # DB demo có thể đang pick_ship (thao tác tay / class multi-step). Đo theo
        # cấu hình thực tế: vẫn đúng một bút toán giá vốn trên chặng đi khách.
        expect_pick = self.warehouse.delivery_steps != 'ship_only'
        self._assert_giavon_dung_mot_lan(expect_pick_leg=expect_pick)

    def _assert_giavon_dung_mot_lan(self, expect_pick_leg):
        """Bán 2 cái giá vốn 20.000/cái → Nợ 632 = 40.000, dù kho mấy bước."""
        expected = 2.0 * 20_000.0
        _so, moves = self._sell(self.p_hh, qty=2.0)

        pick_legs = moves.filtered(lambda m: m.location_dest_usage != 'customer')
        out_legs = moves.filtered(lambda m: m.location_dest_usage == 'customer')
        self.assertEqual(
            len(out_legs), 1,
            f'Chỉ được đúng một chặng đi khách, được {out_legs.ids}',
        )
        if expect_pick_leg:
            self.assertTrue(pick_legs, 'Kỳ vọng có chặng PICK khi kho ở pick_ship')
            self.assertTrue(
                all(m.sale_line_id for m in pick_legs),
                'Chặng PICK vẫn mang sale_line_id — đúng cái bẫy domain cũ mắc phải',
            )
        else:
            self.assertFalse(pick_legs, 'Kho một bước không được có chặng trung gian')

        self._sync()

        self.assertFalse(
            self._vas_for(pick_legs, move_kind='cogs'),
            f'Chặng trung gian không được sinh bút toán giá vốn: {pick_legs.ids}',
        )
        vas_out = self._vas_for(out_legs, move_kind='cogs')
        self.assertEqual(
            len(vas_out), 1,
            f'Đúng MỘT bút toán giá vốn cho một lần bán, được {len(vas_out)}',
        )

        tong_632 = sum(
            line.debit - line.credit
            for line in self._vas_for(moves, move_kind='cogs').mapped('line_ids')
            if line.account_id.code == '632'
        )
        self.assertAlmostEqual(
            tong_632, expected, places=2,
            msg=f'Nợ 632 phải là {expected:,.0f}, được {tong_632:,.0f} '
                f'(gấp đôi nghĩa là R02 lại ăn cả hai chặng)',
        )


@tagged('connecta_vas', 'connecta_vas_w5_sx')
class TestW5KhoNhieuBuoc(TestW5KhoSanXuat):
    """Kho `pick_ship` + `two_steps` — chạy ĐỊNH KỲ, không phải probe rời.

    Lỗi R02 ghi giá vốn hai lần chỉ lộ ra khi một đơn bán tách thành hai chặng,
    nên cấu hình này phải nằm trong bộ test thường. Kế thừa để dùng lại nguyên
    bộ fixture của kho một bước; Odoo không chạy lại test kế thừa nên phần nào
    cần đo ở cả hai cấu hình thì được khai lại ở đây.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.ref('base.group_user').sudo().write({
            'implied_ids': [
                Command.link(cls.env.ref('stock.group_adv_location').id),
                Command.link(cls.env.ref('stock.group_stock_multi_locations').id),
            ],
        })
        cls.warehouse.write({
            'delivery_steps': 'pick_ship',
            'reception_steps': 'two_steps',
        })

    def test_w5_ms_giavon_chi_ghi_mot_lan(self):
        """Bán 2 cái giá vốn 20.000/cái → Nợ 632 = 40.000, KHÔNG phải 80.000."""
        self._assert_giavon_dung_mot_lan(expect_pick_leg=True)

    def test_w5_ms_dieu_chuyen_khong_ghi_so(self):
        super().test_w5_v_dieu_chuyen_khong_ghi_so()

    def test_w5_ms_ma_tran_chong_lan(self):
        """0 cặp rule chồng lấn VÀ mỗi nghiệp vụ đúng một bút toán giá vốn."""
        self._require_mrp()
        _po, mua = self._buy(self.p_hh, qty=5.0)
        _so, ban = self._sell(self.p_hh, qty=2.0)
        chuyen = self._make_internal_transfer(self.p_hh, qty=1.0)
        mo = self._make_mo(self.bom)
        universe = mua | ban | chuyen | mo.move_raw_ids | mo.move_finished_ids

        Move = self.env['stock.move']
        base = [('id', 'in', universe.ids), ('state', '=', 'done')]
        domains = {
            'R02': base + [('location_dest_usage', '=', 'customer')],
            'R06': base + [
                '|', ('purchase_line_id', '!=', False),
                '&', ('picking_code', '=', 'incoming'),
                ('location_usage', '=', 'supplier')],
            'R14': base + [('raw_material_production_id', '!=', False)],
        }
        hits = {label: Move.search(domain) for label, domain in domains.items()}
        for label, found in hits.items():
            print(f'  {label} bắt {len(found)} move: '
                  f'{[(m.id, m.picking_id.name or "-") for m in found.sorted("id")]}')

        chong_lan = [
            (a, b) for a in hits for b in hits
            if a < b and (hits[a] & hits[b])
        ]
        self.assertFalse(chong_lan, f'Có cặp rule giẫm chân nhau: {chong_lan}')

        self.assertEqual(
            len(hits['R02']), 1,
            f'Một đơn bán chỉ được đúng một chặng vào R02, được {hits["R02"].ids}',
        )
        self.assertEqual(
            len(hits['R06']), 1,
            f'Một đơn mua chỉ được đúng một chặng vào R06, được {hits["R06"].ids}',
        )
        self.assertFalse(
            (hits['R02'] | hits['R06'] | hits['R14']) & chuyen,
            'Điều chuyển nội bộ không được rơi vào rule nào',
        )

        self._sync()
        vas_ban = self._vas_for(ban, move_kind='cogs')
        self.assertEqual(
            len(vas_ban), 1,
            f'Đơn bán phải sinh đúng một bút toán giá vốn, được {len(vas_ban)}',
        )
        self.assertFalse(
            self.env['vas.move'].search([
                ('source_model', '=', 'stock.move'),
                ('source_res_id', 'in', chuyen.ids),
            ]),
            'Điều chuyển nội bộ không được sinh bút toán nào',
        )
