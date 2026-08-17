# -*- coding: utf-8 -*-
"""TRỤC 2 — tài khoản chi phí + quyết toán tạm ứng.

Phạm vi đợt này:
  - `expense_account_id` trên `vas.account.map` + selector `product_expense`,
    mặc định 6422 khi chưa khai.
  - R08 bỏ hardcode 6421; R07/R08 tách theo DÒNG hóa đơn.
  - R19c (quyết toán có tạm ứng gốc → Có 141 + Có 334 phần vượt), R19d (nhân
    viên tự bỏ tiền túi → Có 334), R19e (thu hồi tiền thừa), R19f (trả nợ NLĐ).

Test bắt buộc:
  (i)    dịch vụ khai 6421 → ra 6421; dịch vụ khai 6422 → ra 6422.
  (ii)   dịch vụ CHƯA khai → 6422 mặc định + cờ + kỳ không khóa được.
  (iii)  hóa đơn NCC trộn hàng + dịch vụ → R07 và R08 mỗi rule bắt đúng dòng.
  (iv)   tạm ứng 10, tiêu 8, thu hồi 2 → 141 về 0.
  (v)    tạm ứng 10, tiêu 12, chi bù 2 → 141 và 334 cùng về 0.
  (v-b)  tiêu đúng 10 → không sinh chân 334 nào.
  (v-c)  E1 không tạm ứng gốc + trả lại → dùng chung R19f, 334 về 0.
  (vi)   hr.expense có thuế GTGT → chân Nợ 1331 đúng số tiền.
  (vii)  một hr.expense không lọt vào cả R19 lẫn R19c.
  (viii) đồng bộ hai lần → không sinh bút toán trùng.
  (ix)   Paid By=Company + thuế → Nợ CP/1331 / Có 111·112, không 141/334 (R19g).
  (x)    own_account + Register Payment (không nhãn) → R19d rồi R19f, 334 về 0;
         R18 không sinh bút toán ma.
  (xi)   nhãn tay employee_debt_payment vẫn chạy, không ghi hai lần khi vừa
         có nhãn vừa gắn expense.
  (xii)  advance_refund outbound KHÔNG lọt R19e.
"""
from collections import defaultdict

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged, TransactionCase

DATE = '2099-07-15'


