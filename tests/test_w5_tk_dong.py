# -*- coding: utf-8 -*-
"""Trục 1 — chọn tài khoản động theo sản phẩm / nhóm sản phẩm.

(a) nhóm khai tồn 152 → nhập kho vào 152, không phải 156
(b) nhóm dịch vụ khai doanh thu 5113 → hóa đơn Có 5113
(c) hóa đơn 2 dòng khác nhóm → hai dòng Có riêng, tổng vẫn cân
(d) ghi đè trên sản phẩm thắng nhóm
(e) nhóm chưa khai → rơi về 156/5111 kèm log cảnh báo, không lỗi
(i) ngoại lệ khai bằng dòng map apply_to='product' → thắng dòng của nhóm
(ii) nhóm con chưa khai, nhóm CHA đã khai → vẫn về mặc định + gắn cờ
(iii) bút toán dùng TK mặc định → có cờ, lọc được, kỳ KHÔNG khóa được
(iv) khai bổ sung + làm lại bút toán → kỳ khóa được
(v) dòng map khai TK lệch chế độ → raise
(vi) màn rà soát quét ngược bắt được nhóm mới chưa khai
(vii) dòng map đích danh công ty thắng dòng chung; trường trống vẫn rơi xuống dòng chung
"""
from collections import defaultdict
from contextlib import ExitStack
from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged, TransactionCase
from odoo.tools import float_compare

SYNC_LOGGER = 'odoo.addons.connecta_vas.models.vas_sync'


