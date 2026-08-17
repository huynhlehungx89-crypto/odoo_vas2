# -*- coding: utf-8 -*-
"""W11 — B02 KQKD: seed, số W11 (có TC/khác/thuế), lưới G2, mã 23."""
from odoo.tests import tagged, TransactionCase
from odoo.tools.float_utils import float_compare, float_round

from odoo.addons.connecta_vas.models.res_company import (
    W11_BCTC_CIT_AMOUNT,
    W11_BCTC_EXPECT_ADMIN,
    W11_BCTC_EXPECT_PNL60,
    W11_BCTC_EXPECT_REV01,
    W11_BCTC_FINANCE_INCOME,
    W11_BCTC_LOAN_INTEREST,
    W11_BCTC_NON_INTEREST_635,
    W11_BCTC_OTHER_EXPENSE,
    W11_BCTC_OTHER_INCOME,
)
from odoo.addons.connecta_vas.tests.common_vas_query_count import VasQueryCounter

# Mã B02 theo thiết kế §2 (PDF tr.34–37) — kiểm chéo hai chiều
B02_DESIGN_CODES = [
    '01', '02', '10', '11', '20', '21', '22', '23', '24',
    '30', '31', '32', '40', '50', '51', '60',
]


@tagged('post_install', '-at_install', 'connecta_vas', 'connecta_vas_w11')
class TestW11B02Seed(TransactionCase):
    """Kiểm chéo seed ↔ thiết kế + cha con."""

    def test_01_cross_check_design_and_parent_child(self):
        regime = self.env.ref('connecta_vas.vas_regime_tt133')
        lines = self.env['vas.report.line'].search([
            ('form_code', '=', 'B02-DNN'),
            ('regime_id', '=', regime.id),
            ('active', '=', True),
        ])
        by_code = {l.code: l for l in lines}
        seed_codes = sorted(by_code)
        design = sorted(B02_DESIGN_CODES)
        print('B02_CROSS design→seed missing', sorted(set(design) - set(seed_codes)))
        print('B02_CROSS seed→design extra', sorted(set(seed_codes) - set(design)))
        self.assertEqual(seed_codes, design)

        # Ba chốt Connecta
        self.assertEqual(
            by_code['01'].account_codes,
            '511,5111,5112,5113,5118',
        )
        self.assertEqual(by_code['02'].account_codes, by_code['01'].account_codes)
        self.assertEqual(by_code['02'].counterpart_account_codes, '111,112,131')
        self.assertEqual(by_code['24'].account_codes, '6421,6422')
        self.assertEqual(by_code['23'].amount_source, 'code_custom')
        self.assertEqual(by_code['23'].code_custom_key, 'b02_loan_interest')

        # Cha con
        def child_codes(code):
            return set(by_code[code].child_line_ids.mapped('code'))

        self.assertEqual(child_codes('10'), {'01', '02'})
        self.assertEqual(child_codes('20'), {'10', '11'})
        self.assertEqual(child_codes('30'), {'20', '21', '22', '24'})
        self.assertEqual(child_codes('40'), {'31', '32'})
        self.assertEqual(child_codes('50'), {'30', '40'})
        self.assertEqual(child_codes('60'), {'50', '51'})

        # Mọi con được khai phải thuộc đúng một tổng (không mồ côi quan hệ)
        parents_of = {}
        for total in lines.filtered(lambda l: l.line_role == 'total'):
            for ch in total.child_line_ids:
                parents_of.setdefault(ch.code, []).append(total.code)
        orphans = [
            c for c in seed_codes
            if c not in ('01', '02', '11', '21', '22', '23', '24', '31', '32', '51')
            and c not in parents_of
            and by_code[c].line_role == 'detail'
        ]
        # detail leaves that are not children of any total would be wrong;
        # totals themselves are roots except nested
        # Lá detail nằm trong công thức tổng (mã 23 là «trong đó» — không vào total)
        for code in ('01', '02', '11', '21', '22', '24', '31', '32', '51'):
            self.assertIn(code, parents_of, 'thiếu cha cho %s' % code)
        self.assertNotIn('23', parents_of)

        # B01a 200/500 công thức mẫu
        b01 = {
            l.code: l for l in self.env['vas.report.line'].search([
                ('form_code', '=', 'B01a-DNN'), ('regime_id', '=', regime.id),
            ])
        }
        self.assertEqual(
            set(b01['200'].child_line_ids.mapped('code')),
            {'110', '120', '130', '140', '150', '160', '170', '180'},
        )
        self.assertEqual(
            set(b01['500'].child_line_ids.mapped('code')),
            {'300', '400'},
        )
        print('B01a_FORMULA 200/500 OK')


