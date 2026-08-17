# -*- coding: utf-8 -*-
"""W11 — B09 thuyết minh: khung + số từ bản B01a/B02 đã lập."""
import json

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged, TransactionCase
from odoo.tools.float_utils import float_compare, float_round

from odoo.addons.connecta_vas.models.res_company import (
    W11_BCTC_A28_ADVANCE,
    W11_BCTC_A28_CIP,
    W11_BCTC_A28_DEPOSIT,
    W11_BCTC_A28_INTANG,
    W11_BCTC_A28_INTANG_DEP,
    W11_BCTC_A28_PAY_INT,
    W11_BCTC_A28_RECV_INT,
    W11_BCTC_A28_REV_5111,
    W11_BCTC_A28_WARRANTY,
    W11_BCTC_CIT_AMOUNT,
    W11_BCTC_EXPECT_ADMIN,
    W11_BCTC_EXPECT_CASH,
    W11_BCTC_EXPECT_REV01,
    W11_BCTC_FINANCE_INCOME,
    W11_BCTC_LOAN_INTEREST,
    W11_BCTC_NON_INTEREST_635,
    W11_BCTC_OPENING_CASH_111,
    W11_BCTC_OPENING_CASH_112,
    W11_BCTC_OTHER_EXPENSE,
    W11_BCTC_OTHER_INCOME,
)

# 28 dòng loại (A) — đo số sau seed A28
B09_A28_CODES = (
    'V.2b.deposit', 'V.2b.other', 'V.3c.advance', 'V.3c.internal', 'V.3c.other',
    'V.5.tangible.cost', 'V.5.tangible.accum', 'V.5.tangible.net',
    'V.5.intangible.cost', 'V.5.intangible.accum', 'V.5.intangible.net',
    'V.5.lease.cost', 'V.5.lease.accum', 'V.5.lease.net',
    'V.7.buy', 'V.7.cip', 'V.7.repair', 'V.8.tax_recv',
    'V.9c.internal', 'V.9c.other', 'V.11.lease',
    'V.12.warranty', 'V.12.construction', 'V.12.other',
    'VI.1a.goods', 'VI.1a.fg', 'VI.1a.svc', 'VI.1a.other',
)
from odoo.addons.connecta_vas.tests.common_vas_query_count import VasQueryCounter

# Chỉ tiêu B09 lấy thẳng từ B01a / B02 (Cộng / dòng khớp mã)
B09_FROM_B01A = {
    'V.1.total': '110',
    'V.2a.total': '121',
    'V.2b.total': '122',
    'V.2c.total': '124',
    'V.3a.total': '131',
    'V.3b.total': '132',
    'V.3c.total': '134',
    'V.3d.total': '135',
    'V.4.total': '141',
    'V.7.total': '170',
    'V.9a.total': '311',
    'V.9b.total': '312',
    'V.9c.total': '315',
    'V.11.total': '316',
    'V.12.total': '318',
}
B09_FROM_B02 = {
    'VI.1a.total': '01',
    'VI.2.total': '02',
    'VI.3.total': '11',
    'VI.4.total': '21',
    'VI.5.loan': '23',
    'VI.5.total': '22',
    'VI.6.total': '24',
    'VI.7.total': '31',
    'VI.8.total': '32',
    'VI.9.total': '51',
}