@tagged('connecta_vas', 'connecta_vas_w5')
class TestW5TaiKhoanDong(TransactionCase):

    GOODS = 1_000_000.0
    SERVICE = 400_000.0
    TAX_RATE = 10.0

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
        else:
            fy.period_ids.write({'state': 'open'})

        cls.partner = cls.env['res.partner'].create({
            'name': 'Đối tác W5',
            'company_id': cls.company.id,
            'supplier_rank': 1,
            'customer_rank': 1,
        })
        cls.sale_tax = cls._make_tax('sale')
        cls.purchase_tax = cls._make_tax('purchase')
        cls.sale_journal = cls._journal('sale')
        cls.purchase_journal = cls._journal('purchase')

        # Bảng ánh xạ mẫu — nay nằm trên vas.account.map, không phải product.category
        cls.cat_goods = cls.env['product.category'].create({'name': 'W5 Hàng hóa'})
        cls.cat_nvl = cls.env['product.category'].create({'name': 'W5 Nguyên vật liệu'})
        cls.cat_service = cls.env['product.category'].create({'name': 'W5 Dịch vụ'})
        cls.cat_empty = cls.env['product.category'].create({'name': 'W5 Chưa khai'})
        cls.cat_parent = cls.env['product.category'].create({'name': 'W5 Nhóm cha'})
        cls.cat_child = cls.env['product.category'].create({
            'name': 'W5 Nhóm con',
            'parent_id': cls.cat_parent.id,
        })

        cls._map(cls.cat_goods, stock='156', revenue='5111', cogs='632')
        cls._map(cls.cat_nvl, stock='152')
        cls._map(cls.cat_service, revenue='5113')
        cls._map(cls.cat_parent, stock='153', revenue='5112', cogs='632')

        uom = cls.env.ref('uom.product_uom_unit')
        cls.p_nvl = cls.env['product.product'].create({
            'name': 'W5 NVL',
            'is_storable': True,
            'categ_id': cls.cat_nvl.id,
            'list_price': cls.GOODS,
            'standard_price': cls.GOODS,
            'uom_id': uom.id,
            'purchase_ok': True,
            'supplier_taxes_id': [Command.clear()],
        })
        cls.p_goods = cls._sellable('W5 Hàng hóa bán', cls.cat_goods, cls.GOODS, 'consu')
        cls.p_service = cls._sellable('W5 Dịch vụ bán', cls.cat_service, cls.SERVICE, 'service')
        cls.p_override = cls._sellable(
            'W5 Thành phẩm ghi đè', cls.cat_service, cls.SERVICE, 'service',
        )
        cls._map(cls.p_override.product_tmpl_id, revenue='5112')
        cls.p_empty = cls._sellable('W5 Không nhóm', cls.cat_empty, cls.GOODS, 'consu')
        cls.p_child = cls._sellable('W5 SP nhóm con', cls.cat_child, cls.GOODS, 'consu')

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
        """Dòng vas.account.map cho một nhóm sản phẩm hoặc một sản phẩm."""
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
    def _sellable(cls, name, category, price, product_type):
        return cls.env['product.product'].create({
            'name': name,
            'type': product_type,
            'is_storable': False,
            'categ_id': category.id,
            'list_price': price,
            'uom_id': cls.env.ref('uom.product_uom_unit').id,
            'sale_ok': True,
            'taxes_id': [Command.set(cls.sale_tax.ids)],
        })

    @classmethod
    def _journal(cls, jtype):
        journal = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id),
            ('type', '=', jtype),
        ], limit=1)
        assert journal, f'Thiếu nhật ký Odoo loại {jtype}'
        return journal

    @classmethod
    def _make_tax(cls, type_tax_use):
        Tax = cls.env['account.tax']
        existing = Tax.search([
            ('company_id', '=', cls.company.id),
            ('type_tax_use', '=', type_tax_use),
            ('amount', '=', cls.TAX_RATE),
            ('amount_type', '=', 'percent'),
        ], limit=1)
        if existing:
            return existing
        return Tax.create({
            'name': f'GTGT 10% W5 {type_tax_use}',
            'amount': cls.TAX_RATE,
            'amount_type': 'percent',
            'type_tax_use': type_tax_use,
            'company_id': cls.company.id,
        })

    @classmethod
    def _ensure_rules(cls):
        """Rule dữ liệu của module; tạo lại nếu DB test chưa nạp XML."""
        Rule = cls.env['vas.rule']
        regime = cls.company.vas_regime_id
        specs = {
            'R01': ('Hóa đơn bán hàng', 'sale_invoice', 10, [
                ('debit', 'partner_receivable', 'total'),
                ('credit', 'product_revenue', 'untaxed'),
                ('credit', 'tax_output', 'tax'),
            ]),
            'R06': ('Nhập kho mua hàng', 'purchase_receipt', 40, [
                ('debit', 'product_inventory', 'stock_value'),
                ('credit', 'receipt_counterpart', 'stock_value'),
            ]),
        }
        for code, (name, event_type, sequence, lines) in specs.items():
            existing = Rule.search([('regime_id', '=', regime.id), ('code', '=', code)], limit=1)
            if existing:
                if code == 'R06':
                    credit = existing.line_ids.filtered(lambda l: l.side == 'credit')[:1]
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
                        'amount_selector': amount,
                    })
                    for i, (side, selector, amount) in enumerate(lines)
                ],
            })

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _sync(self):
        return self.env['vas.sync'].sync_company(
            self.company, date_from='2099-01-01', date_to='2099-12-31',
        )

    def _invoice(self, lines, date='2099-06-15'):
        move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'invoice_date': date,
            'date': date,
            'journal_id': self.sale_journal.id,
            'company_id': self.company.id,
            'invoice_line_ids': [
                Command.create({
                    'product_id': product.id,
                    'name': product.name,
                    'quantity': 1.0,
                    'price_unit': price,
                    'tax_ids': [Command.set(self.sale_tax.ids)],
                })
                for product, price in lines
            ],
        })
        move.action_post()
        return move

    def _receipt(self, product, price, date='2099-06-10'):
        po = self.env['purchase.order'].create({
            'partner_id': self.partner.id,
            'company_id': self.company.id,
            'date_order': date,
            # Không gắn thuế: R06 chỉ ghi giá trị kho, thuế thuộc R07.
            'order_line': [Command.create({
                'product_id': product.id,
                'name': product.name,
                'product_qty': 1.0,
                'price_unit': price,
                'tax_ids': [Command.clear()],
            })],
        })
        po.button_confirm()
        picking = po.picking_ids.filtered(lambda p: p.state != 'done')[:1]
        self.assertTrue(picking, 'PO phải sinh phiếu nhập')
        for move in picking.move_ids:
            move.quantity = 1.0
        picking.button_validate()
        receipt = picking.move_ids.filtered(lambda m: m.state == 'done')[:1]
        receipt.write({'date': fields.Datetime.to_datetime(date)})
        if float_compare(receipt.value or 0.0, 0.0, precision_digits=2) == 0:
            receipt.value = price
        return receipt

    def _vas_lines(self, record, move_kind):
        moves = self.env['vas.move'].search([
            ('source_model', '=', record._name),
            ('source_res_id', '=', record.id),
            ('move_kind', '=', move_kind),
            ('state', '=', 'posted'),
        ])
        return moves.mapped('line_ids')

    def _report(self, scenario, lines):
        rows = [
            f'  {line.account_id.code} N={line.debit} C={line.credit}'
            for line in lines.sorted(lambda l: (l.move_id.id, l.sequence))
        ]
        balances = defaultdict(float)
        for line in lines:
            balances[line.account_id.code] += line.debit - line.credit
        print(
            f'\n=== {scenario} ===\n' + ('\n'.join(rows) or '  (không có dòng)')
            + f'\nSố dư: {dict(sorted(balances.items()))}'
            + f'\nTổng Nợ={sum(lines.mapped("debit"))} Tổng Có={sum(lines.mapped("credit"))}\n'
        )
        return {code: round(value, 2) for code, value in balances.items()}

    # ------------------------------------------------------------------
    # (a) nhóm khai tồn 152
    # ------------------------------------------------------------------

    def test_w5_a_nhap_kho_nvl_vao_152(self):
        receipt = self._receipt(self.p_nvl, self.GOODS)
        self._sync()
        lines = self._vas_lines(receipt, 'stock')
        balances = self._report('(a) Nhập kho NVL — nhóm khai 152', lines)
        self.assertEqual(balances.get('152'), self.GOODS)
        self.assertNotIn('156', balances)
        self.assertEqual(balances.get('331'), -self.GOODS)

    # ------------------------------------------------------------------
    # (b) nhóm dịch vụ khai doanh thu 5113
    # ------------------------------------------------------------------

    def test_w5_b_dich_vu_doanh_thu_5113(self):
        invoice = self._invoice([(self.p_service, self.SERVICE)])
        self._sync()
        lines = self._vas_lines(invoice, 'sale_inv')
        balances = self._report('(b) Hóa đơn dịch vụ — nhóm khai 5113', lines)
        tax = self.SERVICE * self.TAX_RATE / 100.0
        self.assertEqual(balances.get('5113'), -self.SERVICE)
        self.assertNotIn('5111', balances)
        self.assertEqual(balances.get('131'), self.SERVICE + tax)
        self.assertEqual(balances.get('33311'), -tax)

    # ------------------------------------------------------------------
    # (c) hóa đơn hai dòng khác nhóm
    # ------------------------------------------------------------------

    def test_w5_c_hoa_don_hai_dong_tach_doanh_thu(self):
        invoice = self._invoice([
            (self.p_goods, self.GOODS),
            (self.p_service, self.SERVICE),
        ])
        self._sync()
        lines = self._vas_lines(invoice, 'sale_inv')
        balances = self._report('(c) Hóa đơn 2 dòng — 5111 + 5113', lines)

        untaxed = self.GOODS + self.SERVICE
        tax = untaxed * self.TAX_RATE / 100.0
        revenue_lines = lines.filtered(lambda l: l.account_id.code in ('5111', '5113'))
        self.assertEqual(len(revenue_lines), 2, 'Phải có đúng hai dòng Có doanh thu riêng')
        self.assertEqual(balances.get('5111'), -self.GOODS)
        self.assertEqual(balances.get('5113'), -self.SERVICE)
        self.assertEqual(balances.get('131'), untaxed + tax)
        self.assertEqual(balances.get('33311'), -tax)
        self.assertAlmostEqual(sum(lines.mapped('debit')), sum(lines.mapped('credit')), 2)

    # ------------------------------------------------------------------
    # (d) ghi đè trên sản phẩm
    # ------------------------------------------------------------------

    def test_w5_d_ghi_de_tren_san_pham(self):
        Map = self.env['vas.account.map']
        regime = self.company.vas_regime_id
        self.assertEqual(
            Map._find_row(regime, self.company, 'category', self.cat_service.id)
            .revenue_account_id.code,
            '5113',
        )
        invoice = self._invoice([(self.p_override, self.SERVICE)])
        self._sync()
        lines = self._vas_lines(invoice, 'sale_inv')
        balances = self._report('(d) Ghi đè trên sản phẩm — 5112 thắng 5113', lines)
        self.assertEqual(balances.get('5112'), -self.SERVICE)
        self.assertNotIn('5113', balances)

    # ------------------------------------------------------------------
    # (e) nhóm chưa khai → mặc định + log cảnh báo
    # ------------------------------------------------------------------

    def test_w5_e_nhom_chua_khai_roi_ve_mac_dinh(self):
        invoice = self._invoice([(self.p_empty, self.GOODS)])
        with self.assertLogs(SYNC_LOGGER, level='WARNING') as captured:
            self._sync()
        lines = self._vas_lines(invoice, 'sale_inv')
        balances = self._report('(e) Nhóm chưa khai — về mặc định 5111', lines)
        self.assertEqual(balances.get('5111'), -self.GOODS)
        warned = [
            msg for msg in captured.output
            if 'product_revenue' in msg and self.p_empty.name in msg
        ]
        self.assertTrue(warned, f'Thiếu log cảnh báo nhóm chưa khai: {captured.output}')
        print(f'\n=== (e) log cảnh báo ===\n  {warned[0]}\n')

    # ------------------------------------------------------------------
    # (i) ngoại lệ cấp sản phẩm khai bằng dòng map apply_to='product'
    # ------------------------------------------------------------------

    def test_w5_i_dong_map_san_pham_thang_dong_nhom(self):
        product = self._sellable('W5 SP ngoại lệ map', self.cat_goods, self.GOODS, 'consu')
        self._map(product.product_tmpl_id, revenue='5112')
        invoice = self._invoice([(product, self.GOODS)])
        self._sync()
        lines = self._vas_lines(invoice, 'sale_inv')
        balances = self._report(
            "(i) Dòng map apply_to='product' thắng dòng nhóm (5112 thay 5111)", lines,
        )
        self.assertEqual(balances.get('5112'), -self.GOODS)
        self.assertNotIn('5111', balances)

    # ------------------------------------------------------------------
    # (ii) nhóm con chưa khai, nhóm cha đã khai → KHÔNG leo, về mặc định
    # ------------------------------------------------------------------

    def test_w5_ii_khong_leo_nhom_cha(self):
        Map = self.env['vas.account.map']
        regime = self.company.vas_regime_id
        parent_row = Map._find_row(regime, self.company, 'category', self.cat_parent.id)
        self.assertEqual(parent_row.revenue_account_id.code, '5112', 'Nhóm cha phải đã khai')
        self.assertFalse(
            Map._find_row(regime, self.company, 'category', self.cat_child.id),
            'Nhóm con phải chưa khai',
        )
        invoice = self._invoice([(self.p_child, self.GOODS)])
        self._sync()
        lines = self._vas_lines(invoice, 'sale_inv')
        balances = self._report(
            '(ii) Nhóm con chưa khai, cha khai 5112 → vẫn về mặc định 5111', lines,
        )
        self.assertEqual(balances.get('5111'), -self.GOODS)
        self.assertNotIn('5112', balances)
        move = lines[:1].move_id
        self.assertTrue(move.vas_has_default_account, 'Phải gắn cờ dùng TK mặc định')
        self.assertIn(self.cat_child.name, move.narration or '')
        print(f'\n=== (ii) ghi chú trên bút toán ===\n{move.narration}\n')

    # ------------------------------------------------------------------
    # (iii) cờ + lọc được + kỳ KHÔNG khóa được
    # ------------------------------------------------------------------

    def test_w5_iii_co_va_chan_khoa_ky(self):
        invoice = self._invoice([(self.p_empty, self.GOODS)])
        self._sync()
        move = self._vas_lines(invoice, 'sale_inv')[:1].move_id
        self.assertTrue(move.vas_has_default_account)

        flagged = self.env['vas.move'].search([
            ('company_id', '=', self.company.id),
            ('vas_has_default_account', '=', True),
        ])
        self.assertIn(move, flagged, 'Bộ lọc "Dùng TK mặc định" phải bắt được bút toán này')
        print(
            f'\n=== (iii) lọc TK mặc định ===\n'
            f'  {len(flagged)} bút toán có cờ, gồm {move.name} (kỳ {move.period_id.display_name})\n'
            f'  Ghi chú: {move.narration}\n'
        )

        with self.assertRaises(UserError) as caught:
            move.period_id.state = 'closed'
        self.assertIn('không khóa được', str(caught.exception).lower())
        print(f'=== (iii) chặn khóa kỳ ===\n  {caught.exception}\n')
        self.assertEqual(move.period_id.state, 'open')

    # ------------------------------------------------------------------
    # (iv) khai bổ sung + xử lý lại bút toán → khóa được
    # ------------------------------------------------------------------

    def test_w5_iv_khai_bo_sung_thi_khoa_duoc(self):
        invoice = self._invoice([(self.p_empty, self.GOODS)])
        self._sync()
        move = self._vas_lines(invoice, 'sale_inv')[:1].move_id
        period = move.period_id
        self.assertTrue(move.vas_has_default_account)

        self._map(self.cat_empty, stock='156', revenue='5111', cogs='632')
        move.action_reverse()
        self._sync()

        remade = self.env['vas.move'].search([
            ('source_model', '=', invoice._name),
            ('source_res_id', '=', invoice.id),
            ('move_kind', '=', 'sale_inv'),
            ('state', '=', 'posted'),
            ('is_reversal', '=', False),
        ])
        self.assertTrue(remade, 'Đồng bộ lại phải sinh bút toán mới')
        self.assertFalse(
            remade.filtered('vas_has_default_account'),
            'Bút toán làm lại không được còn cờ TK mặc định',
        )
        balances = self._report('(iv) Sau khi khai bổ sung', remade.line_ids)
        self.assertEqual(balances.get('5111'), -self.GOODS)

        period.state = 'closed'
        self.assertEqual(period.state, 'closed', 'Khai đủ rồi thì kỳ phải khóa được')
        print(f'=== (iv) đã khóa kỳ {period.display_name} ===\n')
        period.state = 'open'

    # ------------------------------------------------------------------
    # (v) dòng map khai TK lệch chế độ → raise
    # ------------------------------------------------------------------

    def test_w5_v_tk_lech_che_do_thi_raise(self):
        other = self.env['vas.regime'].create({'code': 'W5X', 'name': 'Chế độ khác'})
        foreign = self.env['vas.account'].create({
            'code': '5111',
            'name': 'Doanh thu chế độ khác',
            'account_type': 'income',
            'ending_balance_policy': 'none',
            'regime_id': other.id,
        })
        category = self.env['product.category'].create({'name': 'W5 Lệch chế độ'})
        with self.assertRaises(ValidationError) as caught:
            self.env['vas.account.map'].create({
                'regime_id': self.company.vas_regime_id.id,
                'apply_to': 'category',
                'category_id': category.id,
                'company_id': self.company.id,
                'revenue_account_id': foreign.id,
            })
        print(f'\n=== (v) chặn TK lệch chế độ ===\n  {caught.exception}\n')

    # ------------------------------------------------------------------
    # (vi) màn rà soát quét ngược bắt được nhóm mới chưa khai
    # ------------------------------------------------------------------

    def test_w5_vi_man_ra_soat_bat_nhom_chua_khai(self):
        category = self.env['product.category'].create({'name': 'W5 Nhóm mới chưa khai'})
        self._sellable('W5 SP nhóm mới', category, self.GOODS, 'consu')
        Review = self.env['vas.account.map.review']

        row = Review.search([
            ('category_id', '=', category.id),
            ('company_id', '=', self.company.id),
        ])
        self.assertEqual(len(row), 1, 'Nhóm mới có sản phẩm phải xuất hiện đúng một dòng')
        self.assertEqual(row.state, 'missing')
        self.assertEqual(row.product_count, 1)
        self.assertFalse(row.map_id)

        missing = Review.search([
            ('company_id', '=', self.company.id),
            ('state', 'in', ('missing', 'partial')),
        ])
        self.assertIn(row, missing, 'Bộ lọc "thiếu cấu hình" phải chứa nhóm này')
        print(
            '\n=== (vi) màn rà soát ===\n'
            + '\n'.join(
                f'  {r.category_id.display_name}: {r.product_count} SP, '
                f'tồn={r.stock_account_id.code or "-"} '
                f'DT={r.revenue_account_id.code or "-"} '
                f'GV={r.cogs_account_id.code or "-"} → {r.state}'
                for r in missing
            )
            + '\n'
        )

        # Khai ngay tại màn rà soát → nhóm hết thiếu
        action = row.action_configure()
        self.assertEqual(action['res_model'], 'vas.account.map')
        self.env['vas.account.map'].create({
            **{k[len('default_'):]: v for k, v in action['context'].items()},
            'stock_account_id': self._acc('156').id,
            'revenue_account_id': self._acc('5111').id,
            'cogs_account_id': self._acc('632').id,
        })
        row = Review.search([
            ('category_id', '=', category.id),
            ('company_id', '=', self.company.id),
        ])
        self.assertEqual(row.state, 'ok')
        print(f'  → sau khi khai: {row.state}\n')

    # ------------------------------------------------------------------
    # (vii) tầng company_id: dòng đích danh công ty thắng dòng chung
    # ------------------------------------------------------------------

    def test_w5_vii_tang_company_id(self):
        regime = self.company.vas_regime_id
        # hr_timesheet.res_company.create dựng project "Internal"; trên bản Enterprise
        # này project.billing_type vừa là trường tính vừa required nên INSERT không
        # mang giá trị và đụng NOT NULL. Lỗi core, không liên quan VAS — vô hiệu đúng
        # bước đó để test tập trung vào tầng company_id của bảng ánh xạ.
        # DB không cài hr_timesheet thì không có method này, khi đó khỏi vá.
        Company = type(self.env['res.company'])
        with ExitStack() as stack:
            if hasattr(Company, '_create_internal_project_task'):
                stack.enter_context(patch.object(
                    Company, '_create_internal_project_task', lambda records: None,
                ))
            company_b = self.env['res.company'].create({
                'name': 'W5 Công ty B',
                'vas_regime_id': regime.id,
            })
        category = self.env['product.category'].create({'name': 'W5 Hai tầng công ty'})
        product = self._sellable('W5 SP hai tầng', category, self.GOODS, 'consu')
        Map = self.env['vas.account.map']
        Map.create({
            'regime_id': regime.id,
            'apply_to': 'category',
            'category_id': category.id,
            'company_id': False,
            'revenue_account_id': self._acc('5111').id,
            'stock_account_id': self._acc('156').id,
        })
        Map.create({
            'regime_id': regime.id,
            'apply_to': 'category',
            'category_id': category.id,
            'company_id': self.company.id,
            'revenue_account_id': self._acc('5112').id,
        })

        Sync = self.env['vas.sync']
        a_revenue = Sync._product_account(product, 'product_revenue', self.company)
        b_revenue = Sync._product_account(product, 'product_revenue', company_b)
        # Dòng đích danh công ty A bỏ trống TK tồn kho → riêng trường đó rơi
        # tiếp xuống dòng chung, không kéo cả dòng.
        a_stock = Sync._product_account(product, 'product_inventory', self.company)

        print(
            '\n=== (vii) tầng company_id ===\n'
            f'  dòng chung           : DT 5111, tồn 156\n'
            f'  dòng công ty {self.company.name[:18]:<18}: DT 5112, tồn (trống)\n'
            f'  → công ty A ({self.company.name[:18]:<18}) DT={a_revenue.code} tồn={a_stock.code}\n'
            f'  → công ty B ({company_b.name[:18]:<18}) DT={b_revenue.code}\n'
        )
        self.assertEqual(a_revenue.code, '5112', 'Công ty A phải lấy dòng đích danh')
        self.assertEqual(b_revenue.code, '5111', 'Công ty B phải lấy dòng chung')
        self.assertEqual(a_stock.code, '156', 'Trường trống phải rơi xuống dòng chung')