@tagged('post_install', '-at_install', 'connecta_vas', 'connecta_vas_w11')
class TestW11B02Snapshot(TransactionCase):

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

    def test_01_w11_bctc_numbers_and_grids(self):
        self.env['res.company']._vas_w11_ensure_bctc_demo()
        company = self.env['res.company'].search(
            [('name', '=', 'W11-Thử BCTC')], limit=1,
        )
        p01, p12 = self._periods(company)
        snap = self.env['vas.report.snapshot'].generate_b02(
            company, p01, p12, hide_reversed=True,
        )
        by = {l.code: l.amount_closing for l in snap.line_ids}
        print('B02_W11', {k: by[k] for k in B02_DESIGN_CODES})
        print('B02_W11_WARN', snap.warning_text or '')
        print(
            'B02_GRIDS 60=%s diff4212=%s diff417=%s'
            % (by.get('60'), snap.check_60_4212_diff, snap.check_60_b01a_417_diff)
        )

        # Doanh thu / GV / CP QLDN (+ A28 DT 5111 + CP 6422)
        self.assertEqual(float_compare(by['01'], W11_BCTC_EXPECT_REV01, 2), 0)
        self.assertEqual(float_compare(by['02'], 0.0, 2), 0)
        self.assertEqual(float_compare(by['10'], W11_BCTC_EXPECT_REV01, 2), 0)
        self.assertEqual(float_compare(by['11'], -40_000_000, 2), 0)
        # 20 = 10+11
        self.assertEqual(
            float_compare(by['20'], W11_BCTC_EXPECT_REV01 - 40_000_000, 2), 0,
        )
        self.assertEqual(
            float_compare(by['24'], -(5_000_000 + W11_BCTC_EXPECT_ADMIN), 2), 0,
        )

        # Tài chính / khác / thuế (bộ bổ sung)
        self.assertEqual(float_compare(by['21'], W11_BCTC_FINANCE_INCOME, 2), 0)
        self.assertEqual(
            float_compare(by['22'], -(W11_BCTC_LOAN_INTEREST + W11_BCTC_NON_INTEREST_635), 2), 0,
            by['22'],
        )
        self.assertEqual(float_compare(by['23'], W11_BCTC_LOAN_INTEREST, 2), 0)
        self.assertEqual(float_compare(by['31'], W11_BCTC_OTHER_INCOME, 2), 0)
        self.assertEqual(float_compare(by['32'], -W11_BCTC_OTHER_EXPENSE, 2), 0)
        self.assertEqual(float_compare(by['51'], -W11_BCTC_CIT_AMOUNT, 2), 0)

        # 30 = 20+21+22+24 ; 40 = 31+32 ; 50 = 30+40 ; 60 = 50+51
        expect_20 = W11_BCTC_EXPECT_REV01 - 40_000_000
        expect_24 = -(5_000_000 + W11_BCTC_EXPECT_ADMIN)
        expect_30 = float_round(
            expect_20 + W11_BCTC_FINANCE_INCOME
            - (W11_BCTC_LOAN_INTEREST + W11_BCTC_NON_INTEREST_635)
            + expect_24,
            2,
        )
        expect_40 = W11_BCTC_OTHER_INCOME - W11_BCTC_OTHER_EXPENSE
        expect_50 = float_round(expect_30 + expect_40, 2)
        self.assertEqual(float_compare(by['30'], expect_30, 2), 0, by['30'])
        self.assertEqual(float_compare(by['40'], expect_40, 2), 0, by['40'])
        self.assertEqual(float_compare(by['50'], expect_50, 2), 0, by['50'])
        self.assertEqual(float_compare(by['60'], W11_BCTC_EXPECT_PNL60, 2), 0, by['60'])
        self.assertEqual(
            float_compare(by['60'], by['50'] + by['51'], 2), 0,
        )

        self.assertEqual(float_compare(snap.check_60_4212_diff, 0.0, 2), 0)
        self.assertEqual(float_compare(snap.check_60_b01a_417_diff, 0.0, 2), 0)
        self.assertNotEqual(snap.warning_level, 'danger', snap.warning_text)

        # Cảnh báo 635 còn lại — đúng số tiền khoản chiết khấu
        self.assertTrue(snap.warning_text, 'Thiếu cảnh báo 635 còn lại')
        warn_flat = (snap.warning_text or '').replace(',', '')
        self.assertIn('800000', warn_flat, snap.warning_text)
        self.assertIn('635', snap.warning_text)
        self.assertNotIn('LƯỚI G2', snap.warning_text or '')
        # Phương án tạm 31/32 — có PS 711/811 thì cảnh báo (không chặn)
        self.assertIn('phương án tạm', (snap.warning_text or '').lower())
        self.assertIn('711', snap.warning_text)
        self.assertIn('31', snap.warning_text)

        # In bảng số dư lớp tài khoản (F01) để báo cáo VIỆC 1
        f01 = self.env['vas.trial.balance.wizard'].get_report_data({
            'company_id': company.id,
            'period_from_id': p01.id,
            'period_to_id': p12.id,
            'hide_reversed': True,
        })
        print('W11_TB_HEADER')
        for line in f01['lines']:
            if line.get('is_total'):
                print('W11_TB_TOTAL', line['values'])
                continue
            code = line['values'][0]
            if not code:
                continue
            # values: code, name, open_dr, open_cr, ps_dr, ps_cr, close_dr, close_cr (typical)
            print('W11_TB', line['values'])

    def test_02_not_closed_warns_911(self):
        """Kỳ chưa KC — đối ứng 911 = 0 + cảnh báo."""
        regime = self.env.ref('connecta_vas.vas_regime_tt133')
        vnd = self.env.ref('base.VND')
        company = self.env['res.company'].create({
            'name': 'W11-B02 Chưa KC',
            'currency_id': vnd.id,
            'vas_regime_id': regime.id,
            'vas_start_date': '2095-01-01',
        })
        self.env['vas.journal']._ensure_journals_for_company(company)
        journal = self.env['vas.journal'].search([
            ('company_id', '=', company.id), ('code', '=', 'TH'),
        ], limit=1)
        fy = self.env['vas.fiscalyear'].create({
            'name': '2095', 'date_from': '2095-01-01', 'date_to': '2095-12-31',
            'state': 'open', 'company_id': company.id,
        })
        period = self.env['vas.period'].create({
            'name': '06/2095', 'date_start': '2095-06-01', 'date_end': '2095-06-30',
            'fiscalyear_id': fy.id, 'state': 'open',
        })
        a632 = self.env.ref('connecta_vas.vas_account_tt133_632')
        a156 = self.env.ref('connecta_vas.vas_account_tt133_156')
        move = self.env['vas.move'].create({
            'date': '2095-06-10',
            'journal_id': journal.id,
            'regime_id': regime.id,
            'company_id': company.id,
            'move_kind': 'manual',
            'line_ids': [
                (0, 0, {'account_id': a632.id, 'name': 'GV', 'debit': 5_000_000, 'credit': 0}),
                (0, 0, {'account_id': a156.id, 'name': 'Kho', 'debit': 0, 'credit': 5_000_000}),
            ],
        })
        move.action_post()
        snap = self.env['vas.report.snapshot'].generate_b02(
            company, period, period, hide_reversed=True,
        )
        line_11 = snap.line_ids.filtered(lambda l: l.code == '11')
        self.assertEqual(float_compare(line_11.amount_closing, 0.0, 2), 0)
        self.assertTrue(snap.warning_text)
        self.assertIn('11', snap.warning_text)
        self.assertIn('chưa kết chuyển', snap.warning_text)

    def test_03_reverse_closing_no_double(self):
        regime = self.env.ref('connecta_vas.vas_regime_tt133')
        vnd = self.env.ref('base.VND')
        company = self.env['res.company'].create({
            'name': 'W11-B02 Rev KC',
            'currency_id': vnd.id,
            'vas_regime_id': regime.id,
            'vas_start_date': '2095-01-01',
        })
        self.env['vas.journal']._ensure_journals_for_company(company)
        journal = self.env['vas.journal'].search([
            ('company_id', '=', company.id), ('code', '=', 'TH'),
        ], limit=1)
        fy = self.env['vas.fiscalyear'].create({
            'name': '2095b', 'date_from': '2095-01-01', 'date_to': '2095-12-31',
            'state': 'open', 'company_id': company.id,
        })
        period = self.env['vas.period'].create({
            'name': '07/2095', 'date_start': '2095-07-01', 'date_end': '2095-07-31',
            'fiscalyear_id': fy.id, 'state': 'open',
        })
        a632 = self.env.ref('connecta_vas.vas_account_tt133_632')
        a911 = self.env.ref('connecta_vas.vas_account_tt133_911')
        m1 = self.env['vas.move'].create({
            'date': '2095-07-15',
            'journal_id': journal.id,
            'regime_id': regime.id,
            'company_id': company.id,
            'move_kind': 'closing',
            'line_ids': [
                (0, 0, {'account_id': a911.id, 'name': 'KC', 'debit': 3_000_000, 'credit': 0}),
                (0, 0, {'account_id': a632.id, 'name': 'KC', 'debit': 0, 'credit': 3_000_000}),
            ],
        })
        m1.action_post()
        snap1 = self.env['vas.report.snapshot'].generate_b02(
            company, period, period, hide_reversed=True,
        )
        amt1 = abs(snap1.line_ids.filtered(lambda l: l.code == '11').amount_closing)
        self.assertEqual(float_compare(amt1, 3_000_000, 2), 0)
        m1.action_reverse()
        m2 = self.env['vas.move'].create({
            'date': '2095-07-16',
            'journal_id': journal.id,
            'regime_id': regime.id,
            'company_id': company.id,
            'move_kind': 'closing',
            'line_ids': [
                (0, 0, {'account_id': a911.id, 'name': 'KC2', 'debit': 3_000_000, 'credit': 0}),
                (0, 0, {'account_id': a632.id, 'name': 'KC2', 'debit': 0, 'credit': 3_000_000}),
            ],
        })
        m2.action_post()
        snap2 = self.env['vas.report.snapshot'].generate_b02(
            company, period, period, hide_reversed=True,
        )
        amt2 = abs(snap2.line_ids.filtered(lambda l: l.code == '11').amount_closing)
        self.assertEqual(float_compare(amt2, 3_000_000, 2), 0, amt2)

    def test_04_loan_interest_and_residual_635(self):
        regime = self.env.ref('connecta_vas.vas_regime_tt133')
        vnd = self.env.ref('base.VND')
        company = self.env['res.company'].create({
            'name': 'W11-B02 Lãi vay',
            'currency_id': vnd.id,
            'vas_regime_id': regime.id,
            'vas_start_date': '2095-01-01',
        })
        self.env['vas.journal']._ensure_journals_for_company(company)
        journal = self.env['vas.journal'].search([
            ('company_id', '=', company.id), ('code', '=', 'TH'),
        ], limit=1)
        fy = self.env['vas.fiscalyear'].create({
            'name': '2095c', 'date_from': '2095-01-01', 'date_to': '2095-12-31',
            'state': 'open', 'company_id': company.id,
        })
        period = self.env['vas.period'].create({
            'name': '08/2095', 'date_start': '2095-08-01', 'date_end': '2095-08-31',
            'fiscalyear_id': fy.id, 'state': 'open',
        })
        a635 = self.env.ref('connecta_vas.vas_account_tt133_635')
        a111 = self.env.ref('connecta_vas.vas_account_tt133_111')
        # Lãi vay nhận diện
        m_int = self.env['vas.move'].create({
            'date': '2095-08-10',
            'journal_id': journal.id,
            'regime_id': regime.id,
            'company_id': company.id,
            'move_kind': 'loan_interest',
            'line_ids': [
                (0, 0, {'account_id': a635.id, 'name': 'Lãi', 'debit': 2_000_000, 'credit': 0}),
                (0, 0, {'account_id': a111.id, 'name': 'Lãi', 'debit': 0, 'credit': 2_000_000}),
            ],
        })
        m_int.action_post()
        # 635 khác — không nhận diện
        m_other = self.env['vas.move'].create({
            'date': '2095-08-11',
            'journal_id': journal.id,
            'regime_id': regime.id,
            'company_id': company.id,
            'move_kind': 'manual',
            'line_ids': [
                (0, 0, {'account_id': a635.id, 'name': 'CKTT', 'debit': 500_000, 'credit': 0}),
                (0, 0, {'account_id': a111.id, 'name': 'CKTT', 'debit': 0, 'credit': 500_000}),
            ],
        })
        m_other.action_post()
        snap = self.env['vas.report.snapshot'].generate_b02(
            company, period, period, hide_reversed=True,
        )
        line_23 = snap.line_ids.filtered(lambda l: l.code == '23')
        self.assertEqual(float_compare(line_23.amount_closing, 2_000_000, 2), 0)
        self.assertTrue(snap.warning_text)
        self.assertIn('500', snap.warning_text.replace(',', ''))
        self.assertIn('635', snap.warning_text)

    def test_05_511_parent_and_child_no_double(self):
        regime = self.env.ref('connecta_vas.vas_regime_tt133')
        vnd = self.env.ref('base.VND')
        company = self.env['res.company'].create({
            'name': 'W11-B02 511',
            'currency_id': vnd.id,
            'vas_regime_id': regime.id,
            'vas_start_date': '2095-01-01',
        })
        self.env['vas.journal']._ensure_journals_for_company(company)
        journal = self.env['vas.journal'].search([
            ('company_id', '=', company.id), ('code', '=', 'TH'),
        ], limit=1)
        fy = self.env['vas.fiscalyear'].create({
            'name': '2095d', 'date_from': '2095-01-01', 'date_to': '2095-12-31',
            'state': 'open', 'company_id': company.id,
        })
        period = self.env['vas.period'].create({
            'name': '09/2095', 'date_start': '2095-09-01', 'date_end': '2095-09-30',
            'fiscalyear_id': fy.id, 'state': 'open',
        })
        a511 = self.env.ref('connecta_vas.vas_account_tt133_511')
        a5111 = self.env.ref('connecta_vas.vas_account_tt133_5111')
        a131 = self.env.ref('connecta_vas.vas_account_tt133_131')
        self.env['vas.move'].create({
            'date': '2095-09-05',
            'journal_id': journal.id,
            'regime_id': regime.id,
            'company_id': company.id,
            'move_kind': 'manual',
            'line_ids': [
                (0, 0, {'account_id': a131.id, 'name': 'BH', 'debit': 10_000_000, 'credit': 0}),
                (0, 0, {'account_id': a511.id, 'name': 'DT cha', 'debit': 0, 'credit': 6_000_000}),
                (0, 0, {'account_id': a5111.id, 'name': 'DT con', 'debit': 0, 'credit': 4_000_000}),
            ],
        }).action_post()
        snap = self.env['vas.report.snapshot'].generate_b02(
            company, period, period, hide_reversed=True,
        )
        amt01 = snap.line_ids.filtered(lambda l: l.code == '01').amount_closing
        self.assertEqual(float_compare(amt01, 10_000_000, 2), 0, amt01)

    def test_06_query_count_not_linear_in_indicators(self):
        regime = self.env.ref('connecta_vas.vas_regime_tt133')
        vnd = self.env.ref('base.VND')
        company = self.env['res.company'].create({
            'name': 'W11-B02 Q',
            'currency_id': vnd.id,
            'vas_regime_id': regime.id,
            'vas_start_date': '2095-01-01',
        })
        self.env['vas.journal']._ensure_journals_for_company(company)
        fy = self.env['vas.fiscalyear'].create({
            'name': '2095e', 'date_from': '2095-01-01', 'date_to': '2095-12-31',
            'state': 'open', 'company_id': company.id,
        })
        period = self.env['vas.period'].create({
            'name': '10/2095', 'date_start': '2095-10-01', 'date_end': '2095-10-31',
            'fiscalyear_id': fy.id, 'state': 'open',
        })

        def count_gen():
            self.env.flush_all()
            with VasQueryCounter(self.env.cr) as qc:
                snap = self.env['vas.report.snapshot'].generate_b02(
                    company, period, period, hide_reversed=True,
                )
                self.env.flush_all()
            return qc.count, snap

        count_gen()  # warm-up
        q1, _s1 = count_gen()
        n_base = self.env['vas.report.line'].search_count([
            ('form_code', '=', 'B02-DNN'),
            ('regime_id', '=', regime.id),
            ('active', '=', True),
        ])
        probes = self.env['vas.report.line']
        for i in range(n_base):
            probes |= self.env['vas.report.line'].create({
                'sequence': 9000 + i,
                'code': 'Y%03d' % i,
                'name': 'Probe B02 %s' % i,
                'form_code': 'B02-DNN',
                'regime_id': regime.id,
                'line_role': 'detail',
                'amount_source': 'force_zero',
                'force_zero_currency_id': vnd.id,
                'basis_kind': 'chot_connecta',
                'is_system': False,
                'active': True,
            })
        self.addCleanup(probes.unlink)
        q2, _s2 = count_gen()
        delta = q2 - q1
        print('B02_QUERY_SCALE base=%s double=%s delta=%s n=%s' % (q1, q2, delta, n_base))
        self.assertLessEqual(delta, 25)
        self.assertLess(delta, n_base)
