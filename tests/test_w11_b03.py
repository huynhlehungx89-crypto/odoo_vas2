# -*- coding: utf-8 -*-
"""W11 — B03 LCTT gián tiếp: seed, 01/60/70, stage2 03–08/10–14."""
from odoo.exceptions import UserError
from odoo.tests import tagged, TransactionCase
from odoo.tools.float_utils import float_compare, float_round

from odoo.addons.connecta_vas.models.res_company import (
    W11_BCTC_CIT_AMOUNT,
    W11_BCTC_EXPECT_CASH,
    W11_BCTC_EXPECT_CASH_OPENING,
    W11_BCTC_EXPECT_DEP,
    W11_BCTC_LOAN_INTEREST,
)
from odoo.addons.connecta_vas.models.vas_cash_flow_activity import (
    VAS_OP_DEFAULT_CASH_FLOW,
)
from odoo.addons.connecta_vas.tests.common_vas_query_count import VasQueryCounter

B03_DESIGN_CODES = [
    '01', '02', '03', '04', '05', '06', '07', '08', '09',
    '10', '11', '12', '13', '14', '15', '16', '17', '18',
    '20', '21', '22', '23', '24', '25', '30',
    '31', '32', '33', '34', '35', '40', '50', '60', '61', '70',
]
B03_HD_CODES = list(B03_DESIGN_CODES)
B03_STAGE2_CODES = [
    '03', '04', '05', '06', '07', '08',
    '10', '11', '12', '13', '14',
]
B03_STAGE3_CODES = [
    '15', '16', '17', '18',
    '21', '22', '23', '24', '25',
    '31', '32', '33', '34', '35', '61',
]


@tagged('post_install', '-at_install', 'connecta_vas', 'connecta_vas_w11')
class TestW11B03Seed(TransactionCase):

    def test_01_cross_check_hd_and_formulas(self):
        regime = self.env.ref('connecta_vas.vas_regime_tt133')
        lines = self.env['vas.report.line'].search([
            ('form_code', '=', 'B03-DNN'),
            ('regime_id', '=', regime.id),
            ('active', '=', True),
        ])
        by_code = {l.code: l for l in lines}
        seed_codes = sorted(by_code)
        print('B03_CROSS design→seed missing', sorted(set(B03_DESIGN_CODES) - set(seed_codes)))
        print('B03_CROSS seed→design extra', sorted(set(seed_codes) - set(B03_DESIGN_CODES)))
        self.assertEqual(seed_codes, sorted(B03_DESIGN_CODES))
        self.assertEqual(seed_codes, sorted(B03_HD_CODES))

        self.assertEqual(by_code['09'].amount_source, 'total')
        self.assertEqual(
            set(by_code['09'].child_line_ids.mapped('code')),
            set('10 11 12 13 14 15 16 17 18'.split()),
        )
        self.assertEqual(
            set(by_code['02'].child_line_ids.mapped('code')),
            set('03 04 05 06 07 08'.split()),
        )
        self.assertEqual(by_code['03'].name, 'Khấu hao TSCĐ và BĐSĐT')
        for code in B03_STAGE2_CODES:
            self.assertEqual(by_code[code].code_custom_key, 'b03_stage2', code)
        for code in B03_STAGE3_CODES:
            self.assertEqual(by_code[code].code_custom_key, 'b03_stage3', code)

        # Chỉ công nợ (10/12) tách đối tác — HTK/trả trước/CKKD lấy SD thuần
        self.assertTrue(by_code['10'].aggregate_by_partner)
        self.assertTrue(by_code['12'].aggregate_by_partner)
        for code in ('11', '13', '14', '04', '08'):
            self.assertFalse(
                by_code[code].aggregate_by_partner,
                'Chỉ tiêu %s không được tách đối tác' % code,
            )
        self.assertIn('tăng PT→âm', by_code['10'].basis_note or '')
        self.assertIn('không tách', by_code['11'].basis_note or '')