@tagged('post_install', '-at_install', 'connecta_vas', 'connecta_vas_w11')
class TestW11B09Seed(TransactionCase):

    def test_01_structure_and_custom_keys(self):
        regime = self.env.ref('connecta_vas.vas_regime_tt133')
        lines = self.env['vas.report.line'].search([
            ('form_code', '=', 'B09-DNN'),
            ('regime_id', '=', regime.id),
            ('active', '=', True),
        ])
        by = {l.code: l for l in lines}
        self.assertGreaterEqual(len(by), 180, len(by))
        # Phần / bảng ổn định
        for code in ('I', 'II', 'III', 'IV', 'V', 'V.1', 'V.5', 'VI', 'VI.5', 'VII', 'VIII'):
            self.assertIn(code, by, code)
            self.assertEqual(by[code].amount_source, 'code_custom')
        for b09, src in B09_FROM_B01A.items():
            self.assertEqual(by[b09].code_custom_key, 'b09_from_b01a:%s' % src, b09)
        for b09, src in B09_FROM_B02.items():
            self.assertEqual(by[b09].code_custom_key, 'b09_from_b02:%s' % src, b09)
        # Ô chưa lấy được số: unavailable; loại A đã nối ledger/movement
        self.assertEqual(
            by['V.5.tangible.cost'].code_custom_key, 'b09_from_movement:cost',
        )
        self.assertEqual(by['V.5.tangible.cost'].account_codes, '2111')
        self.assertEqual(by['V.2b.deposit'].code_custom_key, 'b09_from_ledger')
        self.assertEqual(by['V.2b.deposit'].account_codes, '1281')
        self.assertEqual(by['V.3đ.total'].code_custom_key, 'b09_unavailable')
        self.assertEqual(by['V.1.cash'].code_custom_key, 'b09_from_ledger')
        self.assertEqual(by['V.1.cash'].account_codes, '111')
        self.assertEqual(by['II.1'].code_custom_key, 'b09_from_text:fiscalyear')
        self.assertEqual(by['VII.1'].b09_fill_kind, 'manual')
        self.assertFalse(by['VII.1'].b09_gap_reason)
        self.assertEqual(by['VII'].b09_table_status, 'manual_all')
        self.assertIn('V.6.cost', by)
        self.assertNotIn('V.3e', by)
        self.assertNotIn('V.3e.total', by)
        self.assertIn('V.14đ', by)
        self.assertNotIn('V.14e', by)
        # Mọi dòng (kể cả mục) đều có phân loại; bảng có trạng thái
        blank_kind = [c for c, l in by.items() if not l.b09_fill_kind]
        self.assertFalse(blank_kind, blank_kind[:20])
        from odoo.addons.connecta_vas.models.vas_b09_meta import TABLE_STATUS
        blank_st = [
            code for code in TABLE_STATUS
            if code in by and not by[code].b09_table_status
        ]
        self.assertFalse(blank_st, blank_st)
        gaps = [
            c for c, l in by.items()
            if l.b09_fill_kind == 'machine_gap' and not l.b09_gap_reason
        ]
        self.assertFalse(gaps, gaps[:10])
        print('B09_SEED_N', len(by))
        print('B09_FILL_COUNTS', {
            k: sum(1 for l in by.values() if l.b09_fill_kind == k)
            for k in (
                'section', 'machine_now', 'machine_gap', 'manual', 'na',
            )
        })


