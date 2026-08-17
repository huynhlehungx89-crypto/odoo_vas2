# -*- coding: utf-8 -*-
"""W10 chặng 3 — L06 + V09 + C01 (lớp B máy tính được)."""
from datetime import date

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged, TransactionCase
from odoo.tools.float_utils import float_compare, float_is_zero


@tagged('post_install', '-at_install', 'connecta_vas', 'connecta_vas_w10')
class TestW10ClosingLayerB(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.regime = cls.env.ref('connecta_vas.vas_regime_tt133')
        if not cls.company.vas_regime_id:
            cls.company.vas_regime_id = cls.regime
        cls.company.vas_start_date = '2090-01-01'
        cls.company.fiscalyear_last_day = 31
        cls.company.fiscalyear_last_month = '12'
        cls.vnd = cls.env.ref('base.VND')
        cls.usd = cls.env.ref('base.USD')
        cls.usd.active = True
        if cls.company.currency_id != cls.vnd:
            cls.company.currency_id = cls.vnd

        fy = cls.env['vas.fiscalyear'].search([
            ('company_id', '=', cls.company.id),
            ('date_from', '<=', '2090-06-15'),
            ('date_to', '>=', '2090-06-15'),
        ], limit=1)
        if not fy:
            fy = cls.env['vas.fiscalyear'].create({
                'name': 'W10B-2090',
                'date_from': '2090-01-01',
                'date_to': '2090-12-31',
                'state': 'open',
                'company_id': cls.company.id,
            })
        cls.fy = fy
        period = cls.env['vas.period'].search([
            ('fiscalyear_id', '=', fy.id),
            ('date_start', '=', '2090-06-01'),
        ], limit=1)
        if not period:
            period = cls.env['vas.period'].create({
                'name': '06/2090-B',
                'date_start': '2090-06-01',
                'date_end': '2090-06-30',
                'fiscalyear_id': fy.id,
                'state': 'open',
            })
        cls.period = period

        cls.journal = cls.env['vas.journal'].search([
            ('company_id', '=', cls.company.id), ('code', '=', 'KC'),
        ], limit=1)
        if not cls.journal:
            cls.journal = cls.env['vas.journal'].search([
                ('company_id', '=', cls.company.id),
            ], limit=1)
        cls.Entry = cls.env['vas.closing.entry']
        cls.Rule = cls.env['vas.closing.rule']
        cls.partner = cls.env['res.partner'].create({
            'name': 'W10B FX Partner',
            'company_id': cls.company.id,
        })

    def _acc(self, code):
        return self.env.ref('connecta_vas.vas_account_tt133_%s' % code)

    def _set_usd_rate(self, day, vnd_per_usd):
        Rate = self.env['res.currency.rate']
        rate_val = 1.0 / vnd_per_usd
        existing = Rate.search([
            ('currency_id', '=', self.usd.id),
            ('name', '=', day),
            ('company_id', '=', self.company.id),
        ], limit=1)
        if existing:
            existing.rate = rate_val
        else:
            Rate.create({
                'currency_id': self.usd.id,
                'name': day,
                'company_id': self.company.id,
                'rate': rate_val,
            })
        got = self.usd._convert(100.0, self.vnd, self.company, day)
        if float_compare(got, 100.0 * vnd_per_usd, precision_digits=0) != 0:
            existing = Rate.search([
                ('currency_id', '=', self.usd.id),
                ('name', '=', day),
                ('company_id', '=', self.company.id),
            ], limit=1)
            existing.rate = vnd_per_usd

    def _post_pair(self, day, debit_acc, credit_acc, amount, name='W10B',
                   currency=None, amount_currency=None, partner=None):
        vals_debit = {
            'account_id': debit_acc.id,
            'name': name,
            'debit': amount,
            'credit': 0.0,
        }
        vals_credit = {
            'account_id': credit_acc.id,
            'name': name,
            'debit': 0.0,
            'credit': amount,
        }
        if currency and amount_currency is not None:
            # Chỉ gắn nguyên tệ lên đúng TK ngoại tệ (tránh kéo TK VND đối ứng vào V09)
            if self._is_fx_account_code(debit_acc.code):
                vals_debit.update({
                    'currency_id': currency.id,
                    'amount_currency': abs(amount_currency),
                })
            if self._is_fx_account_code(credit_acc.code):
                vals_credit.update({
                    'currency_id': currency.id,
                    'amount_currency': -abs(amount_currency),
                })
            # Nếu cả hai đều FX (vd 1122/331): gắn cả hai
            if (
                self._is_fx_account_code(debit_acc.code)
                and self._is_fx_account_code(credit_acc.code)
            ):
                vals_debit.update({
                    'currency_id': currency.id,
                    'amount_currency': abs(amount_currency),
                })
                vals_credit.update({
                    'currency_id': currency.id,
                    'amount_currency': -abs(amount_currency),
                })
        if partner:
            vals_debit['partner_id'] = partner.id
            vals_credit['partner_id'] = partner.id
        move = self.env['vas.move'].create({
            'date': day,
            'journal_id': self.journal.id,
            'regime_id': self.regime.id,
            'move_kind': 'manual',
            'company_id': self.company.id,
            'ref': name,
            'line_ids': [(0, 0, vals_debit), (0, 0, vals_credit)],
        })
        move.action_post()
        return move

    @staticmethod
    def _is_fx_account_code(code):
        code = code or ''
        return any(
            code == p or code.startswith(p)
            for p in ('1112', '1122', '131', '138', '331', '338', '341')
        )

    def _make_entry(self, **kwargs):
        vals = {
            'company_id': self.company.id,
            'date_from': '2090-06-01',
            'date_to': '2090-06-30',
            'run_kqkd': False,
            'run_year_start': False,
            'run_fx': False,
            'run_vat': False,
            'run_prepaid': False,
        }
        vals.update(kwargs)
        return self.Entry.create(vals)

    def _ending_net(self, code):
        amount, side = self.Rule.compute_closing_amount(
            self._acc(code), self.company, '2000-01-01', '2090-06-30', 'both',
        )
        if not side:
            return 0.0
        return -amount if side == 'debit' else amount

    # ----- L06 -----

    def test_01_l06_33311_gt_1331(self):
        self._post_pair('2090-06-10', self._acc('1331'), self._acc('331'), 100_000, 'VAT-IN')
        self._post_pair('2090-06-11', self._acc('131'), self._acc('33311'), 250_000, 'VAT-OUT')
        entry = self._make_entry(run_vat=True)
        entry.action_fetch_data()
        line = entry.line_ids.filtered(lambda l: l.layer == 'B_vat')
        self.assertEqual(len(line), 1)
        self.assertEqual(line.account_debit_id.code, '33311')
        self.assertEqual(line.account_credit_id.code, '1331')
        self.assertEqual(
            float_compare(line.amount, 100_000.0, precision_digits=2), 0,
            'L06 amount=%s (credit33311=%s debit1331=%s)' % (
                line.amount,
                entry._ending_side_balance(self._acc('33311'), 'credit'),
                entry._ending_side_balance(self._acc('1331'), 'debit'),
            ),
        )
        entry.action_post()
        self.assertTrue(float_is_zero(self._ending_side(self._acc('1331'), 'debit'), precision_digits=2))

    def _ending_side(self, account, side):
        return self.Entry.new({
            'company_id': self.company.id,
            'date_to': fields.Date.to_date('2090-06-30'),
        })._ending_side_balance(account, side)

    def test_01b_l06_reverse_reclose_same_amount(self):
        """L06 đọc _ending_side_balance: đảo lô rồi lấy lại → amount không gấp đôi."""
        self._post_pair('2090-06-10', self._acc('1331'), self._acc('331'), 100_000, 'VAT-IN')
        self._post_pair('2090-06-11', self._acc('131'), self._acc('33311'), 250_000, 'VAT-OUT')
        e1 = self._make_entry(run_vat=True)
        e1.action_fetch_data()
        amt1 = e1.line_ids.filtered(lambda l: l.layer == 'B_vat').amount
        e1.action_post()
        e1.action_reverse_entry()
        e2 = self._make_entry(run_vat=True)
        e2.action_fetch_data()
        amt2 = e2.line_ids.filtered(lambda l: l.layer == 'B_vat').amount
        self.assertEqual(
            float_compare(amt2, amt1, 2), 0,
            'L06 sau đảo+lấy lại: %s ≠ lần 1 %s' % (amt2, amt1),
        )

    def test_02_l06_1331_gt_33311(self):
        self._post_pair('2090-06-10', self._acc('1331'), self._acc('331'), 300_000, 'VAT-IN')
        self._post_pair('2090-06-11', self._acc('131'), self._acc('33311'), 120_000, 'VAT-OUT')
        entry = self._make_entry(run_vat=True)
        entry.action_fetch_data()
        line = entry.line_ids.filtered(lambda l: l.layer == 'B_vat')
        self.assertEqual(float_compare(line.amount, 120_000.0, 2), 0)
        entry.action_post()
        self.assertTrue(float_is_zero(
            self._ending_side(self._acc('33311'), 'credit'), 2,
        ))

    def test_03_l06_one_side_zero(self):
        self._post_pair('2090-06-11', self._acc('131'), self._acc('33311'), 50_000, 'OUT-only')
        entry = self._make_entry(run_vat=True)
        entry.action_fetch_data()
        self.assertFalse(entry.line_ids.filtered(lambda l: l.layer == 'B_vat'))

    def test_03b_l06_only_1332(self):
        """K7: chỉ 1332 — khấu trừ vào 1332."""
        self._post_pair('2090-06-10', self._acc('1332'), self._acc('331'), 80_000, 'VAT-TSCD')
        self._post_pair('2090-06-11', self._acc('131'), self._acc('33311'), 200_000, 'VAT-OUT')
        entry = self._make_entry(run_vat=True)
        entry.action_fetch_data()
        lines = entry.line_ids.filtered(lambda l: l.layer == 'B_vat')
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines.account_credit_id.code, '1332')
        self.assertEqual(float_compare(lines.amount, 80_000.0, precision_digits=2), 0)

    def test_03c_l06_both_1331_1332_prefer_1331(self):
        """K7: cả hai + 33311 không đủ — ưu tiên 1331 rồi 1332."""
        self._post_pair('2090-06-10', self._acc('1331'), self._acc('331'), 100_000, 'IN1')
        self._post_pair('2090-06-10', self._acc('1332'), self._acc('331'), 100_000, 'IN2')
        self._post_pair('2090-06-11', self._acc('131'), self._acc('33311'), 150_000, 'OUT')
        entry = self._make_entry(run_vat=True)
        entry.action_fetch_data()
        lines = entry.line_ids.filtered(lambda l: l.layer == 'B_vat').sorted('sequence')
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0].account_credit_id.code, '1331')
        self.assertEqual(float_compare(lines[0].amount, 100_000.0, precision_digits=2), 0)
        self.assertEqual(lines[1].account_credit_id.code, '1332')
        self.assertEqual(float_compare(lines[1].amount, 50_000.0, precision_digits=2), 0)

    # ----- V09 -----

    def test_04_v09_gain_to_515(self):
        self._set_usd_rate('2090-06-01', 25_000.0)
        self._set_usd_rate('2090-06-30', 26_000.0)
        # 100 USD @25k trên 1122
        self._post_pair(
            '2090-06-05', self._acc('1122'), self._acc('511'), 2_500_000,
            'USD-cash', currency=self.usd, amount_currency=100.0,
        )
        entry = self._make_entry(run_fx=True)
        entry.action_fetch_data()
        fx = entry.line_ids.filtered(lambda l: l.layer == 'B_fx')
        close413 = entry.line_ids.filtered(
            lambda l: l.layer == 'A_close'
            and '413' in (l.account_debit_id.code, l.account_credit_id.code)
        )
        self.assertTrue(fx)
        self.assertTrue(self._has(entry, '1122', '413'))
        self.assertTrue(self._has(entry, '413', '515'))
        entry.action_post()
        fx_moves = entry.move_ids.filtered(
            lambda m: m.move_kind == 'forex_reval' and not m.is_reversal
        )
        cl_moves = entry.move_ids.filtered(
            lambda m: m.move_kind == 'closing' and not m.is_reversal
        )
        self.assertTrue(fx_moves)
        self.assertTrue(cl_moves)
        # 413 về 0
        amt, side = self.Rule.compute_closing_amount(
            self._acc('413'), self.company, '2000-01-01', '2090-06-30', 'both',
        )
        self.assertFalse(side)

    def _has(self, entry, debit, credit):
        return any(
            l.account_debit_id.code == debit and l.account_credit_id.code == credit
            for l in entry.line_ids if not l.excluded
        )

    def test_05_v09_loss_to_635(self):
        self._set_usd_rate('2090-06-01', 25_000.0)
        self._set_usd_rate('2090-06-30', 24_000.0)
        self._post_pair(
            '2090-06-05', self._acc('1122'), self._acc('511'), 2_500_000,
            'USD-cash', currency=self.usd, amount_currency=100.0,
        )
        entry = self._make_entry(run_fx=True)
        entry.action_fetch_data()
        self.assertTrue(self._has(entry, '413', '1122'))
        self.assertTrue(self._has(entry, '635', '413'))
        entry.action_post()
        amt, side = self.Rule.compute_closing_amount(
            self._acc('413'), self.company, '2000-01-01', '2090-06-30', 'both',
        )
        self.assertFalse(side)

    def test_06_v09_net_close_not_per_line(self):
        """Vừa lãi vừa lỗ nhiều dòng → 413 xả theo số thuần một dòng."""
        self._set_usd_rate('2090-06-01', 25_000.0)
        self._set_usd_rate('2090-06-30', 26_000.0)
        # Lãi 100 USD → +100k
        self._post_pair(
            '2090-06-05', self._acc('1122'), self._acc('511'), 2_500_000,
            'USD-A', currency=self.usd, amount_currency=100.0,
        )
        # Thêm EUR giả bằng USD khác partner — dùng cùng USD số nhỏ lỗ bằng cách
        # ghi thêm khoản phải trả: 50 USD @25k, rate 26k → lỗ 50k trên nợ
        self._post_pair(
            '2090-06-06', self._acc('156'), self._acc('331'), 1_250_000,
            'USD-AP', currency=self.usd, amount_currency=50.0,
            partner=self.partner,
        )
        entry = self._make_entry(run_fx=True)
        entry.action_fetch_data()
        close413 = entry.line_ids.filtered(
            lambda l: l.layer == 'A_close'
            and set((l.account_debit_id.code, l.account_credit_id.code)) & {'413', '515', '635'}
        )
        # Net lãi = 100k − 50k = 50k → một dòng 413→515
        self.assertEqual(len(close413), 1)
        self.assertEqual(close413.account_debit_id.code, '413')
        self.assertEqual(close413.account_credit_id.code, '515')
        self.assertEqual(float_compare(close413.amount, 50_000.0, 2), 0)

    def test_07_v09_skips_advance_non_monetary(self):
        self._set_usd_rate('2090-06-01', 25_000.0)
        self._set_usd_rate('2090-06-30', 26_000.0)
        # Ứng trước NCC: dư Nợ 331 ngoại tệ — đối ứng tiền VND (không kéo 1122 NT)
        self._post_pair(
            '2090-06-05', self._acc('331'), self._acc('111'), 2_500_000,
            'ADV', currency=self.usd, amount_currency=100.0,
            partner=self.partner,
        )
        entry = self._make_entry(run_fx=True)
        entry.action_fetch_data()
        self.assertFalse(entry.line_ids.filtered(lambda l: l.layer == 'B_fx'))

    def test_08_v09_missing_rate_errors(self):
        # Xóa rate USD quanh ngày
        self.env['res.currency.rate'].search([
            ('currency_id', '=', self.usd.id),
            ('company_id', '=', self.company.id),
        ]).unlink()
        self._post_pair(
            '2090-06-05', self._acc('1122'), self._acc('511'), 2_500_000,
            'USD', currency=self.usd, amount_currency=100.0,
        )
        entry = self._make_entry(run_fx=True)
        with self.assertRaises(UserError) as err:
            entry.action_fetch_data()
        self.assertIn('tỷ giá', err.exception.args[0].lower())

    def test_09_v09_reverse_both_moves(self):
        self._set_usd_rate('2090-06-01', 25_000.0)
        self._set_usd_rate('2090-06-30', 26_000.0)
        self._post_pair(
            '2090-06-05', self._acc('1122'), self._acc('511'), 2_500_000,
            'USD', currency=self.usd, amount_currency=100.0,
        )
        Move = self.env['vas.move']
        Line = self.env['vas.move.line']
        before_m = Move.search_count([('company_id', '=', self.company.id)])
        before_l = Line.search_count([('company_id', '=', self.company.id)])
        entry = self._make_entry(run_fx=True)
        entry.action_fetch_data()
        entry.action_post()
        batch = entry._batch_active_moves()
        batch_ids = batch.ids
        n_batch = len(batch)
        n_lines = sum(len(m.line_ids) for m in batch)
        mid_m = Move.search_count([('company_id', '=', self.company.id)])
        mid_l = Line.search_count([('company_id', '=', self.company.id)])
        self.assertEqual(mid_m, before_m + n_batch)
        self.assertTrue(batch.filtered(lambda m: m.move_kind == 'forex_reval'))
        self.assertTrue(batch.filtered(lambda m: m.move_kind == 'closing'))
        entry.action_reverse_entry()
        self.assertEqual(entry.state, 'cancelled')
        for mid in batch_ids:
            self.assertEqual(Move.browse(mid).state, 'reversed')
        after_m = Move.search_count([('company_id', '=', self.company.id)])
        after_l = Line.search_count([('company_id', '=', self.company.id)])
        # +N move đảo (đủ lô); DELTA orphan = 0 (không nháp dở)
        self.assertEqual(after_m, mid_m + n_batch)
        self.assertEqual(after_l, mid_l + n_lines)
        orphans = Move.search([
            ('company_id', '=', self.company.id),
            ('state', '=', 'draft'),
            ('is_reversal', '=', True),
        ])
        self.assertFalse(orphans)
        # Số dư 413 trở về 0 (trước ĐGL cũng 0)
        amt, side = self.Rule.compute_closing_amount(
            self._acc('413'), self.company, '2000-01-01', '2090-06-30', 'both',
        )
        self.assertFalse(side)

    # ----- C01 -----

    def test_10_c01_from_prepaid_schedule(self):
        asset = self.env['vas.asset'].create({
            'code': 'W10B-PP',
            'name': 'PP C01',
            'company_id': self.company.id,
            'regime_id': self.regime.id,
            'asset_type': 'prepaid',
            'asset_kind': 'prepaid_service',
            'original_value': 1_200_000,
            'date_start': date(2090, 6, 1),
            'method': 'straight_line',
            'duration_months': 2,
            'prorata': False,
            'account_gross_id': self._acc('242').id,
            'account_accum_id': self._acc('242').id,
            'account_expense_id': self._acc('6422').id,
            'journal_id': self.journal.id,
            'source_mode': 'manual',
        })
        asset.action_confirm()
        planned = asset.line_ids.filtered(
            lambda l: l.state == 'planned' and l.period_id == self.period
        )
        self.assertTrue(planned)
        expected = planned[0].amount
        entry = self._make_entry(run_prepaid=True)
        entry.action_fetch_data()
        line = entry.line_ids.filtered('asset_line_id')
        self.assertTrue(line)
        self.assertEqual(float_compare(line[0].amount, expected, 2), 0)
        self.assertEqual(line[0].account_debit_id.code, '6422')
        self.assertEqual(line[0].account_credit_id.code, '242')

    def test_11_c01_no_schedule_reminds(self):
        entry = self._make_entry(run_prepaid=True)
        with self.assertRaises(UserError) as err:
            entry.action_fetch_data()
        self.assertIn('lịch prepaid', err.exception.args[0].lower())
        self.assertIn('không tự tính', err.exception.args[0].lower())