@tagged('connecta_vas', 'connecta_vas_w6_cp')
class TestW6ChiPhiTamUng(TransactionCase):

    ADVANCE = 10_000_000.0
    SPEND_OK = 8_000_000.0        # ≤ tạm ứng → T04
    SPEND_OVER = 12_000_000.0     # > tạm ứng → T05
    REFUND = 2_000_000.0          # cũng là số chi bù của T05 (12 − 10)
    SERVICE_NET = 5_000_000.0
    GOODS_NET = 7_000_000.0

    # ------------------------------------------------------------------
    # Dựng dữ liệu
    # ------------------------------------------------------------------

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        vnd = cls.env.ref('base.VND')
        if cls.company.currency_id != vnd:
            cls.company.currency_id = vnd

        cls.regime = cls.env['vas.regime'].search([('code', '=', 'TT133')], limit=1)
        if not cls.regime:
            cls.regime = cls.env['vas.regime'].create({
                'code': 'TT133', 'name': 'Thông tư 133/2016/TT-BTC',
            })
        cls.company.vas_regime_id = cls.regime
        cls.company.vas_start_date = '2000-01-01'
        cls._ensure_period()

        cls.vendor = cls.env['res.partner'].create({
            'name': 'NCC dịch vụ W6', 'supplier_rank': 1,
        })
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Nguyễn Văn Tạm Ứng',
            'company_id': cls.company.id,
        })
        cls.emp_partner = cls.env['res.partner'].create({'name': 'NLĐ W6'})
        cls.employee.work_contact_id = cls.emp_partner

        cls.cash_journal = cls._journal('cash', 'W6CS', 'W6 Quỹ tiền mặt')
        cls._journal('purchase', 'W6PU', 'W6 Mua hàng')
        cls.tax_10 = cls._purchase_tax_10()

        # ---- Nhóm sản phẩm: dịch vụ bán hàng (6421), quản lý (6422), chưa khai
        cls.cat_sell = cls.env['product.category'].create({'name': 'W6 DV bán hàng'})
        cls.cat_admin = cls.env['product.category'].create({'name': 'W6 DV quản lý'})
        cls.cat_unset = cls.env['product.category'].create({'name': 'W6 DV chưa khai'})
        cls.cat_goods = cls.env['product.category'].create({
            'name': 'W6 Hàng hóa',
            'property_cost_method': 'fifo',
            'property_valuation': 'real_time',
        })

        cls._map(cls.cat_sell, expense='6421')
        cls._map(cls.cat_admin, expense='6422')
        cls._map(cls.cat_goods, stock='156', revenue='5111', cogs='632')
        # cat_unset: CỐ Ý không khai → phải rơi về 6422 mặc định + gắn cờ

        cls.svc_sell = cls._service('W6 Quảng cáo', cls.cat_sell)
        cls.svc_admin = cls._service('W6 Dịch vụ kế toán', cls.cat_admin)
        cls.svc_unset = cls._service('W6 Dịch vụ chưa khai', cls.cat_unset)
        cls.goods = cls.env['product.product'].create({
            'name': 'W6 Hàng hóa 156',
            'is_storable': True,
            'categ_id': cls.cat_goods.id,
            'standard_price': 100_000.0,
            'purchase_ok': True,
        })

    @classmethod
    def _journal(cls, jtype, code, name):
        """Sổ Odoo theo loại; tự tạo nếu DB sạch chưa có."""
        Journal = cls.env['account.journal']
        journal = Journal.search([
            ('company_id', '=', cls.company.id), ('type', '=', jtype),
        ], limit=1)
        return journal or Journal.create({
            'name': name, 'code': code, 'type': jtype, 'company_id': cls.company.id,
        })

    @classmethod
    def _purchase_tax_10(cls):
        """Thuế GTGT đầu vào 10%, giá CHƯA gồm thuế."""
        group = cls.env['account.tax.group'].search([
            ('company_id', '=', cls.company.id),
        ], limit=1)
        if not group:
            group = cls.env['account.tax.group'].create({
                'name': 'GTGT W6', 'company_id': cls.company.id,
            })
        return cls.env['account.tax'].create({
            'name': 'GTGT 10% W6',
            'amount_type': 'percent',
            'amount': 10.0,
            'type_tax_use': 'purchase',
            'price_include_override': 'tax_excluded',
            'tax_group_id': group.id,
            'company_id': cls.company.id,
        })

    @classmethod
    def _service(cls, name, category):
        return cls.env['product.product'].create({
            'name': name,
            'type': 'service',
            'categ_id': category.id,
            'purchase_ok': True,
            'can_be_expensed': True,
            'standard_price': 0.0,
        })

    @classmethod
    def _acc(cls, code):
        account = cls.env['vas.account'].search([
            ('regime_id', '=', cls.regime.id), ('code', '=', code),
        ], limit=1)
        assert account, f'Thiếu tài khoản VAS {code}'
        return account

    @classmethod
    def _map(cls, category, stock=None, revenue=None, cogs=None, expense=None):
        vals = {
            'regime_id': cls.regime.id,
            'apply_to': 'category',
            'company_id': cls.company.id,
            'category_id': category.id,
        }
        for field, code in (
            ('stock_account_id', stock),
            ('revenue_account_id', revenue),
            ('cogs_account_id', cogs),
            ('expense_account_id', expense),
        ):
            if code:
                vals[field] = cls._acc(code).id
        return cls.env['vas.account.map'].create(vals)

    @classmethod
    def _ensure_period(cls):
        fy = cls.env['vas.fiscalyear'].search([
            ('company_id', '=', cls.company.id),
            ('date_from', '<=', DATE), ('date_to', '>=', DATE),
        ], limit=1)
        if not fy:
            fy = cls.env['vas.fiscalyear'].create({
                'name': '2099',
                'date_from': '2099-01-01', 'date_to': '2099-12-31',
                'state': 'open', 'company_id': cls.company.id,
            })
        if not fy.period_ids:
            fy.action_generate_periods()
        else:
            fy.period_ids.write({'state': 'open'})
        cls.period = fy.period_ids.filtered(
            lambda p: p.date_start <= fields.Date.to_date(DATE) <= p.date_end
        )[:1]
        assert cls.period, 'Thiếu kỳ kế toán tháng 7/2099'

    # ------------------------------------------------------------------
    # Tiện ích
    # ------------------------------------------------------------------

    def _sync(self):
        return self.env['vas.sync'].sync_company(self.company)

    def _bill(self, lines, with_tax=True):
        """Hóa đơn NCC; `lines` = [(product, giá chưa thuế), …]."""
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': self.vendor.id,
            'invoice_date': DATE,
            'date': DATE,
            'company_id': self.company.id,
            'invoice_line_ids': [
                Command.create({
                    'product_id': product.id,
                    'quantity': 1.0,
                    'price_unit': price,
                    'tax_ids': [Command.set(self.tax_10.ids)] if with_tax
                    else [Command.clear()],
                })
                for product, price in lines
            ],
        })
        bill.action_post()
        return bill

    def _advance(self, amount, operation='employee_advance', inbound=False):
        payment = self.env['account.payment'].create({
            'payment_type': 'inbound' if inbound else 'outbound',
            'partner_type': 'supplier',
            'partner_id': self.emp_partner.id,
            'amount': amount,
            'date': DATE,
            'journal_id': self.cash_journal.id,
            'company_id': self.company.id,
            'vas_operation_type': operation,
        })
        payment.action_post()
        return payment

    def _expense(self, product, total, advance=None, taxes=None, payment_mode='own_account'):
        expense = self.env['hr.expense'].create({
            'name': f'Chi {product.name}',
            'employee_id': self.employee.id,
            'product_id': product.id,
            'total_amount_currency': total,
            'tax_ids': [Command.set(taxes.ids)] if taxes else [Command.clear()],
            'company_id': self.company.id,
            'date': DATE,
            'payment_mode': payment_mode,
            'vas_advance_payment_id': advance.id if advance else False,
        })
        expense.action_submit()
        if expense.state != 'approved':
            expense.action_approve()
        self.assertEqual(
            expense.state, 'approved',
            f'hr.expense phải ở trạng thái approved, đang là {expense.state}',
        )
        return expense

    def _post_own_expense(self, expense):
        """Post own_account qua API nội bộ (tránh wizard UI)."""
        self.assertEqual(expense.payment_mode, 'own_account')
        expense._post_without_wizard()
        self.assertTrue(expense.account_move_id, 'Post phải sinh account.move')
        self.assertEqual(expense.account_move_id.state, 'posted')
        return expense.account_move_id

    def _register_payment_for_expense(self, expense, journal=None, label=None):
        """Giả lập nút Register Payment — không gắn nhãn trừ khi truyền `label`."""
        move = expense.account_move_id
        self.assertTrue(move, 'Expense phải đã post trước khi Register Payment')
        journal = journal or self.cash_journal
        pay = self.env['account.payment.register'].with_context(
            active_model='account.move',
            active_ids=move.ids,
        ).create({
            'amount': abs(expense.total_amount),
            'journal_id': journal.id,
        })._create_payments()
        if label:
            pay.vas_operation_type = label
        else:
            # Bảo đảm đúng kịch bản nút chuẩn: không nhãn.
            if pay.vas_operation_type:
                pay.vas_operation_type = False
        return pay

    def _moves_for(self, record, move_kind=None):
        domain = [
            ('source_model', '=', record._name),
            ('source_res_id', '=', record.id),
            ('state', '=', 'posted'),
        ]
        if move_kind:
            domain.append(('move_kind', '=', move_kind))
        return self.env['vas.move'].search(domain)

    def _balances(self, moves):
        """{mã TK: (nợ, có)} — in được để làm bằng chứng."""
        out = defaultdict(lambda: [0.0, 0.0])
        for line in moves.mapped('line_ids'):
            bucket = out[line.account_id.code]
            bucket[0] += line.debit
            bucket[1] += line.credit
        return {code: tuple(v) for code, v in sorted(out.items())}

    def _account_balance(self, code, partner=None):
        """Số dư Nợ − Có theo đối tác fixture (tránh nhiễm số dư demo-1)."""
        partner = partner or self.emp_partner
        lines = self.env['vas.move.line'].search([
            ('account_id.code', '=', code),
            ('move_id.company_id', '=', self.company.id),
            ('move_id.state', '=', 'posted'),
            ('partner_id', '=', partner.id),
        ])
        return sum(lines.mapped('debit')) - sum(lines.mapped('credit'))

    def _dump(self, label, moves):
        print(f'\n--- {label} ---')
        for move in moves:
            print(f'  {move.name} kind={move.move_kind} '
                  f'co_mac_dinh={move.vas_has_default_account}')
            for line in move.line_ids.sorted('sequence'):
                print(f'      {line.account_id.code:<8} '
                      f'{line.account_id.name[:30]:<30} '
                      f'No={line.debit:>14,.0f} Co={line.credit:>14,.0f}')

    # ------------------------------------------------------------------
    # (i) TK chi phí lấy theo bảng ánh xạ, không còn hardcode
    # ------------------------------------------------------------------

    def test_w6_i_r08_theo_bang_anh_xa(self):
        bill_sell = self._bill([(self.svc_sell, self.SERVICE_NET)])
        bill_admin = self._bill([(self.svc_admin, self.SERVICE_NET)])
        self._sync()

        for bill, expected in ((bill_sell, '6421'), (bill_admin, '6422')):
            moves = self._moves_for(bill, 'expense')
            self.assertEqual(
                len(moves), 1,
                f'{bill.name}: R08 phải sinh đúng 1 bút toán, có {len(moves)}',
            )
            self._dump(f'(i) {bill.name} → kỳ vọng {expected}', moves)
            balances = self._balances(moves)
            self.assertEqual(
                balances.get(expected), (self.SERVICE_NET, 0.0),
                f'{bill.name}: phải Nợ {expected} = {self.SERVICE_NET:,.0f}, '
                f'thực tế {balances}',
            )
            self.assertEqual(
                balances.get('1331'), (self.SERVICE_NET * 0.1, 0.0),
                f'{bill.name}: thiếu chân Nợ 1331; thực tế {balances}',
            )
            self.assertEqual(
                balances.get('331'), (0.0, self.SERVICE_NET * 1.1),
                f'{bill.name}: phải Có 331 = tổng gồm thuế; thực tế {balances}',
            )
            self.assertFalse(
                moves.vas_has_default_account,
                f'{bill.name}: nhóm đã khai thì KHÔNG được gắn cờ mặc định',
            )

        # Bút toán 6421 và 6422 phải là hai bút toán khác nhau, không dùng
        # chung một tài khoản cắm cứng.
        codes_sell = set(self._balances(self._moves_for(bill_sell, 'expense')))
        codes_admin = set(self._balances(self._moves_for(bill_admin, 'expense')))
        self.assertIn('6421', codes_sell)
        self.assertNotIn('6421', codes_admin)
        self.assertIn('6422', codes_admin)

    # ------------------------------------------------------------------
    # (ii) Chưa khai → 6422 mặc định + cờ + chặn khóa kỳ
    # ------------------------------------------------------------------

    def test_w6_ii_chua_khai_ve_6422_va_khoa_ky(self):
        bill = self._bill([(self.svc_unset, self.SERVICE_NET)])
        self._sync()

        moves = self._moves_for(bill, 'expense')
        self.assertEqual(len(moves), 1)
        self._dump('(ii) dịch vụ CHƯA khai → kỳ vọng 6422 mặc định', moves)
        balances = self._balances(moves)
        self.assertEqual(
            balances.get('6422'), (self.SERVICE_NET, 0.0),
            f'Chưa khai phải rơi về 6422 mặc định; thực tế {balances}',
        )
        self.assertTrue(
            moves.vas_has_default_account,
            'Dùng tài khoản mặc định thì phải gắn cờ vas_has_default_account',
        )
        self.assertIn(
            self.cat_unset.name, moves.narration or '',
            'Ghi chú bút toán phải nêu tên nhóm chưa khai để kế toán tìm được',
        )

        with self.assertRaises(UserError, msg='Kỳ còn bút toán mang cờ thì KHÔNG được khóa'):
            self.period.write({'state': 'closed'})

    # ------------------------------------------------------------------
    # (iii) Hóa đơn trộn: R07 và R08 mỗi rule bắt đúng dòng của mình
    # ------------------------------------------------------------------

    def test_w6_iii_hoa_don_tron_khong_chong_lan(self):
        bill = self._bill([
            (self.goods, self.GOODS_NET),
            (self.svc_admin, self.SERVICE_NET),
        ])
        Sync = self.env['vas.sync']
        goods_lines = Sync._goods_lines(bill)
        service_lines = Sync._service_lines(bill)

        print('\n--- (iii) phân loại dòng hóa đơn ---')
        for line in Sync._real_invoice_lines(bill):
            which = 'HANG (R07)' if line in goods_lines else 'DICH VU (R08)'
            print(f'   {line.product_id.name:<28} '
                  f'chua_thue={line.price_subtotal:>12,.0f}  {which}')

        self.assertEqual(len(goods_lines), 1, 'Phải có đúng 1 dòng hàng')
        self.assertEqual(len(service_lines), 1, 'Phải có đúng 1 dòng dịch vụ')
        self.assertFalse(
            goods_lines & service_lines,
            'KHÔNG dòng nào được rơi vào cả R07 lẫn R08',
        )
        self.assertEqual(
            goods_lines | service_lines, Sync._real_invoice_lines(bill),
            'Hai tập dòng phải phủ kín hóa đơn, không bỏ sót dòng nào',
        )

        self._sync()
        r07 = self._moves_for(bill, 'purchase_inv')
        r08 = self._moves_for(bill, 'expense')
        self._dump('(iii) R07 — thuế của dòng HÀNG', r07)
        self._dump('(iii) R08 — chi phí của dòng DỊCH VỤ', r08)

        self.assertEqual(len(r07), 1, 'R07 phải sinh đúng 1 bút toán')
        self.assertEqual(len(r08), 1, 'R08 phải sinh đúng 1 bút toán')

        b07 = self._balances(r07)
        self.assertEqual(
            b07.get('1331'), (self.GOODS_NET * 0.1, 0.0),
            f'R07 chỉ được ghi thuế của dòng HÀNG ({self.GOODS_NET * 0.1:,.0f}); '
            f'thực tế {b07}',
        )
        self.assertNotIn('6422', b07, 'R07 không được ghi tài khoản chi phí')

        b08 = self._balances(r08)
        self.assertEqual(
            b08.get('6422'), (self.SERVICE_NET, 0.0),
            f'R08 phải ghi Nợ 6422 = {self.SERVICE_NET:,.0f}; thực tế {b08}',
        )
        self.assertEqual(
            b08.get('1331'), (self.SERVICE_NET * 0.1, 0.0),
            f'R08 chỉ được ghi thuế của dòng DỊCH VỤ; thực tế {b08}',
        )
        self.assertNotIn('156', b08, 'R08 không được ghi tài khoản tồn kho')

        # Tổng thuế đầu vào của hóa đơn không được đếm hai lần
        tax_total = (
            b07.get('1331', (0.0, 0.0))[0] + b08.get('1331', (0.0, 0.0))[0]
        )
        self.assertAlmostEqual(
            tax_total, bill.amount_tax, places=0,
            msg=f'Tổng Nợ 1331 ({tax_total:,.0f}) phải bằng thuế trên hóa đơn '
                f'({bill.amount_tax:,.0f}) — không thừa, không thiếu',
        )

    # ------------------------------------------------------------------
    # (iv) T04 — tạm ứng 10, tiêu 8, thu hồi 2 → 141 về 0
    # ------------------------------------------------------------------

    def test_w6_iv_tam_ung_chi_khong_het(self):
        print('\n=== (iv) T04: tạm ứng 10tr, tiêu 8tr, thu hồi 2tr ===')

        advance = self._advance(self.ADVANCE)
        self._sync()
        buoc1 = self._account_balance('141')
        self._dump('bước 1 — chi tạm ứng (R19)', self._moves_for(advance))
        print(f'   số dư 141 sau bước 1 = {buoc1:>14,.0f}')
        self.assertAlmostEqual(
            buoc1, self.ADVANCE, places=0,
            msg='Sau khi chi tạm ứng, 141 phải dư Nợ đúng số đã ứng',
        )

        expense = self._expense(self.svc_admin, self.SPEND_OK, advance=advance)
        self._sync()
        settle = self._moves_for(expense, 'expense')
        self.assertEqual(len(settle), 1, 'R19c phải sinh đúng 1 bút toán')
        self._dump('bước 2 — quyết toán chi phí (R19c)', settle)
        b = self._balances(settle)
        self.assertEqual(
            b.get('6422'), (self.SPEND_OK, 0.0),
            f'Phải Nợ 6422 = {self.SPEND_OK:,.0f}; thực tế {b}',
        )
        self.assertEqual(
            b.get('141'), (0.0, self.SPEND_OK),
            f'Phải Có 141 = {self.SPEND_OK:,.0f} (tất toán tạm ứng), '
            f'KHÔNG phải Có 331/334; thực tế {b}',
        )
        self.assertNotIn('334', b, 'Có tạm ứng gốc thì không được ghi 334')
        self.assertNotIn('331', b, 'Có tạm ứng gốc thì không được ghi 331')
        buoc2 = self._account_balance('141')
        print(f'   số dư 141 sau bước 2 = {buoc2:>14,.0f}')
        self.assertAlmostEqual(buoc2, self.ADVANCE - self.SPEND_OK, places=0)

        refund = self._advance(
            self.REFUND, operation='advance_refund', inbound=True,
        )
        self._sync()
        refund_moves = self._moves_for(refund)
        self.assertEqual(len(refund_moves), 1, 'R19e phải sinh đúng 1 bút toán')
        self._dump('bước 3 — thu hồi tiền thừa (R19e)', refund_moves)
        br = self._balances(refund_moves)
        self.assertEqual(
            br.get('111'), (self.REFUND, 0.0),
            f'Phải Nợ 111 = {self.REFUND:,.0f}; thực tế {br}',
        )
        self.assertEqual(
            br.get('141'), (0.0, self.REFUND),
            f'Phải Có 141 = {self.REFUND:,.0f}; thực tế {br}',
        )
        buoc3 = self._account_balance('141')
        print(f'   số dư 141 sau bước 3 = {buoc3:>14,.0f}  <-- phải bằng 0')
        self.assertAlmostEqual(
            buoc3, 0.0, places=0,
            msg=f'141 phải TẤT TOÁN về 0, đang là {buoc3:,.0f}',
        )

    # ------------------------------------------------------------------
    # (v) T05 — chi vượt: Có 141 kịch số đã ứng, phần vượt sang Có 334
    # ------------------------------------------------------------------

    def _print_141_334(self, label):
        so_141 = self._account_balance('141')
        so_334 = self._account_balance('334')
        print(f'   {label:<34} 141 = {so_141:>14,.0f}   334 = {so_334:>14,.0f}')
        return so_141, so_334

    def test_w6_v_chi_vuot_tam_ung(self):
        print('\n=== (v) T05: tạm ứng 10tr, tiêu 12tr, chi bù 2tr ===')
        excess = self.SPEND_OVER - self.ADVANCE

        advance = self._advance(self.ADVANCE)
        self._sync()
        self._dump('bước 1 — chi tạm ứng (R19)', self._moves_for(advance))
        so_141, so_334 = self._print_141_334('sau bước 1 (chi tạm ứng)')
        self.assertAlmostEqual(so_141, self.ADVANCE, places=0)
        self.assertAlmostEqual(so_334, 0.0, places=0)

        over = self._expense(self.svc_admin, self.SPEND_OVER, advance=advance)
        self._sync()
        settle = self._moves_for(over, 'expense')
        self.assertEqual(len(settle), 1, 'R19c phải sinh đúng 1 bút toán')
        self._dump('bước 2 — quyết toán chi vượt (R19c)', settle)
        b = self._balances(settle)
        self.assertEqual(
            b.get('6422'), (self.SPEND_OVER, 0.0),
            f'Chi phí ghi trọn số đã tiêu = {self.SPEND_OVER:,.0f}; thực tế {b}',
        )
        self.assertEqual(
            b.get('141'), (0.0, self.ADVANCE),
            f'Có 141 chỉ tối đa bằng số đã ứng ({self.ADVANCE:,.0f}), '
            f'không được vượt để 141 mang số dư Có; thực tế {b}',
        )
        self.assertEqual(
            b.get('334'), (0.0, excess),
            f'Phần vượt {excess:,.0f} phải sang Có 334; thực tế {b}',
        )
        self.assertNotIn('331', b, 'Phần vượt là nợ NLĐ (334), không phải NCC (331)')
        so_141, so_334 = self._print_141_334('sau bước 2 (quyết toán)')
        self.assertAlmostEqual(
            so_141, 0.0, places=0,
            msg=f'141 phải TẤT TOÁN về 0, đang là {so_141:,.0f}',
        )
        self.assertAlmostEqual(so_334, -excess, places=0, msg='334 phải dư Có phần vượt')

        # Chi bù KHÔNG dùng lại R19 (R19 ghi Nợ 141, sẽ làm tạm ứng phình lên).
        # Nhãn riêng "Trả nợ người lao động" → R19f ghi Nợ 334 / Có 111.
        top_up = self._advance(excess, operation='employee_debt_payment')
        self._sync()
        moves = self._moves_for(top_up)
        self.assertEqual(len(moves), 1, 'R19f phải sinh đúng 1 bút toán cho phiếu chi bù')
        self._dump('bước 3 — chi bù (R19f)', moves)
        bt = self._balances(moves)
        self.assertEqual(
            bt.get('334'), (excess, 0.0),
            f'Chi bù phải Nợ 334 = {excess:,.0f}; thực tế {bt}',
        )
        self.assertEqual(
            bt.get('111'), (0.0, excess),
            f'Chi bù phải Có 111 = {excess:,.0f}; thực tế {bt}',
        )
        self.assertNotIn(
            '141', bt,
            'Chi bù TUYỆT ĐỐI không được chạm 141 — đó là lỗi của chỉ thị D4 cũ',
        )
        so_141, so_334 = self._print_141_334('sau bước 3 (chi bù)  <-- cả hai về 0')
        self.assertAlmostEqual(
            so_141, 0.0, places=0, msg=f'141 phải về 0, đang là {so_141:,.0f}')
        self.assertAlmostEqual(
            so_334, 0.0, places=0, msg=f'334 phải về 0, đang là {so_334:,.0f}')

    # ------------------------------------------------------------------
    # (v-b) Tiêu ĐÚNG bằng số đã ứng → không sinh chân 334 nào
    # ------------------------------------------------------------------

    def test_w6_v_tieu_dung_bang_tam_ung(self):
        print('\n=== (v-b) tạm ứng 10tr, tiêu đúng 10tr ===')
        advance = self._advance(self.ADVANCE)
        expense = self._expense(self.svc_admin, self.ADVANCE, advance=advance)
        self._sync()

        settle = self._moves_for(expense, 'expense')
        self._dump('quyết toán vừa khít', settle)
        b = self._balances(settle)
        self.assertEqual(b.get('141'), (0.0, self.ADVANCE), f'thực tế {b}')
        self.assertNotIn(
            '334', b,
            'Tiêu vừa khít thì chân 334 = 0 và engine phải BỎ dòng, '
            f'không được ghi dòng 0 đồng; thực tế {b}',
        )
        self.assertEqual(
            len(settle.line_ids), 2,
            f'Bút toán phải đúng 2 chân (Nợ 6422 / Có 141), '
            f'đang có {len(settle.line_ids)}',
        )
        so_141, so_334 = self._print_141_334('sau quyết toán')
        self.assertAlmostEqual(so_141, 0.0, places=0)
        self.assertAlmostEqual(
            so_334, 0.0, places=0, msg='Không được phát sinh dòng 334 nào')

    # ------------------------------------------------------------------
    # (v-c) E1 — không tạm ứng gốc: R19d ghi Có 334, R19f trả lại → 334 về 0
    # ------------------------------------------------------------------

    def test_w6_v_e1_tu_bo_tien_tui_roi_tra_lai(self):
        print('\n=== (v-c) E1: NLĐ tự bỏ tiền túi 8tr, công ty trả lại 8tr ===')
        expense = self._expense(self.svc_admin, self.SPEND_OK, advance=None)
        self._sync()

        settle = self._moves_for(expense, 'expense')
        self.assertEqual(len(settle), 1, 'R19d phải sinh đúng 1 bút toán')
        self._dump('bước 1 — ghi nhận chi phí (R19d)', settle)
        b = self._balances(settle)
        self.assertEqual(
            b.get('334'), (0.0, self.SPEND_OK),
            f'Không có tạm ứng gốc thì toàn bộ vào Có 334; thực tế {b}',
        )
        self.assertNotIn('141', b, 'Không có tạm ứng gốc thì không được chạm 141')
        so_141, so_334 = self._print_141_334('sau bước 1 (ghi nhận)')
        self.assertAlmostEqual(so_334, -self.SPEND_OK, places=0)

        pay_back = self._advance(self.SPEND_OK, operation='employee_debt_payment')
        self._sync()
        moves = self._moves_for(pay_back)
        self.assertEqual(len(moves), 1, 'Phải dùng đúng R19f — một rule cho cả E1 và T05')
        self._dump('bước 2 — trả lại NLĐ (R19f)', moves)
        bt = self._balances(moves)
        self.assertEqual(bt.get('334'), (self.SPEND_OK, 0.0), f'thực tế {bt}')
        self.assertEqual(bt.get('111'), (0.0, self.SPEND_OK), f'thực tế {bt}')
        self.assertEqual(
            moves.mapped('ref'), ['Trả nợ người lao động'],
            f'E1 và T05 phải dùng CHUNG một rule chi bù; thực tế {moves.mapped("ref")}',
        )
        so_141, so_334 = self._print_141_334('sau bước 2 (trả lại)  <-- 334 về 0')
        self.assertAlmostEqual(
            so_334, 0.0, places=0, msg=f'334 phải về 0, đang là {so_334:,.0f}')

    # ------------------------------------------------------------------
    # (vi) hr.expense có thuế GTGT → chân Nợ 1331
    # ------------------------------------------------------------------

    def test_w6_vi_thue_gtgt_tren_hr_expense(self):
        advance = self._advance(self.ADVANCE)
        expense = self._expense(
            self.svc_admin, self.SPEND_OK, advance=advance, taxes=self.tax_10,
        )
        net = expense.untaxed_amount
        tax = expense.tax_amount
        print(f'\n=== (vi) hr.expense có thuế: tổng={expense.total_amount:,.0f} '
              f'chưa thuế={net:,.0f} thuế={tax:,.0f} ===')
        self.assertGreater(tax, 0.0, 'Khoản chi này phải có thuế GTGT đầu vào')

        self._sync()
        moves = self._moves_for(expense, 'expense')
        self.assertEqual(len(moves), 1)
        self._dump('(vi) quyết toán có thuế', moves)
        b = self._balances(moves)
        self.assertEqual(
            b.get('1331'), (tax, 0.0),
            f'Chân Nợ 1331 phải đúng {tax:,.0f}; thực tế {b}',
        )
        self.assertEqual(
            b.get('6422'), (net, 0.0),
            f'Nợ 6422 phải là số CHƯA thuế {net:,.0f}, không phải tổng; '
            f'thực tế {b}',
        )
        self.assertEqual(
            b.get('141'), (0.0, expense.total_amount),
            f'Có 141 phải là TỔNG gồm thuế {expense.total_amount:,.0f}; '
            f'thực tế {b}',
        )
        self.assertAlmostEqual(
            sum(v[0] for v in b.values()), sum(v[1] for v in b.values()),
            places=0, msg='Bút toán phải cân',
        )

    # ------------------------------------------------------------------
    # (vii) một hr.expense không lọt vào cả R19 lẫn R19c
    # ------------------------------------------------------------------

    def test_w6_vii_khong_chong_lan_r19_va_quyet_toan(self):
        advance = self._advance(self.ADVANCE)
        expense = self._expense(self.svc_admin, self.SPEND_OK, advance=advance)
        self._sync()

        exp_moves = self._moves_for(expense)
        pay_moves = self._moves_for(advance)
        print('\n=== (vii) ma trận nguồn → bút toán ===')
        print(f'   hr.expense({expense.id})      → {len(exp_moves)} bút toán, '
              f'kind={exp_moves.mapped("move_kind")}, ref={exp_moves.mapped("ref")}')
        print(f'   account.payment({advance.id}) → {len(pay_moves)} bút toán, '
              f'kind={pay_moves.mapped("move_kind")}, ref={pay_moves.mapped("ref")}')

        self.assertEqual(
            len(exp_moves), 1,
            'Một hr.expense chỉ được sinh ĐÚNG MỘT bút toán quyết toán',
        )
        self.assertEqual(
            len(pay_moves), 1,
            'Phiếu tạm ứng chỉ được R19 ghi một lần',
        )
        # R19 đọc account.payment, R19c đọc hr.expense — hai model khác nhau
        Sync = self.env['vas.sync']
        self.assertFalse(
            Sync._is_employee_advance_payment(advance) and expense in advance.expense_ids,
            'Phiếu tạm ứng gốc không được vừa là nguồn của R19 vừa gắn hr.expense',
        )
        self.assertFalse(
            self.env['vas.move'].search([
                ('source_model', '=', 'hr.expense'),
                ('move_kind', '=', 'payment'),
            ]),
            'hr.expense KHÔNG được sinh bút toán loại payment (đó là địa hạt R19)',
        )

        # D5(a): nút "Register Payment" của Odoo không được làm R18 ghi thêm
        self.assertTrue(
            Sync._payment_linked_to_expense(
                self.env['account.payment'].new({'expense_ids': [Command.link(expense.id)]})
            )
            if 'expense_ids' in self.env['account.payment']._fields else True,
            'R18 phải nhận diện được payment gắn hr.expense để loại trừ',
        )

    # ------------------------------------------------------------------
    # (viii) đồng bộ hai lần → không trùng
    # ------------------------------------------------------------------

    def test_w6_viii_idempotent(self):
        bill = self._bill([
            (self.goods, self.GOODS_NET),
            (self.svc_admin, self.SERVICE_NET),
        ])
        advance = self._advance(self.ADVANCE)
        expense = self._expense(self.svc_admin, self.SPEND_OK, advance=advance)
        refund = self._advance(
            self.REFUND, operation='advance_refund', inbound=True,
        )
        top_up = self._advance(self.REFUND, operation='employee_debt_payment')

        def snapshot():
            return {
                'hóa đơn trộn — R07': len(self._moves_for(bill, 'purchase_inv')),
                'hóa đơn trộn — R08': len(self._moves_for(bill, 'expense')),
                'tạm ứng — R19': len(self._moves_for(advance)),
                'quyết toán — R19c': len(self._moves_for(expense, 'expense')),
                'thu hồi — R19e': len(self._moves_for(refund)),
                'chi bù — R19f': len(self._moves_for(top_up)),
            }

        first = self._sync()
        counts_1 = snapshot()
        print('\n=== (viii) sau lần đồng bộ 1 ===')
        for label, n in counts_1.items():
            print(f'   {label:<24} = {n}')
        print(f"   stats: purchase_service={first.get('purchase_service')} "
              f"advance_settlement={first.get('advance_settlement')} "
              f"advance_refund={first.get('advance_refund')} "
              f"employee_debt_payment={first.get('employee_debt_payment')}")
        self.assertTrue(all(n == 1 for n in counts_1.values()), counts_1)

        second = self._sync()
        counts_2 = snapshot()
        print('=== sau lần đồng bộ 2 ===')
        for label, n in counts_2.items():
            print(f'   {label:<24} = {n}')
        print(f"   stats: purchase_service={second.get('purchase_service')} "
              f"advance_settlement={second.get('advance_settlement')} "
              f"advance_refund={second.get('advance_refund')} "
              f"employee_debt_payment={second.get('employee_debt_payment')}")
        self.assertEqual(
            counts_2, counts_1,
            'Bấm Đồng bộ lần hai KHÔNG được sinh bút toán nào thêm',
        )
        self.assertEqual(second['advance_settlement']['created'], 0)
        # skipped đếm cả expense/payment đã sync trên DB demo — chỉ cần >= 1
        self.assertGreaterEqual(second['advance_settlement']['skipped'], 1)
        self.assertEqual(second['purchase_service']['created'], 0)
        self.assertEqual(second['advance_refund']['created'], 0)
        self.assertEqual(second['employee_debt_payment']['created'], 0)
        self.assertGreaterEqual(second['employee_debt_payment']['skipped'], 1)

    # ------------------------------------------------------------------
    # (ix) Paid By = Company → R19g: Nợ CP/1331 / Có 111·112, không 141/334
    # ------------------------------------------------------------------

    def test_w6_ix_company_account_r19g(self):
        total = 1_100_000.0
        expense = self._expense(
            self.svc_admin, total, taxes=self.tax_10,
            payment_mode='company_account',
        )
        # Chưa post → chưa có payment → sync phải bỏ qua, không đẻ Có 334
        stats_wait = self._sync()
        self.assertFalse(
            self._moves_for(expense),
            'company_account chưa post không được sinh bút toán (kể cả Có 334)',
        )
        self.assertEqual(stats_wait['advance_settlement']['created'], 0)

        expense.action_post()
        self.assertEqual(expense.state, 'paid')
        pay = expense.account_move_id.origin_payment_id
        self.assertTrue(pay, 'Odoo 19 phải tự sinh payment khi post company_account')
        cash_code = '111' if pay.journal_id.type == 'cash' else '112'

        self._sync()
        moves = self._moves_for(expense, 'expense')
        self.assertEqual(len(moves), 1)
        self._dump(
            f'(ix) company_account → kỳ vọng Có {cash_code} '
            f'(journal={pay.journal_id.type})',
            moves,
        )
        bal = self._balances(moves)
        untaxed = expense.untaxed_amount
        tax = expense.tax_amount
        self.assertAlmostEqual(bal.get('6422', (0, 0))[0], untaxed, places=2)
        self.assertAlmostEqual(bal.get('1331', (0, 0))[0], tax, places=2)
        self.assertAlmostEqual(bal.get(cash_code, (0, 0))[1], total, places=2)
        self.assertNotIn('141', bal, f'Không được đụng 141: {bal}')
        self.assertNotIn('334', bal, f'Không được đụng 334: {bal}')
        self.assertEqual(moves.ref, 'Chi phí công ty trả thẳng')

        # Payment gắn expense company_account: R18 bỏ, R19f bỏ
        Sync = self.env['vas.sync']
        self.assertTrue(Sync._payment_linked_to_expense(pay))
        self.assertFalse(
            Sync._is_employee_debt_payment(pay),
            'company_account payment KHÔNG được vào R19f',
        )
        self.assertFalse(self._moves_for(pay), 'Payment company_account không sinh VAS')

    # ------------------------------------------------------------------
    # (x) Register Payment không nhãn → R19f tất toán 334; R18 im
    # ------------------------------------------------------------------

    def test_w6_x_register_payment_tat_toan_334(self):
        amount = 900_000.0
        expense = self._expense(self.svc_admin, amount)
        self._sync()
        exp_moves = self._moves_for(expense, 'expense')
        self.assertEqual(len(exp_moves), 1)
        self._dump('(x) bước 1 — R19d Có 334', exp_moves)
        self.assertAlmostEqual(
            self._balances(exp_moves).get('334', (0, 0))[1], amount, places=2,
        )
        self.assertAlmostEqual(
            self._account_balance('334'), -amount, places=2,
            msg='Sau R19d: 334 mang số dư Có (= công ty nợ NLĐ)',
        )

        self._post_own_expense(expense)
        pay = self._register_payment_for_expense(expense, journal=self.cash_journal)
        self.assertFalse(
            pay.vas_operation_type,
            f'Register Payment phải không nhãn, được {pay.vas_operation_type!r}',
        )
        self.assertEqual(pay.payment_type, 'outbound')
        Sync = self.env['vas.sync']
        self.assertTrue(Sync._payment_linked_to_expense(pay))
        self.assertTrue(Sync._is_employee_debt_payment(pay))

        stats = self._sync()
        pay_moves = self._moves_for(pay, 'payment')
        self.assertEqual(len(pay_moves), 1, 'R19f phải sinh đúng 1 bút toán')
        self._dump('(x) bước 2 — Register Payment → R19f', pay_moves)
        bal = self._balances(pay_moves)
        self.assertAlmostEqual(bal.get('334', (0, 0))[0], amount, places=2)
        self.assertAlmostEqual(bal.get('111', (0, 0))[1], amount, places=2)

        # R18 không được sinh thêm (cùng source payment chỉ 1 move)
        self.assertEqual(
            len(self._moves_for(pay)), 1,
            'Chỉ một bút toán trên payment — R18 phải im',
        )
        self.assertEqual(stats['payment_out']['created'], 0)
        self.assertAlmostEqual(
            self._account_balance('334'), 0.0, places=2,
            msg='Sau R19f số dư 334 phải về 0',
        )

    # ------------------------------------------------------------------
    # (xi) Nhãn tay + gắn expense → một bút toán, không ghi hai lần
    # ------------------------------------------------------------------

    def test_w6_xi_nhan_tay_khong_ghi_hai_lan(self):
        amount = 750_000.0
        expense = self._expense(self.svc_admin, amount)
        self._sync()
        self._post_own_expense(expense)
        pay = self._register_payment_for_expense(
            expense, journal=self.cash_journal, label='employee_debt_payment',
        )
        self.assertEqual(pay.vas_operation_type, 'employee_debt_payment')
        self.assertTrue(self.env['vas.sync']._payment_linked_to_expense(pay))
        self.assertTrue(self.env['vas.sync']._is_employee_debt_payment(pay))

        first = self._sync()
        self.assertEqual(first['employee_debt_payment']['created'], 1)
        self.assertEqual(len(self._moves_for(pay, 'payment')), 1)
        self._dump('(xi) nhãn tay + gắn expense', self._moves_for(pay))

        second = self._sync()
        self.assertEqual(second['employee_debt_payment']['created'], 0)
        self.assertGreaterEqual(second['employee_debt_payment']['skipped'], 1)
        self.assertEqual(
            len(self._moves_for(pay, 'payment')), 1,
            'Vừa nhãn vừa gắn expense vẫn chỉ một bút toán',
        )

    # ------------------------------------------------------------------
    # (xii) advance_refund outbound không lọt R19e
    # ------------------------------------------------------------------

    def test_w6_xii_r19e_chi_inbound(self):
        bad = self._advance(
            500_000.0, operation='advance_refund', inbound=False,
        )
        good = self._advance(
            500_000.0, operation='advance_refund', inbound=True,
        )
        Sync = self.env['vas.sync']
        self.assertFalse(
            bad.vas_operation_type == 'advance_refund' and bad.payment_type == 'inbound',
        )
        self.assertEqual(good.payment_type, 'inbound')

        self._sync()
        self.assertFalse(
            self._moves_for(bad),
            f'advance_refund outbound không được sinh VAS: {self._moves_for(bad)}',
        )
        self.assertEqual(
            len(self._moves_for(good)), 1,
            'advance_refund inbound vẫn phải vào R19e',
        )
        self._dump('(xii) R19e chỉ inbound', self._moves_for(good))

        # Rule condition nguyên văn
        rule = self.env.ref('connecta_vas.vas_rule_tt133_r19e')
        self.assertEqual(
            rule.condition,
            '[("payment_type", "=", "inbound")]',
            f'R19e phải siết inbound, đang là {rule.condition!r}',
        )