@tagged('post_install', '-at_install', 'connecta_vas', 'connecta_vas_w11')
class TestW11B09Snapshot(TransactionCase):

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

    def _ensure_sources(self, company, p01, p12):
        Snap = self.env['vas.report.snapshot']
        b01a = Snap.generate_b01a(company, p01, p12, hide_reversed=True)
        b02 = Snap.generate_b02(company, p01, p12, hide_reversed=True)
        return b01a, b02

    def test_01_w11_numbers_from_b01a_b02(self):
        self.env['res.company']._vas_w11_ensure_bctc_demo()
        company = self.env['res.company'].search(
            [('name', '=', 'W11-Thử BCTC')], limit=1,
        )
        p01, p12 = self._periods(company)
        b01a, b02 = self._ensure_sources(company, p01, p12)
        b01 = {l.code: l for l in b01a.line_ids}
        b02m = {l.code: l for l in b02.line_ids}

        snap = self.env['vas.report.snapshot'].generate_b09(
            company, p01, p12, hide_reversed=True,
        )
        by = {l.code: l for l in snap.line_ids}
        print('B09_W11_FROM_B01A', {
            k: (by[k].amount_opening, by[k].amount_closing)
            for k in B09_FROM_B01A
        })
        print('B09_W11_FROM_B02', {
            k: by[k].amount_closing for k in B09_FROM_B02
        })
        print('B09_W11_WARN_HEAD', (snap.warning_text or '')[:500])

        for b09, src in B09_FROM_B01A.items():
            self.assertFalse(by[b09].is_na_closing, b09)
            self.assertEqual(
                float_compare(by[b09].amount_closing, b01[src].amount_closing, 2), 0,
                '%s vs B01a %s' % (b09, src),
            )
            self.assertEqual(
                float_compare(by[b09].amount_opening, b01[src].amount_opening, 2), 0,
                '%s opening vs B01a %s' % (b09, src),
            )
        for b09, src in B09_FROM_B02.items():
            self.assertFalse(by[b09].is_na_closing, b09)
            self.assertTrue(by[b09].is_na_opening, b09)
            self.assertEqual(
                float_compare(by[b09].amount_closing, b02m[src].amount_closing, 2), 0,
                '%s vs B02 %s' % (b09, src),
            )

        # Spot W11 known B02 figures (+ A28 DT 5111)
        self.assertEqual(
            float_compare(by['VI.1a.total'].amount_closing, W11_BCTC_EXPECT_REV01, 2), 0,
        )
        self.assertEqual(
            float_compare(by['VI.5.loan'].amount_closing, W11_BCTC_LOAN_INTEREST, 2), 0,
        )
        self.assertEqual(
            float_compare(
                by['VI.5.total'].amount_closing,
                -(W11_BCTC_LOAN_INTEREST + W11_BCTC_NON_INTEREST_635),
                2,
            ),
            0,
        )
        self.assertEqual(
            float_compare(by['VI.4.total'].amount_closing, W11_BCTC_FINANCE_INCOME, 2), 0,
        )
        self.assertEqual(
            float_compare(by['VI.7.total'].amount_closing, W11_BCTC_OTHER_INCOME, 2), 0,
        )
        self.assertEqual(
            float_compare(by['VI.8.total'].amount_closing, -W11_BCTC_OTHER_EXPENSE, 2), 0,
        )
        self.assertEqual(
            float_compare(by['VI.9.total'].amount_closing, -W11_BCTC_CIT_AMOUNT, 2), 0,
        )

        # Gap còn N/A; loại A + V.5 đã nối
        self.assertTrue(by['V.3đ.total'].is_na_closing)
        self.assertFalse(by['V.5.tangible.cost'].is_na_closing)
        self.assertFalse(by['V.5.tangible.cost'].is_na_opening)
        self.assertFalse(by['V.5.tangible.cost'].is_na_increase)
        self.assertEqual(
            float_compare(by['V.5.tangible.cost'].amount_closing, 100_000_000, 2), 0,
            by['V.5.tangible.cost'].amount_closing,
        )
        self.assertEqual(
            float_compare(by['V.5.tangible.cost'].amount_increase, 100_000_000, 2), 0,
        )
        self.assertEqual(
            float_compare(by['V.5.tangible.accum'].amount_closing, 10_000_000, 2), 0,
        )
        self.assertEqual(
            float_compare(by['V.5.tangible.net'].amount_closing, 90_000_000, 2), 0,
        )
        # đầu + tăng − giảm = cuối
        for code in (
            'V.5.tangible.cost', 'V.5.tangible.accum', 'V.5.tangible.net',
        ):
            row = by[code]
            bal = float_round(
                row.amount_opening + row.amount_increase - row.amount_decrease, 2,
            )
            self.assertEqual(
                float_compare(bal, row.amount_closing, 2), 0, code,
            )
        self.assertEqual(
            float_compare(
                by['V.5.tangible.net'].amount_closing,
                by['V.5.tangible.cost'].amount_closing
                - by['V.5.tangible.accum'].amount_closing,
                2,
            ),
            0,
        )
        self.assertFalse(by['V.2b.deposit'].is_na_closing)
        self.assertFalse(by['V.7.buy'].is_na_closing)
        self.assertFalse(by['VI.1a.goods'].is_na_closing)
        # A28: DT HH trên 5111 song song DT trên 511 cha
        self.assertEqual(
            float_compare(by['VI.1a.goods'].amount_closing, W11_BCTC_A28_REV_5111, 2), 0,
            by['VI.1a.goods'].amount_closing,
        )
        self.assertFalse(by['V.1.cash'].is_na_closing)
        # V.1.cash = 111; V.1.bank = 112; tổng tiền = B01a 110
        cash_bank = float_round(
            by['V.1.cash'].amount_closing + by['V.1.bank'].amount_closing, 2,
        )
        self.assertEqual(
            float_compare(cash_bank, W11_BCTC_EXPECT_CASH, 2), 0,
            'cash=%s bank=%s' % (
                by['V.1.cash'].amount_closing, by['V.1.bank'].amount_closing,
            ),
        )
        self.assertEqual(
            float_compare(by['V.1.total'].amount_closing, W11_BCTC_EXPECT_CASH, 2), 0,
            by['V.1.total'].amount_closing,
        )
        self.assertEqual(
            float_compare(by['V.1.cash'].amount_opening, W11_BCTC_OPENING_CASH_111, 2), 0,
            by['V.1.cash'].amount_opening,
        )
        self.assertEqual(
            float_compare(by['V.1.bank'].amount_opening, W11_BCTC_OPENING_CASH_112, 2), 0,
            by['V.1.bank'].amount_opening,
        )
        self.assertEqual(by['V.5'].b09_table_status, 'full')
        self.assertFalse(by['V.1.bank'].is_na_closing)
        self.assertFalse(by['V.4.merch'].is_na_closing)
        self.assertEqual(
            float_compare(by['V.4.merch'].amount_closing, 10_000_000, 2), 0,
        )
        self.assertFalse(by['V.9c.accrued'].is_na_closing)
        # W11 B03-3: đã trả lãi vay tiền mặt → 335 về 0 (trước đó 1M lãi chưa trả)
        self.assertEqual(
            float_compare(by['V.9c.accrued'].amount_closing, 0.0, 2), 0,
            by['V.9c.accrued'].amount_closing,
        )
        # VI.6 chi tiết từ sổ (đối ứng 642↔911), dấu âm như B02
        self.assertFalse(by['VI.6.selling'].is_na_closing)
        self.assertFalse(by['VI.6.admin'].is_na_closing)
        self.assertEqual(
            float_compare(by['VI.6.selling'].amount_closing, -5_000_000, 2), 0,
        )
        self.assertEqual(
            float_compare(by['VI.6.admin'].amount_closing, -W11_BCTC_EXPECT_ADMIN, 2), 0,
        )
        self.assertEqual(
            float_compare(
                by['VI.6.selling'].amount_closing + by['VI.6.admin'].amount_closing,
                by['VI.6.total'].amount_closing,
                2,
            ),
            0,
        )
        # A28 — các dòng loại (A) đã có nghiệp vụ
        self.assertEqual(
            float_compare(by['V.2b.deposit'].amount_closing, W11_BCTC_A28_DEPOSIT, 2), 0,
        )
        self.assertEqual(
            float_compare(by['V.3c.advance'].amount_closing, W11_BCTC_A28_ADVANCE, 2), 0,
        )
        self.assertEqual(
            float_compare(by['V.3c.internal'].amount_closing, W11_BCTC_A28_RECV_INT, 2), 0,
        )
        self.assertEqual(
            float_compare(by['V.9c.internal'].amount_closing, W11_BCTC_A28_PAY_INT, 2), 0,
        )
        self.assertEqual(
            float_compare(by['V.5.intangible.cost'].amount_closing, W11_BCTC_A28_INTANG, 2), 0,
        )
        self.assertEqual(
            float_compare(
                by['V.5.intangible.accum'].amount_closing, W11_BCTC_A28_INTANG_DEP, 2,
            ), 0,
        )
        self.assertEqual(
            float_compare(by['V.7.cip'].amount_closing, W11_BCTC_A28_CIP, 2), 0,
        )
        self.assertEqual(
            float_compare(by['V.12.warranty'].amount_closing, W11_BCTC_A28_WARRANTY, 2), 0,
        )
        # Text II
        self.assertTrue(by['II.1'].b09_text_value)
        self.assertIn('2026', by['II.1'].b09_text_value)
        self.assertEqual(by['II.2'].b09_text_value, 'VND')
        # Phân loại / trạng thái copy sang bản đã lập
        self.assertEqual(by['V.3đ.total'].b09_fill_kind, 'machine_gap')
        self.assertTrue(by['V.3đ.total'].b09_gap_reason)
        self.assertEqual(by['V.3đ'].b09_table_status, 'none_yet')
        self.assertEqual(by['V.1'].b09_table_status, 'total_ok_detail_open')
        self.assertEqual(by['V.2c'].b09_table_status, 'full')
        self.assertEqual(by['II'].b09_table_status, 'full')
        self.assertEqual(by['I'].b09_table_status, 'manual_all')
        warn = snap.warning_text or ''
        self.assertIn('B09 —', warn)
        self.assertNotIn('BẢNG THIẾU CHI TIẾT:', warn)
        self.assertNotRegex(warn, r'V\.3a,\s*V\.3b')
        # Lưới tự kiểm: VI.1a chi tiết (511x) ≠ tổng B02 (còn DT trên 511 cha)
        self.assertIn('LƯỚI B09', warn)
        self.assertIn('VI.1a.total', warn)
        meta = json.loads(snap.meta_json)
        self.assertTrue(meta.get('b09_table_status_counts'))
        self.assertFalse(meta.get('partial_tables'))
        self.assertEqual(meta['source_b01a_snapshot_id'], b01a.id)
        self.assertEqual(meta['source_b02_snapshot_id'], b02.id)
        self.assertTrue(meta.get('b09_source_grid'))
        self.assertTrue(meta.get('b09_detail_sum_checks'))
        self.assertFalse(
            any(r.get('missing_source') for r in meta['b09_source_grid']),
        )
        a28_amt = {c: by[c].amount_closing for c in B09_A28_CODES}
        print('B09_A28', a28_amt)
        blank = [l.code for l in snap.line_ids if not l.b09_fill_kind]
        self.assertFalse(blank, blank[:20])
        # machine_now số/text đều đã điền (không còn N/A trống)
        for code, line in by.items():
            if line.b09_fill_kind != 'machine_now':
                continue
            if line.b09_text_value:
                continue
            if code.startswith('II.'):
                self.fail('%s machine_now thiếu text' % code)
            self.assertFalse(
                line.is_na_closing,
                '%s machine_now vẫn N/A' % code,
            )

    def test_02_requires_b01a_b02_no_silent_zero(self):
        regime = self.env.ref('connecta_vas.vas_regime_tt133')
        vnd = self.env.ref('base.VND')
        company = self.env['res.company'].create({
            'name': 'W11-B09 Missing Sources',
            'currency_id': vnd.id,
            'vas_regime_id': regime.id,
            'vas_start_date': '2094-01-01',
        })
        self.env['vas.journal']._ensure_journals_for_company(company)
        fy = self.env['vas.fiscalyear'].create({
            'name': '2094', 'date_from': '2094-01-01', 'date_to': '2094-12-31',
            'state': 'open', 'company_id': company.id,
        })
        p01 = self.env['vas.period'].create({
            'name': '01/2094', 'date_start': '2094-01-01', 'date_end': '2094-01-31',
            'fiscalyear_id': fy.id, 'state': 'open',
        })
        p12 = self.env['vas.period'].create({
            'name': '12/2094', 'date_start': '2094-12-01', 'date_end': '2094-12-31',
            'fiscalyear_id': fy.id, 'state': 'open',
        })
        with self.assertRaises(UserError) as err:
            self.env['vas.report.snapshot'].generate_b09(
                company, p01, p12, hide_reversed=True,
            )
        msg = err.exception.args[0]
        self.assertIn('B01a', msg)
        self.assertIn('B02', msg)
        self.assertIn('không tự lập ngầm', msg)

        # Chỉ có B01a — vẫn chặn
        self.env['vas.report.snapshot'].generate_b01a(
            company, p01, p12, hide_reversed=True,
        )
        with self.assertRaises(UserError) as err2:
            self.env['vas.report.snapshot'].generate_b09(
                company, p01, p12, hide_reversed=True,
            )
        self.assertIn('B02', err2.exception.args[0])
        self.assertEqual(
            self.env['vas.report.snapshot'].search_count([
                ('form_code', '=', 'B09-DNN'),
                ('company_id', '=', company.id),
            ]),
            0,
        )

    def test_03_stale_source_warns(self):
        from datetime import timedelta

        self.env['res.company']._vas_w11_ensure_bctc_demo()
        company = self.env['res.company'].search(
            [('name', '=', 'W11-Thử BCTC')], limit=1,
        )
        p01, p12 = self._periods(company)
        # Xóa bản cũ trên DB sống để _find_period_snapshot bắt đúng bản vừa lập
        self.env['vas.report.snapshot'].search([
            ('company_id', '=', company.id),
            ('period_from_id', '=', p01.id),
            ('period_to_id', '=', p12.id),
            ('form_code', 'in', ('B01a-DNN', 'B02-DNN', 'B09-DNN')),
        ]).unlink()
        b01a, b02 = self._ensure_sources(company, p01, p12)
        # Lùi thời điểm lập nguồn để create_date chứng từ mới chắc chắn >
        # date_computed (so sánh giây — cùng giây sẽ bỏ sót).
        past = fields.Datetime.now() - timedelta(minutes=5)
        b01a.write({'date_computed': past})
        b02.write({'date_computed': past})

        journal = self.env['vas.journal'].search([
            ('company_id', '=', company.id), ('code', '=', 'TH'),
        ], limit=1)
        acc111 = self.env.ref('connecta_vas.vas_account_tt133_111')
        acc411 = self.env.ref('connecta_vas.vas_account_tt133_4111')
        move = self.env['vas.move'].create({
            'company_id': company.id,
            'journal_id': journal.id,
            'date': '2026-06-15',
            'move_kind': 'manual',
            'line_ids': [
                (0, 0, {
                    'account_id': acc111.id, 'name': 'B09 stale',
                    'debit': 1_000, 'credit': 0,
                }),
                (0, 0, {
                    'account_id': acc411.id, 'name': 'B09 stale',
                    'debit': 0, 'credit': 1_000,
                }),
            ],
        })
        move.action_post()

        snap = self.env['vas.report.snapshot'].generate_b09(
            company, p01, p12, hide_reversed=True,
        )
        warn = snap.warning_text or ''
        self.assertTrue(warn)
        self.assertTrue(
            'B01a' in warn or 'B02' in warn,
            warn[:400],
        )
        meta = json.loads(snap.meta_json)
        self.assertTrue(
            meta.get('source_b01a_ledger_changed')
            or meta.get('source_b02_ledger_changed'),
            meta,
        )

    def test_04_reopen_does_not_recompute(self):
        self.env['res.company']._vas_w11_ensure_bctc_demo()
        company = self.env['res.company'].search(
            [('name', '=', 'W11-Thử BCTC')], limit=1,
        )
        p01, p12 = self._periods(company)
        self._ensure_sources(company, p01, p12)
        snap = self.env['vas.report.snapshot'].generate_b09(
            company, p01, p12, hide_reversed=True,
        )
        before = {
            l.code: (l.amount_closing, l.is_na_closing)
            for l in snap.line_ids
        }
        data = self.env['vas.b09.wizard'].get_report_data({
            'snapshot_id': snap.id,
        })
        self.assertTrue(data['meta']['from_snapshot'])
        self.assertEqual(data['meta']['snapshot_id'], snap.id)
        after = {
            l.code: (l.amount_closing, l.is_na_closing)
            for l in snap.line_ids
        }
        self.assertEqual(before, after)

    def test_05_query_count_not_linear_in_indicators(self):
        self.env['res.company']._vas_w11_ensure_bctc_demo()
        company = self.env['res.company'].search(
            [('name', '=', 'W11-Thử BCTC')], limit=1,
        )
        p01, p12 = self._periods(company)
        self._ensure_sources(company, p01, p12)
        Snap = self.env['vas.report.snapshot']
        regime = company.vas_regime_id

        def count_gen():
            self.env.flush_all()
            with VasQueryCounter(self.env.cr) as qc:
                snap = Snap.generate_b09(company, p01, p12, hide_reversed=True)
                self.env.flush_all()
            return qc.count, snap

        count_gen()  # warm-up
        q_base, snap_base = count_gen()
        n_base = self.env['vas.report.line'].search_count([
            ('form_code', '=', 'B09-DNN'),
            ('regime_id', '=', regime.id),
            ('active', '=', True),
        ])
        self.assertEqual(len(snap_base.line_ids), n_base)
        self.assertGreaterEqual(n_base, 100)

        probes = self.env['vas.report.line']
        for i in range(n_base):
            probes |= self.env['vas.report.line'].create({
                'sequence': 90000 + i,
                'code': 'ZB09%03d' % i,
                'name': 'B09 probe %s' % i,
                'form_code': 'B09-DNN',
                'regime_id': regime.id,
                'line_role': 'detail',
                'amount_source': 'code_custom',
                'code_custom_key': 'b09_unavailable',
                'basis_kind': 'chot_connecta',
                'is_system': False,
                'active': True,
            })
        self.addCleanup(probes.unlink)

        q_double, snap_double = count_gen()
        self.assertEqual(len(snap_double.line_ids), n_base * 2)
        delta = q_double - q_base
        max_delta = 25
        print(
            'B09_QUERY_SCALE base=%s double=%s delta=%s n_base=%s'
            % (q_base, q_double, delta, n_base)
        )
        self.assertLessEqual(delta, max_delta)
        self.assertLess(delta, n_base)
        self.assertEqual(
            delta, 0,
            'B09 phải cố định số câu SQL khi nhân đôi chỉ tiêu (ORM INSERT_BATCH '
            '100 đã bị thay bằng 1 INSERT). delta=%s base=%s double=%s'
            % (delta, q_base, q_double),
        )


