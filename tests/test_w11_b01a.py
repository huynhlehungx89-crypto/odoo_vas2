# -*- coding: utf-8 -*-
"""W11 — khung chỉ tiêu BCTC + B01a-DNN (công ty thử riêng, không lẫn demo)."""
from odoo.exceptions import UserError
from odoo.tests import tagged, TransactionCase
from odoo.tools.float_utils import float_compare, float_is_zero


@tagged('post_install', '-at_install', 'connecta_vas', 'connecta_vas_w11')
class TestW11B01a(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.regime = cls.env.ref('connecta_vas.vas_regime_tt133')
        vnd = cls.env.ref('base.VND')
        cls.company = cls.env['res.company'].create({
            'name': 'W11-B01a Thử',
            'currency_id': vnd.id,
            'vas_regime_id': cls.regime.id,
            'vas_start_date': '2091-01-01',
        })
        cls.env.user.company_ids = [(4, cls.company.id)]
        cls.env.user.company_id = cls.company

        cls.fy = cls.env['vas.fiscalyear'].create({
            'name': 'W11-2091',
            'date_from': '2091-01-01',
            'date_to': '2091-12-31',
            'state': 'open',
            'company_id': cls.company.id,
        })
        cls.p01 = cls.env['vas.period'].create({
            'name': '01/2091',
            'date_start': '2091-01-01',
            'date_end': '2091-01-31',
            'fiscalyear_id': cls.fy.id,
            'state': 'open',
        })
        cls.period = cls.env['vas.period'].create({
            'name': '03/2091',
            'date_start': '2091-03-01',
            'date_end': '2091-03-31',
            'fiscalyear_id': cls.fy.id,
            'state': 'open',
        })
        seq = cls.env['ir.sequence'].create({
            'name': 'VAS W11 B01a',
            'code': 'vas.move.w11.b01a',
            'prefix': 'W11B/',
            'padding': 4,
            'company_id': cls.company.id,
        })
        cls.journal = cls.env['vas.journal'].create({
            'code': 'W11B',
            'name': 'W11 B01a',
            'type': 'general',
            'regime_id': cls.regime.id,
            'sequence_id': seq.id,
            'company_id': cls.company.id,
        })

    def _acc(self, code):
        return self.env.ref('connecta_vas.vas_account_tt133_%s' % code)

    def _post_move(self, date, lines, ref='W11-B01a'):
        move = self.env['vas.move'].create({
            'date': date,
            'journal_id': self.journal.id,
            'regime_id': self.regime.id,
            'company_id': self.company.id,
            'ref': ref,
            'move_kind': 'manual',
            'line_ids': [(0, 0, {
                'account_id': acc.id,
                'name': name,
                'debit': deb,
                'credit': cre,
                'partner_id': partner.id if partner else False,
            }) for acc, name, deb, cre, partner in lines],
        })
        move.action_post()
        return move

    def _options(self, period_from=None, period_to=None):
        period_from = period_from or self.period
        period_to = period_to or self.period
        return {
            'company_id': self.company.id,
            'period_from_id': period_from.id,
            'period_to_id': period_to.id,
            'hide_reversed': True,
        }

    def _amounts_by_code(self, data):
        out = {}
        # values: code, name, note_b09, opening, closing
        for line in data['lines']:
            code = line['values'][0]
            out[code] = {
                'opening': line['values'][3],
                'closing': line['values'][4],
            }
        return out

    def test_01_seed_count_and_structure(self):
        lines = self.env['vas.report.line'].search([
            ('form_code', '=', 'B01a-DNN'),
            ('regime_id', '=', self.regime.id),
        ])
        self.assertEqual(len(lines), 47)
        line_200 = self.env.ref('connecta_vas.vas_report_line_b01a_200')
        self.assertEqual(line_200.amount_source, 'total')
        self.assertEqual(
            set(line_200.child_line_ids.mapped('code')),
            {'110', '120', '130', '140', '150', '160', '170', '180'},
        )
        line_110 = self.env.ref('connecta_vas.vas_report_line_b01a_110')
        self.assertEqual(line_110.basis_kind, 'chot_connecta')
        self.assertEqual(line_110.warn_kind, 'balance_on_codes')
        self.assertIn('111', line_110.account_codes)
        self.assertNotIn('1281', (line_110.account_codes or ''))
        line_411 = self.env.ref('connecta_vas.vas_report_line_b01a_411')
        self.assertIn('411', line_411.account_codes)
        self.assertIn('4111', line_411.account_codes)

    def test_02_seed_protected_like_closing_rule(self):
        line = self.env.ref('connecta_vas.vas_report_line_b01a_110')
        with self.assertRaises(UserError):
            line.write({'account_codes': '999'})
        with self.assertRaises(UserError):
            line.write({'is_system': False})
        with self.assertRaises(UserError):
            line.unlink()

    def test_03_balance_sheet_equals_and_totals(self):
        self._post_move('2091-03-10', [
            (self._acc('111'), 'TM', 5_000_000, 0, False),
            (self._acc('4111'), 'Von', 0, 5_000_000, False),
        ])
        data = self.env['vas.b01a.wizard'].get_report_data(self._options())
        am = self._amounts_by_code(data)
        self.assertEqual(
            float_compare(am['200']['closing'], am['500']['closing'], 2), 0,
            '200=%s 500=%s' % (am['200']['closing'], am['500']['closing']),
        )
        self.assertFalse(data['checks'].get('imbalance_200_500'))
        self.assertEqual(
            float_compare(
                am['120']['closing'],
                (am['121']['closing'] or 0) + (am['122']['closing'] or 0)
                + (am['123']['closing'] or 0) + (am['124']['closing'] or 0),
                2,
            ),
            0,
        )
        self.assertEqual(float_compare(am['110']['closing'], 5_000_000, 2), 0)
        self.assertEqual(float_compare(am['411']['closing'], 5_000_000, 2), 0)

    def test_04_missing_account_warns_not_silent_zero(self):
        probe = self.env['vas.report.line'].create({
            'sequence': 9999,
            'code': '999',
            'name': 'Probe missing',
            'form_code': 'B01a-DNN',
            'regime_id': self.regime.id,
            'line_role': 'detail',
            'amount_source': 'balance',
            'balance_side': 'debit',
            'account_codes': 'ZZZ999',
            'basis_kind': 'chot_connecta',
            'is_system': False,
            'active': True,
        })
        self.addCleanup(probe.unlink)
        data = self.env['vas.b01a.wizard'].get_report_data(self._options())
        am = self._amounts_by_code(data)
        self.assertEqual(am['999']['closing'], 'N/A')
        self.assertIn('999', data['meta']['missing_accounts'])
        self.assertIn('ZZZ999', data['meta']['missing_accounts']['999'])
        self.assertTrue(data['meta']['warning'])
        self.assertIn('THIẾU TÀI KHOẢN', data['meta']['warning'])

    def test_05_imbalance_still_renders_with_bold_warn(self):
        self._post_move('2091-03-11', [
            (self._acc('111'), 'TM', 2_000_000, 0, False),
            (self._acc('511'), 'DT', 0, 2_000_000, False),
        ])
        data = self.env['vas.b01a.wizard'].get_report_data(self._options())
        am = self._amounts_by_code(data)
        self.assertIsNotNone(am['200']['closing'])
        self.assertIsNotNone(am['500']['closing'])
        self.assertNotEqual(
            float_compare(am['200']['closing'], am['500']['closing'], 2), 0,
            '200=%s 500=%s' % (am['200']['closing'], am['500']['closing']),
        )
        self.assertEqual(data['meta']['warning_level'], 'danger')
        self.assertIn('CẢNH BÁO ĐẬM', data['meta']['warning'])
        self.assertTrue(len(data['lines']) >= 47)

    def test_06_match_f01_cash_line(self):
        self._post_move('2091-03-12', [
            (self._acc('111'), 'TM', 1_250_000, 0, False),
            (self._acc('4111'), 'Von', 0, 1_250_000, False),
        ])
        opts = self._options()
        b01 = self.env['vas.b01a.wizard'].get_report_data(opts)
        f01 = self.env['vas.trial.balance.wizard'].get_report_data(opts)
        am = self._amounts_by_code(b01)
        f01_by_code = {}
        for line in f01['lines']:
            code = line['values'][0]
            if not code or line.get('is_total'):
                continue
            f01_by_code[code] = (line['values'][6] or 0.0, line['values'][7] or 0.0)
        cash_codes = ['111', '1111', '1112', '112', '1121', '1122']
        f01_cash = sum(f01_by_code.get(c, (0, 0))[0] for c in cash_codes)
        self.assertEqual(
            float_compare(am['110']['closing'], f01_cash, 2), 0,
            'B01a 110=%s F01 cash debit=%s' % (am['110']['closing'], f01_cash),
        )

    def test_07_classification_warn_1281(self):
        self._post_move('2091-03-13', [
            (self._acc('1281'), 'TGCKH', 3_000_000, 0, False),
            (self._acc('4111'), 'Von', 0, 3_000_000, False),
        ])
        data = self.env['vas.b01a.wizard'].get_report_data(self._options())
        am = self._amounts_by_code(data)
        self.assertTrue(float_is_zero(am['110']['closing'] or 0.0, 2))
        self.assertIn('1281', data['meta']['warning'] or '')

    def test_08_opening_balance_plus_ps_equals_closing(self):
        """Số dư trước date_from → cột cuối = đầu kỳ + PS trong khoảng."""
        # Đầu kỳ (trước 03/2091): Nợ 111 / Có 4111 = 4tr
        self._post_move('2091-01-15', [
            (self._acc('111'), 'TM đầu', 4_000_000, 0, False),
            (self._acc('4111'), 'Von đầu', 0, 4_000_000, False),
        ], ref='W11-OPEN')
        # PS trong 03: +1tr
        self._post_move('2091-03-15', [
            (self._acc('111'), 'TM PS', 1_000_000, 0, False),
            (self._acc('4111'), 'Von PS', 0, 1_000_000, False),
        ], ref='W11-PS')
        data = self.env['vas.b01a.wizard'].get_report_data(self._options())
        am = self._amounts_by_code(data)
        self.assertEqual(float_compare(am['110']['opening'], 4_000_000, 2), 0)
        self.assertEqual(float_compare(am['110']['closing'], 5_000_000, 2), 0)
        self.assertEqual(
            float_compare(
                am['110']['closing'],
                (am['110']['opening'] or 0) + 1_000_000,
                2,
            ),
            0,
        )

    def test_09_opposite_side_balance_warns(self):
        """141 lấy SD Nợ; 156 dư Có → cảnh báo, số 141 vẫn 0."""
        # Hàng hóa xuất âm kiểu dư Có trên 156 (đối ứng 4111 để cân)
        self._post_move('2091-03-16', [
            (self._acc('4111'), 'Von', 30_000_000, 0, False),
            (self._acc('156'), 'HH dư Có', 0, 30_000_000, False),
        ])
        data = self.env['vas.b01a.wizard'].get_report_data(self._options())
        am = self._amounts_by_code(data)
        self.assertTrue(float_is_zero(am['141']['closing'] or 0.0, 2))
        warn = data['meta']['warning'] or ''
        self.assertIn('DƯ NGƯỢC CHIỀU', warn)
        self.assertIn('141', warn)
        self.assertIn('156', warn)
        self.assertIn('30,000,000', warn.replace('.', ',').replace(' ', '') or warn)
        # chấp nhận cả định dạng 30,000,000 hoặc 30000000
        self.assertTrue(
            '30,000,000' in warn or '30000000' in warn.replace(',', ''),
            warn,
        )

    def test_10_total_na_when_child_na(self):
        probe = self.env['vas.report.line'].create({
            'sequence': 155,
            'code': '141x',
            'name': 'Probe HTK missing',
            'form_code': 'B01a-DNN',
            'regime_id': self.regime.id,
            'line_role': 'detail',
            'amount_source': 'balance',
            'balance_side': 'debit',
            'account_codes': 'NO_SUCH_ACC',
            'basis_kind': 'chot_connecta',
            'is_system': False,
            'active': True,
        })
        self.addCleanup(probe.unlink)
        line_140 = self.env.ref('connecta_vas.vas_report_line_b01a_140')
        # Tạm gắn probe vào 140 (seed bảo vệ — dùng SQL)
        self.env.cr.execute(
            'INSERT INTO vas_report_line_child_rel (parent_id, child_id) VALUES (%s, %s)',
            [line_140.id, probe.id],
        )
        self.addCleanup(
            lambda: self.env.cr.execute(
                'DELETE FROM vas_report_line_child_rel WHERE parent_id=%s AND child_id=%s',
                [line_140.id, probe.id],
            )
        )
        data = self.env['vas.b01a.wizard'].get_report_data(self._options())
        am = self._amounts_by_code(data)
        self.assertEqual(am['141x']['closing'], 'N/A')
        self.assertEqual(am['140']['closing'], 'N/A')
        # 200 cũng N/A vì 140 N/A
        self.assertEqual(am['200']['closing'], 'N/A')
        warn = data['meta']['warning'] or ''
        self.assertIn('TỔNG THIẾU CON', warn)
        self.assertIn('140', warn)
        self.assertIn('141x', data['meta']['total_na_children'].get('140', []))

    def test_11_parent_and_child_no_double_count(self):
        """Khai 411+4111: ghi lên cha hoặc lá — không cộng trùng."""
        # Chỉ ghi lên cha 411
        self._post_move('2091-03-17', [
            (self._acc('111'), 'TM', 2_000_000, 0, False),
            (self._acc('411'), 'Von cha', 0, 2_000_000, False),
        ], ref='W11-411P')
        data = self.env['vas.b01a.wizard'].get_report_data(self._options())
        am = self._amounts_by_code(data)
        self.assertEqual(float_compare(am['411']['closing'], 2_000_000, 2), 0)

        # Thêm ghi lên lá 4111 — tổng phải = 2tr + 3tr = 5tr (không nhân đôi)
        self._post_move('2091-03-18', [
            (self._acc('111'), 'TM2', 3_000_000, 0, False),
            (self._acc('4111'), 'Von lá', 0, 3_000_000, False),
        ], ref='W11-411C')
        data2 = self.env['vas.b01a.wizard'].get_report_data(self._options())
        am2 = self._amounts_by_code(data2)
        self.assertEqual(
            float_compare(am2['411']['closing'], 5_000_000, 2), 0,
            am2['411']['closing'],
        )

    def test_12_b01a_vs_f01_whole_sheet_leaves_only(self):
        """Đối chiếu toàn bảng: B01a = Σ F01 theo đúng mã lá (không cộng dòng cha roll-up).

        F01 ``build_account_hierarchy_lines`` có dòng cha đã cộng dồn con; so sánh
        phải chỉ lấy dòng lá (is_leaf) hoặc loại dòng có con trong cùng tập mã.
        """
        self._post_move('2091-03-19', [
            (self._acc('111'), 'TM', 7_000_000, 0, False),
            (self._acc('1122'), 'NH NT', 3_000_000, 0, False),
            (self._acc('1331'), 'GTGT', 1_000_000, 0, False),
            (self._acc('4111'), 'Von', 0, 11_000_000, False),
        ])
        opts = self._options()
        b01 = self.env['vas.b01a.wizard'].get_report_data(opts)
        f01 = self.env['vas.trial.balance.wizard'].get_report_data(opts)
        am = self._amounts_by_code(b01)

        # Map F01: chỉ dòng lá (is_leaf True) — bỏ cha roll-up
        f01_leaf = {}
        for line in f01['lines']:
            code = line['values'][0]
            if not code or line.get('is_total'):
                continue
            if line.get('is_leaf') is False:
                continue
            f01_leaf[code] = {
                'cd': line['values'][6] or 0.0,
                'cc': line['values'][7] or 0.0,
            }

        def leaf_sum(codes, side):
            total = 0.0
            for c in codes:
                row = f01_leaf.get(c)
                if not row:
                    continue
                total += row['cd'] if side == 'debit' else row['cc']
            return total

        line_110 = self.env.ref('connecta_vas.vas_report_line_b01a_110')
        codes_110 = [c.strip() for c in line_110.account_codes.split(',') if c.strip()]
        self.assertEqual(
            float_compare(am['110']['closing'], leaf_sum(codes_110, 'debit'), 2), 0,
            '110 B01a=%s F01_leaf=%s (không cộng cha roll-up)' % (
                am['110']['closing'], leaf_sum(codes_110, 'debit'),
            ),
        )
        line_181 = self.env.ref('connecta_vas.vas_report_line_b01a_181')
        codes_181 = [c.strip() for c in line_181.account_codes.split(',') if c.strip()]
        self.assertEqual(
            float_compare(am['181']['closing'], leaf_sum(codes_181, 'debit'), 2), 0,
        )
        line_411 = self.env.ref('connecta_vas.vas_report_line_b01a_411')
        codes_411 = [c.strip() for c in line_411.account_codes.split(',') if c.strip()]
        self.assertEqual(
            float_compare(am['411']['closing'], leaf_sum(codes_411, 'credit'), 2), 0,
        )
        # Chứng minh cộng cả cha F01 sẽ LỆCH (112 roll-up nếu có)
        f01_all = {}
        for line in f01['lines']:
            code = line['values'][0]
            if not code or line.get('is_total'):
                continue
            f01_all[code] = line['values'][6] or 0.0
        naive = sum(f01_all.get(c, 0.0) for c in codes_110)
        # Nếu có roll-up cha, naive >= leaf; khi 1122 có số và 112 là cha roll-up → lệch
        if float_compare(naive, leaf_sum(codes_110, 'debit'), 2) != 0:
            self.assertNotEqual(
                float_compare(am['110']['closing'], naive, 2), 0,
                'Naive F01 (gồm cha) phải lệch B01a khi có roll-up',
            )

    def test_13_aggregate_by_partner_flag_on_debt_lines(self):
        for code in ('131', '132', '134', '182', '311', '312', '313', '314', '315'):
            line = self.env.ref('connecta_vas.vas_report_line_b01a_%s' % code)
            self.assertTrue(
                line.aggregate_by_partner,
                'Chỉ tiêu %s phải khai aggregate_by_partner' % code,
            )
        line_110 = self.env.ref('connecta_vas.vas_report_line_b01a_110')
        self.assertFalse(line_110.aggregate_by_partner)


@tagged('post_install', '-at_install', 'connecta_vas', 'connecta_vas_w11')
class TestW11B01aCompleteBooks(TransactionCase):
    """Nghiệm thu trên bộ sổ W11-Thử BCTC (đầy đủ + đã KC)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['res.company']._vas_w11_ensure_bctc_demo()
        cls.company = cls.env['res.company'].search([
            ('name', '=', 'W11-Thử BCTC'),
        ], limit=1)
        assert cls.company, 'W11-Thử BCTC seed failed'
        cls.regime = cls.company.vas_regime_id
        cls.p01 = cls.env['vas.period'].search([
            ('fiscalyear_id.company_id', '=', cls.company.id),
            ('date_start', '=', '2026-01-01'),
        ], limit=1)
        cls.p12 = cls.env['vas.period'].search([
            ('fiscalyear_id.company_id', '=', cls.company.id),
            ('date_start', '=', '2026-12-01'),
        ], limit=1)
        cls.env.user.company_ids = [(4, cls.company.id)]
        cls.env.user.company_id = cls.company
        cls.journal = cls.env['vas.journal'].search([
            ('company_id', '=', cls.company.id), ('code', '=', 'TH'),
        ], limit=1)

    def _options(self):
        return {
            'company_id': self.company.id,
            'period_from_id': self.p01.id,
            'period_to_id': self.p12.id,
            'hide_reversed': True,
        }

    def _amounts_by_code(self, data):
        out = {}
        # values: code, name, note_b09, opening, closing
        for line in data['lines']:
            code = line['values'][0]
            out[code] = {
                'opening': line['values'][3],
                'closing': line['values'][4],
            }
        return out

    def _acc(self, code):
        return self.env.ref('connecta_vas.vas_account_tt133_%s' % code)

    def test_01_balanced_no_imbalance_no_opposite(self):
        data = self.env['vas.b01a.wizard'].get_report_data(self._options())
        am = self._amounts_by_code(data)
        self.assertEqual(
            float_compare(am['200']['closing'], am['500']['closing'], 2), 0,
            '200=%s 500=%s' % (am['200']['closing'], am['500']['closing']),
        )
        self.assertFalse(data['checks'].get('imbalance_200_500'))
        warn = data['meta']['warning'] or ''
        self.assertNotIn('CẢNH BÁO ĐẬM', warn)
        self.assertNotIn('DƯ NGƯỢC CHIỀU', warn)
        self.assertFalse(data['checks'].get('opposite_side_msgs'))

    def test_02_customer_and_vendor_both_sides(self):
        data = self.env['vas.b01a.wizard'].get_report_data(self._options())
        am = self._amounts_by_code(data)
        # KH A nợ 38tr → 131; KH B trả trước 15tr → 312 (không bù trừ)
        self.assertEqual(float_compare(am['131']['closing'], 38_000_000, 2), 0, am['131'])
        self.assertEqual(float_compare(am['312']['closing'], 15_000_000, 2), 0, am['312'])
        # NCC B trả trước 10tr → 132; NCC A còn nợ 35tr → 311
        self.assertEqual(float_compare(am['132']['closing'], 10_000_000, 2), 0, am['132'])
        self.assertEqual(float_compare(am['311']['closing'], 35_000_000, 2), 0, am['311'])

    def test_03_class_5_to_9_zero_after_closing(self):
        opts = self._options()
        f01 = self.env['vas.trial.balance.wizard'].get_report_data(opts)
        for line in f01['lines']:
            code = line['values'][0]
            if not code or line.get('is_total') or line.get('is_leaf') is False:
                continue
            if code[0] not in '56789':
                continue
            cd = line['values'][6] or 0.0
            cc = line['values'][7] or 0.0
            self.assertTrue(
                float_is_zero(cd, 2) and float_is_zero(cc, 2),
                'TK %s còn SD sau KC: N=%s C=%s' % (code, cd, cc),
            )

    def test_04_orphan_partner_warns(self):
        self.env['vas.move'].create({
            'date': '2026-08-01',
            'journal_id': self.journal.id,
            'regime_id': self.regime.id,
            'company_id': self.company.id,
            'ref': 'W11-ORPHAN',
            'move_kind': 'manual',
            'line_ids': [
                (0, 0, {
                    'account_id': self._acc('131').id,
                    'name': 'orphan AR',
                    'debit': 2_000_000,
                    'credit': 0,
                    'partner_id': False,
                }),
                (0, 0, {
                    'account_id': self._acc('511').id,
                    'name': 'orphan AR',
                    'debit': 0,
                    'credit': 2_000_000,
                    'partner_id': False,
                }),
            ],
        }).action_post()
        # Re-close would be heavy; orphan on 131 after year P&L already closed —
        # 511 gets balance again. Only assert orphan warn on 131.
        data = self.env['vas.b01a.wizard'].get_report_data(self._options())
        warn = data['meta']['warning'] or ''
        self.assertIn('CÔNG NỢ KHÔNG ĐỐI TÁC', warn)
        self.assertIn('131', warn)
        self.assertTrue(
            '2,000,000' in warn or '2000000' in warn.replace(',', ''),
            warn,
        )
        orphans = data['checks'].get('orphan_partner_msgs') or []
        self.assertTrue(orphans)

    def test_05_shared_parent_balance_warns(self):
        self.env['vas.move'].create({
            'date': '2026-08-02',
            'journal_id': self.journal.id,
            'regime_id': self.regime.id,
            'company_id': self.company.id,
            'ref': 'W11-SHARED-PARENT',
            'move_kind': 'manual',
            'line_ids': [
                (0, 0, {
                    'account_id': self._acc('229').id,
                    'name': 'parent 229',
                    'debit': 0,
                    'credit': 1_500_000,
                }),
                (0, 0, {
                    'account_id': self._acc('4111').id,
                    'name': 'parent 229',
                    'debit': 1_500_000,
                    'credit': 0,
                }),
            ],
        }).action_post()
        data = self.env['vas.b01a.wizard'].get_report_data(self._options())
        warn = data['meta']['warning'] or ''
        self.assertIn('229', warn)
        self.assertIn('phân loại tay', warn)
        self.assertTrue(
            '1,500,000' in warn or '1500000' in warn.replace(',', ''),
            warn,
        )

    def test_06_b01a_vs_f01_leaves_whole_sheet(self):
        opts = self._options()
        b01 = self.env['vas.b01a.wizard'].get_report_data(opts)
        f01 = self.env['vas.trial.balance.wizard'].get_report_data(opts)
        am = self._amounts_by_code(b01)
        f01_leaf = {}
        for line in f01['lines']:
            code = line['values'][0]
            if not code or line.get('is_total'):
                continue
            if line.get('is_leaf') is False:
                continue
            f01_leaf[code] = {
                'cd': line['values'][6] or 0.0,
                'cc': line['values'][7] or 0.0,
            }

        def leaf_side_sum(codes, side):
            total = 0.0
            for c in codes:
                row = f01_leaf.get(c)
                if not row:
                    continue
                total += row['cd'] if side == 'debit' else row['cc']
            return total

        # Chỉ tiêu không cộng theo đối tác: khớp F01 lá theo bên
        for xmlid_code, side in (
            ('110', 'debit'),
            ('141', 'debit'),
            ('151', 'debit'),
            ('181', 'debit'),
            ('411', 'credit'),
        ):
            line = self.env.ref('connecta_vas.vas_report_line_b01a_%s' % xmlid_code)
            codes = [c.strip() for c in (line.account_codes or '').split(',') if c.strip()]
            expected = leaf_side_sum(codes, side)
            if line.sign_negative:
                expected = -expected
            self.assertEqual(
                float_compare(am[xmlid_code]['closing'] or 0.0, expected, 2), 0,
                '%s B01a=%s F01=%s' % (xmlid_code, am[xmlid_code]['closing'], expected),
            )

        # Công nợ theo đối tác: 131 − 312 = net F01 TK 131 (không bù trên từng chỉ tiêu)
        row131 = f01_leaf.get('131', {'cd': 0, 'cc': 0})
        f01_net = (row131['cd'] or 0.0) - (row131['cc'] or 0.0)
        b01_net = (am['131']['closing'] or 0.0) - (am['312']['closing'] or 0.0)
        self.assertEqual(
            float_compare(b01_net, f01_net, 2), 0,
            '131−312=%s F01 net 131=%s' % (b01_net, f01_net),
        )
        row331 = f01_leaf.get('331', {'cd': 0, 'cc': 0})
        f01_331 = (row331['cd'] or 0.0) - (row331['cc'] or 0.0)
        b01_331 = (am['132']['closing'] or 0.0) - (am['311']['closing'] or 0.0)
        self.assertEqual(
            float_compare(b01_331, f01_331, 2), 0,
            '132−311=%s F01 net 331=%s' % (b01_331, f01_331),
        )