@tagged('post_install', '-at_install', 'connecta_vas', 'connecta_vas_w11')
class TestW11B03Snapshot(TransactionCase):

    def _periods(self, company):
        p01 = self.env['vas.period'].search([
            ('fiscalyear_id.company_id', '=', company.id),
            ('date_start', '=', '2026-01-01'),
        ], limit=1)
        p12 = self.env['vas.period'].search([
            ('fiscalyear_id.company_id', '=', company.id),
            ('date_start', '=', '2026-12-01'),
        ], limit=1)
        return p01, p12

    def _fresh_b01a_b02(self, company, p01, p12):
        """Luôn lập mới — mở đầu kỳ / sổ demo có thể vừa bổ sung."""
        Snap = self.env['vas.report.snapshot']
        b01a = Snap.generate_b01a(company, p01, p12, hide_reversed=True)
        b02 = Snap.generate_b02(company, p01, p12, hide_reversed=True)
        return b01a, b02

    def test_01_w11_opening_and_stage2_numbers(self):
        self.env['res.company']._vas_w11_ensure_bctc_demo()
        company = self.env['res.company'].search(
            [('name', '=', 'W11-Thử BCTC')], limit=1,
        )
        p01, p12 = self._periods(company)
        b01a, b02 = self._fresh_b01a_b02(company, p01, p12)

        b01a_110 = b01a.line_ids.filtered(lambda l: l.code == '110')
        b02_50 = b02.line_ids.filtered(lambda l: l.code == '50')
        b02_23 = b02.line_ids.filtered(lambda l: l.code == '23')
        b02_60 = b02.line_ids.filtered(lambda l: l.code == '60')
        cash_o = b01a_110.amount_opening
        cash_c = b01a_110.amount_closing
        pnl50 = b02_50.amount_closing
        pnl60 = b02_60.amount_closing
        interest = b02_23.amount_closing

        print(
            'B03_OPENING_TABLE 111+112 đầu=%s cuối=%s expect_o=%s expect_c=%s'
            % (cash_o, cash_c, W11_BCTC_EXPECT_CASH_OPENING, W11_BCTC_EXPECT_CASH)
        )

        snap = self.env['vas.report.snapshot'].generate_b03(
            company, p01, p12, hide_reversed=True,
        )
        by = {l.code: l.amount_closing for l in snap.line_ids}
        print(
            'B03_W11_STAGE2',
            {k: by.get(k) for k in (
                '01', '02', '03', '04', '05', '06', '07', '08',
                '09', '10', '11', '12', '13', '14', '60', '70',
            )},
        )
        print('B03_W11_WARN_HEAD', (snap.warning_text or '')[:500])

        # 60 / 70 sau số dư đầu kỳ
        self.assertEqual(
            float_compare(cash_o, W11_BCTC_EXPECT_CASH_OPENING, 2), 0, cash_o,
        )
        self.assertEqual(float_compare(by['60'], cash_o, 2), 0, by['60'])
        self.assertEqual(float_compare(by['70'], cash_c, 2), 0, by['70'])
        self.assertEqual(float_compare(by['70'], W11_BCTC_EXPECT_CASH, 2), 0)
        self.assertEqual(float_compare(by['01'], pnl50, 2), 0)

        # 03 không bóc tách = toàn bộ KH kỳ
        self.assertFalse(company.vas_boc_tach_khau_hao_htk)
        self.assertEqual(
            float_compare(by['03'], W11_BCTC_EXPECT_DEP, 2), 0, by['03'],
        )

        # 07 = B02.23
        self.assertEqual(float_compare(by['07'], interest, 2), 0, by['07'])
        self.assertEqual(
            float_compare(by['07'], W11_BCTC_LOAN_INTEREST, 2), 0, by['07'],
        )

        # 11 = Δ SD thuần 156 = −10.000.000 (không tách đối tác)
        self.assertEqual(float_compare(by['11'], -10_000_000, 2), 0, by['11'])

        # 02 = Σ 03…08
        expect_02 = float_round(
            by['03'] + by['04'] + by['05'] + by['06'] + by['07'] + by['08'], 2,
        )
        self.assertEqual(float_compare(by['02'], expect_02, 2), 0, by['02'])

        # 09 = Σ 10…18 (gồm 15–18 stage3)
        expect_09 = float_round(
            sum(by.get(c, 0.0) for c in '10 11 12 13 14 15 16 17 18'.split()), 2,
        )
        self.assertEqual(float_compare(by['09'], expect_09, 2), 0, by['09'])

        # Stage3 chạm đầu tư/tài chính + lãi/thuế đã trả
        self.assertEqual(
            float_compare(by['15'], -W11_BCTC_LOAN_INTEREST, 2), 0, by['15'],
        )
        self.assertEqual(
            float_compare(by['16'], -W11_BCTC_CIT_AMOUNT, 2), 0, by['16'],
        )
        self.assertEqual(float_compare(by['33'], 100_000_000, 2), 0, by['33'])
        self.assertEqual(float_compare(by['31'], 200_000_000, 2), 0, by['31'])
        print(
            'B03_W11_STAGE3',
            {k: by.get(k) for k in (
                '15', '16', '17', '18',
                '21', '22', '23', '24', '25',
                '30', '31', '32', '33', '34', '35', '40', '50', '61',
            )},
        )
        print(
            'B03_L4',
            'diff=', snap.check_b03_l4_diff,
            'level=', snap.warning_level,
        )
        self.assertEqual(
            float_compare(snap.check_b03_l4_diff or 0.0, 0.0, 2), 0,
            'L4 phải lệch 0 trên W11 sau phân loại đủ; diff=%s warn=%s' % (
                snap.check_b03_l4_diff, (snap.warning_text or '')[:800],
            ),
        )

        # 06 cảnh báo khi có 711/811
        self.assertIn('711', snap.warning_text or '')
        self.assertIn('06', snap.warning_text or '')

        # B01a/B02 không bị sửa bởi lập B03
        b01a.invalidate_recordset()
        b02.invalidate_recordset()
        self.assertEqual(float_compare(b01a_110.amount_closing, cash_c, 2), 0)
        self.assertEqual(float_compare(b02_50.amount_closing, pnl50, 2), 0)
        self.assertEqual(float_compare(b02_60.amount_closing, pnl60, 2), 0)

    def test_02_missing_b02_raises_clear(self):
        regime = self.env.ref('connecta_vas.vas_regime_tt133')
        vnd = self.env.ref('base.VND')
        company = self.env['res.company'].create({
            'name': 'W11-B03 no B02',
            'currency_id': vnd.id,
            'vas_regime_id': regime.id,
            'vas_start_date': '2096-01-01',
        })
        self.env['vas.journal']._ensure_journals_for_company(company)
        fy = self.env['vas.fiscalyear'].create({
            'name': '2096b', 'date_from': '2096-01-01', 'date_to': '2096-12-31',
            'state': 'open', 'company_id': company.id,
        })
        period = self.env['vas.period'].create({
            'name': '01/2096', 'date_start': '2096-01-01', 'date_end': '2096-01-31',
            'fiscalyear_id': fy.id, 'state': 'open',
        })
        self.env['vas.report.snapshot'].generate_b01a(
            company, period, period, hide_reversed=True,
        )
        with self.assertRaises(UserError) as err:
            self.env['vas.report.snapshot'].generate_b03(
                company, period, period, hide_reversed=True,
            )
        msg = str(err.exception)
        self.assertIn('B02', msg)
        self.assertIn('không tự lập ngầm', msg)

    def test_03_warn_1281_balance(self):
        regime = self.env.ref('connecta_vas.vas_regime_tt133')
        vnd = self.env.ref('base.VND')
        company = self.env['res.company'].create({
            'name': 'W11-B03 1281b',
            'currency_id': vnd.id,
            'vas_regime_id': regime.id,
            'vas_start_date': '2096-01-01',
        })
        self.env['vas.journal']._ensure_journals_for_company(company)
        fy = self.env['vas.fiscalyear'].create({
            'name': '2096d', 'date_from': '2096-01-01', 'date_to': '2096-12-31',
            'state': 'open', 'company_id': company.id,
        })
        period = self.env['vas.period'].create({
            'name': '02/2096', 'date_start': '2096-02-01', 'date_end': '2096-02-29',
            'fiscalyear_id': fy.id, 'state': 'open',
        })
        journal = self.env['vas.journal'].search([
            ('company_id', '=', company.id), ('code', '=', 'TH'),
        ], limit=1)
        a1281 = self.env.ref('connecta_vas.vas_account_tt133_1281')
        a4111 = self.env.ref('connecta_vas.vas_account_tt133_4111')
        self.env['vas.move'].create({
            'date': '2096-02-10',
            'journal_id': journal.id,
            'regime_id': regime.id,
            'company_id': company.id,
            'ref': 'B03-1281b',
            'line_ids': [
                (0, 0, {
                    'account_id': a1281.id, 'name': 'TG',
                    'debit': 1_500_000, 'credit': 0,
                }),
                (0, 0, {
                    'account_id': a4111.id, 'name': 'Von',
                    'debit': 0, 'credit': 1_500_000,
                }),
            ],
        }).action_post()
        self.env['vas.report.snapshot'].generate_b01a(
            company, period, period, hide_reversed=True,
        )
        self.env['vas.report.snapshot'].generate_b02(
            company, period, period, hide_reversed=True,
        )
        snap = self.env['vas.report.snapshot'].generate_b03(
            company, period, period, hide_reversed=True,
        )
        self.assertIn('1281', snap.warning_text or '')

    def test_04_boc_tach_warn_and_exclude(self):
        self.env['res.company']._vas_w11_ensure_bctc_demo()
        company = self.env['res.company'].search(
            [('name', '=', 'W11-Thử BCTC')], limit=1,
        )
        p01, p12 = self._periods(company)
        self._fresh_b01a_b02(company, p01, p12)

        company.write({
            'vas_boc_tach_khau_hao_htk': True,
            'vas_khau_hao_trong_htk': 0,
        })
        snap_warn = self.env['vas.report.snapshot'].generate_b03(
            company, p01, p12, hide_reversed=True,
        )
        self.assertIn('Bóc tách', snap_warn.warning_text or '')
        self.assertIn('chưa nhập', (snap_warn.warning_text or '').lower())
        by_warn = {l.code: l.amount_closing for l in snap_warn.line_ids}
        # Chưa nhập → không đoán: mã 03 như không bóc tách
        self.assertEqual(
            float_compare(by_warn['03'], W11_BCTC_EXPECT_DEP, 2), 0, by_warn['03'],
        )

        kh_htk = 1_200_000
        company.write({'vas_khau_hao_trong_htk': kh_htk})
        self._fresh_b01a_b02(company, p01, p12)
        snap = self.env['vas.report.snapshot'].generate_b03(
            company, p01, p12, hide_reversed=True,
        )
        by = {l.code: l.amount_closing for l in snap.line_ids}
        expect_03 = float_round(W11_BCTC_EXPECT_DEP - kh_htk, 2)
        self.assertEqual(float_compare(by['03'], expect_03, 2), 0, by['03'])
        # 11 tăng thêm đúng số KH đã loại khỏi 03 (đồng bộ hai trường hợp)
        # So với bản không bóc tách cùng kỳ: delta_11 = +kh_htk
        company.write({
            'vas_boc_tach_khau_hao_htk': False,
            'vas_khau_hao_trong_htk': 0,
        })
        self._fresh_b01a_b02(company, p01, p12)
        snap_base = self.env['vas.report.snapshot'].generate_b03(
            company, p01, p12, hide_reversed=True,
        )
        base_11 = snap_base.line_ids.filtered(lambda l: l.code == '11').amount_closing
        self.assertEqual(
            float_compare(by['11'], float_round(base_11 + kh_htk, 2), 2), 0,
            '11=%s base=%s' % (by['11'], base_11),
        )
        # Trả cấu hình về mặc định
        company.write({
            'vas_boc_tach_khau_hao_htk': False,
            'vas_khau_hao_trong_htk': 0,
        })

    def test_05_config_boc_tach_default_and_save(self):
        company = self.env.company
        self.assertFalse(company.vas_boc_tach_khau_hao_htk)
        company.write({
            'vas_boc_tach_khau_hao_htk': True,
            'vas_khau_hao_trong_htk': 123_456,
        })
        company.invalidate_recordset()
        self.assertTrue(company.vas_boc_tach_khau_hao_htk)
        self.assertEqual(
            float_compare(company.vas_khau_hao_trong_htk, 123_456, 2), 0,
        )
        company.write({
            'vas_boc_tach_khau_hao_htk': False,
            'vas_khau_hao_trong_htk': 0,
        })

    def test_06_query_count_not_linear_in_indicators(self):
        regime = self.env.ref('connecta_vas.vas_regime_tt133')
        vnd = self.env.ref('base.VND')
        company = self.env['res.company'].create({
            'name': 'W11-B03 Q2',
            'currency_id': vnd.id,
            'vas_regime_id': regime.id,
            'vas_start_date': '2097-01-01',
        })
        self.env['vas.journal']._ensure_journals_for_company(company)
        fy = self.env['vas.fiscalyear'].create({
            'name': '2097q2', 'date_from': '2097-01-01', 'date_to': '2097-12-31',
            'state': 'open', 'company_id': company.id,
        })
        period = self.env['vas.period'].create({
            'name': '03/2097', 'date_start': '2097-03-01', 'date_end': '2097-03-31',
            'fiscalyear_id': fy.id, 'state': 'open',
        })
        self.env['vas.report.snapshot'].generate_b01a(
            company, period, period, hide_reversed=True,
        )
        self.env['vas.report.snapshot'].generate_b02(
            company, period, period, hide_reversed=True,
        )

        def count_gen():
            self.env.flush_all()
            with VasQueryCounter(self.env.cr) as qc:
                snap = self.env['vas.report.snapshot'].generate_b03(
                    company, period, period, hide_reversed=True,
                )
                self.env.flush_all()
            return qc.count, snap

        count_gen()
        q1, _s1 = count_gen()
        n_base = self.env['vas.report.line'].search_count([
            ('form_code', '=', 'B03-DNN'),
            ('regime_id', '=', regime.id),
            ('active', '=', True),
        ])
        probes = self.env['vas.report.line']
        for i in range(n_base):
            probes |= self.env['vas.report.line'].create({
                'sequence': 9000 + i,
                'code': 'Z%03d' % i,
                'name': 'Probe B03 %s' % i,
                'form_code': 'B03-DNN',
                'regime_id': regime.id,
                'line_role': 'detail',
                'amount_source': 'code_custom',
                'code_custom_key': 'b03_pending',
                'basis_kind': 'chot_connecta',
                'is_system': False,
                'active': True,
            })
        self.addCleanup(probes.unlink)
        q2, _s2 = count_gen()
        delta = q2 - q1
        print('B03_QUERY_SCALE base=%s double=%s delta=%s n=%s' % (q1, q2, delta, n_base))
        self.assertLessEqual(delta, 25)
        self.assertLess(delta, n_base)
        print('B03_QUERY_COUNT', q1)

    def test_07_wc_net_inventory_and_131_331_split(self):
        """Mã 11 = SD thuần 156; 131/331 dư Nợ→10, dư Có→12; không rơi số."""
        self.env['res.company']._vas_w11_ensure_bctc_demo()
        company = self.env['res.company'].search(
            [('name', '=', 'W11-Thử BCTC')], limit=1,
        )
        p01, p12 = self._periods(company)
        b01a, b02 = self._fresh_b01a_b02(company, p01, p12)
        b01a_110 = b01a.line_ids.filtered(lambda l: l.code == '110').amount_closing
        b02_50 = b02.line_ids.filtered(lambda l: l.code == '50').amount_closing
        b09 = self.env['vas.report.snapshot'].generate_b09(
            company, p01, p12, hide_reversed=True,
        )
        b09_v1 = b09.line_ids.filtered(lambda l: l.code == 'V.1.total')
        b09_cash = b09_v1.amount_closing if b09_v1 else None

        Snap = self.env['vas.report.snapshot']
        buckets = Snap._books_aggregate_buckets(
            company, p01.date_start, p12.date_end, True,
        )
        a131 = self.env.ref('connecta_vas.vas_account_tt133_131')
        a331 = self.env.ref('connecta_vas.vas_account_tt133_331')
        a156 = self.env.ref('connecta_vas.vas_account_tt133_156')

        def partner_side_sums(aid):
            d_tot = c_tot = 0.0
            for (acc, _pid), b in buckets.items():
                if acc != aid:
                    continue
                o, cl = b['opening'], b['closing']
                o_dr = o if o > 0 else 0.0
                c_dr = cl if cl > 0 else 0.0
                o_cr = -o if o < 0 else 0.0
                c_cr = -cl if cl < 0 else 0.0
                d_tot = float_round(d_tot + (o_dr - c_dr), 2)
                c_tot = float_round(c_tot + (c_cr - o_cr), 2)
            return d_tot, c_tot

        d131, c131 = partner_side_sums(a131.id)
        d331, c331 = partner_side_sums(a331.id)
        r156 = Snap._books_rollup_account(buckets, a156.id)
        expect_11 = float_round(
            r156['opening_debit'] - r156['closing_debit'], 2,
        )
        self.assertEqual(float_compare(expect_11, -10_000_000, 2), 0, expect_11)
        self.assertEqual(float_compare(d131, -38_000_000, 2), 0, d131)
        self.assertEqual(float_compare(c131, 15_000_000, 2), 0, c131)
        self.assertEqual(float_compare(d331, -10_000_000, 2), 0, d331)
        self.assertEqual(float_compare(c331, 35_000_000, 2), 0, c331)

        snap = Snap.generate_b03(company, p01, p12, hide_reversed=True)
        by = {l.code: l.amount_closing for l in snap.line_ids}
        print('B03_WC_FIX', {k: by[k] for k in '10 11 12 13 14'.split()})
        self.assertEqual(float_compare(by['11'], -10_000_000, 2), 0, by['11'])
        # 131/331: phần dư Nợ nằm trong 10, dư Có trong 12 — cộng hai phía không rơi
        self.assertLessEqual(by['10'], d131 + d331)  # 10 còn TK khác (âm hơn)
        self.assertGreaterEqual(by['12'], c131 + c331)  # 12 còn TK khác
        # Bảo toàn từng TK: debit_delta + credit_delta = net open−close kiểu partner
        self.assertEqual(
            float_compare(d131 + c131, -23_000_000, 2), 0, d131 + c131,
        )
        self.assertEqual(
            float_compare(d331 + c331, 25_000_000, 2), 0, d331 + c331,
        )
        # Không còn cảnh báo bỏ cả 335
        self.assertNotIn('không đưa 335', snap.warning_text or '')
        # B01a / B02 / B09 không đổi vì lập B03
        b01a.invalidate_recordset()
        b02.invalidate_recordset()
        b09.invalidate_recordset()
        self.assertEqual(
            float_compare(
                b01a.line_ids.filtered(lambda l: l.code == '110').amount_closing,
                b01a_110, 2,
            ), 0,
        )
        self.assertEqual(
            float_compare(
                b02.line_ids.filtered(lambda l: l.code == '50').amount_closing,
                b02_50, 2,
            ), 0,
        )
        if b09_cash is not None:
            self.assertEqual(
                float_compare(
                    b09.line_ids.filtered(
                        lambda l: l.code == 'V.1.total',
                    ).amount_closing,
                    b09_cash, 2,
                ), 0,
            )

    def test_08_335_exclude_loan_interest_warn_other(self):
        """Mã 12 lấy 335 nhưng trừ lãi vas.loan; phần không phân loại → cảnh báo."""
        regime = self.env.ref('connecta_vas.vas_regime_tt133')
        vnd = self.env.ref('base.VND')
        company = self.env['res.company'].create({
            'name': 'W11-B03 335x',
            'currency_id': vnd.id,
            'vas_regime_id': regime.id,
            'vas_start_date': '2098-01-01',
        })
        self.env['vas.journal']._ensure_journals_for_company(company)
        fy = self.env['vas.fiscalyear'].create({
            'name': '2098x', 'date_from': '2098-01-01', 'date_to': '2098-12-31',
            'state': 'open', 'company_id': company.id,
        })
        period = self.env['vas.period'].create({
            'name': '01/2098', 'date_start': '2098-01-01', 'date_end': '2098-01-31',
            'fiscalyear_id': fy.id, 'state': 'open',
        })
        journal = self.env['vas.journal'].search([
            ('company_id', '=', company.id), ('code', '=', 'TH'),
        ], limit=1)
        a335 = self.env.ref('connecta_vas.vas_account_tt133_335')
        a642 = self.env.ref('connecta_vas.vas_account_tt133_6422')
        a111 = self.env.ref('connecta_vas.vas_account_tt133_111')
        # Lãi vay (loại khỏi mã 12)
        self.env['vas.move'].create({
            'date': '2098-01-10',
            'journal_id': journal.id,
            'regime_id': regime.id,
            'company_id': company.id,
            'move_kind': 'loan_interest',
            'ref': 'B03-335-INT',
            'line_ids': [
                (0, 0, {
                    'account_id': a642.id, 'name': 'Lai',
                    'debit': 400_000, 'credit': 0,
                }),
                (0, 0, {
                    'account_id': a335.id, 'name': 'Lai PT',
                    'debit': 0, 'credit': 400_000,
                }),
            ],
        }).action_post()
        # Phải trả khác trên 335 — không phải loan_interest → vào 12 + cảnh báo
        self.env['vas.move'].create({
            'date': '2098-01-15',
            'journal_id': journal.id,
            'regime_id': regime.id,
            'company_id': company.id,
            'ref': 'B03-335-OTHER',
            'line_ids': [
                (0, 0, {
                    'account_id': a111.id, 'name': 'Chi',
                    'debit': 250_000, 'credit': 0,
                }),
                (0, 0, {
                    'account_id': a335.id, 'name': 'PT khac',
                    'debit': 0, 'credit': 250_000,
                }),
            ],
        }).action_post()
        self.env['vas.report.snapshot'].generate_b01a(
            company, period, period, hide_reversed=True,
        )
        self.env['vas.report.snapshot'].generate_b02(
            company, period, period, hide_reversed=True,
        )
        snap = self.env['vas.report.snapshot'].generate_b03(
            company, period, period, hide_reversed=True,
        )
        amt_12 = snap.line_ids.filtered(lambda l: l.code == '12').amount_closing
        self.assertEqual(float_compare(amt_12, 250_000, 2), 0, amt_12)
        warn = snap.warning_text or ''
        self.assertIn('335', warn)
        self.assertIn('250,000', warn.replace('.', ','))
        self.assertIn('loan_interest', warn)
        self.assertNotIn('không đưa 335', warn)

    def test_09_cash_flow_activity_defaults_and_unclassified(self):
        """Mặc định theo bảng 2(a); không nhãn → trống; sửa được; cảnh báo chưa phân loại."""
        Payment = self.env['account.payment']
        self.assertEqual(
            VAS_OP_DEFAULT_CASH_FLOW.get('loan_receipt'), 'financing',
        )
        self.assertEqual(
            VAS_OP_DEFAULT_CASH_FLOW.get('payroll_pay'), 'operating',
        )
        self.assertEqual(
            VAS_OP_DEFAULT_CASH_FLOW.get('internal_transfer'), 'none',
        )
        self.assertFalse(VAS_OP_DEFAULT_CASH_FLOW.get(''))

        journal = self.env['account.journal'].search([
            ('type', 'in', ('cash', 'bank')),
            ('company_id', '=', self.env.company.id),
        ], limit=1)
        if not journal:
            journal = self.env['account.journal'].create({
                'name': 'CF test cash', 'code': 'CFT', 'type': 'cash',
                'company_id': self.env.company.id,
            })
        pay = Payment.create({
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': self.env.company.partner_id.id,
            'amount': 1_000,
            'journal_id': journal.id,
            'vas_operation_type': 'capital_receipt',
        })
        self.assertEqual(pay.vas_cash_flow_activity, 'financing')
        pay.write({'vas_cash_flow_activity': 'operating'})
        self.assertEqual(pay.vas_cash_flow_activity, 'operating')

        bare = Payment.create({
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': self.env.company.partner_id.id,
            'amount': 2_000,
            'journal_id': journal.id,
        })
        self.assertFalse(bare.vas_cash_flow_activity)

        # Chứng từ chưa phân loại → cảnh báo + không vào chỉ tiêu
        regime = self.env.ref('connecta_vas.vas_regime_tt133')
        vnd = self.env.ref('base.VND')
        company = self.env['res.company'].create({
            'name': 'W11-B03 CF bare',
            'currency_id': vnd.id,
            'vas_regime_id': regime.id,
            'vas_start_date': '2099-01-01',
        })
        self.env['vas.journal']._ensure_journals_for_company(company)
        fy = self.env['vas.fiscalyear'].create({
            'name': '2099cf', 'date_from': '2099-01-01', 'date_to': '2099-12-31',
            'state': 'open', 'company_id': company.id,
        })
        period = self.env['vas.period'].create({
            'name': '01/2099', 'date_start': '2099-01-01', 'date_end': '2099-01-31',
            'fiscalyear_id': fy.id, 'state': 'open',
        })
        vj = self.env['vas.journal'].search([
            ('company_id', '=', company.id), ('code', '=', 'TH'),
        ], limit=1)
        a111 = self.env.ref('connecta_vas.vas_account_tt133_111')
        a411 = self.env.ref('connecta_vas.vas_account_tt133_4111')
        self.env['vas.move'].create({
            'date': '2099-01-10',
            'journal_id': vj.id,
            'regime_id': regime.id,
            'company_id': company.id,
            'ref': 'BARE-CF-NO-LABEL',
            'line_ids': [
                (0, 0, {
                    'account_id': a111.id, 'name': 'Thu',
                    'debit': 7_777_000, 'credit': 0,
                }),
                (0, 0, {
                    'account_id': a411.id, 'name': 'Von',
                    'debit': 0, 'credit': 7_777_000,
                }),
            ],
        }).action_post()
        self.env['vas.report.snapshot'].generate_b01a(
            company, period, period, hide_reversed=True,
        )
        self.env['vas.report.snapshot'].generate_b02(
            company, period, period, hide_reversed=True,
        )
        snap = self.env['vas.report.snapshot'].generate_b03(
            company, period, period, hide_reversed=True,
        )
        by = {l.code: l.amount_closing for l in snap.line_ids}
        self.assertEqual(float_compare(by.get('31', 0.0), 0.0, 2), 0)
        self.assertEqual(float_compare(by.get('33', 0.0), 0.0, 2), 0)
        warn = snap.warning_text or ''
        self.assertIn('chưa phân loại', warn.lower())
        self.assertIn('7,777,000', warn.replace('.', ','))
        self.assertIn('BARE-CF-NO-LABEL', warn)