@tagged('post_install', '-at_install', 'connecta_vas', 'connecta_vas_w11')
class TestW11B09FaDecreaseWarn(TransactionCase):
    """Cột giảm TSCĐ có số → cảnh báo chưa phân tích nguyên nhân TL."""

    def test_01_decrease_warns(self):
        regime = self.env.ref('connecta_vas.vas_regime_tt133')
        vnd = self.env.ref('base.VND')
        company = self.env['res.company'].create({
            'name': 'W11-B09 FA Decrease',
            'currency_id': vnd.id,
            'vas_regime_id': regime.id,
            'vas_start_date': '2095-01-01',
        })
        self.env['vas.journal']._ensure_journals_for_company(company)
        fy = self.env['vas.fiscalyear'].create({
            'name': '2095', 'date_from': '2095-01-01', 'date_to': '2095-12-31',
            'state': 'open', 'company_id': company.id,
        })
        p01 = self.env['vas.period'].create({
            'name': '01/2095', 'date_start': '2095-01-01', 'date_end': '2095-01-31',
            'fiscalyear_id': fy.id, 'state': 'open',
        })
        p12 = self.env['vas.period'].create({
            'name': '12/2095', 'date_start': '2095-12-01', 'date_end': '2095-12-31',
            'fiscalyear_id': fy.id, 'state': 'open',
        })
        journal = self.env['vas.journal'].search([
            ('company_id', '=', company.id), ('code', '=', 'TH'),
        ], limit=1)
        acc111 = self.env.ref('connecta_vas.vas_account_tt133_111')
        acc2111 = self.env.ref('connecta_vas.vas_account_tt133_2111')
        acc411 = self.env.ref('connecta_vas.vas_account_tt133_4111')
        # Góp vốn + mua TS + ghi giảm nguyên giá (giả lập giảm chưa có TL)
        for day, lines, name in [
            ('2095-01-05', [
                (acc111, 50_000_000, 0), (acc411, 0, 50_000_000),
            ], 'vốn'),
            ('2095-02-01', [
                (acc2111, 20_000_000, 0), (acc111, 0, 20_000_000),
            ], 'mua TS'),
            ('2095-06-01', [
                (acc111, 5_000_000, 0), (acc2111, 0, 5_000_000),
            ], 'giảm NG'),
        ]:
            self.env['vas.move'].create({
                'company_id': company.id,
                'journal_id': journal.id,
                'date': day,
                'move_kind': 'manual',
                'line_ids': [
                    (0, 0, {
                        'account_id': a.id, 'name': name,
                        'debit': d, 'credit': c,
                    }) for a, d, c in lines
                ],
            }).action_post()
        # Nguồn B01a/B02 tối thiểu
        self.env['vas.report.snapshot'].generate_b01a(
            company, p01, p12, hide_reversed=True,
        )
        self.env['vas.report.snapshot'].generate_b02(
            company, p01, p12, hide_reversed=True,
        )
        snap = self.env['vas.report.snapshot'].generate_b09(
            company, p01, p12, hide_reversed=True,
        )
        by = {l.code: l for l in snap.line_ids}
        self.assertEqual(
            float_compare(by['V.5.tangible.cost'].amount_decrease, 5_000_000, 2), 0,
        )
        warn = snap.warning_text or ''
        self.assertIn('giảm', warn.lower())
        self.assertIn('thanh lý', warn.lower())
        self.assertIn('V.5.tangible.cost', warn)


@tagged('post_install', '-at_install', 'connecta_vas', 'connecta_vas_w11')
class TestW11B09CodeRename(TransactionCase):

    def test_01_v3d_and_v14d_codes(self):
        """Mã mẫu in dùng chữ đ — bản ghi / xmlid không còn ASCII e."""
        regime = self.env.ref('connecta_vas.vas_regime_tt133')
        Line = self.env['vas.report.line']
        self.assertTrue(
            Line.search([
                ('form_code', '=', 'B09-DNN'),
                ('regime_id', '=', regime.id),
                ('code', '=', 'V.3đ'),
            ], limit=1),
        )
        self.assertFalse(
            Line.search([
                ('form_code', '=', 'B09-DNN'),
                ('regime_id', '=', regime.id),
                ('code', 'in', ('V.3e', 'V.3e.total', 'V.14e')),
            ]),
        )
        self.env.ref('connecta_vas.vas_report_line_b09_V_3đ')
        self.env.ref('connecta_vas.vas_report_line_b09_V_3đ_total')
        self.env.ref('connecta_vas.vas_report_line_b09_V_14đ')
